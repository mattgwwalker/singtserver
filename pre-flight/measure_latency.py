# Check that audio can be played... at all.
import pyogg
import time
import sounddevice as sd
import numpy
from enum import Enum
import time
import threading
import math
import operator
import wave
from measure_levels import measure_levels, FFTAnalyser, Tone

# Phase One
# =========
# Measure latency approximately via tones.
def phase_one(levels, desired_latency="low", samples_per_second=48000, channels=(2,2)):
    """Channels are specified as a tuple of (input channels, output channels)."""
    input_channels, output_channels = channels

    # Class to describe the current state of the process
    class ProcessState(Enum):
        RESET = 0
        DETECT_TONE0 = 10
        DETECT_TONE0_TONE1 = 60
        COMPLETING = 70
        COMPLETED = 80
        ABORTED = 90

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
            
            self.samples_per_second = samples_per_second
        
            # Allocate space for recording
            max_recording_duration = 2 #seconds
            max_recording_samples = max_recording_duration * samples_per_second
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
                               self.tone_duration,
                               self.samples_per_second,
                               output_channels,
                               1/n_tones)
                          for freq in self.fft_analyser.freqs]

            # Variables for levels
            self.tone0_mean = levels["tone0_mean"]
            self.tone0_sd = levels["tone0_sd"]
            self.tone0_tone1_mean = levels["tone0_tone1_mean"]
            self.tone0_tone1_sd = levels["tone0_tone1_sd"]



    # FIXME: The code below isn't functional, but it useful to copy
    # from
    return
            
    # Initialise tones detected, which stores the number of samples
    # for which the tone has been continuously detected.
    tones_detected = [0] * len(tones)

    # Initialise the number of samples for which the tone has been
    # played; None indicates the tone is not being played.
    tones_played = [None] * len(tones)

    # Initialise the number of samples for which the tone has been
    # continuously silent; we start in silence
    tones_silence = [0] * len(tones)

    # Set the minimum on-time for a tone
    min_on_seconds = 0.2 # seconds
    min_on_samples = min_on_seconds * samples_per_second

    # Set the minimum off-time for a tone
    min_off_seconds = 0.2 # seconds
    min_off_samples = min_off_seconds * samples_per_second

    # Specify the minimum duration for a tone to be continuously
    # detected before we will process the detection.
    threshold_detected_ms = 5 #ms
    threshold_detected_samples = (
        threshold_detected_ms * samples_per_second // 1000
    )

    
    # States for a tone
    class ToneState(Enum):
        RESET = 0
        #STARTING = 1
        PLAYING = 2   # play for min on time
        STOPPING = 3  # fade out tone
        STOPPED = 4   # wait for min off time
    tones_state = [ToneState.RESET] * len(tones)

    # Commands for a tone
    class ToneCommand(Enum):
        NONE = 0
        START = 1
        STOP = 2
    tones_cmd = [ToneCommand.NONE] * len(tones)

    # Start the first tone
    #tones_cmd[0] = ToneCommand.START
    #tones_cmd[1] = ToneCommand.START

    # Timers for each tone
    tones_start_time = [None] * len(tones)
    
    # List for latency measurements
    latencies = []

    # States for the thread
    class ThreadState(Enum):
        RESET = 0
        RUNNING = 1
        ENDING = 2
        ENDED = 3
        ABORTING = 4
        ABORTED = 5
    thread_state = ThreadState.RESET
    
    # Commands for the thread
    class ThreadCommand(Enum):
        NONE = 0
        END = 1
        ABORT = 2
    thread_cmd = ThreadCommand.NONE

    # List of noise levels recorded when playing nothing
    tones_noise_levels = [[]] * len(tones)
    
    
    # Callback for when the recording buffer is ready.  The size of the
    # buffer depends on the latency requested.
    def callback(indata, outdata, samples, time, status):
        #nonlocal rec_pcm, rec_position, tones_position, tones_detected, tones_played
        #nonlocal tones_silence, latencies, thread_state, thread_cmd

        # FIXME: These aren't necessary when finished
        assert len(indata) == len(outdata)
        assert len(indata) == samples
        
        #print("")
        if status:
            print(status)





        # Analysis
        # ========

        # Store the recording
        rec_pcm[rec_position:rec_position+samples] = indata[:]
        rec_position += samples

        # If we have more than the required number of samples
        # recorded, execute FFT analysis
        if rec_position > fft_n:
            data = rec_pcm[rec_position-256:rec_position]
            data_transpose = data.transpose()
            left = data_transpose[0]
            right = data_transpose[1]
            mono = left+right / 2

            y = numpy.fft.rfft(
                # Use of Hann window to reduce spectral leakage (see
                # https://stackoverflow.com/questions/8573702/units-of-frequency-when-using-fft-in-numpy)
                # I'm not sure this is really necessary.
                mono * numpy.hanning(len(mono)), 
                n=fft_n
            )
            y = numpy.abs(y)




            # sp_max = sp.max()
            # if sp_max == 0:
            #     # We don't have any signal; stop analysing
            #     return 
            # db = 20*numpy.log10(sp / sp.max())

            # TEST
            # if sp.max() > 1.0:
            #     print("sp.max():", sp.max())
            #     assert False
            # db = 20*numpy.log10(sp) # assumes the max volume is 1.0  

            dbs = []
            for freq_index in freq_indices:
                y = db[freq_index]
                dbs.append(y)

            sum_others = numpy.sum(db) - numpy.sum(dbs)
            mean_others = sum_others / len(db)

            # Clear decisions
            decisions = [False] * len(freqs)

            # FIXME: These probably shouldn't be hard-coded
            threshold_noise_db = 20 # dB louder than noise
            threshold_signal_db = 20 # db within other signals

            for index, _ in enumerate(tones):
                index_other1 = (index+1) % len(tones)
                index_other2 = (index+2) % len(tones)
                decisions[index] = (
                    (dbs[index] - threshold_noise_db > mean_others) and
                    (dbs[index] + threshold_signal_db > dbs[index_other1]) and
                    (dbs[index] + threshold_signal_db > dbs[index_other2])
                )

                if decisions[index]:
                    tones_detected[index] += samples
                else:
                    tones_detected[index] = 0

            print(
            #    samples,
            #    "play:",tones_play_cmd,
            #    "decision:",decisions,
            #    "s.played:",tones_played,
            #    "s.detected:",tones_detected,
            #    round(mean_others,1),
                numpy.around(dbs,2)
            )

        # Clear the first half second of the recording buffer if we've
        # recorded more than one second
        if rec_position > samples_per_second:
            seconds_to_clear = 0.5 # seconds
            samples_to_clear = int(seconds_to_clear * samples_per_second)
            rec_pcm = numpy.roll(rec_pcm, -samples_to_clear, axis=0)
            rec_position -= samples_to_clear











            
        # Thread Transitions
        # ==================

        if thread_state == ThreadState.RESET:
            thread_state = ThreadState.RUNNING
            
        elif thread_state == ThreadState.RUNNING:
            if thread_cmd == ThreadCommand.END:
                thread_state = ThreadState.ENDING
            elif thread_cmd == ThreadCommand.ABORT:
                thread_state = ThreadState.ABORTING

        elif thread_state == ThreadState.ENDING:
            next_state = ThreadState.ENDED
            for tone_state in tones_state:
                if (tone_state != ToneState.STOPPED and
                    tone_state != ToneState.RESET):
                    next_state = ThreadState.ENDING
            thread_state = next_state

        elif thread_state == ThreadState.ENDED:
            # We stay in this state
            pass

        elif thread_state == ThreadState.ABORTING:
            next_state = ThreadState.ABORTED
            for tone_state in tones_state:
                if (tone_state != ToneState.STOPPED and
                    tone_state != ToneState.RESET):
                    next_state = ThreadState.ABORTING
            thread_state = next_state

        elif thread_state == ThreadState.ABORTED:
            # We stay in this state
            pass
        

        # Thread States
        # =============
        
        if thread_state == ThreadState.RESET:
            pass
            
        elif thread_state == ThreadState.RUNNING:
            pass

        elif thread_state == ThreadState.ENDING:
            pass

        elif thread_state == ThreadState.ENDED:
            raise sd.CallbackStop

        elif thread_state == ThreadState.ABORTING:
            pass

        elif thread_state == ThreadState.ABORTED:
            raise sd.CallbackAbort
        
            
        # Tone Transitions
        # ================

        for index, tone_state in enumerate(tones_state):
            tone_cmd = tones_cmd[index]

            # RESET Transitions
            if tone_state == ToneState.RESET:
                if tone_cmd == ToneCommand.NONE:
                    pass
                elif tone_cmd == ToneCommand.START:
                    tones_state[index] = ToneState.PLAYING
                    #print("\nStarting timer for tone #",index)
                    #print("time.outputBufferDacTime:", time.outputBufferDacTime)
                    tones_start_time[index] = time.outputBufferDacTime
                else:
                    print("Invalid command (",tone_cmd,") for tone",index,"in state",tone_state)
                tones_cmd[index] = ToneCommand.NONE

            # PLAYING Transitions
            elif tone_state == ToneState.PLAYING:
                if tone_cmd == ToneCommand.NONE:
                    pass
                elif tone_cmd == ToneCommand.STOP:
                    if tones_played[index] >= min_on_samples:
                        tones_state[index] = ToneState.STOPPING
                    else:
                        pass
                        #print("Tone",index,"requested to stop, ",
                        #      "but it hasn't been on for long enough")
                else:
                    print("Invalid command (",tone_cmd,") for tone",index,"in state",tone_state)
                    # Clear the just-processed command
                    tones_cmd[index] = ToneCommand.NONE

            # STOPPING Transitions
            elif tone_state == ToneState.STOPPING:
                # From this state, move immediately to Stopped.
                tones_state[index] = ToneState.STOPPED

            # STOPPED Transitions
            elif tone_state == ToneState.STOPPED:
                # Ensure that the tone has been off for the minimum
                # required time.
                if tones_silence[index] >= min_off_samples:
                    tones_state[index] = ToneState.RESET

                
        #print("Stop cmd:", tones_stop_cmd)
        #print("silence:", tones_silence)

        # States
        # ======
                
        # Fill the outdata with zeros
        if output_channels == 1:
            outdata[:] = [0] * samples
        else:
            outdata[:] = [[0,0]] * samples


        for index, tone_state in enumerate(tones_state):
            #print("Tone",index,"in state",tone_state)

            
            # RESET State
            if tone_state == ToneState.RESET:
                pass

            
            # PLAYING State
            elif tone_state == ToneState.PLAYING:
                #print("Playing tone #", index)
                # We have been requested to play the tone
                if tones_position[index]+samples <= len(tones[index]):
                    # Copy tone in one hit
                    outdata[:] += tones[index] \
                        [tones_position[index]:tones_position[index]+samples]
                    tones_position[index] += samples
                else:
                    # Need to loop back to the beginning of the tone
                    remaining = len(tones[index])-tones_position[index]
                    outdata[:remaining] += (
                        tones[index][tones_position[index]:len(tones[index])]
                    )
                    outdata[remaining:] += (
                        tones[index][:samples-remaining]
                    )
                    tones_position[index] = samples-remaining
                if tones_played[index] is None:
                    tones_played[index] = samples
                else:
                    tones_played[index] += samples

                # Given we're playing this tone, set silence to None
                tones_silence[index] = None

                # While we're playing, detect if we've heard the tone
                if index==0:
                    # We're playing the background tone
                    if tones_detected[0] > threshold_detected_samples:
                        # The background tone has been detected, so we
                        # need to start measuring latency.  Start tone
                        # #1.
                        if tones_state[1] is ToneState.RESET:
                            # We aren't currently playing, so start
                            # playing now.
                            tones_cmd[1] = ToneCommand.START
                    elif tones_played[0] > 48000:
                        # We haven't heard tone #0 for a whole second;
                        # give up.
                        thread_cmd = ThreadCommand.ABORT
                        

                elif index==1:
                    # We're playing tone #1
                    if tones_detected[1] > threshold_detected_samples:
                        # Tone #1 has been detected.  Store how long
                        # it took, and then turn it off.
                        if tones_start_time[1] is not None:
                            # print("time.inputBufferAdcTime:",time.inputBufferAdcTime)
                            # print("samples:", samples)
                            # print("tones_detected[1]:", tones_detected[1])
                            # print("samples_per_second:", samples_per_second)
                            end_time = (time.inputBufferAdcTime
                                        + samples / samples_per_second
                                        - tones_detected[1] / samples_per_second)
                            # print("end_time:",end_time)
                            latency = end_time - tones_start_time[1]
                            print("Latency of",latency*1000,"ms detected")
                            if latency < 0:
                                #print("Negative latency; discarding")
                                pass
                            else:
                                latencies.append(latency)
                                tones_start_time[1] = None
                                tones_cmd[1] = ToneCommand.STOP
                        
                    
            # if tones_detected[0] > 0.5*samples_per_second:
            #     # If we've just started playing this tone, set tones
            #     # played to zero
            #     if tones_played[1] is None:
            #         print("Playing second tone")
            #         tones_played[1] = 0
            #         tones_play_cmd[1] = True





                # # Respond to detection of the tone if we've heard it
                # # continuously for sufficient time.
                # if (#index != 0 and
                #         tones_detected[index] >= threshold_detected_samples):
                #     samples_since_started = tones_played[index] - threshold_samples 
                #     seconds_since_started = samples_since_started / samples_per_second
                #     print("time_since_start:",
                #           round(seconds_since_started*1000, 1),
                #           "ms")

                #     print("Requesting that tone #",index,"stop")
                #     tones_cmd[index] = ToneCommand.STOP




            # STOPPING State
            elif tone_state == ToneState.STOPPING:
                #print("Stopping tone #", index)
                # We have been requested to stop the tone; we want to
                # finish on a zero-crossing.  Rather than searching
                # for a zero-crossing, we can just fade out the tone.
                fade_multiplier = numpy.linspace(1, 0, samples)
                if output_channels == 2:
                    fade_multiplier = [[x,x] for x in fade_multiplier]
                
                if tones_position[index]+samples <= len(tones[index]):
                    # Apply multiplier
                    faded_pcm = tones[index] \
			[tones_position[index]:tones_position[index]+samples] \
                        * fade_multiplier
                    # Copy tone in one hit
                    outdata[:] += faded_pcm
                else:
                    # Need to loop back to the beginning of the tone
                    remaining = len(tones[index])-tones_position[index]
                    faded_pcm = fade_multiplier
                    faded_pcm[:remaining] = (
                        tones[index][tones_position[index]:len(tones[index])] \
                        * fade_multiplier[:remaining]
                    )
                    faded_pcm[remaining:] = (
                        tones[index][:samples-remaining] \
                        * fade_multiplier[-samples-remaining-1:]
                    )
                    outdata[:] = faded_pcm[:]

                # Set tone position back to zero
                tones_position[index] = 0

                # Set number of samples played back to None to
                # indicate that it's not currently being played
                tones_played[index] = None

                # Set the number of samples of silence to zero
                tones_silence[index] = 0


            # STOPPED State
            elif tone_state == ToneState.STOPPED:
                # Increment the number of samples of silence; it was
                # reset to zero in the STOPPING state.
                tones_silence[index] += samples

                # Set the position in the PCM back to zero
                tones_position[index] = 0

                # TEST
                tones_cmd[index] = ToneCommand.START
            
        


            
    # Play first tone
    # Open a read-write stream
    stream = sd.Stream(samplerate=48000,
                       channels=2,
                       dtype=numpy.float32,
                       latency="high",#"low",
                       callback=callback)

    print("Playing...")
    with stream:
        input()  # Wait until playback is finished

    # Done!
    print("Finished.")




        
def phase_two(approximate_latency):
    pass



def measure_latency():
    print("")
    print("Measuring Latency")
    print("=================")
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

    levels = measure_levels(desired_latency="low")
    approximate_latency = phase_one(levels)
    #accurate_latency = phase_two(approximate_latency)
    
    

if __name__ == "__main__":
    measure_latency()
