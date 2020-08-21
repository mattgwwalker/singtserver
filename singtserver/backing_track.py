import audioop
import ctypes
from pathlib import Path
import random
import json
import wave

import pyogg
from pyogg import opus
from pyogg import OggOpusWriter
from twisted.web import server, resource

import sys
from twisted.logger import Logger

# Start a logger with a namespace for a particular subsystem of our application.
log = Logger("backing_track")


class BackingTrack(resource.Resource):
    isLeaf = True

    def __init__(self, session_files, database, eventsource):
        super()
        self._session_files = session_files
        self._db = database
        self._eventsource = eventsource

    def render_POST(self, request):
        request.setResponseCode(201)
        
        command = request.args[b"command"][0].decode("utf-8") 
        print("command:", command)

        name = request.args[b"name"][0].decode("utf-8")
        print("name:", name)

        # Save file
        file_contents = request.args[b"file"][0]

        def make_random_filename(ext):
            return str(random.randint(0, 1e8))+ext

        user_filename = self._session_files.uploads_dir / make_random_filename(".user_upload")
        user_file = open(user_filename, "wb")
        user_file.write(file_contents)

        # Open user file for reading.  Previously we were opening the
        # file just once with the mode 'w+b', but this is incompatible
        # with reading using Python's wave module.
        user_file = open(user_filename, "rb")
        
        # Check if the file is WAV or Opus or something else
        first_bytes = user_file.read(4)
        user_file.seek(0)

        if first_bytes == b"RIFF":
            print("Uploaded file is a WAV file; need to convert it to Opus")
            # Attempt to convert the uploaded file to Opus format.
            # Give the converted file a temporary name, as we won't
            # have the correct name until it's placed in the database,
            # and we don't want to do that until we've verified that
            # the conversion process worked correctly.
            try:
                output_filename = self._session_files.uploads_dir / make_random_filename(".opus") 
                output_file = open(output_filename, "wb")
                convert_wav_to_opus(user_file, output_file)
                user_file.close()
            except Exception as e:
                msg = {
                    "result":"error",
                    "reason":(f"Regarding the backing track '{name}', the "+
                              "uploaded wav file was not able to be "+
                              "converted to Opus format: "+str(e))
                }
                log.warn("Failed to convert user wav file to opus: "+str(e))
                return json.dumps(msg).encode("utf-8")
                
            finally:
                # Delete the original wav file
                Path(user_filename).unlink()
                        
        elif first_bytes == b"OggS":
            # Uploaded file is an Ogg Stream, which may be in Opus
            # format; double-check.
            try:
                validate_oggopus(user_file)
            except Exception as e:
                msg = {
                    "result":"error",
                    "reason":("Regarding the backing track '{:s}', the uploaded ".format(name)+
                               "Opus file was not able to be read correctly: "+str(e))
                }
                return json.dumps(msg).encode("utf-8")
            output_file = user_file
            
        else:
            # Delete the original file
            Path(user_file.name).unlink()
            
            log.warn("Uploaded file was neither wav nor Opus")
            # Inform the user that there was a problem
            msg = {
                "result":"error",
                "reason":("Regarding the backing track '{:s}', the uploaded ".format(name)+
                           "file was in neither wav nor Opus formats.")
            }
            return json.dumps(msg).encode("utf-8")
        
        # Add backing track into database
        def add_backing_track():
            # TODO: Check that the backing track name hasn't already
            # been used.
            def write_to_database(cursor):
                print("Inserting '{:s}' into backing tracks".format(name))
                # Turn on foreign key constraints
                cursor.execute("PRAGMA foreign_keys = ON;")
                cursor.execute("INSERT INTO AudioIdentifiers DEFAULT VALUES")
                audio_id = cursor.lastrowid
                cursor.execute("INSERT INTO BackingTracks(audioId, trackName) VALUES (?,?);", (audio_id, name))
                backing_track_id = cursor.lastrowid
                return backing_track_id
            return self._db.dbpool.runInteraction(write_to_database)
            
        def on_success(backing_track_id):
            # Rename file
            desired_path = self._session_files.get_track_path(backing_track_id)
            log.info("Saving uploaded file as '{:s}'".format(str(desired_path)))

            output_path = Path(output_file.name)
            output_path.rename(desired_path)

            # Close the file
            output_file.close()

            msg = {
                "result":"success",
            }

            request.write(json.dumps(msg).encode("utf-8"))
            self._publish()
            request.finish()

            
        def on_error(data):
            print("in on_error, data:", data)
            msg = {
                "result":"error",
                "reason":str(data)
            }
            result = json.dumps(msg).encode("utf-8")
            print("result:",result)
            request.write(result)
            request.finish()

        d = add_backing_track()
        d.addCallback(on_success)
        d.addErrback(on_error)

        return server.NOT_DONE_YET

    def initialise_eventsource(self):
        def on_error(error):
            log.error("Failed to initialise backing track list to eventsource:" +str(error))
            
        d = self._get_backing_track_json()

        d.addCallback(lambda data: ("update_backing_tracks", data))
        d.addErrback(on_error)

        return d
        

    def _publish(self):
        def publish_results(results):
            # Send out eventsource update on list of backing tracks
            self._eventsource.publish_to_all(
                "update_backing_tracks",
                results
            )

        def on_error(error):
            log.error("Failed to publish backing track list to eventsource:" +str(error))
            
        d = self._get_backing_track_json()

        d.addCallback(publish_results)
        d.addErrback(on_error)

        return d

    def _get_backing_track_json(self):
        # Get list of backing tracks from database
        # TODO: This should be in database.py
        def execute_sql(cursor):
            cursor.execute("SELECT id, trackName FROM BackingTracks")
            rows = cursor.fetchall()
            results = [{"id":row[0], "track_name":row[1]} for row in rows]
            results_json = json.dumps(results)
            print("backing track json:", results_json)
            return results_json

        def when_ready(dbpool):
            return dbpool.runInteraction(execute_sql)
        d = self._db._db_ready.addCallback(when_ready)

        def on_error(error):
            log.error("Failed to get backing track list from database:" +str(error))

        d.addErrback(on_error)

        return d
        

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
