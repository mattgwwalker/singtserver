// Listen for EventSource events, log them to the console

alert("Processing Javascript");

var source = new EventSource('eventsource');
source.onmessage = function (event) {
  alert(event.data);
};
