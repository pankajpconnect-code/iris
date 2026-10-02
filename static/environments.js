const ACTIVE_ENV_STORAGE_KEY = "csvApiConsole.activeEnvironmentSlug";

const environmentState = {
  list: [],
  activeSlug: "",
  activeVars: {},
  editingSlug: "",
  // {name: {secret, environmentNames}} — replaced (not merged) on every
  // renderEnvEditor() call; see fetchDivergence().
  divergence: {},
};

function activeEnvironmentSlug() {
  return environmentState.activeSlug;
}

function activeEnvironmentVars() {
  return environmentState.activeVars;
}

async function loadEnvironmentList() {
  try {
    const response = await fetch("/api/environments");
    const data = await response.json();
    environmentState.list = (response.ok && data.environments) || [];
  } catch {
    environmentState.list = [];
  }
  populateEnvSelects();
  const stored = localStorage.getItem(ACTIVE_ENV_STORAGE_KEY) || "";
  if (stored && environmentState.list.some((e) => e.slug === stored)) {
    await setActiveEnvironment(stored);
  } else if (stored) {
    // The stored active environment no longer exists (deleted and
    // recreated, e.g. to clear out a bad variable) — the Runner's own
    // picker would otherwise silently sit on "No Environment" while the
    // top bar still shows a name, since it never re-syncs on its own.
    localStorage.removeItem(ACTIVE_ENV_STORAGE_KEY);
  }
}

function populateEnvSelects() {
  for (const select of [$("envSelect"), $("runnerEnvSelect")]) {
    if (!select) continue;
    const previous = select.value;
    select.innerHTML = '<option value="">No Environment</option>';
    for (const env of environmentState.list) {
      const option = document.createElement("option");
      option.value = env.slug;
      option.textContent = env.name;
      select.appendChild(option);
    }
    if ([...select.options].some((o) => o.value === previous)) select.value = previous;
  }
}

async function setActiveEnvironment(slug) {
  environmentState.activeSlug = slug;
  localStorage.setItem(ACTIVE_ENV_STORAGE_KEY, slug || "");
  let vars = {};
  if (slug) {
    try {
      const response = await fetch(`/api/environments/${encodeURIComponent(slug)}/vars`);
      const data = await response.json();
      vars = (response.ok && data.variables) || {};
    } catch {
      vars = {};
    }
  }
  // A faster later call (switching A -> B before A's fetch resolves) already
  // moved activeSlug on — this fetch's result is stale, discard it instead
  // of clobbering whatever the newer call already applied.
  if (environmentState.activeSlug !== slug) return;
  environmentState.activeVars = vars;
  $("envSelect").value = slug;
  // The Runner has its own, separate environment picker — keep it following
  // the console's active environment by default. This does mean a
  // deliberate divergent choice in the Runner gets reset the next time the
  // active environment changes elsewhere; that's the right tradeoff against
  // the alternative (silently running against no/stale environment, which
  // is what a request whose {{var}} depends on it needs to fail loudly on).
  if ($("runnerEnvSelect")) $("runnerEnvSelect").value = slug;
  if (typeof renderConsoleVars === "function") renderConsoleVars();
}

// --- manager modal ---

function openEnvModal() {
  $("envModal").classList.remove("hidden");
  renderEnvList();
}

function closeEnvModal() {
  $("envModal").classList.add("hidden");
}

function renderEnvList() {
  const list = $("envList");
  list.innerHTML = "";
  for (const env of environmentState.list) {
    const row = document.createElement("div");
    row.className = "env-row";
    if (env.slug === environmentState.editingSlug) row.classList.add("active");
    row.innerHTML = `<span>${escapeHtml(env.name)}</span><button class="icon-btn" type="button" title="Delete">&times;</button>`;
    row.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      environmentState.editingSlug = env.slug;
      renderEnvList();
      renderEnvEditor();
    });
    row.querySelector("button").addEventListener("click", async () => {
      if (!(await irisConfirm(`Delete environment "${env.name}"?`))) return;
      await fetch(`/api/environments/${encodeURIComponent(env.slug)}`, { method: "DELETE" });
      if (environmentState.editingSlug === env.slug) environmentState.editingSlug = "";
      if (environmentState.activeSlug === env.slug) await setActiveEnvironment("");
      await loadEnvironmentList();
      renderEnvList();
      renderEnvEditor();
    });
    list.appendChild(row);
  }
}

