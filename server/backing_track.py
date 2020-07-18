import audioop
import ctypes
import wave

import pyogg
from pyogg import opus
from pyogg import OggOpusWriter

# Validate OggOpus file coming from user.
# Assume user is passing in temp file handle
def validate_oggopus(file_handle):
    # First we'll need to read the entire file into memory.  This way
    # we do not close the file, which would delete the file if it is
    # was a TemporaryFile.
    file_handle.seek(0)
    file_contents = file_handle.read()

    # Find the length of the bytes array
    file_length = len(file_contents)

    # Get a pointer to the memory
    ctypes_file_contents = ctypes.cast(file_contents, ctypes.POINTER(ctypes.c_ubyte))

    # Get file length as ctypes
    ctypes_file_length = ctypes.c_size_t(file_length)

    # Create int for result
    ctypes_error = ctypes.c_int()
    
    # Open the memory for reading using OpusFile
    ctypes_oggopusfile_ptr = opus.op_open_memory(
        ctypes_file_contents,
        ctypes_file_length,
        ctypes.pointer(ctypes_error)
    )

    # Check if we encountered any errors
    if ctypes_error.value != 0:
        raise Exception("Failed to open file as Opus stream.  "+
                        "OpusFile error number {:d}.".format(ctypes_error.value))

    # Create an array of floats in which to store the decoded data
    buf_size = 11520 # 120ms at 48kHz
    CtypesPcmType = ctypes.c_float * buf_size
    ctypes_pcm = CtypesPcmType()
    ctypes_pcm_ptr = ctypes.cast(ctypes.byref(ctypes_pcm), ctypes.POINTER(ctypes.c_float))

    # Create an int giving the size of the array of floats
    ctypes_buf_size = ctypes.c_int(buf_size)

    # Create an int for the return value
    ctypes_samples_read = ctypes.c_int()

    while True:
        # Read the memory using OpusFile
        ctypes_samples_read = opus.op_read_float_stereo(
            ctypes_oggopusfile_ptr,
            ctypes_pcm_ptr,
            ctypes_buf_size
        )

        # Check if we've finished or if an error was detected
        if ctypes_samples_read <= 0:
            break

    # Check if an error was detected
    if ctypes_samples_read < 0:
        raise Exception(
            "Error while reading Opus file.  "+
            "OpusFile error number {:d}.".format(ctypes_samples_read.value)
        )



# Convert wav to Opus.  Assumes that file_handle may be provided from
# a TemporaryFile.
def convert_wav_to_opus(wav_file, opus_filename):
    # Create a Wave_read object
    wave_read = wave.open(wav_file)

    # Extract the wav's specification
    channels = wave_read.getnchannels()
    samples_per_second = wave_read.getframerate()
    bytes_per_sample = wave_read.getsampwidth()

    if bytes_per_sample != 2:
        raise Exception(
            "We can currently only process 16-bit wav files"
        )

    # Check if resampling is necessary
    if samples_per_second in [8000, 12000, 16000, 24000, 48000]:
        resampling_required = False
        desired_samples_per_second = samples_per_second
    else:
        resampling_required = True
        desired_samples_per_second = 48000 
        resampling_state = None
   
    # Create an OggOpusWriter
    ogg_opus_writer = OggOpusWriter(opus_filename)
    ogg_opus_writer.set_application("audio")
    ogg_opus_writer.set_sampling_frequency(desired_samples_per_second)
    ogg_opus_writer.set_channels(channels)

    # Calculate the desired frame size (in samples per channel)
    desired_frame_duration = 20/1000 # milliseconds
    desired_frame_size = int(
        desired_frame_duration
        * desired_samples_per_second
    )

    if resampling_required:
        samples_to_read = int(
            desired_frame_size
            * float(samples_per_second)
            / desired_samples_per_second
        )
    else:
        samples_to_read = desired_frame_size
    
    # Loop through the wav file's PCM data and encode it as Opus
    while True:
        # Get data from the wav file
        pcm = wave_read.readframes(samples_to_read)
        print(f"read {len(pcm)} bytes")

        # Check if we've finished reading the wav file
        if len(pcm) == 0:
            break

        # Resample the PCM if necessary
        if resampling_required:
            pcm, resampling_state = audioop.ratecv(
                pcm,
                bytes_per_sample,
                channels,
                samples_per_second,
                desired_samples_per_second,
                resampling_state
            )

        # Calculate the effective frame size from the number of bytes
        # read
        effective_frame_size = (
            len(pcm) # bytes
            // bytes_per_sample
            // channels
        )

        # Check if we've received enough data
        if effective_frame_size < desired_frame_size:
            # We haven't read a full frame from the wav file, so this
            # is most likely a final partial frame before the end of
            # the file.  We'll pad the end of this frame with silence.
            pcm += (
                b"\x00"
                * ((desired_frame_size - effective_frame_size)
                   * bytes_per_sample
                   * channels)
            )
                
        # Encode the PCM data
        ogg_opus_writer.encode(pcm)

    # Close the OggOpus file
    ogg_opus_writer.close()

    
if __name__ == "__main__":
    # Open a test file
    filename = "../sounds/starting.opus"
    #filename = "../sounds/starting.wav"
    f = open(filename, "rb")

    validate_oggopus(f)
    
    print("The file '{:s}' was a valid OggOpus file".format(filename))
