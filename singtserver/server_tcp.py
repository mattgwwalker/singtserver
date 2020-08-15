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


    def connectionMade(self):
        self._tcp_packetizer = TCPPacketizer(self.transport)

        
    def announce(self, json_data):
        """Announces username, which is then stored in the shared context.
        Returns True if username is unused."""

        # Extract the username
        username = json_data["username"]

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
            print("Failed to parse message as JSON.")
            print("msg:", msg)
            print("Exception:",e)
            return

        # Execute commands
        try:
            command = json_data["command"]
        except KeyError:
            print("Failed to find 'command' key in JSON")
            print("msg:", msg)
            return
        
        if command=="announce":
            self.announce(json_data)
        else:
            print("Unknown command ({:s})".format(command))
            print("msg:", msg)
            return

        
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

 
class TCPServerFactory(protocol.Factory):
    class SharedContext:
        def __init__(self, eventsource):
            self.eventsource = eventsource
            self.usernames = {}
            
    def __init__(self, web_server):
        # Create a list of protocol instances, used for broadcasting
        # to all clients
        self._protocols = []

        # TODO: Is this really the best way to implement this?
        eventsource = web_server.eventsource_resource
        backing_track_resource = web_server.backing_track_resource
        self._shared_context = TCPServerFactory.SharedContext(eventsource)
        self._shared_context.eventsource.add_initialiser(
            self.initialiseParticipants
        )
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
        
