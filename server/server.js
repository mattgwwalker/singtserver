// Listen for EventSource events, log them to the console

updateParticipants = function(event) {
    console.log(event);
    let parsed_data = JSON.parse(event.data);
    console.log(parsed_data);

    if ("participants" in parsed_data) {
	participants = parsed_data["participants"];
	
	// If there aren't any participants, state that
	if (participants.length == 0) {
	    participantsHtml =
		"<p>No-one is currently connected to this "+
		"server.  You're all on your own.  Sorry.</p>"
	}
	else {	
	    // Otherwise, form an unordered list with the names of the
	    // participants
	    participantsHtml =
		"<p>The following people are currently connected to "+
		"this server:</p><ul>"
	    for (participant of participants) {
		participantsHtml += "<li>" + participant + "</li>";
	    }
	    participantsHtml += "</ul>";
	}
	
	// Update the participants' list
	$("#participants").html(participantsHtml);
    }
    
};


// When the document has finished loading
$(document).ready(function() {
    // Connect to EventSource
    let eventSource = new EventSource('eventsource');
    eventSource.addEventListener("update_participants", updateParticipants, false);
})
