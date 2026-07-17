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

  const MAX_ACTS = 6;
  const CLIENT_URL = "http://localhost:7860/client/";
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
    .activity {
      flex: 1; min-height: 0; overflow-y: auto; margin-top: 2px; padding-top: 10px;
      border-top: 1px solid rgba(255,255,255,.08); display: flex; flex-direction: column; gap: 5px;
    }
    .act {
      font: 11.5px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: #a9adb8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .act:first-child { color: #d7dae0; }
    .footer {
      font-size: 11.5px; color: #6ea8fe; text-decoration: none;
      padding-top: 8px; border-top: 1px solid rgba(255,255,255,.08);
    }
    .footer:hover { text-decoration: underline; }
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
        <div class="activity" id="activity"></div>
        <a class="footer" id="audioLink" href="${CLIENT_URL}" target="_blank" rel="noopener noreferrer">Audio settings ↗</a>
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
    };
    root.getElementById("collapseBtn").addEventListener("click", () => {
      state.collapsed = true;
      renderCollapsed();
    });
    ui.pillEl.addEventListener("click", () => {
      state.collapsed = false;
      renderCollapsed();
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
  };

  if (document.documentElement) install();
  else document.addEventListener("DOMContentLoaded", install, { once: true });
})();
