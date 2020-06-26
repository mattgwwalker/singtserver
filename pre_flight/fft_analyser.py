import numpy

# Fast Fourier Transform for recorded samples, specifically focused on
# certain frequencies.
class FFTAnalyser:
    def __init__(self, samples_per_second):
        # Number of samples for FFT analysis.  256 samples is
        # approximately 5ms at 48kHz.
        self._n = 256

        self._samples_per_second = samples_per_second

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


    @property
    def window_width(self):
        """The width of the FFT window in seconds."""
        return self._n / self._samples_per_second
    

    def run(self, rec_pcm, rec_position):
        # If we have more than the required number of samples
        # recorded, execute FFT analysis
        if rec_position >= self._n:
            # If we've got stereo data, average together the two
            # channels
            channels = rec_pcm.shape[1]
            if channels == 2:
                left = rec_pcm[rec_position-self._n:rec_position, 0]
                right = rec_pcm[rec_position-self._n:rec_position, 1]
                mono = (left+right) / 2
            elif channels == 1:
                mono = rec_pcm[rec_position-self._n:rec_position, 0]
            else:
                raise Exception(
                    "Attempted to analyse data with an unsupported "+
                    "number of channels ({:d})".format(channels)
                )

            y = numpy.fft.rfft(
                # Use of Hann window to reduce spectral leakage (see
                # https://stackoverflow.com/questions/8573702/units-of-frequency-when-using-fft-in-numpy)
                # I'm not sure this is really necessary.
                mono * numpy.hanning(len(mono)), 
                n=self._n
            )
            y = numpy.abs(y)

            return y[self._freq_indices]
        
        else:
            # We don't have enough samples to analyse
            return None
    

        
if __name__ == "__main__":
    from tone import Tone
    
    samples_per_second = 48000
    fft_analyser = FFTAnalyser(samples_per_second)

    # Create a buffer to hold a sample
    samples = int(
        fft_analyser.window_width
        * samples_per_second
    )
    channels = 1
    buf = numpy.zeros((samples, channels), numpy.float32)

    # Populate the buffer with a tone 
    frequency = 375 # Hz
    tone = Tone(frequency, channels=channels)
    tone.play()
    tone.output(buf)

    # Analyse the buffer
    result = fft_analyser.run(buf, len(buf))

    print("Levels at analysed frequencies:")
    print(numpy.around(result,1))
