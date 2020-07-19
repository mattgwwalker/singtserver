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
from fft_analyser import FFTAnalyser
from tone import Tone

def process_click_data(q, detection_threshold):
    if q.empty():
        print("Queue is empty in function")

    results = []
    while True:
        # Get next item from queue
        try:
            item = q.get_nowait()
        except queue.Empty:
            print("No more data")
            break

        #print(item.keys())

        try:
            play_click_start_time = item["play_click_start_time"]
            clock_delta = item["clock_delta"]
            play_click_count = item["play_click_count"]

            click_detected_start_time = None
            click_detected_end_time = None
            multiple_detections = False
        except KeyError:
            # We can't be at the start of a click
            pass

        try:
            time = item["time"]
            mono = item["mono"]

            detected = mono > detection_threshold

            if any(detected):
                #print("Detected")
                # Loop through levels and find start and end times for the click
                samples_per_second = 48000 # FIXME
                wave_length = 1/375 # FIXME
                for i, d in enumerate(detected):
                    if d:
                        t = time + i/samples_per_second
                        #print("at time",t)
                        if click_detected_start_time is None:
                            click_detected_start_time = t
                            click_detected_end_time = t
                        elif t < click_detected_end_time + wave_length*3: #FIXME
                            click_detected_end_time = t
                        else:
                            multiple_detections = True
        except KeyError:
            # We don't have data to process
            pass

        try:
            assert item["end"] == True

            # Store results from just processed click data
            if not multiple_detections:
                measured_delta = click_detected_start_time - play_click_start_time
                latency = clock_delta + measured_delta
                results.append(latency)
            else:
                print("Multiple click detections")
        except KeyError:
            pass
            
    print("Latency results (ms):")
    print(numpy.round(numpy.array(results, numpy.float32)*1000))
        
    if len(results)>=2:
        median = numpy.median(results)
        return median
    else:
        print("Failed to accumulate sufficient results")
        return None
        
            

