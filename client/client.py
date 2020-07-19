import json
import struct
import sys
import time
import threading
import queue
import wave

import numpy
from pyogg import OpusEncoder
from pyogg import OpusDecoder
import sounddevice as sd
from twisted.internet import reactor
from twisted.internet.endpoints import TCP4ClientEndpoint, connectProtocol
from twisted.internet.protocol import DatagramProtocol
from twisted.internet.protocol import Protocol

q = queue.Queue()

class TCPClient(Protocol):
    def __init__(self, name):
        super()
        self._name = name

        print("Client started")

    def connectionMade(self):
        data = {
            "command":"announce",
            "username": self._name
        }
        msg = json.dumps(data) 
        self.sendMessage(msg)

    def connectionLost(self, reason):
        print("Connection lost:", reason)
        if reactor.running:
            reactor.stop()
        
    def sendMessage(self, msg):
        msg_as_bytes = msg.encode("utf-8")
        len_as_short = struct.pack("H", len(msg))
        encoded_msg = len_as_short + msg_as_bytes
        self.transport.write(encoded_msg)

    def dataReceived(self, data):
        print("data received:", data)



# Open opus file and sent it to server
class UDPClient(DatagramProtocol):
    def __init__(self):
        super().__init__()

        # Initialise the decoder
        self._opus_decoder = OpusDecoder()
        self._opus_decoder.set_channels(1) # Mono
        self._opus_decoder.set_sampling_frequency(48000)

        # Initialise the wave_write
        filename = "out.wav"
        self._wave_write = wave.open(filename, "wb")
        self._wave_write.setnchannels(1)
        self._wave_write.setsampwidth(2)
        self._wave_write.setframerate(48000)

    
    def startProtocol(self):
        host = sys.argv[1]
        port = 12345

        self.transport.connect(host, port)

        sequence_no = 0

        store = []

        # Open wav file
        #filename = "../left-right-demo-5s.wav"
        filename = "../gs-16b-2c-44100hz.wav"
        wave_read = wave.open(filename, "rb")
        
        # Extract the wav's specification
        channels = wave_read.getnchannels()
        print("Number of channels:", channels)
        samples_per_second = wave_read.getframerate()
        print("Sampling frequency:", samples_per_second)
        bytes_per_sample = wave_read.getsampwidth()

        # Create an Opus encoder
        opus_encoder = OpusEncoder()
        opus_encoder.set_application("audio")
        opus_encoder.set_sampling_frequency(samples_per_second)
        opus_encoder.set_channels(channels)

        # Calculate the desired frame size (in samples per channel)
        desired_frame_duration = 20/1000 # milliseconds
        desired_frame_size = int(desired_frame_duration * samples_per_second)

        # Loop through the wav file converting its PCM to Opus-encoded packets 
        while True:
            # Get data from the wav file
            pcm = wave_read.readframes(desired_frame_size)

            # Check if we've finished reading the wav file
            if len(pcm) == 0:
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
            encoded_packet = opus_encoder.encode(pcm)

            # Insert timestamp and sequence number before
            # encoded frame
            # INEFFICIENT: This copies the PCM data
            current_time = int(time.monotonic()*1000) % (2**32-1)
            packet = (
                struct.pack(">I", current_time)
                + struct.pack(">H", sequence_no)
                + encoded_packet
            )

            # # TEST: What happens if not all packets are delivered?
            # if random.random() <= 0:
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

            self.transport.write(packet)

            sequence_no += 1

            
    def datagramReceived(self, data, addr):
        #print("Received UDP packet from", addr)

        # Extract the timestamp (4 bytes), sequence number (2 bytes),
        # and encoded frame (remainder)
        timestamp = data[0:4]
        seq_no = data[4:6]
        encoded_packet = data[6:]

        seq_no = int.from_bytes(seq_no ,"big")

        # Decode the encoded packet
        pcm = self._opus_decoder.decode(encoded_packet)

        # Write the PCM to the wav file
        self._wave_write.writeframes(pcm)

        # Convert the data to floating point
        pcm_int16 = numpy.frombuffer(
            pcm,
            dtype = numpy.int16
        )

        # DEBUG
        #print("pcm:", pcm[0:10])
        #print("pcm_int16:", pcm_int16[0:5])
        #assert pcm[0] == pcm_int16[0]
        
        pcm_float = pcm_int16.astype(numpy.float32)
        pcm_float /= 2**15
        pcm_float = numpy.reshape(pcm_float, (len(pcm_float), 1))
        #print("pcm_float:", pcm_float[0:5])

        q.put_nowait(pcm_float)

        
    # Possibly invoked if there is no server listening on the
    # address to which we are sending.
    def connectionRefused(self):
        print("No one listening")


# Create output stream
buf = None
def callback(outdata, frames, time, status):
    global buf 

    # Attempt to get data from queue
    while True:
        try:
            pcm = q.get_nowait()
        except queue.Empty:
            break

        # Push data to buf
        if buf is None:
            buf = pcm
        else:
            buf = numpy.concatenate((buf, pcm))

    # If there's no data in the buf, fill the output with zeros
    if buf is None:
        print("WARNING No data in buffer")
        outdata.fill(0)
        return

    # If there's some data, but not enough, take what's available and
    # fill the rest with zeros.
    if len(buf) < frames:
        print("WARNING Insufficient data in buffer")
        outdata[:len(buf)] = buf[:]
        outdata[len(buf):].fill(0)
        buf = None
        return

    # Otherwise, if there's more than enough data, copy all that's
    # needed and remove that much from the buffer.
    outdata[:] = buf[:frames]
    buf = buf[frames:]

    
stream = sd.OutputStream(
    samplerate = 48000,
    channels = 1,
    dtype = numpy.float32,
    latency = 100/1000,
    callback = callback
)
    
if __name__=="__main__":
    print("What is your name?")
    name = input()

    # TCP
    # ===
    address = sys.argv[1]
    point = TCP4ClientEndpoint(reactor, address, 1234)

    client = TCPClient(name)
    d = connectProtocol(point, client)
    
    def err(failure):
        print("An error occurred:", failure)

    d.addErrback(err)

    # UDP
    # ===

    # 0 means any port, we don't care in this case
    reactor.listenUDP(0, UDPClient())

    
    print("Running reactor")
    with stream:
        reactor.run()

