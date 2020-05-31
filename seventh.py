# Reads OggOpus file, extracts PCM
# then encodes using Opus, decodes using Opus
# and plays the result

# This is just a cleaned-up version of sixth-b.py

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


# Specify the file containing Opus audio
#filename = "ff-16b-2c-44100hz.opus"
#filename = "gs-16b-1c-44100hz.opus"
#filename = "gs-16b-2c-44100hz.opus"
filename = "left-right-demo-5s.opus"
#filename = "humm-120samples.opus"

# Read the Opus file and place the PCM in a memory buffer
print("Reading Opus file...")
opusFile = pyogg.OpusFile(filename)


# Display information about the file
print("\nRead Opus file")
print("Channels:"+str(opusFile.channels))
print("Frequency:"+str(opusFile.frequency))
print("Buffer Length (bytes): "+str(opusFile.buffer_length))


# The buffer holds the entire song in memory, however the shape of the
# array isn't obvious.  Note that the above buffer length is in bytes,
# but the PCM values are stored in two-byte ints (shorts).
bytesPerSample = ctypes.sizeof(opusFile.buffer.contents)
samplesPerChannel = \
    opusFile.buffer_length// \
    bytesPerSample// \
    opusFile.channels
buf = numpy.ctypeslib.as_array(opusFile.buffer,
                               (samplesPerChannel,
                                opusFile.channels,))


# The shape of the NumPy buffer is now measured in units of (number of
# samples, number of channels)
print("Buffer Shape (number of samples, number of channels):", buf.shape)


# The duration, in seconds, can now be found by dividing the number of
# samples by the frequency
bufferDuration = buf.shape[0]/opusFile.frequency
print("Duration of buffer (seconds): ",
      bufferDuration)


# Function to play Numpy PCM buffers
def playNumpyBuffer(npBuf, freq=48000):
    print("Playing...")
    startTime = datetime.now()
    sd.play(npBuf, freq)
    sd.wait()  # Wait until sound has finished playing
    endTime = datetime.now()
    print("Duration: "+str(endTime - startTime))
    

# Play our newly-loaded audio, if desired
if False:
    playNumpyBuffer(buf)


# Print the buffer to learn what the PCM looks like
with numpy.printoptions(threshold=numpy.inf):
    print("Example of decoded PCM:\n", buf[0:10])


# Create a second buffer to store the re-decoded version.  Given our
# source file was in the Opus format, our re-decoding should have an
# identical number of samples.
print("\nCreating Second Buffer...")
buf2StorageType = (opus.opus_int16*opusFile.channels) * samplesPerChannel
buf2Storage = buf2StorageType()


# A pointer to the buffer storage is required, otherwise NumPy seems
# to get confused with the shape of the array
buf2StoragePtr = ctypes.cast(ctypes.pointer(buf2Storage),
                             ctypes.POINTER(opus.opus_int16))


# Create a numpy array using this newly created buffer
buf2 = numpy.ctypeslib.as_array(buf2StoragePtr,
                                buf.shape)
print("Shape of Second Buffer: ", buf2.shape)


# Create an encoder
def createEncoder(npBufSource, freq):
    # To create an encoder, we must first allocate resources for it.
    # We want Python to be responsible for the memory deallocation,
    # and thus Python must be responsible for the initial memory
    # allocation.

    # Opus can encode both speech and music, and it can automatically
    # detect when the source swaps between the two.  Here we specify
    # automatic detection.
    application = opus.OPUS_APPLICATION_AUDIO

    # The frequency must be passed in as a 32-bit int
    freq = opus.opus_int32(freq)

    # The number of channels can be obtained from the shape of the
    # NumPy array that was passed in as npBufSource
    channels = npBufSource.shape[1]

    # Obtain the number of bytes of memory required for the encoder
    size = opus.opus_encoder_get_size(channels);

    # Allocate the required memory for the encoder
    memory = ctypes.create_string_buffer(size)

    # Cast the newly-allocated memory as a pointer to an encoder.  We
    # could also have used opus.oe_p as the pointer type, but writing
    # it out in full may be clearer.
    encoder = ctypes.cast(memory, ctypes.POINTER(opus.OpusEncoder))

    # Initialise the encoder
    error = opus.opus_encoder_init(encoder, freq, channels, application);

    # Check that there hasn't been an error when initialising the
    # encoder
    if error != opus.OPUS_OK:
        raise Exception("An error occurred while creating the encoder: "+
                        opus.opus_strerror(error).decode("utf"))

    # Return our newly-created encoder
    return encoder


def createDecoder(freq, channels):
    # Just as with the encoder, to create a decoder, we must first
    # allocate resources for it.  We want Python to be responsible for
    # the memory deallocation, and thus Python must be responsible for
    # the initial memory allocation.

    # The frequency must be passed in as a 32-bit int
    freq = opus.opus_int32(freq)

    # The number of channels must also be passed in as a 32-bit int
    channels = opus.opus_int32(channels)
    
    # Obtain the number of bytes of memory required for the decoder
    size = opus.opus_decoder_get_size(channels);

    # Allocate the required memory for the decoder
    memory = ctypes.create_string_buffer(size)

    # Cast the newly-allocated memory as a pointer to a decoder.  We
    # could also have used opus.od_p as the pointer type, but writing
    # it out in full may be clearer.
    decoder = ctypes.cast(memory, ctypes.POINTER(opus.OpusDecoder))

    # Initialise the decoder
    error = opus.opus_decoder_init(decoder, freq, channels);

    # Check that there hasn't been an error when initialising the
    # decoder
    if error != opus.OPUS_OK:
        raise Exception("An error occurred while creating the decoder: "+
                        opus.opus_strerror(error).decode("utf"))

    # Return our newly-created decoder
    return decoder
    


