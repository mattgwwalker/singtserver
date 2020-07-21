import random
import struct
import time
import wave

import pyogg
from twisted.internet import reactor
from twisted.internet.protocol import DatagramProtocol
from twisted.internet.task import LoopingCall
from twisted.logger import Logger

from singt.jitter_buffer import JitterBuffer
from singt.udp_packetizer import UDPPacketizer

# Start a logger with a namespace for a particular subsystem of our application.
log = Logger("backing_track")


class RecvOpusStream(DatagramProtocol):
    def __init__(self):
        # Dictionary of OpusDecoders; one per connected client
        self._opus_decoders = {}

        # Dictionary of wave_writes; one per connected client
        self._wave_writes = {}
        
        # Initialise the jitter buffer
        packets_to_buffer = 3
        self._jitter_buffer = JitterBuffer(packets_to_buffer)

        # TEST
        self._dropped_packets = 0

        reactor.callWhenRunning(self._start_audio_processing_loop, 20/1000)

        self._connections = {}
        
    def datagramReceived(self, data, addr):
        #print("Received UDP packet from", addr)

        # If we haven't already seen this address, create a new
        # UDPPacketizer for it, otherwise get the appropriate instance
        if addr not in self._connections:
            self._connections[addr] = UDPPacketizer(self.transport, addr)
        udp_packetizer = self._connections[addr]
            
        
        # Extract the timestamp (4 bytes), sequence number (2 bytes),
        # and encoded frame (remainder)
        timestamp, seq_no, encoded_packet = udp_packetizer.decode(data)

        self._jitter_buffer.put_packet(seq_no, encoded_packet)

        return


        # !!!!!!!!!!! FIXME !!!!!!!!!!!
        # Doesn't use the jitter buffer's packet

        # Fake high data loss
        reliability = 1.0
        if random.random() < reliability: 
            self.transport.write(data, addr)
        else:
            self._dropped_packets += 1
            print(f"TEST: DROPPING PACKET! Dropped a total of {self._dropped_packets} packets.")
            
        return


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


    def process_audio_frame(self, count):
        start_time = time.time()
        print("In process_audio_frame()  count:",count)

        # Repeat count times
        for _ in range(count):
            # For each jitter buffer, get the next packet and send it on.
            for udp_packetizer in self._connections.values():
                # Currently, there is only one jitter buffer!
                encoded_packet = self._jitter_buffer.get_packet()

                # Send encoded packet
                if encoded_packet is not None:
                    udp_packetizer.write(encoded_packet)

        end_time = time.time()
        print(f"process_audio_frame() duration: {round((end_time-start_time)*1000)} ms")
        
    def _start_audio_processing_loop(self, interval):
        looping_call = LoopingCall.withCount(self.process_audio_frame)

        d = looping_call.start(interval)

        def on_stop(data):
            print("The audio processing loop was stopped")
            
        def on_error(data):
            print("ERROR: An error occurred during the audio processing loop:", data)
            raise Exception("An error occurred during the audio processing loop:" + str(data))

        d.addCallback(on_stop)
        d.addErrback(on_error)

        return d
        
