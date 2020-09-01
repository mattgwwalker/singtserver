from enum import Enum
from pathlib import Path

import json

from twisted.internet import protocol
from twisted.internet import reactor
from twisted.internet import endpoints
from twisted.internet import defer

from singtcommon import TCPPacketizer
from .session_files import SessionFiles

# Start a logger with a namespace for a particular subsystem of our application.
from twisted.logger import Logger
log = Logger("server_file")


class FileTransportServer(protocol.Protocol):
    """Responsible for either sending or receiving one file.

    Client initiates either sending on file to the server or receiving
    one file from the server.

    Once the file is transported, the connection is cut by the server.

    """
    def __init__(self, context):
        self._started = False
        self._context = context
        self._session_files = context["session_files"]

    def connectionMade(self):
        log.info("Connection made to server")
        self._packetizer = TCPPacketizer(self.transport)
        
    def connectionLost(self, reason):
        pass
        
    def dataReceived(self, data):
        #print("data received:", data)
        packets = self._packetizer.decode_bytes(data)

        for packet in packets:
            if not self._started:
                self._process_command(packet)
            else:
                self._process_data(packet)

    def _process_command(self, packet):
        print("in _process_command")
        packet = packet.decode("utf-8")
        message = json.loads(packet)
        print("Received message:", message)
        command = message["command"]
        if command == "receive_file":
            self._audio_id = message["audio_id"]
            # Assume this file is a recording; get its location
            self._audio_path = self._session_files.get_audio_path(self._audio_id)
            # Open file for writing
            self._f = open(self._audio_path, "wb")
            self._started = True
            print("Starting...")
        elif command == "send":
            raise NotImplementedError("'Send' command not yet implemented")
        else:
            raise Exception(f"Command '{command}' is not supported")

    def _process_data(self, packet):
        print("in _process_data")
        def head(packet, header):
            return packet[0:len(header)] == header

        def tail(packet, header):
            return packet[len(header):]

        data_header = b"DATA"
        abort_header = b"ABORT"
        end_header = b"END"
        
        if head(packet, data_header):
            print("Received data")
            data = tail(packet, data_header)
            self._f.write(data)
        elif head(packet, abort_header):
            print("Aborted")
            self._f.close()
            self.transport.loseConnection()
        elif head(packet, end_header):
            print("Finished")
            self._f.close()
            self.transport.loseConnection()
            d = self.factory.anticipate_audio_id(self._audio_id)
            d.callback(self._audio_id)
        else:
            raise Exception("Error; unexpected packet contents.  First 10 bytes: ",packet[0:10])
        

class FileTransportServerFactory(protocol.Factory):
    def __init__(self, context):
        self._context = context
        self._anticipated_audio_ids = {}
        
    def buildProtocol(self, addr):
        print("Building a protocol")
        protocol = FileTransportServer(self._context)
        protocol.factory = self
        return protocol

    def startFactory(self):
        log.info("FileTransportServerFactory started")

    def anticipate_audio_id(self, audio_id):
        # Check if audio_id is already anticipated
        if audio_id in self._anticipated_audio_ids:
            # Audio id already anticipated
            return self._anticipated_audio_ids[audio_id]
        else:
            # Add audio id to anticipated list
            d = defer.Deferred()
            self._anticipated_audio_ids[audio_id] = d
            return d
        

if __name__ == "__main__":
    # Create empty context
    context = {}

    # Create a session_files instance
    session_files = SessionFiles(Path.home() / "server_file_test")
    context["session_files"] = session_files
    
    # Start a file transport server factory
    file_transport_server_factory = FileTransportServerFactory(context)
    
    port = 2000
    endpoints.serverFromString(reactor, f"tcp:{port}").listen(file_transport_server_factory)

    reactor.run()
