from twisted.web import server
from twisted.web.static import File

from singt.eventsource import EventSource
from singt.client.client_web_command import CommandResource

def create_web_interface(reactor):
    # TEST
    import pkg_resources
    DATA_PATH = pkg_resources.resource_filename('singt', 'client/www')

    
    # Create the web resources
    file_resource = File(DATA_PATH)#("./www/")
    root = file_resource

    # Create an event source server
    eventsource_resource = EventSource()
    root.putChild(b"eventsource", eventsource_resource)

    # Create a command receiver
    command_resource = CommandResource(reactor)
    root.putChild(b"command", command_resource)
    
    # Create a web server
    site = server.Site(root)

    return site, eventsource_resource
