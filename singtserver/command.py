from twisted.logger import Logger

# Start a logger with a namespace for a particular subsystem of our application.
log = Logger("command")


class Command:
    def __init__(self,
                 session_files,
                 database,
                 udp_server):
        self._database = database
        self._session_files = session_files
        self._udp_server = udp_server

        
    def play_for_everyone(self, track_id, take_ids):
        if track_id is None and len(take_ids) == 0:
            raise Exception("'Play for everyone' requires at least a track ID or a take ID")
        
        # Get filename of the track
        track_filename = self._session_files.get_track_filename(track_id)
        print("track_filename:", track_filename)
        
        # Get filenames of the takes
        take_filenames = [self._session_files.get_take_filename(take_id)
                          for take_id in take_ids]
        print("take_filenames:", take_filenames)

        # Combine filenames
        filenames = take_filenames
        filenames.append(track_filename)
        print("filenames:", filenames)
        
        # Request ServerUDP to play the audio
        self._udp_server.play_audio(filenames)

        
    def stop_for_everyone(self):
        self._udp_server.stop_audio()


    def prepare_combination(self, track_id, take_ids):
        if track_id is None and len(take_ids) == 0:
            raise Exception("'Prepare combination' requires at least a track ID or a take ID")

        # Check to see if the combination already exists
        d = self._database.get_combination(track_id, take_ids)

        def on_success(combo_id):
            # May return either a deferred (if we're going to add the
            # combination into the database) or an immediate result
            # (if the combination already exists).
            if combo_id is None:
                # Add the combination into the database
                return self._database.add_combination(track_id, take_ids)
            return combo_id

        def on_error(error):
            log.warn("Exception occurred while attempting to get a combination ID from the database: "+ str(error))
            raise Exception("Failed to get a combination ID from the database")

        d.addCallback(on_success)
        d.addErrback(on_error)
        return d
        

