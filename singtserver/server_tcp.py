import json
import struct

from twisted.internet import defer
from twisted.internet import protocol

from singtcommon import TCPPacketizer

# Start a logger with a namespace for a particular subsystem of our application.
from twisted.logger import Logger
log = Logger("server_tcp")


# An instance of this class is created for each client connection.
class TCPServer(protocol.Protocol):
    def __init__(self, shared_context):
        super()
        self._tcp_packetizer = None

        self._shared_context = shared_context
        self.username = None
        self.client_id = None

        self._commands = {}
        self._register_commands()
        
    def _register_commands(self):
        self.register_command("announce", self._command_announce)
        self.register_command("update_downloaded", self._command_update_downloaded)

    def register_command(self, command, function):
        self._commands[command] = function
        
    def connectionMade(self):
        self._tcp_packetizer = TCPPacketizer(self.transport)
        
    def send_file(self, filename):
        f = open(filename, "rb")

        # Get size of file.  See
        # https://stackoverflow.com/questions/33683848/python-2-7-get-the-size-of-a-file-just-from-its-handle-and-not-its-path
        file_size = os.fstat(f.fileno()).st_size

        # Send the number of bytes in the file
        file_size_as_bytes = struct.pack("I", file_size)
        self.transport.write(file_size_as_bytes)

        # Send the file in parts so that we don't block the reactor
        bytes_read = 0
        def send_file_in_parts(num_bytes):
            nonlocal bytes_read
            while True:
                data = f.read(num_bytes)
                if len(data) == 0:
                    # We've come to the end of the file
                    break
                bytes_read += len(data)
                self.transport.write(data)
                yield bytes_read

        cooperative_task = task.cooperate(send_file_in_parts(1000))

        return cooperative_task.whenDone()

    
    # The message is complete and should not contain any extra data
    def process(self, msg):
        # Parse JSON message
        try:
            json_data = json.loads(msg)
        except Exception as e:
            raise Exception(f"Failed to parse message ({msg}) as JSON: "+str(e))

        # Get command
        try:
            command = json_data["command"]
        except KeyError:
            raise Exception(f"Failed to find 'command' key in message ({msg})")

        # Get function
        try:
            function = self._commands[command]
        except KeyError:
            raise Exception(f"No function was registered against the command '{command}'")

        # Execute function
        try:
            function(json_data)
        except Exception as e:
            log.warn(f"Exception during execution of function for command '{command}': "+str(e))
            raise
        
    # Data received may be a partial package, or it may be multiple
    # packets joined together.
    def dataReceived(self, data):
        packets = self._tcp_packetizer.decode(data)

        for packet in packets:
            print("packet decoded:", packet)
            self.process(packet)

            
    def connectionLost(self, reason):
        log.info(f"Connection lost to user '{self.username}': {reason}")
        self._shared_context.participants.leave(self.client_id)

    def send_message(self, msg):
        msg_as_bytes = msg.encode("utf-8")
        len_as_short = struct.pack("H", len(msg))
        encoded_msg = len_as_short + msg_as_bytes
        self.transport.write(encoded_msg)

    def send_download_request(self, audio_id, partial_url):
        command = {
            "command": "download",
            "audio_id": audio_id,
            "partial_url": str(partial_url)
        }
        command_json = json.dumps(command)
        self.send_message(command_json)

    def send_record_request(self, audio_ids, recording_audio_id):
        command = {
            "command": "record",
            "backing_audio_ids": audio_ids,
            "recording_audio_id": recording_audio_id
        }
        command_json = json.dumps(command)
        self.send_message(command_json)

    def _command_announce(self, json_data):
        """Announce client's username.

        Announces username, which is then stored in the shared context
        along with the client's ID.  

        Also causes the current invitation to be sent to the client.

        """

        # Extract the username
        print("json_data:",json_data)
        self.username = json_data["username"]
        self.client_id = int(json_data["client_id"])

        # Store and announce the client
        self._shared_context.participants.join(
            self.client_id,
            self.username
        )

        # Send the client the current invitation from the shared
        # context
        # TODO
        

    def _command_update_downloaded(self, json_data):
        print("In _command_update_downloaded, with json_data: ", json_data)
        client_id = self.client_id
        audio_id = json_data["audio_id"]
        result = json_data["result"]

        # Get the deferred that's waiting on this update
        d = self._shared_context._download_results_collector.get_deferred(
            client_id,
            audio_id
        )

        # Call the appropriate callback
        if result=="success":
            print("Calling success callback")
            d.callback((client_id, audio_id))
        else:
            print("Calling error callback")
            d.errback((client_id, audio_id, json_data["error"]))

        # Remove the deferred from the collector
        self._shared_context._download_results_collector.remove_deferred(
            client_id,
            audio_id
        )

        return d
            
 
