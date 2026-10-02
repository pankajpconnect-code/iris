// Autocomplete: (1) predefined header-key suggestions, (2) a `{{var}}`
// dropdown showing each candidate's current value — for the URL input,
// header-value inputs, and the body editor. Both share one styled dropdown
// renderer so they look/behave the same way.
// Standard HTTP request header field names (IANA HTTP Field Name Registry /
// MDN), plus the couple of domain-specific ones this API actually uses
// (x-tenant-identifier, User).
const COMMON_HEADER_NAMES = [
  "Accept", "Accept-Charset", "Accept-Datetime", "Accept-Encoding", "Accept-Language",
  "Authorization", "Cache-Control", "Connection", "Content-Encoding", "Content-Language",
  "Content-Length", "Content-MD5", "Content-Type", "Cookie", "Date", "DNT", "Expect",
  "Forwarded", "From", "Host", "If-Match", "If-Modified-Since", "If-None-Match", "If-Range",
  "If-Unmodified-Since", "Max-Forwards", "Origin", "Pragma", "Proxy-Authorization", "Range",
  "Referer", "TE", "Trailer", "Transfer-Encoding", "Upgrade", "User-Agent", "Via", "Warning",
  "X-Api-Key", "X-Correlation-Id", "X-CSRF-Token", "X-Forwarded-For", "X-Forwarded-Host",
  "X-Forwarded-Proto", "X-Request-Id", "X-Requested-With",
  "x-tenant-identifier", "User",
];

function knownVariableEntries() {
  const envVars = (typeof activeEnvironmentVars === "function") ? activeEnvironmentVars() : {};
  // Broader than the Vars TAB's display (which is scoped to the selected
  // request) — autocomplete's job is helping you discover/insert ANY variable
  // used anywhere in the collection, even one you haven't given a value yet.
  const collectionNames = (typeof collectionVarNames === "function")
    ? [...collectionVarNames(consoleState.selectedCollection)] : [];
  const names = new Set([...collectionNames, ...Object.keys(consoleState.vars || {}), ...Object.keys(envVars)]);
  return [...names].sort().map((name) => ({
    name,
    value: Object.prototype.hasOwnProperty.call(envVars, name) ? envVars[name] : (consoleState.vars[name] || ""),
  }));
}

// Real mouse-hover preview of a SINGLE {{var}} token — distinct from the
// dropdown above, which only shows a value while a token is being typed.
// Secret-named vars are masked the same way environments.js's Vars tab
// already treats them (never shown, even to their own owner — see
// SECRET_NAME_PATTERN there); a long value is truncated the same way the
// dropdown above already truncates its own sublabel.
function varValueLabel(name) {
  const entry = knownVariableEntries().find((candidate) => candidate.name === name);
  if (!entry || entry.value === "") return `${name} = (not set)`;
  if (SECRET_NAME_PATTERN.test(name)) return `${name} = ••••••`;
  const value = String(entry.value);
  return `${name} = ${value.length > 30 ? `${value.slice(0, 30)}…` : value}`;
}

// The `.body-var-token` span whose rendered box contains (x, y), or null if
// none does — i.e. exactly the token under the mouse, not "any token
// anywhere in the field". `overlay` is the highlight layer (see
// renderVarHighlight below) sitting behind `el`; `el` itself sits on top and
// would otherwise be all elementFromPoint ever hits, since it owns the real
// (transparent) text and receives every pointer event. Both pointer-events
// are flipped only for the duration of this one lookup — same tick, no
// paint in between — so neither ever actually receives a stray click.
function varTokenNameAtPoint(el, overlay, x, y) {
  const elPointerEvents = el.style.pointerEvents;
  const overlayPointerEvents = overlay.style.pointerEvents;
  el.style.pointerEvents = "none";
  overlay.style.pointerEvents = "auto";
  const hit = document.elementFromPoint(x, y);
  el.style.pointerEvents = elPointerEvents;
  overlay.style.pointerEvents = overlayPointerEvents;
  const span = hit && hit.closest && hit.closest(".body-var-token");
  const match = span && /^\{\{(.+)\}\}$/.exec(span.textContent);
  return match ? match[1] : null;
}

