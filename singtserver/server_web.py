import json

import pkg_resources
from singtcommon import EventSource
from twisted.web import resource
from twisted.web import server
from twisted.web.static import File

from .backing_track import BackingTrack
from .eventsource_participants_listener import EventSourceParticipantsListener

# Start a logger with a namespace for a particular subsystem of our application.
from twisted.logger import Logger
log = Logger("server_web")

class WebServer:
    def __init__(self, context):
        session_files = context["session_files"]
        database = context["database"]
        command = context["command"]
        
        # Create the web resources
        www_dir = pkg_resources.resource_filename("singtserver", "www")
        file_resource = File(www_dir)
        self.root = file_resource

        # Session files (as File resource)
        session_files_resource = File(session_files.session_dir)
        session_files_resource.contentTypes[".opus"] = "audio/ogg"
        self.session_files_location = "session_files"
        self.root.putChild(
            self.session_files_location.encode("utf-8"),
            session_files_resource
        )

        # Event source
        self.eventsource_resource = EventSource()
        self.root.putChild(b"eventsource", self.eventsource_resource)

        # Add event source as a listener of participants
        self._event_source_participants_listener = \
            EventSourceParticipantsListener(
                context["participants"],
                self.eventsource_resource
            )

        # Backing tracks
        self.backing_track_resource = BackingTrack(
            session_files,
            database,
            self.eventsource_resource
        )
        self.root.putChild(b"backing_track", self.backing_track_resource)

        # Create a command resource
        self.command_resource = WebCommand(command)
        self.root.putChild(b"command", self.command_resource)

        # Create a web server
        self.site = server.Site(self.root)
        self.www_port = None

    def set_www_port(self, port):
        self.www_port = port
        
    def get_partial_url_prefix(self):
        return ":"+str(self.www_port)+"/"+self.session_files_location+"/"


class WebCommand(resource.Resource):
    isLeaf = True

    def __init__(self, command):
        super()
        self._command = command

        self.commands = {}
        self._register_commands()
        
    def render_POST(self, request):
        content = request.content.read()
        content = json.loads(content)

        command = content["command"]

        command_handler = self.commands[command]

        return command_handler(content, request)

    def register_command(self, command, function):
        self.commands[command] = function
        
    def _success(self, data, request):
        request.setResponseCode(200)
        result = {
            "result": "success",
            "data": str(data),
        }
        result_json = json.dumps(result).encode("utf-8")
        request.write(result_json)
        request.finish()

    def _make_success(self, request):
        def f(data):
            self._success(data, request)
        return f

    def _failure(self, error, request, finish=False):
        log.error(error)
        request.setResponseCode(500)
        result = {
            "result":"failure",
            "error":str(error)
        }
        result_json = json.dumps(result).encode("utf-8")
        request.write(result_json)
        if finish:
            request.finish()

    def _make_failure(self, request, message = None, raise_exception=False):
        def f(error):
            log.error(str(error))
            nonlocal message
            if message is None:
                message = error
            self._failure(message, request, finish=not raise_exception)
            if raise_exception:
                raise error
        return f
            
    def _register_commands(self):
        self.register_command("play_for_everyone", self._command_play_for_everyone)
        self.register_command("stop_for_everyone", self._command_stop_for_everyone)
        self.register_command("prepare_for_recording", self._command_prepare_for_recording)
        self.register_command("record", self._command_record)

    def _command_play_for_everyone(self, content, request):
        try:
            track_id = int(content["track_id"])
        except KeyError:
            track_id = None

        try:
            take_ids = [int(id) for id in content["take_ids"]]
        except KeyError:
            take_ids = []

        try:
            self._command.play_for_everyone(track_id, take_ids)
            self._success("Started playing for everyone", request)
        except Exception as e:
            self._failure(e, request, finish=False)
            raise

        return server.NOT_DONE_YET
            
    def _command_stop_for_everyone(self, content, request):
        try:
            self._command.stop_for_everyone()
            self._success("Stopped playing for everyone", request)
        except Exception as e:
            self._failure(e, request, finish=False)
            raise

        return server.NOT_DONE_YET

    def _command_prepare_for_recording(self, content, request):
        try:
            track_id = int(content["track_id"])
        except KeyError:
            track_id = None

        try:
            take_ids = [int(id) for id in content["take_ids"]]
        except KeyError:
            take_ids = []

        try:
            participants = [int(id) for id in content["participants"]]
        except KeyError:
            raise Exception("Failed to find 'participants' key in content while preparing for recording")

        try:
            # This also returns a second deferred, however we can
            # ignore that as here we need only respond to the request
            # itself.
            d, _ = self._command.prepare_for_recording(
                track_id,
                take_ids,
                participants
            )
            def make_json_response(combination_id):
                result = {
                    "result":"success",
                    "combination_id":combination_id
                }
                result_json = json.dumps(result).encode("utf-8")
                request.write(result_json)
                request.finish()
                return combination_id
            d.addCallback(make_json_response)
            d.addErrback(self._make_failure(
                request,
                message="Failed during preparation of recording",
                raise_exception=True
            ))
            
        except Exception as e:
            message = "Failed to prepare for recording"
            self._failure(message, request, finish=False)
            raise

        return server.NOT_DONE_YET

    
    def _command_record(self, content, request):
        # Extract take name
        try:
            take_name = content["take_name"]
        except KeyError:
            take_name = ""
        
        # Extract combination ID
        try:
            combination_id = int(content["combination_id"])
        except KeyError:
            message = "Invalid 'record' command; combination_id not specified"
            self._failure(message, request, finish=False)
            raise Exception(message)

        try:
            participants = [int(id) for id in content["participants"]]
        except KeyError:
            raise Exception("Failed to find 'participants' key in content while preparing for recording")

        print(f"Record combination id {combination_id} with participants {participants}")

        d = self._command.record(
            take_name,
            combination_id,
            participants
        )

        def on_success(_):
            self._success("Recording started", request)
        d.addCallback(on_success)
        
        return server.NOT_DONE_YET
        
