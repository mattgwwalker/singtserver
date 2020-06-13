# Check that audio can be played... at all.
import pyogg
import time
import sounddevice as sd
import numpy
from enum import Enum
import time


# Fast Fourier Transform for recorded samples, specifically focused on
# certain frequencies.
class FFTAnalyser:
    def __init__(self, samples_per_second):
        # Number of samples for FFT analysis.  Approximately 5ms at
        # 48kHz.
        self._n = 256 

        fft_freqs = numpy.fft.rfftfreq(self._n) * samples_per_second
        self._freq_indices = [2, 5]
        self._freqs = [fft_freqs[i] for i in self._freq_indices]

        print("FFT analysis configured for frequencies (Hz):", self._freqs)

    
    @property
    def n_freqs(self):
        """Gives the number of frequencies returned by the run() method."""
        return len(self._freq_indices)


    @property
    def freqs(self):
        """Gives the frequencies focussed on by this analyser."""
        return self._freqs
        
    def run(self, rec_pcm, rec_position):
        # If we have more than the required number of samples
        # recorded, execute FFT analysis
        if rec_position > self._n:
            left = rec_pcm[rec_position-self._n:rec_position, 0]
            right = rec_pcm[rec_position-self._n:rec_position, 1]
            #data_transpose = data.transpose()
            #left = data_transpose[0]
            #right = data_transpose[1]
            mono = (left+right) / 2

            y = numpy.fft.rfft(
                # Use of Hann window to reduce spectral leakage (see
                # https://stackoverflow.com/questions/8573702/units-of-frequency-when-using-fft-in-numpy)
                # I'm not sure this is really necessary.
                mono * numpy.hanning(len(mono)), 
                n=self._n
            )
            y = numpy.abs(y)

            return y[self._freq_indices]
    


class Tone:
    def __init__(self, freq, duration=1.0, samples_per_second=48000, channels=2):
        # FIXME: The duration should be extended so that the PCM
        # finishes on a zero-crossing.
        
        t = numpy.linspace(
            0,
            duration,
            int(duration * samples_per_second),
            False
        )

        pcm = numpy.sin(freq * t * 2 * numpy.pi)

        if channels == 2:
            two_channels = [[x,x] for x in pcm]
            self._pcm = numpy.array(two_channels, dtype=numpy.float32)
        else:
            self._pcm = pcm

        self._pos = 0

        
        
    def play(self, samples, outdata):
        # Ensure the number of channels is the same
        assert outdata.shape[1] == self._pcm.shape[1]
        
        if self._pos+samples <= len(self._pcm):
            # Copy tone in one hit
            outdata[:] = self._pcm \
                [self._pos:self._pos+samples]
            self._pos += samples
        else:
            # Need to loop back to the beginning of the tone
            remaining = len(self._pcm)-self._pos
            outdata[:remaining] = (
                self._pcm[self._pos:len(self._pcm)]
            )
            outdata[remaining:] = (
                self._pcm[:samples-remaining]
            )
            self._pos = samples-remaining





        
# Measure Levels
# ==============

# Measure levels of silence at tone #0's frequency.  Then play tone #0
# and ask user to increase the system volume until non-silence is
# detected.  From here, ask the user not to change the system volume.
#
# Then, measure levels of tone #0 and not-tone #1. Play tone #0 and
# tone #1 and wait until we detect not-not-tone#1.  Finally, measure
# levels of tone #0 and tone #1.

