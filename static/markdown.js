/* Minimal, dependency-free markdown -> HTML renderer for a collection's
 * imported `description` (see collection description support). Covers only
 * what real-world collection docs actually use: headings, bold/italic,
 * links, images, paragraphs, bullet lists. Anything else (tables, nested
 * blockquotes, code fences) renders as a literal paragraph rather than
 * failing — there is no parse error state, only "didn't recognize this as
 * a special block."
 *
 * Security: description text is untrusted (it comes from an imported
 * Postman collection file, not from this app). Every plain-text segment is
 * escapeHtml'd before being placed in the output, and link/image URLs are
 * restricted to http:/https:/mailto: — a `javascript:` URL is rejected and
 * falls back to plain escaped text instead of a clickable/loadable tag.
 * Relies on escapeHtml/escapeAttr as globals (shared.js, loaded before this
 * file), same convention as folders.js/sidebar.js.
 */

const SAFE_URL_RE = /^(https?:|mailto:)/i;

const NAMED_ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };

// Real-world source text (e.g. GoCardless's description) already contains
// HTML entities like "Developers &gt; Access Token" — whatever authored it
// HTML-encoded first. Decoding these back to plain characters before block
// parsing avoids double-encoding ("&gt;" displaying literally instead of
// ">"). This runs BEFORE inline parsing, so decoded text is parsed exactly
// as if the source had contained those characters unencoded — a fully
// encoded "&amp;lt;script&amp;gt;" decodes to the literal text "<script>"
// and is then escaped as plain text (safe, inert), while a fully encoded
// "&amp;lt;img src=&amp;quot;https://x&amp;quot;&amp;gt;" decodes to a real
// <img> tag and is rendered via the same whitelisted, attribute-stripping
// renderRawImgTag as if it had been unencoded raw HTML all along (also
// safe). Decoding never produces output outside what an unencoded source
// could already produce through the constructs below.
function decodeHtmlEntities(text) {
  return text.replace(/&(#x?[0-9a-f]+|[a-z]+\d*);/gi, (entity, body) => {
    if (body[0] === "#") {
      const codePoint = body[1].toLowerCase() === "x" ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10);
      const isValid = Number.isInteger(codePoint) && codePoint >= 0 && codePoint <= 0x10ffff;
      return isValid ? String.fromCodePoint(codePoint) : entity;
    }
    const key = body.toLowerCase();
    return key in NAMED_ENTITIES ? NAMED_ENTITIES[key] : entity;
  });
}

// Real-world collection descriptions (e.g. GoCardless's) embed screenshots
// as raw HTML <img> tags — Postman's own doc editor emits this, not markdown
// ![]() syntax. Recognized as its own whitelisted inline construct (only
// src/alt/width/height are ever read; every other attribute, e.g. an
// onerror handler, is silently dropped) rather than falling through to the
// generic "escape unrecognized text" path, or these would never render.
const INLINE_RE = /<img\s+([^>]*?)\/?>|!\[([^\]]*)\]\(([^)\s]+)\)|\[([^\]]*)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*/g;

// (?:^|\s) rather than \b before the attribute name — \b matches after a
// hyphen too, so a `\bsrc=` lookup would wrongly pick up `data-src="..."`.
function extractHtmlAttr(attrs, name) {
  const match = attrs.match(new RegExp(`(?:^|\\s)${name}\\s*=\\s*"([^"]*)"`, "i"));
  return match ? match[1] : undefined;
}

function decodeAltSafe(alt) {
  try {
    return decodeURIComponent(alt);
  } catch {
    return alt;
  }
}

function renderRawImgTag(attrs) {
  const src = extractHtmlAttr(attrs, "src");
  if (!src || !SAFE_URL_RE.test(src)) return "";
  const alt = decodeAltSafe(extractHtmlAttr(attrs, "alt") || "");
  const width = extractHtmlAttr(attrs, "width");
  const height = extractHtmlAttr(attrs, "height");
  let tag = `<img src="${escapeAttr(src)}" alt="${escapeAttr(alt)}"`;
  if (/^\d+$/.test(width || "")) tag += ` width="${width}"`;
  if (/^\d+$/.test(height || "")) tag += ` height="${height}"`;
  return tag + ">";
}

function renderImage(alt, url) {
  if (!SAFE_URL_RE.test(url)) return escapeHtml(alt);
  return `<img alt="${escapeAttr(alt)}" src="${escapeAttr(url)}">`;
}

function renderLink(text, url) {
  if (!SAFE_URL_RE.test(url)) return escapeHtml(text);
  return `<a href="${escapeAttr(url)}" target="_blank" rel="noopener">${escapeHtml(text)}</a>`;
}

// Manual scan rather than a plain `.replace(INLINE_RE, cb)`: the text
// BETWEEN matches also needs escapeHtml, and replace() only ever hands a
// callback the matched substrings, never the gaps.
function renderInline(text) {
  let html = "";
  let lastIndex = 0;
  INLINE_RE.lastIndex = 0;
  let match;
  while ((match = INLINE_RE.exec(text))) {
    html += escapeHtml(text.slice(lastIndex, match.index));
    if (match[1] !== undefined) html += renderRawImgTag(match[1]);
    else if (match[2] !== undefined) html += renderImage(match[2], match[3]);
    else if (match[4] !== undefined) html += renderLink(match[4], match[5]);
    else if (match[6] !== undefined) html += `<strong>${escapeHtml(match[6])}</strong>`;
    else if (match[7] !== undefined) html += `<em>${escapeHtml(match[7])}</em>`;
    lastIndex = INLINE_RE.lastIndex;
  }
  html += escapeHtml(text.slice(lastIndex));
  return html;
}

// A blank-line-only split (the previous approach) missed a very common real-
// world shape: "## Auth\nUse a bearer token." — one regex match attempt
// against the whole multi-line chunk can't isolate the heading line from the
// paragraph line after it, so the heading was silently swallowed into a
// single paragraph. Grouping line-by-line instead means a heading line or a
// list-item run starts its own block immediately, blank line or not.
function splitIntoBlocks(text) {
  const blocks = [];
  let current = null;
  const flush = () => {
    if (current && current.lines.length) blocks.push(current);
    current = null;
  };
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (!line) {
      flush();
      continue;
    }
    if (/^#{1,3}\s+/.test(line)) {
      flush();
      blocks.push({ kind: "heading", lines: [line] });
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      if (!current || current.kind !== "list") {
        flush();
        current = { kind: "list", lines: [] };
      }
      current.lines.push(line);
      continue;
    }
    if (!current || current.kind !== "paragraph") {
      flush();
      current = { kind: "paragraph", lines: [] };
    }
    current.lines.push(line);
  }
  flush();
  return blocks;
}

function renderBlock(block) {
  if (block.kind === "heading") {
    const heading = block.lines[0].match(/^(#{1,3})\s+(.*)$/);
    const level = heading[1].length;
    return `<h${level}>${renderInline(heading[2])}</h${level}>`;
  }
  if (block.kind === "list") {
    const items = block.lines.map((line) => `<li>${renderInline(line.replace(/^[-*]\s+/, ""))}</li>`).join("");
    return `<ul>${items}</ul>`;
  }
  return `<p>${renderInline(block.lines.join(" "))}</p>`;
}

function renderMarkdownToHtml(text) {
  if (!text) return "";
  const decoded = decodeHtmlEntities(String(text)).replace(/\r\n/g, "\n");
  return splitIntoBlocks(decoded).map(renderBlock).join("\n");
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { renderMarkdownToHtml };
}