// Divergence is a whole-collection signal (which environments define a
// given variable name with which of several distinct values), not scoped
// to one environment — fetched fresh alongside vars-state on every editor
// render rather than cached, so a save elsewhere always reflects promptly.
async function fetchDivergence() {
  try {
    const response = await fetch("/api/environment-divergence");
    const data = await response.json();
    return (response.ok && data.divergence) || {};
  } catch {
    return {};
  }
}

async function renderEnvEditor() {
  const editor = $("envEditor");
  const slug = environmentState.editingSlug;
  if (!slug) {
    editor.innerHTML = '<div class="console-empty">Select or create an environment.</div>';
    return;
  }
  const [varsResponse, divergence] = await Promise.all([
    fetch(`/api/environments/${encodeURIComponent(slug)}/vars-state`),
    fetchDivergence(),
  ]);
  const data = await varsResponse.json();
  const varsState = (varsResponse.ok && data.variables) || {};
  environmentState.divergence = divergence;
  const rows = Object.keys(varsState).sort()
    .map((name) => envVarRowHtml(name, varsState[name].value, varsState[name].enabled)).join("");
  editor.innerHTML = `
    <div id="envVarsTableWrap">
      <table>
        <thead><tr><th style="width:26px"></th><th>Variable</th><th>Value</th><th style="width:30px"></th></tr></thead>
        <tbody id="envVarsBody">${rows}</tbody>
      </table>
    </div>
    <textarea class="hidden" id="envVarsBulkEditor"
              placeholder='{&#10;  "url": "https://dev.nucleus.oak...",&#10;  "username": "operator"&#10;}'></textarea>
    <div class="row-actions" style="border:0;padding:10px 0 0;justify-content:flex-start">
      <button class="btn" id="envAddVarBtn" type="button">+ Variable</button>
      <button class="btn" id="envBulkEditBtn" type="button">Bulk Edit</button>
    </div>
    <div class="hint plain hidden" id="envBulkEditHint">Replaces every <b>enabled</b> variable in this environment
      with what's in the JSON above. Disabled variables aren't shown here and are left untouched.</div>
  `;
  editor.querySelectorAll("#envVarsBody tr").forEach((row) => wireEnvVarRow(slug, row));
  $("envAddVarBtn").addEventListener("click", () => addBlankEnvVarRow(slug));
  $("envBulkEditBtn").addEventListener("click", () => toggleEnvVarsBulkEdit(slug));
}

// --- env vars bulk edit (JSON, not key:value lines — env var values often
// need types/quoting a "Key: Value" line can't express cleanly,
// and this is what was asked for: paste a JSON object, it just takes it) ---

function toggleEnvVarsBulkEdit(slug) {
  const bulkArea = $("envVarsBulkEditor");
  const bulkBtn = $("envBulkEditBtn");
  const entering = bulkArea.classList.contains("hidden");
  if (entering) {
    enterEnvVarsBulkEdit(slug, bulkArea, bulkBtn);
  } else {
    exitEnvVarsBulkEdit(slug, bulkArea, bulkBtn);
  }
}

// Reads straight from the rendered rows rather than re-fetching — the rows
// are always this table's live, current-as-of-right-now state (rendering
// them is the ONLY thing that ever populates them), whereas a fetch here
// raced against a just-triggered row save (e.g. mousedown on this very
// button blurs whatever row you were editing, kicking off an unawaited
// PUT) and could show — or on "Done", act on — data from before that save
// landed.
function enterEnvVarsBulkEdit(slug, bulkArea, bulkBtn) {
  const enabledOnly = {};
  for (const row of $("envVarsBody").querySelectorAll("tr")) {
    if (!row.dataset.name) continue; // unsaved blank row — nothing to include yet
    if (!row.querySelector(".env-var-enabled").checked) continue;
    enabledOnly[row.dataset.name] = row.querySelector(".env-var-value").value;
  }
  bulkArea.value = JSON.stringify(enabledOnly, null, 2);
  $("envVarsTableWrap").classList.add("hidden");
  $("envAddVarBtn").classList.add("hidden");
  $("envBulkEditHint").classList.remove("hidden");
  bulkArea.classList.remove("hidden");
  bulkBtn.textContent = "Done";
}

