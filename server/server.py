from enum import Enum
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile

from twisted.internet import protocol, reactor, endpoints
from twisted.internet import defer
from twisted.internet import task
from twisted.web import server, resource
from twisted.web.static import File

from backing_track import BackingTrack
from database import Database
from eventsource import EventSource

# Setup logging
import sys
from twisted.logger import Logger, LogLevel, LogLevelFilterPredicate, \
    textFileLogObserver, FilteringLogObserver, globalLogBeginner


logfile = open("application.log", 'w')
logtargets = []

# Set up the log observer for stdout.
logtargets.append(
    FilteringLogObserver(
        textFileLogObserver(sys.stdout),
        predicates=[LogLevelFilterPredicate(LogLevel.debug)] # was: warn
    )
)

# Set up the log observer for our log file. "debug" is the highest possible level.
logtargets.append(
    FilteringLogObserver(
        textFileLogObserver(logfile),
        predicates=[LogLevelFilterPredicate(LogLevel.debug)]
    )
)

# Direct the Twisted Logger to log to both of our observers.
globalLogBeginner.beginLoggingTo(logtargets)

# Start a logger with a namespace for a particular subsystem of our application.
log = Logger("server")








# Define directories
session_dir = Path("session_files/")
uploads_dir = Path(session_dir / "uploads/")
backing_track_dir = Path(session_dir / "backing_tracks/")

# Ensure directories exist
session_dir.mkdir(exist_ok=True)
uploads_dir.mkdir(exist_ok=True)
backing_track_dir.mkdir(exist_ok=True)

# Define database filename
db_filename = session_dir / "database.sqlite3"

# Create the database
database = Database(db_filename)

# Create the web resources
file_resource = File("./www/")
root = file_resource

eventsource_resource = EventSource()
root.putChild(b"eventsource", eventsource_resource)

backing_track_resource = BackingTrack(
    uploads_dir,
    backing_track_dir,
    database,
    eventsource_resource
)
root.putChild(b"backing_track", backing_track_resource)

# Create a web server
site = server.Site(root)
reactor.listenTCP(8080, site)


# An instance of this class is created for each client connection.
class Server(protocol.Protocol):
    class State:
        STARTING = 10
        CONTINUING = 20
    
    def __init__(self, shared_context):
        super()
        self._buffer = b""
        self._state = Server.State.STARTING
        self._length = None

        self._shared_context = shared_context
        self.username = None


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
        print("Received data:", data)

        # Combine current data with buffer
        data = self._buffer + data

        while len(data) > 0:
            #print("Considering data:", data)
            
            if self._state == Server.State.STARTING:
                # Read the first two bytes as a short integer
                self._length = struct.unpack("H",data[0:2])[0]
                #print("length:",self._length)

                # Remove the short from the data
                data = data[2:]

                # Move to CONTINUING
                self._state = Server.State.CONTINUING

            if self._state == Server.State.CONTINUING:
                # Do we have all the required characters in the current data?
                if len(data) >= self._length:
                    # Separate the current message
                    msg = data[:self._length]

                    # Process the message
                    self.process(msg.decode("utf-8"))

                    # Remove the current message from any remaining data
                    data = data[self._length:]

                    # Move back to STARTING
                    self._state = Server.State.STARTING
                else:
                    # We do not have sufficient characters.  Store them in
                    # the buffer till next time we receive data.
                    #print("We do not have sufficient characters; waiting")
                    #print("len(data):", len(data))
                    self._buffer = data
                    data = ""

    def connectionLost(self, reason):
        print("Connection lost to user '{:s}':".format(self.username), reason)
        del self._shared_context.usernames[self.username]
        data = {
            "participants": list(self._shared_context.usernames.keys())
        }
        self._shared_context.eventsource.publish_to_all(
            "update_participants",
            json.dumps(data)
        )
            

 
class ServerFactory(protocol.Factory):
    class SharedContext:
        def __init__(self):
            self.eventsource = eventsource_resource
            self.usernames = {}
            
    def __init__(self):
        self._shared_context = ServerFactory.SharedContext()
        self._shared_context.eventsource.add_initialiser(
            "update_participants",
            self.initialiseParticipants
        )
    
    def buildProtocol(self, addr):
        return Server(self._shared_context)

    def startFactory(self):
        print("Server started")

    def initialiseParticipants(self):
        data = {
            "participants": list(self._shared_context.usernames.keys())
        }
        return json.dumps(data)
        

endpoints.serverFromString(reactor, "tcp:1234").listen(ServerFactory())

reactor.run()
