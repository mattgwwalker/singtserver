import copy
import random
import sys
import threading

import numpy
import sounddevice as sd
from twisted.internet import reactor
from twisted.internet.endpoints import TCP4ClientEndpoint, connectProtocol

from singt.client.client_tcp import TCPClient
from singt.client.client_udp import UDPClientTester
    
if __name__=="__main__":
    # Create a name for this tester
    tester_id = str(random.randint(0,1000))
    name = "Singt Client Tester #" + tester_id

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
    udp_client = UDPClientTester(address, 12345, f"out-{tester_id}.wav")
    

    filename = "../../gs-16b-2c-44100hz.wav"
    reactor.callWhenRunning(udp_client.send_file, filename)
    reactor.callWhenRunning(udp_client.start_audio_processing_loop)
    reactor.listenUDP(0, udp_client)

    # Reactor
    # =======
    
    print("Running reactor")
    reactor.run()

    print("Finished.")

