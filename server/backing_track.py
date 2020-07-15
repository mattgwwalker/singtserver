import ctypes

import pyogg
from pyogg import opus

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


if __name__ == "__main__":
    # Open a test file
    filename = "../sounds/starting.opus"
    #filename = "../sounds/starting.wav"
    f = open(filename, "rb")

    validate_oggopus(f)
    
    print("The file '{:s}' was a valid OggOpus file".format(filename))
