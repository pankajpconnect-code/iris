// Auth tab: shared collection auth (consoleState.vars) with a fallback to a
// single imported request's own borrowed `.auth` — split out of
// static/request-tabs.js to keep that file under this repo's 500-line cap.

const AUTH_KEYS = {
  mode: "__authMode",
  url: "__authIdentityUrl",
  tenant: "__authTenant",
  user: "__authUser",
  refreshSecret: "__authRefreshSecret",
  refreshEachRow: "__authRefreshEachRow",
  bearerToken: "__authBearerToken",
  basicUser: "__authBasicUser",
  basicPassword: "__authBasicPassword",
  apiKeyName: "__authApiKeyName",
  apiKeyValue: "__authApiKeyValue",
  apiKeyLocation: "__authApiKeyLocation",
  oauth2ClientId: "__authOauth2ClientId",
  oauth2ClientSecret: "__authOauth2ClientSecret",
  oauth2TokenUrl: "__authOauth2TokenUrl",
  oauth2Scope: "__authOauth2Scope",
  oauth2AuthStyle: "__authOauth2AuthStyle",
};
// Short forms of the <select id="authMode"> option labels (templates/index.html) —
// used wherever auth needs to be surfaced compactly (tab badge, topbar pill).
const AUTH_MODE_LABELS = {
  "refresh-cookie": "Cookie→Bearer",
  bearer: "Bearer",
  basic: "Basic",
  apikey: "API Key",
  "oauth2-client-credentials": "OAuth2",
};

function isAuthKey(name) {
  return Object.values(AUTH_KEYS).includes(name);
}

// Shared collection auth (consoleState.vars, edited via the Auth tab) is
// still the primary mechanism and always wins once configured. But an
// imported request's own `.auth` (no editor of its own — see AGENTS.md
// Phase 0) was being silently ignored everywhere: the Auth tab showed "No
// auth" and Send attached no Authorization header, even though the request's
// real credentials were sitting right there in its own `.auth` field. This
// fills that gap — used by both renderAuthTab (display) and
// authPayloadFields (Send) — without touching precedence for any collection
// that already relies on shared auth today.
// True exactly when the Auth tab is (or would be) showing `request`'s own
// borrowed auth rather than the collection's real shared auth — i.e. the
// fallback in resolvedAuthVars below actually applies. saveAuthTab() reuses
// this same condition to stop that borrowed, editable-looking auth from
// being silently promoted into the shared auth for the whole collection.
function isDisplayingBorrowedAuth(vars, request) {
  const sharedMode = vars[AUTH_KEYS.mode] || "none";
  const requestAuth = request && request.auth;
  return sharedMode === "none" && !!requestAuth && !!requestAuth.mode && requestAuth.mode !== "none";
}

function resolvedAuthVars(vars, request) {
  if (!isDisplayingBorrowedAuth(vars, request)) {
    return vars;
  }
  const requestAuth = request.auth;
  const overrides = { [AUTH_KEYS.mode]: requestAuth.mode };
  if (requestAuth.mode === "bearer") {
    overrides[AUTH_KEYS.bearerToken] = requestAuth.bearerToken || "";
  } else if (requestAuth.mode === "basic") {
    overrides[AUTH_KEYS.basicUser] = requestAuth.basicUser || "";
    overrides[AUTH_KEYS.basicPassword] = requestAuth.basicPassword || "";
  } else if (requestAuth.mode === "apikey") {
    overrides[AUTH_KEYS.apiKeyName] = requestAuth.apiKeyName || "";
    overrides[AUTH_KEYS.apiKeyValue] = requestAuth.apiKeyValue || "";
    overrides[AUTH_KEYS.apiKeyLocation] = requestAuth.apiKeyLocation || "header";
  }
  return { ...vars, ...overrides };
}

