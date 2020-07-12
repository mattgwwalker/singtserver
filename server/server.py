import json
from enum import Enum
from twisted.internet import protocol, reactor, endpoints

class State(Enum):
    RESET = 0
    CONVERSATION = 10
    RECORDING = 20

state = State.RESET

class Server(protocol.Protocol):
    def announce(self, json_data):
        username = json_data["username"]
        print("User '{:s}' has just announced themselves".format(username))
    
    def dataReceived(self, data):
        print("Received data:", data)
        return
        
        try:
            json_data = json.loads(data)
        except Exception as e:
            print("Failed to parse data as JSON.")
            print("data:", data)
            print("Exception:",e)
            return
        
        print("json_data:", json_data)

        command = json_data["command"]
        if command=="announce":
            self.announce(json_data)
        else:
            print("Unknown command ({:s})".format(command))
            
        
        #self.transport.write(data)

class ServerFactory(protocol.Factory):
    def buildProtocol(self, addr):
        return Server()

endpoints.serverFromString(reactor, "tcp:1234").listen(ServerFactory())
reactor.run()
