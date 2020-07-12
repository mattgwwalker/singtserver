import struct
import json
from enum import Enum
from twisted.internet import protocol, reactor, endpoints

class Server(protocol.Protocol):
    class State:
        STARTING = 10
        CONTINUING = 20
    
    def __init__(self):
        super()
        self._buffer = b""
        self._state = Server.State.STARTING
        self._length = None
    
    def announce(self, json_data):
        username = json_data["username"]
        print("User '{:s}' has just announced themselves".format(username))

    # The message is complete and should not contain any extra data
    def process(self, msg):
        print("Trying to process '{:s}'".format(msg))
        try:
            json_data = json.loads(msg)

        except Exception as e:
            print("Failed to parse message as JSON.")
            print("msg:", msg)
            print("Exception:",e)
            return

        print("json_data:", json_data)

        try:
            command = json_data["command"]
        except KeyError:
            print("Failed to find 'command' key in JSON")
            return
        
        if command=="announce":
            self.announce(json_data)
        else:
            print("Unknown command ({:s})".format(command))

        #self.transport.write(data)

        
    # Data received may be a partial package, or it may be multiple
    # packets joined together.
    def dataReceived(self, data):
        print("Received data:", data)

        # Combine current data with buffer
        data = self._buffer + data

        while len(data) > 0:
            print("Considering data:", data)
            
            if self._state == Server.State.STARTING:
                # Read the first two bytes as a short integer
                self._length = struct.unpack("H",data[0:2])[0]
                print("length:",self._length)

                # Remove the short from the data
                data = data[2:]

                # Move to CONTINUING
                self._state = Server.State.CONTINUING

            if self._state == Server.State.CONTINUING:
                # Do we have all the required characters in the current data?
                if len(data) >= self._length:
                    # Separate the current message
                    msg = data[:self._length]

                    # Process the message
                    self.process(msg.decode("utf-8"))

                    # Remove the current message from any remaining data
                    data = data[self._length:]

                    # Move back to STARTING
                    self._state = Server.State.STARTING
                else:
                    # We do not have sufficient characters.  Store them in
                    # the buffer till next time we receive data.
                    print("We do not have sufficient characters; waiting")
                    print("len(data):", len(data))
                    self._buffer = data
                    data = ""

 
class ServerFactory(protocol.Factory):
    def buildProtocol(self, addr):
        return Server()

endpoints.serverFromString(reactor, "tcp:1234").listen(ServerFactory())
reactor.run()
