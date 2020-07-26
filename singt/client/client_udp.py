import time
import struct
import wave

import numpy
from pyogg import OpusEncoder
from pyogg import OpusBufferedEncoder
from pyogg import OpusDecoder
from twisted.internet import reactor
from twisted.internet import task
from twisted.internet.protocol import DatagramProtocol
from twisted.internet.task import LoopingCall
import sounddevice as sd

from singt.jitter_buffer import JitterBuffer
from singt.udp_packetizer import UDPPacketizer

from twisted.logger import Logger

# Start a logger with a namespace for a particular subsystem of our application.
log = Logger("client_udp")

class UDPClientBase(DatagramProtocol):
    def __init__(self, host, port):
        super().__init__()

        self._host = host
        self._port = port
        
        # Initialise the jitter buffer
        packets_to_buffer = 3
        self._jitter_buffer = JitterBuffer(packets_to_buffer)
        self._udp_packetizer = None

        
    def startProtocol(self):
        # "Connect" this to the server
        self.transport.connect(
            self._host,
            self._port
        )

        # Initialise UDP Packetizer
        self._udp_packetizer = UDPPacketizer(
            self.transport,
            (self._host, self._port)
        )


    def datagramReceived(self, data, addr):
        #print("Received UDP packet from", addr)

        # Extract the timestamp, sequence number, and encoded frame
        timestamp, seq_no, encoded_packet = self._udp_packetizer.decode(data)

        # Put the encoded packet in the jitter buffer
        self._jitter_buffer.put_packet(seq_no, encoded_packet)

                
    # Possibly invoked if there is no server listening on the
    # address to which we are sending.
    def connectionRefused(self):
        print("No one listening; stopping")
        if reactor.running:
            log.error("STOPPING CLIENT")
            reactor.stop()



class UDPClient(UDPClientBase):
    def __init__(self, host, port):
        super().__init__(host, port)

        # Create a Stream
        self._stream = sd.Stream(
            samplerate = 48000,
            channels = 1,
            dtype = numpy.float32,
            latency = "low",#100/1000,
            callback = self._make_callback()
        )

        # Start the audio stream
        self._stream.start()

        
        
    def __del__(self):
        # Shutdown the audio stream
        print("Shutting down audio")
        self._stream.stop()
        self._stream.close()

        
    def _make_callback(self):
        # Jitter buffer is thread safe
        jitter_buffer = self._jitter_buffer

        samples_per_second = 48000 # FIXME
        frame_size_ms = 20 # ms FIXME
        
        # OpusDecoder dedicated to callback
        opus_decoder = OpusDecoder()
        opus_decoder.set_sampling_frequency(samples_per_second)
        opus_decoder.set_channels(1) #FIXME

        # OpusBufferedEncoder dedicated to callback
        opus_encoder = OpusBufferedEncoder()
        opus_encoder.set_application("audio")
        opus_encoder.set_sampling_frequency(samples_per_second)
        opus_encoder.set_channels(1) #FIXME
        opus_encoder.set_frame_size(frame_size_ms) # ms
        
        # PCM buffer dedicated to callback
        buf = None

        # Started flag dedicated to callback
        started = False
        
        def callback(indata, outdata, frames, time, status):
            nonlocal jitter_buffer
            nonlocal buf
            nonlocal started

            #print("in callback")
            
            if status:
                print(status)

            # Input
            # =====

            if indata is None:
                print("************************ indata is None ***************")
            # Convert from float32 to int16
            indata_int16 = indata * (2**15-1)
            indata_int16 = indata_int16.astype(numpy.int16)
            encoded_packets = opus_encoder.encode(indata_int16.tobytes())

            # Send the encoded packets.  Make sure not to call from
            # this thread.
            for encoded_packet in encoded_packets:
                reactor.callFromThread(self._udp_packetizer.write,
                                       encoded_packet)
                
            # Output
            # ======
            
            def decode_next_packet():
                nonlocal started

                #print("in decode_next_packet")

                encoded_packet = jitter_buffer.get_packet()

                if encoded_packet is not None:
                    # Decode the encoded packet
                    pcm = opus_decoder.decode(encoded_packet)
                    started = True
                else:
                    # Accept that we're missing the packet
                    if started:
                        print("WARNING Missing packet")
                        pcm = opus_decoder.decode_missing_packet(frame_size_ms)
                    else:
                        # We haven't even started, just output silence
                        #print("Haven't even started, return silence")
                        channels = outdata.shape[1]
                        samples = frame_size_ms * samples_per_second // 1000
                        pcm = numpy.zeros((samples, channels), dtype=numpy.int16)

                # Convert the data to floating point
                pcm_int16 = numpy.frombuffer(
                    pcm,
                    dtype = numpy.int16
                )

                pcm_float = pcm_int16.astype(numpy.float32)
                pcm_float /= 2**15
                pcm_float = numpy.reshape(pcm_float, (len(pcm_float), 1))

                # DEBUG
                if pcm_float.shape[0] != frame_size_ms * samples_per_second // 1000:
                    print("FAIL Frame size isn't the desired duration ***********************************************")
                    print(f"It's first dimension is {pcm_float.shape[0]}.")

                if pcm_float.shape[1] != 1: # channels
                    print("FAIL Frame size isn't the correct number of channels")
                
                return pcm_float

            # If there's insufficient data in buf attempt to obtain it
            # from the jitter buffer
            while buf is None or len(buf) < frames:
                if buf is None:
                    buf = decode_next_packet()
                else:
                    buf = numpy.concatenate((buf, decode_next_packet()))

            # Copy the data from the buffer remove from the buffer than which
            # we used.
            outdata[:] = buf[:frames]

            # This is INEFFICIENT and could be improved
            buf = buf[frames:]
            
        return callback



