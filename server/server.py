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
from twisted.enterprise import adbapi

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
backing_track_dir = Path(session_dir / "backing_tracks/")

# Ensure directories exist
session_dir.mkdir(exist_ok=True)
backing_track_dir.mkdir(exist_ok=True)

# Define database filename
db_filename = session_dir / "database.sqlite3"

# Note if database already exists
database_exists = db_filename.is_file()
    
# Open a connection to the database.  SQLite will create the file if
# it doesn't already exist.
dbpool = adbapi.ConnectionPool("sqlite3", db_filename)

# Initialise the database structure from instructions in file
def initialise_database(cursor):
    try:
        print("Initialising database")
        initialisation_commands_filename = "database.sql"
        f = open(initialisation_commands_filename, "r")
        initialisation_commands = f.read()
        print("Raising exception")
        #import pdb; pdb.set_trace() # DEBUG
        log.error("Raising exception")
        raise Exception("Testing")
        print(initialisation_commands)

        return cursor.executemany(initialisation_commands)
    except Exception as e:
        log.error("Exception caught; re-raising")
        log.error(str(e))
        raise e

# If the database did not exist, initialise the database
if not database_exists:
    print("Database requires initialisation")
    d = dbpool.runInteraction(initialise_database)
    def on_success(data):
        print("Database successfully initialised")
    def on_error(data):
        print("Failed to initialise the database")
        reactor.stop()

    d.addCallback(on_success)
    d.addErrback(on_error)




class Simple(resource.Resource):
    #isLeaf = True
    def render_GET(self, request):
        return b"<html>Hello, world!</html>"

file_resource = File("./")


class BackingTrack(resource.Resource):
    isLeaf = True

    def __init__(self):
        super()

        # Check that backing track directory exists
        

    def render_POST(self, request):
        request.setResponseCode(201)
        
        command = request.args[b"command"][0].decode("utf-8") 
        print("command:", command)

        name = request.args[b"name"][0].decode("utf-8")
        print("name:", name)

        # Save file
        file_contents = request.args[b"file"][0]
        f = tempfile.TemporaryFile()
        f.write(file_contents)

        # Check if the file is WAV or Opus or something else
        f.seek(0)
        first_chars = f.read(4)

        if first_chars == b"RIFF":
            print("Uploaded file is a WAV file; need to convert it to Opus")
            # TODO: Convert WAV to Opus.
            
        elif first_chars == b"OggS":
            print("Uploaded file is an Ogg Stream, which may be in Opus format; double-check.")
            # TODO: Double-check it's actually an Opus-formatted Ogg stream.
            
        else:
            print("Uploaded file was neither WAV nor Opus; error.")
        
        f.close()

        # Add backing track into database
        def add_backing_track():
            def write_to_database(cursor):
                print("Inserting '{:s}' into backing tracks".format(name))
                cursor.execute("INSERT INTO BackingTracks(trackName) VALUES (?);", (name,))
                backing_track_id = cursor.lastrowid
                return backing_track_id
            return dbpool.runInteraction(write_to_database)
            
        
        def on_success(backing_track_id):
            print("in on_success, rowid:", backing_track_id)

            # Write file
            filename = XXX

        def on_error(data):
            print("in on_error, data:", data)

        d = add_backing_track()
        d.addCallback(on_success)
        d.addErrback(on_error)
        
        return b"{\'result\': \'success\'}"
        

# See https://github.com/juggernaut/twisted-sse-demo/blob/master/sse_server.py
class EventSource(resource.Resource):
    isLeaf = True

    def __init__(self):
        self.subscribers = set()
        self._initialisers = {}
        
    
    def render_GET(self, request):
        request.setHeader('Content-Type', 'text/event-stream; charset=utf-8')
        request.setResponseCode(200)
        self.add_subscriber(request)
        request.write("")
        return server.NOT_DONE_YET

    
    def add_subscriber(self, request):
        #log.msg("Adding subscriber...")
        self.subscribers.add(request)
        d = request.notifyFinish()
        d.addBoth(self.remove_subscriber)

        # Loop through all the initialisers to bring the newly
        # connected client up to date.
        for event, f in self._initialisers.items():
            data = f()
            self.publish_to_one(request, event, data)

    
    def remove_subscriber(self, subscriber):
        if subscriber in self.subscribers:
            #log.msg("Removing subscriber..")
            self.subscribers.remove(subscriber)


    def publish_to_all(self, event, data):
        for subscriber in self.subscribers:
            self.publish_to_one(subscriber, event, data)

            
    def publish_to_one(self, request, event, data):
        request.write("event: {:s}\n".format(event).encode("utf-8"))
        request.write("data: {:s}\n".format(data).encode("utf-8"))
        # A extra new line is required to dispatch the event to the client
        request.write(b"\n")
                          

    def add_initialiser(self, event, f):
        self._initialisers[event] = f
        

            
root = file_resource

eventsource_resource = EventSource()
root.putChild(b"eventsource", eventsource_resource)

backing_track_resource = BackingTrack()
root.putChild(b"backing_track", backing_track_resource)

#site = server.Site(Simple())
#site = server.Site(file_resource)
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
