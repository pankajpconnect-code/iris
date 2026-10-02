// Bridges to save_bridge.py's SaveBridgeApi, exposed by pywebview as
// window.pywebview.api. Replaces URL.createObjectURL + <a download> (always
// landed in ~/Downloads with a browser-chosen name) and navigator.clipboard
// (denied by WKWebView's permission model — see save_bridge.py's docstring
// for the same finding).

// content: string. suggestedName: string, e.g. "request.json". Shows a
// native Save As dialog; returns once saved or cancelled — never throws.
async function saveTextFile(suggestedName, content) {
  const result = await window.pywebview.api.save_text_file(suggestedName, content);
  if (!result.saved && result.error && result.error !== "Save was cancelled") {
    alert(`Save failed: ${result.error}`);
  }
  return result;
}

async function irisClipboardWrite(text) {
  const result = await window.pywebview.api.clipboard_write(text);
  if (!result.ok) {
    throw new Error(result.error || "Clipboard write failed");
  }
}
