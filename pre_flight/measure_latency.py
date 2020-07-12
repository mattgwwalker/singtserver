# Check that audio can be played... at all.
import pyogg
import time
import sounddevice as sd
import numpy
from enum import Enum
import time
import threading
import math
import operator
import wave
from measure_levels import measure_levels
from measure_latency_phase_one import measure_latency_phase_one
from measure_latency_phase_two import measure_latency_phase_two


def measure_latency(desired_latency="high", repeats=3):
    print("Desired latency:", desired_latency)
    levels = measure_levels(desired_latency)

    phase_one_median_latencies = []
    for i in range(repeats):
        print("\n")
        latencies = measure_latency_phase_one(levels, desired_latency)
        median_latency = numpy.median(latencies)
        print("median latency (ms):", round(median_latency*1000))
        phase_one_median_latencies.append(median_latency)

    phase_two_median_latencies = []
    for i in range(repeats):
        print("\n")
        latencies = measure_latency_phase_two(levels, desired_latency)
        print("latencies:", latencies)
        if latencies is None:
            # Insufficient number of successful measures (multiple possible clicks detected)
            print("Warning: No median produced")
        else:
            median_latency = numpy.median(latencies)
            print("median latency (ms):", round(median_latency*1000))
            phase_two_median_latencies.append(median_latency)

    phase_one_mean_median_latency = numpy.mean(phase_one_median_latencies)
    print("Phase One: mean of the median latencies (ms):",
          round(phase_one_mean_median_latency*1000))

    phase_two_mean_median_latency = numpy.mean(phase_two_median_latencies)
    print("Phase Two: mean of the median latencies (ms):",
          round(phase_two_mean_median_latency*1000))

    
    #return mean_median_latency
    

if __name__ == "__main__":
    print("")
    print("Measuring Latency")
    print("=================")
    print("")
    print("We are now going to measure the latency in your audio system.  Latency is the time")
    print("starting from when the program requests that a sound is made, until the program hears")
    print("that sound in a recording of itself.  This latency measure is used to adjust recordings")
    print("so that they are synchronised with the backing track.  If you change the configuration")
    print("of the either the playback or the recording device then you will need to re-run this")
    print("measurement.")
    print("")
    print("You will need to adjust the position of the microphone and output device.  For this")
    print("measurement, the microphone needs to be able to hear the output.  So, for example, if")
    print("you have headphones with an inline microphone, place the microphone over one of the")
    print("ear pieces.")
    print("")
    print("The process takes a few seconds.  It will play a constant tone.  You will need to ")
    print("increase the volume until the microphone can reliably hear the output.  It will then")
    print("play a number of tones until it has approximately measured the latency in your system.")
    print("It will then play a number of clicks to accurately measure the latency.")
    print("")
    print("Do not move the microphone or output device once the system can hear the constant tone.")
    print("Do not make any noise during this measurement.")
    print("")
    print("Press enter to start.")
    print("")

    input() # wait for enter key

    measure_latency(
        #desired_latency="high"
        desired_latency=100/1000 # seconds
    )
