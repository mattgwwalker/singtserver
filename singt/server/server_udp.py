import struct
import wave

import pyogg
from twisted.internet.protocol import DatagramProtocol
from twisted.logger import Logger

# Start a logger with a namespace for a particular subsystem of our application.
log = Logger("backing_track")


class RecvOpusStream(DatagramProtocol):
    def __init__(self):
        # Dictionary of OpusDecoders; one per connected client
        self._opus_decoders = {}

        # Dictionary of wave_writes; one per connected client
        self._wave_writes = {}
        
    
    def datagramReceived(self, data, addr):
        #print("Received UDP packet from", addr)

        self.transport.write(data, addr)
        return

        # Extract the timestamp (4 bytes), sequence number (2 bytes),
        # and encoded frame (remainder)
        timestamp, seq_no = struct.unpack(">IH", data[0:6])
        encoded_packet = data[6:]

        seq_no = int.from_bytes(seq_no ,"big")
        print("\n",seq_no)

        # Get OpusDecoder for this client
        try:
            opus_decoder = self._opus_decoders[addr]
        except KeyError:
            # Didn't find an OpusDecoder for this connection, create
            # one and store it in the dictionary
            opus_decoder = pyogg.OpusDecoder()
            self._opus_decoders[addr] = opus_decoder

            # Initialise the decoder
            opus_decoder.set_channels(1) # Mono
            opus_decoder.set_sampling_frequency(48000)

        # Decode the encoded packet
        pcm = opus_decoder.decode(encoded_packet)

        # Get the wave_write for this client
        try:
            wave_write = self._wave_writes[addr]
        except KeyError:
            # Didn't find a wave_write for this connection, create one
            # and store it in the dictionary
            filename = f"{addr[0]}_{addr[1]}.wav"
            wave_write = wave.open(filename, "wb")
            self._wave_writes[addr] = wave_write

            # Initialise the wave_write
            wave_write.setnchannels(1)
            wave_write.setsampwidth(2)
            wave_write.setframerate(48000)

        # Write the PCM to the wav file
        wave_write.writeframes(pcm)
        
