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
from scipy import signal

def process_samples(q):
    # Create arrays to hold the complete
    max_duration = 10 # seconds
    samples_per_second = 48000 # FIXME
    pcm_in = numpy.zeros((
        max_duration * samples_per_second,
    ))
    pcm_in_pos = 0
    pcm_out = numpy.zeros((
        max_duration * samples_per_second,
    ))
    pcm_out_pos = 0

    count = 0

    # List for results of processing
    latencies = []
           
    while True:
        try:
            item = q.get_nowait()
        except queue.Empty:
            print("Finished processing")
            break

        try:
            assert item["start"] == True
            pcm_in_pos = 0
            pcm_out_pos = 0
            count += 1
            internal_delta = item["out_time"] - item["in_time"] 
            
        except KeyError:
            # We can't be at the start
            pass

        try:
            # Copy input data
            indata = item["in"]
            if indata.shape[1] == 2:
                # Convert to mono
                left = indata[:,0]
                right = indata[:,1]
                indata = (left+right)/2
            elif indata.shape[1] == 1:
                # Source is mono
                indata = indata[:,0]
            else:
                raise Exception("Unexpected number of input channels "+
                                "({:d})".format(indata.shape[1]))
            
            pcm_in[pcm_in_pos:pcm_in_pos+len(indata)] = \
                indata[:]
            pcm_in_pos += len(indata)

            # Copy output data
            outdata = item["out"]
            if outdata.shape[1] == 2:
                # Convert to mono
                left = outdata[:,0]
                right = outdata[:,1]
                outdata = (left+right)/2
            elif outdata.shape[1] == 1:
                # Output is already mono
                outdata = outdata[:,0]
            else:
                raise Exception("Unexpected number of output channels "+
				"({:d})".format(indata.shape[1]))

            pcm_out[pcm_out_pos:pcm_out_pos+len(outdata)] = \
                outdata[:]
            pcm_out_pos += len(outdata)

        except KeyError:
            # Don't have data, must be at the end
            pass

        
        try:
            assert item["end"] == True
            
            # Save as wave
            def save_as_wave(pcm, filename):
                print("Saving wav:", filename)

                wave_file = wave.open(filename, "wb")
                wave_file.setnchannels(1) # mono
                wave_file.setsampwidth(2) # int16
                wave_file.setframerate(48000) # FIXME
                # Convert to int16
                pcm = pcm * (2**15-1)
                pcm = pcm.astype(numpy.int16)
                wave_file.writeframes(pcm)
                wave_file.close()

            indata = pcm_in[:pcm_in_pos]
            outdata = pcm_out[:pcm_out_pos]
                
            save_as_wave(indata,
                         "in{:d}.wav".format(count))
            save_as_wave(outdata,
                         "out{:d}.wav".format(count))

            cor = signal.correlate(outdata, indata)
            correction = len(indata) - numpy.argmax(cor)
            external_delta = (
                correction/samples_per_second
                - internal_delta
            )
            latency = internal_delta+external_delta
            latencies.append(latency)
            print("internal (ms):",round(internal_delta*1000))
            print("external (ms):",round(external_delta*1000))
            print("latency (ms):",round(latency*1000))
            
        except KeyError:
            # We aren't at the end
            pass

    return latencies
              

