import numpy


class FrameBuffer:
    def __init__(self, number_of_samples, channels, dtype=numpy.float32):
        # Store the data type
        self._dtype = dtype
        
        # Create a buffer of the desired size, filled with zeros
        self._buffer = numpy.zeros(
            (number_of_samples, channels),
            dtype=self._dtype
        )

        # Position in buffer from which data can be appended
        self._pos = 0

        
    def size(self):
        """Returns the size of the buffer."""
        return self._pos

        
    def put(self, data):
        # Check that the number of channels matches
        assert data.shape[1] == self._buffer.shape[1]
        
        # Check that there's sufficient space
        assert self._pos + len(data) <= len(self._buffer)
        
        # Copy the data
        self._buffer[self._pos : self._pos+len(data)] = data[:]

        # Adjust the position
        self._pos += len(data)

        
    def get(self, samples):
        """ Returns the frame_size data from the buffer. """
        # TODO: Is this the most efficient approach?
        frame = numpy.zeros(
            (samples,self._buffer.shape[1]),
            dtype=self._dtype
        )

        frame[:] = self._buffer[0:samples]

        # Clear the old data
        channels = self._buffer.shape[1]
        self._buffer[0:samples].fill(0)

        # Roll the buffer so that the first uncopied sample is at
        # location 0.
        self._buffer = numpy.roll(
            self._buffer,
            -samples,
            axis=0
        )

        # Adjust the position for new data
        self._pos -= samples
        if self._pos < 0:
            self._pos = 0

        return frame
