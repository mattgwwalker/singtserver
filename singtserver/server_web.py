from twisted.web import server
from twisted.web.static import File

from backing_track import BackingTrack
from singt.eventsource import EventSource

def create_web_interface(uploads_dir, backing_track_dir, database):
    # Create the web resources
    file_resource = File("./www/")
    root = file_resource

    eventsource_resource = EventSource()
    root.putChild(b"eventsource", eventsource_resource)

    backing_track_resource = BackingTrack(
        uploads_dir,
        backing_track_dir,
        database,
        eventsource_resource
    )
    root.putChild(b"backing_track", backing_track_resource)

    # Create a web server
    site = server.Site(root)

    return site, eventsource_resource, backing_track_resource
