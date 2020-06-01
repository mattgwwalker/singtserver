# Connects to microphone input stream, 
# then encodes using Opus, decodes using Opus
# and plays the result

# FIXME: Appears to work only when the headset is plugged in.

import pdb
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


recFrameSize = 64 # FIXME: need to get this from portaudio
channels = 2 # FIXME:Record in mono
opusFrameSize = 32
freq = 48000 # Samples per second

# Create a circular input buffer.  The worst case is that we've got
# opusFrameSize + recFrameSize data stored in the buffer because we
# haven't yet processed the Opus frame and we've received the
# recording frame.
maxInBufSize = opusFrameSize+recFrameSize
inBuf = numpy.zeros((maxInBufSize, channels),
                    dtype=numpy.int16)
inBufProduceIndex = 0


# Create a delayed output buffer for testing.  At worst, it will need
# to store the delay plus an output frame (which is the same size as
# the recording frame).
delayDuration = 1 # seconds
maxOutBufSize = freq*delayDuration+recFrameSize
outBuf = numpy.zeros((maxOutBufSize,channels),
                     dtype=numpy.int16)
outBufProduceIndex = delayDuration*freq


# Callback for when the recording buffer is ready.  The size of the
# buffer depends on the latency.
def callback(indata, outdata, samples, time, status):
    global inBuf, inBufProduceIndex
    global outBuf, outBufProduceIndex


    # The number of samples should never change
    if samples != recFrameSize:
        print("samples:",samples," != ","recFrameSize:",recFrameSize)
        raise Exception("We should not get here")
    
    def pb(b):
        for i in range(b.shape[0]):
            print(i,":",b[i])

    #pdb.set_trace()
    
    # FIXME: What does this do?
    if status:
        print(status)

    # For telephony, we want to take the input, encode it, and send
    # it.

    # The input is in indata, but at 512 samples, that's not one of
    # the options in Opus.  So we will have to process what we can,
    # probably with a frame size of 480 (10ms).  This will leave us
    # with 32 samples left over the first time.

    
    # Copy all the incoming data into the input buffer
    inBuf[inBufProduceIndex:inBufProduceIndex+recFrameSize] = \
        indata[0:recFrameSize]

    #print(inBuf)


    # Update the index into the input buffer
    inBufProduceIndex += recFrameSize


    # Consume as many frames from the input buffer as possible.  (For
    # this demonstration, copy them to the output buffer.)
    while inBufProduceIndex >= opusFrameSize:
        # Copy the input data to the output buffer
        outBuf[outBufProduceIndex:outBufProduceIndex+opusFrameSize] = \
            inBuf[0:opusFrameSize]

        # Adjust the output buffer index
        outBufProduceIndex += opusFrameSize
        
        # Roll the input buffer
        inBuf = numpy.roll(inBuf, -opusFrameSize, axis=0)
        
        # Adjust the input buffer index
        inBufProduceIndex -= opusFrameSize
        assert inBufProduceIndex >= 0
        
    #print(outBuf)
        

    # Copy the output buffer to the output
    outdata[0:recFrameSize] = outBuf[0:recFrameSize]


    # Roll the output buffer
    outBuf = numpy.roll(outBuf, -recFrameSize, axis=0)

    
    # Adjust the output buffer index
    outBufProduceIndex -= recFrameSize
    assert outBufProduceIndex >= 0


# Open a read-write stream
duration = 6000 # seconds
with sd.Stream(channels=2,
               dtype=numpy.int16,
               latency="low",
               callback=callback):
    sd.sleep(int(duration * 1000))


# Done!
print("Finished.")
