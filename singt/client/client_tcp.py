import json
import struct

from twisted.internet import reactor
from twisted.internet.protocol import Protocol

class TCPClient(Protocol):
    def __init__(self, name):
        super()
        self._name = name

        print("Client started")

    def connectionMade(self):
        data = {
            "command":"announce",
            "username": self._name
        }
        msg = json.dumps(data) 
        self.sendMessage(msg)

    def connectionLost(self, reason):
        print("Connection lost:", reason)
        if reactor.running:
            reactor.stop()
        
    def sendMessage(self, msg):
        msg_as_bytes = msg.encode("utf-8")
        len_as_short = struct.pack("H", len(msg))
        encoded_msg = len_as_short + msg_as_bytes
        self.transport.write(encoded_msg)

    def dataReceived(self, data):
        print("data received:", data)
