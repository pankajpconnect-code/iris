// Vars tab: the collection's explicitly-defined console variables
// (consoleState.vars) — split out of static/request-tabs.js to keep that
// file under this repo's 500-line cap.

const SECRET_NAME_PATTERN = /token|secret|password|cookie/i;

async function loadConsoleVars(slug) {
  try {
    const response = await fetch(`/api/collections/${encodeURIComponent(slug)}/vars`);
    const data = await response.json();
    consoleState.vars = (response.ok && data.variables) || {};
  } catch {
    consoleState.vars = {};
  }
  renderConsoleVars();
  // Auth fields live in consoleState.vars too (as __auth*-prefixed keys) —
  // without this, the Auth tab kept showing whatever was on screen from the
  // previously-selected collection (or blank on first load) until the user
  // happened to touch the Mode dropdown, since renderAuthTab() otherwise
  // only ran once, at page-init, before this fetch had ever resolved.
  renderAuthTab();
}

function renderConsoleVars() {
  const envVars = (typeof activeEnvironmentVars === "function") ? activeEnvironmentVars() : {};
  // collectBodyParams(), not collectAllBodyParams() — matches collectHeaders()
  // right beside it: this fallback only exists for a brand-new unsaved
  // request, and a disabled row shouldn't raise "needs a value" any more
  // than a disabled header does.
  const selected = consoleState.selectedRequest ||
    { url: $("url").value, headers: collectHeaders(), body: $("bodyEditor").value, bodyParams: collectBodyParams() };
  // Vars is for variables the user has explicitly defined for this collection
  // (via "+ Variable" or a Capture test) — not every {{var}} this request
  // happens to reference, and not environment variables (those live in the
  // Environments modal and surface where they're actually used, via the
  // header/URL/body {{var}} autocomplete — showing them here too would just
  // duplicate them under a second, easily-confused tab).
  const names = new Set(Object.keys(consoleState.vars).filter((n) => !isAuthKey(n)));
  const sorted = [...names].sort();
  const body = $("varsBody");
  body.innerHTML = "";
  for (const name of sorted) {
    const value = consoleState.vars[name] || "";
    const isSecret = SECRET_NAME_PATTERN.test(name);
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="mono var">${escapeHtml(name)}</td>
      <td>
        <input class="hdr-value var-value" type="${isSecret ? "password" : "text"}" data-name="${escapeAttr(name)}" value="${escapeAttr(value)}">
        ${isSecret ? '<span class="console-var-secret-label">session only</span>' : ""}
      </td>
    `;
    row.querySelector(".var-value").addEventListener("change", (event) => saveConsoleVar(name, event.target.value));
    body.appendChild(row);
  }

  // The "needs a value" warning is a different concern from what's SHOWN in
  // the table above — it's about whether this request can actually run, so it
  // still checks every {{var}} the request references against both the
  // collection's explicit vars and the active environment.
  const missing = [...requestVarNames(selected)].filter((name) => !consoleState.vars[name] && !envVars[name]);
  $("tabVarCount").textContent = sorted.length || "";
  const warning = $("varsWarning");
  if (missing.length) {
    warning.textContent = `${missing.length} variable(s) need a value before this request will run: ${missing.join(", ")}`;
    warning.classList.remove("hidden");
  } else {
    warning.classList.add("hidden");
  }
}

async function saveConsoleVar(name, value) {
  const slug = consoleState.selectedCollectionSlug;
  if (!slug) {
    alert("Select or create a collection in the sidebar first.");
    return;
  }
  try {
    const data = await putJson(`/api/collections/${encodeURIComponent(slug)}/vars`, { [name]: value });
    consoleState.vars = data.variables || consoleState.vars;
    renderConsoleVars();
  } catch (error) {
    alert(`Could not save variable: ${error.message}`);
  }
}

async function addVariablePrompt() {
  const name = ((await irisPrompt("Variable name:")) || "").trim();
  if (!name) return;
  const value = (await irisPrompt(`Value for ${name}:`)) || "";
  await saveConsoleVar(name, value);
}

document.addEventListener("DOMContentLoaded", () => {
  $("addVarBtn").addEventListener("click", addVariablePrompt);
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = { loadConsoleVars, renderConsoleVars, saveConsoleVar, addVariablePrompt, SECRET_NAME_PATTERN };
}
