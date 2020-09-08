import json

from twisted.internet import defer

from singtcommon import EventSource

class EventSourceParticipantsListener:
    def __init__(self, participants, eventsource):
        self._participants = participants
        self._eventsource = eventsource

        # Register event source callbacks
        def as_deferred():
            d = defer.Deferred()
            event = "update_participants"
            data = self._publish_complete_list()
            d.callback((event,data))
            return d
        self._eventsource.add_initialiser(as_deferred)

    def participant_joined(self, client_id, name):
        print(f"Participant joined with client_id {client_id} "+
              f"and name '{name}'")
        self._publish_complete_list()
        
    def participant_left(self, client_id, name):
        print(f"Participant left with client_id {client_id} "+
              f"and name '{name}'")
        self._publish_complete_list()

    def _publish_complete_list(self):
        # Get list
        participants_list = self._participants.get_list()

        # Convert to strings as javascript cannot handle 64-bit ints.
        participants_list = [
            {"id":str(id_), "name":name}
            for id_, name in participants_list
        ]
        participants_list_json = json.dumps(participants_list)
        
        # Publish the complete list to the eventsource
        self._eventsource.publish_to_all(
            "update_participants",
            participants_list_json
        )
