import copy
import random
import sys
import threading

import numpy
import sounddevice as sd
from twisted.internet import reactor
from twisted.internet.endpoints import TCP4ClientEndpoint, connectProtocol
from twisted.logger import Logger, LogLevel, LogLevelFilterPredicate, \
    textFileLogObserver, FilteringLogObserver, globalLogBeginner

from singt.client.client_tcp import TCPClient
from singt.client.client_udp import UDPClient
    
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

    # Setup logging
    logfile = open(f"client-{username}.log", 'w')
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

        
    # TCP
    # ===
    point = TCP4ClientEndpoint(reactor, address, 1234)
    client = TCPClient(username)
    d = connectProtocol(point, client)
    
    def err(failure):
        print("An error occurred:", failure)

    d.addErrback(err)

    # UDP
    # ===

    # 0 means any port, we don't care in this case
    udp_client = UDPClient(address, 12345)
    reactor.listenUDP(0, udp_client)

    # Reactor
    # =======
    
    print("Running reactor")
    reactor.run()

    print("Finished.")

