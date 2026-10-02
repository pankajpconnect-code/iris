const test = require("node:test");
const assert = require("node:assert/strict");

global.document = { addEventListener: () => {} };
const {
  AUTH_KEYS, authPayloadFields, authBadgeLabel, isAuthKey, resolvedAuthVars, renderAuthTab,
  isDisplayingBorrowedAuth, saveAuthTab,
} = require("./request-auth.js");

// Minimal fake DOM: renderAuthTab/syncAuthVisibility/updateAuthBadge only
// ever read/write .value, .checked, .textContent and toggle classes — a real
// DOM (or a heavier framework mock) isn't needed to prove the precedence
// rule renders correctly.
function makeFakeDom() {
  const elements = new Map();
  const makeElement = () => ({
    value: "",
    checked: false,
    textContent: "",
    classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
  });
  return (id) => {
    if (!elements.has(id)) elements.set(id, makeElement());
    return elements.get(id);
  };
}

test("isAuthKey: true for every key in AUTH_KEYS", () => {
  Object.values(AUTH_KEYS).forEach((key) => assert.equal(isAuthKey(key), true));
});

test("isAuthKey: false for a plain collection variable name", () => {
  assert.equal(isAuthKey("myVariable"), false);
});

test("authBadgeLabel: empty string when no auth vars are saved at all", () => {
  assert.equal(authBadgeLabel({}), "");
});

test("authBadgeLabel: empty string for explicit none mode", () => {
  assert.equal(authBadgeLabel({ [AUTH_KEYS.mode]: "none" }), "");
});

test("authBadgeLabel: short label for each real auth mode", () => {
  assert.equal(authBadgeLabel({ [AUTH_KEYS.mode]: "oauth2-client-credentials" }), "OAuth2");
  assert.equal(authBadgeLabel({ [AUTH_KEYS.mode]: "bearer" }), "Bearer");
  assert.equal(authBadgeLabel({ [AUTH_KEYS.mode]: "basic" }), "Basic");
  assert.equal(authBadgeLabel({ [AUTH_KEYS.mode]: "apikey" }), "API Key");
  assert.equal(authBadgeLabel({ [AUTH_KEYS.mode]: "refresh-cookie" }), "Cookie→Bearer");
});

test("authPayloadFields: forwards all five oauth2 fields from vars", () => {
  const vars = {
    [AUTH_KEYS.mode]: "oauth2-client-credentials",
    [AUTH_KEYS.oauth2ClientId]: "cid",
    [AUTH_KEYS.oauth2ClientSecret]: "csecret",
    [AUTH_KEYS.oauth2TokenUrl]: "https://idp.example/token",
    [AUTH_KEYS.oauth2Scope]: "read write",
    [AUTH_KEYS.oauth2AuthStyle]: "basic-header",
  };

  const result = authPayloadFields(vars);

  assert.equal(result.authMode, "oauth2-client-credentials");
  assert.equal(result.oauth2ClientId, "cid");
  assert.equal(result.oauth2ClientSecret, "csecret");
  assert.equal(result.oauth2TokenUrl, "https://idp.example/token");
  assert.equal(result.oauth2Scope, "read write");
  assert.equal(result.oauth2AuthStyle, "basic-header");
});

test("authPayloadFields: defaults oauth2 fields to empty strings when unset", () => {
  const result = authPayloadFields({});

  assert.equal(result.oauth2ClientId, "");
  assert.equal(result.oauth2ClientSecret, "");
  assert.equal(result.oauth2TokenUrl, "");
  assert.equal(result.oauth2Scope, "");
  assert.equal(result.oauth2AuthStyle, "");
});

test("authPayloadFields: forwards apikey fields from vars", () => {
  const vars = {
    [AUTH_KEYS.mode]: "apikey",
    [AUTH_KEYS.apiKeyName]: "X-Api-Key",
    [AUTH_KEYS.apiKeyValue]: "s3cret",
    [AUTH_KEYS.apiKeyLocation]: "query",
  };

  const result = authPayloadFields(vars);

  assert.equal(result.authMode, "apikey");
  assert.equal(result.apiKeyName, "X-Api-Key");
  assert.equal(result.apiKeyValue, "s3cret");
  assert.equal(result.apiKeyLocation, "query");
});

test("authPayloadFields: defaults apiKeyLocation to header when unset", () => {
  const result = authPayloadFields({});

  assert.equal(result.apiKeyName, "");
  assert.equal(result.apiKeyValue, "");
  assert.equal(result.apiKeyLocation, "header");
});

// --- resolvedAuthVars: the precedence rule between shared collection auth
// (consoleState.vars, edited via the Auth tab) and a single imported
// request's own `.auth` ---

