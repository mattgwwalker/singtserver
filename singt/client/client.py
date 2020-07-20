import copy
import random
import sys
import threading

import numpy
import sounddevice as sd
from twisted.internet import reactor
from twisted.internet.endpoints import TCP4ClientEndpoint, connectProtocol

from singt.client.client_tcp import TCPClient
from singt.client.client_udp import UDPClient
    
if __name__=="__main__":
    print("What is your name?")
    name = input()

    # TCP
    # ===
    address = sys.argv[1]
    point = TCP4ClientEndpoint(reactor, address, 1234)

    client = TCPClient(name)
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

