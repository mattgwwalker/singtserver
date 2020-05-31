# Connects to microphone input stream, 
# then encodes using Opus, decodes using Opus
# and plays the result

import pyogg
from pyogg import opus
import numpy
import ctypes
from datetime import datetime
import sounddevice as sd
import time # sleep

# Display the version of the Opus library
version = opus.opus_get_version_string()
print("Opus library version: "+
      str(version.decode('utf-8')))


sampleSize = 512 # FIXME: need to get this from portaudio
channels = 2 # FIXME:Record in mono

# Create two input buffers
inBufs = numpy.zeros((2, sampleSize, channels))
activeBuffer = 0
bufferIndex = [0,0]
frameSize = 512

# Create a delay buffer for testing
outBuf = numpy.zeros((48000*2,channels))
outBufProduceIndex = 5000


def callback(indata, outdata, samples, time, status):
    global inBufs, activeBuffer, bufferIndex, frameSize, sampleSize, outBuf, outBufProduceIndex

    # FIXME: What does this do?
    if status:
        print(status)

    # For telephony, we want to take the input, encode it, and send
    # it.

    # The input is in indata, but at 512 samples, that's not one of
    # the options in Opus.  So we will have to process what we can,
    # probably with a frame size of 480 (10ms).  This will leave us
    # with 32 samples left over the first time.

    # Set the non-active buffer
    nonActiveBuffer = (activeBuffer+1)%2
    
    # Ensure there are sufficient samples in the active buffer for
    # Opus to encode a frame.
    samplesToCopy = frameSize - bufferIndex[activeBuffer]
    #print("samplesToCopy:", samplesToCopy)
    inBufs[activeBuffer][bufferIndex[activeBuffer]:frameSize] = \
        indata[0:samplesToCopy]

    # Copy the remaining samples to the other buffer
    remainingSamples = sampleSize - frameSize
    if remainingSamples > 0:
        inBufs[nonActiveBuffer][0:remainingSamples] = \
            indata[samplesToCopy:sampleSize]

    # FIXME: Encode the active buffer

    # TEST
    # Copy the prepared active buffer to the delayed buffer
    outBuf[outBufProduceIndex:outBufProduceIndex+frameSize] = \
        inBufs[activeBuffer][0:frameSize]

    # Copy the delayed buffer to the output
    outdata[0:frameSize] = outBuf[0:frameSize]

    # Roll the delayed buffer
    outBuf = numpy.roll(outBuf, -frameSize)

    # MORE SIMPLE TEST
    # Copy the active buffer to the output
    #outdata[0:frameSize] = inBufs[activeBuffer][0:frameSize]
    
    # Set the active buffer's index back to zero as it has been
    # consumed.
    bufferIndex[activeBuffer] = 0
    
    # Swap active buffers
    activeBuffer = nonActiveBuffer


    

    # FIXME: For monitoring we want to copy the data to the speakers
    # (outdata), but we'll also want to mix that with the backing
    # track.  For telephony, we don't need monitoring
    #outdata[:] = indata


# Open a read-write stream
duration = 30 # seconds
with sd.Stream(channels=2, callback=callback):
    sd.sleep(int(duration * 1000))


# Done!
print("Finished.")