async function exitEnvVarsBulkEdit(slug, bulkArea, bulkBtn) {
  let parsed;
  try {
    parsed = JSON.parse(bulkArea.value || "{}");
  } catch (error) {
    alert(`Invalid JSON: ${error.message}`);
    return;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    alert("Paste a flat JSON object of variable name/value pairs, e.g. {\"url\": \"...\"}.");
    return;
  }
  for (const [name, value] of Object.entries(parsed)) {
    if (value !== null && typeof value === "object") {
      alert(`Variable "${name}" must be a plain string/number/boolean value, not an object or array.`);
      return;
    }
  }
  await applyEnvVarsBulkJson(slug, parsed);
  bulkArea.classList.add("hidden");
  $("envVarsTableWrap").classList.remove("hidden");
  $("envAddVarBtn").classList.remove("hidden");
  $("envBulkEditHint").classList.add("hidden");
  bulkBtn.textContent = "Bulk Edit";
}

// Full-replace semantics for the enabled set, mirroring the headers Bulk
// Edit: whatever's left in the box when you click Done becomes the new
// enabled-variable set. A previously-enabled variable dropped from the JSON
// gets deleted (after a confirm naming what's about to go, matching the
// single-row delete's own confirm); disabled variables were never shown
// here, so a JSON key that happens to collide with a disabled variable's
// name is skipped rather than silently overwriting a value the user
// couldn't see in this view.
//
// Reads the enabled/disabled split from the DOM rows (still present, just
// CSS-hidden, under the bulk textarea) rather than re-fetching — nothing
// reachable while bulk mode is open can change the environment's vars out
// from under it (the +Variable button and per-row controls are hidden too),
// so those rows are exactly as current as a fresh fetch would be, without
// the fetch's own race against a save still in flight from the moment bulk
// mode was entered.
async function applyEnvVarsBulkJson(slug, parsed) {
  const enabledRowNames = new Set();
  const disabledNames = new Set();
  for (const row of $("envVarsBody").querySelectorAll("tr")) {
    if (!row.dataset.name) continue;
    if (row.querySelector(".env-var-enabled").checked) enabledRowNames.add(row.dataset.name);
    else disabledNames.add(row.dataset.name);
  }
  const collidesWithDisabled = Object.keys(parsed).filter((name) => disabledNames.has(name));
  if (collidesWithDisabled.length) {
    alert(`Skipping ${collidesWithDisabled.join(", ")} — disabled in this environment, not editable from Bulk Edit. Use the table view (checkbox) to change them.`);
  }
  const nextNames = new Set(Object.keys(parsed).filter((name) => !disabledNames.has(name)));
  const toDelete = [...enabledRowNames].filter((name) => !nextNames.has(name));
  if (toDelete.length && !(await irisConfirm(`This will delete ${toDelete.length} variable(s) not present in the JSON: ${toDelete.join(", ")}. Continue?`))) {
    return;
  }
  for (const name of toDelete) {
    await fetch(`/api/environments/${encodeURIComponent(slug)}/vars/${encodeURIComponent(name)}`, { method: "DELETE" });
  }
  const updates = {};
  for (const [name, value] of Object.entries(parsed)) {
    if (disabledNames.has(name)) continue;
    updates[name] = String(value);
  }
  if (Object.keys(updates).length) await putJson(`/api/environments/${encodeURIComponent(slug)}/vars`, updates);
  if (environmentState.activeSlug === slug) await setActiveEnvironment(slug);
  renderEnvEditor();
}

