from pyogg import opus
import ctypes

def create_decoder(freq, channels):
    # To create a decoder, we must first allocate resources for it.
    # We want Python to be responsible for the memory deallocation,
    # and thus Python must be responsible for the initial memory
    # allocation.

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



# Create an encoder
def create_encoder(npBufSource, samples_per_second):
    # To create an encoder, we must first allocate resources for it.
    # We want Python to be responsible for the memory deallocation,
    # and thus Python must be responsible for the initial memory
    # allocation.

    # Opus can encode both speech and music, and it can automatically
    # detect when the source swaps between the two.  Here we specify
    # automatic detection.
    application = opus.OPUS_APPLICATION_AUDIO

    # The frequency must be passed in as a 32-bit int
    samples_per_second = opus.opus_int32(samples_per_second)

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
    error = opus.opus_encoder_init(
        encoder,
        samples_per_second,
        channels,
        application
    )

    # Check that there hasn't been an error when initialising the
    # encoder
    if error != opus.OPUS_OK:
        raise Exception("An error occurred while creating the encoder: "+
                        opus.opus_strerror(error).decode("utf"))

    # Return our newly-created encoder
    return encoder
