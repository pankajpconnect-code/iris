let lastSingleResponse = null;

// A response should only be dropped when the user has genuinely switched to
// a DIFFERENT tab while the request was in flight (or closed the one that
// sent it) — not merely because there was no tab open when Send fired. The
// console is fully usable before any tab exists (the URL/method/body fields
// always work off the live DOM, not a tab draft — see currentConsoleRequest
// in request-tabs.js), so a tab-less send that's still tab-less on return is
// the SAME state, not a stale one, and its result belongs on screen.
function shouldRenderSendResult(tabIdAtSend, currentTab) {
  if (currentTab) return currentTab.id === tabIdAtSend;
  return tabIdAtSend === null;
}

function setSendPending(el, isPending) {
  el.classList.toggle("pending", isPending);
}

async function sendConsoleRequest() {
  // An Overview tab shows collection documentation, not a request — Send
  // must never fire off whatever a hidden, previously-active request tab
  // left sitting in the (still-present, just hidden) form fields.
  if (activeTab() && activeTab().kind === "overview") return;
  const slug = consoleState.selectedCollectionSlug;
  const button = $("sendBtn");
  // Captured up front so the response below only ever paints into the tab
  // that actually sent it — without this, switching tabs while a request is
  // still in flight would paint its (now stale) result into whatever tab the
  // user has since switched to.
  const tabId = activeTab() ? activeTab().id : null;
  $("respSingle").classList.remove("hidden");
  setBusy(button, true);
  // Previously the status dot/text just sat on whatever the LAST response
  // left them at until this one resolved — no feedback at all that a
  // request was actually in flight, and the old body/headers/raw kept
  // showing unchanged the whole time, easy to mistake for the new result.
  $("singleDot").className = "dot running";
  $("singleStatusText").textContent = "Sending…";
  $("singleMeta").textContent = "";
  setSendPending($("respSingle"), true);
  try {
    const auth = authPayloadFields();
    const result = await postJson("/api/send-one", {
      slug,
      request: currentConsoleRequest(),
      environmentSlug: activeEnvironmentSlug(),
      auth: {
        mode: auth.authMode, tokenUrl: auth.tokenUrl, tenant: auth.tenant, refreshToken: auth.refreshToken,
        bearerToken: auth.bearerToken, basicUser: auth.basicUser, basicPassword: auth.basicPassword,
        apiKeyName: auth.apiKeyName, apiKeyValue: auth.apiKeyValue, apiKeyLocation: auth.apiKeyLocation,
        oauth2ClientId: auth.oauth2ClientId, oauth2ClientSecret: auth.oauth2ClientSecret,
        oauth2TokenUrl: auth.oauth2TokenUrl, oauth2Scope: auth.oauth2Scope, oauth2AuthStyle: auth.oauth2AuthStyle,
      },
      timeout: getRequestTimeoutSeconds(),
      proxySettings: getProxySettings(),
      insecure: getInsecureMode(),
    });
    if (!shouldRenderSendResult(tabId, activeTab())) return;
    if (activeTab()) activeTab().response = result;
    renderSingleResponse(result);
  } catch (error) {
    if (!shouldRenderSendResult(tabId, activeTab())) return;
    const errorResult = { status: 0, elapsedMs: 0, sizeBytes: 0, headers: {}, body: error.message, isError: true };
    if (activeTab()) activeTab().response = errorResult;
    renderSingleResponse(errorResult);
  } finally {
    setBusy(button, false);
    setSendPending($("respSingle"), false);
  }
}

// Called on tab switch/close so a newly-activated tab never briefly shows the
// previous tab's leftover response markup — activateTab() only toggled the
// "hidden" class here before, leaving stale content sitting in the DOM to
// flash into view the instant the next Send unhides the panel.
function resetSingleResponsePanel() {
  $("respSingle").classList.add("hidden");
  setSendPending($("respSingle"), false);
  $("singleDot").className = "dot";
  $("singleStatusText").textContent = "";
  $("singleMeta").textContent = "";
  $("singleBody").innerHTML = "";
  $("singleHeaders").innerHTML = "";
  $("singleRaw").textContent = "";
  renderSingleTestResults(null, null);
  lastSingleResponse = null;
  $("saveResponseBtn").disabled = true;
}

async function saveSingleResponse() {
  if (!lastSingleResponse || lastSingleResponse.isError) return;
  const requestName = currentConsoleRequest().name || "response";
  const extension = lastSingleResponse.isJson ? "json" : "txt";
  await saveTextFile(`${slugify(requestName) || "response"}-response.${extension}`, lastSingleResponse.body || "");
}