# Phase One
# =========
# Measure latency approximately via tones.
def measure_latency_phase_one(levels, desired_latency="high", samples_per_second=48000, channels=(2,2)):
    """Channels are specified as a tuple of (input channels, output channels)."""
    input_channels, output_channels = channels

    # Class to describe the current state of the process
    class ProcessState(Enum):
        RESET = 0
        DETECT_SILENCE_START = 10
        START_TONE = 20
        DETECT_TONE = 30
        STOP_TONE = 35
        DETECT_SILENCE_END = 40
        CLEANUP = 50
        COMPLETING = 60
        COMPLETED = 70
        ABORTED = 80

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

            # Queues for off-thread processing
            self.q_process = queue.Queue()

            # Store samples per second parameter
            self.samples_per_second = samples_per_second
        
            # Allocate space for recording
            max_recording_duration = 10 # seconds
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
            self.fft_analyser = FFTAnalyser(
                array=self.rec_pcm,
                samples_per_second=samples_per_second
            )

            # Variable to record when we entered the current state
            self.state_start_time = None

            # Variables for tone
            assert self.fft_analyser.n_freqs == 1
            tone_duration = 1 # second
            self.tone = Tone(self.fft_analyser.freqs[0],
                             self.samples_per_second,
                             channels = output_channels,
                             max_level = 1,
                             duration = tone_duration)

            # Variables for levels
            self.silence_mean = levels["silence_mean"]
            self.silence_sd = levels["silence_sd"]
            self.tone0_mean = levels["tone0_mean"]
            self.tone0_sd = levels["tone0_sd"]

            # Variables for DETECT_SILENCE_START
            self.detect_silence_start_threshold_levels = (
                (self.tone0_mean[0] + self.silence_mean[0]) / 2
            )
            self.detect_silence_start_samples = 0
            self.detect_silence_start_threshold_samples = 100 # samples
            self.detect_silence_start_detected = False

            # Variables for START_TONE
            self.start_tone_click_duration = 75/1000 # seconds
            
            # Variables for DETECT_TONE
            self.detect_tone_threshold = (
                (self.tone0_mean[0] + self.silence_mean[0]) / 2
            )
            self.detect_tone_start_detect_time = None
            self.detect_tone_threshold_duration = 50/1000 # seconds
            self.detect_tone_detected = False
            self.detect_tone_max_time_in_state = 5 # seconds

            # Variables for STOP_TONE
            self.stop_tone_fadeout_duration = 20/1000 # seconds
            
            # Variables for DETECT_SILENCE_END
            self.detect_silence_end_threshold_levels = (
                (self.tone0_mean[0] + self.silence_mean[0]) / 2
            )
            self.detect_silence_end_samples = 0
            self.detect_silence_end_threshold_samples = 10
            self.detect_silence_end_detected = False

            # Variables for CLEANUP
            self.cleanup_cycles = 0
            self.cleanup_cycles_threshold = 3
            
            # =======

            # Variables for START_TONE0
            self.start_tone0_start_play_time = None

            # Variables for DETECT_TONE0            
            self.detect_tone0_threshold_num_sd = 4
            
            # Variables for START_TONE0_TONE1
            self.start_tone0_tone1_start_play_time = None
            self.start_tone0_tone1_fadein_duration = 5/1000 # seconds
            
            # Variables for DETECT_TONE0_TONE1
            self.detect_tone0_tone1_start_detect_time = None
            self.detect_tone0_tone1_threshold_num_sd = 4
            self.detect_tone0_tone1_threshold_duration = 50/1000 # seconds
            self.detect_tone0_tone1_max_time_in_state = 5 # seconds
            self.detect_tone0_tone1_detected = False
            
    # Create an instance of the shared variables
    v = SharedVariables(samples_per_second)


    # # Check that tone0 and tone0_tone1 are not overlapping in terms of
    # # the thresholds defined above.  We are only concerned with tone1
    # # and not-tone1 being mutually exclusive.
    # x = numpy.array([-1,1])
    # range_not_tone1 = v.tone0_mean[1] + x * v.tone0_sd[1]
    # range_tone1 = v.tone0_tone1_mean[1] + x * v.tone0_tone1_sd[1]
    # if min(range_not_tone1) < max(range_tone1) and \
    #    min(range_tone1) < max(range_not_tone1):
    #     print("range_not_tone1:", range_not_tone1)
    #     print("range_tone1:", range_tone1)
    #     raise Exception("ERROR: The expected ranges of the two tones overlap. "+
    #                     "Try increasing the system volume and try again")
        
    
            
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

        assert v.rec_pcm is v.fft_analyser._pcm
        analyses = v.fft_analyser.run(v.rec_position)
        #print(tones_level)
        

        # # Clear the first half second of the recording buffer if we've
        # # recorded more than one second
        # if v.rec_position > v.samples_per_second:
        #     seconds_to_clear = 0.5 # seconds
        #     samples_to_clear = int(seconds_to_clear * v.samples_per_second)
        #     v.rec_pcm = numpy.roll(v.rec_pcm, -samples_to_clear, axis=0)
        #     v.rec_position -= samples_to_clear

        
        # Transitions
        # ===========

        previous_state = v.process_state

        if v.process_state == ProcessState.RESET:
            v.process_state = ProcessState.DETECT_SILENCE_START

        elif v.process_state == ProcessState.DETECT_SILENCE_START:
            if v.detect_silence_start_detected:
                v.process_state = ProcessState.START_TONE
            
        elif v.process_state == ProcessState.START_TONE:
            v.process_state = ProcessState.DETECT_TONE
            
        elif v.process_state == ProcessState.DETECT_TONE:
            if v.detect_tone_detected:
                v.process_state = ProcessState.STOP_TONE
            
            if time.currentTime - v.state_start_time > v.detect_tone_max_time_in_state:
                print("ERROR: We've spent too long listening for tone.  Aborting.")
                v.process_state = ProcessState.ABORTED

        elif v.process_state == ProcessState.STOP_TONE:
            if v.tone.inactive:
                v.process_state = ProcessState.DETECT_SILENCE_END

        elif v.process_state == ProcessState.DETECT_SILENCE_END:
            if v.detect_silence_end_detected:
                v.process_state = ProcessState.CLEANUP
        
        elif v.process_state == ProcessState.CLEANUP:
            if v.tone.inactive:
                if v.cleanup_cycles >= v.cleanup_cycles_threshold:
                    v.process_state = ProcessState.COMPLETED
                else:
                    v.process_state = ProcessState.DETECT_SILENCE_START
                        
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
            v.tone.stop()
            v.tone.output(outdata)

            
        if v.process_state == ProcessState.DETECT_SILENCE_START:
            # The tone was stopped in the previous state
            v.tone.output(outdata)

            for analysis in analyses:
                tones_level = analysis["freq_levels"]
                
                # Ensure that the levels are below the threshold
                if tones_level is not None:
                    # Check if levels are below the silence threshold
                    if tones_level[0] < v.detect_silence_start_threshold_levels:
                        v.detect_silence_start_samples += 1
                        if v.detect_silence_start_samples >= v.detect_silence_start_threshold_samples:
                            #print("Silence detected")
                            v.detect_silence_start_detected = True
                    else:
                        # Restart the counter
                        v.detect_silence_start_samples = 0
                else:
                    print("tones_levels was None")

            
        elif v.process_state == ProcessState.START_TONE:
            # Play tone #0
            v.tone.click(v.start_tone_click_duration)
            v.tone.output(outdata)
            
            # Start the timer from the moment the system says it will
            # play the audio.
            v.start_tone0_start_play_time = time.outputBufferDacTime

            # Send the data for off-thread analysis
            v.q_process.put_nowait(
                {"start": True,
                 "out": outdata.copy(),
                 "out_time": v.start_tone0_start_play_time,
                 "in": indata.copy(),
                 "in_time": time.inputBufferAdcTime
                }
            )

            
        elif v.process_state == ProcessState.DETECT_TONE:
            # Output tone, which may or may not be active
            v.tone.output(outdata)

            for analysis in analyses:
                tones_level = analysis["freq_levels"]
                
                if tones_level is not None:
                    # Are we hearing the tone?
                    if tones_level[0] > v.detect_tone_threshold:
                        #print("Tone detected")
                        v.detect_tone_detected = True

                        # No need to process the remaining samples
                        break
                else:
                    print("tones_levels was None")

            # Send the data for off-thread analysis
            v.q_process.put_nowait(
                {"out": outdata.copy(),
                 "out_time": v.start_tone0_start_play_time,
                 "in": indata.copy(),
                 "in_time": time.inputBufferAdcTime
                }
            )

                
        elif v.process_state == ProcessState.STOP_TONE:
            # Fadeout tone
            #v.tone.fadeout(v.stop_tone_fadeout_duration)
            v.tone.output(outdata)

            # Send the data for off-thread analysis
            v.q_process.put_nowait(
                {"out": outdata.copy(),
                 "out_time": v.start_tone0_start_play_time,
                 "in": indata.copy(),
                 "in_time": time.inputBufferAdcTime
                }
            )
            
        elif v.process_state == ProcessState.DETECT_SILENCE_END:
            # The tone was stopped in the previous state
            v.tone.output(outdata)

            for analysis in analyses:
                tones_level = analysis["freq_levels"]
                
                # Ensure that the levels are below the threshold
                if tones_level is not None:
                    if tones_level[0] < v.detect_silence_end_threshold_levels:
                        v.detect_silence_end_samples += 1
                        if v.detect_silence_end_samples >= v.detect_silence_end_threshold_samples:
                            #print("Silence detected")
                            v.detect_silence_end_detected = True
                    else:
                        # Restart the timer
                        v.detect_silence_end_samples = 0
                else:
                    print("tones_levels was None")

            # Send the data for off-thread analysis
            v.q_process.put_nowait(
                {"out": outdata.copy(),
                 "out_time": v.start_tone0_start_play_time,
                 "in": indata.copy(),
                 "in_time": time.inputBufferAdcTime
                }
            )
            
                
        elif v.process_state == ProcessState.CLEANUP:
            # Keep outputting tone until it's inactive
            v.tone.output(outdata)

            # Send the data for off-thread analysis
            v.q_process.put_nowait(
                {"end":True}
            )

            # Reset key variables
            v.detect_silence_start_start_time = None            
            v.detect_silence_start_detected = False
            v.detect_silence_end_start_time = None            
            v.detect_silence_end_detected = False
            v.detect_tone_start_detect_time = None            
            v.detect_tone_detected = False

            # Increment the number of cleanup cycles
            v.cleanup_cycles += 1
            

        elif v.process_state == ProcessState.COMPLETED:
            # Actively fill outdata with zeros
            outdata.fill(0)
            print("Completed phase one latency measurement")
            exception = sd.CallbackStop

        
        elif v.process_state == ProcessState.ABORTED:
            # Actively fill outdata with zeros
            outdata.fill(0)
            print("Aborted phase one latency measurement")
            exception = sd.CallbackAbort

        
        # Store output
        # ============
        v.q.put(outdata.copy())

        # Terminate if required
        # =====================
        if exception is not None:
            raise exception


    # Play first tone
    # Open a read-write stream
    stream = sd.Stream(samplerate=samples_per_second,
                       #channels=channels, #FIXME
                       dtype=numpy.float32,
                       latency=desired_latency,
                       callback=callback,
                       finished_callback=v.event.set)

    print("Measuring latency...")
    with stream:
        print("Stated stream latency:", stream.latency)
        v.event.wait()  # Wait until measurement is finished


    print("Processing collected samples...")
    latencies = process_samples(v.q_process)
        
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
    print("Finished measurement of latency.")

    return latencies


        
def _measure_latency(desired_latency="high"):
    print("Desired latency:", desired_latency)
    levels = measure_levels(desired_latency)
    print("\n")
    latencies = measure_latency_phase_one(levels, desired_latency)

    return numpy.mean(latencies)
    
    

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

    _measure_latency(
        desired_latency = 100/1000 # seconds
        #desired_latency="high"
    )
