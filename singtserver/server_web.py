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
        
    def _success(self):
        result = {
            "result": "success"
        }

        result_json = json.dumps(result).encode("utf-8")

        return result_json

    def _failure(self, error):
        result = {
            "result":"failure",
            "error":str(error)
        }
        request.write(json.dumps(result).encode("utf-8"))
        request.finish()
            
    def _register_commands(self):
        self.register_command("play_for_everyone", self._command_play_for_everyone)
        self.register_command("stop_for_everyone", self._command_stop_for_everyone)

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
            return self._success()
        except Exception as e:
            return self._failure(e)
            raise
            
    def _command_stop_for_everyone(self, content, request):
        try:
            self._command.stop_for_everyone()
            return self._success()
        except Exception as e:
            return self._failure(e)
            raise
