# Load a song, play it back while simultaneously recording.
# Recorded sound is saved as WAV.

# FIXME: Appears to work only when the headset is plugged in.

import pdb
import pyogg
from pyogg import opus
import numpy
import ctypes
from datetime import datetime
import sounddevice as sd
import time # sleep





#filename = "ff-16b-2c-44100hz.opus"
#filename = "gs-16b-2c-44100hz.opus"
#filename = "gs-16b-1c-44100hz.opus"
filename = "left-right-demo-5s.opus"

print("Reading Opus file...")
opus_file = pyogg.OpusFile(filename)

print("\nRead Opus file")
print("Channels:"+str(opus_file.channels))
print("Frequency:"+str(opus_file.frequency))
print("Buffer Length: "+str(opus_file.buffer_length))


# Create NumPy array from buffer
bytes_per_sample = ctypes.sizeof(opus_file.buffer.contents)
buffer = numpy.ctypeslib.as_array(
    opus_file.buffer,
    (opus_file.buffer_length//
     bytes_per_sample//
     opus_file.channels,
     opus_file.channels)
)


# Convert buffer to floating point between -1 and +1
max_abs_short = 32768
buffer = buffer.astype(numpy.float32) / max_abs_short


# Calculate maximum absolute volume of a buffer
def get_max_abs_volume(buffer):
    max_volume = numpy.amax(buffer)
    min_volume = numpy.amin(buffer)

    max_abs_volume = max(max_volume,
                         -min_volume)

    return max_abs_volume


# Rescale to a maximum volume as a proportion of full scale
def rescale(buffer, desired_max=0.5):
    max_abs_vol = get_max_abs_volume(buffer)

    result = (buffer.astype(numpy.float32)
              / max_abs_vol
              * desired_max)

    return result

    
    
# Re-scale audio to at most 50% of full scale (-6dBFS)
print("\nRescaling audio to 50% of full scale...")
buffer = rescale(buffer, 0.5)


# Detect the maximum volume of the microphone during example usage
maxAbsInput = 0
def detectMax(indata, frames, time, status):
    """This is called (from a separate thread) for each audio block."""
    global maxAbsInput
    
    if status:
        print(status, file=sys.stderr)

    maxAbsFrame = get_max_abs_volume(indata)
    
    if maxAbsFrame > maxAbsInput:
        print("Peak detected at",
              round(100 * maxAbsFrame, 1),"% of input's full scale")
        maxAbsInput = maxAbsFrame



# Measure the expected maximum volume of microphone's input
duration = 2 # seconds
print("\nPlease use the microphone at the loudest level you expect.")
print("You have", duration, "seconds...")
with sd.InputStream(callback=detectMax, dtype=numpy.float32):
    sd.sleep(int(duration * 1000))

    
# Index into audio buffer so that we know what we're playing next
bufferIndex = 0


# Callback for when the recording buffer is ready.  The size of the
# buffer depends on the latency requested.
def callback(indata, outdata, samples, time, status):
    global bufferIndex
    
    if status:
        print(status)

    # Scale input to be at 50% of anticipated full scale
    indata = (indata.astype(numpy.float32)
              / maxAbsInput
              * 0.5)
            
    # Mix the input and audio together by simply adding the two
    # signals.  They should not combine to more than 100% of full
    # scale given they were both set to 50% each.  Send the result to
    # the output.
    if bufferIndex+len(indata) <= len(buffer):
        outdata[:] = indata + buffer[bufferIndex : bufferIndex+len(indata)]
        bufferIndex += len(indata)
    else:
        audio = (buffer[bufferIndex : len(buffer)]
                 + [0.0, 0.0] * (bufferIndex+len(indata) - len(buffer)))
        outdata[:] = indata + audio
        bufferIndex = len(buffer)

    if bufferIndex == len(buffer):
        raise sd.CallbackStop

                 


# Open a read-write stream
duration = 10 # seconds
with sd.Stream(channels=2,
               dtype=numpy.float32,
               latency="low",
               callback=callback):
    sd.sleep(int(duration * 1000))


# Done!
print("Finished.")
