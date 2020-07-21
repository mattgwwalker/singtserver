# UDP transport of Opus audio
# Sever receives and plays back sound
# Includes jitter buffer


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
import math
import threading

# Queue to hold PCM data sent via the network to the audio processing
# thread.
q = queue.Queue(maxsize=-1)


# Jitter Buffer
# =============

# Assume that the client is a constant stream of evenly spaced
# packets.  At the destination we will create a fixed duration buffer
# (say 30ms).  The buffer is initialised with silence for the 30ms and
# the expected sequence number is set to zero.  When the first packet
# is received we start consumption.  If a packet that is received has
# the expected sequence number, it is decoded and placed into the
# PCM buffer.

class JitterBuffer:
    # The maximum
    # length of an Opus frame is 120ms (see
    # https://tools.ietf.org/html/rfc6716).
    max_frame_duration = 120 #ms

    # The value of seq_no at which it rolls back to zero
    seq_rollover = 2**16
    
    def __init__(self,
                 buffer_duration = 30,
                 samples_per_second = 48000,
                 channels = 2,
                 samples_per_channel_per_frame = 480):
        # Create a reentrant lock so that we are threadsafe
        self.__lock = threading.RLock()

        # Aquire the lock immediately
        with self.__lock:
            # Store parameters as member variables
            self.__buffer_duration = buffer_duration
            self.__samples_per_second = samples_per_second
            self.__channels = channels
            self.__samples_per_channel_per_frame = samples_per_channel_per_frame

            # Initialise the expected sequence number to zero
            self.__expected_seq_no = 0

            # Initialise the started flag
            self.__started = False

            # Create an Opus decoder
            self.__decoder_ptr = create_decoder(
                samples_per_second,
                channels
            )

            # Calculate size of PCM buffer to hold a decoded frame
            self.__samples_per_channel_in_buf = (
                samples_per_second
                // 1000
                * JitterBuffer.max_frame_duration
            )

            # Create a class defining a PCM Frame Buffer
            self.__PCMFrameBufferType = (
                (opus.opus_int16 * channels)
                * self.__samples_per_channel_in_buf
            )

            # Create a list to store out-of-order frames
            self.__out_of_order_frames = {}

            # Put a number of silent PCM buffers into the audio queue
            num_10ms_buffers = math.ceil(buffer_duration / 10)
            for i in range(num_10ms_buffers):
                pcm_buf = numpy.zeros(
                    (samples_per_second//100,
                     channels)
                )
                q.put_nowait(pcm_buf)

                
    # Calculates most likely distance between two sequence numbers
    # given that they may have rolledover.
    def __calc_distance(new, current, rollover):
        adjusted_new = new + rollover
        adjusted_current = current + rollover

        distance = new - current

        def assess(n,c):
            nonlocal distance
            if abs(n-c) < abs(distance):
                distance = n-c

        assess(adjusted_new, current)
        assess(adjusted_new, adjusted_current)
        assess(new, adjusted_current)

        return distance

        
    def process_frame(self, encoded_frame, seq_no):
        # Aquire the lock to ensure that we're threadsafe
        with self.__lock:
            # Mark the fact that we've started
            self.__started = True
            
            # Is the sequence number the one we're expecting?  If not,
            # consider storing it for later processing.
            print("Expecting seq no",self.__expected_seq_no)
            if encoded_frame is None:
                print("Did not get seq no", seq_no)
            else:
                print("Got seq no", seq_no)

            if seq_no != self.__expected_seq_no:
                print("Found out of order frame")
                # Calculate the new frame's distance from the
                # currently expected sequence number.  Because the
                # sequence numbers may roll over, we need to account
                # for that.
                distance = JitterBuffer.__calc_distance(
                    seq_no,
                    self.__expected_seq_no,
                    JitterBuffer.seq_rollover
                )

                # Check if the frame is too late
                if distance > 0:
                    print("Frame is ahead of what we were expecting; storing")
                    self.__out_of_order_frames[seq_no] = encoded_frame
                else:
                    print("Frame is behind what we were expecting; discarding")
                    pass

                # Are there frames still in the queue?  If not, then we
                # have a problem.  The current frame isn't what we need,
                # and we're in immediate need of the one we're missing.
                # It's time to give up on the currently expected frame.
                if q.empty():
                    self.give_up_on_expected_sequence()
                
                return


            # The encoded frame is the next in the sequence, so process it
            # now.

            # Create a buffer to hold the PCM data
            pcm_buf = self.__PCMFrameBufferType()

            # Get pointer to first element of the PCM buffer
            pcm_buf_ptr = ctypes.cast(
                pcm_buf,
                ctypes.POINTER(opus.opus_int16)
            )

            # Get pointer to encoded frame
            if encoded_frame is None:
                encoded_frame_ptr = None
                encoded_frame_bytes = 0
            else:
                encoded_frame_ptr = ctypes.cast(
                    encoded_frame,
                    ctypes.POINTER(ctypes.c_ubyte)
                )
                encoded_frame_bytes = len(encoded_frame)

            # Decode the frame
            num_samples = opus.opus_decode(
                self.__decoder_ptr,
                encoded_frame_ptr,
                encoded_frame_bytes,
                pcm_buf_ptr,
                self.__samples_per_channel_in_buf,
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

            # We can now expect the next sequence number
            self.__expected_seq_no += 1

            # If the next frame is already in the out-of-order dictionary,
            # process it now
            seq_no = self.__expected_seq_no
            if (seq_no in self.__out_of_order_frames):
                print("Processing previously stored, out-of-order, frame")
                self.process_frame(
                    self.__out_of_order_frames[seq_no],
                    seq_no
                )
                del self.__out_of_order_frames[seq_no]

            
    # Give up on the currently awaited sequence number and ask the
    # decoder to guess at what it should be.
    def give_up_on_expected_sequence(self):
        # Acquire the lock to ensure we're threadsafe
        with self.__lock:
            # Check that we've started
            if self.__started:
                print("Giving up on seq no",self.__expected_seq_no)
                self.process_frame(None, self.__expected_seq_no)

            # Return the started flag to share if we've put anything
            # on the queue.
            return self.__started
            
        



# Decoding
# ========

# Number of channels to decode to.  It's reasonable that backing
# tracks might be in stereo and we might even play with placing
# people in virtual locations (OpenAL).
channels = 2




class PlayOpusStream(DatagramProtocol):
    def __init__(self, samples_per_second, channels):
        super().__init__()

        buffer_duration = 30 #ms
        self.jitter_buffer = JitterBuffer(
            buffer_duration,
            samples_per_second,
            channels
        )

        
    def datagramReceived(self, data, addr):
        #print("Received UDP packet from", addr)

        # TODO: Once we've started receiving data from a given
        
        # address, should we close down this port to other addresses?
        # Extract the timestamp (4 bytes), sequence number (2 bytes),
        # and encoded frame (remainder)
        timestamp = data[0:4]
        seq_no = data[4:6]
        encoded_frame = data[6:]

        seq_no = int.from_bytes(seq_no ,"little")
        print("\n",seq_no)
        
        self.jitter_buffer.process_frame(
            encoded_frame,
            seq_no
        )
        
        

# Function to create the audio callback.  This is used to protect the
# variables that are out of the callback's scope.
def make_callback(jitter_buffer):
    # Allocate a one second buffer for PCM data
    pcm_buf = numpy.zeros((samples_per_second,channels),
                          dtype=numpy.int16)
    pcm_buf_produce_index = 0


    # Audio callback that plays back the decoded PCM data.  
    def callback(outdata, frames, time, status):
        nonlocal pcm_buf, pcm_buf_produce_index

        # If the buffer is getting low, attempt to get decoded PCM
        # data from the queue.  Copy the queue's PCM data to the
        # one-second buffer.
        if pcm_buf_produce_index < 5000:
            data = None
            try:
                data = q.get_nowait() # may raise exception
            except queue.Empty:
                # Force the generation of a frame onto the queue.
                if jitter_buffer.give_up_on_expected_sequence():
                    data = q.get_nowait() 

            # Copy the queue's data if it's valid.
            if data is not None:
                # Copy the quque's PCM data to the one-second buffer
                pcm_buf[pcm_buf_produce_index : pcm_buf_produce_index+len(data)] = \
                    data[0:len(data)]
                pcm_buf_produce_index += len(data)


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



# Specify configuration of sound to output
samples_per_second = 48000
channels = 2


# Create our UDP server
print("Starting Server...")
protocol = PlayOpusStream(samples_per_second, channels)
reactor.listenUDP(9999, protocol)


# Create an output stream
stream = sd.OutputStream(
    samplerate=samples_per_second,
    callback=make_callback(protocol.jitter_buffer),
    dtype=numpy.int16
)


# Run the server with the audio callback being reguarly fired on
# another thread.
with stream:
    reactor.run()