class TCPServerFactory(protocol.Factory):
    class SharedContext:
        def __init__(self, context):
            self.eventsource = context["web_server"].eventsource_resource
            self.participants = Participants(context)
            self._download_results_collector = DownloadResultsCollector()
            self.current_invitation = None
            
    def __init__(self, context):
        self._context = context
        web_server = self._context["web_server"]
        
        # Create a list of protocol instances, used for broadcasting
        # to all clients
        self._protocols = []

        # TODO: Is this really the best way to implement this?
        backing_track_resource = web_server.backing_track_resource
        self._shared_context = TCPServerFactory.SharedContext(context)
        self._shared_context.eventsource.add_initialiser(
            backing_track_resource.initialise_eventsource
        )
    
    def buildProtocol(self, addr):
        protocol = TCPServer(self._shared_context)
        self._protocols.append(protocol)
        return protocol

    def startFactory(self):
        log.info("TCPServerFactory started")

    def broadcast_download_request(self, audio_id, partial_url, participants):
        deferreds = []
        for protocol in self._protocols:
            if protocol.client_id in participants:
                protocol.send_download_request(audio_id, partial_url)
                d = self._shared_context._download_results_collector.make_deferred(protocol.client_id, audio_id)
                deferreds.append(d)
                
        d = defer.gatherResults(deferreds)
            
        return d

    def broadcast_record_request(self, backing_audio_ids, recording_audio_ids, participants):
        """Request clients start recording.

        backing_audio_ids is a list of audio ids that specify the
        audio that should be played as the backing audio.  This may be
        a combination of audio ids for tracks and takes.

        recording_audio_ids is a dictionary of audio_ids, keyed by
        client_id.  The audio_id is for the client's recording.  They
        will use this ID to identify the file they send back.

        participants is a list of client_ids; it specifies which
        clients will be asked to record.

        The method returns a deferred once all clients have finished
        sending their recordings, or an error has occurred.

        """
        deferreds = []
        for protocol in self._protocols:
            if protocol.client_id in participants:
                recording_audio_id = recording_audio_ids[protocol.client_id]
                protocol.send_record_request(backing_audio_ids, recording_audio_id)
                #d = self._shared_context._download_results_collector.make_deferred(protocol.client_id, audio_id)
                #deferreds.append(d)
                
        d = defer.gatherResults(deferreds)
        return d
    

class Participants:
    def __init__(self, context):
        self._context = context
        self._db = context["database"]
        self._eventsource = context["web_server"].eventsource_resource
        self._connected_participants = {}

        self._eventsource.add_initialiser(self.eventsource_initialiser)


    def join(self, client_id, name):
        """Assigns name to client_id, overwriting if it exists already.

        Broadcasts new client on eventsource.

        """
        d = self._db.assign_participant(client_id, name)

        def on_success(client_id):
            self._connected_participants[client_id] = name
            self.eventsource_broadcast()
        d.addCallback(on_success)
        return d

    
    def leave(self, client_id):
        print(self._connected_participants)
        try:
            del self._connected_participants[client_id]
            self.eventsource_broadcast()
        except KeyError:
            log.warn(f"Failed to find participant with client id {client_id}; could not remove from participants list")

    
    def get_list(self):
        """Returns list of currently connected participants.

        Converts the client id to a string, as Javascript's unable to
        handle ints larger than 53-bits.

        """
        connected_list = [
            {"id":str(id_), "name":name}
            for id_, name in self._connected_participants.items()
        ]
        return json.dumps(connected_list)
        

    def eventsource_initialiser(self):
        d = defer.Deferred()
        d.callback(
            ("update_participants",
             self.get_list())
        )
        return d

    
    def eventsource_broadcast(self):
        connected_list = self.get_list()
        self._eventsource.publish_to_all(
            "update_participants",
            connected_list
        )



class DownloadResultsCollector:
    def __init__(self):
        # A dict of dicts.  This is referenced by client_id.  The
        # resulting dict is referenced by audio_id.
        self._deferreds_by_client_id = {}
        
    def make_deferred(self, client_id, audio_id):
        """Makes a deferred if it doesn't already exist."""
        # Get dict of deferreds for the given client id
        try:
            deferreds_by_audio_id = self._deferreds_by_client_id[client_id]
        except KeyError:
            # Client ID doesn't yet have any deferreds, create a dict
            deferreds_by_audio_id = {}
            self._deferreds_by_client_id[client_id] = deferreds_by_audio_id

        # Get deferred for the given audio_id
        try:
            deferred = deferreds_by_audio_id[audio_id]
        except KeyError:
            deferred = defer.Deferred()
            deferreds_by_audio_id[audio_id] = deferred

        return deferred

    def get_deferred(self, client_id, audio_id):
        """Gets a deferred."""
        deferreds_by_audio_id = self._deferreds_by_client_id[client_id]
        print("deferreds_by_audio_id:", deferreds_by_audio_id)
        deferred = deferreds_by_audio_id[audio_id]
        return deferred
        
    def remove_deferred(self, client_id, audio_id):
        """Removes a deferred."""
        deferreds_by_audio_id = self._deferreds_by_client_id[client_id]
        del deferreds_by_audio_id[audio_id]

        if len(deferreds_by_audio_id) == 0:
            del self._deferreds_by_client_id[client_id]
    
