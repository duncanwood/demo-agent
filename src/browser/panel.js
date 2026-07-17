// Injected status panel (guided-UX layer, mirrors cursor.js's structure). An
// idempotent IIFE installed via context.add_init_script so it survives every
// real navigation. Renders a right-edge sidebar (or a collapsed pill) inside
// a Shadow DOM host so page CSS can never bleed in either direction: `all:
// initial` on :host blocks inherited page styles from leaking IN, and Shadow
// DOM scoping keeps this file's <style> from leaking OUT.
//
// The startup splash (controller.show_splash(), via page.set_content()) is a
// SEPARATE, duck-typed window.__demoPanel defined inline in that HTML.
// Verified empirically that set_content() does not run context init scripts
// (and leaves page.url() at "about:blank"), so this file and the splash's
// own script never coexist on one document — a real navigate() re-installs
// this file fresh on the new document, taking over the same API.
//
// API: window.__demoPanel.phase(text, state) / .hint(text) / .act(text) / .collapse(bool)
// state is "working" | "live" | "error". Calls are queued if made before the
// DOM is installed (defensive — in practice this IIFE runs to completion,
// installing synchronously, before any caller could reach these).
(function () {
  if (window.__demoPanel) return;
  // Never render on our own localhost pages (the pipecat client tab, the
  // setup page) — the panel belongs on the demo page only. Init scripts are
  // context-wide, so this is the per-page opt-out.
  if (location.origin === "http://localhost:7860") return;

  const MAX_ACTS = 6;
  const PANEL_WIDTH = 280;
  const FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    [hidden] { display: none !important; }
    .sidebar, .pill { font-family: ${FONT}; color: #e6e7ea; }
    .sidebar {
      position: fixed; top: 0; right: 0; width: 280px; height: 100vh; z-index: 2147483647;
      background: #17181c; border-left: 1px solid rgba(255,255,255,.08);
      box-shadow: -8px 0 24px rgba(0,0,0,.25); padding: 14px 16px;
      display: flex; flex-direction: column; gap: 10px;
    }
    .top { display: flex; align-items: center; justify-content: space-between; }
    .brand { font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: #7c8794; }
    .toggle { all: unset; cursor: pointer; color: #7c8794; font-size: 12px; padding: 3px 7px; border-radius: 5px; }
    .toggle:hover { background: rgba(255,255,255,.08); color: #e6e7ea; }
    .status { display: flex; align-items: center; gap: 8px; }
    .phase { font-size: 13px; font-weight: 500; }
    .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; background: #6b7280; }
    .dot.working { background: #f0a93b; animation: pulse 1.6s ease-in-out infinite; }
    .dot.live { background: #34c77b; }
    .dot.error { background: #ff5c5c; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .45; } }
    .hint { font-size: 11.5px; color: #8b8d97; }
    .seclabel { font-size: 10px; letter-spacing: .07em; text-transform: uppercase; color: #6b7280;
                padding-top: 10px; border-top: 1px solid rgba(255,255,255,.08); }
    .transcript {
      flex: 1; min-height: 60px; overflow-y: auto;
      display: flex; flex-direction: column; gap: 7px;
    }
    .t { font-size: 11.5px; line-height: 1.45; color: #c9ccd3; }
    .t .who { font-weight: 700; font-size: 10px; letter-spacing: .05em; margin-right: 5px; }
    .t.user .who { color: #6ea8fe; }
    .t.assistant .who { color: #34c77b; }
    .activity {
      max-height: 78px; overflow-y: auto; flex: none;
      display: flex; flex-direction: column; gap: 5px;
    }
    .iorow { display: flex; align-items: center; gap: 8px; font-size: 11px; color: #8b8d97; }
    .iorow select {
      flex: 1; min-width: 0; background: #101114; color: #c3c6cd; font-size: 11px;
      border: 1px solid rgba(255,255,255,.14); border-radius: 6px; padding: 4px 6px;
    }
    .iorow input[type="range"] { flex: 1; accent-color: #6ea8fe; }
    .act {
      font: 11.5px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: #a9adb8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .act:first-child { color: #d7dae0; }
    .controls { display: flex; flex-direction: column; gap: 8px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,.08); }
    .row2 { display: flex; gap: 8px; }
    .btn {
      all: unset; cursor: pointer; flex: 1; text-align: center; font-family: ${FONT};
      font-size: 12px; font-weight: 600; color: #c3c6cd; background: rgba(255,255,255,.06);
      border: 1px solid rgba(255,255,255,.14); border-radius: 7px; padding: 7px 0;
    }
    .btn:hover { background: rgba(255,255,255,.12); color: #e6e7ea; }
    .btn.muted { color: #f0a93b; border-color: rgba(240,169,59,.45); }
    .end {
      all: unset; cursor: pointer; text-align: center; font-family: ${FONT};
      font-size: 12px; font-weight: 600; color: #ffb3b3; background: rgba(255,92,92,.12);
      border: 1px solid rgba(255,92,92,.35); border-radius: 7px; padding: 7px 0;
    }
    .end:hover { background: rgba(255,92,92,.22); }
    .end[disabled] { opacity: .55; cursor: default; }
    .pill {
      position: fixed; top: 12px; right: 12px; z-index: 2147483647; cursor: pointer;
      display: flex; align-items: center; gap: 7px; font-size: 12px;
      background: #17181c; border: 1px solid rgba(255,255,255,.1); border-radius: 999px;
      padding: 7px 11px; box-shadow: 0 4px 16px rgba(0,0,0,.3);
    }
  `;

  const state = { phase: "Starting…", dotState: "working", hint: "", acts: [], collapsed: false };
  let ui = null;
  const queue = [];
  const run = (fn) => (ui ? fn() : queue.push(fn));

  function renderPhase() {
    ui.phaseEls.forEach((el) => { el.textContent = state.phase; });
    ui.dotEls.forEach((el) => { el.className = "dot " + state.dotState; });
  }
  function renderHint() {
    ui.hintEl.textContent = state.hint;
    ui.hintEl.hidden = !state.hint;
  }
  function renderActs() {
    ui.activityEl.innerHTML = "";
    for (const line of state.acts) {
      const row = document.createElement("div");
      row.className = "act";
      row.textContent = line;
      ui.activityEl.appendChild(row);
    }
  }
  function renderCollapsed() {
    ui.sidebarEl.hidden = state.collapsed;
    ui.pillEl.hidden = !state.collapsed;
    reserveLane(!state.collapsed);
  }

  let savedHtmlMargin = null;
  function reserveLane(on) {
    // The page renders full width in its own lane; the sidebar is ADDITIVE,
    // not an overlay: reserve its width on <html> while expanded. (Apps that
    // hard-position elements with 100vw/right:0 may still reach under — a
    // known limit of injecting into an arbitrary page.)
    const html = document.documentElement;
    if (on) {
      if (savedHtmlMargin === null) savedHtmlMargin = html.style.marginRight || "";
      html.style.setProperty("margin-right", PANEL_WIDTH + "px", "important");
    } else if (savedHtmlMargin !== null) {
      if (savedHtmlMargin) html.style.marginRight = savedHtmlMargin;
      else html.style.removeProperty("margin-right");
      savedHtmlMargin = null;
    }
  }

  function install() {
    const host = document.createElement("div");
    host.id = "__demo-panel-host";
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>${CSS}</style>
      <div class="sidebar" id="sidebar">
        <div class="top">
          <span class="brand">demo-agent</span>
          <button class="toggle" id="collapseBtn" title="Collapse" aria-label="Collapse">⌄</button>
        </div>
        <div class="status"><span class="dot" id="dot"></span><span class="phase" id="phaseText"></span></div>
        <div class="hint" id="hintText"></div>
        <div class="seclabel">Conversation</div>
        <div class="transcript" id="transcript"></div>
        <div class="seclabel">Agent activity</div>
        <div class="activity" id="activity"></div>
        <div class="controls">
          <div class="iorow"><span>Mic</span>
            <select id="micSel" title="Switch the live microphone"><option value="">Default</option></select>
          </div>
          <div class="iorow"><span>Vol</span>
            <input type="range" id="vol" min="0" max="100" value="100" title="Bot voice volume">
          </div>
          <div class="row2">
            <button class="btn" id="muteBtn" title="Mute or unmute your microphone">Mute mic</button>
            <button class="btn" id="audioBtn" title="Bring the live audio panel (device pickers, levels) to the front">Audio panel</button>
          </div>
          <button class="end" id="endBtn" title="End the demo and write the lead report">End demo</button>
        </div>
      </div>
      <div class="pill" id="pill" hidden title="Expand">
        <span class="dot" id="pillDot"></span>
        <span class="phase" id="pillPhase"></span>
        <span class="toggle" id="expandChevron">⌃</span>
      </div>`;
    document.documentElement.appendChild(host);

    ui = {
      sidebarEl: root.getElementById("sidebar"),
      pillEl: root.getElementById("pill"),
      dotEls: [root.getElementById("dot"), root.getElementById("pillDot")],
      phaseEls: [root.getElementById("phaseText"), root.getElementById("pillPhase")],
      hintEl: root.getElementById("hintText"),
      activityEl: root.getElementById("activity"),
      muteBtnEl: root.getElementById("muteBtn"),
      transcriptEl: root.getElementById("transcript"),
      micSelEl: root.getElementById("micSel"),
    };
    root.getElementById("collapseBtn").addEventListener("click", () => {
      state.collapsed = true;
      renderCollapsed();
    });
    ui.pillEl.addEventListener("click", () => {
      state.collapsed = false;
      renderCollapsed();
    });
    // All controls proxy to Python via the polled command QUEUE — the live
    // session (mic tracks, devices, playback) exists in the voice-client tab,
    // not here. Mute's label is set authoritatively by Python via micState()
    // after the real tracks flip, so it can never drift from reality.
    const cmd = (c) => {
      (window.__demoPanelCmds = window.__demoPanelCmds || []).push(c);
    };
    root.getElementById("muteBtn").addEventListener("click", (e) => {
      cmd("mute-toggle");
      e.target.textContent = "…";
    });
    root.getElementById("audioBtn").addEventListener("click", () => cmd("front-client"));
    ui.micSelEl.addEventListener("change", (e) => {
      if (e.target.value) cmd("mic:" + e.target.value);
    });
    root.getElementById("vol").addEventListener("change", (e) => {
      cmd("volume:" + (Number(e.target.value) / 100).toFixed(2));
    });
    root.getElementById("endBtn").addEventListener("click", (e) => {
      // Same graceful path as Ctrl-C: report written, everything closes.
      cmd("end");
      e.target.disabled = true;
      e.target.textContent = "Ending…";
      window.__demoPanel.phase("Ending — writing your report…", "working");
    });

    renderPhase();
    renderHint();
    renderActs();
    renderCollapsed();
    queue.splice(0).forEach((fn) => fn());
  }

  window.__demoPanel = {
    phase(text, dotState) {
      run(() => {
        state.phase = text == null ? "" : String(text);
        state.dotState = dotState || "working";
        renderPhase();
      });
    },
    hint(text) {
      run(() => {
        state.hint = text == null ? "" : String(text);
        renderHint();
      });
    },
    act(text) {
      run(() => {
        state.acts.unshift(text == null ? "" : String(text));
        state.acts = state.acts.slice(0, MAX_ACTS);
        renderActs();
      });
    },
    collapse(flag) {
      run(() => {
        state.collapsed = !!flag;
        renderCollapsed();
      });
    },
    micState(text) {
      run(() => {
        const muted = text === "muted";
        ui.muteBtnEl.classList.toggle("muted", muted);
        ui.muteBtnEl.textContent = muted ? "Unmute mic" : "Mute mic";
      });
    },
    turn(text, role) {
      run(() => {
        const row = document.createElement("div");
        row.className = "t " + (role === "user" ? "user" : "assistant");
        const who = document.createElement("span");
        who.className = "who";
        who.textContent = role === "user" ? "YOU" : "AGENT";
        row.appendChild(who);
        row.appendChild(document.createTextNode(text));
        ui.transcriptEl.appendChild(row);
        ui.transcriptEl.scrollTop = ui.transcriptEl.scrollHeight;
      });
    },
    micDevices(jsonText) {
      run(() => {
        let devices;
        try { devices = JSON.parse(jsonText); } catch { return; }
        const current = ui.micSelEl.value;
        ui.micSelEl.innerHTML = "";
        for (const d of devices) {
          const opt = document.createElement("option");
          opt.value = d.id;
          opt.textContent = d.label;
          ui.micSelEl.appendChild(opt);
        }
        if (current) ui.micSelEl.value = current;
      });
    },
  };

  if (document.documentElement) install();
  else document.addEventListener("DOMContentLoaded", install, { once: true });
})();
