// Drag-to-resize for fixed-size panels that had no way to reclaim space:
// the response panels (Console's #respSingle, Runner's #runnerResp, both
// pinned at panel.css's .resp{height:44%}) and the collection sidebar
// (#collectionSidebar, pinned at .side{width:260px}). Size is stored in px
// (not %) once dragged, so a window resize doesn't fight the user's chosen
// split; persisted per target so each panel remembers its own size.
const RESIZE_STORAGE_PREFIX = "iris.panelSize.";
const RESIZE_MIN_PX = 120;

// Some targets (e.g. #runnerResp, styled `flex:1` so it fills whatever
// space is left) have flex-basis:0 from that shorthand — under flex-basis:0,
// flex-grow distributes space by ratio and an explicit height/width on the
// item is simply ignored, so setting only .style.height did nothing there
// (Console's #respSingle worked because .resp is flex:0 0 auto to begin
// with). Forcing flex to "0 0 auto" here makes an explicit size stick
// regardless of whatever flex-grow the target's own CSS class set.
function applyPanelSize(target, axis, px) {
  target.style.flex = "0 0 auto";
  target.style[axis === "x" ? "width" : "height"] = `${px}px`;
}

function restorePanelSize(target, axis) {
  const stored = localStorage.getItem(RESIZE_STORAGE_PREFIX + target.id);
  if (stored) applyPanelSize(target, axis, stored);
}

function wireResizeHandle(handle) {
  const target = document.getElementById(handle.dataset.resizeTarget);
  if (!target) return;
  const axis = handle.dataset.resizeAxis || "y";
  restorePanelSize(target, axis);

  handle.addEventListener("mousedown", (event) => {
    event.preventDefault();
    const container = target.parentElement;
    const startPos = axis === "x" ? event.clientX : event.clientY;
    const startSize = axis === "x" ? target.getBoundingClientRect().width : target.getBoundingClientRect().height;
    handle.classList.add("dragging");
    document.body.style.cursor = axis === "x" ? "ew-resize" : "ns-resize";

    function onMouseMove(moveEvent) {
      const pos = axis === "x" ? moveEvent.clientX : moveEvent.clientY;
      // Sidebar (x axis): dragging right grows it, so delta = pos - start.
      // Response panel (y axis): dragging up grows it, so delta = start - pos.
      const delta = axis === "x" ? pos - startPos : startPos - pos;
      const containerSize = axis === "x"
        ? container.getBoundingClientRect().width
        : container.getBoundingClientRect().height;
      // `containerSize - RESIZE_MIN_PX` assumes there's always at least
      // RESIZE_MIN_PX worth of sibling content the target could take space
      // from. Not true for #runnerResp — it's `flex:1` (already filling
      // 100% of whatever's left; its siblings there are fixed-height, not
      // themselves compressible, unlike Console's editor). When siblings
      // there take up LESS than RESIZE_MIN_PX, that formula produced a
      // ceiling BELOW the panel's current size — so even an upward
      // (grow) drag snapped it smaller on the very first pixel of movement,
      // which is exactly what looked like "resize doesn't work". Flooring
      // the ceiling at startSize means growing past the natural maximum is
      // a harmless no-op instead, while shrinking still works down to
      // RESIZE_MIN_PX as before.
      const maxSize = Math.max(containerSize - RESIZE_MIN_PX, RESIZE_MIN_PX, startSize);
      const nextSize = Math.min(Math.max(startSize + delta, RESIZE_MIN_PX), maxSize);
      applyPanelSize(target, axis, nextSize);
    }
    function onMouseUp() {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      handle.classList.remove("dragging");
      document.body.style.cursor = "";
      const finalSize = axis === "x"
        ? target.getBoundingClientRect().width
        : target.getBoundingClientRect().height;
      localStorage.setItem(RESIZE_STORAGE_PREFIX + target.id, Math.round(finalSize));
    }
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-resize-target]").forEach(wireResizeHandle);
});
