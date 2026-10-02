/* Manage Environments modal footer — Save / Cancel.
 *
 * Split out of environments.js, which is already at this repo's 500-line
 * limit — this is self-contained enough to live on its own, relying only on
 * the $ helper (shared.js) and closeEnvModal/environmentState
 * (environments.js), both loaded as separate <script> tags before this one.
 *
 * Every field in the modal already persists on its own blur/change — these
 * buttons exist for discoverability (so the modal doesn't look like it has
 * no save path) and to give the one case that genuinely needs handling:
 * whatever field the user is still mid-edit in when they click a footer
 * button, instead of clicking away first.
 */

// Scoped to the two per-row inputs whose blur/change handlers actually
// persist a value — NOT the Bulk Edit textarea (populated by property
// assignment, so its defaultValue never reflects what's actually saved;
// discarding it would blow away the pasted JSON) and not the enabled
// checkbox or the buttons themselves (already committed on click, and
// their .value has nothing to do with the row's data).
function isCommittableEnvField(el) {
  return !!el && typeof el.matches === "function" && el.matches(".env-var-name, .env-var-value");
}

// Commits the field still focused inside the modal, same as clicking away
// would, so Save also covers "I typed a value then clicked Save" — not just
// "I typed a value then clicked elsewhere first".
function blurActiveElementWithin(container) {
  const active = document.activeElement;
  if (!active || !container.contains(active) || !isCommittableEnvField(active)) return false;
  active.blur();
  return true;
}

// Reverts the focused field to its last-rendered (== last-saved) value
// before blurring, so the native blur -> change -> save path sees no diff
// and never fires — unlike blurActiveElementWithin, this discards rather
// than commits. Relies on defaultValue tracking the last-saved value, which
// holds for every row produced by a full renderEnvEditor() rebuild; the one
// path that patches a row in place instead (createEnvVar, environments.js)
// resyncs defaultValue itself once its save lands, for the same reason.
function discardActiveElementEditWithin(container) {
  const active = document.activeElement;
  if (!active || !container.contains(active) || !isCommittableEnvField(active)) return false;
  active.value = active.defaultValue;
  active.blur();
  return true;
}

let envModalSavedFlashTimer;

// Only flashes when a field was actually mid-edit and got committed —
// e.g. clicking Save while the Bulk Edit textarea is focused can't reach
// it (isCommittableEnvField excludes it) and must not claim it did.
function saveEnvModal() {
  if (!blurActiveElementWithin($("envModal"))) return;
  const flash = $("envModalSavedFlash");
  flash.classList.remove("hidden");
  clearTimeout(envModalSavedFlashTimer);
  envModalSavedFlashTimer = setTimeout(() => flash.classList.add("hidden"), 2200);
}

function cancelEnvModal() {
  discardActiveElementEditWithin($("envModal"));
  closeEnvModal();
}

document.addEventListener("DOMContentLoaded", () => {
  $("envModalSaveBtn").addEventListener("click", saveEnvModal);
  $("envModalCancelBtn").addEventListener("click", cancelEnvModal);
  // Without this, the mousedown that precedes the click would itself shift
  // focus to the button first — so by the time saveEnvModal/cancelEnvModal
  // runs, document.activeElement is the button, not the field being edited,
  // and blurActiveElementWithin/discardActiveElementEditWithin silently do
  // nothing.
  $("envModalSaveBtn").addEventListener("mousedown", (event) => event.preventDefault());
  $("envModalCancelBtn").addEventListener("mousedown", (event) => event.preventDefault());
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = { blurActiveElementWithin, discardActiveElementEditWithin };
}
