const test = require("node:test");
const assert = require("node:assert/strict");

global.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
// Defined in console-vars.js (a separate <script> tag in the browser) and
// referenced by environments.js as a bare global — stub it here the same way.
global.SECRET_NAME_PATTERN = /token|secret|password|cookie/i;
// Defined in shared.js (a separate <script> tag in the browser) and
// referenced by environments.js as a bare global — stub it here the same
// way SECRET_NAME_PATTERN is stubbed above.
global.escapeAttr = (value) => String(value);
const fakeElements = {};
global.$ = (id) => fakeElements[id] || (fakeElements[id] = { value: "" });
global.document = { addEventListener: () => {}, createElement: () => ({}), hasFocus: () => true };

const {
  setActiveEnvironment, environmentState, cleanupAbandonedBlankRow, createEnvVar, wireEnvVarRow,
  envVarRowHtml, envVarDivergenceBadgeHtml, fetchDivergence,
} = require("./environments.js");

function fakeBlankRow() {
  let removed = false;
  return {
    row: {
      dataset: {},
      contains: () => false,
      remove: () => { removed = true; },
    },
    nameInput: { value: "" },
    valueInput: { value: "" },
    wasRemoved: () => removed,
  };
}

test("cleanupAbandonedBlankRow: an empty row is removed when focus moves elsewhere within the app", () => {
  const { row, nameInput, valueInput, wasRemoved } = fakeBlankRow();
  document.hasFocus = () => true;
  cleanupAbandonedBlankRow(row, nameInput, valueInput, { relatedTarget: null });
  assert.equal(wasRemoved(), true);
});

test("cleanupAbandonedBlankRow: an empty row survives blur caused by the whole window losing focus", () => {
  // Regression: switching to another app (e.g. to go copy a value) blurs
  // the focused input just like clicking elsewhere in Iris does, but the
  // row wasn't actually abandoned — it must still be there when the user
  // comes back.
  const { row, nameInput, valueInput, wasRemoved } = fakeBlankRow();
  document.hasFocus = () => false;
  cleanupAbandonedBlankRow(row, nameInput, valueInput, { relatedTarget: null });
  assert.equal(wasRemoved(), false);
});

test("setActiveEnvironment: a slower earlier fetch resolving after a later switch does not clobber the newer environment's vars", async () => {
  // Regression for a race caught by an independent review: switching the
  // environment dropdown from A to B before A's /vars fetch resolves used
  // to let A's slower fetch silently overwrite B's vars once it finally
  // resolved, even though the UI (and activeSlug) had already moved on to B.
  let resolveA;
  global.fetch = (url) => {
    if (url.includes("/A/")) {
      return new Promise((resolve) => { resolveA = resolve; });
    }
    return Promise.resolve({ ok: true, json: async () => ({ variables: { b: "1" } }) });
  };

  const pendingA = setActiveEnvironment("A");
  await setActiveEnvironment("B");
  assert.equal(environmentState.activeSlug, "B");
  assert.deepEqual(environmentState.activeVars, { b: "1" });

  resolveA({ ok: true, json: async () => ({ variables: { a: "stale" } }) });
  await pendingA;

  assert.equal(environmentState.activeSlug, "B");
  assert.deepEqual(environmentState.activeVars, { b: "1" });
});

// Regression (caught by independent review): createEnvVar patches a row in
// place instead of re-rendering (to preserve focus/in-flight typing), which
// used to leave the row's inputs at their original blank-row defaultValue
// ("") forever. A later Cancel on that same row (env-modal-footer.js) would
// then discard back to "" instead of the value that was actually just
// saved, silently overwriting it via the same blur -> change -> save path
// Cancel relies on elsewhere.
test("createEnvVar: resyncs the row's defaultValue to what was actually saved", async () => {
  global.putJson = async () => ({});
  const nameInput = { defaultValue: "" };
  const valueInput = { defaultValue: "", type: "text" };
  const row = {
    dataset: {},
    querySelector: (selector) => (selector === ".env-var-name" ? nameInput : valueInput),
  };
  await createEnvVar("dev", "url", "https://real-value", row);
  assert.equal(nameInput.defaultValue, "url");
  assert.equal(valueInput.defaultValue, "https://real-value");
});

