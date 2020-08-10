// Create single namespace
window.SINGT = {};


SINGT.wireup = function(){
    // All wireup goes here
    SINGT.wireup.nav();
    SINGT.wireup.eventsource();
    SINGT.wireup.forms();
    SINGT.wireup.page_tracks();
    SINGT.wireup.page_playback();
}

SINGT.wireup.nav = function() {
    $('.navbar-nav .nav-link').each(function(index){
        $(this).bind('click', function(){
            //change classes of nav buttons
            $('.navbar-nav .nav-item').removeClass('active');
            $(this).parent().addClass('active');
            //hide other pages show target page
            var target_id = $(this).attr('href');
            $('.page').removeClass('show');
            $(target_id).addClass('show');
        })
    });
    // Check for hash symbol in address
    var hash = window.location.hash || '#page_tracks';
    hash = hash.split('/')[0]; //allow for splitting has h for multiple uses
    $('a[href="'+hash+'"]').click();
    
}

SINGT.wireup.eventsource = function(){
    let eventSource = new EventSource('eventsource');
    eventSource.addEventListener("update_participants", SINGT.participants.update, false);
    eventSource.addEventListener("update_backing_tracks", SINGT.backing_tracks.update, false);
};

SINGT.wireup.page_tracks = function(){
    // Ensures that any use of Bootstrap's custom file selector
    // updates the filename when the user selects a file.
    $('.custom-file-input').on('change', function() { 
	let fileName = $(this).val().split('\\').pop(); 
	$(this).next('.custom-file-label').addClass("selected").html(fileName); 
    });
};

SINGT.wireup.page_playback = function(){
    $("#playback_button_play").click(function() {
        console.log("Playback button clicked");

        // Get state of combo selection
        var combo_selection = undefined
        if ($("#playback_combo_track_only").is(":checked")) {
            combo_selection = "track_only";
        } else if ($("#playback_combo_mix").is(":checked")) {
            combo_selection = "mix";
        } else if ($("#playback_combo_takes_only").is(":checked")) {
            combo_selection = "takes_only";
        }
        console.log("combo_selection:", combo_selection);

        // Get selected track
        track = $("#playback_select_tracks").val();
        console.log("track:", track);

        // Get selected takes
        takes = $("#playback_multiselect_takes").val()
        console.log("takes:", takes);

        // Form command
        command = {
            "command": "play_for_everyone"
        }
        if (combo_selection=="track_only" ||
            combo_selection=="mix") {
            command["track_id"] = track;
        }
        if (combo_selection=="mix" ||
            combo_selection=="takes_only") {
            command["take_ids"] = takes;
        }
        json_command = JSON.stringify(command);
        
        // Send command
        console.log("command:", command);
        $.ajax({
            type: 'POST',
            url: 'command',
            data: json_command,
            dataType: "json",
            contentType: "application/json",
            success: function(msg) {
                console.log(msg);
            },
            error: function(jqXHR, st, error) {
                // Hopefully we should never reach here
                alert("FAILED to send command 'play_for_everyone'");
            }
        });

        return false; // Do not reload page
    });

    $("#playback_button_stop").click(function() {
        console.log("Stop button clicked");

        // Form command
        command = {
            "command": "stop_for_everyone"
        }
        json_command = JSON.stringify(command);
        
        // Send command
        console.log("command:", command);
        $.ajax({
            type: 'POST',
            url: 'command',
            data: json_command,
            dataType: "json",
            contentType: "application/json",
            success: function(msg) {
                console.log(msg);
            },
            error: function(jqXHR, st, error) {
                // Hopefully we should never reach here
                alert("FAILED to send command 'stop_for_everyone'");
            }
        });

        return false; // Do not reload page
    });    
};

SINGT.wireup.forms = function() {
    // Connect backing track upload button
    $("#backing_track_upload").click(SINGT.backing_tracks.upload);

    $("#show_upload_form").click(function(){
        $(this).parent().addClass('d-none');
        $("#upload_form").removeClass('d-none');
    })
    $("#backing_track_cancel").click(function(){
        $("#show_upload_form").parent().removeClass('d-none');
        $("#upload_form").addClass('d-none');
    })
}

SINGT.participants = {};
SINGT.participants.update = function() {
    console.log(event);
    let parsed_data = JSON.parse(event.data);
    console.log(parsed_data);

    if ("participants" in parsed_data) {
        participants = parsed_data["participants"];
        
        $('#participants').addClass('d-none');
        $('#no_participants').addClass('d-none');
        $('#nav-participants').addClass('d-none');
        

        // If there aren't any participants, state that
        if (participants.length == 0) {
            $('#no_participants').removeClass('d-none');
        } else {	
            // Otherwise, form an unordered list with the names of the
            // participants
            let participantsHtml = '';
            for (participant of participants) {
                participantsHtml += '<li class="list-group-item"><img src="./icons/person-badge.svg" alt="" width="32" height="32" title="Person" class="mr-2">' + participant + '</li>';
            }
            $("#participants").html(participantsHtml).removeClass('d-none');
            $('#nav-participants').text(participants.length).removeClass('d-none');
        }
    } else {
        console.error('Dude, wheres my car?');
    }
    
};

SINGT.backing_tracks = {};

SINGT.backing_tracks.upload = function() {
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
		else if (msg["result"]=="success") {
		    alert("Successfully uploaded backing track");
		}
		else {
		    alert("Unexpected response from server:"+msg)
		}
            } else {
                alert("Unexpected response from server:"+msg)
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

    return false;
}

SINGT.backing_tracks.update = function() {
    let parsed_data = JSON.parse(event.data);

    if (parsed_data.length == 0) {
        // There are zero entries in the list of backing tracks
        $('#zero_tracks').removeClass('d-none');
        $('#backing_tracks').addClass('d-none');

        let optionsHtml = '<option value="-1">No tracks uploaded</option>';
        $("#recording_select_tracks").html(optionsHtml).removeClass('d-none');
        $("#playback_select_tracks").html(optionsHtml).removeClass('d-none');
        return
    } 

    // There are more than zero entries in the list of backing tracks
    $('#zero_tracks').addClass('d-none');
    $('#backing_tracks').removeClass('d-none');
    let tracksHtml = '';
    let optionsHtml = '';

    // Go through each of the entries and add in a row to the tracks
    // pages, the recording page, and the playback page
    for (track_entry of parsed_data) {
        track_id = track_entry[0]
        track_name = track_entry[1]
        
        tracksHtml += '<li class="list-group-item"><img src="./icons/file-music.svg" alt="" width="32" height="32" title="Track" class="mr-2">' + track_name + '</li>';

        optionsHtml += '<option value="'+track_id+'">'+track_name+'</option>'
    }
    $("#backing_tracks").html(tracksHtml).removeClass('d-none');
    $("#recording_select_tracks").html(optionsHtml).removeClass('d-none');
    $("#playback_select_tracks").html(optionsHtml).removeClass('d-none');
};



$(document).ready(function(){
    SINGT.wireup();
})
