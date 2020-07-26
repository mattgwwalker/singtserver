import copy
import random
import sys
import threading

import art
import numpy
import sounddevice as sd
from twisted.internet import reactor
from twisted.logger import Logger, LogLevel, LogLevelFilterPredicate, \
    textFileLogObserver, FilteringLogObserver, globalLogBeginner

from singt.client import client_web

# Setup logging
logfile = open(f"client.log", 'w')
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
log = Logger("client")



def start():
    title = art.text2art("Singt")
    print(title)

    # Web Interface
    # =============

    web_server, eventsource_resource = client_web.create_web_interface(reactor)
    reactor.listenTCP(8000, web_server)
    
    # Reactor
    # =======
    
    print("Running reactor")
    reactor.run()

    print("Finished.")



if __name__=="__main__":
    # Ensure the user has called this script with the correct number
    # of arguments.
    if len(sys.argv) != 3:
        print("Usage:")
        print(f"   {sys.argv[0]} ip-address name")
        exit()

    # Extract values for the IP address and the user's name
    address = sys.argv[1]
    username = sys.argv[2]

    run_client(address, username)
    