test("resolvedAuthVars: passthrough unchanged when the request has no auth of its own", () => {
  const vars = { [AUTH_KEYS.mode]: "none" };
  assert.deepEqual(resolvedAuthVars(vars, { name: "r" }), vars);
});

test("resolvedAuthVars: passthrough unchanged when there is no selected request at all", () => {
  const vars = { [AUTH_KEYS.mode]: "none" };
  assert.deepEqual(resolvedAuthVars(vars, null), vars);
});

test("resolvedAuthVars: falls back to the request's own bearer auth when shared mode is absent", () => {
  const result = resolvedAuthVars({}, { auth: { mode: "bearer", bearerToken: "abc" } });
  assert.equal(result[AUTH_KEYS.mode], "bearer");
  assert.equal(result[AUTH_KEYS.bearerToken], "abc");
});

test("resolvedAuthVars: falls back to the request's own auth when shared mode is explicitly 'none'", () => {
  const vars = { [AUTH_KEYS.mode]: "none" };
  const result = resolvedAuthVars(vars, { auth: { mode: "bearer", bearerToken: "abc" } });
  assert.equal(result[AUTH_KEYS.mode], "bearer");
  assert.equal(result[AUTH_KEYS.bearerToken], "abc");
});

test("resolvedAuthVars: maps basic and apikey request auth fields too", () => {
  const basic = resolvedAuthVars({}, { auth: { mode: "basic", basicUser: "u", basicPassword: "p" } });
  assert.equal(basic[AUTH_KEYS.mode], "basic");
  assert.equal(basic[AUTH_KEYS.basicUser], "u");
  assert.equal(basic[AUTH_KEYS.basicPassword], "p");

  const apiKey = resolvedAuthVars({}, { auth: { mode: "apikey", apiKeyName: "X-Key", apiKeyValue: "v", apiKeyLocation: "query" } });
  assert.equal(apiKey[AUTH_KEYS.mode], "apikey");
  assert.equal(apiKey[AUTH_KEYS.apiKeyName], "X-Key");
  assert.equal(apiKey[AUTH_KEYS.apiKeyValue], "v");
  assert.equal(apiKey[AUTH_KEYS.apiKeyLocation], "query");
});

test("resolvedAuthVars: shared auth wins over the request's own when already configured", () => {
  const vars = { [AUTH_KEYS.mode]: "basic", [AUTH_KEYS.basicUser]: "shared-user" };
  const result = resolvedAuthVars(vars, { auth: { mode: "bearer", bearerToken: "abc" } });
  assert.equal(result[AUTH_KEYS.mode], "basic");
  assert.equal(result[AUTH_KEYS.basicUser], "shared-user");
});

// --- authPayloadFields: the same precedence rule, but as what Send actually
// forwards to /api/send-one when called live (no explicit vars argument) ---

test("authPayloadFields: uses the request's own auth when called live with no shared auth set", () => {
  global.consoleState = { vars: {}, selectedRequest: { auth: { mode: "bearer", bearerToken: "abc" } } };
  const result = authPayloadFields();
  assert.equal(result.authMode, "bearer");
  assert.equal(result.bearerToken, "abc");
  delete global.consoleState;
});

test("authPayloadFields: shared auth still wins when called live and already configured", () => {
  global.consoleState = {
    vars: { [AUTH_KEYS.mode]: "basic", [AUTH_KEYS.basicUser]: "shared" },
    selectedRequest: { auth: { mode: "bearer", bearerToken: "abc" } },
  };
  const result = authPayloadFields();
  assert.equal(result.authMode, "basic");
  assert.equal(result.basicUser, "shared");
  delete global.consoleState;
});

// --- renderAuthTab: the Auth tab form itself, driven through a fake DOM ---

test("renderAuthTab: shows 'No auth' when neither shared nor request auth is set", () => {
  global.$ = makeFakeDom();
  global.consoleState = { vars: {}, selectedRequest: { name: "r" } };
  renderAuthTab();
  assert.equal(global.$("authMode").value, "none");
  assert.equal(global.$("authBearerToken").value, "");
  delete global.consoleState;
  delete global.$;
});

test("renderAuthTab: shows the request's own bearer token when shared auth is unset", () => {
  global.$ = makeFakeDom();
  global.consoleState = { vars: {}, selectedRequest: { auth: { mode: "bearer", bearerToken: "abc123" } } };
  renderAuthTab();
  assert.equal(global.$("authMode").value, "bearer");
  assert.equal(global.$("authBearerToken").value, "abc123");
  delete global.consoleState;
  delete global.$;
});

