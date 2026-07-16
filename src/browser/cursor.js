// Synthetic cursor overlay (BUILD_PLAN B3).
// Injected into every page so the demo shows a visible pointer gliding to each
// element before the agent acts. Control is DOM-based; this is cosmetic.
// Exposes window.__demoCursor.moveTo(x, y) -> Promise (resolves when the glide ends).
(function () {
  if (window.__demoCursor) return;
  const dot = document.createElement("div");
  Object.assign(dot.style, {
    position: "fixed", left: "0px", top: "0px", width: "18px", height: "18px",
    borderRadius: "50%", background: "rgba(30,30,30,0.85)",
    border: "2px solid #fff", boxShadow: "0 2px 6px rgba(0,0,0,0.4)",
    zIndex: "2147483647", pointerEvents: "none",
    transform: "translate(-50%, -50%)", transition: "left .5s ease, top .5s ease",
  });
  document.documentElement.appendChild(dot);
  let x = window.innerWidth / 2, y = window.innerHeight / 2;
  dot.style.left = x + "px"; dot.style.top = y + "px";
  window.__demoCursor = {
    moveTo(nx, ny) {
      x = nx; y = ny;
      dot.style.left = nx + "px"; dot.style.top = ny + "px";
      return new Promise((r) => setTimeout(r, 520)); // matches transition
    },
    pos() { return { x, y }; },
  };
})();
