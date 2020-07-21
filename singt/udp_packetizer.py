import struct
import time

class UDPPacketizer:
    def __init__(self, transport, address):
        self._transport = transport
        self._address = address
        self._seq_no = 0
        self._seq_no_max = 2**16
        # sequence numbers will be from zero to seq_no_max-1,
        # inclusive

    def write(self, data):
        # Insert timestamp and sequence number header before data
        current_time = int(time.monotonic()*1000) % (2**32-1)
        header = struct.pack(">IH", current_time, self._seq_no)

        self._transport.write(header+data, self._address)
        
        self._seq_no += 1
        self._seq_no %= self._seq_no_max

    def decode(self, packet):
        timestamp, seq_no = struct.unpack(">IH", packet[0:6])
        data = packet[6:]

        return (timestamp, seq_no, data)
