const test = require("node:test");
const assert = require("node:assert/strict");

// markdown.js calls escapeHtml/escapeAttr, normally globals provided by
// shared.js (loaded before it in index.html) — stub the same escaping
// behavior here, same convention sidebar.test.js already uses.
global.escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
global.escapeAttr = (value) => global.escapeHtml(value).replace(/`/g, "&#96;");

const { renderMarkdownToHtml } = require("./markdown.js");

test("renderMarkdownToHtml: empty/absent description renders nothing", () => {
  assert.equal(renderMarkdownToHtml(""), "");
  assert.equal(renderMarkdownToHtml(undefined), "");
});

test("renderMarkdownToHtml: renders headings level 1 through 3", () => {
  assert.equal(renderMarkdownToHtml("# One"), "<h1>One</h1>");
  assert.equal(renderMarkdownToHtml("## Two"), "<h2>Two</h2>");
  assert.equal(renderMarkdownToHtml("### Three"), "<h3>Three</h3>");
});

test("renderMarkdownToHtml: a plain line becomes a paragraph", () => {
  assert.equal(renderMarkdownToHtml("Just some text"), "<p>Just some text</p>");
});

test("renderMarkdownToHtml: a heading directly followed by a paragraph with no blank line still splits into two blocks", () => {
  assert.equal(renderMarkdownToHtml("## Auth\nUse a bearer token."), "<h2>Auth</h2>\n<p>Use a bearer token.</p>");
});

test("renderMarkdownToHtml: a list directly following a paragraph line with no blank line still splits into two blocks", () => {
  assert.equal(renderMarkdownToHtml("Steps:\n- one\n- two"), "<p>Steps:</p>\n<ul><li>one</li><li>two</li></ul>");
});

test("renderMarkdownToHtml: two blocks separated by a blank line become two paragraphs", () => {
  assert.equal(renderMarkdownToHtml("First\n\nSecond"), "<p>First</p>\n<p>Second</p>");
});

test("renderMarkdownToHtml: lines within one block join into a single paragraph", () => {
  assert.equal(renderMarkdownToHtml("Line one\nLine two"), "<p>Line one Line two</p>");
});

test("renderMarkdownToHtml: renders bold and italic", () => {
  assert.equal(renderMarkdownToHtml("**bold** and *italic*"), "<p><strong>bold</strong> and <em>italic</em></p>");
});

test("renderMarkdownToHtml: renders a bullet list (- and * markers)", () => {
  assert.equal(renderMarkdownToHtml("- One\n- Two"), "<ul><li>One</li><li>Two</li></ul>");
  assert.equal(renderMarkdownToHtml("* One\n* Two"), "<ul><li>One</li><li>Two</li></ul>");
});

test("renderMarkdownToHtml: renders a safe https link", () => {
  assert.equal(
    renderMarkdownToHtml("[docs](https://example.com/docs)"),
    '<p><a href="https://example.com/docs" target="_blank" rel="noopener">docs</a></p>'
  );
});

test("renderMarkdownToHtml: renders a safe http and mailto link", () => {
  assert.match(renderMarkdownToHtml("[go](http://example.com)"), /^<p><a href="http:\/\/example\.com"/);
  assert.match(renderMarkdownToHtml("[mail](mailto:a@b.com)"), /^<p><a href="mailto:a@b\.com"/);
});

test("renderMarkdownToHtml: a javascript: link is rejected — rendered as plain escaped text, no anchor", () => {
  const html = renderMarkdownToHtml("[click me](javascript:alert%281%29)");
  assert.doesNotMatch(html, /<a /);
  assert.match(html, /click me/);
});

test("renderMarkdownToHtml: renders a safe image", () => {
  assert.equal(
    renderMarkdownToHtml("![a screenshot](https://example.com/shot.png)"),
    '<p><img alt="a screenshot" src="https://example.com/shot.png"></p>'
  );
});

// Real-world Postman collection descriptions (e.g. GoCardless's) embed
// screenshots as raw HTML <img> tags, not markdown ![]() syntax — Postman's
// own doc editor emits this. Recognized as a whitelisted inline construct
// (src/alt/width/height only, same URL-scheme validation as markdown images)
// rather than escaped as generic raw HTML, or these never render at all.
test("renderMarkdownToHtml: renders a raw HTML <img> tag with src/alt/width/height", () => {
  assert.equal(
    renderMarkdownToHtml('<img src="https://example.com/shot.png" alt="a shot" width="270" height="163">'),
    '<p><img src="https://example.com/shot.png" alt="a shot" width="270" height="163"></p>'
  );
});

test("renderMarkdownToHtml: a raw HTML <img> tag with no alt/width/height still renders with just src", () => {
  assert.equal(
    renderMarkdownToHtml('<img src="https://example.com/shot.png">'),
    '<p><img src="https://example.com/shot.png" alt=""></p>'
  );
});

test("renderMarkdownToHtml: a raw HTML <img> tag's percent-encoded alt text is decoded for readability", () => {
  assert.equal(
    renderMarkdownToHtml('<img src="https://example.com/shot.png" alt="Creating%20a%20token">'),
    '<p><img src="https://example.com/shot.png" alt="Creating a token"></p>'
  );
});

test("renderMarkdownToHtml: a raw HTML <img> tag with a javascript: src is dropped entirely, not rendered", () => {
  const html = renderMarkdownToHtml('<img src="javascript:alert%281%29" alt="evil">');
  assert.doesNotMatch(html, /<img/);
});

test("renderMarkdownToHtml: a raw HTML <img> tag ignores attributes outside the src/alt/width/height whitelist", () => {
  const html = renderMarkdownToHtml('<img src="https://example.com/shot.png" onerror="alert(1)" onload="alert(2)">');
  assert.doesNotMatch(html, /onerror/);
  assert.doesNotMatch(html, /onload/);
});

test("renderMarkdownToHtml: a raw HTML <img> tag's src lookup isn't fooled by a preceding data-src attribute", () => {
  const html = renderMarkdownToHtml('<img data-src="javascript:alert(1)" src="https://example.com/shot.png">');
  assert.match(html, /src="https:\/\/example\.com\/shot\.png"/);
  assert.doesNotMatch(html, /javascript:/);
});

test("renderMarkdownToHtml: a javascript: image src is rejected — rendered as plain escaped alt text, no img tag", () => {
  const html = renderMarkdownToHtml("![x](javascript:alert%281%29)");
  assert.doesNotMatch(html, /<img/);
  assert.match(html, />x</);
});

// Real-world source (GoCardless's description) contains literal HTML
// entities like "Developers &gt; Create &gt; Access Token" — the authoring
// tool already HTML-encoded it. Without decoding first, escapeHtml would
// double-encode the leading `&`, and the browser would then display the
// literal text "&gt;" instead of ">".
test("renderMarkdownToHtml: a pre-encoded HTML entity in the source decodes to its character, not double-escaped text", () => {
  assert.equal(renderMarkdownToHtml("Developers &gt; Create &gt; Access Token"), "<p>Developers &gt; Create &gt; Access Token</p>");
});

test("renderMarkdownToHtml: a pre-encoded entity inside link text decodes correctly too", () => {
  const html = renderMarkdownToHtml("[Developers &gt; Access Token](https://example.com)");
  assert.equal(html, '<p><a href="https://example.com" target="_blank" rel="noopener">Developers &gt; Access Token</a></p>');
});

test("renderMarkdownToHtml: an out-of-range numeric entity is left alone instead of throwing", () => {
  assert.doesNotThrow(() => renderMarkdownToHtml("&#99999999;"));
  assert.doesNotThrow(() => renderMarkdownToHtml("&#x110000;"));
  assert.equal(renderMarkdownToHtml("&#99999999;"), "<p>&amp;#99999999;</p>");
});

test("renderMarkdownToHtml: decoding a pre-encoded entity never re-introduces real markup — a fully-encoded <script> tag stays inert", () => {
  const html = renderMarkdownToHtml("&lt;script&gt;alert(1)&lt;/script&gt;");
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test("renderMarkdownToHtml: raw HTML in the source text is escaped, not executed", () => {
  const html = renderMarkdownToHtml("<script>alert(1)</script>");
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test("renderMarkdownToHtml: a real-world multi-block description with a heading, a link, and a paragraph", () => {
  const description = "# 👋 Introduction\n\nSee the [docs](https://example.com) for more.";
  const html = renderMarkdownToHtml(description);
  assert.equal(
    html,
    '<h1>👋 Introduction</h1>\n<p>See the <a href="https://example.com" target="_blank" rel="noopener">docs</a> for more.</p>'
  );
});
