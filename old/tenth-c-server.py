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
from opus_helpers import create_decoder


q = queue.Queue(maxsize=-1)




# Decoding
# ========

# Number of channels to decode to.  It's reasonable that backing
# tracks might be in stereo and we might even play with placing
# people in virtual locations (OpenAL).
channels = 2

# TODO: The sample rate is fixed here at 48kHz.  This seems to be the
# base choice of iOS, Android and Windows.  It's certainly not a
# problem on my Mac.  If the backing track is provided at a different
# sample rate, then it will have to be upsampled.
samples_per_second = 48000 # samples per second

# Create a decoder
decoder_ptr = create_decoder(samples_per_second,
                             channels)
                                       
# Calculate size of PCM buffer to hold a decoded frame.  The maximum
# length of an Opus frame is 120ms (see
# https://tools.ietf.org/html/rfc6716).  
max_frame_duration = 120 # ms 
samples_per_channel_in_buf = (samples_per_second // 1000
                              * max_frame_duration)
PCMBufType = (opus.opus_int16*channels) * samples_per_channel_in_buf



class PlayOpusStream(DatagramProtocol):

    def datagramReceived(self, encoded_frame, addr):
        #print("Received data from", addr)

        # TODO: Once we've started receiving data from a given
        # address, should we close down this port to other addresses?

        # Create a buffer to hold the PCM data
        pcm_buf = PCMBufType()

        # Get pointer to first element of the PCM buffer
        pcm_buf_ptr = ctypes.cast(pcm_buf, ctypes.POINTER(opus.opus_int16))

        # Get pointer to encoded frame
        encoded_frame_ptr = ctypes.cast(encoded_frame, ctypes.POINTER(ctypes.c_ubyte))
        encoded_frame_bytes = len(encoded_frame)
        
        # Decode the frame
        num_samples = opus.opus_decode(
            decoder_ptr,
            encoded_frame_ptr,
            encoded_frame_bytes,
            pcm_buf_ptr,
            samples_per_channel_in_buf,
            0 # FIXME: What's this about?
        )
        
        # Check for any errors during decoding
        if num_samples < 0:
            raise Exception("Decoder error detected: "+
                            opus.opus_strerror(numSamples).decode("utf"))

        # Create a numpy array to hold the decoded PCM data.  Note
        # that the numpy array has the correct shape (whereas the
        # original PCM buffer had sufficient space allocated for the
        # largest possible frame.
        np_pcm_buf = numpy.ctypeslib.as_array(
            pcm_buf,
            (num_samples//channels, channels)
        )
        np_pcm_buf = np_pcm_buf[0:num_samples]
        
        # Put the samples on the queue to play
        q.put_nowait(np_pcm_buf)
        

# Function to create the audio callback.  This is used to protect the
# variables that are out of the callback's scope.
def make_callback():
    # Allocate a one second buffer for PCM data
    pcm_buf = numpy.zeros((samples_per_second,channels),
                          dtype=numpy.int16)
    pcm_buf_produce_index = 0


    # Audio callback that plays back the decoded PCM data.  
    def callback(outdata, frames, time, status):
        nonlocal pcm_buf, pcm_buf_produce_index
        try:
            # If the buffer is getting low, attempt to get decoded PCM
            # data from the queue.  Copy the queue's PCM data to the
            # one-second buffer.
            if pcm_buf_produce_index < 5000:
                data = q.get_nowait() # may raise exception
                pcm_buf[pcm_buf_produce_index : pcm_buf_produce_index+len(data)] = \
                    data[0:len(data)]
                pcm_buf_produce_index += len(data)

        # It's possible the buffer is empty.  There's nothing we can
        # do about that other than perhaps issue a warning.  Instead,
        # if we run out of audio we just send zeros to the output.
        except queue.Empty:
            pass

        # Copy the PCM data from the one second buffer to the output.
        outdata[:] = pcm_buf[:len(outdata)]

        # If the buffer isn't empty then we need to shift the
        # remaining data down.
        if pcm_buf_produce_index > 0:
            # Overwrite the played data with zeros (as they will wrap
            # around with the roll)
            pcm_buf[:len(outdata)] = [[0,0]] * len(outdata)

            # Roll the buffered PCM data down
            pcm_buf = numpy.roll(pcm_buf, -len(outdata), axis=0)
            pcm_buf_produce_index -= len(outdata)
            if pcm_buf_produce_index < 0:
                pcm_buf_produce_index = 0

    # Return the callback closure
    return callback


# Create an output stream
stream = sd.OutputStream(
    samplerate=samples_per_second,
    callback=make_callback(),
    dtype=numpy.int16
)


# Create our UDP server
print("Starting Server...")
reactor.listenUDP(9999, PlayOpusStream())


# Run the server with the audio callback being reguarly fired on
# another thread.
with stream:
    reactor.run()