// Regression: found during manual verification of a different feature.
// Committing a brand-new row's name fires createEnvVar with whatever the
// Value field held at that instant (often still blank, per the comment on
// createEnvVar above) — if the user immediately types the value afterward,
// that second save (saveEnvVar, fired by the Value field's own change
// event) races the first. Secret-named variables make this far more likely
// to actually bite, since their PUT is slower (Keychain shell-out) than a
// plain var's — whichever request's response lands last wins, so the
// blank-value creation PUT can silently overwrite the real value the user
// just typed.
test("wireEnvVarRow: committing the value right after the name does not race the name-creation save", async () => {
  const calls = [];
  let resolveFirstPut;
  global.putJson = (url, body) => {
    calls.push(body);
    if (calls.length === 1) {
      return new Promise((resolve) => { resolveFirstPut = resolve; });
    }
    return Promise.resolve({});
  };
  global.fetch = () => Promise.resolve({ ok: true, json: async () => ({ variables: {} }) });

  const handlers = {};
  const makeInput = (extra) => ({
    value: "", defaultValue: "", ...extra,
    addEventListener(event, handler) { handlers[`${extra.id}:${event}`] = handler; },
  });
  const nameInput = makeInput({ id: "name" });
  const valueInput = makeInput({ id: "value", type: "text", insertAdjacentHTML: () => {} });
  const enabledInput = { addEventListener: () => {} };
  const deleteBtn = { addEventListener: () => {} };
  const row = {
    dataset: {},
    querySelector: (selector) => ({
      ".env-var-name": nameInput,
      ".env-var-value": valueInput,
      ".env-var-enabled": enabledInput,
      ".env-var-delete": deleteBtn,
      ".console-var-secret-label": null,
    }[selector]),
  };

  wireEnvVarRow("dev", row);

  nameInput.value = "apiSecret";
  handlers["name:change"]({ target: nameInput }); // createEnvVar("dev","apiSecret","", row) — 1st PUT, deliberately left pending
  valueInput.value = "the-real-secret";
  const valueSaved = handlers["value:change"]({ target: valueInput });

  await Promise.resolve();
  await Promise.resolve();
  assert.equal(calls.length, 1, "the value save must wait for the in-flight name-creation PUT, not fire concurrently");

  resolveFirstPut({});
  await valueSaved;

  assert.deepEqual(calls, [{ apiSecret: "" }, { apiSecret: "the-real-secret" }]);
});

test("envVarRowHtml: renders a divergence badge when the name has an entry", () => {
  environmentState.divergence = {
    tenant: { secret: false, environmentNames: ["Dev", "Prod"] },
  };
  const html = envVarRowHtml("tenant", "dev-tenant", true);
  assert.match(html, /class="badge"/);
  assert.match(html, /Differs across 2 environments/);
  assert.match(html, /title="Present in: Dev, Prod"/);
  environmentState.divergence = {};
});

test("envVarRowHtml: renders no badge when the name has no divergence entry", () => {
  environmentState.divergence = {};
  const html = envVarRowHtml("region", "eu-west-1", true);
  assert.doesNotMatch(html, /badge/);
});

// Security-critical: a secret variable's divergence badge must never carry
// its value — only that it differs and which environments define it. The
// row's OWN value input still holds the (masked, type="password") value
// for the environment being edited today, same as before this feature —
// this test is scoped to the badge markup specifically, not the whole row.
test("envVarDivergenceBadgeHtml: never contains the variable's value, secret or not", () => {
  environmentState.divergence = {
    apiToken: { secret: true, environmentNames: ["Dev", "Prod"] },
  };
  const badge = envVarDivergenceBadgeHtml("apiToken");
  assert.match(badge, /Differs across 2 environments/);
  assert.doesNotMatch(badge, /dev-secret-value-123/);
  environmentState.divergence = {};
});

test("fetchDivergence: returns {} when the request fails", async () => {
  global.fetch = () => Promise.reject(new Error("network down"));
  const result = await fetchDivergence();
  assert.deepEqual(result, {});
});

test("fetchDivergence: returns the divergence map on a successful response", async () => {
  global.fetch = () => Promise.resolve({
    ok: true,
    json: async () => ({ divergence: { tenant: { secret: false, environmentNames: ["Dev", "Prod"] } } }),
  });
  const result = await fetchDivergence();
  assert.deepEqual(result, { tenant: { secret: false, environmentNames: ["Dev", "Prod"] } });
});
