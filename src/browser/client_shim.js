// Client-tab shim (mirror image of panel.js's origin guard: runs ONLY on our
// localhost pages — i.e. the pipecat voice-client tab). Wraps getUserMedia to
// keep handles on the local media streams so the demo-page sidebar can mute or
// unmute the microphone deterministically (track.enabled), independent of the
// prebuilt client UI's unlabeled, state-dependent buttons.
(function () {
  if (location.origin !== "http://localhost:7860") return;
  if (window.__setMicEnabled) return;

  const streams = [];
  const orig = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async (constraints) => {
    const stream = await orig(constraints);
    streams.push(stream);
    return stream;
  };

  // Returns how many audio tracks were switched — 0 means no live mic stream
  // (e.g. permission denied), which the Python side reports honestly.
  window.__setMicEnabled = (on) => {
    let count = 0;
    for (const stream of streams) {
      for (const track of stream.getAudioTracks()) {
        track.enabled = !!on;
        count += 1;
      }
    }
    return count;
  };
})();
