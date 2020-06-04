# UDP transport of Opus audio
# Sever receives and plays back sound

from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
import pyogg
from pyogg import opus
import ctypes
import queue
import sounddevice as sd
import sys
import numpy

q = queue.Queue(maxsize=-1)


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
#samples_in_buf = samples_per_channel_in_buf * channels
TypeBuf = (ctypes.c_short*channels) * samples_per_channel_in_buf

class Echo(DatagramProtocol):

    def datagramReceived(self, data, addr):
        print("Received data from", addr)

        print("len(data):", len(data))
        #print(data)

        # Create a buffer to hold the PCM data
        buf = TypeBuf()

        # Get pointer to first element of buf
        bufPtr = ctypes.cast(buf, ctypes.POINTER(opus.opus_int16))

        # Get pointer to encoded frame
        encodedFramePtr = ctypes.cast(data, ctypes.POINTER(ctypes.c_ubyte))
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

        # Put the samples on the queue to play
        np_buf = numpy.ctypeslib.as_array(
            buf,
            (numSamples//channels, channels)
        )

        np_buf = np_buf[0:numSamples]

        print("data placed on queue")
        #print("channels:", channels)
        print("shape:",np_buf.shape)
        q.put_nowait(np_buf)
        

# One second buffer
pcm_buf = numpy.zeros((48000,2), dtype=numpy.int16)
pcm_buf_produce_index = 0
        

def callback(outdata, frames, time, status):
    global pcm_buf, pcm_buf_produce_index
    try:
        if pcm_buf_produce_index < 5000:
            data = q.get_nowait()
            print("Data found in queue")
            print("type(data):", type(data))
            print("data:", data)
            print("len(data)", len(data))
            print("shape:", data.shape)
            print("pcm_buf_produce_index:",pcm_buf_produce_index)
            pcm_buf[pcm_buf_produce_index : pcm_buf_produce_index+len(data)] = \
                data[0:len(data)]
            #print("pcm_buf (after data copied):",pcm_buf[pcm_buf_produce_index : pcm_buf_produce_index+len(data)])
            pcm_buf_produce_index += len(data)
                    
        
    except queue.Empty:
        #print("Buffer is empty")
        pass

    outdata[:] = pcm_buf[:len(outdata)]
    if pcm_buf_produce_index > 0:
        #print("pcm_buf[:len(outdata)]:", pcm_buf[:len(outdata)])
        #print("outdata:",outdata)
        pcm_buf[:len(outdata)] = [[0,0]] * len(outdata)
        pcm_buf = numpy.roll(pcm_buf, -len(outdata), axis=0)
        pcm_buf_produce_index -= len(outdata)
        if pcm_buf_produce_index < 0:
            pcm_buf_produce_index = 0
        #print("pcm_buf_produce_index:",pcm_buf_produce_index)

print("Starting Server...")
reactor.listenUDP(9999, Echo())

stream = sd.OutputStream(
    samplerate=48000,
    callback=callback,
    dtype=numpy.int16
)

with stream:
    reactor.run()
