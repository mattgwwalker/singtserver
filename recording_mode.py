# Given a backing track, records while playing the backing track,
# saving the result to and OggOpus file.

import pyogg
from pyogg import opus
import sounddevice as sd
import numpy
import ctypes
import threading
from opus_helpers import create_encoder
from frame_buffer import FrameBuffer


class RecordingMode:
    def __init__(self):
        # Create re-entrant lock so that we threadsafe
        self.__lock = threading.RLock();

        # Grab the lock immediately
        with self.__lock:
            self.__samples_per_second = 48000
            self.__silence_duration_after = 60 # ms
            self.__starting_sound_filename = "sounds/starting.opus"
            self.__playback_level = 0.5
            self.__monitoring_level = 0.5

            # Open the starting sound file and store it as PCM buffer
            opus_file = pyogg.OpusFile(self.__starting_sound_filename)
            self.__starting_sound_pcm = opus_file.as_array()
            self.__starting_sound_pcm = self.__starting_sound_pcm.astype(numpy.float32) / (2**15)


            
    @property
    def __monitoring_level(self):
        return 1 - self.__playback_level

    
    @__monitoring_level.setter
    def __monitoring_level(self, new_value):
        if new_value > 1:
            new_value = 1
        if new_value < 0:
            new_value = 0
        self.__playback_level = 1 - new_value

        
    def prepare(self, backing_track_filename):
        # Grab the lock so that we're threadsafe
        with self.__lock:
            # Open the backing track and store it as PCM buffer
            opus_file = pyogg.OpusFile(backing_track_filename)
            self.__backing_track_pcm = opus_file.as_array()
            self.__backing_track_pcm = self.__backing_track_pcm.astype(numpy.float32) / (2**15)

            # Create an encoder
            self.__encoder = create_encoder(
                self.__backing_track_pcm,
                self.__samples_per_second
            )

            
    def record(self):
        # Define the stream's callback
        def callback(indata, outdata, samples, time, status):
            nonlocal step_no, current_pos, stream, warmup_samples
            nonlocal samples_per_frame
            
            
            if status:
                print(status)
                
            # Grab the lock so that we're threadsafe
            with self.__lock:
                # TODO: Need to add monitoring
                inx = []
                inx[:] = indata[:] 

                # Step No 0
                # =========
                if step_no == 0:
                    # Copy the starting sound to the output
                    remaining = len(self.__starting_sound_pcm) - current_pos
                    if remaining >= samples:
                        outdata[:] = self.__starting_sound_pcm[
                            current_pos : current_pos+samples
                        ]
                    else:
                        # Copy what's left of the starting sound, and fill
                        # the rest with silence
                        outdata[:remaining] = self.__starting_sound_pcm[
                            current_pos : len(self.__starting_sound_pcm)
                        ]
                        outdata[remaining:samples] = [[0.0, 0.0]] * (samples-remaining)

                    # Adjust the starting sound position
                    current_pos += samples

                    if current_pos >= len(self.__starting_sound_pcm):
                        print("Finished playing starting sound; moving to next step")
                        step_no += 1
                        current_pos = 0

                # Step No 1
                # =========
                elif step_no == 1:
                    # Play silence
                    outdata[:] = [[0.0, 0.0]] * samples
                    current_pos += samples

                    # Warm-up the encoder.  See "Encoder Guidelines"
                    # at https://tools.ietf.org/html/rfc7845#page-27
                    frame_buffer.put(indata)
                    if frame_buffer.size() >= samples_per_frame:
                        # TODO: Pass the frame onto another thread for processing
                        pass

                    if current_pos >= warmup_samples:
                        print("Finished warming up the encoder; moving to next step")
                        step_no += 1
                        warmup_samples = current_pos
                        current_pos = 0
                    

                elif step_no == 2:
                    # Play backing track and record voice
                    # Copy the backing track to the output
                    remaining = len(self.__backing_track_pcm) - current_pos
                    if remaining >= samples:
                        outdata[:] = self.__backing_track_pcm[
                            current_pos : current_pos+samples
                        ]
                    else:
                        # Copy what's left of the backing track, and fill
                        # the rest with silence
                        outdata[:remaining] = self.__backing_track_pcm[
                            current_pos : len(self.__backing_track_pcm)
                        ]
                        outdata[remaining:samples] = [[0.0, 0.0]] * (samples-remaining)

                    # Adjust the position
                    current_pos += samples

                    if current_pos >= len(self.__backing_track_pcm):
                        print("Finished playing backing track; moving to next step")
                        step_no += 1
                        current_pos = 0

                elif step_no == 3:
                    # Play one frame's worth of silence, just to
                    # ensure we can keep the frame size constant.
                    outdata[:] = [[0.0, 0.0]] * samples
                    current_pos += samples

                    # TODO: Encode
                    
                    if current_pos >= warmup_samples:
                        print("Finished playing a frame's worth of silence; moving to next step")
                        step_no += 1
                        current_pos = 0
                    

                else:
                    print("Stopping")
                    raise sd.CallbackStop
                    

            if stream.cpu_load > 0.2:
                print("CPU Load above 20% during playback")


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
            self.__encoder,
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
            2*samples_per_frame,
            channels
        )

        
        # Create an event for communication between threads
        finished = threading.Event()

        
        # Create an input-output sounddevice stream
        print("Creating stream")
        stream = sd.Stream(
            samplerate=48000,
            channels=channels,
            dtype=numpy.float32,
            latency="low",
            callback=callback,
            finished_callback=finished.set
        )

        with stream:
            finished.wait()  # Wait until playback is finished
        


    def write(self, output_filename):
        pass
        

if __name__ == "__main__":
    backing_track_filename = "left-right-demo-5s.opus"
    output_filename = "recording.opus"

    rec = RecordingMode()
    rec.prepare(backing_track_filename)
    rec.record()
    rec.write(output_filename)
        
    print("Finished.")
