# Given a backing track, records while playing the backing track,
# saving the result to and OggOpus file.

import pyogg
from pyogg import opus
from pyogg import ogg
import sounddevice as sd
import numpy
import ctypes
import threading
import opus_helpers
from frame_buffer import FrameBuffer
import queue
import time as t # for debugging
import wave

q = queue.Queue(maxsize=-1)
q2 = queue.Queue(maxsize=-1) # FIXME: This is a debug queue for testing


class RecordingMode:
    def __init__(self):
        # Create re-entrant lock so that we threadsafe
        self._lock = threading.RLock();

        # Grab the lock immediately
        with self._lock:
            self._samples_per_second = 48000
            self._silence_duration_after = 60 # ms
            self._starting_sound_filename = "sounds/starting.opus"
            self._playback_level = 0.5
            self._monitoring_level = 0.5

            # Open the starting sound file and store it as PCM buffer
            opus_file = pyogg.OpusFile(self._starting_sound_filename)
            self._starting_sound_pcm = opus_file.as_array()
            self._starting_sound_pcm = self._starting_sound_pcm.astype(numpy.float32) / (2**15)


            
    @property
    def _monitoring_level(self):
        return 1 - self._playback_level

    
    @_monitoring_level.setter
    def _monitoring_level(self, new_value):
        if new_value > 1:
            new_value = 1
        if new_value < 0:
            new_value = 0
        self._playback_level = 1 - new_value


    def set_latency_adjustment(self, latency):
        self._latency = latency

        
    def prepare(self, backing_track_filename):
        # Grab the lock so that we're threadsafe
        with self._lock:
            # Open the backing track and store it as PCM buffer
            opus_file = pyogg.OpusFile(backing_track_filename)
            self._backing_track_pcm = opus_file.as_array()
            self._backing_track_pcm = self._backing_track_pcm.astype(numpy.float32) / (2**15)

            # Create an encoder
            self._encoder = opus_helpers.create_encoder(
                self._backing_track_pcm,
                self._samples_per_second
            )

            
    def record(self):
        # Define the stream's callback
        count = 0 # DEBUG
        last_inputBufferAdcTime = None
        
        def callback(indata, outdata, samples, time, status):
            nonlocal step_no, current_pos, stream, warmup_samples
            nonlocal samples_per_frame
            nonlocal count
            nonlocal frame_buffer
            nonlocal last_inputBufferAdcTime

            start_time = t.time()

            # internal_latency = (time.outputBufferDacTime
            #                     - time.inputBufferAdcTime)
            # print("internal latency:", internal_latency,
            #       "samples:", samples)

            # if last_inputBufferAdcTime is not None:
            #     print("time diff:", time.inputBufferAdcTime - last_inputBufferAdcTime)
            # last_inputBufferAdcTime = time.inputBufferAdcTime
            
            if status:
                print(status)

            count += 1
            
            # Grab the lock so that we're threadsafe
            with self._lock:
                # TODO: Need to add monitoring
                inx = []
                inx[:] = indata[:] 

                # Step No 0
                # =========
                if step_no == 0:

                    if status.input_underflow:
                        print("INPUT UNDERFLOW: Not a problem as we're just writing out.  Count:",count)
                    elif status.input_overflow:
                        print("INPUT OVERFLOW: Not a problem as we're just writing out. Count:",count)
                    elif status:
                        print(status)
                        print("count: ",count)
                        print("ABORTING")
                        raise sd.CallbackAbort


                    # If the number of output channels does not match
                    # out starting sound's PCM, we'll need to adjust
                    # it.
                    if outdata.shape[1] != self._starting_sound_pcm.shape[1]:
                        # Number of channels does not match
                        print("Number of channels does not match")

                    # Copy the starting sound to the output
                    remaining = len(self._starting_sound_pcm) - current_pos
                    if remaining >= samples:
                        outdata[:] = self._starting_sound_pcm[
                            current_pos : current_pos+samples
                        ]
                    else:
                        # Copy what's left of the starting sound, and fill
                        # the rest with silence
                        outdata[:remaining] = self._starting_sound_pcm[
                            current_pos : len(self._starting_sound_pcm)
                        ]
                        outdata[remaining:samples] = [[0.0, 0.0]] * (samples-remaining)

                    # Adjust the starting sound position
                    current_pos += samples

                    if current_pos >= len(self._starting_sound_pcm):
                        print("Finished playing starting sound; moving to next step")
                        step_no = 2#+= 1 FIXME
                        current_pos = 0

                        
                # Step No 1
                # =========
                elif step_no == 1:
                    if status:
                        print(status, "in step #1; ignoring")
                    
                    # Play silence
                    outdata[:] = [[0.0, 0.0]] * samples
                    current_pos += samples

                    # Warm-up the encoder.  See "Encoder Guidelines"
                    # at https://tools.ietf.org/html/rfc7845#page-27
                    frame_buffer.put(indata)
                    if frame_buffer.size() >= samples_per_frame:
                        # Pass the complete frame to another thread for processing
                        q.put(frame_buffer.get(samples_per_frame))

                    if current_pos >= warmup_samples:
                        print("Finished warming up the encoder; moving to next step")
                        step_no += 1
                        warmup_samples = current_pos
                        current_pos = 0
                    

                # Step No 2
                # =========
                elif step_no == 2:
                    if status:
                        print(status, "in step #2; aborting")
                        print("count: ",count)
                        print("ABORTING")
                        raise sd.CallbackAbort

                    
                    # Play backing track and record voice
                    # Copy the backing track to the output
                    remaining = len(self._backing_track_pcm) - current_pos
                    if remaining >= samples:
                        outdata[:] = self._backing_track_pcm[
                            current_pos : current_pos+samples
                        ]
                    else:
                        # Copy what's left of the backing track, and fill
                        # the rest with silence
                        outdata[:remaining] = self._backing_track_pcm[
                            current_pos : len(self._backing_track_pcm)
                        ]
                        outdata[remaining:samples] = [[0.0, 0.0]] * (samples-remaining)
                        
                    # Adjust the position
                    current_pos += samples


                    # DEBUG send outdata to q2
                    q2.put_nowait(outdata.copy())
                    
                    # Record the microphone
                    frame_buffer.put(indata)

                    # DEBUG send the microphone data straight to the queue
                    #q.put_nowait(indata.copy())

                    while frame_buffer.size() >= samples_per_frame:
                        # Pass complete frames to another thread for processing
                        frame = frame_buffer.get(samples_per_frame)
                        q.put_nowait(frame)

                    if current_pos >= len(self._backing_track_pcm):
                        print("Finished playing backing track; moving to next step")
                        step_no += 1
                        current_pos = 0
                        
                    end_time = t.time()
                    duration = end_time - start_time
                    if duration > 2/1000:
                        print("    thread call duration at end of step 2(ms):", round(duration*1000, 2))

                        
                # Step No 3
                # =========
                elif step_no == 3:
                    if status:
                        print(status, "in step #3; ignoring")
                        
                    # Play one frame's worth of silence, just to
                    # ensure we can keep the frame size constant.
                    outdata[:] = [[0.0, 0.0]] * samples
                    current_pos += samples

                    # Record the microphone
                    frame_buffer.put(indata)
                    if frame_buffer.size() >= samples_per_frame:
                        # Pass the complete frame to another thread for processing
                        q.put(frame_buffer.get(samples_per_frame))
                    
                    if current_pos >= warmup_samples:
                        print("Finished playing a frame's worth of silence; moving to next step")
                        step_no += 1
                        current_pos = 0
                    

                else:
                    print("Stopping")
                    raise sd.CallbackStop
                    

            if stream.cpu_load > 0.2:
                print("CPU Load above 20% during playback")

            end_time = t.time()
            duration = end_time - start_time
            if duration > 2/1000:
                print("    thread call duration (ms):", round(duration*1000, 2))



        # Step number indicates where we are in the recording process
        # 0: play starting sound
        # 1: silence used for warming up the encoder
        # 2: backing track and recording
        # 3: silence + recording to ensure we finish on a clean
        step_no = 0

        # Step 0: Set the current position for the sound being played
        current_pos = 0

        
        # Step 1: Encoder warmup
        # Obtain the algorithmic delay of the Opus encoder
        delay = opus.opus_int32()
        result = opus.opus_encoder_ctl(
            self._encoder,
            opus.OPUS_GET_LOOKAHEAD_REQUEST,
            ctypes.pointer(delay)
        )
        if result != opus.OPUS_OK:
            raise Exception("Failed in OPUS_GET_LOOKAHEAD_REQUEST")
        delay_samples = delay.value

        # The encoder guidelines recommend that at least an extra 120
        # samples is added to delay_samples.  See
        # https://tools.ietf.org/html/rfc7845#page-27
        extra_samples = 120
        warmup_samples = delay_samples + extra_samples 

        # Create a buffer capable of holding two frames 
        samples_per_frame = 960
        channels = 2
        frame_buffer = FrameBuffer(
            48000, # one second FIXME
            channels
        )

        
        # Create an event for communication between threads
        finished = threading.Event()

        
        # Create an input-output sounddevice stream
        print("Creating stream")
        stream = sd.Stream(
            samplerate=48000,
            #channels=channels,
            dtype=numpy.float32,
            latency=100/1000, #"high",
            callback=callback,
            finished_callback=finished.set
        )

        with stream:
            finished.wait()  # Wait until playback is finished

        # Store the final number of pre-skip warmup samples
        self._pre_skip = warmup_samples
        


    def write_opus(self, output_filename):
        # Go through the frames and save them as an OggOpus file

        # Create a new stream state with a random serial number
        stream_state = opus_helpers.create_stream_state()

        # Create a packet (reused for each pass)
        ogg_packet = ogg.ogg_packet()

        # Flag to indicate the start of stream
        start_of_stream = 1

        # Packet counter
        count_packets = 0

        # PCM samples counter
        count_samples = 0

        # Allocate memory for a page
        ogg_page = ogg.ogg_page()

        # Allocate storage space for the encoded frame.  4,000 bytes
        # is the recommended maximum buffer size for the encoded
        # frame.
        max_bytes_in_encoded_frame = opus.opus_int32(4000)
        EncodedFrameType = ctypes.c_ubyte * max_bytes_in_encoded_frame.value
        encoded_frame = EncodedFrameType()

        # Create a pointer to the first byte of the buffer for the
        # encoded frame.
        encoded_frame_ptr = ctypes.cast(
            ctypes.pointer(encoded_frame),
            ctypes.POINTER(ctypes.c_ubyte)
        )

        
        # Open file for writing
        f = open(output_filename, "wb")

        # Headers
        # =======
        
        # Specify the identification header
        id_header = opus.make_identification_header(
            pre_skip = self._pre_skip
        )

        # Specify the packet containing the identification header
        ogg_packet.packet = ctypes.cast(id_header, ogg.c_uchar_p)
        ogg_packet.bytes = len(id_header)
        ogg_packet.b_o_s = start_of_stream
        ogg_packet.e_o_s = 0
        ogg_packet.granulepos = 0
        ogg_packet.packetno = count_packets
        start_of_stream = 0
        count_packets += 1

        # Write the header
        result = ogg.ogg_stream_packetin(
            stream_state,
            ogg_packet
        )

        if result != 0:
            raise Exception("Failed to write Opus identification header")


        # Specify the comment header
        comment_header = opus.make_comment_header()

        # Specify the packet containing the identification header
        ogg_packet.packet = ctypes.cast(comment_header, ogg.c_uchar_p)
        ogg_packet.bytes = len(comment_header)
        ogg_packet.b_o_s = start_of_stream
        ogg_packet.e_o_s = 0
        ogg_packet.granulepos = 0
        ogg_packet.packetno = count_packets
        count_packets += 1

        # Write the header
        result = ogg.ogg_stream_packetin(
            stream_state,
            ogg_packet
        )

        if result != 0:
            raise Exception("Failed to write Opus comment header")


        # Write out pages to file
        while ogg.ogg_stream_flush(ctypes.pointer(stream_state),
                                   ctypes.pointer(ogg_page)) != 0:
            # Write page
            print("Writing header page")
            f.write(bytes(ogg_page.header[0:ogg_page.header_len]))
            f.write(bytes(ogg_page.body[0:ogg_page.body_len]))

            
        # Frames
        # ======

        # Loop through the PCM frames in the queue
        while not q.empty():
            # Get the frame from the queue
            frame_pcm = q.get_nowait()

            # Convert to opus_int16
            frame_pcm = numpy.array(frame_pcm * 2**15, dtype=opus.opus_int16) 

            # Create a pointer to the start of the frame's data
            source_ptr = frame_pcm.ctypes.data_as(ctypes.c_void_p)
            
            #print("Processing frame at sourcePtr ", sourcePtr.value)

            # Check if we have enough source data remaining to process at
            # the current frame size
            samples_per_frame = 960
            assert len(frame_pcm) == samples_per_frame

            # Encode the audio
            #print("Encoding audio")
            num_bytes = opus.opus_encode(
                self._encoder,
                ctypes.cast(source_ptr, ctypes.POINTER(opus.opus_int16)),
                samples_per_frame,
                encoded_frame_ptr,
                max_bytes_in_encoded_frame
            )
            #print("num_bytes: ", num_bytes)

            # Check for any errors during encoding
            if num_bytes < 0:
                raise Exception("Encoder error detected: "+
                                opus.opus_strerror(num_bytes).decode("utf"))

            # Writing OggOpus
            # ===============

            # Increase the number of samples
            count_samples += samples_per_frame

            # Place data into the packet
            ogg_packet.packet = encoded_frame_ptr
            ogg_packet.bytes = num_bytes
            ogg_packet.b_o_s = start_of_stream
            ogg_packet.e_o_s = 0 # FIXME: It needs to end!
            ogg_packet.granulepos = count_samples
            ogg_packet.packetno = count_packets

            # No longer the start of stream
            start_of_stream = 0

            # Increase the number of packets
            count_packets += 1

            # Place the packet in to the stream
            result = ogg.ogg_stream_packetin(
                stream_state,
                ogg_packet
            )

            # Check for errors
            if result != 0:
                raise Exception("Error while placing packet in Ogg stream")

            # Write out pages to file
            while ogg.ogg_stream_pageout(ctypes.pointer(stream_state),
                                         ctypes.pointer(ogg_page)) != 0:
                # Write page
                print("Writing page")
                f.write(bytes(ogg_page.header[0:ogg_page.header_len]))
                f.write(bytes(ogg_page.body[0:ogg_page.body_len]))

                
        # Force the writing of the final page
        while ogg.ogg_stream_flush(ctypes.pointer(stream_state),
                                   ctypes.pointer(ogg_page)) != 0:
            # Write page
            print("Writing final page")
            f.write(bytes(ogg_page.header[0:ogg_page.header_len]))
            f.write(bytes(ogg_page.body[0:ogg_page.body_len]))

                
        # Make sure the queue is empty
        if not q.empty():
            print("WARNING: Failed to completely process all the recorded frames")
        
        # Finished
        f.close()
        print("Finished writing file")


    def write_wave(self, filename):
        print("Saving wav:", filename)

        wave_file = wave.open(filename, "wb")
        wave_file.setnchannels(2) # FIXME
        wave_file.setsampwidth(2) # int16
        wave_file.setframerate(48000) # FIXME


        filename2="non-adjusted-"+filename
        print("Saving wav:", filename2)

        wave_file2 = wave.open(filename2, "wb")
        wave_file2.setnchannels(2) # FIXME
        wave_file2.setsampwidth(2) # int16
        wave_file2.setframerate(48000) # FIXME

        
        # Calculate the number of samples to drop for the latency
        # adjustment
        latency_samples = int(self._latency * 48000)
        print("Dropping", latency_samples, "samples to adjust for latency")
        
        # Loop through queue
        dropped_samples = 0
        while not q.empty():
            pcm = q.get_nowait()
            # Convert to int16
            pcm = pcm * (2**15-1)
            pcm = pcm.astype(numpy.int16)
            wave_file2.writeframes(pcm)
            
            samples_remaining_to_drop = latency_samples - dropped_samples
            if samples_remaining_to_drop > 0:
                if samples_remaining_to_drop >= len(pcm):
                    # drop this whole frame
                    dropped_samples += len(pcm)
                    continue
                else:
                    # drop part of this frame
                    pcm = pcm[samples_remaining_to_drop:]
                    dropped_samples += samples_remaining_to_drop
            wave_file.writeframes(pcm)

        wave_file.close()
        wave_file2.close()



        filename2 = "output-"+filename
        print("Saving wav:", filename2)

        wave_file = wave.open(filename2, "wb")
        wave_file.setnchannels(2) # FIXME
        wave_file.setsampwidth(2) # int16
        wave_file.setframerate(48000) # FIXME
        # Convert to int16

        # Loop through queue
        while not q2.empty():
            pcm = q2.get_nowait()
            pcm = pcm * (2**15-1)
            pcm = pcm.astype(numpy.int16)
            wave_file.writeframes(pcm)

        wave_file.close()
        
            


if __name__ == "__main__":
    #backing_track_filename = "left-right-demo-5s.opus"
    #backing_track_filename = "sounds/one-click.opus"
    backing_track_filename = "sounds/rhythm.opus"
    output_filename = "recording"

    rec = RecordingMode()
    print("Preparing...")
    rec.set_latency_adjustment(210/1000) # FIXME
    rec.prepare(backing_track_filename)
    print("Recording...")
    rec.record()
    print("Writing...")
    rec.write_wave(output_filename+".wav")
    #rec.write_opus(output_filename+".opus")
    
    print("Finished.")
