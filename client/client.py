import json
import struct
from twisted.internet import reactor
from twisted.internet.protocol import Protocol
from twisted.internet.endpoints import TCP4ClientEndpoint, connectProtocol

class Client(Protocol):
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
        reactor.stop()
        
    def sendMessage(self, msg):
        msg_as_bytes = msg.encode("utf-8")
        len_as_short = struct.pack("H", len(msg))
        encoded_msg = len_as_short + msg_as_bytes
        self.transport.write(encoded_msg)

    def dataReceived(self, data):
        print("data received:", data)

        
def err(failure):
    print("An error occurred:", failure)

    
if __name__=="__main__":
    print("What is your name?")
    name = input()

    point = TCP4ClientEndpoint(reactor, "localhost", 1234)

    client = Client(name)
    d = connectProtocol(point, client)
    d.addErrback(err)
    print("Running reactor")
    reactor.run()

