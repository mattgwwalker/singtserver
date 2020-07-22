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
from singt.client.client_udp import UDPClientTester
    
if __name__=="__main__":
    # Ensure the user has called this script with the correct number
    # of arguments.
    if len(sys.argv) != 3:
        print("Usage:")
        print(f"   {sys.argv[0]} ip-address wav_filename")
        exit()

    # Create a name for this tester
    tester_id = str(random.randint(0,1000))
    username = "Singt Client Tester #" + tester_id

    # Extract values for the IP address and the filename of the wav
    # file to play
    address = sys.argv[1]
    in_filename = sys.argv[2]

    # Setup logging
    logfile = open(f"client-{tester_id}.log", 'w')
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
    log = Logger("client_tester")

    
    # TCP
    # ===
    address = sys.argv[1]
    point = TCP4ClientEndpoint(reactor, address, 1234)

    client = TCPClient(username)
    d = connectProtocol(point, client)
    
    def err(failure):
        print("An error occurred:", failure)

    d.addErrback(err)

    # UDP
    # ===

    # 0 means any port, we don't care in this case
    out_filename = f"out-{tester_id}.wav"
    udp_client = UDPClientTester(
        address, 12345,
        in_filename,
        out_filename
    )
    

    #reactor.callWhenRunning(udp_client.send_file, filename)
    #reactor.callWhenRunning(udp_client.start_audio_processing_loop)
    reactor.listenUDP(0, udp_client)

    # Reactor
    # =======
    
    print("Running reactor")
    reactor.run()

    print("Finished.")

