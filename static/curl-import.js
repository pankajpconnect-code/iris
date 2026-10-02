// Reverse of requestToCurl() (sidebar-request-actions.js) — turns a curl command pasted from
// a browser's devtools / API docs into an Iris request shape, so a curl
// snippet handed to you mid-demo doesn't require retyping every header by
// hand.

// Line-continuations (`\` + newline) are how curl commands wrap across
// multiple lines when copied from devtools "pretty" mode — collapse them to
// spaces before tokenizing so the shell-quoting rules below only have to deal
// with one logical line.
function tokenizeCurlCommand(text) {
  const cleaned = String(text || "").replace(/\\\r?\n/g, " ");
  const tokens = [];
  let i = 0;
  const n = cleaned.length;
  while (i < n) {
    while (i < n && /\s/.test(cleaned[i])) i++;
    if (i >= n) break;
    let token = "";
    while (i < n && !/\s/.test(cleaned[i])) {
      const ch = cleaned[i];
      if (ch === "'") {
        i++;
        while (i < n && cleaned[i] !== "'") {
          token += cleaned[i];
          i++;
        }
        i++;
      } else if (ch === '"') {
        i++;
        while (i < n && cleaned[i] !== '"') {
          if (cleaned[i] === "\\" && i + 1 < n && (cleaned[i + 1] === '"' || cleaned[i + 1] === "\\")) {
            token += cleaned[i + 1];
            i += 2;
          } else {
            token += cleaned[i];
            i++;
          }
        }
        i++;
      } else if (ch === "\\" && i + 1 < n) {
        token += cleaned[i + 1];
        i += 2;
      } else {
        token += ch;
        i++;
      }
    }
    tokens.push(token);
  }
  return tokens;
}

const DATA_FLAGS = new Set(["-d", "--data", "--data-raw", "--data-binary", "--data-ascii"]);
// Flags curl accepts that have no corresponding field on an Iris request and
// take no argument — listed explicitly (rather than "ignore anything
// unrecognized") so a typo'd flag doesn't silently vanish instead of
// surfacing as a confusing partial import.
const NO_OP_FLAGS = new Set([
  "-k", "--insecure", "-L", "--location", "--compressed", "-s", "--silent",
  "-v", "--verbose", "-i", "--include", "--http1.1", "--http2",
]);
// Flags with no Iris equivalent that DO take a value argument — the argument
// must still be consumed here, otherwise it gets misread as the request URL
// by the fallback branch below (e.g. -F 'file=@x.jpg' would import
// "file=@x.jpg" as the URL instead of the one later in the command).
const VALUE_NO_OP_FLAGS = new Set([
  "-F", "--form", "-b", "--cookie", "-A", "--user-agent", "-e", "--referer",
  "-o", "--output", "-T", "--upload-file", "-x", "--proxy", "-w", "--write-out",
  "-m", "--max-time", "--connect-timeout", "--cert", "--key",
]);

function parseCurlCommand(text) {
  const tokens = tokenizeCurlCommand(text);
  if (!tokens.length || tokens[0] !== "curl") {
    throw new Error("Not a curl command — expected it to start with 'curl'.");
  }
  let method = null;
  let url = null;
  const headers = [];
  const bodyParts = [];
  const unsupportedFlags = [];

  for (let i = 1; i < tokens.length; i++) {
    const tok = tokens[i];
    if (tok === "-X" || tok === "--request") {
      method = tokens[++i];
    } else if (tok === "-H" || tok === "--header") {
      const raw = tokens[++i] || "";
      const idx = raw.indexOf(":");
      if (idx !== -1) {
        headers.push({ key: raw.slice(0, idx).trim(), value: raw.slice(idx + 1).trim(), enabled: true });
      }
    } else if (DATA_FLAGS.has(tok)) {
      // Real curl concatenates repeated -d occurrences with "&" rather than
      // letting the last one win — matters for e.g. curl-cheat-sheet snippets
      // that split a form body across multiple -d flags for readability.
      bodyParts.push(tokens[++i] || "");
      if (!method) method = "POST";
    } else if (tok === "--data-urlencode") {
      const raw = tokens[++i] || "";
      const eq = raw.indexOf("=");
      bodyParts.push(eq === -1 ? encodeURIComponent(raw) : `${raw.slice(0, eq)}=${encodeURIComponent(raw.slice(eq + 1))}`);
      if (!method) method = "POST";
    } else if (tok === "-u" || tok === "--user") {
      const cred = tokens[++i] || "";
      headers.push({ key: "Authorization", value: `Basic ${btoa(cred)}`, enabled: true });
    } else if (NO_OP_FLAGS.has(tok)) {
      // no corresponding Iris request field — intentionally dropped
    } else if (VALUE_NO_OP_FLAGS.has(tok)) {
      i++; // consume the value — no Iris equivalent for this flag yet
      unsupportedFlags.push(tok);
    } else if (!tok.startsWith("-") && !url) {
      url = tok;
    }
  }

  if (!url) {
    throw new Error("No URL found in the curl command.");
  }

  const body = bodyParts.join("&");
  const contentType = headers.find((h) => h.key.toLowerCase() === "content-type");
  const bodyMode = contentType && contentType.value.includes("x-www-form-urlencoded") ? "urlencoded" : "raw";
  const bodyParams = bodyMode === "urlencoded"
    ? body.split("&").filter(Boolean).map((pair) => {
        const idx = pair.indexOf("=");
        const k = idx === -1 ? pair : pair.slice(0, idx);
        const v = idx === -1 ? "" : pair.slice(idx + 1);
        return { key: decodeURIComponent(k), value: decodeURIComponent(v), enabled: true };
      })
    : [];

  return {
    method: method || "GET",
    url,
    headers,
    body: bodyMode === "raw" ? body : "",
    bodyMode,
    bodyParams,
    unsupportedFlags,
  };
}

async function importRequestFromCurl(collectionSlug) {
  const curlText = await irisPrompt("Paste a curl command:");
  if (!curlText) return;
  let parsed;
  try {
    parsed = parseCurlCommand(curlText);
  } catch (error) {
    alert(`Could not parse curl command: ${error.message}`);
    return;
  }
  const name = await irisPrompt("Name this request:", uniqueRequestName(collectionSlug, `${parsed.method} ${parsed.url}`));
  if (!name) return;
  const { unsupportedFlags, ...request } = parsed;
  try {
    await postJson(`/api/collections/${encodeURIComponent(collectionSlug)}/requests`, { ...request, name, tests: [] });
    await loadCollections();
    if (unsupportedFlags.length) {
      alert(`Imported, but these curl flags have no Iris equivalent yet and were skipped: ${unsupportedFlags.join(", ")}`);
    }
  } catch (error) {
    alert(`Import from curl failed: ${error.message}`);
  }
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { parseCurlCommand, importRequestFromCurl };
}