// Wires one <tr> (from envVarRowHtml) for both the initial full render and a
// single row appended later by addBlankEnvVarRow — an unsaved new row has
// data-name="", which the name/value handlers below treat as "create" instead
// of "rename"/"update".
function wireEnvVarRow(slug, row) {
  row.querySelector(".env-var-enabled").addEventListener("change", (event) => {
    const name = row.dataset.name;
    if (!name) return; // nothing persisted yet to toggle
    setEnvVarEnabled(slug, name, event.target.checked);
  });
  const nameInput = row.querySelector(".env-var-name");
  const valueInput = row.querySelector(".env-var-value");
  nameInput.addEventListener("change", (event) => {
    const oldName = row.dataset.name;
    const newName = event.target.value.trim();
    if (!newName) { event.target.value = oldName; return; }
    // Stashed on the row so the Value field's own change handler below can
    // await it — without this, a value typed right after the name races
    // this PUT (which fired with whatever the Value field held at THIS
    // instant, often still blank) and can silently lose to it.
    if (!oldName) { row._creatingVar = createEnvVar(slug, newName, valueInput.value, row); return; }
    if (newName === oldName) return;
    renameEnvVar(slug, oldName, newName, valueInput.value);
  });
  // Cleans up an added-then-abandoned blank row (created via + Variable,
  // never actually given a name or value) instead of leaving a dead row
  // sitting in the table until the next full re-render. Scoped to focus
  // actually leaving the row (event.relatedTarget) — without that check,
  // clicking straight from the blank name field into this row's OWN value
  // field (to type the value first) fires this same blur with both fields
  // still empty, deleting the row out from under the click.
  nameInput.addEventListener("blur", (event) => cleanupAbandonedBlankRow(row, nameInput, valueInput, event));
  valueInput.addEventListener("blur", (event) => cleanupAbandonedBlankRow(row, nameInput, valueInput, event));
  valueInput.addEventListener("change", async (event) => {
    // If the name was just committed, createEnvVar's PUT for this row may
    // still be in flight (see the comment at that call site) — waiting for
    // it here guarantees this save (the value the user actually typed)
    // always lands after it, instead of racing it on the wire.
    if (row._creatingVar) await row._creatingVar.catch(() => {});
    const name = row.dataset.name || nameInput.value.trim();
    if (!name) return; // no name committed yet — nothing to persist
    saveEnvVar(slug, name, event.target.value);
  });
  row.querySelector(".env-var-delete").addEventListener("click", async () => {
    const name = row.dataset.name;
    if (!name) { row.remove(); return; } // unsaved row — just drop it
    if (await irisConfirm(`Delete variable "${name}"?`)) deleteEnvVar(slug, name);
  });
}

// "+ Variable": drop a blank editable row straight into the
// table instead of two browser prompt() dialogs.
function addBlankEnvVarRow(slug) {
  const body = $("envVarsBody");
  body.insertAdjacentHTML("beforeend", envVarRowHtml("", "", true));
  const row = body.lastElementChild;
  wireEnvVarRow(slug, row);
  row.querySelector(".env-var-name").focus();
}

// Shared by the name and value blur handlers in wireEnvVarRow — only ever
// removes a row that's still unsaved (no dataset.name) AND whose blur is
// genuinely leaving the row, not just moving focus from one of its own
// fields to the other (checked via event.relatedTarget).
function cleanupAbandonedBlankRow(row, nameInput, valueInput, event) {
  if (row.dataset.name) return; // already saved — never auto-remove
  if (row.dataset.saving) return; // createEnvVar's PUT is in flight for this row
  if (row.contains(event.relatedTarget)) return;
  // The whole window/app lost focus (switching apps, e.g. to go copy a
  // value from somewhere else) rather than the user clicking away from this
  // row within Iris itself — blur still fires on the focused input either
  // way, but only the latter means the row was actually abandoned.
  if (!document.hasFocus()) return;
  if (!nameInput.value.trim() && !valueInput.value.trim()) row.remove();
}

// Never reads or shows the variable's value here, even for a secret —
// only whether the name diverges and which environment names define it
// (see environment_store.divergence(), which computes this server-side so
// no other environment's secret value ever has to reach this code at all).
function envVarDivergenceBadgeHtml(name) {
  const divergence = environmentState.divergence[name];
  if (!divergence) return "";
  const count = divergence.environmentNames.length;
  const tooltip = `Present in: ${divergence.environmentNames.join(", ")}`;
  return `<span class="badge" title="${escapeAttr(tooltip)}">Differs across ${count} environments</span>`;
}

function envVarRowHtml(name, value, enabled) {
  const isSecret = SECRET_NAME_PATTERN.test(name);
  return `
    <tr data-name="${escapeAttr(name)}" class="${enabled ? "" : "row-disabled"}">
      <td><input type="checkbox" class="env-var-enabled" ${enabled ? "checked" : ""} title="Enabled"></td>
      <td><input class="hdr-value env-var-name mono" type="text" maxlength="256" value="${escapeAttr(name)}">${envVarDivergenceBadgeHtml(name)}</td>
      <td>
        <input class="hdr-value env-var-value" type="${isSecret ? "password" : "text"}" value="${escapeAttr(value)}">
        ${isSecret ? '<span class="console-var-secret-label">stored in Keychain</span>' : ""}
      </td>
      <td><button class="icon-btn env-var-delete" type="button" title="Delete">&times;</button></td>
    </tr>
  `;
}

