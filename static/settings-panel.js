// static/settings-panel.js
// Settings modal controller: owns open/close and proxy-field
// rendering/wiring. Timeout (request-timeout.js) and TLS-verify
// (insecure-settings.js) wire their own single input directly — only
// proxy needs cross-field rendering because of its object shape.

// Right edge is a static 14px in CSS, matching .topbar's own right padding
// (static/sidebar.css) — the topbar's rightmost element (currently the theme
// toggle, not settingsBtn) already sits flush with that edge, so anchoring
// to it directly keeps the box flush regardless of future topbar reordering.
function positionSettingsModal() {
  const anchor = $("settingsBtn").getBoundingClientRect();
  $("settingsModalBox").style.top = `${anchor.bottom + 8}px`;
}

function openSettingsModal() {
  $("settingsModal").classList.remove("hidden");
  positionSettingsModal();
  renderProxyFields();
}

function closeSettingsModal() {
  $("settingsModal").classList.add("hidden");
}

function proxyModeRadioId(mode) {
  return "proxyMode" + mode.charAt(0).toUpperCase() + mode.slice(1);
}

function updateProxyCustomFieldsVisibility(mode) {
  $("proxyCustomFields").classList.toggle("hidden", mode !== "custom");
}

function renderProxyFields() {
  const settings = getProxySettings();
  $(proxyModeRadioId(settings.mode)).checked = true;
  $("proxyUrlInput").value = settings.url;
  $("proxyUsernameInput").value = settings.username;
  $("proxyPasswordInput").value = settings.password;
  $("proxyBypassListInput").value = settings.bypassList.join("\n");
  updateProxyCustomFieldsVisibility(settings.mode);
}

function isValidUrl(value) {
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) && Boolean(parsed.hostname);
  } catch (e) {
    return false;
  }
}

function parseBypassList(text) {
  return text.split("\n").map((line) => line.trim()).filter((line) => line.length > 0);
}

// An empty/whitespace-only value means "no proxy" and is always valid — only
// a non-empty value that fails URL parsing is rejected, reverting to
// whatever was last persisted (same shape as request-timeout.js's own
// reject-and-revert behavior for invalid input).
function resolveProxyUrlInput(rawValue, previousUrl) {
  const value = rawValue.trim();
  if (value === "") return { valid: true, value: "" };
  if (!isValidUrl(value)) return { valid: false, value: previousUrl };
  return { valid: true, value };
}

document.addEventListener("DOMContentLoaded", () => {
  $("settingsBtn").addEventListener("click", openSettingsModal);
  $("settingsModalClose").addEventListener("click", closeSettingsModal);
  $("settingsModal").addEventListener("click", (event) => {
    if (event.target.id === "settingsModal") closeSettingsModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("settingsModal").classList.contains("hidden")) closeSettingsModal();
  });

  for (const mode of ["system", "env", "custom"]) {
    $(proxyModeRadioId(mode)).addEventListener("change", () => {
      patchProxySettings({ mode });
      updateProxyCustomFieldsVisibility(mode);
    });
  }

  $("proxyUrlInput").addEventListener("change", () => {
    const input = $("proxyUrlInput");
    const { valid, value } = resolveProxyUrlInput(input.value, getProxySettings().url);
    $("proxyUrlError").classList.toggle("hidden", valid);
    input.value = value;
    if (valid) patchProxySettings({ url: value });
  });

  $("proxyUsernameInput").addEventListener("change", () => {
    patchProxySettings({ username: $("proxyUsernameInput").value });
  });

  $("proxyPasswordInput").addEventListener("change", () => {
    patchProxySettings({ password: $("proxyPasswordInput").value });
  });

  $("proxyBypassListInput").addEventListener("change", () => {
    patchProxySettings({ bypassList: parseBypassList($("proxyBypassListInput").value) });
  });
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    openSettingsModal, closeSettingsModal, renderProxyFields, positionSettingsModal,
    updateProxyCustomFieldsVisibility, isValidUrl, parseBypassList, resolveProxyUrlInput,
  };
}