test("renderAuthTab: shared auth still wins for display when already configured", () => {
  global.$ = makeFakeDom();
  global.consoleState = {
    vars: { [AUTH_KEYS.mode]: "basic", [AUTH_KEYS.basicUser]: "shared-user" },
    selectedRequest: { auth: { mode: "bearer", bearerToken: "abc123" } },
  };
  renderAuthTab();
  assert.equal(global.$("authMode").value, "basic");
  assert.equal(global.$("authBasicUser").value, "shared-user");
  delete global.consoleState;
  delete global.$;
});

test("renderAuthTab: switching requests doesn't leak stale auth between them", () => {
  global.$ = makeFakeDom();
  global.consoleState = { vars: {}, selectedRequest: { auth: { mode: "bearer", bearerToken: "first-token" } } };
  renderAuthTab();
  assert.equal(global.$("authBearerToken").value, "first-token");

  global.consoleState.selectedRequest = { name: "no-auth-request" };
  renderAuthTab();
  assert.equal(global.$("authMode").value, "none");
  assert.equal(global.$("authBearerToken").value, "");
  delete global.consoleState;
  delete global.$;
});

// --- isDisplayingBorrowedAuth / saveAuthTab: guarding against silently
// promoting a single request's own (borrowed) auth into the shared auth for
// the whole collection ---

test("isDisplayingBorrowedAuth: true when shared auth is unset and the request has its own", () => {
  assert.equal(isDisplayingBorrowedAuth({}, { auth: { mode: "bearer", bearerToken: "abc" } }), true);
});

test("isDisplayingBorrowedAuth: false when shared auth is already configured", () => {
  const vars = { [AUTH_KEYS.mode]: "basic" };
  assert.equal(isDisplayingBorrowedAuth(vars, { auth: { mode: "bearer", bearerToken: "abc" } }), false);
});

test("isDisplayingBorrowedAuth: false when the request has no auth of its own", () => {
  assert.equal(isDisplayingBorrowedAuth({}, { name: "r" }), false);
  assert.equal(isDisplayingBorrowedAuth({}, null), false);
});

test("saveAuthTab: saves immediately, with no confirmation prompt, when displaying real shared auth", async () => {
  global.$ = makeFakeDom();
  let confirmCalls = 0;
  global.irisConfirm = async () => { confirmCalls += 1; return true; };
  const putCalls = [];
  global.putJson = async (url, body) => { putCalls.push({ url, body }); return { variables: body }; };
  global.updateTopbarPills = () => {};
  global.consoleState = {
    selectedCollectionSlug: "col",
    vars: { [AUTH_KEYS.mode]: "basic" },
    selectedRequest: { auth: { mode: "bearer", bearerToken: "borrowed" } },
  };

  await saveAuthTab();

  assert.equal(confirmCalls, 0);
  assert.equal(putCalls.length, 1);
  delete global.consoleState;
  delete global.irisConfirm;
  delete global.putJson;
  delete global.updateTopbarPills;
  delete global.$;
});

test("saveAuthTab: requires confirmation before saving borrowed auth, and skips the save if declined", async () => {
  global.$ = makeFakeDom();
  let confirmCalls = 0;
  global.irisConfirm = async () => { confirmCalls += 1; return false; };
  const putCalls = [];
  global.putJson = async (url, body) => { putCalls.push({ url, body }); return { variables: body }; };
  global.updateTopbarPills = () => {};
  global.consoleState = {
    selectedCollectionSlug: "col",
    vars: {},
    selectedRequest: { auth: { mode: "bearer", bearerToken: "borrowed" } },
  };

  await saveAuthTab();

  assert.equal(confirmCalls, 1);
  assert.equal(putCalls.length, 0, "declining the confirmation must not save anything");
  delete global.consoleState;
  delete global.irisConfirm;
  delete global.putJson;
  delete global.updateTopbarPills;
  delete global.$;
});

test("saveAuthTab: proceeds with the save once the borrowed-auth confirmation is accepted", async () => {
  global.$ = makeFakeDom();
  let confirmCalls = 0;
  global.irisConfirm = async () => { confirmCalls += 1; return true; };
  const putCalls = [];
  global.putJson = async (url, body) => { putCalls.push({ url, body }); return { variables: body }; };
  global.updateTopbarPills = () => {};
  global.consoleState = {
    selectedCollectionSlug: "col",
    vars: {},
    selectedRequest: { auth: { mode: "bearer", bearerToken: "borrowed" } },
  };

  await saveAuthTab();

  assert.equal(confirmCalls, 1);
  assert.equal(putCalls.length, 1);
  delete global.consoleState;
  delete global.irisConfirm;
  delete global.putJson;
  delete global.updateTopbarPills;
  delete global.$;
});