function renderAuthTab() {
  const v = resolvedAuthVars(consoleState.vars, consoleState.selectedRequest);
  const mode = v[AUTH_KEYS.mode] || "none";
  $("authMode").value = mode;
  $("authUrl").value = v[AUTH_KEYS.url] || "";
  $("authTenant").value = v[AUTH_KEYS.tenant] || "";
  $("authUser").value = v[AUTH_KEYS.user] || "";
  $("authRefreshSecret").value = v[AUTH_KEYS.refreshSecret] || "";
  $("authRefreshEachRow").checked = v[AUTH_KEYS.refreshEachRow] === "true";
  $("authBearerToken").value = v[AUTH_KEYS.bearerToken] || "";
  $("authBasicUser").value = v[AUTH_KEYS.basicUser] || "";
  $("authBasicPassword").value = v[AUTH_KEYS.basicPassword] || "";
  $("authApiKeyName").value = v[AUTH_KEYS.apiKeyName] || "";
  $("authApiKeyValue").value = v[AUTH_KEYS.apiKeyValue] || "";
  $("authApiKeyLocation").value = v[AUTH_KEYS.apiKeyLocation] || "header";
  $("authOauth2ClientId").value = v[AUTH_KEYS.oauth2ClientId] || "";
  $("authOauth2ClientSecret").value = v[AUTH_KEYS.oauth2ClientSecret] || "";
  $("authOauth2TokenUrl").value = v[AUTH_KEYS.oauth2TokenUrl] || "";
  $("authOauth2Scope").value = v[AUTH_KEYS.oauth2Scope] || "";
  $("authOauth2AuthStyle").value = v[AUTH_KEYS.oauth2AuthStyle] || "basic-header";
  syncAuthVisibility();
  updateAuthBadge();
}

// Auth lives on the collection (consoleState.vars), not the per-tab draft, so a
// brand-new "Untitled Request" silently carries whatever real credentials the
// collection already has saved — this badge is the only cue on the tab strip
// that Send will actually use them. Called from both renderAuthTab (tab
// switch/collection load) and saveAuthTab (editing without switching away),
// matching the updateHeaderCountBadge/updateParamCountBadge convention.
function updateAuthBadge() {
  $("tabAuthCount").textContent = authBadgeLabel(consoleState.vars);
}

function authBadgeLabel(vars) {
  const mode = vars[AUTH_KEYS.mode] || "none";
  return AUTH_MODE_LABELS[mode] || "";
}

function syncAuthVisibility() {
  const mode = $("authMode").value;
  $("authRefreshFields").classList.toggle("hidden", mode !== "refresh-cookie");
  $("authBearerFields").classList.toggle("hidden", mode !== "bearer");
  $("authBasicFields").classList.toggle("hidden", mode !== "basic");
  $("authApiKeyFields").classList.toggle("hidden", mode !== "apikey");
  $("authOauth2Fields").classList.toggle("hidden", mode !== "oauth2-client-credentials");
}

