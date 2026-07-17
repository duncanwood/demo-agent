// Client-tab shim (mirror image of panel.js's origin guard: runs ONLY on our
// localhost pages — i.e. the pipecat voice-client tab). Wraps getUserMedia and
// RTCPeerConnection so the demo-page sidebar can drive the LIVE session
// deterministically — mute, mic-device switch, bot volume — independent of the
// prebuilt client UI's unlabeled, state-dependent controls.
(function () {
  if (location.origin !== "http://localhost:7860") return;
  if (window.__setMicEnabled) return;

  const streams = [];
  const gum = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async (constraints) => {
    const stream = await gum(constraints);
    streams.push(stream);
    return stream;
  };

  // Capture peer connections so a mic-device switch can replaceTrack() on the
  // live audio sender without the client app knowing or caring.
  window.__pcs = [];
  const OrigPC = window.RTCPeerConnection;
  function WrappedPC(...args) {
    const pc = new OrigPC(...args);
    window.__pcs.push(pc);
    return pc;
  }
  WrappedPC.prototype = OrigPC.prototype;
  Object.setPrototypeOf(WrappedPC, OrigPC); // statics: generateCertificate etc.
  window.RTCPeerConnection = WrappedPC;

  // Returns how many audio tracks were switched — 0 means no live mic stream
  // (e.g. permission denied); the Python side reports that honestly.
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

  window.__listMics = async () => {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices
      .filter((d) => d.kind === "audioinput" && d.deviceId)
      .map((d) => ({ id: d.deviceId, label: d.label || "Microphone" }));
  };

  // Switch the live outgoing audio to another input device: new capture,
  // replaceTrack on every live audio sender. Returns senders switched.
  window.__setMicDevice = async (deviceId) => {
    const stream = await gum({ audio: { deviceId: { exact: deviceId } } });
    streams.push(stream);
    const track = stream.getAudioTracks()[0];
    if (!track) return 0;
    let count = 0;
    for (const pc of window.__pcs) {
      for (const sender of pc.getSenders()) {
        if (sender.track && sender.track.kind === "audio") {
          await sender.replaceTrack(track);
          count += 1;
        }
      }
    }
    return count;
  };

  // Bot playback volume (0..1): the prebuilt client attaches remote audio to
  // media elements. Returns elements touched — 0 = nothing to control (yet).
  window.__setBotVolume = (v) => {
    const els = document.querySelectorAll("audio, video");
    els.forEach((el) => {
      el.volume = Math.min(1, Math.max(0, v));
    });
    return els.length;
  };
})();
