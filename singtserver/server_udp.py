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

from singtcommon import JitterBuffer
from singtcommon import UDPPacketizer
from singtcommon import AutomaticGainControl

# Start a logger with a namespace for a particular subsystem of our application.
log = Logger("backing_track")


class UDPServer(DatagramProtocol):
    def __init__(self):
        self._stream = None
        self._stream_buffer = None
        # TEST
        self._dropped_packets = 0

        reactor.callWhenRunning(self._start_audio_processing_loop, 20/1000)

        self._connections = {}

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


    def play_audio(self, filenames):
        # Assumes filename points to Opus-encoded audio.
        # TODO: Check that we're not currently playing anything else

        # TODO: Deal with more than one filename
        log.info("Playing these filenames: "+str(filenames))
        filename = filenames[0]
        
        # Open file as stream
        try:
            self._stream = pyogg.OpusFileStream(str(filename))
        except Exception as e:
            raise Exception(f"Failed to open OpusFileStream (with filename '{filename}': "+
                            str(e))
        self._stream_buffer = None

    def stop_audio(self):
        # TODO: It would be much nicer if this faded out
        self._stream = None
        self._stream_buffer = None


    def process_audio_frame(self, count):
        start_time = time.time()
        if count != 1:
            print(f"WARNING in process_audio_frame(), catching up on {count} missed cycles")

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

                # Convert the PCM to floating point
                if pcm is not None:
                    pcm_int16 = numpy.frombuffer(
                        pcm,
                        dtype = numpy.int16
                    )

                    pcm_float = pcm_int16.astype(numpy.float32)
                    pcm_float /= 2**15
                    pcm_float = numpy.reshape(pcm_float, (len(pcm_float), 1))
                    pcm = pcm_float

                    # # Apply automatic gain control to the PCM
                    # try:
                    #     agc = connection["automatic_gain_control"]
                    # except KeyError:
                    #     agc = AutomaticGainControl()
                    #     connection["automatic_gain_control"] = agc
                    # agc.apply(pcm)
                    # print("gain:", agc.gain)
                    
                # Store the PCM
                pcms[address] = pcm

            # The number of people who may simultaneously speak
            # without the volume decreasing
            simultaneous_voices = 2 # FIXME

            # Loop through all the pcms and mix them together
            combined_pcm = None
            for address, pcm in pcms.items():
                if pcm is None:
                    continue

                pcm /= simultaneous_voices
                pcms[address] = pcm
                
                if combined_pcm is None:
                    combined_pcm = pcm.copy()
                else:
                    combined_pcm += pcm

            # Mix in playback audio
            if (self._stream is not None
                or self._stream_buffer is not None):
                # Read the next part of the stream until either we
                # come to the end or we've got sufficient for a full
                # frame.
                samples_per_second = 48000 # FIXME
                duration_ms = 20 # FIXME
                samples_per_frame = samples_per_second // 1000 * duration_ms # FIXME
                while (self._stream_buffer is None
                       or len(self._stream_buffer) < samples_per_frame):
                    next_ = self._stream.get_buffer_as_array()
                    if next_ is None:
                        # We've come to the end
                        self._stream = None
                        break
                    # Join what we just read to what we've read so far
                    if self._stream_buffer is None:
                        self._stream_buffer = numpy.copy(next_)
                    else:
                        self._stream_buffer = numpy.concatenate(
                            (self._stream_buffer, next_)
                        )

                # Obtain the PCM
                if len(self._stream_buffer) >= samples_per_frame:
                    # Take what we need to fill a frame and leave the rest
                    pcm = self._stream_buffer[:samples_per_frame]
                    self._stream_buffer = self._stream_buffer[samples_per_frame:]
                else:
                    # Take whatever's left
                    pcm = self._stream_buffer
                    self._stream_buffer = None

                # Convert the int16 data to float
                pcm_float = pcm.astype(numpy.float32)
                pcm_float /= 2**15

                # Convert it to mono if it's in stereo
                pcm_float = numpy.mean(pcm_float, axis=1)
                pcm_float = pcm_float.reshape((len(pcm_float),1))

                # Fill with zeros if it's not long enough
                if len(pcm_float) < samples_per_frame:
                    pcm_float = numpy.concatenate(
                        (pcm_float, numpy.zeros(
                            (samples_per_frame - len(pcm_float), 1)
                        ))
                    )

                # Halve the volume
                pcm_float /= 2

                # Add it into the combined pcm
                if combined_pcm is None:
                    combined_pcm = pcm_float
                else:
                    combined_pcm += pcm_float
                    

            # Prepare each individual client's PCM
            if combined_pcm is not None:
                # Send the encoded packet to all the clients
                for address, connection in self._connections.items():
                    client_signal = pcms[address]
                    if client_signal is None:
                        continue
                    
                    # Remove their signal from the audio
                    client_pcm = combined_pcm #- client_signal

                    # Convert from float32 to int16
                    pcm_int16 = client_pcm * (2**15-1)
                    pcm_int16 = pcm_int16.astype(numpy.int16)

                    # Obtain encoder
                    try:
                        opus_encoder = connection["opus_encoder"]
                    except KeyError:
                        opus_encoder = OpusEncoder()
                        opus_encoder.set_application("audio")
                        opus_encoder.set_sampling_frequency(48000)
                        opus_encoder.set_channels(1)
                        connection["opus_encoder"] = opus_encoder
                    
                    # Encode the PCM
                    encoded_packet = opus_encoder.encode(pcm_int16.tobytes())
                    
                    # Send encoded packet
                    udp_packetizer = connection["udp_packetizer"]
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
        