def measure_levels(desired_latency="low", samples_per_second=48000, channels=(2,2)):
    """Channels are specified as a tuple of (input channels, output channels)."""
    input_channels, output_channels = channels

    # Class to describe the current state of the process
    class ProcessState(Enum):
        RESET = 0
        MEASURE_SILENCE = 1
        DETECT_TONE0 = 2
        MEASURE_TONE0 = 3
        DETECT_TONE1 = 4
        MEASURE_TONE0_TONE1 = 5
        COMPLETED = 6
        ABORTED = 7


    # Create a class to hold the shared variables
    class SharedVariables:
        def __init__(self, samples_per_second):
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

            self.fft_analyser = FFTAnalyser(samples_per_second)

            # Variables for the measurement of levels of silence
            self.silence_seconds = 0.5 # seconds
            self.silence_levels = []
            self.silence_start_time = None
            self.silence_mean = None
            self.silence_sd = None
            self.silence_mean_threshold = 1e-6
            self.silence_sd_threshold = 1e-6

            # Variables for tones
            self.tone_duration = 1 # second
            self.tones = [Tone(freq,
                               self.tone_duration,
                               self.samples_per_second,
                               output_channels)
                          for freq in self.fft_analyser.freqs]

            # Variables for non-silence
            self.non_silence_threshold_num_sd = 6 # number of std. deviations away from silence
            self.non_silence_threshold_duration = 0.5 # seconds of non-silence
            self.non_silence_threshold_abort_duration = 5 # seconds waiting for non-silence
            self.non_silence_start_time = None
            self.non_silence_detected = False
            self.non_silence_abort_start_time = None

            # Variables for measurement of tone0 and not-tone1
            self.tone0_levels = []
            self.tone0_start_time = None
            self.tone0_threshold_duration = 0.5 # seconds of tone0 and not tone1
            self.tone0_mean = None
            self.tone0_sd = None

            # Variables for detection of tone1
            self.detect_tone1_threshold_num_sd = 6 # number of std. deviations away from not-tone1
            self.detect_tone1_threshold_duration = 0.5 # seconds of not-not-tone1
            self.detect_tone1_start_time = None
            self.detect_tone1_detected = False

            # Variables for measurement of tone0 and tone1
            self.tone0_tone1_levels = []
            self.tone0_tone1_start_time = None
            self.tone0_tone1_threshold_duration = 0.5 # seconds of tone0 and tone1
            self.tone0_tone1_mean = None
            self.tone0_tone1_sd = None

    # Create an instance of the shared variables
    v = SharedVariables(samples_per_second)
    
    # Callback for when the recording buffer is ready.  The size of the
    # buffer depends on the latency requested.
    def callback(indata, outdata, samples, time, status):
        # FIXME: This is rediculous!
        nonlocal v
        
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

        if v.process_state == ProcessState.RESET:
            v.process_state = ProcessState.MEASURE_SILENCE
            v.silence_start_time = time.inputBufferAdcTime
            
            
        elif v.process_state == ProcessState.MEASURE_SILENCE:
            if v.silence_mean is not None and \
               v.silence_sd is not None:
                if any(v.silence_mean < v.silence_mean_threshold):
                    print("Implausibly low mean level detected for silence; aborting.")
                    v.process_state = v.ProcessState.ABORTED
                elif any(v.silence_sd < v.silence_sd_threshold):
                    print("Implausibly low standard deviation detected for silence; aborting.")
                    v.process_state = ProcessState.ABORTED
                else:
                    # No reason not to continue
                    v.process_state = ProcessState.DETECT_TONE0
                    v.non_silence_abort_start_time = time.currentTime
                    print("About to play tone.  Please increase system volume until the tone is detected.")

        elif v.process_state == ProcessState.DETECT_TONE0:
            if v.non_silence_detected:
                v.process_state = ProcessState.MEASURE_TONE0
                print("Base tone detected.  Please do not adjust system volume nor position of microphone or speakers")
            elif (time.currentTime - v.non_silence_abort_start_time
                  > v.non_silence_threshold_abort_duration):
                print("Giving up waiting for non-silence; aborting.")
                v.process_state = ProcessState.ABORTED
                

        elif v.process_state == ProcessState.MEASURE_TONE0:
            if v.tone0_mean is not None and \
               v.tone0_sd is not None:
                v.process_state = ProcessState.DETECT_TONE1
                
        elif v.process_state == ProcessState.DETECT_TONE1:
            if v.detect_tone1_detected:
                v.process_state = ProcessState.MEASURE_TONE0_TONE1

        elif v.process_state == ProcessState.MEASURE_TONE0_TONE1:
            if v.tone0_tone1_mean is not None and \
               v.tone0_tone1_sd is not None:
                v.process_state = ProcessState.COMPLETED

        elif v.process_state == ProcessState.COMPLETED:
            pass    
        

        # States
        # ======

        if v.process_state == ProcessState.RESET:
            pass
            
        elif v.process_state == ProcessState.MEASURE_SILENCE:
            duration = time.currentTime - v.silence_start_time
            if duration <= v.silence_seconds:
                if tones_level is not None:
                    v.silence_levels.append(tones_level)
            else:
                # We've now collected enough samples
                #print("silence_levels:",silence_levels)
                v.silence_mean = numpy.mean(v.silence_levels, axis=0)
                v.silence_sd = numpy.std(v.silence_levels, axis=0)
                print("silence_mean:",v.silence_mean)
                print("silence_sd:", v.silence_sd)

                
        elif v.process_state == ProcessState.DETECT_TONE0:
            # Play tone #0
            v.tones[0].play(samples, outdata)

            # Calculate the number of standard deviations from silence
            num_sd = (tones_level[0] - v.silence_mean[0]) / v.silence_sd[0]

            if num_sd > v.non_silence_threshold_num_sd:
                if v.non_silence_start_time is None:
                    v.non_silence_start_time = time.currentTime
                else:
                    duration = time.currentTime - v.non_silence_start_time
                    if duration > v.non_silence_threshold_duration:
                        print("Non-silence detected")
                        v.non_silence_detected = True
            else:
                # Reset timer
                v.non_silence_start_time = None

                
        elif v.process_state == ProcessState.MEASURE_TONE0:
            # Play tone #0
            v.tones[0].play(samples, outdata)

            # Start the timer if not started
            if v.tone0_start_time is None:
                v.tone0_start_time = time.currentTime

            # TODO: Should we check that we've got non-silence?
                
            # Save the levels because we assume we're hearing tone #0
            v.tone0_levels.append(tones_level)

            duration = time.currentTime - v.tone0_start_time
            if duration > v.tone0_threshold_duration:
                # We've now collected enough samples
                v.tone0_mean = numpy.mean(v.tone0_levels, axis=0)
                v.tone0_sd = numpy.std(v.tone0_levels, axis=0)
                print("tone0_mean:",v.tone0_mean)
                print("tone0_sd:", v.tone0_sd)

                        
        elif v.process_state == ProcessState.DETECT_TONE1:
            # Temporary output buffer
            output_buffer = numpy.zeros(outdata.shape)
            # Play tone #0
            v.tones[0].play(samples, output_buffer)
            # Play tone #1
            v.tones[1].play(samples, outdata)
            # Combine the two tones
            outdata += output_buffer
            # Average the two tones to ensure we don't peak
            outdata /= 2 
            

            # Calculate the number of standard deviations from not-tone1
            num_sd = (tones_level[1] - v.tone0_mean[1]) / v.tone0_sd[1]

            if num_sd > v.detect_tone1_threshold_num_sd:
                if v.detect_tone1_start_time is None:
                    v.detect_tone1_start_time = time.currentTime
                else:
                    duration = time.currentTime - v.detect_tone1_start_time
                    if duration > v.detect_tone1_threshold_duration:
                        print("Tone #1 detected")
                        v.detect_tone1_detected = True
            else:
                # Reset timer
                v.non_silence_start_time = None
            

        elif v.process_state == ProcessState.MEASURE_TONE0_TONE1:
            # FIXME: The following code should be a function of some sort.
            
            # Temporary output buffer
            output_buffer = numpy.zeros(outdata.shape)
            # Play tone #0
            v.tones[0].play(samples, output_buffer)
            # Play tone #1
            v.tones[1].play(samples, outdata)
            # Combine the two tones
            outdata += output_buffer
            # Average the two tones to ensure we don't peak
            outdata /= 2 

            # Start the timer if not started
            if v.tone0_tone1_start_time is None:
                v.tone0_tone1_start_time = time.currentTime

            # TODO: Should we check that we've got not-not-tone1?
                
            # Save the levels because we assume we're hearing tone #1
            v.tone0_tone1_levels.append(tones_level)

            duration = time.currentTime - v.tone0_tone1_start_time
            if duration > v.tone0_tone1_threshold_duration:
                # We've now collected enough samples
                v.tone0_tone1_mean = numpy.mean(v.tone0_tone1_levels, axis=0)
                v.tone0_tone1_sd = numpy.std(v.tone0_tone1_levels, axis=0)
                print("tone0_tone1_mean:",v.tone0_tone1_mean)
                print("tone0_tone1_sd:", v.tone0_tone1_sd)

                
        elif v.process_state == ProcessState.COMPLETED:
            print("Finished measuring levels")
            raise sd.CallbackStop



        
    # Open a read-write stream
    stream = sd.Stream(samplerate=48000,
                       channels=2,
                       dtype=numpy.float32,
                       latency="high",#"low",  # FIXME: desired_latency
                       callback=callback)

    print("Measuring levels...")
    with stream:
        input()  # Wait until measurement is finished

    # Done!
    print("Finished measuring levels.")