# Function to encode and then immediately re-decode using Opus
def encodeThenDecode(npBufSource, npBufTarget, freq):
    # Encoding
    # ========

    # Extract the number of channels in the source
    sourceChannels = npBufSource.shape[1]

    
    # Create an encoder
    encoder = createEncoder(npBufSource, freq)

    
    # Frame sizes are measured in number of samples.  There are only a
    # specified number of possible valid frame durations for Opus,
    # which (assuming a frequency of 48kHz) gives the following valid
    # sizes.
    frameSizes = [120, 240, 480, 960, 1920, 2880]

    
    # Specify the desired frame size.  This will be used for the vast
    # majority of the encoding, except possibly at the end of the
    # buffer (as there may not be sufficient data left to fill a
    # frame.)
    frameSize = frameSizes[5]


    # Function to calculate the size of a frame in bytes
    def frameSizeBytes(frameSize):
        global bytesPerSample
        return frameSize * sourceChannels * bytesPerSample

    
    # Allocate storage space for the encoded frame.  4,000 bytes is
    # the recommended maximum buffer size for the encoded frame.
    maxEncodedFrameBytes = opus.opus_int32(4000)
    encodedFrameType = ctypes.c_ubyte * maxEncodedFrameBytes.value
    encodedFrame = encodedFrameType()


    # Create a pointer to the first byte of the buffer for the encoded
    # frame.
    encodedFramePtr = ctypes.cast(ctypes.pointer(encodedFrame),
                                  ctypes.POINTER(ctypes.c_ubyte))

    
    # Number of bytes to process in buffer
    bytesPerSample = 2
    lengthBytes = buf.shape[0] * buf.shape[1] * bytesPerSample

    
    # Decoding
    # ========

    # Extract the number of channels for the target
    targetChannels = npBufTarget.shape[1]


    # Create a decoder
    decoderFreq = 48000 # TODO: Test changes to this
    decoderPtr = createDecoder(decoderFreq,
                               targetChannels)
                                       
    
    
    # Encode and re-decode the audio
    # ==============================

    # Pointer to a location in the source buffer.  We will increment
    # this as we progress through the encoding of the buffer.  It
    # starts pointing to the first byte.
    sourcePtr = npBufSource.ctypes.data_as(ctypes.c_void_p)
    sourcePtr_init = sourcePtr


    # The number of bytes processed will be the difference between the
    # pointer's current location and the address of the first byte.
    bytesProcessed = sourcePtr.value - sourcePtr_init.value


    # Pointer to a location in the target buffer.  We will increment
    # this as we progress through re-decoding each encoded frame.
    targetPtr = npBufTarget.ctypes.data_as(ctypes.c_void_p)
    

    # Loop through the source buffer
    count = 0 # FIXME: debugging only 
    while bytesProcessed < lengthBytes:
        print("processing frame: ",count)
        count += 1
        print("Processing frame at sourcePtr ", sourcePtr.value)

    
        # Check if we have enough source data remaining to process at
        # the current frame size
        print("lengthBytes: ",lengthBytes)
        print("bytesProcessed: ",bytesProcessed)
        print("lengthBytes - bytesProcessed:",lengthBytes - bytesProcessed)
        print("frameSizeBytes(frameSize):", frameSizeBytes(frameSize))
        if lengthBytes - bytesProcessed < frameSizeBytes(frameSize):
            print("Warning! Not enough data for last frame")
            # FIXME: The last frame needs to have the end data plus zeros padded
            break

        
        
        # Encode the audio
        if True:
            # Print out the PCM data to see that it's readable
            #p = sourcePtr
            #d = 0
            #while d < frameSize*2*2:
            #    p2 = ctypes.c_void_p(ctypes.cast(p,ctypes.c_void_p).value + d)
            #    print("p[",p2.value,"]:",ctypes.cast(p2, opus.opus_int16_p).contents.value)
            #    d += 2

                
            print("Encoding audio")
            numBytes = opus.opus_encode(
                encoder,
                ctypes.cast(sourcePtr, ctypes.POINTER(opus.opus_int16)),
                frameSize,
                encodedFramePtr,
                maxEncodedFrameBytes
            )
            print("numBytes: ", numBytes)
        
            # Check for any errors during encoding
            if numBytes < 0:
                raise Exception("Encoder error detected: "+
                                opus.opus_strerror(numBytes).decode("utf"))
        
            # Move to next position in the buffer: encoder
            oldAddress = sourcePtr.value
            #print("oldAddress:",oldAddress)
            deltaBytes = frameSize*sourceChannels*2
            newAddress = oldAddress + deltaBytes
            #print("newAddress:",newAddress)
            sourcePtr = ctypes.c_void_p(newAddress)

            bytesProcessed = sourcePtr.value - sourcePtr_init.value

        # Decode the audio
        if True:
            print("Decoding audio")
            numSamples = opus.opus_decode(decoderPtr,
                                          encodedFramePtr,
                                          numBytes,
                                          ctypes.cast(targetPtr, ctypes.POINTER(ctypes.c_short)),
                                          5760, # Max space required in PCM
                                          0 # What's this about?
            )
            print("numSamples: ",numSamples)
        
            # Check for any errors during decoding
            if numSamples < 0:
                raise Exception("Decoder error detected: "+
                                opus.opus_strerror(numSamples).decode("utf"))

            # Move to next position in the buffer: decoder
            targetPtr.value += numSamples*targetChannels*2

            



    

# Encode and re-decode the PCM buffer
print("Encoding...")
startTime = datetime.now()
encodeThenDecode(buf, buf2, opusFile.frequency)
endTime = datetime.now()
print("Duration: "+str(endTime - startTime))


# Play our re-decoded audio, if desired
if True:
    playNumpyBuffer(buf2)


# Done!
print("Finished.")
