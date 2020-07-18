from twisted.web import resource
from twisted.web import server

# See https://github.com/juggernaut/twisted-sse-demo/blob/master/sse_server.py
class EventSource(resource.Resource):
    isLeaf = True

    def __init__(self):
        self.subscribers = set()
        self._initialisers = {}
        
    
    def render_GET(self, request):
        request.setHeader('Content-Type', 'text/event-stream; charset=utf-8')
        request.setResponseCode(200)
        self.add_subscriber(request)
        request.write("")
        return server.NOT_DONE_YET

    
    def add_subscriber(self, request):
        #log.msg("Adding subscriber...")
        self.subscribers.add(request)
        d = request.notifyFinish()
        d.addBoth(self.remove_subscriber)

        # Loop through all the initialisers to bring the newly
        # connected client up to date.
        for event, f in self._initialisers.items():
            data = f()
            self.publish_to_one(request, event, data)

    
    def remove_subscriber(self, subscriber):
        if subscriber in self.subscribers:
            #log.msg("Removing subscriber..")
            self.subscribers.remove(subscriber)


    def publish_to_all(self, event, data):
        for subscriber in self.subscribers:
            self.publish_to_one(subscriber, event, data)

            
    def publish_to_one(self, request, event, data):
        request.write("event: {:s}\n".format(event).encode("utf-8"))
        request.write("data: {:s}\n".format(data).encode("utf-8"))
        # A extra new line is required to dispatch the event to the client
        request.write(b"\n")
                          

    def add_initialiser(self, event, f):
        self._initialisers[event] = f
        