// A custom floating box rather than the native `title` attribute — this app
// runs in an embedded WKWebView where native title tooltips don't reliably
// render, so the preview has to be drawn in the page itself.
let hoverTooltipEl = null;

function hideVarHoverTooltip() {
  if (hoverTooltipEl) hoverTooltipEl.remove();
  hoverTooltipEl = null;
}

// Positioned at the cursor, not the field's own box — bodyEditor is a tall,
// wide textarea, so anchoring to its bounding rect (or to wherever the mouse
// happened to be on a single "mouseenter" firing at whatever edge it was
// entered from) would leave the tooltip stuck far from wherever the mouse
// actually ends up. Updates the same element's position/text in place on
// every "mousemove" instead, so it tracks the cursor properly.
function showVarHoverTooltip(x, y, text) {
  if (!hoverTooltipEl) {
    hoverTooltipEl = document.createElement("div");
    hoverTooltipEl.className = "var-hover-tooltip";
    document.body.appendChild(hoverTooltipEl);
  }
  hoverTooltipEl.textContent = text;
  hoverTooltipEl.style.left = `${x + window.scrollX}px`;
  hoverTooltipEl.style.top = `${y + window.scrollY + 16}px`;
}

function attachVarHoverPreview(el, overlay) {
  el.addEventListener("mousemove", (event) => {
    const name = varTokenNameAtPoint(el, overlay, event.clientX, event.clientY);
    if (name) showVarHoverTooltip(event.clientX, event.clientY, varValueLabel(name));
    else hideVarHoverTooltip();
  });
  el.addEventListener("mouseleave", hideVarHoverTooltip);
}

// Colors {{var}} tokens inline (the same convention commercial API clients
// use) for a single-line field — highlightVarTokens is body-editor.js's,
// reused as-is since a URL/header
// value never needs the JSON-specific coloring highlightJson layers on top
// of it for the body. `overlay` is the sibling div panel.css positions
// behind `el` (see .var-input-wrap) — el's own text is made transparent so
// only the overlay's colored spans are visible, and it's also what
// varTokenNameAtPoint hit-tests against for the hover preview above.
function renderVarHighlight(el, overlay) {
  overlay.innerHTML = highlightVarTokens(el.value);
  overlay.scrollLeft = el.scrollLeft;
}

// A single-line input scrolls its text horizontally once the caret moves
// past the visible edge — the overlay must track that scroll position too,
// or (now that the input's own text is transparent) whatever's visible
// stops matching the caret once the value overflows the field's width.
// "scroll" alone isn't reliably fired by every engine, so it's paired with
// the two other ways scrollLeft can change without an "input" event: caret
// navigation (keyup) and clicking to reposition the caret (click).
function syncVarHighlightScroll(el, overlay) {
  overlay.scrollLeft = el.scrollLeft;
}

function attachVarHighlight(el, overlay) {
  renderVarHighlight(el, overlay);
  el.addEventListener("input", () => renderVarHighlight(el, overlay));
  el.addEventListener("scroll", () => syncVarHighlightScroll(el, overlay));
  el.addEventListener("keyup", () => syncVarHighlightScroll(el, overlay));
  el.addEventListener("click", () => syncVarHighlightScroll(el, overlay));
  attachVarHoverPreview(el, overlay);
}

// Whenever something sets $("url").value directly (tab switch, new tab,
// Duplicate, curl import) rather than through user typing, no "input" event
// fires, so the overlay above would keep showing stale/empty text while the
// input's own (transparent) text silently held the real value — the same
// staleness renderBodyHighlight() is already called for after tabs.js sets
// $("bodyEditor").value directly. Callers making a bare non-typed url.value
// assignment must call this too.
function renderUrlHighlight() {
  const overlay = $("urlHighlight");
  if (overlay) renderVarHighlight($("url"), overlay);
}

let acDropdown = null;
let acTarget = null;

function closeDropdown() {
  if (acDropdown) acDropdown.remove();
  acDropdown = null;
  acTarget = null;
}

