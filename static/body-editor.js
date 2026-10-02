// JSON body editor: a transparent textarea layered over a
// syntax-highlighted <pre>, kept in sync on every keystroke and scroll.
// Written from scratch rather than pulling in a code-editor library — this
// project has no build step/bundler, so a dependency would mean vendoring a
// large file by hand for a feature this narrow (this textarea only ever holds
// JSON request bodies).
const JSON_TOKEN_PATTERN = /"(?:\\.|[^"\\])*"|\btrue\b|\bfalse\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;
const BODY_VAR_TOKEN_PATTERN = /\{\{[^{}]+\}\}/g;

function jsonTokenClass(token, followedByColon) {
  if (token[0] === '"') return followedByColon ? "json-key" : "json-string";
  if (token === "true" || token === "false") return "json-boolean";
  if (token === "null") return "json-null";
  return "json-number";
}

function wrapSpan(text, className) {
  return text ? `<span class="${className}">${highlightVarTokens(text)}</span>` : "";
}

// Splits rawText (a chunk of the ORIGINAL source at absoluteStart) around
// its overlap with activeRange, wrapping only the overlapping slice in
// <mark>. toHtml renders each of the up-to-three pieces the same way the
// caller would have rendered the whole chunk, so token pieces keep their
// span/class and plain-text pieces stay escaped-only.
function emitChunk(rawText, absoluteStart, toHtml, activeRange) {
  if (!activeRange) return toHtml(rawText);
  const relStart = Math.max(activeRange.start - absoluteStart, 0);
  const relEnd = Math.min(activeRange.end - absoluteStart, rawText.length);
  if (relStart >= relEnd) return toHtml(rawText);
  const pre = rawText.slice(0, relStart);
  const mid = rawText.slice(relStart, relEnd);
  const post = rawText.slice(relEnd);
  return `${toHtml(pre)}<mark class="body-find-active">${toHtml(mid)}</mark>${toHtml(post)}`;
}

// Same contract as escapeHtml (raw text in, escaped HTML out) — this used
// to run as a single global regex pass over the already-assembled HTML
// instead, which was only safe as long as nothing else ever injected a tag
// between a {{ and its }}. Once emitChunk started splitting tokens with
// <mark>, that regex could bridge across the inserted tag and capture a
// stray closing </span> from inside its own match, corrupting tag nesting.
// Running per-chunk on raw text — the same way JSON token splitting works —
// means a split {{var}} just loses its color instead of breaking the DOM.
function highlightVarTokens(text) {
  let result = "";
  let lastIndex = 0;
  BODY_VAR_TOKEN_PATTERN.lastIndex = 0;
  let match;
  while ((match = BODY_VAR_TOKEN_PATTERN.exec(text))) {
    result += escapeHtml(text.slice(lastIndex, match.index));
    result += `<span class="body-var-token">${escapeHtml(match[0])}</span>`;
    lastIndex = BODY_VAR_TOKEN_PATTERN.lastIndex;
  }
  return result + escapeHtml(text.slice(lastIndex));
}

function highlightJson(text, activeRange) {
  let result = "";
  let lastIndex = 0;
  JSON_TOKEN_PATTERN.lastIndex = 0;
  let match;
  while ((match = JSON_TOKEN_PATTERN.exec(text))) {
    const tokenStart = match.index;
    result += emitChunk(text.slice(lastIndex, tokenStart), lastIndex, highlightVarTokens, activeRange);
    lastIndex = JSON_TOKEN_PATTERN.lastIndex;
    const followedByColon = match[0][0] === '"' && /^\s*:/.test(text.slice(lastIndex));
    const className = jsonTokenClass(match[0], followedByColon);
    result += emitChunk(match[0], tokenStart, (piece) => wrapSpan(piece, className), activeRange);
  }
  result += emitChunk(text.slice(lastIndex), lastIndex, highlightVarTokens, activeRange);
  return result;
}

// --- find / replace (plain-text, case-insensitive; no editor library) ---

function findMatches(text, query) {
  if (!query) return [];
  const haystack = text.toLowerCase();
  const needle = query.toLowerCase();
  const indices = [];
  let from = 0;
  let idx;
  while ((idx = haystack.indexOf(needle, from)) !== -1) {
    indices.push(idx);
    from = idx + needle.length;
  }
  return indices;
}

