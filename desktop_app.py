"""Entry point for the Iris native app: starts the server on
a daemon thread, opens a pywebview window against it, and guards quit while
a run is in flight. No Terminal exists once launched from Finder, so
bootstrap failures are logged to disk and surfaced via `osascript`.
"""
import datetime
import logging
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HERE, "iris.log")

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("desktop_app")


def _alert(title, message):
    """Native alert with no Terminal available — the only way to surface a
    bootstrap failure to a user who double-clicked an .app icon."""
    import subprocess

    script = f'display alert "{title}" message "{message}" as critical'
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=10)
    except Exception:
        log.exception("Failed to show native alert (title=%r)", title)


def _active_run_summary():
    """Return a human-readable 'name + iteration' string for the first
    in-flight run, or None if nothing is running. Used by the quit guard."""
    import run_history_store
    import runner_commands
    import server as server_module

    with runner_commands.ACTIVE_RUNS_LOCK:
        run_ids = list(runner_commands.ACTIVE_RUNS.keys())
    if not run_ids:
        return None
    run_id = run_ids[0]
    try:
        doc = run_history_store.get_run(server_module.RUNS_DIR, run_id)
    except Exception:
        return f"run {run_id}"
    last_iteration = None
    last_total = None
    for event in reversed(doc.get("events") or []):
        if "iteration" in event:
            last_iteration = event["iteration"]
            last_total = event.get("iterationTotal")
            break
    if last_iteration is None:
        return f"run {run_id}"
    if last_total:
        return f"run {run_id} (iteration {last_iteration} of {last_total})"
    return f"run {run_id} (iteration {last_iteration})"


def _confirm_quit_with_active_run(summary):
    """A blocking native confirm dialog. Returns True if the user chose to
    quit anyway. Runs checkpoint to disk continuously (run_history_store),
    so confirming quit keeps everything up to the last checkpoint — nothing
    is silently lost, but an in-flight HTTP call is abandoned."""
    import subprocess

    script = (
        f'display dialog "{summary} is still running. Quitting now will stop it; '
        'results are saved up to the last checkpoint." '
        'with title "Iris" buttons {{"Cancel", "Quit Anyway"}} '
        'default button "Cancel" cancel button "Cancel" with icon caution'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=300
        )
        return result.returncode == 0 and "Quit Anyway" in result.stdout
    except Exception:
        log.exception("Quit-guard dialog failed; defaulting to blocking quit")
        return False


def main():
    log.info("Iris starting (pid=%s)", os.getpid())
    try:
        import desktop_runtime

        port = int(os.environ.get("IRIS_PORT", "5090"))
        if desktop_runtime.probe_running_instance(port):
            _alert(
                "Iris is already running",
                f"An instance is already listening on port {port}. "
                "Switch to it instead of opening a second copy.",
            )
            log.info("Single-instance probe found a live server on %s; exiting", port)
            return 0
    except Exception:
        log.exception("Startup probe failed")
        _alert("Iris failed to start", "See iris.log for details.")
        return 1

    try:
        import server as server_module
        import webview

        import menu as menu_module
        import save_bridge

        server, bound_port = server_module.start_server()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        log.info("Server thread started on port %s", bound_port)

        url = f"http://127.0.0.1:{bound_port}/"
        window = webview.create_window(
            "Iris", url, width=1280, height=860, min_size=(960, 640),
            js_api=save_bridge.SaveBridgeApi(),
            # pywebview defaults text_select to False — every response/payload
            # body, header value, and run-history row would be unselectable
            # (not just uncopyable) without this, defeating the Cmd+C/Cmd+X
            # fallback in shared.js before it ever gets a selection to act on.
            text_select=True,
        )

        def on_closing():
            summary = _active_run_summary()
            if summary is None:
                return True
            return _confirm_quit_with_active_run(summary)

        window.events.closing += on_closing

        menu = menu_module.build_menu(window)
        # The launcher script execs into a bare python3 process (see its own
        # comment on why it's a shell script, not a Mach-O binary), so macOS
        # shows that interpreter's own registered Dock icon unless told
        # otherwise — CFBundleIconFile in Info.plist is never consulted once
        # that swap happens. pywebview's cocoa backend does support this
        # despite its `icon` docstring saying "GTK/QT only".
        icon_path = os.path.join(HERE, "Iris.app", "Contents", "Resources", "Iris.icns")
        # Same root cause gives the process the name "Python" on Dock hover
        # and in the menu bar: NSBundle.mainBundle() resolves to
        # Python.framework's own Info.plist (CFBundleName "Python"), not
        # Iris.app's, since nothing launched a bundle's Mach-O binary.
        # pywebview's cocoa backend reads this same NSBundle dict when it
        # spins up NSApplication inside webview.start(), so patch it here,
        # before that call, rather than in Iris.app/Contents/Info.plist
        # (already "Iris" there, but never consulted once the bare-python3
        # swap happens).
        from Foundation import NSBundle

        bundle_info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        if bundle_info is not None:
            bundle_info["CFBundleName"] = "Iris"
        webview.start(menu=menu, debug=False, icon=icon_path)
        log.info("Iris window closed; shutting down")
        server.shutdown()
        return 0
    except Exception:
        log.exception("Fatal error during startup")
        _alert("Iris failed to start", "See iris.log for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