# Phase Two
# =========
# Measure latency accurately via clicks
def measure_latency_phase_two(levels, desired_latency="high", samples_per_second=48000, channels=(2,2)):
    """Channels are specified as a tuple of (input channels, output channels)."""
    input_channels, output_channels = channels

    # Class to describe the current state of the process
    class ProcessState(Enum):
        RESET = 0
        DETECT_SILENCE = 10
        PLAY_CLICK = 20
        DETECT_CLICK = 30
        CLEANUP = 40
        COMPLETED = 50
        ABORTED = 60

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

            # Queues to hold input and output frames for debugging
            self.q_in = queue.Queue()
            self.q_out = queue.Queue()

            # Queue to hold click-based information for processing
            # outside of the audio thread.
            self.q_click = queue.Queue()
            
            # Store samples per second
            self.samples_per_second = samples_per_second
        
            # Allocate space for recording
            max_recording_duration = 10 #seconds
            max_recording_samples = max_recording_duration * samples_per_second
            self.rec_pcm = numpy.zeros((
                max_recording_samples,
                input_channels
            ))

            # Instance of the Fast Fourier Transform (FFT) analyser
            self.fft_analyser = FFTAnalyser(
                array=self.rec_pcm,
                samples_per_second=samples_per_second
            )

            # Tone to produce clicks
            self.tone = Tone(375)

            # Initialise recording position
            self.rec_position = 0

            # Current state of the process
            self.process_state = ProcessState.RESET

            # Variable to record when we entered the current state
            self.state_start_time = None

            # Variables from levels
            self.silence_abs_pcm_mean = levels["silence_abs_pcm_mean"]
            self.silence_abs_pcm_sd = levels["silence_abs_pcm_sd"]
            self.tone0_abs_pcm_mean = levels["tone0_abs_pcm_mean"]
            self.ton0_abs_pcm_sd = levels["tone0_abs_pcm_sd"]

            # Variables for detect silence
            self.detect_silence_detected = False
            self.detect_silence_threshold_num_sd = 5 # std. deviations
            self.detect_silence_threshold_samples = 20
            self.detect_silence_samples = 0 # samples
            
            # Variables for CLEANUP
            self.cleanup_cycles = 0
            self.cleanup_cycles_threshold = 3

            # Variables for PLAY_CLICK
            self.play_click_count = 0

    # Create an instance of the shared variables
    v = SharedVariables(samples_per_second)


    # TODO: Check that silence and detection levels are not
    # overlapping.
    
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
        
        # # Clear the first half second of the recording buffer if we've
        # # recorded more than one second
        # if v.rec_position > v.samples_per_second:
        #     seconds_to_clear = 0.5 # seconds
        #     samples_to_clear = int(seconds_to_clear * v.samples_per_second)
        #     v.rec_pcm = numpy.roll(v.rec_pcm, -samples_to_clear, axis=0)
        #     v.rec_position -= samples_to_clear

        
        # Analysis
        # ========

        assert v.rec_pcm is v.fft_analyser._pcm
        analyses = v.fft_analyser.run(v.rec_position)
        #print(tones_level)
        

        # Transitions
        # ===========

        previous_state = v.process_state

        if v.process_state == ProcessState.RESET:
            v.process_state = ProcessState.DETECT_SILENCE

        elif v.process_state == ProcessState.DETECT_SILENCE:
            if v.detect_silence_detected:
                v.process_state = ProcessState.PLAY_CLICK
            
        elif v.process_state == ProcessState.PLAY_CLICK:
            v.process_state = ProcessState.DETECT_CLICK

        elif v.process_state == ProcessState.DETECT_CLICK:
            if time.inputBufferAdcTime - v.play_click_start_time > 0.5: #FIXME
                v.process_state = ProcessState.CLEANUP
            
        elif v.process_state == ProcessState.CLEANUP:
            if v.play_click_count >= 5: #FIXME
                v.process_state = ProcessState.COMPLETED
            else:
                v.process_state = ProcessState.PLAY_CLICK
        
        elif v.process_state == ProcessState.COMPLETED:
            pass

        
        # Set state start time
        if previous_state != v.process_state:
            v.state_start_time = time.currentTime
        
        
        # States
        # ======

        if v.process_state == ProcessState.RESET:
            # It's a requirement that outdata is always actively
            # filled
            outdata.fill(0)

            
        elif v.process_state == ProcessState.DETECT_SILENCE:
            # It's a requirement that outdata is always actively
            # filled
            outdata.fill(0)

            for analysis in analyses:
                abs_pcm_mean = analysis["abs_pcm_mean"]
            
                # Are we hearing silence?  Ensure we're within an
                # acceptable number of standard deviations from the mean.
                num_sd = abs((abs_pcm_mean - v.silence_abs_pcm_mean) / v.silence_abs_pcm_sd)

                if num_sd < v.detect_silence_threshold_num_sd:
                    v.detect_silence_samples += 1
                    if v.detect_silence_samples > v.detect_silence_threshold_samples:
                        #print("silence detected")
                        v.detect_silence_detected = True
                else:
                    print("not silent; resetting")
                    v.detect_silence_start_samples = 0

            
        elif v.process_state == ProcessState.PLAY_CLICK:
            v.tone.click(5/1000) # FIXME
            v.tone.output(outdata)

            # Start timing
            v.play_click_start_time = time.outputBufferDacTime

            v.play_click_count += 1

            clock_delta = (
                time.outputBufferDacTime
                - time.inputBufferAdcTime
            )
            
            # Queue the details for off-thread processing
            v.q_click.put_nowait(
                {"play_click_start_time": v.play_click_start_time,
                 "play_click_count": v.play_click_count,
                 "clock_delta": clock_delta
                }
            )

                
        elif v.process_state == ProcessState.DETECT_CLICK:
            # Continue to output click, which will rapidly become
            # inactive and output zeros.
            v.tone.output(outdata)

            # If we have two channels, average them to give us a mono channel
            channels = indata.shape[1]
            if channels == 2:
                left = indata[:,0]
                right = indata[:,1]
                mono = (left+right) / 2
            elif channels == 1:
                mono = indata[:,0]
            else:
                raise Exception(
                    "Attempted to analyse data with an unsupported "+
                    "number of channels ({:d})".format(channels)
                )
            
            # Measure the number of standard deviations away from silence
            num_sd = abs((mono - v.silence_abs_pcm_mean) / v.silence_abs_pcm_sd)

            # Queue the details for off-thread processing
            v.q_click.put_nowait(
                {"time": time.inputBufferAdcTime,
                 "mono": mono}
            )

                
        elif v.process_state == ProcessState.CLEANUP:
            # This should be inactive, and thus just output zeros
            v.tone.output(outdata)
            
            # Queue the details for off-thread processing
            v.q_click.put_nowait(
                {"end":True}
            )
            
            
        elif v.process_state == ProcessState.COMPLETED:
            # Actively fill outdata with zeros
            outdata.fill(0)

            print("Completed phase two latency measurement")
            exception = sd.CallbackStop

        
        elif v.process_state == ProcessState.ABORTED:
            # Actively fill outdata with zeros
            outdata.fill(0)
            print("Aborted phase two latency measurement")
            raise sd.CallbackAbort

        
        # Store output
        # ============
        v.q_in.put_nowait(indata.copy())
        v.q_out.put_nowait(outdata.copy())

        # Terminate if required
        # =====================
        if exception is not None:
            raise exception
    

    # Play first tone
    # Open a read-write stream
    stream = sd.Stream(samplerate=samples_per_second,
                       channels=channels,
                       dtype=numpy.float32,
                       latency=desired_latency,
                       callback=callback,
                       finished_callback=v.event.set)

    print("Measuring latency...")
    with stream:
        v.event.wait()  # Wait until measurement is finished


    print("Processing click data...")
    detection_threshold = (v.silence_abs_pcm_mean + v.tone0_abs_pcm_mean)/2
    median_latency = process_click_data(v.q_click, detection_threshold)
        
    # Save output as wave file
    print("Writing output wave file")
    wave_file = wave.open("out.wav", "wb")
    wave_file.setnchannels(2) #FIXME
    wave_file.setsampwidth(2)
    wave_file.setframerate(samples_per_second)
    while True:
        try:
            data = v.q_out.get_nowait()
        except:
            break
        data = data * (2**15-1)
        data = data.astype(numpy.int16)
        wave_file.writeframes(data)
    wave_file.close()


    # Save input as wave file
    print("Writing input wave file")
    wave_file = wave.open("in.wav", "wb")
    wave_file.setnchannels(2) #FIXME
    wave_file.setsampwidth(2)
    wave_file.setframerate(samples_per_second)
    while True:
        try:
            data = v.q_in.get_nowait()
        except:
            break
        data = data * (2**15-1)
        data = data.astype(numpy.int16)
        wave_file.writeframes(data)
    wave_file.close()


        
    # Done!
    print("Finished.")
    return median_latency

        
def _measure_latency(desired_latency="high"):
    print("Desired latency:", desired_latency)
    levels = measure_levels(desired_latency)
    print("\n")
    accurate_latency = measure_latency_phase_two(levels, desired_latency)
    
    

if __name__ == "__main__":
    print("")
    print("Measuring Latency: Phase Two")
    print("============================")
    print("FIXME: NEEDS RE_WRITE")
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
        desired_latency=100/1000 # seconds
        #desired_latency="high"
    )
