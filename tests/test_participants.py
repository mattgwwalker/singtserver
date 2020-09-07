from pathlib import Path

import pytest_twisted

from singtserver import SessionFiles
from singtserver import Database
from singtserver import Participants

def create_participants(test_name):
    # Create an empty context
    context = {}

    # Create session files
    session_files = SessionFiles(Path.cwd() / ("test_participants__"+test_name))
    context["session_files"] = session_files

    # Create a database
    database = Database(context)
    context["database"] = database

    # Create a Participants instance
    participants = Participants(context)

    return participants

def create_listener():
    class Listener:
        def participant_joined(self, client_id, name):
            print(f"Participant joined with client_id {client_id} "+
                  f"and name '{name}'")
        def participant_left(self, client_id, name):
            print(f"Participant left with client_id {client_id} "+
                  f"and name '{name}'")
    listener = Listener()
    return listener

def test_create_participants():
    participants = create_participants("test_create_participants")

def test_join_tcp_first():
    participants = create_participants("test_join_tcp_first")

    # Add listener
    listener = create_listener()
    participants.add_listener(listener)
    
    # Join with TCP
    client_id = 1
    client_name = "test"
    result = participants.join_tcp(client_id, client_name)
    assert result == False

    # Join with UDP
    d = participants.join_udp(client_id)

    def check_in_list(unknown):
        list_of_participants = participants.get_list()
        assert len(list_of_participants) == 1
        assert list_of_participants[0]["id"] == client_id
        assert list_of_participants[0]["name"] == client_name
    d.addCallback(check_in_list)
    
    return d

def test_join_udp_first():
    participants = create_participants("test_join_udp_first")

    # Add listener
    listener = create_listener()
    participants.add_listener(listener)
    
    # Join with UDP
    client_id = 1
    client_name = "test"
    result = participants.join_udp(client_id)
    assert result == False

    # Join with TCP
    d = participants.join_tcp(client_id, client_name)

    def check_in_list(unknown):
        list_of_participants = participants.get_list()
        assert len(list_of_participants) == 1
        assert list_of_participants[0]["id"] == client_id
        assert list_of_participants[0]["name"] == client_name
    d.addCallback(check_in_list)
    
    return d

def test_join_twice_tcp_first():
    participants = create_participants("test_join_twice_tcp_first")

    # Add listener
    listener = create_listener()
    participants.add_listener(listener)
    
    # Join with TCP
    client_id = 1
    client_name = "test"
    result = participants.join_tcp(client_id, client_name)
    assert result == False

    # Join with UDP
    d = participants.join_udp(client_id)

    def check_in_list(newly_added_entry):
        list_of_participants = participants.get_list()
        assert len(list_of_participants) == 1
        assert list_of_participants[0]["id"] == client_id
        assert list_of_participants[0]["name"] == client_name

        return newly_added_entry
    d.addCallback(check_in_list)

    # Join again with TCP without leaving first
    def join_again(newly_added_entry):
        client_name = "test"
        result = participants.join_tcp(client_id, client_name)
        assert result == False

        # Check there aren't any participants after the second join
        list_of_participants = participants.get_list()
        assert len(list_of_participants) == 0

        # Join with UDP
        d2 = participants.join_udp(client_id)
        return d2
    d.addCallback(join_again)
    d.addCallback(check_in_list)

    return d

def test_join_twice_udp_first():
    participants = create_participants("test_join_twice_udp_first")

    # Add listener
    listener = create_listener()
    participants.add_listener(listener)
    
    # Join with UDP
    client_id = 1
    client_name = "test"
    result = participants.join_udp(client_id)
    assert result == False

    # Join with TCP
    d = participants.join_tcp(client_id, client_name)

    def check_in_list(newly_added_entry):
        list_of_participants = participants.get_list()
        assert len(list_of_participants) == 1
        assert list_of_participants[0]["id"] == client_id
        assert list_of_participants[0]["name"] == client_name

        return newly_added_entry
    d.addCallback(check_in_list)

    # Join again with TCP without leaving first
    def join_again(newly_added_entry):
        client_name = "test"
        result = participants.join_udp(client_id)
        assert result == False

        # Check there aren't any participants after the second join
        list_of_participants = participants.get_list()
        assert len(list_of_participants) == 0

        # Join with UDP
        d2 = participants.join_tcp(client_id, client_name)
        return d2
    d.addCallback(join_again)
    d.addCallback(check_in_list)

    return d
