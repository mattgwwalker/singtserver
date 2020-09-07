import art
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

from .command import Command
from .database import Database
from .server_file import FileTransportServerFactory
from .server_tcp import TCPServerFactory
from .server_udp import UDPServer
from .server_web import WebServer
from .session_files import SessionFiles

# Setup logging
import sys
from twisted.logger import Logger, LogLevel, LogLevelFilterPredicate, \
    textFileLogObserver, FilteringLogObserver, globalLogBeginner


# Start a logger with a namespace for a particular subsystem of our application.
log = Logger("server")

def start_logging(session_files):
    logfile = open(session_files.session_dir / "server.log", 'w')
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

def start():
    # Create empty context
    context = {}
    context["reactor"] = reactor

    # Create session's required directories
    session_files = SessionFiles(Path.home())
    context["session_files"] = session_files

    # Start logging
    start_logging(session_files)
    
    # ASCII-art title
    title = art.text2art("Singt")
    log.info("\n"+title)

    # Create the database
    database = Database(context)
    session_files.set_database(database)
    context["database"] = database

    # Create UDP server
    udp_server = UDPServer()
    context["udp_server"] = udp_server

    # Create a Command instance
    command = Command(context)
    context["command"] = command

    # Create the web-server based interface
    web_server = WebServer(context)
    command.set_web_server(web_server)
    context["web_server"] = web_server

    # Create TCP server factory
    tcp_server_factory = TCPServerFactory(context)
    command.set_tcp_server_factory(tcp_server_factory)
    context["tcp_server_factory"] = tcp_server_factory

    # Create a file transfer server factory
    file_transport_server_factory = FileTransportServerFactory(context)
    context["file_transport_server_factory"] = file_transport_server_factory
    
    endpoints.serverFromString(reactor, "tcp:2000").listen(file_transport_server_factory)
    endpoints.serverFromString(reactor, "tcp:1234").listen(tcp_server_factory)
    reactor.listenUDP(12345, udp_server)
    www_port = 8080
    reactor.listenTCP(www_port, web_server.site)
    web_server.set_www_port(www_port)

    reactor.run()


if __name__ == "__main__":
    start()
