# Check that audio can be played... at all.
import pyogg
import time
import sounddevice as sd

def check_play_audio():
    print("")
    print("Recording Audio")
    print("===============")
    print("")
    print("This test checks that we can record audio and that you can hear the recording.")

    while True:
        print("")
        
        device_strings = sd.query_devices()
        default_input_index = sd.default.device[0]
        default_device_string = device_strings[default_input_index]["name"]
        print("Selected input device:", default_device_string)

        max_input_channels = device_strings[default_input_index]["max_input_channels"]
        print("Maximum number of input channels:", max_input_channels)

        print("\nWhen you are ready to record, press enter.  Recording will start immediately")
        print("and last for three seconds.")
        user_input = input()

        print("\nRecording for three seconds...")
        duration = 3 # seconds
        samples_per_second = 48000
        samples_to_record = duration * samples_per_second
        channels = max_input_channels
        audio = sd.rec(
            samples_to_record,
            samplerate = samples_per_second,
            channels = channels
        )
        sd.wait()


        print("")

        default_output_index = sd.default.device[1]
        default_device_string = device_strings[default_output_index]["name"]
        print("Selected output device:", default_device_string)

        print("Playing back recording...")
        sd.play(audio,
                samples_per_second)

        print("\nCan you hear your recording?")
        print("Type 'y' followed by enter if you can hear the recording correctly.")
        print("")
        print("If you can't hear your recording then try again, but next time speak more loudly.")
        print("If your micophone has an 'on' switch, make sure it's turned on.")
        print("Check the sound input settings on your operating system.")
        print("")
        print("To stop playback, and to indicate that this check has failed, just press enter.")
        print("To repeat this check, type 'r' and then enter.")
        user_input = input()

        if len(user_input)>=1 and (user_input[0] == "y" or user_input[0]=="Y"):
            print("Check passed.")
            return True
        elif len(user_input)>=1 and (user_input[0] == "r" or user_input[0]=="R"):
            print("Repeating test.")
        else:
            print("Check failed.")
            return False
    
    

if __name__ == "__main__":
    check_play_audio()