// `rows` is [{label, sublabel, onPick}] — onPick applies the choice to `el`.
function renderDropdown(el, rows) {
  closeDropdown();
  if (!rows.length) return;
  acTarget = el;
  const rect = el.getBoundingClientRect();
  const box = document.createElement("div");
  box.className = "var-autocomplete";
  box.style.left = `${rect.left + window.scrollX}px`;
  box.style.top = `${rect.bottom + window.scrollY + 2}px`;
  box.style.minWidth = `${Math.min(rect.width, 260)}px`;
  for (const { label, sublabel, onPick } of rows) {
    const row = document.createElement("div");
    row.className = "var-autocomplete-row";
    row.innerHTML = `<span class="var-autocomplete-name">${escapeHtml(label)}</span>` +
      (sublabel ? `<span class="var-autocomplete-value">${escapeHtml(sublabel)}</span>` : "");
    row.addEventListener("mousedown", (event) => {
      event.preventDefault();
      onPick();
      closeDropdown();
    });
    box.appendChild(row);
  }
  document.body.appendChild(box);
  acDropdown = box;
}

function applyPick(el, replaceStart, replaceEnd, text) {
  const before = el.value.slice(0, replaceStart);
  const after = el.value.slice(replaceEnd);
  el.value = before + text + after;
  const cursor = before.length + text.length;
  el.setSelectionRange(cursor, cursor);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.focus();
}

function openVarDropdown(el, partial, replaceStart, replaceEnd) {
  const partialLower = partial.toLowerCase();
  const matches = knownVariableEntries().filter((v) => v.name.toLowerCase().startsWith(partialLower)).slice(0, 8);
  renderDropdown(el, matches.map((entry) => ({
    label: entry.name,
    sublabel: entry.value ? String(entry.value).slice(0, 30) : "",
    onPick: () => applyPick(el, replaceStart, replaceEnd, `{{${entry.name}}}`),
  })));
}

function handleVarAutocompleteInput(event) {
  const el = event.target;
  const cursor = el.selectionStart;
  const before = el.value.slice(0, cursor);
  const match = before.match(/\{\{([\w.-]*)$/);
  if (!match) {
    if (acTarget === el) closeDropdown();
    return;
  }
  openVarDropdown(el, match[1], cursor - match[0].length, cursor);
}

function openHeaderKeyDropdown(el) {
  const partial = el.value.toLowerCase();
  const matches = COMMON_HEADER_NAMES.filter((name) => name.toLowerCase().includes(partial)).slice(0, 8);
  renderDropdown(el, matches.map((name) => ({
    label: name,
    sublabel: "",
    onPick: () => applyPick(el, 0, el.value.length, name),
  })));
}

function attachVarAutocomplete(el) {
  el.addEventListener("input", handleVarAutocompleteInput);
  el.addEventListener("blur", () => setTimeout(() => { if (acTarget === el) closeDropdown(); }, 150));
  el.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && acTarget === el) closeDropdown();
  });
}

function attachHeaderKeyAutocomplete(el) {
  el.addEventListener("input", () => openHeaderKeyDropdown(el));
  el.addEventListener("focus", () => openHeaderKeyDropdown(el));
  el.addEventListener("blur", () => setTimeout(() => { if (acTarget === el) closeDropdown(); }, 150));
  el.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && acTarget === el) closeDropdown();
  });
}

// Header rows are created dynamically (addHeaderRow) — attach lazily via
// focus-in delegation on the container instead of per-row wiring.
const _autocompleteAttached = new WeakSet();
function attachOnce(el, attachFn) {
  if (_autocompleteAttached.has(el)) return;
  _autocompleteAttached.add(el);
  attachFn(el);
}

document.addEventListener("DOMContentLoaded", () => {
  attachVarAutocomplete($("url"));
  attachVarHighlight($("url"), $("urlHighlight"));
  attachVarAutocomplete($("bodyEditor"));
  attachVarHoverPreview($("bodyEditor"), $("bodyHighlight")); // body already highlights its own {{var}} tokens — see body-editor.js
  $("headersList").addEventListener("focusin", (event) => {
    if (event.target.classList.contains("hdr-value")) attachOnce(event.target, attachVarAutocomplete);
    if (event.target.classList.contains("hdr-key")) attachOnce(event.target, attachHeaderKeyAutocomplete);
  });
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = { varValueLabel, renderVarHighlight };
}
