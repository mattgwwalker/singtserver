import time
import struct
import wave

import numpy
from pyogg import OpusEncoder
from pyogg import OpusBufferedEncoder
from pyogg import OpusDecoder
from twisted.internet import task
from twisted.internet.protocol import DatagramProtocol
import sounddevice as sd

from singt.jitter_buffer import JitterBuffer


# Open opus file and send it to server
class UDPClient(DatagramProtocol):
    def __init__(self, host, port):
        super().__init__()

        self._host = host
        self._port = port
        
        # Initialise the jitter buffer
        packets_to_buffer = 3
        self._jitter_buffer = JitterBuffer(packets_to_buffer)

        # Start with sequence number zero
        self._sequence_no = 0

        # Create an OutputStream
        self._stream = sd.OutputStream(
            samplerate = 48000,
            channels = 1,
            dtype = numpy.float32,
            latency = 100/1000,
            callback = self._make_callback()
        )

        # Start the audio stream
        self._stream.start()

        
    def __del__(self):
        # Shutdown the audio stream
        print("Shutting down audio")
        self._stream.stop()
        self._stream.close()

        
    def startProtocol(self):
        # "Connect" this to the server
        self.transport.connect(
            self._host,
            self._port
        )

        store = []

        self._send_file()


    def sendEncodedPacket(self, encoded_packet):
        # Insert timestamp and sequence number before
        # encoded frame
        # INEFFICIENT: This copies the PCM data
        current_time = int(time.monotonic()*1000) % (2**32-1)
        packet = (
            struct.pack(">I", current_time)
            + struct.pack(">H", self._sequence_no)
            + encoded_packet
        )
        
        self.transport.write(packet)
        print(f"client_udp: sent sequence no {self._sequence_no}")
        
        self._sequence_no += 1

        
    def datagramReceived(self, data, addr):
        #print("Received UDP packet from", addr)

        # Extract the timestamp (4 bytes), sequence number (2 bytes),
        # and encoded frame (remainder)
        timestamp, seq_no = struct.unpack(">IH", data[0:6])
        encoded_packet = data[6:]

        self._jitter_buffer.put_packet(seq_no, encoded_packet)

        

        
    # Possibly invoked if there is no server listening on the
    # address to which we are sending.
    def connectionRefused(self):
        print("No one listening")


    def _send_file(self):
        # Open wav file
        #filename = "../../left-right-demo-5s.wav"
        filename = "../../gs-16b-2c-44100hz.wav"
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
                    self.sendEncodedPacket(encoded_packet)

                yield self._sequence_no

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

        # Install as cooperative task
        
        cooperative_task = task.cooperate(send_packets())

        return cooperative_task.whenDone()
            


    def _make_callback(self):
        # Jitter buffer is thread safe
        jitter_buffer = self._jitter_buffer

        # OpusDecoder dedicated to callback
        opus_decoder = OpusDecoder()
        opus_decoder.set_sampling_frequency(48000) #FIXME
        opus_decoder.set_channels(1) #FIXME

        
        # PCM buffer dedicated to callback
        buf = None

        # Started flag dedicated to callback
        started = False
        
        def callback(outdata, frames, time, status):
            nonlocal jitter_buffer
            nonlocal buf
            nonlocal started

            #print("in callback")
            
            if status:
                print(status)
                
            def decode_next_packet():
                nonlocal started

                #print("in decode_next_packet")
                # Output
                # ======

                encoded_packet = jitter_buffer.get_packet()

                if encoded_packet is not None:
                    # Decode the encoded packet
                    pcm = opus_decoder.decode(encoded_packet)
                    started = True
                else:
                    # Accept that we're missing the packet
                    if started:
                        assumed_frame_duration = 20 # milliseconds FIXME
                        print("WARNING Missing packet")
                        pcm = opus_decoder.decode_missing_packet(assumed_frame_duration)
                    else:
                        # We haven't even started, just output silence
                        print("Haven't even started, just output silence")
                        return numpy.zeros(outdata.shape)


                # Convert the data to floating point
                pcm_int16 = numpy.frombuffer(
                    pcm,
                    dtype = numpy.int16
                )

                pcm_float = pcm_int16.astype(numpy.float32)
                pcm_float /= 2**15
                pcm_float = numpy.reshape(pcm_float, (len(pcm_float), 1))

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
