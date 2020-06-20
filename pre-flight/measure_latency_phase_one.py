# Check that audio can be played... at all.
import time
import sounddevice as sd
import numpy
from enum import Enum
import time
import threading
import math
import operator
import wave
import queue
from measure_levels import measure_levels
from tone import Tone
from fft_analyser import FFTAnalyser

# Phase One
# =========
# Measure latency approximately via tones.
def measure_latency_phase_one(levels, desired_latency="high", samples_per_second=48000, channels=(2,2)):
    """Channels are specified as a tuple of (input channels, output channels)."""
    input_channels, output_channels = channels

    # Class to describe the current state of the process
    class ProcessState(Enum):
        RESET = 0
        START_TONE0 = 5
        DETECT_TONE0 = 10
        START_TONE0_TONE1 = 15
        DETECT_TONE0_TONE1 = 20
        CLEANUP = 25
        COMPLETING = 30
        COMPLETED = 40
        ABORTED = 50

    # Create a class to hold the shared variables
    class SharedVariables:
        def __init__(self, samples_per_second):
            # DEBUG
            # Create a buffer to store the outdata for analysis
            duration = 20 # seconds
            self.out_pcm = numpy.zeros((
                duration*samples_per_second,
                output_channels
            ))
            self.out_pcm_pos = 0

            # Threading event on which the stream can wait
            self.event = threading.Event()

            # Queue to save output data for debugging
            self.q = queue.Queue()

            # Store samples per second parameter
            self.samples_per_second = samples_per_second
        
            # Allocate space for recording
            max_recording_duration = 2 # seconds
            max_recording_samples = (
                max_recording_duration
                * samples_per_second
            )
            self.rec_pcm = numpy.zeros((
                max_recording_samples,
                input_channels
            ))

            # Initialise recording position
            self.rec_position = 0

            # Current state of the process
            self.process_state = ProcessState.RESET

            # Instance of the Fast Fourier Transform (FFT) analyser
            self.fft_analyser = FFTAnalyser(samples_per_second)

            # Variable to record when we entered the current state
            self.state_start_time = None

            # Variables for tones
            self.tone_duration = 1 # second
            n_tones = len(self.fft_analyser.freqs)
            self.tones = [Tone(freq,
                               self.samples_per_second,
                               channels = output_channels,
                               max_level = 1/n_tones,
                               duration = self.tone_duration)
                          for freq in self.fft_analyser.freqs]

            # Variables for levels
            self.tone0_mean = levels["tone0_mean"]
            self.tone0_sd = levels["tone0_sd"]
            self.tone0_tone1_mean = levels["tone0_tone1_mean"]
            self.tone0_tone1_sd = levels["tone0_tone1_sd"]

            # Variables for START_TONE0
            self.start_tone0_start_play_time = None

            # Variables for DETECT_TONE0            
            self.detect_tone0_start_detect_time = None
            self.detect_tone0_threshold_num_sd = 4
            self.detect_tone0_threshold_duration = 0.05 # seconds
            self.detect_tone0_max_time_in_state = 5 # seconds
            self.detect_tone0_detected = False
            
            # Variables for START_TONE0_TONE1
            self.start_tone0_tone1_start_play_time = None
            self.start_tone0_tone1_fadein_duration = 5/1000 # seconds
            
            # Variables for DETECT_TONE0_TONE1
            self.detect_tone0_tone1_start_detect_time = None
            self.detect_tone0_tone1_threshold_num_sd = 4
            self.detect_tone0_tone1_threshold_duration = 50/1000 # seconds
            self.detect_tone0_tone1_max_time_in_state = 5 # seconds
            self.detect_tone0_tone1_detected = False

            # Variables for CLEANUP
            self.cleanup_cycles = 0
            self.cleanup_cycles_threshold = 3
            self.cleanup_fadeout_duration = 5/1000 # seconds

            # Variables for COMPLETING
            self.completing_fadeout_duration = 50/1000 # seconds
            
    # Create an instance of the shared variables
    v = SharedVariables(samples_per_second)


    # Check that tone0 and tone0_tone1 are not overlapping in terms of
    # the thresholds defined above.  We are only concerned with tone1
    # and not-tone1 being mutually exclusive.
    x = numpy.array([-1,1])
    range_not_tone1 = v.tone0_mean[1] + x * v.tone0_sd[1]
    range_tone1 = v.tone0_tone1_mean[1] + x * v.tone0_tone1_sd[1]
    if min(range_not_tone1) < max(range_tone1) and \
       min(range_tone1) < max(range_not_tone1):
        print("range_not_tone1:", range_not_tone1)
        print("range_tone1:", range_tone1)
        raise Exception("ERROR: The expected ranges of the two tones overlap. "+
                        "Try increasing the system volume and try again")
        
    
            
    # Callback for when the recording buffer is ready.  The size of the
    # buffer depends on the latency requested.
    def callback(indata, outdata, samples, time, status):
        nonlocal v

        # Store any exceptions to be raised
        exception = None

        # Store Recording
        # ===============
        
        v.rec_pcm[v.rec_position:v.rec_position+samples] = indata[:]
        v.rec_position += samples
        
        # Analysis
        # ========

        tones_level = v.fft_analyser.run(v.rec_pcm, v.rec_position)
        #print(tones_level)
        

        # Clear the first half second of the recording buffer if we've
        # recorded more than one second
        if v.rec_position > v.samples_per_second:
            seconds_to_clear = 0.5 # seconds
            samples_to_clear = int(seconds_to_clear * v.samples_per_second)
            v.rec_pcm = numpy.roll(v.rec_pcm, -samples_to_clear, axis=0)
            v.rec_position -= samples_to_clear

        
        # Transitions
        # ===========

        previous_state = v.process_state

        if v.process_state == ProcessState.RESET:
            v.process_state = ProcessState.START_TONE0

        elif v.process_state == ProcessState.START_TONE0:
            v.process_state = ProcessState.DETECT_TONE0
            
        elif v.process_state == ProcessState.DETECT_TONE0:
            if v.detect_tone0_detected:
                v.process_state = ProcessState.START_TONE0_TONE1
            
            if time.currentTime - v.state_start_time > v.detect_tone0_max_time_in_state:
                print("ERROR: We've spent too long listening for tone #0.  Aborting.")
                v.process_state = ProcessState.ABORTED

        elif v.process_state == ProcessState.START_TONE0_TONE1:
            v.process_state = ProcessState.DETECT_TONE0_TONE1
            
        elif v.process_state == ProcessState.DETECT_TONE0_TONE1:
            if v.detect_tone0_tone1_detected:
                v.process_state = ProcessState.CLEANUP
            
            if time.currentTime - v.state_start_time > v.detect_tone0_tone1_max_time_in_state:
                print("ERROR: We've spent too long listening for tone #0.  Aborting.")
                v.process_state = ProcessState.ABORTED

        elif v.process_state == ProcessState.CLEANUP:
            if v.cleanup_cycles > v.cleanup_cycles_threshold:
                v.process_state = ProcessState.COMPLETING
            else:
                v.process_state = ProcessState.START_TONE0
                
        elif v.process_state == ProcessState.COMPLETING:
            if v.tones[0].inactive and v.tones[1].inactive:
                v.process_state = ProcessState.COMPLETED
        
        elif v.process_state == ProcessState.COMPLETED:
            pass
        
        elif v.process_state == ProcessState.ABORTED:
            pass    
                
            
        # Set state start time
        if previous_state != v.process_state:
            v.state_start_time = time.currentTime
        
        
        # States
        # ======

        if v.process_state == ProcessState.RESET:
            # Ensure tone #0 is stopped
            v.tones[0].stop()
            v.tones[0].output(outdata)

            # Ensure tone #1 is stopped
            v.tones[1].stop()
            v.tones[1].output(outdata)

            
        elif v.process_state == ProcessState.START_TONE0:
            # Play tone #0
            v.tones[0].play()
            v.tones[0].output(outdata)
            
            # Start the timer from the moment the system says it will
            # play the audio.
            v.start_tone0_start_play_time = time.outputBufferDacTime

            
        elif v.process_state == ProcessState.DETECT_TONE0:
            # Play tone #0
            v.tones[0].play()
            v.tones[0].output(outdata)

            if tones_level is not None:
                # Are we hearing the tone?  Ensure we're within an
                # acceptable number of standard deviations from the mean.
                num_sd = abs((tones_level - v.tone0_mean) / v.tone0_sd)

                # FIXME: How should I compare two normal distributions?
                if all(num_sd < v.detect_tone0_threshold_num_sd):
                    if v.detect_tone0_start_detect_time is None:
                        v.detect_tone0_start_detect_time = time.inputBufferAdcTime
                    else:
                        detect_duration = time.inputBufferAdcTime - v.detect_tone0_start_detect_time
                        if detect_duration > v.detect_tone0_threshold_duration:
                            print("Tone0 detected")
                            v.detect_tone0_detected = True

                            # Calculate latency to the moment the
                            # system says it recorded the audio.
                            latency = (
                                v.detect_tone0_start_detect_time
                                - v.start_tone0_start_play_time
                                - v.fft_analyser.window_width
                            )
                            print("Latency: ",round(latency*1000), "ms")
                            
                else:
                    # Reset timer
                    v.detect_tone0_start_detect_time = None
            else:
                print("tones_levels was None")

                
        elif v.process_state == ProcessState.START_TONE0_TONE1:
            # Play tone #0 as it should be on in the background
            v.tones[0].play()
            v.tones[0].output(outdata)

            # Start playing tone #1
            v.tones[1].fadein(v.start_tone0_tone1_fadein_duration)
            v.tones[1].output(outdata, operator.iadd)
            
            # Start the timer from the moment the system says it will
            # play the audio.
            v.start_tone0_tone1_start_play_time = time.outputBufferDacTime

            
        elif v.process_state == ProcessState.DETECT_TONE0_TONE1:
            # Play both tones
            v.tones[0].output(outdata)
            v.tones[1].output(outdata, op=operator.iadd)

            if tones_level is not None:
                # Are we hearing the tone?  Ensure we're within an
                # acceptable number of standard deviations from the mean.
                num_sd = abs((tones_level - v.tone0_tone1_mean) / v.tone0_tone1_sd)
                print(num_sd)

                # FIXME: How should I compare two normal distributions?
                if all(num_sd < v.detect_tone0_tone1_threshold_num_sd):
                    if v.detect_tone0_tone1_start_detect_time is None:
                        print("Detected")
                        v.detect_tone0_tone1_start_detect_time = time.inputBufferAdcTime
                    else:
                        detect_duration = time.inputBufferAdcTime - v.detect_tone0_tone1_start_detect_time
                        if detect_duration > v.detect_tone0_tone1_threshold_duration:
                            print("Tone0 and Tone1 detected")
                            v.detect_tone0_tone1_detected = True

                            # Calculate latency to the moment the
                            # system says it recorded the audio.
                            latency = (
                                v.detect_tone0_tone1_start_detect_time
                                - v.start_tone0_tone1_start_play_time
                                - v.fft_analyser.window_width
                            )
                            print("Latency: ",round(latency*1000), "ms")
                            
                else:
                    # Reset timer
                    print("Resetting")
                    v.detect_tone0_tone1_start_detect_time = None
            else:
                print("tones_levels was None")

                
        elif v.process_state == ProcessState.CLEANUP:
            # Play tone #0 as it shouldn't shut down
            v.tones[0].play()
            v.tones[0].output(outdata)

            # Shut down tone #1
            v.tones[1].fadeout(v.cleanup_fadeout_duration)
            v.tones[1].output(outdata, op=operator.iadd)

            # Reset key variables
            v.detect_tone0_start_detect_time = None            
            v.detect_tone0_detected = False
            v.detect_tone0_tone1_start_detect_time = None            
            v.detect_tone0_tone1_detected = False

            # Increment the number of cleanup cycles
            v.cleanup_cycles += 1
            
                
        elif v.process_state == ProcessState.COMPLETING:
            print("Completing")
            v.tones[0].fadeout(v.completing_fadeout_duration) #FIXME
            v.tones[0].output(outdata)

            v.tones[1].fadeout(v.completing_fadeout_duration)
            v.tones[1].output(outdata, op=operator.iadd)


        elif v.process_state == ProcessState.COMPLETED:
            outdata.fill(0)

            print("Completed phase one latency measurement")
            exception = sd.CallbackStop

        
        elif v.process_state == ProcessState.ABORTED:
            # Actively fill outdata with zeros
            outdata.fill(0)
            print("Aborted phase one latency measurement")
            raise sd.CallbackAbort

        
        # Store output
        # ============
        v.q.put(outdata.copy())

        # Terminate if required
        # =====================
        if exception is not None:
            raise exception


    # Play first tone
    # Open a read-write stream
    print("STREAM's Desired latency:", desired_latency)
    stream = sd.Stream(samplerate=samples_per_second,
                       channels=channels,
                       dtype=numpy.float32,
                       latency=desired_latency,
                       callback=callback,
                       finished_callback=v.event.set)

    print("Measuring latency...")
    with stream:
        v.event.wait()  # Wait until measurement is finished

    # Save output as wave file
    print("Writing wave file")
    wave_file = wave.open("out.wav", "wb")
    wave_file.setnchannels(2) #FIXME
    wave_file.setsampwidth(2)
    wave_file.setframerate(samples_per_second)
    while True:
        try:
            data = v.q.get_nowait()
        except:
            break
        data = data * (2**15-1)
        data = data.astype(numpy.int16)
        wave_file.writeframes(data)
    wave_file.close()

        
    # Done!
    print("Finished.")


        
