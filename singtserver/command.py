from twisted.internet.defer import gatherResults
from twisted.logger import Logger

# Start a logger with a namespace for a particular subsystem of our application.
log = Logger("command")


class Command:
    def __init__(self, context):
        self._context = context
        self._database = context["database"]
        self._session_files = context["session_files"]
        self._udp_server = context["udp_server"]
        self._tcp_server_factory = None
        self._web_server = None


    def set_tcp_server_factory(self, tcp_server_factory):
        self._tcp_server_factory = tcp_server_factory


    def set_web_server(self, web_server):
        self._web_server = web_server

        
    def play_for_everyone(self, track_id, take_ids):
        if track_id is None and len(take_ids) == 0:
            raise Exception("'Play for everyone' requires at least a track ID or a take ID")
        
        # Get path of the track
        track_path = self._session_files.get_track_path(track_id)
        
        # Get paths of the takes
        take_paths = [self._session_files.get_take_path(take_id)
                      for take_id in take_ids]

        # Combine paths
        paths = take_paths
        paths.append(track_path)
        
        # Request ServerUDP to play the audio
        self._udp_server.play_audio(paths)

        
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


    def request_download(self, track_id=None, take_ids=[], participants=[]):
        # List of deferreds to gather
        ds = []
        
        # Track
        if track_id is not None:
            track_path = self._session_files.get_track_relpath(track_id)
            track_path = (
                self._web_server.get_partial_url_prefix() +
                str(track_path)
            )
            
            d_track_audio_id = self._database.get_track_audio_id(track_id)
            def request_download_track(audio_id):
                return self._tcp_server_factory.broadcast_download_request(
                    audio_id,
                    track_path,
                    participants
                )
            d_track_audio_id.addCallback(request_download_track)
            ds.append(d_track_audio_id)

        # Takes
        for take_id in take_ids:
            take_path = self._session_files.get_take_relpath(take_id)
            take_path = (
                self._web_server.get_partial_url_prefix() +
                str(take_path)
            )
            
            d_take_audio_id = self._database.get_take_audio_id(take_id)
            def request_download_take(audio_id):
                this_take_path = take_path
                return self._tcp_server_factory.broadcast_download_request(
                    audio_id,
                    this_take_path,
                    participants
                )
            d_take_audio_id.addCallback(request_download_take)
            ds.append(d_take_audio_id)

        # Gather deferreds
        d = gatherResults(ds)
        def on_error(error):
            log.warn("Error in requesting client downloads: "+str(error))
            return error
        d.addErrback(on_error)
            
        return d

    def prepare_for_recording(self, track_id, take_ids, participants):
        d_combo_id = self.prepare_combination(track_id, take_ids)
        d_requested_download = self.request_download(track_id, take_ids, participants)

        d = gatherResults([d_combo_id, d_requested_download])
        def on_error(error):
            log.warn("Error in preparing for recording: "+str(error))
            return error
        d.addErrback(on_error)
        
        return d
