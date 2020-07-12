import struct
from twisted.internet import reactor
from twisted.internet.protocol import Protocol
from twisted.internet.endpoints import TCP4ClientEndpoint, connectProtocol

class Greeter(Protocol):
    def __init__(self, name):
        super()
        self._name = name

    def connectionMade(self):
        self.sendMessage('{{"announce":"{:s}"}}'.format(self._name))
            
    def sendMessage(self, msg):
        msg_as_bytes = msg.encode("utf-8")
        len_as_short = struct.pack("H", len(msg))
        encoded_msg = len_as_short + msg_as_bytes
        self.transport.write(encoded_msg)

        
def gotConnectedProtocol(p):
    p.sendMessage("Hello")
    reactor.callLater(1, p.sendMessage, "This is sent in a second")
    reactor.callLater(2, p.transport.loseConnection)

    
def err(failure):
    print("An error occurred:", failure)

    
if __name__=="__main__":
    print("What is your name?")
    name = input()

    point = TCP4ClientEndpoint(reactor, "localhost", 1234)

    greeter = Greeter(name)
    d = connectProtocol(point, greeter)
    d.addCallback(gotConnectedProtocol)
    d.addErrback(err)
    print("Running reactor")
    reactor.run()
    print("Finished")
