import json
import struct

from twisted.internet import defer
from twisted.internet import protocol
from twisted.logger import Logger

from singtcommon import TCPPacketizer

# Start a logger with a namespace for a particular subsystem of our application.
log = Logger("server_tcp")


# An instance of this class is created for each client connection.
class TCPServer(protocol.Protocol):
    def __init__(self, shared_context):
        super()
        self._tcp_packetizer = None

        self._shared_context = shared_context
        self.username = None

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
            raise Exception(f"Exception during execution of function for command '{command}': "+str(e))
        
    # Data received may be a partial package, or it may be multiple
    # packets joined together.
    def dataReceived(self, data):
        packets = self._tcp_packetizer.decode(data)

        for packet in packets:
            print("packet decoded:", packet)
            self.process(packet)

            
    def connectionLost(self, reason):
        print(f"Connection lost to user '{self.username}':", reason)
        del self._shared_context.usernames[self.username]
        data = {
            "participants": list(self._shared_context.usernames.keys())
        }
        self._shared_context.eventsource.publish_to_all(
            "update_participants",
            json.dumps(data)
        )

    def send_message(self, msg):
        msg_as_bytes = msg.encode("utf-8")
        len_as_short = struct.pack("H", len(msg))
        encoded_msg = len_as_short + msg_as_bytes
        self.transport.write(encoded_msg)

    def send_download_request(self, audio_id, partial_url):
        command = {
            "command": "download",
            "audio_id": str(audio_id),
            "partial_url": str(partial_url)
        }
        command_json = json.dumps(command)
        self.send_message(command_json)

    def _command_announce(self, json_data):
        """Announces username, which is then stored in the shared context.
        Returns True if username is unused."""

        # Extract the username
        username = json_data["username"]
        client_id = json_data["client_id"]

        self._shared_context.participants.assign(client_id, username)
        
        # PREVIOUS TECHNIQUE

        # Check if the username is already registered
        if username in self._shared_context.usernames:
            # The username already registered; disconnect client
            print("Username '{:s}' already in use".format(username))
            msg = {
                "error": (
                    "Username '{:s}' already in use.  ".format(username)+
                    "Try again with a different username."
                )
            }
            self.transport.write(json.dumps(msg).encode("utf-8"))
            self.transport.loseConnection()
            return False

        # Store username and this protocol instance in the shared
        # context
        self.username = username
        print("User '{:s}' has just announced themselves".format(username))
        self._shared_context.usernames[username] = self

        # Publish an event to update the web interface
        data = {
            "participants": list(self._shared_context.usernames.keys())
        }
        self._shared_context.eventsource.publish_to_all("update_participants", json.dumps(data))
        
        return True

    def _command_update_downloaded(self, json_data):
        print("In _command_update_downloaded, with json_data: ", json_data)
        audio_id = json_data["audio_id"]

 
class TCPServerFactory(protocol.Factory):
    class SharedContext:
        def __init__(self, context):
            self.eventsource = context["web_server"].eventsource_resource
            self.usernames = {}
            
            self.participants = Participants(context)
            
    def __init__(self, context):
        self._context = context
        web_server = self._context["web_server"]
        
        # Create a list of protocol instances, used for broadcasting
        # to all clients
        self._protocols = []

        # TODO: Is this really the best way to implement this?
        eventsource = web_server.eventsource_resource
        backing_track_resource = web_server.backing_track_resource
        self._shared_context = TCPServerFactory.SharedContext(context)
        # self._shared_context.eventsource.add_initialiser(
        #     self.initialiseParticipants
        # )
        self._shared_context.eventsource.add_initialiser(
            backing_track_resource.initialise_eventsource
        )
    
    def buildProtocol(self, addr):
        protocol = TCPServer(self._shared_context)
        self._protocols.append(protocol)
        return protocol

    def startFactory(self):
        print("Server started")

    def initialiseParticipants(self):
        data = {
            "participants": list(self._shared_context.usernames.keys())
        }

        json_data = json.dumps(data)

        d = defer.Deferred()
        d.callback(("update_participants", json_data))
        return d

    def broadcast_download_request(self, audio_id, partial_url):
        for protocol in self._protocols:
            protocol.send_download_request(audio_id, partial_url)
        

class Participants:
    def __init__(self, context):
        self._context = context
        self._db = context["database"]
        self._eventsource = context["web_server"].eventsource_resource
        self._data_by_id = {}

        self._eventsource.add_initialiser(self.eventsource_initialiser)

        
    def assign(self, client_id, name):
        """Assigns name to client_id, overwriting if it exists already."""
        
        print(f"Attempting to add '{name}' to the list of participants")

        d = self._db.assign_participant(client_id, name)


    def get_list(self):
        """Returns list of participants."""
        return self._db.get_participants()
        

    def eventsource_initialiser(self):
        d = self.get_list()
        def on_success(participants):
            event = "update_participants"
            participants_json = json.dumps(participants)
            return (event, participants_json)
        d.addCallback(on_success)

        return d
