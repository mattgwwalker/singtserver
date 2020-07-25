import collections
import threading

class JitterBuffer:
    def __init__(self, buffer_length=3):
        self._buffer_lock = threading.RLock()

        with self._buffer_lock:
            self._buffer_length = buffer_length
            
            # The value at which sequence numbers roll back to zero
            self._seq_no_rollover = 2**16

            self._reset_buffer()
            
            
    def put_packet(self, seq_no, packet):
        with self._buffer_lock:
            #print(f"jitter buffer recv'd packet number {seq_no} (buffer contains {self._get_buffer_size()} items)")

            self._started = True
            
            # If we don't know the expected sequence number, then just
            # use whatever we've received
            if self._expected_seq_no is None:
                self._expected_seq_no = seq_no

            # If this sequence number is the expected one then just
            # append it to the buffer
            if self._expected_seq_no == seq_no:
                self._buffer.append(packet)
                self._expected_seq_no += 1
                self._expected_seq_no %= self._seq_no_rollover

                # Check the out-of-order dictionary, maybe the next
                # packet is already waiting
                self._check_out_of_order_packets()
                
            else:
                # We have an out-of-order packet.  Check if it's
                # before or after the expected sequence number
                distance = self._calc_distance(
                    seq_no,
                    self._expected_seq_no
                )
                print("distance:",distance)

                # Check if the frame is too late
                if distance >= 0:
                    # Add it to the dictionary
                    print("Frame is ahead of what we were expecting; storing")
                    self._out_of_order_packets[seq_no] = packet
                else:
                    print("Frame is behind what we were expecting; discarding")
                    return

        
    def get_packet(self):
        with self._buffer_lock:
            #print(f"getting packet from jitter buffer (which contains {self._get_buffer_size()} items)")

            if not self._started:
                #print("We haven't received our first packet; ignoring get request")
                return None
            
            # If the buffer is empty, give up on the currently
            # expected sequence number and return None
            if len(self._buffer) == 0:
                self._missed_packets += 1
                print(f"jitter buffer is giving up on the expected packet number {self._expected_seq_no} (total of {self._missed_packets} packets missed)")
                self._expected_seq_no += 1
                self._check_out_of_order_packets()
                if self._missed_packets >= 3:
                    self._reset_buffer()
                return None

            # Otherwise, return the first item
            packet = self._buffer.popleft()
            return packet


    def _reset_buffer(self):
        """Resets the buffer.

        Called as part of the constructor, but also called if too many
        packets have been missed.

        """
        with self._buffer_lock:
            self._expected_seq_no = None
            self._buffer = collections.deque()
            self._out_of_order_packets = {}

            # Only after the first packet has been 'put' do we allow
            # gets
            self._started = False

            # Fill the buffer with None's up to the given buffer
            # length
            for _ in range(self._buffer_length):
                self._buffer.append(None)

            self._missed_packets = 0

        
    def _get_buffer_size(self):
        with self._buffer_lock:
            return len(self._buffer) + len(self._out_of_order_packets)

        
    def _check_out_of_order_packets(self):
        with self._buffer_lock:
            while self._expected_seq_no in self._out_of_order_packets:
                oo_packet = self._out_of_order_packets[self._expected_seq_no]
                self._buffer.append(oo_packet)
                del self._out_of_order_packets[self._expected_seq_no]
                self._expected_seq_no += 1
        

    # Calculates most likely distance between two sequence numbers
    # given that they may have rolledover.
    def _calc_distance(self, new, current):
        adjusted_new = new + self._seq_no_rollover
        adjusted_current = current + self._seq_no_rollover

        distance = new - current

        def assess(n,c):
            if abs(n-c) < abs(distance):
                return n-c
            else:
                return distance

        distance = assess(adjusted_new, current)
        distance = assess(adjusted_new, adjusted_current)
        distance = assess(new, adjusted_current)

        return distance


# OLD IMPLEMENTATION BELOW


# Jitter Buffer
# =============

# Assume that the client is a constant stream of evenly spaced
# packets.  At the destination we will create a fixed duration buffer
# (say 30ms).  The buffer is initialised with silence for the 30ms and
# the expected sequence number is set to zero.  When the first packet
# is received we start consumption.  If a packet that is received has
# the expected sequence number, it is decoded and placed into the
# PCM buffer.

class OLDJitterBuffer:
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