async function saveAuthTab() {
  const slug = consoleState.selectedCollectionSlug;
  if (!slug) {
    alert("Select or create a collection in the sidebar first.");
    return;
  }
  // Before the borrowed-auth fallback existed, whatever this form showed was
  // always the real shared auth, so saving it was never ambiguous. Now it can
  // be showing a single request's own auth instead (shared unset) — saving
  // that as-is would silently promote one request's credentials into the
  // shared auth for every request in the collection.
  if (isDisplayingBorrowedAuth(consoleState.vars, consoleState.selectedRequest)) {
    const proceed = await irisConfirm(
      "This is showing this request's own auth, not the collection's shared auth. Saving will set it as the shared auth for every request in this collection. Continue?"
    );
    if (!proceed) return;
  }
  const updates = {
    [AUTH_KEYS.mode]: $("authMode").value,
    [AUTH_KEYS.url]: $("authUrl").value.trim(),
    [AUTH_KEYS.tenant]: $("authTenant").value.trim(),
    [AUTH_KEYS.user]: $("authUser").value.trim(),
    [AUTH_KEYS.refreshSecret]: $("authRefreshSecret").value,
    [AUTH_KEYS.refreshEachRow]: String($("authRefreshEachRow").checked),
    [AUTH_KEYS.bearerToken]: $("authBearerToken").value,
    [AUTH_KEYS.basicUser]: $("authBasicUser").value.trim(),
    [AUTH_KEYS.basicPassword]: $("authBasicPassword").value,
    [AUTH_KEYS.apiKeyName]: $("authApiKeyName").value.trim(),
    [AUTH_KEYS.apiKeyValue]: $("authApiKeyValue").value,
    [AUTH_KEYS.apiKeyLocation]: $("authApiKeyLocation").value,
    [AUTH_KEYS.oauth2ClientId]: $("authOauth2ClientId").value.trim(),
    [AUTH_KEYS.oauth2ClientSecret]: $("authOauth2ClientSecret").value,
    [AUTH_KEYS.oauth2TokenUrl]: $("authOauth2TokenUrl").value.trim(),
    [AUTH_KEYS.oauth2Scope]: $("authOauth2Scope").value.trim(),
    [AUTH_KEYS.oauth2AuthStyle]: $("authOauth2AuthStyle").value,
  };
  try {
    const data = await putJson(`/api/collections/${encodeURIComponent(slug)}/vars`, updates);
    consoleState.vars = data.variables || consoleState.vars;
    updateTopbarPills();
    updateAuthBadge();
  } catch (error) {
    alert(`Could not save auth settings: ${error.message}`);
  }
}

function authPayloadFields(vars) {
  // No explicit `vars` means a live call (Send) — apply the same shared/
  // request-auth fallback the Auth tab renders, so what Send attaches always
  // matches what the Auth tab is showing. An explicit `vars` (e.g. the
  // Runner passing its own run-wide vars) bypasses the fallback: there's no
  // single "current request" for it to fall back to.
  const v = vars || resolvedAuthVars(consoleState.vars, consoleState.selectedRequest);
  return {
    authMode: v[AUTH_KEYS.mode] || "none",
    tokenUrl: v[AUTH_KEYS.url] || "",
    tenant: v[AUTH_KEYS.tenant] || "",
    user: v[AUTH_KEYS.user] || "",
    refreshToken: v[AUTH_KEYS.refreshSecret] || "",
    bearerToken: v[AUTH_KEYS.bearerToken] || "",
    refreshTokenEachRow: v[AUTH_KEYS.refreshEachRow] === "true",
    basicUser: v[AUTH_KEYS.basicUser] || "",
    basicPassword: v[AUTH_KEYS.basicPassword] || "",
    apiKeyName: v[AUTH_KEYS.apiKeyName] || "",
    apiKeyValue: v[AUTH_KEYS.apiKeyValue] || "",
    apiKeyLocation: v[AUTH_KEYS.apiKeyLocation] || "header",
    oauth2ClientId: v[AUTH_KEYS.oauth2ClientId] || "",
    oauth2ClientSecret: v[AUTH_KEYS.oauth2ClientSecret] || "",
    oauth2TokenUrl: v[AUTH_KEYS.oauth2TokenUrl] || "",
    oauth2Scope: v[AUTH_KEYS.oauth2Scope] || "",
    oauth2AuthStyle: v[AUTH_KEYS.oauth2AuthStyle] || "",
  };
}

function updateTopbarPills() {
  const collection = consoleState.selectedCollection;
  $("topbarTenant").textContent = collection ? (consoleState.vars[AUTH_KEYS.tenant] || collection.name) : "no collection";
  const mode = consoleState.vars[AUTH_KEYS.mode] || "none";
  $("topbarAuth").textContent = collection ? `auth: ${AUTH_MODE_LABELS[mode] || mode}` : "auth: —";
}

document.addEventListener("DOMContentLoaded", () => {
  $("authMode").addEventListener("change", syncAuthVisibility);
  $("saveAuthBtn").addEventListener("click", saveAuthTab);
  renderAuthTab();
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    AUTH_KEYS, authPayloadFields, authBadgeLabel, isAuthKey,
    resolvedAuthVars, renderAuthTab, isDisplayingBorrowedAuth, saveAuthTab,
  };
}
