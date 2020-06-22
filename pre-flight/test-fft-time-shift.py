import wave
import numpy
import time

filename_original = "out1.wav"
filename_delayed = "in1.wav"

def read_wave(filename):
    print("Reading",filename)
    
    # Read file to get buffer
    ifile = wave.open(filename)
    samples = ifile.getnframes()
    channels = ifile.getnchannels()
    audio = ifile.readframes(samples)

    # Convert buffer to float32 using NumPy
    audio_as_np_int16 = numpy.frombuffer(audio, dtype=numpy.int16)
    audio_as_np_float32 = audio_as_np_int16.astype(numpy.float32)

    # Normalise float32 array so that values are between -1.0 and +1.0
    max_int16 = 2**15
    audio_normalised = audio_as_np_float32 / max_int16

    # Reshape the array for the number of channels
    audio_reshaped = numpy.reshape(
        audio_normalised,
        (len(audio_normalised)//channels,
         channels)
    )

    return audio_reshaped


def make_mono(audio):
    if audio.shape[1] == 1:
        # It's already mono
        return audio
    
    left = audio[:,0]
    right = audio[:,1]
    mono = (left+right)/2
    
    return numpy.reshape(mono, (len(mono),1))

original = read_wave(filename_original)
original = make_mono(original)
delayed = read_wave(filename_delayed)
delayed = make_mono(delayed)



print("number of samples (original):", len(original))
print("number of samples (delayed):", len(delayed))

from scipy import signal, fftpack

print("Calculating correlation")
start_time = time.time()
cor = signal.correlate(original, delayed)
end_time = time.time()
print("duration", end_time - start_time)

correction = len(delayed) - numpy.argmax(cor)
print("correction:", correction)

samples_per_second = 48000
print("time offset (s):", correction/samples_per_second)

if True:
    import matplotlib.pyplot as plt
    fig=plt.figure()
    ax=fig.add_subplot()
    ax.scatter(range(len(cor)), cor)
    plt.show()
