from twisted.internet import reactor
from twisted.internet.protocol import Protocol
from twisted.internet.endpoints import TCP4ClientEndpoint, connectProtocol

class Greeter(Protocol):
    def __init__(self, name):
        super()
        self._name = name
        
    
    def sendMessage(self, msg):
        print("In send message")
        message = "MESSAGE {:s} FROM {:s}\n".format(msg, self._name)
        self.transport.write(message.encode("utf-8"))

def gotProtocol(p):
    print("In gotProtocol")
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
    d.addCallback(gotProtocol)
    d.addErrback(err)
    print("Running reactor")
    reactor.run()
    print("Finished")