class UDPClientTester(UDPClientBase):
    def __init__(self, host, port, in_filename, out_filename):
        super().__init__(host, port)

        # Have we started receiving data from the jitter buffer
        self._started = False 

        # Open file for writing
        samples_per_second = 48000

        # Output
        print(f"Opening file '{out_filename}' for writing as wave file") 
        self._wave_write = wave.open(out_filename, "wb")
        self._wave_write.setnchannels(1) # FIXME
        self._wave_write.setsampwidth(2) # FIXME
        self._wave_write.setframerate(48000) # FIXME

        self._opus_decoder = OpusDecoder()
        self._opus_decoder.set_sampling_frequency(samples_per_second)
        self._opus_decoder.set_channels(1) #FIXME

        # Input
        self._send_packet_generator = self._get_send_packet_generator(in_filename)

        
    def startProtocol(self):
        super().startProtocol()
        
        assert self.transport is not None
        interval = 20/1000
        self.start_audio_processing_loop(interval)

        
    def process_audio_frame(self, count):
        start_time = time.time()

        # # DEBUG
        # try:
        #     counter = self.counter
        # except:
        #     self.counter = 0
        #     counter = 0
        # if counter % 20 == 0:
        #     time.sleep(250/1000)
        # self.counter += 1

            
        print("In process_audio_frame()  count:",count)

        samples_per_second = 48000 # FIXME
        frame_size_ms = 20 # FIXME


        #DEBUG
        assert self.transport is not None
        
        # Repeat count times
        for _ in range(count):
            # Send packets
            # ============
            try:
                next(self._send_packet_generator)
            except StopIteration:
                d = self.transport.stopListening()
                if d is None:
                    log.error("STOPPING CLIENT")
                    reactor.stop()
                else:
                    def on_success(data):
                        print("WARNING: In on_success. data:",str(data))
                        log.error("STOPPING CLIENT")
                        reactor.stop()
                    def on_error(data):
                        print("ERROR Failed to stop listening:"+str(data))
                    d.addCallback(on_success)
                    d.addErrback(on_error)
                return d
            
            
            # Received Packets
            # ================
            
            # Get next packet from jitter buffer
            encoded_packet = self._jitter_buffer.get_packet()

            # Decode packet
            if encoded_packet is not None:
                # Decode the encoded packet
                pcm = self._opus_decoder.decode(encoded_packet)
                self._started = True
            else:
                # Accept that we're missing the packet
                if self._started:
                    print("WARNING Missing packet")
                    pcm = self._opus_decoder.decode_missing_packet(frame_size_ms)
                else:
                    # We haven't even started, just output silence
                    #print("Haven't even started, return silence")
                    channels = 1 # FIXME
                    samples = frame_size_ms * samples_per_second // 1000
                    pcm = numpy.zeros((samples, channels), dtype=numpy.int16)

            # Save PCM into wave file
            self._wave_write.writeframes(pcm)

        end_time = time.time()
        print(f"process_audio_frame() duration: {round((end_time-start_time)*1000)} ms")

        
    def start_audio_processing_loop(self, interval=20/1000):
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

    
    def _get_send_packet_generator(self, filename):
        # Open wav file
        wave_read = wave.open(filename, "rb")
        
        # Extract the wav's specification
        channels = wave_read.getnchannels()
        print("Number of channels:", channels)
        samples_per_second = wave_read.getframerate()
        print("Sampling frequency:", samples_per_second)
        bytes_per_sample = wave_read.getsampwidth()

        # Create an Opus encoder
        opus_encoder = OpusBufferedEncoder()
        opus_encoder.set_application("audio")
        opus_encoder.set_sampling_frequency(samples_per_second)
        opus_encoder.set_channels(channels)
        opus_encoder.set_frame_size(20)

        # Calculate the desired frame size (in samples per channel)
        desired_frame_duration = 20/1000 # milliseconds
        desired_frame_size = int(desired_frame_duration * samples_per_second)

        # Loop through the wav file converting its PCM to Opus-encoded packets
        def send_packets():
            while True:
                # Get data from the wav file
                pcm = wave_read.readframes(desired_frame_size)

                # Check if we've finished reading the wav file
                if len(pcm) == 0:
                    print("client_udp: finished reading wave file")
                    break

                # Calculate the effective frame size from the number of bytes
                # read
                effective_frame_size = (
                    len(pcm) # bytes
                    // bytes_per_sample
                    // channels
                )

                # Check if we've received enough data
                if effective_frame_size < desired_frame_size:
                    # We haven't read a full frame from the wav file, so this
                    # is most likely a final partial frame before the end of
                    # the file.  We'll pad the end of this frame with silence.
                    pcm += (
                        b"\x00"
                        * ((desired_frame_size - effective_frame_size)
                           * bytes_per_sample
                           * channels)
                    )

                # Encode the PCM data
                encoded_packets = opus_encoder.encode(pcm)

                for encoded_packet in encoded_packets:
                    self._udp_packetizer.write(encoded_packet)

                yield "Not done yet"

                # # TEST: What happens if not all packets are delivered?
                # if random.random() <= 0.05:
                #     # Discard
                #     print("Discarding")
                #     pass
                # elif random.random() <= 0.7:
                #     # Reorder
                #     print("Reordering")
                #     store.append(packet)
                # else:
                #     print("Sending")
                #     # Send
                #     self.transport.write(packet)
                #     # Send all stored packets
                #     for p in random.sample(store, k=len(store)):
                #         self.transport.write(p)
                #     store = []
            print(f"Finished sending '{filename}'")

        return send_packets()
