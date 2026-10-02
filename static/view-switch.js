function showConsoleView() {
  $("consoleView").classList.remove("hidden");
  $("runnerView").classList.add("hidden");
  $("viewConsoleBtn").classList.add("active");
  $("viewRunnerBtn").classList.remove("active");
}

function showRunnerView() {
  $("runnerView").classList.remove("hidden");
  $("consoleView").classList.add("hidden");
  $("viewRunnerBtn").classList.add("active");
  $("viewConsoleBtn").classList.remove("active");
  if (typeof refreshRunnerRequestOptions === "function") refreshRunnerRequestOptions();
}

document.addEventListener("DOMContentLoaded", () => {
  $("viewConsoleBtn").addEventListener("click", showConsoleView);
  $("viewRunnerBtn").addEventListener("click", showRunnerView);
});
