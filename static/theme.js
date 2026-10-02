const THEME_STORAGE_KEY = "iris-theme";

function resolveInitialTheme(stored, prefersLight) {
  if (stored === "light" || stored === "dark") return stored;
  return prefersLight ? "light" : "dark";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const btn = document.getElementById("themeToggleBtn");
  if (btn) {
    btn.textContent = theme === "light" ? "☽" : "☀";
    btn.title = theme === "light" ? "Switch to dark mode" : "Switch to light mode";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const media = window.matchMedia("(prefers-color-scheme: light)");
  let stored = localStorage.getItem(THEME_STORAGE_KEY);
  applyTheme(resolveInitialTheme(stored, media.matches));

  media.addEventListener("change", (e) => {
    stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark") return;
    applyTheme(e.matches ? "light" : "dark");
  });

  document.getElementById("themeToggleBtn").addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "light" ? "dark" : "light";
    localStorage.setItem(THEME_STORAGE_KEY, next);
    applyTheme(next);
  });
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = { resolveInitialTheme };
}
