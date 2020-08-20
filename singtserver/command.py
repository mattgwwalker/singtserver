import json

from twisted.internet import defer
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
        d.addCallback(on_success)

        def on_error(error):
            log.warn("Exception occurred while attempting to get a combination ID from the database: "+ str(error))
            raise Exception("Failed to get a combination ID from the database")
        d.addErrback(on_error)

        return d


    def request_download(self, track_id=None, take_ids=[], participants=[]):
        """Requests download by the clients.

        Returns a list of deferreds, once for each participant.

        """
        # List of deferreds to gather
        ds = []
        
        # Track
        if track_id is not None:
            track_path = self._session_files.get_track_relpath(track_id)
            track_path = (
                self._web_server.get_partial_url_prefix() +
                str(track_path)
            )
            
            d = self._database.get_track_audio_id(track_id)
            def request_download_track(audio_id):
                return self._tcp_server_factory.broadcast_download_request(
                    audio_id,
                    track_path,
                    participants
                )
            d.addCallback(request_download_track)
            ds.append(d)

        # Takes
        for take_id in take_ids:
            take_path = self._session_files.get_take_relpath(take_id)
            take_path = (
                self._web_server.get_partial_url_prefix() +
                str(take_path)
            )
            
            d = self._database.get_take_audio_id(take_id)
            def request_download_take(audio_id):
                this_take_path = take_path
                return self._tcp_server_factory.broadcast_download_request(
                    audio_id,
                    this_take_path,
                    participants
                )
            d.addCallback(request_download_take)
            ds.append(d)

        # Gather deferreds
        d = gatherResults(ds)
        def on_error(error):
            log.warn("Error in requesting client downloads: "+str(error))
            return error
        d.addErrback(on_error)
            
        return d

    def prepare_for_recording(self, track_id, take_ids, participants):
        """Prepares the clients for recording.

        Returns a tuple: the first item is a deferred that resolves
        when the combination id has been obtained from the database
        and the download requests have been send, and a second item is
        a deferred that resolves when the clients have all finished
        their downloads.

        """
        d1 = self.prepare_combination(track_id, take_ids)
        d2 = defer.Deferred()
        def on_combination_prepared(combination_id):
            print("We have combination id:", combination_id)
            d2.callback(combination_id)
            return combination_id
        d1.addCallback(on_combination_prepared)
        
        def request_download(combo_id):
            d = self.request_download(track_id, take_ids, participants)
            def on_success(data):
                print("All downloads completed successfully")
                return (combo_id, "success")
            d.addCallback(on_success)
            def on_error(error):
                log.error(f"Failed to download for all clients: {error}")
                # Note that the error is being absorbed
                return (combo_id, "failure")
            d.addErrback(on_error)
            return d
        d2.addCallback(request_download)

        eventsource = self._context["web_server"].eventsource_resource
        def on_success(data):
            combo_id, result = data
            # Send notification over EventSource: this may be either
            # success or failure
            message =  {
                "combination_id": combo_id,
                "result": result
            }
            message_json = json.dumps(message)
            eventsource.publish_to_all(
                "ready_to_record",
                message_json
            )
            return combo_id
        d2.addCallback(on_success)
            
        def on_error(error):
            log.warn("Error in preparing for recording: "+str(error))
            return error
        d2.addErrback(on_error)
        
        return (d1, d2)

    def record(self, take_name, combination_id, participants):
        # We need the audio ids of the track and takes that make up
        # the combination.
        d1 = self._database.get_audio_ids_from_combination_id(combination_id)
        
        def on_success(audio_ids):
            print(f"Given combination id {combination_id} we got these backing audio ids: {audio_ids}")
            return audio_ids
        d1.addCallback(on_success)

        def on_error(error):
            log.error(f"Failed to get audio ids from combination id ({combination_id}): {error}")
            return error
        d1.addErrback(on_error)

        # Create a new take
        d2 = self._database.add_take(
            take_name,
            combination_id
        )

        # We need the audio_ids of the recordings that the clients
        # will send back
        def add_recording_ids(take_id):
            return self._database.add_recording_audio_ids(
                take_id,
                participants
            )
        d2.addCallback(add_recording_ids)

        d = gatherResults([d1, d2])
        return d # TEMP
        # def on_success(data):
        #     backing_audio_ids, recording_ids = data
        #     # Send the record command to each of the participants
        #     return self._tcp_server_factory.broadcast_record_request(
        #         backing_audio_ids,
        #         recording_ids,
        #         participants
        #     )
        # d.addCallback(on_success)

        # def on_error(error):
        #     log.error(f"Failed to record: {error}")
        #     return error
        # d.addErrback(on_error)

        
