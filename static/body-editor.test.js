const test = require("node:test");
const assert = require("node:assert/strict");

global.document = { addEventListener: () => {}, querySelector: () => null };
// body-editor.js calls the global escapeHtml() defined by shared.js in the
// browser; shared.js itself isn't require()-able (it touches document.body
// at load time), so mirror its implementation here for tests.
global.escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
// scrollMatchIntoView reads the textarea's computed line-height (same
// 1-visual-row-per-\n approximation renderBodyLineGutter already makes —
// see panel.css's line-gutter comment); stub it like the other browser
// globals above instead of pulling in jsdom for one CSS read.
global.getComputedStyle = () => ({ lineHeight: "20px" });
const {
  findMatches,
  replaceAtIndex,
  replaceAllMatches,
  highlightVarTokens,
  selectFindMatch,
  scrollMatchIntoView,
  highlightJson,
} = require("./body-editor.js");

test("findMatches: finds all case-insensitive occurrences", () => {
  assert.deepEqual(findMatches('{"loanId": "9", "LoanId": "9"}', "loanid"), [2, 17]);
});

test("findMatches: empty query returns no matches", () => {
  assert.deepEqual(findMatches("anything", ""), []);
});

test("findMatches: no occurrences returns empty array", () => {
  assert.deepEqual(findMatches("hello world", "xyz"), []);
});

test("replaceAtIndex: swaps only the matched span, keeping surrounding text intact", () => {
  assert.equal(replaceAtIndex("abcXYZdef", 3, 3, "123"), "abc123def");
});

test("replaceAllMatches: replaces every occurrence without touching text between them", () => {
  assert.equal(replaceAllMatches("foo-bar-foo-bar", "foo", "baz"), "baz-bar-baz-bar");
});

test("replaceAllMatches: no query is a no-op", () => {
  assert.equal(replaceAllMatches("unchanged", "", "x"), "unchanged");
});

// highlightVarTokens takes RAW text and returns escaped HTML, same contract
// as escapeHtml — it used to run as a single global regex pass over
// already-assembled HTML instead, which corrupted tag nesting whenever a
// {{var}} spanned an injected <mark> (see the highlightJson tests below).
test("highlightVarTokens: escapes plain text and wraps {{var}} placeholders in a span", () => {
  assert.equal(
    highlightVarTokens('"{{url}}/api/loans/{{loanId}}"'),
    '&quot;<span class="body-var-token">{{url}}</span>/api/loans/<span class="body-var-token">{{loanId}}</span>&quot;'
  );
});

test("selectFindMatch: sets the selection range without stealing focus from the find input", () => {
  let focusCalled = false;
  const fakeTextarea = {
    setSelectionRange: () => {},
    focus: () => { focusCalled = true; },
  };
  selectFindMatch(fakeTextarea, 5, 3);
  assert.equal(focusCalled, false);
});

test("selectFindMatch: selects exactly the match span", () => {
  const calls = [];
  const fakeTextarea = { setSelectionRange: (start, end) => calls.push([start, end]), focus: () => {} };
  selectFindMatch(fakeTextarea, 5, 3);
  assert.deepEqual(calls, [[5, 8]]);
});

test("scrollMatchIntoView: scrolls down when the match is below the visible viewport", () => {
  const lines = Array.from({ length: 20 }, (_, i) => `line${i}`);
  const fakeTextarea = { value: lines.join("\n"), scrollTop: 0, clientHeight: 100 };
  const matchStart = lines.slice(0, 10).join("\n").length + 1; // start of line 10
  scrollMatchIntoView(fakeTextarea, matchStart);
  assert.equal(fakeTextarea.scrollTop, 120); // matchBottom (220) - clientHeight (100)
});

test("scrollMatchIntoView: scrolls up when the match is above the visible viewport", () => {
  const lines = Array.from({ length: 20 }, (_, i) => `line${i}`);
  const fakeTextarea = { value: lines.join("\n"), scrollTop: 200, clientHeight: 100 };
  const matchStart = lines.slice(0, 1).join("\n").length + 1; // start of line 1
  scrollMatchIntoView(fakeTextarea, matchStart);
  assert.equal(fakeTextarea.scrollTop, 20); // matchTop of line 1
});