function replaceAtIndex(text, index, matchLength, replacement) {
  return text.slice(0, index) + replacement + text.slice(index + matchLength);
}

function replaceAllMatches(text, query, replacement) {
  const indices = findMatches(text, query);
  if (!indices.length) return text;
  let result = "";
  let cursor = 0;
  for (const idx of indices) {
    result += text.slice(cursor, idx) + replacement;
    cursor = idx + query.length;
  }
  return result + text.slice(cursor);
}

function renderBodyHighlight() {
  const code = document.querySelector("#bodyHighlight code");
  if (!code) return;
  code.innerHTML = highlightJson($("bodyEditor").value, activeFindHighlightRange());
  renderBodyLineGutter();
}

// The body text is only ever visible via this highlight overlay (the
// textarea's own text is transparent — see panel.css), so the active find
// match has to be marked up here rather than via textarea selection, which
// would be invisible while the find input holds keyboard focus.
function activeFindHighlightRange() {
  if ($("bodyFindBar").classList.contains("hidden")) return null;
  if (findState.activeIndex < 0) return null;
  const start = findState.matches[findState.activeIndex];
  return { start, end: start + findState.query.length };
}

function renderBodyLineGutter() {
  const gutter = $("bodyLineGutter");
  if (!gutter) return;
  const lineCount = $("bodyEditor").value.split("\n").length;
  gutter.textContent = Array.from({ length: lineCount }, (_, i) => i + 1).join("\n");
}

function syncBodyScroll() {
  $("bodyHighlight").scrollTop = $("bodyEditor").scrollTop;
  $("bodyHighlight").scrollLeft = $("bodyEditor").scrollLeft;
  $("bodyLineGutter").scrollTop = $("bodyEditor").scrollTop;
}

function beautifyBody() {
  const textarea = $("bodyEditor");
  const errorEl = $("bodyJsonError");
  if (!textarea.value.trim()) { errorEl.classList.add("hidden"); return; }
  try {
    textarea.value = JSON.stringify(JSON.parse(textarea.value), null, 2);
    errorEl.classList.add("hidden");
    renderBodyHighlight();
    markActiveTabDirty();
  } catch (error) {
    errorEl.textContent = `Invalid JSON: ${error.message}`;
    errorEl.classList.remove("hidden");
  }
}

// --- find / replace UI (the active match is marked up inside
// highlightJson's own output — see emitChunk — since the textarea's text is
// transparent; native textarea selection alone would be invisible whenever
// the find input, not the textarea, holds keyboard focus) ---

let findState = { matches: [], activeIndex: -1, query: "" };

function renderFindCount() {
  const el = $("bodyFindCount");
  el.textContent = findState.matches.length
    ? `${findState.activeIndex + 1}/${findState.matches.length}`
    : ($("bodyFindInput").value ? "0/0" : "");
}

function refreshFindMatches() {
  findState.query = $("bodyFindInput").value;
  findState.matches = findMatches($("bodyEditor").value, findState.query);
  if (findState.activeIndex >= findState.matches.length) findState.activeIndex = findState.matches.length - 1;
  if (findState.matches.length && findState.activeIndex < 0) findState.activeIndex = 0;
  renderFindCount();
}

// Deliberately does not call textarea.focus() — this runs on every keystroke
// in the find input, and focusing the textarea would steal focus away from
// it, causing the next typed character to land in the textarea and
// overwrite the just-selected match instead of extending the search query.
function selectFindMatch(textarea, matchStart, queryLength) {
  textarea.setSelectionRange(matchStart, matchStart + queryLength);
}

// setSelectionRange alone doesn't scroll an unfocused textarea (the find
// input holds focus, not the body — see selectFindMatch above), so a match
// outside the current viewport is selected but never seen. Approximates one
// visual row per \n, the same tradeoff renderBodyLineGutter already makes
// (panel.css's line-gutter comment) rather than pulling in a line-height-
// measuring editor.
function scrollMatchIntoView(textarea, matchStart) {
  const lineNumber = textarea.value.slice(0, matchStart).split("\n").length - 1;
  const lineHeight = parseFloat(getComputedStyle(textarea).lineHeight);
  const matchTop = lineNumber * lineHeight;
  const matchBottom = matchTop + lineHeight;
  if (matchTop < textarea.scrollTop) {
    textarea.scrollTop = matchTop;
  } else if (matchBottom > textarea.scrollTop + textarea.clientHeight) {
    textarea.scrollTop = matchBottom - textarea.clientHeight;
  }
}

