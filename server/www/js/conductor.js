// Create single namespace
window.SINGT = {};


SINGT.wireup = function(){
    //all wireup goes here

    console.log('wiring up!');
    SINGT.wireup.nav();
    SINGT.wireup.eventsource();
    SINGT.wireup.forms();
    SINGT.wireup.page_tracks();
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
    //check for hash
    var hash = window.location.hash || '#page_tracks';
    hash = hash.split('/')[0]; //allow for splitting has h for multiple uses
    $('a[href="'+hash+'"]').click();
    
}

SINGT.wireup.eventsource = function(){
    let eventSource = new EventSource('eventsource');
    eventSource.addEventListener("update_participants", SINGT.participants.update, false);
};

SINGT.wireup.page_tracks = function(){
    // Ensures that any use of Bootstrap's custom file selector
    // updates the filename when the user selects a file.
    $('.custom-file-input').on('change', function() { 
	let fileName = $(this).val().split('\\').pop(); 
	$(this).next('.custom-file-label').addClass("selected").html(fileName); 
    });
};

SINGT.wireup.forms = function() {
    // Connect backing track upload button
    $("#backing_track_upload").click(SINGT.tracks.upload);

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

SINGT.tracks = {};

SINGT.tracks.upload = function() {
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
$(document).ready(function(){
    SINGT.wireup();
})
