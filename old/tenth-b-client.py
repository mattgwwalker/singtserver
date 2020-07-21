# UDP transport of Opus encoded audio
# Client sends


from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
import pyogg
from pyogg import opus
import numpy
import ctypes
from datetime import datetime
import sounddevice as sd
import time # sleep


# Step one, get PCM data from a Ogg Opus file
# ===========================================

# Display the version of the Opus library
version = opus.opus_get_version_string()
print("Opus library version: "+
      str(version.decode('utf-8')))


# Specify the file containing Opus audio
#filename = "ff-16b-2c-44100hz.opus"
#filename = "gs-16b-1c-44100hz.opus"
#filename = "gs-16b-2c-44100hz.opus"
filename = "left-right-demo-5s.opus"


# Read the Opus file and place the PCM in a memory buffer
print("Reading Opus file...")
opus_file = pyogg.OpusFile(filename)


# Display information about the file
print("\nRead Opus file")
print("Channels:"+str(opus_file.channels))
print("Frequency:"+str(opus_file.frequency))
print("Buffer Length (bytes): "+str(opus_file.buffer_length))


# The buffer holds the entire song in memory, however the shape of the
# array isn't obvious.  Note that the above buffer length is in bytes,
# but the PCM values are stored in two-byte ints (shorts).
bytes_per_sample = ctypes.sizeof(opus_file.buffer.contents)
samples_per_channel = \
    opus_file.buffer_length// \
    bytes_per_sample// \
    opus_file.channels
np_buf_source = numpy.ctypeslib.as_array(
    opus_file.buffer,
    (samples_per_channel, opus_file.channels)
)


# Common frequency
freq = opus_file.frequency


# The shape of the NumPy buffer is now measured in units of (number of
# samples, number of channels)
print("Buffer Shape (number of samples, number of channels):", np_buf_source.shape)


# The duration, in seconds, can now be found by dividing the number of
# samples by the frequency
buffer_duration = np_buf_source.shape[0]/opus_file.frequency
print("Duration of buffer (seconds): ",
      buffer_duration)


# Function to play Numpy PCM buffers
def play_numpy_buffer(npBuf, freq=48000):
    print("\nPlaying...")
    start_time = datetime.now()
    sd.play(npBuf, freq)
    sd.wait()  # Wait until sound has finished playing
    end_time = datetime.now()
    print("Duration: "+str(end_time - start_time))
    

# Play our newly-loaded audio, if desired
if False:
    play_numpy_buffer(np_buf_source)






# Create an encoder
def create_encoder(npBufSource, freq):
    # To create an encoder, we must first allocate resources for it.
    # We want Python to be responsible for the memory deallocation,
    # and thus Python must be responsible for the initial memory
    # allocation.

    # Opus can encode both speech and music, and it can automatically
    # detect when the source swaps between the two.  Here we specify
    # automatic detection.
    application = opus.OPUS_APPLICATION_AUDIO

    # The frequency must be passed in as a 32-bit int
    freq = opus.opus_int32(freq)

    # The number of channels can be obtained from the shape of the
    # NumPy array that was passed in as npBufSource
    channels = npBufSource.shape[1]

    # Obtain the number of bytes of memory required for the encoder
    size = opus.opus_encoder_get_size(channels);

    # Allocate the required memory for the encoder
    memory = ctypes.create_string_buffer(size)

    # Cast the newly-allocated memory as a pointer to an encoder.  We
    # could also have used opus.oe_p as the pointer type, but writing
    # it out in full may be clearer.
    encoder = ctypes.cast(memory, ctypes.POINTER(opus.OpusEncoder))

    # Initialise the encoder
    error = opus.opus_encoder_init(encoder, freq, channels, application);

    # Check that there hasn't been an error when initialising the
    # encoder
    if error != opus.OPUS_OK:
        raise Exception("An error occurred while creating the encoder: "+
                        opus.opus_strerror(error).decode("utf"))

    # Return our newly-created encoder
    return encoder






# Encoding
# ========

# Extract the number of channels in the source
source_channels = np_buf_source.shape[1]

    
# Create an encoder
encoder = create_encoder(np_buf_source, freq)

    
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
    global bytes_per_sample
    return frame_size * source_channels * bytes_per_sample

    
# Allocate storage space for the encoded frame.  4,000 bytes is
# the recommended maximum buffer size for the encoded frame.
max_encoded_frame_bytes = opus.opus_int32(4000)
TypeEncodedFrame = ctypes.c_ubyte * max_encoded_frame_bytes.value
encoded_frame = TypeEncodedFrame()


# Create a pointer to the first byte of the buffer for the encoded
# frame.
encoded_frame_ptr = ctypes.cast(ctypes.pointer(encoded_frame),
                                ctypes.POINTER(ctypes.c_ubyte))

    
# Number of bytes to process in buffer
length_bytes = np_buf_source.shape[0] * np_buf_source.shape[1] * bytes_per_sample






# Pointer to a location in the source buffer.  We will increment
# this as we progress through the encoding of the buffer.  It
# starts pointing to the first byte.
sourcePtr = np_buf_source.ctypes.data_as(ctypes.c_void_p)
sourcePtr_init = sourcePtr


# The number of bytes processed will be the difference between the
# pointer's current location and the address of the first byte.
bytesProcessed = sourcePtr.value - sourcePtr_init.value





def encode_next_frame(sourcePtr):
    global length_bytes, bytesProcessed, frame_size, frame_sizes, frame_size_index
    
    if bytesProcessed >= length_bytes:
        print("WARNING: No more data")
        return None
        
    print("Processing frame at sourcePtr ", sourcePtr.value)
    
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
        ctypes.cast(sourcePtr, ctypes.POINTER(opus.opus_int16)),
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
    oldAddress = sourcePtr.value
    #print("oldAddress:",oldAddress)
    deltaBytes = frame_size*source_channels*2
    newAddress = oldAddress + deltaBytes
    #print("newAddress:",newAddress)
    sourcePtr = ctypes.c_void_p(newAddress)

    bytesProcessed = sourcePtr.value - sourcePtr_init.value

    return (sourcePtr, encoded_frame_ptr, numBytes)







class SendOpusStream(DatagramProtocol):
    def startProtocol(self):
        global sourcePtr, encoded_frame_ptr
        
        host = "127.0.0.1"
        port = 9999

        self.transport.connect(host, port)



        
        # TODO: Implement this!
        while True:
            sourcePtr, encoded_frame_ptr, num_bytes = encode_next_frame(sourcePtr)

            # Create numpy array from encoded frame
            np_frame = numpy.ctypeslib.as_array(
                encoded_frame_ptr,
                (num_bytes,)
            )
            
            self.transport.write(np_frame)
            #break #FIXME

            
    def datagramReceived(self, data, addr):
        print("received %r from %s" % (data, addr))

    # Possibly invoked if there is no server listening on the
    # address to which we are sending.
    def connectionRefused(self):
        print("No one listening")

# 0 means any port, we don't care in this case
reactor.listenUDP(0, SendOpusStream())
reactor.run()