# Phase One
# =========
# Measure latency approximately via tones.
def phase_one(desired_latency="low", samples_per_second=48000, channels=(2,2)):
    """Channels are specified as a tuple of (input channels, output channels)."""
    input_channels, output_channels = channels

    # Generate the tones required.  Frequencies chosen from mid-points
    # of FFT analysis.
    fft_n = 256 # Approximately 5ms at 48kHz
    fft_freqs = numpy.fft.rfftfreq(fft_n) * samples_per_second
    freqs = [375, 1125, 2250]

    # Get index of desired frequencies
    freq_indices = []
    for freq in freqs:
        indices = numpy.where(fft_freqs == freq)
        assert len(indices) == 1
        freq_indices.append(indices[0][0])

    # FIXME: This duration should be shorter, but it needs to finish
    # at a zero-crossing of the sine wave.  A quick fix is just to
    # make the duration much longer than it needs to be.
    duration = 10.0 # seconds
    t = numpy.linspace(0, duration, int(duration * samples_per_second), False)

    tones = []
    for freq in freqs:
        tone = numpy.sin(freq * t * 2 * numpy.pi)

        if output_channels == 2:
            two_channels = [[x,x] for x in tone]
            tones.append(numpy.array(two_channels, dtype=numpy.float32))
        else:
            tones.append(tone)

        del tone

        
    # Normalise the tones so that when combined they'll never clip
    for index,tone in enumerate(tones):
        tones[index] = tone / len(tones)
        
        
    # Initialise the current position for each tone
    tones_position = [0] * len(tones)


    # Allocate space for recording
    max_recording_duration = 2 #seconds
    max_recording_samples = max_recording_duration * samples_per_second
    rec_pcm = numpy.zeros((
        max_recording_samples,
        input_channels
    ))

    # Initialise recording position
    rec_position = 0

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
        nonlocal rec_pcm, rec_position, tones_position, tones_detected, tones_played
        nonlocal tones_silence, latencies, thread_state, thread_cmd

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



            # TEST
            # Let's try measuring the levels of silence
            for index, freq_index in enumerate(freq_indices):
                level = y[freq_index]
                print("level:", level)
                tones_noise_levels[index].append(level)

            return










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

    measure_levels()
    #approximate_latency = phase_one()
    #accurate_latency = phase_two(approximate_latency)
    
    

if __name__ == "__main__":
    measure_latency()
