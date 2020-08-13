import json

import pkg_resources
from twisted.web import resource
from twisted.web import server
from twisted.web.static import File

from backing_track import BackingTrack
from singtcommon import EventSource

def create_web_interface(session_files, database, command):
    # Create the web resources
    www_dir = pkg_resources.resource_filename("singtserver", "www")
    file_resource = File(www_dir)
    root = file_resource

    eventsource_resource = EventSource()
    root.putChild(b"eventsource", eventsource_resource)

    backing_track_resource = BackingTrack(
        session_files,
        database,
        eventsource_resource
    )
    root.putChild(b"backing_track", backing_track_resource)

    # Create a command resource
    command_resource = WebCommand(command)
    root.putChild(b"command", command_resource)
    
    # Create a web server
    site = server.Site(root)

    return site, eventsource_resource, backing_track_resource


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
            return self._success("Started playing for everyone")
        except Exception as e:
            return self._failure(e)
            raise
            
    def _command_stop_for_everyone(self, content, request):
        try:
            self._command.stop_for_everyone()
            return self._success("Stopped playing for everyone")
        except Exception as e:
            return self._failure(e)
            raise

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
            d = self._command.prepare_combination(track_id, take_ids)
            d.addCallback(self._make_success(request))
            d.addErrback(self._make_failure(
                request,
                message="Failed during preparation of combination",
                raise_exception=True
            ))
            
        except Exception as e:
            message = "Failed to prepare combination"
            self._failure(message, request, finish=False)
            raise

        return server.NOT_DONE_YET