def _measure_latency(desired_latency="high"):
    print("Desired latency:", desired_latency)
    levels = measure_levels(desired_latency)
    print("\n")
    approximate_latency = measure_latency_phase_one(levels, desired_latency)
    
    

if __name__ == "__main__":
    print("")
    print("Measuring Latency: Phase One")
    print("============================")
    print("")
    print("We are now going to measure the latency in your audio system.  Latency is the time")
    print("starting from when the program requests that a sound is made, until the program hears")
    print("that sound in a recording of itself.  This latency measure is used to adjust recordings")
    print("so that they are synchronised with the backing track.  If you change the configuration")
    print("of the either the playback or the recording device then you will need to re-run this")
    print("measurement.")
    print("")
    print("You will need to adjust the position of the microphone and output device.  For this")
    print("measurement, the microphone needs to be able to hear the output.  So, for example, if")
    print("you have headphones with an inline microphone, place the microphone over one of the")
    print("ear pieces.")
    print("")
    print("The process takes a few seconds.  It will play a constant tone.  You will need to ")
    print("increase the volume until the microphone can reliably hear the output.  It will then")
    print("play a number of tones until it has approximately measured the latency in your system.")
    print("It will then play a number of clicks to accurately measure the latency.")
    print("")
    print("Do not move the microphone or output device once the system can hear the constant tone.")
    print("Do not make any noise during this measurement.")
    print("")
    print("Press enter to start.")
    print("")

    input() # wait for enter key

    _measure_latency("high")
