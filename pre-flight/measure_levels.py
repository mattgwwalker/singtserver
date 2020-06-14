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
    def __init__(self, freq, duration=1.0, samples_per_second=48000, channels=2, max_level=1):
        """Freq in Hz, duration in seconds.  Will extend the duration so that
        a whole number of wavelengths are formed."""
        # Extend the duration so that the PCM finishes on a
        # zero-crossing.
        duration_wavelength = 1 / freq
        num_wavlengths = math.ceil(duration / duration_wavelength)
        duration = num_wavlengths * duration_wavelength
        
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

        # Noramlise
        self._pcm *= max_level

        self._pos = 0

        
        
    def play(self, samples, outdata, op = None):
        """Op needs to be an in-place operator (see
        https://docs.python.org/3/library/operator.html)"""
        # Ensure the number of channels is the same
        assert outdata.shape[1] == self._pcm.shape[1]
        
        if self._pos+samples <= len(self._pcm):
            # Copy tone in one hit
            data = self._pcm[self._pos:self._pos+samples]
            if op is None:
                outdata[:] = data
            else:
                op(outdata, data)
            self._pos += samples
        else:
            # Need to loop back to the beginning of the tone
            remaining = len(self._pcm)-self._pos
            head = self._pcm[self._pos:len(self._pcm)]
            tail = self._pcm[:samples-remaining]
            if op is None:
                outdata[:remaining] = head
                outdata[remaining:] = tail
            else:
                op(outdata[:remaining], head)
                op(outdata[remaining:], tail)

            self._pos = samples-remaining


    def _fade(self, samples, outdata, op, from_, to_):
        # Produce a linear fadeout multiplier
        faded = numpy.linspace(from_, to_, samples)

        # Adjust multiplier if two channels are needed
        if outdata.shape[1] == 2:
            faded = numpy.array([[x,x] for x in faded])

        # Get the samples as if they were being played, multiplying
        # them by the fadeout
        self.play(samples, faded, op=operator.imul)

        # Output the result
        if op is None:
            outdata[:] = faded
        else:
            op(outdata, faded)

            
    def fadein(self, samples, outdata, op=None):
        self._fade(samples, outdata, op,
                   from_=0, to_=1)

        
    def fadeout(self, samples, outdata, op=None):
        self._fade(samples, outdata, op,
                   from_=1, to_=0)


        
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
        MEASURE_SILENCE = 10
        FADEIN_TONE0 = 20
        DETECT_TONE0 = 30
        MEASURE_TONE0 = 40
        DETECT_TONE1 = 50
        MEASURE_TONE0_TONE1 = 60
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

            # Specifiy the minimum number of samples
            self.min_num_samples = 50

            # Variables for the measurement of levels of silence
            self.silence_threshold_duration = 0.5 # seconds
            self.silence_levels = []
            self.silence_start_time = None
            self.silence_mean = None
            self.silence_sd = None
            self.silence_mean_threshold = 1e-6
            self.silence_sd_threshold = 1e-6
            self.silence_max_time_in_state = 5 # seconds

            # Variables for tones
            self.tone_duration = 1 # second
            n_tones = len(self.fft_analyser.freqs)
            self.tones = [Tone(freq,
                               self.tone_duration,
                               self.samples_per_second,
                               output_channels,
                               1/n_tones)
                          for freq in self.fft_analyser.freqs]

            # Variables for non-silence
            self.non_silence_threshold_num_sd = 4 # number of std. deviations away from silence
            self.non_silence_threshold_duration = 0.5 # seconds of non-silence
            self.non_silence_start_time = None
            self.non_silence_detected = False
            self.non_silence_abort_start_time = None
            self.non_silence_max_time_in_state = 5 # seconds

            # Variables for measurement of tone0 and not-tone1
            self.tone0_levels = []
            self.tone0_start_time = None
            self.tone0_threshold_duration = 0.5 # seconds of tone0 and not tone1
            self.tone0_mean = None
            self.tone0_sd = None

            # Variables for detection of tone1
            self.detect_tone1_threshold_num_sd = 4 # number of std. deviations away from not-tone1
            self.detect_tone1_threshold_duration = 0.5 # seconds of not-not-tone1
            self.detect_tone1_start_time = None
            self.detect_tone1_detected = False
            self.detect_tone1_max_time_in_state = 5 # seconds

            # Variables for measurement of tone0 and tone1
            self.tone0_tone1_levels = []
            self.tone0_tone1_start_time = None
            self.tone0_tone1_threshold_duration = 0.5 # seconds of tone0 and tone1
            self.tone0_tone1_mean = None
            self.tone0_tone1_sd = None

            # To overcome what seems to be a bug in either sounddevice
            # or portaudio, we need to write a complete frame of zeros
            # in order to avoid a click when the stream closes.  See
            # https://github.com/spatialaudio/python-sounddevice/issues/249
            self.zero_frames_count = 0
            
    # Create an instance of the shared variables
    v = SharedVariables(samples_per_second)
    
    # Callback for when the recording buffer is ready.  The size of the
    # buffer depends on the latency requested.
    def callback(indata, outdata, samples, time, status):
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

        previous_state = v.process_state

        if v.process_state == ProcessState.RESET:
            v.process_state = ProcessState.MEASURE_SILENCE
                        
        elif v.process_state == ProcessState.MEASURE_SILENCE:
            if v.silence_mean is not None and \
               v.silence_sd is not None:
                if any(v.silence_mean < v.silence_mean_threshold):
                    print("Implausibly low mean level detected for silence; aborting.")
                    v.process_state = ProcessState.ABORTED
                elif any(v.silence_sd < v.silence_sd_threshold):
                    print("Implausibly low standard deviation detected for silence; aborting.")
                    v.process_state = ProcessState.ABORTED
                else:
                    # No reason not to continue
                    v.process_state = ProcessState.FADEIN_TONE0
                    v.non_silence_abort_start_time = time.currentTime
                    print("About to play tone.  Please increase system volume until the tone is detected.")
                    
            if time.currentTime - v.state_start_time > v.silence_max_time_in_state:
                print("ERROR: We've spent too long listening to silence.  Aborting.")
                v.process_state = ProcessState.ABORTED

                
        elif v.process_state == ProcessState.FADEIN_TONE0:
            v.process_state = ProcessState.DETECT_TONE0    

            
        elif v.process_state == ProcessState.DETECT_TONE0:
            if v.non_silence_detected:
                v.process_state = ProcessState.MEASURE_TONE0
                print("Base tone detected.  Please do not adjust system volume nor position of microphone or speakers")

            if time.currentTime - v.state_start_time > v.non_silence_max_time_in_state:
                print("ERROR: We've spent too long listening for non-silence.  Aborting.")
                v.process_state = ProcessState.ABORTED


        elif v.process_state == ProcessState.MEASURE_TONE0:
            if v.tone0_mean is not None and \
               v.tone0_sd is not None:
                v.process_state = ProcessState.DETECT_TONE1

                
        elif v.process_state == ProcessState.DETECT_TONE1:
            if v.detect_tone1_detected:
                v.process_state = ProcessState.MEASURE_TONE0_TONE1

            if time.currentTime - v.state_start_time > v.detect_tone1_max_time_in_state:
                print("ERROR: We've spent too long listening for tone #1.  Aborting.")
                v.process_state = ProcessState.ABORTED
                

        elif v.process_state == ProcessState.MEASURE_TONE0_TONE1:
            if v.tone0_tone1_mean is not None and \
               v.tone0_tone1_sd is not None:
                v.process_state = ProcessState.COMPLETING

                
        elif v.process_state == ProcessState.COMPLETING:
            v.process_state = ProcessState.COMPLETED

            
        elif v.process_state == ProcessState.COMPLETED:
            pass
        

        # Set state start time
        if previous_state != v.process_state:
            v.state_start_time = time.currentTime
        
        
        # States
        # ======

        if v.process_state == ProcessState.RESET:
            pass
            
        elif v.process_state == ProcessState.MEASURE_SILENCE:
            # Check if the sample is acceptable:
            if tones_level is not None and all(tones_level > 0):
                # Levels are acceptable

                # If we haven't started timing, do so now
                if v.silence_start_time is None:
                    v.silence_start_time = time.inputBufferAdcTime

                # Check if we've listened to enough silence
                duration = time.currentTime - v.silence_start_time
                if duration <= v.silence_threshold_duration:
                    # Record this level
                    v.silence_levels.append(tones_level)
                elif len(v.silence_levels) < v.min_num_samples:
                    print("Insufficient samples of silence observed; listening for another half-second")
                    v.silence_threshold_duration += 0.5 # seconds
                else:
                    # We've now collected enough sample levels;
                    # calculate the mean and standard deviation of the
                    # samples taken.
                    v.silence_mean = numpy.mean(v.silence_levels, axis=0)
                    v.silence_sd = numpy.std(v.silence_levels, axis=0)
                    print("silence_mean:",v.silence_mean)
                    print("silence_sd:", v.silence_sd)
                    print("sample size of silence:", len(v.silence_levels))


                
        elif v.process_state == ProcessState.FADEIN_TONE0:
            print("Fading in tone #0")
            v.tones[0].fadein(samples, outdata)
            
            
        elif v.process_state == ProcessState.DETECT_TONE0:
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
                if len(v.tone0_levels) >= v.min_num_samples:
                    # We've now collected enough samples
                    v.tone0_mean = numpy.mean(v.tone0_levels, axis=0)
                    v.tone0_sd = numpy.std(v.tone0_levels, axis=0)
                    print("tone0_mean:",v.tone0_mean)
                    print("tone0_sd:", v.tone0_sd)
                    print("tone0 number of samples:", len(v.tone0_levels))
                else:
                    print("We haven't collected sufficient samples; increasing sampling time by half a second")
                    v.tone0_threshold_duration += 0.5

                        
        elif v.process_state == ProcessState.DETECT_TONE1:
            # Play tones
            v.tones[0].play(samples, outdata)
            v.tones[1].play(samples, outdata, op=operator.iadd)

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
            # Play tones
            v.tones[0].play(samples, outdata)
            v.tones[1].play(samples, outdata, op=operator.iadd)

            # Start the timer if not started
            if v.tone0_tone1_start_time is None:
                v.tone0_tone1_start_time = time.currentTime

            # TODO: Should we check that we've got not-not-tone1?
                
            # Save the levels because we assume we're hearing tone #1
            v.tone0_tone1_levels.append(tones_level)

            duration = time.currentTime - v.tone0_tone1_start_time
            if duration > v.tone0_tone1_threshold_duration:
                if len(v.tone0_tone1_levels) >= v.min_num_samples:
                    # We've now collected enough samples
                    v.tone0_tone1_mean = numpy.mean(v.tone0_tone1_levels, axis=0)
                    v.tone0_tone1_sd = numpy.std(v.tone0_tone1_levels, axis=0)
                    print("tone0_tone1_mean:",v.tone0_tone1_mean)
                    print("tone0_tone1_sd:", v.tone0_tone1_sd)
                    print("tone0_tone1 number of samples:", len(v.tone0_tone1_levels))
                else:
                    print("We haven't collected sufficient samples; increasing sampling time by half a second")
                    v.tone0_tone1_threshold_duration += 0.5

                
        elif v.process_state == ProcessState.COMPLETING:
            outdata[:] = numpy.zeros(outdata.shape)
            print("Fading out tone #0")
            v.tones[0].fadeout(samples, outdata, op=operator.iadd)
            print("Fading out tone #1")
            v.tones[1].fadeout(samples, outdata, op=operator.iadd)                

            
        elif v.process_state == ProcessState.COMPLETED:
            outdata[:] = [[0,0]] * samples
            v.zero_frames_count += 1
            if v.zero_frames_count > 1:
                print("Completed measuring levels")
                raise sd.CallbackStop

        
        elif v.process_state == ProcessState.ABORTED:
            v.zero_frames_count += 1
            if v.zero_frames_count > 1:
                print("Aborting measuring levels")
                print(sd.query_devices())
                raise sd.CallbackStop

            
        # DEBUG
        # Save outdata for analysis
        v.out_pcm[v.out_pcm_pos:v.out_pcm_pos+samples] = outdata[:]
        v.out_pcm_pos += samples
        if v.out_pcm_pos > len(v.out_pcm):
            print("ERROR: Buffer for PCM of output is full; aborting")
            raise sd.CallbackAbort
            

        
    # Open a read-write stream
    stream = sd.Stream(samplerate=samples_per_second,
                       channels=channels,
                       dtype=numpy.float32,
                       latency=desired_latency,
                       callback=callback,
                       finished_callback=v.event.set)


    print("Measuring levels...")
    with stream:
        v.event.wait()  # Wait until measurement is finished

    # Save out pcm for analysis
    wave_file = wave.open("out.wav", "wb")
    wave_file.setnchannels(channels[1])
    wave_file.setsampwidth(2)
    wave_file.setframerate(samples_per_second)
    data = v.out_pcm[0:v.out_pcm_pos]
    data = data * 2**15-1
    data = data.astype(numpy.int16)
    wave_file.writeframes(data)
    wave_file.close()
        
    # Done!
    print("Finished measuring levels.")

    return {
        "tone0_mean": v.tone0_mean,
        "tone0_sd": v.tone0_sd,
        "tone0_tone1_mean": v.tone0_tone1_mean,
        "tone0_tone1_sd": v.tone0_tone1_sd
    }


if __name__ == "__main__":
    print("")
    print("Measuring Levels")
    print("================")
    print("")
    print("We are now going to measure the levels heard by your microphone when we play some tones.")
    print("These levels will be used later, when measuring the latency in your system.")
    print("")
    print("You will need to adjust the position of the microphone and output device.  For this")
    print("measurement, the microphone needs to be able to hear the output.  So, for example, if")
    print("you have headphones with an inline microphone, place the microphone over one of the")
    print("ear pieces.")
    print("")
    print("The process takes a few seconds.  It will first record the background noise, then it will")
    print("play a couple of tones.  You will need to ensure the volume is sufficiently high so that")
    print("the microphone can reliably hear the output.")
    print("")
    print("Do not move the microphone or output device once the system can hear the constant tone.")
    print("Do not make any noise during this measurement.")
    print("")
    print("Press enter to start.")
    print("")

    input() # wait for enter key

    levels = measure_levels(desired_latency="high")
    print(levels)