test("scrollMatchIntoView: leaves scroll position untouched when the match is already visible", () => {
  const lines = Array.from({ length: 20 }, (_, i) => `line${i}`);
  const fakeTextarea = { value: lines.join("\n"), scrollTop: 100, clientHeight: 100 };
  const matchStart = lines.slice(0, 6).join("\n").length + 1; // start of line 6, within [100,200]
  scrollMatchIntoView(fakeTextarea, matchStart);
  assert.equal(fakeTextarea.scrollTop, 100);
});

// The visible body text is rendered entirely by this highlight overlay (the
// textarea's own text is transparent — see panel.css), so the find match
// has to be marked up here, not via textarea selection, or it's invisible
// whenever the find input (not the body) holds keyboard focus.
test("highlightJson: wraps a match that sits fully inside one token, preserving the token's class", () => {
  const html = highlightJson('{"username": "bob"}', { start: 2, end: 10 });
  assert.equal(
    html,
    '{<span class="json-key">&quot;</span><mark class="body-find-active"><span class="json-key">username</span></mark><span class="json-key">&quot;</span>: <span class="json-string">&quot;bob&quot;</span>}'
  );
});

test("highlightJson: wraps a match that sits in the plain text between tokens", () => {
  const html = highlightJson("null,null", { start: 4, end: 5 });
  assert.equal(
    html,
    '<span class="json-null">null</span><mark class="body-find-active">,</mark><span class="json-null">null</span>'
  );
});

// Each chunk (token or plain-text gap) wraps its own overlapping slice
// independently, so a match spanning a boundary produces adjacent <mark>
// elements rather than one merged one — visually identical (no gap/border
// between them) and far simpler than merging across chunk boundaries.
test("highlightJson: wraps a match spanning a token boundary across two adjacent tokens", () => {
  const html = highlightJson("true,false", { start: 3, end: 6 });
  assert.equal(
    html,
    '<span class="json-boolean">tru</span><mark class="body-find-active"><span class="json-boolean">e</span></mark><mark class="body-find-active">,</mark><mark class="body-find-active"><span class="json-boolean">f</span></mark><span class="json-boolean">alse</span>'
  );
});

test("highlightJson: no activeRange behaves exactly as before (no <mark> anywhere)", () => {
  assert.equal(highlightJson('{"a": 1}'), highlightJson('{"a": 1}', null));
});

test("highlightJson: {{var}} inside a JSON string keeps correct nested styling with balanced tags", () => {
  const html = highlightJson('{"url": "{{baseUrl}}"}');
  assert.equal(
    html,
    '{<span class="json-key">&quot;url&quot;</span>: <span class="json-string">&quot;<span class="body-var-token">{{baseUrl}}</span>&quot;</span>}'
  );
});

test("highlightJson: an active find match elsewhere does not disturb an unrelated {{var}} token's styling", () => {
  const html = highlightJson('{"url": "{{baseUrl}}"}', { start: 2, end: 5 });
  assert.equal(
    html,
    '{<span class="json-key">&quot;</span><mark class="body-find-active"><span class="json-key">url</span></mark><span class="json-key">&quot;</span>: <span class="json-string">&quot;<span class="body-var-token">{{baseUrl}}</span>&quot;</span>}'
  );
});

// Regression for the bug an independent review caught: highlightVarTokens
// used to run once over the fully-assembled HTML, so when an active find
// match split a {{var}} token, the regex bridged across the injected <mark>
// tag and captured a stray closing </span> from inside the match — wrapping
// it in a new outer span produced mismatched/unbalanced tags, not just lost
// styling. Now that var-token detection runs per-chunk on raw text (same as
// JSON token splitting), a split token just loses its color gracefully
// instead of corrupting the surrounding markup.
test("highlightJson: a find match splitting a {{var}} token degrades gracefully instead of corrupting tags", () => {
  const text = '{"url": "{{baseUrl}}"}';
  const html = highlightJson(text, { start: text.indexOf("ase"), end: text.indexOf("ase") + 3 });
  assert.equal(
    html,
    '{<span class="json-key">&quot;url&quot;</span>: <span class="json-string">&quot;{{b</span><mark class="body-find-active"><span class="json-string">ase</span></mark><span class="json-string">Url}}&quot;</span>}'
  );
});
