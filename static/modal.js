// Promise-based replacement for window.prompt(), which pywebview's WKWebView
// does not support (silently returns null). Styled from tokens.css / the
// env-modal pattern already in environments.css. Call sites: console-vars.js
// (variable name/value), request-tabs.js (save-name), environments.js (new
// environment name), sidebar.js (duplicate name, new collection name).
//
// irisConfirm() below is the same fix for window.confirm(): pywebview's
// WKWebView does render it, but as a native OS dialog carrying a generic
// default icon instead of Iris's — same root cause, same fix shape.

function ensureModalHost() {
  let host = document.getElementById("irisModalHost");
  if (host) return host;
  host = document.createElement("div");
  host.id = "irisModalHost";
  host.className = "iris-modal hidden";
  host.innerHTML = `
    <div class="iris-modal-box">
      <div class="iris-modal-message" id="irisModalMessage"></div>
      <input class="iris-modal-input" id="irisModalInput" type="text" autocomplete="off">
      <div class="iris-modal-actions">
        <button class="btn" id="irisModalCancel" type="button">Cancel</button>
        <button class="btn primary" id="irisModalOk" type="button">OK</button>
      </div>
    </div>`;
  document.body.appendChild(host);
  return host;
}

// Returns the entered string, or null if cancelled — matching prompt()'s
// contract so every call site's `(await irisPrompt(...)) || ""` idiom works
// unchanged.
function irisPrompt(message, defaultValue) {
  const host = ensureModalHost();
  const messageEl = document.getElementById("irisModalMessage");
  const input = document.getElementById("irisModalInput");
  const okBtn = document.getElementById("irisModalOk");
  const cancelBtn = document.getElementById("irisModalCancel");

  messageEl.textContent = message;
  input.value = defaultValue || "";
  host.classList.remove("hidden");
  input.focus();
  input.select();

  return new Promise((resolve) => {
    function cleanup(result) {
      host.classList.add("hidden");
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      input.removeEventListener("keydown", onKeydown);
      resolve(result);
    }
    function onOk() {
      cleanup(input.value);
    }
    function onCancel() {
      cleanup(null);
    }
    function onKeydown(event) {
      if (event.key === "Enter") {
        event.preventDefault();
        onOk();
      } else if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
      }
    }
    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    input.addEventListener("keydown", onKeydown);
  });
}

// Returns true/false, matching confirm()'s contract so every call site's
// `if (!(await irisConfirm(...))) return;` idiom works unchanged. Reuses the
// irisPrompt host with its text input hidden — there's nothing to enter.
function irisConfirm(message) {
  const host = ensureModalHost();
  const messageEl = document.getElementById("irisModalMessage");
  const input = document.getElementById("irisModalInput");
  const okBtn = document.getElementById("irisModalOk");
  const cancelBtn = document.getElementById("irisModalCancel");

  messageEl.textContent = message;
  input.classList.add("hidden");
  host.classList.remove("hidden");
  okBtn.focus();

  return new Promise((resolve) => {
    function cleanup(result) {
      host.classList.add("hidden");
      input.classList.remove("hidden");
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      document.removeEventListener("keydown", onKeydown);
      resolve(result);
    }
    function onOk() {
      cleanup(true);
    }
    function onCancel() {
      cleanup(false);
    }
    function onKeydown(event) {
      if (event.key === "Enter") {
        event.preventDefault();
        onOk();
      } else if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
      }
    }
    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    document.addEventListener("keydown", onKeydown);
  });
}
