# Check that audio can be played... at all.
import pyogg
import time
import sounddevice as sd
import numpy
from enum import Enum

# Phase One
# =========
# Measure latency approximately via tones.
def phase_one(desired_latency="low", samples_per_second=48000, channels=(2,2)):
    """Channels are specified as a tuple of (input channels, output channels)."""
    input_channels, output_channels = channels

    # Generate the tones required.  Frequencies chosen from mid-points
    # of FFT analysis.
    fft_n = 256 # Approximately 5ms at 48kHz
    fft_freqs = numpy.fft.rfftfreq(fft_n) * samples_per_second
    freqs = [375, 1125, 2250]

    # Get index of desired frequencies
    freq_indices = []
    for freq in freqs:
        indices = numpy.where(fft_freqs == freq)
        assert len(indices) == 1
        freq_indices.append(indices[0][0])

    # FIXME: This duration should be shorter, but it needs to finish
    # at a zero-crossing of the sine wave.  A quick fix is just to
    # make the duration much longer than it needs to be.
    duration = 10.0 # seconds
    t = numpy.linspace(0, duration, int(duration * samples_per_second), False)

    tones = []
    for freq in freqs:
        tone = numpy.sin(freq * t * 2 * numpy.pi)

        if output_channels == 2:
            two_channels = [[x,x] for x in tone]
            tones.append(numpy.array(two_channels, dtype=numpy.float32))
        else:
            tones.append(tone)

        del tone

        
    # Normalise the tones so that when combined they'll never clip
    for index,tone in enumerate(tones):
        tones[index] = tone / len(tones)
        
        
    # Initialise the current position for each tone
    tone_positions = [0] * len(tones)


    # Allocate space for recording
    max_recording_duration = 10 #seconds
    max_recording_samples = max_recording_duration * samples_per_second
    rec_pcm = numpy.zeros((
        max_recording_samples,
        input_channels
    ))

    # Initialise recording position
    rec_position = 0

    # Initialise tones detected, which stores the number of samples
    # for which the tone has been continuously detected.
    tones_detected = [0] * len(tones)

    # Initialise the number of samples for which the tone has been
    # played; None indicates the tone is not being played.
    tones_played = [None] * len(tones)

    # Initialise the number of samples for which the tone has been
    # continuously silent; we start in silence
    tones_silence = [0] * len(tones)

    # Set the minimum on-time for a tone
    min_on_seconds = 0.3 # seconds
    min_on_samples = min_on_seconds * samples_per_second

    # Set the minimum on-time for a tone
    min_off_seconds = 3 # seconds
    min_off_samples = min_off_seconds * samples_per_second

    # States for a tone
    class State(Enum):
        RESET = 0
        #STARTING = 1
        PLAYING = 2
        #STOPPING = 3
        STOPPED = 4
    tones_state = [State.RESET] * len(tones)

    # Commands for a tone
    class Command(Enum):
        NONE = 0
        START = 1
        STOP = 2
    tones_cmd = [Command.NONE] * len(tones)

    # Start the first tone
    tones_cmd[0] = Command.START
    
    # Callback for when the recording buffer is ready.  The size of the
    # buffer depends on the latency requested.
    def callback(indata, outdata, samples, time, status):
        nonlocal rec_position, tone_positions, tones_detected, tones_played
        nonlocal tones_silence

        # FIXME: These aren't necessary when finished
        assert len(indata) == len(outdata)
        assert len(indata) == samples
        
        print("")
        
        if status:
            print(status)

        # Transitions
        # ===========

        for index, tone_state in enumerate(tones_state):
            tone_cmd = tones_cmd[index]
            if tone_state == State.RESET:
                if tone_cmd == Command.NONE:
                    pass
                elif tone_cmd == Command.START:
                    tones_state[index] = State.PLAYING
                else:
                    print("Invalid command (",tone_cmd,") for tone",index,"in state",tone_state)
                    tones_cmd[index] = Command.NONE
                    
            elif tone_state == State.PLAYING:
                if tone_cmd == Command.NONE:
                    pass
                elif tone_cmd == Command.STOP:
                    if tones_played[index] >= min_on_samples:
                        tones_state[index] = State.STOPPING
                    else:
                        print("Tone",index,"requested to stop, ",
                              "but it hasn't been on for long enough")
                else:
                    print("Invalid command (",tone_cmd,") for tone",index,"in state",tone_state)
                    tones_cmd[index] = Command.NONE
                    
            elif tone_state == State.STOPPED:
                if tones_silence[index] >= min_off_samples:
                    tones_state[index] = State.RESET


        # FIXME: Temp remove the following code
        if False:
            # If the background tone has been detected, then we need to
            # start measuring latency
            if tones_detected[0] > 0.5*samples_per_second:
                # If we've just started playing this tone, set tones
                # played to zero
                if tones_played[1] is None:
                    print("Playing second tone")
                    tones_played[1] = 0
                    tones_play_cmd[1] = True


            # Respond to detection of the tone if we've heard it
            # continuously for sufficient time.
            threshold_samples = 256 # approx 5ms
            if (tones_detected[1] >= threshold_samples) and (tones_played[1] is not None):
                if tones_played[1] is None:
                    print("False detection")
                else:
                    samples_since_started = tones_played[1] - threshold_samples 
                    seconds_since_started = samples_since_started / samples_per_second
                    print("time_since_start:",
                          round(seconds_since_started*1000, 1),
                          "ms")


                    print("Requesting that tone #",1,"stop")
                    tones_stop_cmd[1] = True



                
        #print("Stop cmd:", tones_stop_cmd)
        #print("silence:", tones_silence)

        # States
        # ======
                
        # Fill the outdata with zeros
        if output_channels == 1:
            outdata[:] = [0] * samples
        else:
            outdata[:] = [[0,0]] * samples


        for index, tone_state in enumerate(tones_state):
            print("Tone",index,"in state",tone_state)
            if tone_state == State.RESET:
                pass
            elif tone_state == State.PLAYING:
                print("Playing tone #", index)
                # We have been requested to play the tone
                if tone_positions[index]+samples <= len(tones[index]):
                    # Copy tone in one hit
                    outdata[:] += tones[index] \
                        [tone_positions[index]:tone_positions[index]+samples]
                    tone_positions[index] += samples
                else:
                    # Need to loop back to the beginning of the tone
                    remaining = len(tones[index])-tone_positions[index]
                    outdata[:remaining] += (
                        tones[index][tone_positions[index]:len(tones[index])]
                    )
                    outdata[remaining:] += (
                        tones[index][:samples-remaining]
                    )
                    tone_positions[index] = samples-remaining
                if tones_played[index] is None:
                    tones_played[index] = samples
                else:
                    tones_played[index] += samples

                # We're now playing this tone so set silence to None
                tones_silence[index] = None

                
            elif tone_state == State.STOPPING:
                print("Stopping tone #", index)
                # We have been requested to stop the tone; we want to
                # finish on a zero-crossing.  Rather than searching
                # for a zero-crossing, we can just fade out the tone.
                fade_multiplier = numpy.linspace(1, 0, samples)
                if output_channels == 2:
                    fade_multiplier = [[x,x] for x in fade_multiplier]
                
                if tone_positions[index]+samples <= len(tones[index]):
                    # Copy tone in one hit
                    outdata[:] = tones[index] \
                        [tone_positions[index]:tone_positions[index]+samples] \
                        * fade_multiplier
                else:
                    # Need to loop back to the beginning of the tone
                    remaining = len(tones[index])-tone_positions[index]
                    outdata[:remaining] = (
                        tones[index][tone_positions[index]:len(tones[index])] \
                        * fade_multiplier[:remaining]
                    )
                    outdata[remaining:] = (
                        tones[index][:samples-remaining] \
                        * fade_multiplier[-samples-remaining-1:]
                    )

                # Set tone position back to zero
                tone_positions[index] = 0

                # Set number of samples played back to None to
                # indicate that it's not currently being played
                tones_played[index] = None

                # Set the number of samples of silence to zero
                tones_silence[index] = 0

                # Turn off the stop command
                print("Clearing the stop command for index", index)
                tones_stop_cmd[index] = False

                # Turn off the play command
                print("Clearing the play command for index", index)
                tones_play_cmd[index] = False

                
            elif tone_state == State.STOPPED:
                pass
            
        

        # FIXME: Temp inactive
        if False:
            # Count silence
            for index in range(len(tones)):
                if (not tones_play_cmd[index]) and (not tones_stop_cmd[index]):
                    # Increment the number of samples of silence
                    if tones_silence[index] is None:
                        tones_silence[index] = samples
                    else:
                        tones_silence[index] += samples


            # Store the recording
            rec_pcm[rec_position:rec_position+samples] = indata[:]
            rec_position += samples


            # Analysis
            # ========

            # If we have more than the required number of samples
            # recorded, execute FFT analysis
            if rec_position > fft_n:
                data = rec_pcm[rec_position-256:rec_position]
                data_transpose = data.transpose()
                left = data_transpose[0]
                right = data_transpose[1]
                mono = left+right

                sp = numpy.fft.rfft(
                    mono,
                    n=fft_n
                )
                sp = numpy.abs(sp)
                sp_max = sp.max()
                if sp_max == 0:
                    # We don't have any signal; stop analysing
                    return 
                db = 20*numpy.log10(sp / sp.max())

                dbs = []
                for freq_index in freq_indices:
                    y = db[freq_index]
                    dbs.append(y)

                sum_others = numpy.sum(db) - numpy.sum(dbs)
                mean_others = sum_others / len(db)

                # Clear decisions
                decisions = [False] * len(freqs)

                # Detect the first tone
                threshold_noise_db = 20 # dB louder than noise
                threshold_signal_db = 20 # db within other signals
                decisions[0] = (
                    (dbs[0] - threshold_noise_db > mean_others) and
                    (dbs[0] + threshold_signal_db > dbs[1]) and
                    (dbs[0] + threshold_signal_db > dbs[2])
                )

                if decisions[0]:
                    tones_detected[0] += samples
                else:
                    tones_detected[0] = 0

                # Detect the second tone
                #decisions[1] = dbs[1] - 20 > mean_others
                decisions[1] = (
                    (dbs[1] - threshold_noise_db > mean_others) and
                    (dbs[1] + threshold_signal_db > dbs[0]) and
                    (dbs[1] + threshold_signal_db > dbs[2])
                )
                if decisions[1]:
                    tones_detected[1] += samples
                else:
                    tones_detected[1] = 0

                print(
                    samples,
                    "play:",tones_play_cmd,
                    "decision:",decisions,
                    "s.played:",tones_played,
                    "s.detected:",tones_detected,
                    round(mean_others,1),
                    numpy.around(dbs,1)
                )

            
    # Play first tone
    # Open a read-write stream
    stream = sd.Stream(samplerate=48000,
                       channels=2,
                       dtype=numpy.float32,
                       latency=0.2,#"low",
                       callback=callback)

    print("Playing...")
    with stream:
        input()  # Wait until playback is finished

    # Done!
    print("Finished.")




        
def phase_two(approximate_latency):
    pass



def measure_latency():
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
    
    approximate_latency = phase_one()
    accurate_latency = phase_two(approximate_latency)
    
    

if __name__ == "__main__":
    measure_latency()