function renderSingleResponse(result) {
  // Also reached from activateTab() (tabs.js) when switching to a tab that
  // already has a stored response — that tab never had its own send in
  // flight, so any "pending" dimming left over from a DIFFERENT tab's Send
  // must not carry over onto it.
  setSendPending($("respSingle"), false);
  const ok = result.status >= 200 && result.status < 400;
  $("singleDot").className = `dot ${result.isError ? "bad" : ok ? "" : "bad"}`;
  $("singleStatusText").textContent = result.isError ? "Request failed" : `${result.status} ${ok ? "OK" : ""}`.trim();
  $("singleMeta").textContent = result.isError ? result.body : `${result.elapsedMs} ms · ${formatSize(result.sizeBytes)}`;
  let pretty = result.body;
  let isJson = true;
  try {
    pretty = JSON.stringify(JSON.parse(result.body), null, 2);
  } catch {
    isJson = false; // leave as-is if the body isn't JSON
  }
  // Same highlightJson() the request Body editor uses (body-editor.js) — a
  // JSON response with no key/string/number coloring read as an unbroken
  // wall of text next to a payload editor that already has it.
  // renderLineNumbered (shared.js) gives it a line-number gutter too.
  if (result.isError) {
    $("singleBody").innerHTML = "";
  } else {
    renderLineNumbered($("singleBody"), highlightJson(pretty || ""));
  }
  // Headers get the same highlight+gutter treatment as Body — Raw is left as
  // plain text on purpose, since its whole point is showing the untouched
  // wire response.
  renderLineNumbered($("singleHeaders"), highlightJson(JSON.stringify(result.headers || {}, null, 2)));
  $("singleRaw").textContent = result.body || "";
  renderSingleTestResults(result.tests, result.warnings);
  lastSingleResponse = { ...result, isJson };
  $("saveResponseBtn").disabled = !!result.isError || !result.body;
}

// Tests used to render as an always-visible block stacked under whichever
// response tab (Body/Headers/Raw) happened to be open — they now get their
// own "Test Results" tab instead, so that's what this drives now:
// #singleTestsTab (hidden when there's nothing to show) plus the pass-count
// badge, with #singleTestResults' visibility gated on BOTH having content
// AND that tab being the active one (the click handler in request-tabs.js
// handles the latter for a tab switch; this handles it for a fresh response).
function renderSingleTestResults(tests, warnings) {
  const panel = $("singleTestResults");
  const tab = $("singleTestsTab");
  const rows = [];
  if (warnings && warnings.length) {
    rows.push(...warnings.map((w) => `<div class="test-result-row status-fail">&#9888; ${escapeHtml(w)}</div>`));
  }
  let passedCount = 0;
  if (tests && tests.length) {
    passedCount = tests.filter((t) => t.passed).length;
    rows.unshift(`<p class="meta">Tests ${passedCount}/${tests.length}</p>`);
    rows.push(...tests.map((t) => {
      const label = t.type === "capture"
        ? `capture ${escapeHtml(t.variable || "")} = ${escapeHtml(String(t.actual))}`
        : t.type === "python"
          ? `python: ${escapeHtml(t.expected || "")}`
          : `${escapeHtml(t.source)} ${escapeHtml(t.path || "")} ${escapeHtml(t.operator)} ${escapeHtml(String(t.expected))} (actual: ${escapeHtml(String(t.actual))})`;
      return `<div class="test-result-row ${t.passed ? "status-ok" : "status-fail"}">${t.passed ? "&#10003;" : "&#10007;"} ${label}</div>`;
    }));
  }
  panel.innerHTML = rows.join("");
  const hasContent = rows.length > 0;
  tab.classList.toggle("hidden", !hasContent);
  tab.innerHTML = tests && tests.length
    ? `Test Results <span class="badge">${passedCount}/${tests.length}</span>`
    : "Test Results";
  if (!hasContent && tab.classList.contains("active")) {
    // The tab a user was looking at just disappeared (e.g. re-sending after
    // removing the last test row) — land back on Body instead of leaving
    // them on a now-hidden "active" tab.
    tab.classList.remove("active");
    document.querySelector('.tab[data-response-tab="body"]').classList.add("active");
    $("singleBody").classList.remove("hidden");
    $("singleHeaders").classList.add("hidden");
    $("singleRaw").classList.add("hidden");
    panel.classList.add("hidden");
  } else {
    panel.classList.toggle("hidden", !(hasContent && tab.classList.contains("active")));
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("sendBtn").addEventListener("click", sendConsoleRequest);
  $("saveResponseBtn").addEventListener("click", () => saveSingleResponse().catch((e) => alert(e.message)));
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = { shouldRenderSendResult, setSendPending, sendConsoleRequest };
}