async function saveEnvVar(slug, name, value) {
  await putJson(`/api/environments/${encodeURIComponent(slug)}/vars`, { [name]: value });
  if (environmentState.activeSlug === slug) await setActiveEnvironment(slug);
  renderEnvEditor();
}

// Creating a variable is triggered by committing its NAME (blur/Enter on the
// name field) — which is typically the split second before the user tabs
// into the Value field to type the actual value. saveEnvVar's full
// renderEnvEditor() rebuild landing right then (this is a network round
// trip) would yank focus out of that field and discard whatever was typed
// in the meantime, and would persist whatever the Value field held at the
// moment the name was committed — usually still empty. So this patches the
// row in place instead: no rebuild, no focus loss. The row does stay out of
// alphabetical order until the next full render for some other reason —
// an accepted, purely cosmetic trade-off against losing what the user types.
async function createEnvVar(slug, name, value, row) {
  // Committing the name (blur/Enter) kicks off this PUT, but the row's
  // dataset.name isn't set until it resolves below — the row's own blur
  // handler (fired synchronously right after this starts, e.g. tabbing
  // straight into another field) would otherwise see an unsaved-looking
  // blank row mid-flight and delete it out from under this request.
  row.dataset.saving = "1";
  try {
    await putJson(`/api/environments/${encodeURIComponent(slug)}/vars`, { [name]: value });
  } catch (error) {
    alert(`Could not save variable: ${error.message}`);
    return;
  } finally {
    delete row.dataset.saving;
  }
  row.dataset.name = name;
  // This patches the row in place instead of going through
  // renderEnvEditor() (see the comment above the call site), which is the
  // only path that leaves an input's defaultValue behind its actual saved
  // value — resync both here so a later Cancel-triggered discard reverts to
  // what was just persisted, not to the blank row's original defaultValue.
  const nameInput = row.querySelector(".env-var-name");
  const valueInput = row.querySelector(".env-var-value");
  nameInput.defaultValue = name;
  valueInput.defaultValue = value;
  if (SECRET_NAME_PATTERN.test(name)) {
    valueInput.type = "password";
    if (!row.querySelector(".console-var-secret-label")) {
      valueInput.insertAdjacentHTML("afterend", '<span class="console-var-secret-label">stored in Keychain</span>');
    }
  }
  if (environmentState.activeSlug === slug) await setActiveEnvironment(slug);
}

async function renameEnvVar(slug, oldName, newName, value) {
  try {
    await fetch(`/api/environments/${encodeURIComponent(slug)}/vars/${encodeURIComponent(oldName)}`, { method: "DELETE" });
    await saveEnvVar(slug, newName, value);
  } catch (error) {
    alert(`Rename failed: ${error.message}`);
    renderEnvEditor();
  }
}

async function deleteEnvVar(slug, name) {
  await fetch(`/api/environments/${encodeURIComponent(slug)}/vars/${encodeURIComponent(name)}`, { method: "DELETE" });
  if (environmentState.activeSlug === slug) await setActiveEnvironment(slug);
  renderEnvEditor();
}

async function setEnvVarEnabled(slug, name, enabled) {
  await fetch(`/api/environments/${encodeURIComponent(slug)}/vars/${encodeURIComponent(name)}/enabled`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (environmentState.activeSlug === slug) await setActiveEnvironment(slug);
  renderEnvEditor();
}

async function createEnvironment() {
  const name = ((await irisPrompt("New environment name:")) || "").trim();
  if (!name) return;
  try {
    const data = await postJson("/api/environments", { name });
    await loadEnvironmentList();
    environmentState.editingSlug = data.slug;
    renderEnvList();
    renderEnvEditor();
  } catch (error) {
    alert(`Could not create environment: ${error.message}`);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadEnvironmentList();
  $("envSelect").addEventListener("change", (event) => setActiveEnvironment(event.target.value));
  $("manageEnvBtn").addEventListener("click", openEnvModal);
  $("envModalClose").addEventListener("click", closeEnvModal);
  $("envCreateBtn").addEventListener("click", createEnvironment);
  $("envModal").addEventListener("click", (event) => {
    if (event.target.id === "envModal") closeEnvModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("envModal").classList.contains("hidden")) closeEnvModal();
  });
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    setActiveEnvironment, environmentState, cleanupAbandonedBlankRow, createEnvVar, wireEnvVarRow,
    envVarRowHtml, envVarDivergenceBadgeHtml, fetchDivergence,
  };
}
