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

from database import Database
from server_udp import UDPServer
from server_tcp import TCPServerFactory
import server_web

# Setup logging
import sys
from twisted.logger import Logger, LogLevel, LogLevelFilterPredicate, \
    textFileLogObserver, FilteringLogObserver, globalLogBeginner


logfile = open("server.log", 'w')
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

# Create UDP server
udp_server = UDPServer()

# TEST Audio playback
def play_audio():
    filename = "psallite.opus"
    #filename="left-right-demo-5s.opus"
    udp_server.play_audio(filename)
reactor.callWhenRunning(play_audio)

# Create the web-server based interface
www_server, eventsource_resource, backing_track_resource = server_web.create_web_interface(
    uploads_dir,
    backing_track_dir,
    database
)

# Create TCP server factory
tcp_server_factory = TCPServerFactory(
    eventsource_resource,
    backing_track_resource
)


endpoints.serverFromString(reactor, "tcp:1234").listen(tcp_server_factory)
reactor.listenUDP(12345, udp_server)
reactor.listenTCP(8080, www_server)

reactor.run()
