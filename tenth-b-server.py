# UDP transport of Opus audio
# Sever receives and plays back sound

from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
import pyogg
from pyogg import opus
import ctypes

def createDecoder(freq, channels):
    # Just as with the encoder, to create a decoder, we must first
    # allocate resources for it.  We want Python to be responsible for
    # the memory deallocation, and thus Python must be responsible for
    # the initial memory allocation.

    # The frequency must be passed in as a 32-bit int
    freq = opus.opus_int32(freq)

    # The number of channels must also be passed in as a 32-bit int
    channels = opus.opus_int32(channels)
    
    # Obtain the number of bytes of memory required for the decoder
    size = opus.opus_decoder_get_size(channels);

    # Allocate the required memory for the decoder
    memory = ctypes.create_string_buffer(size)

    # Cast the newly-allocated memory as a pointer to a decoder.  We
    # could also have used opus.od_p as the pointer type, but writing
    # it out in full may be clearer.
    decoder = ctypes.cast(memory, ctypes.POINTER(opus.OpusDecoder))

    # Initialise the decoder
    error = opus.opus_decoder_init(decoder, freq, channels);

    # Check that there hasn't been an error when initialising the
    # decoder
    if error != opus.OPUS_OK:
        raise Exception("An error occurred while creating the decoder: "+
                        opus.opus_strerror(error).decode("utf"))

    # Return our newly-created decoder
    return decoder


# Decoding
# ========

# FIXME: How to get the number of channels?
channels = 2


# Create a decoder
decoderFreq = 48000 # TODO: Test changes to this
decoderPtr = createDecoder(decoderFreq,
                           channels)
                                       

# Calculate size of PCM buffer
max_frame_duration = 120 # ms (See https://tools.ietf.org/html/rfc6716)
samples_per_second = 48000
samples_per_channel_in_buf = samples_per_second // 1000 * max_frame_duration
samples_in_buf = samples_per_channel_in_buf * channels
TypeBuf = ctypes.c_short * samples_in_buf

class Echo(DatagramProtocol):

    def datagramReceived(self, data, addr):
        print("Received data from %s" % addr)

        # Create a buffer to hold the PCM data
        buf = TypeBuf()

        # Get pointer to first element of buf
        bufPtr = ctypes.cast(buf, ctypes.POINTER(opus.opus_int16))

        # Get pointer to encoded frame
        encodedFramePtr = ctypes.cast(data, ctypes.POINTER(ctype.c_ubyte))
        numBytes = len(data)
        
        # Decode the frame
        numSamples = opus.opus_decode(
            decoderPtr,
            encodedFramePtr,
            numBytes,
            bufPtr,
            samples_per_channel_in_buf,
            0 # FIXME: What's this about?
        )
        print("numSamples: ",numSamples)
        
        # Check for any errors during decoding
        if numSamples < 0:
            raise Exception("Decoder error detected: "+
                            opus.opus_strerror(numSamples).decode("utf"))

        # TODO: Play decoded frame

        

print("Starting Server...")
reactor.listenUDP(9999, Echo())
reactor.run()
