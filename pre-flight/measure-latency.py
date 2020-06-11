# Check that audio can be played... at all.
import pyogg
import time
import sounddevice as sd
import numpy

# Phase One
# =========
# Measure latency approximately via tones.
def phase_one(desired_latency="low", samples_per_second=48000, channels=(2,2)):
    """Channels are specified as a tuple of (input channels, output channels)."""
    input_channels, output_channels = channels

    # Generate the tones required.  Assumes no blocksize will be
    # greater than one second.  Frequencies chosen from mid-points of
    # FFT analysis.
    fft_n = 256 # Approximately 5ms at 48kHz
    fft_freqs = numpy.fft.rfftfreq(fft_n) * samples_per_second
    freqs = [375, 1125, 2250]

    # Get index of desired frequencies
    freq_indices = []
    for freq in freqs:
        indices = numpy.where(fft_freqs == freq)
        assert len(indices) == 1
        freq_indices.append(indices[0][0])

    duration = 1.0 # seconds
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


    # Initialise the current position for each tone
    tone_positions = [0] * len(tones)


    # Allocate space for recording
    max_recording_duration = 10 #seconds
    max_recording_samples = max_recording_duration * samples_per_second
    rec_pcm = numpy.zeros((
        max_recording_samples,
        input_channels
    ))

    # Initialise recording position
    rec_position = 0
        
    
    # Callback for when the recording buffer is ready.  The size of the
    # buffer depends on the latency requested.
    def callback(indata, outdata, samples, time, status):
        nonlocal rec_position, tone_positions

        if status:
            print(status)

        # Play the tone
        if tone_positions[0]+samples <= len(tones[0]):
            # Copy tone in one hit
            outdata[:] = tones[0][tone_positions[0]:tone_positions[0]+samples]
            tone_positions[0] += samples
        else:
            # Need to loop back to the beginning of the tone
            remaining = len(tones[0])-tone_positions[0]
            outdata[:remaining] = (
                tones[0][tone_positions[0]:len(tones[0])]
            )
            outdata[remaining:] = (
                tones[0][:samples-remaining]
            )
            tone_positions[0] = samples-remaining

            
        # Store the recording
        rec_pcm[rec_position:rec_position+samples] = indata[:]
        rec_position += samples

        # If we have more than the required number of samples
        # recorded, execute FFT analysis
        fft_n = 256 # about 5ms at 48kHz
        if rec_position > fft_n:
            data = rec_pcm[rec_position-256:rec_position]
            data_transpose = data.transpose()
            left = data_transpose[0]
            right = data_transpose[1]
            mono = left+right
                        
            sp = numpy.fft.rfft(
                mono,
                n=fft_n
            )
            sp = numpy.abs(sp)
            db = 20*numpy.log10(sp / sp.max())

            dbs = []
            for freq_index in freq_indices:
                y = db[freq_index]
                dbs.append(y)

            mean = numpy.mean(db)
            decision = dbs[0] - 30 > mean
            print(decision, numpy.mean(db), dbs)
            #raise sd.CallbackAbort

            
            
            
        # Detect the tone
        

            
    # Play first tone
    # Open a read-write stream
    stream = sd.Stream(samplerate=48000,
                       channels=2,
                       dtype=numpy.float32,
                       latency="low",
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
    
    approximate_latency = phase_one()
    accurate_latency = phase_two(approximate_latency)
    
    

if __name__ == "__main__":
    measure_latency()
