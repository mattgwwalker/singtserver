# UDP transport of Opus encoded audio
# Client sends
# Added timestamp and sequence number into UDP packet
# Swapped song playback for microphone (see ninth-c.py)

from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
import pyogg
from pyogg import opus
import numpy
import ctypes
from datetime import datetime
import sounddevice as sd
import time
from opus_helpers import create_encoder
import struct
import random


# Gain
# ====

# Automatic gain for the "discussion" mode can come later.  For the
# meantime, measure peak usage while talking loudly before we start.


# Calculate maximum absolute volume of a buffer
def get_max_abs_volume(buffer):
    max_volume = numpy.amax(buffer)
    min_volume = numpy.amin(buffer)

    max_abs_volume = max(max_volume,
                         -min_volume)

    return max_abs_volume


# Detect the maximum volume of the microphone during example usage
max_abs_input = 0
def detectMax(indata, frames, time, status):
    """This is called (from a separate thread) for each audio block."""
    global max_abs_input
    
    if status:
        print(status, file=sys.stderr)

    max_abs_frame = get_max_abs_volume(indata)
    
    if max_abs_frame > max_abs_input:
        print("Peak detected at",
              round(100 * max_abs_frame, 1),"% of input's full scale")
        max_abs_input = max_abs_frame

# Measure the expected maximum volume of microphone's input
duration = 2 # seconds
print("\nPlease use the microphone at the loudest level you expect.")
print("You have", duration, "seconds...")
with sd.InputStream(callback=detectMax, dtype=numpy.float32):
    sd.sleep(int(duration * 1000))


# Check that we've got an acceptable gain
if (max_abs_input < 0.03):
    raise Exception("Extremely low gain detected; aborting.")



exit()

# Encoding
# ========

# Extract the number of channels in the source
source_channels = np_buf_source.shape[1]

    
# Create an encoder
encoder = create_encoder(np_buf_source, samples_per_second)

    
# Frame sizes are measured in number of samples.  There are only a
# specified number of possible valid frame durations for Opus,
# which (assuming a frequency of 48kHz) gives the following valid
# sizes.
frame_sizes = [120, 240, 480, 960, 1920, 2880]

    
# Specify the desired frame size.  This will be used for the vast
# majority of the encoding, except possibly at the end of the
# buffer (as there may not be sufficient data left to fill a
# frame.)
frame_size_index = 5
frame_size = frame_sizes[frame_size_index]


# Function to calculate the size of a frame in bytes
def frame_size_bytes(frame_size):
    return frame_size * source_channels * bytes_per_sample

    
# Allocate storage space for the encoded frame.  4,000 bytes is
# the recommended maximum buffer size for the encoded frame.
max_encoded_frame_bytes = opus.opus_int32(4000)
EncodedFrameType = ctypes.c_ubyte * max_encoded_frame_bytes.value
encoded_frame = EncodedFrameType()


# Create a pointer to the first byte of the buffer for the encoded
# frame.
encoded_frame_ptr = ctypes.cast(ctypes.pointer(encoded_frame),
                                ctypes.POINTER(ctypes.c_ubyte))

    
# Number of bytes to process in buffer
length_bytes = (np_buf_source.shape[0]
                * np_buf_source.shape[1]
                * bytes_per_sample)


# Pointer to a location in the source buffer.  We will increment
# this as we progress through the encoding of the buffer.  It
# starts pointing to the first byte.
source_ptr = np_buf_source.ctypes.data_as(ctypes.c_void_p)
source_ptr_init = source_ptr


# The number of bytes processed will be the difference between the
# pointer's current location and the address of the first byte.
bytesProcessed = source_ptr.value - source_ptr_init.value




def encode_next_frame(source_ptr):
    global length_bytes, bytesProcessed, frame_size, frame_sizes, frame_size_index
    
    if bytesProcessed >= length_bytes:
        print("WARNING: No more data")
        return None
        
    print("Processing frame at source_ptr ", source_ptr.value)
    
    # Check if we have enough source data remaining to process at
    # the current frame size
    print("length_bytes: ",length_bytes)
    print("bytesProcessed: ",bytesProcessed)
    print("bytes remaining (length_bytes - bytesProcessed):",length_bytes - bytesProcessed)
    print("frameSizeBytes(frame_size):", frame_size_bytes(frame_size))
    while length_bytes - bytesProcessed < frame_size_bytes(frame_size):
        print("Warning! Not enough data for frame.")
        frame_size_index -= 1
        if frame_size_index < 0:
            # The data is less than the smallest number of samples
            # in a frame.  Either we ignore the remaining samples
            # and shorten the audio, or we pad the frame with
            # zeros and lengthen the audio.  We'll take the easy
            # option and shorten the audio.
            break
        frame_size = frame_sizes[frame_size_index]
        print("Decreased frame size to ",frame_size)
        
    if frame_size_index < 0:
        print("Warning! Ignoring samples at the end of the audio\n"+
              "as they do not fit into even the smallest frame.")
        # FIXME: This last frame probably isn't correct
        return
        
    # Encode the audio
    print("Encoding audio")
    numBytes = opus.opus_encode(
        encoder,
        ctypes.cast(source_ptr, ctypes.POINTER(opus.opus_int16)),
        frame_size,
        encoded_frame_ptr,
        max_encoded_frame_bytes
    )
    print("numBytes: ", numBytes)
    
    # Check for any errors during encoding
    if numBytes < 0:
        raise Exception("Encoder error detected: "+
                        opus.opus_strerror(numBytes).decode("utf"))
    
    # Move to next position in the buffer: encoder
    oldAddress = source_ptr.value
    #print("oldAddress:",oldAddress)
    deltaBytes = frame_size*source_channels*2
    newAddress = oldAddress + deltaBytes
    #print("newAddress:",newAddress)
    source_ptr = ctypes.c_void_p(newAddress)

    bytesProcessed = source_ptr.value - source_ptr_init.value

    return (source_ptr, encoded_frame_ptr, numBytes)







class SendOpusStream(DatagramProtocol):
    def startProtocol(self):
        global source_ptr, encoded_frame_ptr
        
        host = "127.0.0.1"
        port = 9999

        self.transport.connect(host, port)


        sequence_no = 0

        store = []
        
        # TODO: Implement this!
        while True:
            source_ptr, encoded_frame_ptr, num_bytes = encode_next_frame(source_ptr)

            # INEFFICIENT: Insert timestamp and sequence number before
            # encoded frame (copies encoded frame)
            current_time = int(time.monotonic()*1000) % (2**32-1)
            timestamp = struct.pack(">I", current_time)
            packet = (timestamp
                      + bytes(ctypes.c_short(sequence_no))
                      + bytes(encoded_frame_ptr[0:num_bytes]))

            # TEST: What happens if not all packets are delivered?
            if random.random() <= 0:
                # Discard
                print("Discarding")
                pass
            elif random.random() <= 0.7:
                # Reorder
                print("Reordering")
                store.append(packet)
            else:
                print("Sending")
                # Send
                self.transport.write(packet)

                # Send all stored packets
                for p in random.sample(store, k=len(store)):
                    self.transport.write(p)

                store = []
                    

            #self.transport.write(packet)
            #break #FIXME

            sequence_no += 1

            
    def datagramReceived(self, data, addr):
        print("received %r from %s" % (data, addr))

    # Possibly invoked if there is no server listening on the
    # address to which we are sending.
    def connectionRefused(self):
        print("No one listening")

# 0 means any port, we don't care in this case
reactor.listenUDP(0, SendOpusStream())
reactor.run()

