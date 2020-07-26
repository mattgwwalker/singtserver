import sounddevice as sd
import numpy
import math

class AutomaticGainControl:
    def __init__(self, max_gain=25):
        self.gain = 1
        self.mu = 0.1
        self.target = 0.5
        self.max_gain = max_gain

    def apply(self, sample):
        """Applies automatic gain to the given sample.

        Overwrites data in place.

        """
        # Store previous gain
        old_gain = self.gain

        # Apply previous gain to form temp array
        temp = sample * self.gain

        # Measure max of scaled input
        max_in_sample = numpy.max(abs(temp))

        # Calculate difference compared to desired gain
        error = self.target - max_in_sample

        # Calculate new gain, for next time
        self.gain += self.mu * (error**2) * numpy.sign(error)
        if math.isnan(self.gain):
            self.gain = 1
        if self.gain > self.max_gain:
            self.gain = self.max_gain
        if self.gain < 0:
            self.gain = 0

        # Create a linear scaling from the old value to the new one
        channels = sample.shape[1]
        multiplier = numpy.linspace(
            start = [old_gain] * channels,
            stop = [self.gain] * channels,
            num = len(sample)
        )

        # Apply multiplier to input
        sample *= multiplier


if __name__ == "__main__":
    print("Testing automatic gain control:")
    
    agc = AutomaticGainControl()

    def callback(indata, outdata, frames, time, status):
        if status:
            print(status)

        # Automatic gain control
        agc.apply(indata)

        # Write to output
        outdata[:] = indata


    stream = sd.Stream(
        callback = callback
    )

    with stream:
        print("Press any key to finish")
        input()
