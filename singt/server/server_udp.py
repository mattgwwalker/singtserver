import random
import struct
import time
import wave

import numpy
import pyogg
from pyogg import OpusDecoder
from pyogg import OpusEncoder
from twisted.internet import reactor
from twisted.internet.protocol import DatagramProtocol
from twisted.internet.task import LoopingCall
from twisted.logger import Logger

from singt.jitter_buffer import JitterBuffer
from singt.udp_packetizer import UDPPacketizer

# Start a logger with a namespace for a particular subsystem of our application.
log = Logger("backing_track")


class UDPServer(DatagramProtocol):
    def __init__(self):
        
        # TEST
        self._dropped_packets = 0

        reactor.callWhenRunning(self._start_audio_processing_loop, 20/1000)

        self._connections = {}

        self._opus_encoder = OpusEncoder()
        self._opus_encoder.set_application("audio")
        self._opus_encoder.set_sampling_frequency(48000)
        self._opus_encoder.set_channels(1)
        
    def datagramReceived(self, data, addr):
        #print("Received UDP packet from", addr)

        # If we haven't already seen this address, create a new
        # UDPPacketizer for it, otherwise get the appropriate instance
        if addr not in self._connections:
            packets_to_buffer = 3
            self._connections[addr] = {
                "udp_packetizer": UDPPacketizer(self.transport, addr),
                # Initialise the jitter buffer
                "jitter_buffer": JitterBuffer(packets_to_buffer)
            }
        udp_packetizer = self._connections[addr]["udp_packetizer"]
        jitter_buffer = self._connections[addr]["jitter_buffer"]
        
        # Extract the timestamp (4 bytes), sequence number (2 bytes),
        # and encoded frame (remainder)
        timestamp, seq_no, encoded_packet = udp_packetizer.decode(data)

        jitter_buffer.put_packet(seq_no, encoded_packet)

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
        if count != 1:
            print("WARNING in process_audio_frame(), count:",count)

        # Repeat count times
        for _ in range(count):
            pcms = {}
            
            # For each jitter buffer, get the next packet and send it on.
            for address, connection in self._connections.items():
                jitter_buffer = connection["jitter_buffer"]
                encoded_packet = jitter_buffer.get_packet()

                # Get decoder
                try:
                    opus_decoder = connection["opus_decoder"]
                    started = connection["started"]
                except KeyError:
                    opus_decoder = OpusDecoder()
                    opus_decoder.set_sampling_frequency(48000) # FIXME
                    opus_decoder.set_channels(1) # FIXME
                    started = False
                    connection["opus_decoder"] = opus_decoder
                    connection["started"] = started
                    
                # Decode encoded packet to PCM
                if encoded_packet is None:
                    duration_ms = 20 # ms FIXME
                    if not started:
                        # We haven't started yet, so ignore this connection
                        pcm = None
                    else:
                        # We have started, so this means we've lost a packet
                        pcm = opus_decoder.decode_missing_packet(duration_ms)
                else:
                    # We've got a valid packet, decode it
                    pcm = opus_decoder.decode(encoded_packet)

                pcms[address] = pcm

            # The number of people who may simultaneously speak
            # without the volume decreasing
            simultaneous_voices = 2 # FIXME

            # Loop through all the pcms and mix them together
            combined_pcm = None
            for address, pcm in pcms.items():
                if pcm is None:
                    continue

                # Convert the PCM to floating point
                pcm_int16 = numpy.frombuffer(
                    pcm,
                    dtype = numpy.int16
                )

                pcm_float = pcm_int16.astype(numpy.float32)
                pcm_float /= 2**15
                pcm_float = numpy.reshape(pcm_float, (len(pcm_float), 1))
                
                pcm_float /= simultaneous_voices
                if combined_pcm is None:
                    combined_pcm = pcm_float
                else:
                    combined_pcm += pcm_float

            # Encode the PCM
            if combined_pcm is not None:
                # Convert from float32 to int16
                pcm_int16 = combined_pcm * (2**15-1)
                pcm_int16 = pcm_int16.astype(numpy.int16)

                # Encode the PCM
                encoded_packet = self._opus_encoder.encode(pcm_int16.tobytes())

                # Send the encoded packet to all the clients
                for address, connection in self._connections.items():
                    udp_packetizer = connection["udp_packetizer"]
                    # Send encoded packet
                    if encoded_packet is not None:
                        udp_packetizer.write(encoded_packet)

        end_time = time.time()
        duration_ms = (end_time-start_time)*1000
        if duration_ms > 5:
            print(f"process_audio_frame() duration: {round(duration_ms)} ms")
        
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
        