function selectActiveFindMatch() {
  renderBodyHighlight();
  if (findState.activeIndex < 0) return;
  const start = findState.matches[findState.activeIndex];
  const textarea = $("bodyEditor");
  selectFindMatch(textarea, start, findState.query.length);
  scrollMatchIntoView(textarea, start);
}

function goToFindMatch(delta) {
  if (!findState.matches.length) return;
  findState.activeIndex = (findState.activeIndex + delta + findState.matches.length) % findState.matches.length;
  renderFindCount();
  selectActiveFindMatch();
}

function openFindBar() {
  $("bodyFindBar").classList.remove("hidden");
  $("bodyFindInput").focus();
  $("bodyFindInput").select();
  refreshFindMatches();
  selectActiveFindMatch();
}

function closeFindBar() {
  $("bodyFindBar").classList.add("hidden");
  findState = { matches: [], activeIndex: -1, query: "" };
  $("bodyEditor").focus();
  renderBodyHighlight();
}

function replaceActiveFindMatch() {
  if (findState.activeIndex < 0) return;
  const textarea = $("bodyEditor");
  const start = findState.matches[findState.activeIndex];
  textarea.value = replaceAtIndex(textarea.value, start, findState.query.length, $("bodyReplaceInput").value);
  markActiveTabDirty();
  refreshFindMatches();
  selectActiveFindMatch();
}

function replaceAllFindMatches() {
  const textarea = $("bodyEditor");
  textarea.value = replaceAllMatches(textarea.value, $("bodyFindInput").value, $("bodyReplaceInput").value);
  markActiveTabDirty();
  refreshFindMatches();
  selectActiveFindMatch();
}

// --- fullscreen ---

function exitBodyFullscreen() {
  $("tab-body").classList.remove("body-fullscreen");
}

document.addEventListener("DOMContentLoaded", () => {
  const textarea = $("bodyEditor");
  textarea.addEventListener("input", () => {
    $("bodyJsonError").classList.add("hidden");
    if (!$("bodyFindBar").classList.contains("hidden")) refreshFindMatches();
    renderBodyHighlight();
  });
  textarea.addEventListener("scroll", syncBodyScroll);
  textarea.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "f") {
      event.preventDefault();
      openFindBar();
    }
  });
  $("beautifyBodyBtn").addEventListener("click", beautifyBody);

  $("bodyFindBtn").addEventListener("click", openFindBar);
  $("bodyFindCloseBtn").addEventListener("click", closeFindBar);
  $("bodyFindInput").addEventListener("input", () => {
    findState.activeIndex = -1;
    refreshFindMatches();
    selectActiveFindMatch();
  });
  $("bodyFindInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); goToFindMatch(event.shiftKey ? -1 : 1); }
    else if (event.key === "Escape") {
      // Without stopPropagation, this Escape keydown bubbles to the
      // document-level handler below, which would then ALSO see
      // bodyFindBar as already-hidden (just closed here) and immediately
      // exit fullscreen too — collapsing what should be two separate
      // Escape presses into one.
      event.preventDefault();
      event.stopPropagation();
      closeFindBar();
    }
  });
  $("bodyFindPrevBtn").addEventListener("click", () => goToFindMatch(-1));
  $("bodyFindNextBtn").addEventListener("click", () => goToFindMatch(1));
  $("bodyReplaceOneBtn").addEventListener("click", replaceActiveFindMatch);
  $("bodyReplaceAllBtn").addEventListener("click", replaceAllFindMatches);

  $("bodyWrapToggleBtn").addEventListener("click", () => $("bodyEditorWrap").classList.toggle("no-wrap"));
  $("bodyFullscreenBtn").addEventListener("click", () => $("tab-body").classList.toggle("body-fullscreen"));
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!$("bodyFindBar").classList.contains("hidden")) { closeFindBar(); return; }
    exitBodyFullscreen();
  });

  renderBodyHighlight();
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = { findMatches, replaceAtIndex, replaceAllMatches, highlightVarTokens, highlightJson, selectFindMatch, scrollMatchIntoView };
}
