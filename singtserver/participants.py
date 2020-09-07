# Start a logger with a namespace for a particular subsystem of our application.
from twisted.logger import Logger
log = Logger("participants")

class Participants:
    def __init__(self, context):
        self._context = context
        self._db = context["database"]
        self._joined_participants = {}
        self._joining_participants = {}
        self._listeners = []

    def join_tcp(self, client_id, name):
        """Joins client as participant with TCP data.

        If the client has already announced themselves via UDP, then
        we join the client to the list of participants.  Otherwise, we
        store the data until the UDP announcement is received.

        Returns False immediately if the UDP announcement hasn't
        already been made, otherwise returns a deferred that resolves
        when the client ID and name have been saved in the database.

        """
        # Check if the client is already joined, if so disconnect them
        # first
        if client_id in self._joined_participants:
            self.leave(client_id)
        
        # Check if the client has already announced via UDP
        try:
            data = self._joining_participants[client_id]
            udp = data["udp"]
        except KeyError:
            data = {}
            udp = None
            
        # Check if the join is currently being executed.  Return the
        # active deferred if it is.
        try:
            d = data["deferred"]
            return d
        except KeyError:
            pass
        
        # Join the client id as a participant if the client id has
        # already announced via UDP, otherwise store the TCP data
        if udp:
            d = self._do_join(client_id, name)
            data["deferred"] = d
            self._joining_participants[client_id] = data
            return d
        else:
            data["name"] = name
            data["tcp"] = True
            self._joining_participants[client_id] = data

        return False

    def join_udp(self, client_id):
        """Joins client as participant with UDP data.

        If the client has already announced themselves via TCP, then
        we join the client to the list of participants.  Otherwise, we
        store the data until the TCP announcement is received.

        Returns False immediately if the TCP announcement hasn't
        already been made, otherwise returns a deferred that resolves
        when the client ID and name have been saved in the database.

        """
        # Check if the client is already joined, if so disconnect them
        # first
        if client_id in self._joined_participants:
            self.leave(client_id)
        
        # Check if the client has already announced via TCP
        try:
            data = self._joining_participants[client_id]
            tcp = data["tcp"]
            name = data["name"]
        except KeyError:
            data = {}
            tcp = None

        # Check if the join is currently being executed.  Return the
        # active deferred if it is.
        try:
            d = data["deferred"]
            return d
        except KeyError:
            pass
        
        # Join the client id as a participant if the client id has
        # already announced via TCP, otherwise store the UDP data
        if tcp:
            d = self._do_join(client_id, name)
            data["deferred"] = d
            self._joining_participants[client_id] = data
            return d
        else:
            data["udp"] = True
            self._joining_participants[client_id] = data

        return False

    
    def _do_join(self, client_id, name):
        """Assigns name to client_id, overwriting if it exists already.

        Broadcasts new client on eventsource.

        """
        d = self._db.assign_participant(client_id, name)

        def on_success(client_id):
            del self._joining_participants[client_id]
            self._joined_participants[client_id] = name
            for listener in self._listeners:
                listener.participant_joined(client_id, name)
            return (client_id, name)

        d.addCallback(on_success)
        return d

    
    def leave(self, client_id):
        try:
            name = self._joined_participants[client_id]
            del self._joined_participants[client_id]
            for listener in self._listeners:
                listener.participant_left(client_id, name)

        except KeyError:
            log.warn(
                f"Failed to find participant with client id "+
                f"{client_id}; could not remove from participants "+
                f"list"
            )

    
    def get_list(self):
        """Returns list of currently connected participants."""
        connected_list = [
            {"id":id_, "name":name}
            for id_, name in self._joined_participants.items()
        ]
        return connected_list

    
    def add_listener(self, listener):
        self._listeners.append(listener)
