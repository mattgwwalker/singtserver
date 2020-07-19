// Handle EventSource event 'update_participants' 
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


// Handle uploading of backing track
uploadBackingTrack = function() {
    console.log("Uploading backing track")

    let formData = new FormData();
    formData.append("command", "upload_backing_track");
    formData.append("name", $("#backing_track_name").val());
    formData.append("file", $("#backing_track_file").get(0).files[0]);
    
    $.ajax({
        url: 'backing_track',
        type: 'POST',
        data: formData,
	dataType: "json",
	processData: false,
	mimeType: 'multipart/form-data',
	contentType: false,
	cache: false,
        success: function(msg) {
	    console.log(msg);
	    if ("result" in msg) {
		if (msg["result"]=="error") {
		    reason = msg["reason"]
		    alert("Error: "+reason);
		}
	    }
	    else {
		alert('Backing track added successfully');
	    }
        },
	error: function(jqXHR, st, error) {
            // Hopefully we should never reach here
            //console.log(jqXHR);
            //console.log(st);
            console.log("error:",error);
	    //console.log("status:",st);
	    alert("FAILED to send backing track file");
	}
    });
}


// When the document has finished loading
$(document).ready(function() {
    // Connect to EventSource
    let eventSource = new EventSource('eventsource');
    eventSource.addEventListener("update_participants", updateParticipants, false);

    // Connect backing track upload button
    $("#backing_track_upload").click(uploadBackingTrack);
})
