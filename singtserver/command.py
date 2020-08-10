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
