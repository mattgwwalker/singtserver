import numpy as np
import simpleaudio as sa
import wave


# calculate note frequencies
A_freq = 440
Csh_freq = A_freq * 2 ** (4 / 12)
E_freq = A_freq * 2 ** (7 / 12)

# get timesteps for each sample, T is note duration in seconds
sample_rate = 48000
T = 0.25
t = np.linspace(0, T, int(T * sample_rate), False)

# generate sine wave notes
A_note = np.sin(A_freq * t * 2 * np.pi)
Csh_note = np.sin(Csh_freq * t * 2 * np.pi)
E_note = np.sin(E_freq * t * 2 * np.pi)

# concatenate notes
audio = np.hstack((A_note, Csh_note, E_note))
# normalize to 16-bit range
audio *= 32767 / np.max(np.abs(audio))
# convert to 16-bit data
audio = audio.astype(np.int16)

# start playback
play_obj = sa.play_buffer(audio, 1, 2, sample_rate)

# wait for playback to finish before exiting
play_obj.wait_done()

# save as wave file
wave_write = wave.open('sound.wav','wb')
wave_write.setnchannels(1) # mono
wave_write.setsampwidth(2) # bytes
wave_write.setframerate(sample_rate) # hertz
wave_write.writeframes(audio)
wave_write.close()
