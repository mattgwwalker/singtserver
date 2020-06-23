import numpy


class FrameBuffer:
    def __init__(self, number_of_samples, channels, dtype=numpy.float32):
        # Store the data type
        self.__dtype = dtype
        
        # Create a buffer of the desired size, filled with zeros
        self.__buffer = numpy.zeros(
            (number_of_samples, channels),
            dtype=self.__dtype
        )

        # Position in buffer from which data can be appended
        self.__pos = 0

        
    def size(self):
        """Returns the size of the buffer."""
        return self.__pos

        
    def put(self, data):
        # Check that there's sufficient space
        assert self.__pos + len(data) <= len(self.__buffer)
        
        # Copy the data
        self.__buffer[self.__pos : self.__pos+len(data)] = data[:]

        # Adjust the position
        self.__pos += len(data)

        
    def get(self, samples):
        """ Returns the frame_size data from the buffer. """
        # TODO: Is this the most efficient approach?
        frame = numpy.zeros(
            (samples,self.__buffer.shape[1]),
            dtype=self.__dtype
        )

        frame[:] = self.__buffer[0:samples]

        # Clear the old data
        channels = self.__buffer.shape[1]
        self.__buffer[0:samples].fill(0)

        # Roll the buffer so that the first uncopied sample is at
        # location 0.
        self.__buffer = numpy.roll(
            self.__buffer,
            -samples,
            axis=0
        )

        # Adjust the position for new data
        self.__pos -= samples
        if self.__pos < 0:
            self.__pos = 0

        return frame
