const $ = (id) => document.getElementById(id);

async function postJson(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

async function putJson(path, body) {
  const response = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

async function deleteJson(path) {
  const response = await fetch(path, { method: "DELETE" });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

function setBusy(button, busy) {
  button.disabled = busy;
  button.dataset.originalText ||= button.textContent;
  button.textContent = busy ? "Working..." : button.dataset.originalText;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

// Mirrors collection_store.slugify() on the backend — must stay in sync so a
// client-side "does this name collide" check agrees with the server's.
function slugify(name) {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function formatSize(bytes) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

// WKWebView (the pywebview runtime this app runs in) applies its own
// autocapitalize/autocorrect defaults to text inputs — a behavior desktop
// Safari/Chrome don't have, and one Iris's original browser-tab delivery
// never hit. Left alone, typing "operator" into a username/variable field
// renders "Operator", silently corrupting values this tool is meant to hold
// verbatim (URLs, credentials, variable names). Stamped on every text-like
// input/textarea, present and future, rather than only the ones known to be
// affected today — the fix is generic, so a future dynamic field doesn't
// have to remember to opt in.
// Renders pre-escaped/highlighted HTML (already-safe markup, e.g. from
// highlightJson()) into `el` with a line-number gutter — one number per
// source line, not per wrapped visual row. Safe to split `html`
// on "\n" because highlightJson() only ever wraps a single JSON token
// (string/number/bool/null) in a span, and JSON.stringify's own pretty-print
// escapes any real newline inside a string value as the two characters
// "\" + "n" — so a literal newline byte in `html` only ever falls between
// spans, never inside one.
function renderLineNumbered(el, html) {
  el.innerHTML = (html || "").split("\n").map((line, i) =>
    `<div class="code-line"><span class="line-no">${i + 1}</span><span class="line-content">${line}</span></div>`
  ).join("");
}

function disableAutoCorrection(el) {
  el.setAttribute("autocapitalize", "off");
  el.setAttribute("autocorrect", "off");
  if (!el.hasAttribute("spellcheck")) el.setAttribute("spellcheck", "false");
}

function disableAutoCorrectionWithin(root) {
  root.querySelectorAll('input[type="text"], input[type="password"], input:not([type]), textarea')
    .forEach(disableAutoCorrection);
}

// pywebview 6.2.1's menu API has no accelerator support at all (see
// menu.py), so "Collection > Save Request" ships with no keyboard
// shortcut natively. This is the JS-level substitute: Cmd+S clicks the same
// #saveBtn the menu item and the visible Save button both already trigger,
// so all three stay in sync with a single source of truth for what "save"
// does. preventDefault matters even though WKWebView has no page-save
// dialog to suppress — without it, Cmd+S still beeps/no-ops loudly enough
// on some macOS builds to look broken.
document.addEventListener("keydown", (event) => {
  if (!(event.metaKey || event.ctrlKey)) return;
  if (event.key.toLowerCase() !== "s") return;
  event.preventDefault();
  $("saveBtn")?.click();
});

// Same fix as Cmd+S above, same root cause (menu.py has no accelerator
// support) — Cmd+Enter to send the current Console request, working from
// anywhere on the page including inside the body editor textarea.
document.addEventListener("keydown", (event) => {
  if (!(event.metaKey || event.ctrlKey)) return;
  if (event.key !== "Enter") return;
  event.preventDefault();
  $("sendBtn")?.click();
});

// Same root cause as the Cmd+S fix above, different symptom: with no
// standard Edit menu wired to the native cut:/copy:/paste: selectors (see
// menu.py), Cmd+C on a selection never reaches WKWebView's editing commands
// — the keystroke just never gets routed anywhere.
//
// Two distinct selection sources have to be checked, not one: text selected
// in a read-only area (e.g. the response body <pre>) lives in
// window.getSelection(); text selected inside an <input>/<textarea> (e.g.
// the request body editor) is a completely separate browser mechanism
// (selectionStart/selectionEnd) that window.getSelection() can never see. A
// first pass here only handled the former, which is exactly why copying a
// selection out of the payload editor still did nothing.
//
// Routed through the same save_bridge.py `pbcopy` bridge the visible "Copy"
// button already uses (confirmed working), rather than
// document.execCommand("copy") — untested in this WKWebView build and not
// worth risking on the one thing users need reliably.
function currentKeyboardSelection() {
  const active = document.activeElement;
  if (
    active &&
    (active.tagName === "TEXTAREA" || active.tagName === "INPUT") &&
    active.selectionStart !== active.selectionEnd
  ) {
    return { text: active.value.slice(active.selectionStart, active.selectionEnd), el: active };
  }
  const text = String(window.getSelection());
  return text ? { text, el: null } : null;
}

document.addEventListener("keydown", (event) => {
  if (!(event.metaKey || event.ctrlKey)) return;
  const key = event.key.toLowerCase();
  if (key !== "c" && key !== "x") return;
  const selection = currentKeyboardSelection();
  if (!selection) return;
  event.preventDefault();
  irisClipboardWrite(selection.text).catch((error) => alert(`Copy failed: ${error.message}`));
  if (key === "x" && selection.el) {
    const el = selection.el;
    const [start, end] = [el.selectionStart, el.selectionEnd];
    el.setRangeText("", start, end, "start");
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }
});

document.addEventListener("DOMContentLoaded", () => {
  disableAutoCorrectionWithin(document);
  new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType !== Node.ELEMENT_NODE) continue;
        if (node.matches?.('input[type="text"], input[type="password"], input:not([type]), textarea')) {
          disableAutoCorrection(node);
        }
        disableAutoCorrectionWithin(node);
      }
    }
  }).observe(document.body, { childList: true, subtree: true });
});
