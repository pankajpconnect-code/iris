"""Native macOS menu bar for Iris, wired to element ids in templates/index.html
via evaluate_js — the click handlers already live in the frontend, so the
menu just triggers a synthetic click.

pywebview 6.2.1's MenuAction takes no accelerator argument at all (its own
source has a `# TODO: support platform-agnostic shortcut` next to an unused,
commented-out self.shortcut). Every item below ships without a keyboard
shortcut as a result — see README.md "Known limitations".
"""
from webview.menu import Menu, MenuAction, MenuSeparator


def _click(window, element_id):
    def handler():
        window.evaluate_js(
            f"(function(){{var el = document.getElementById('{element_id}'); "
            f"if (el) {{ el.click(); }} }})()"
        )
    return handler


def _switch_view(window, button_id):
    return _click(window, button_id)


def build_menu(window):
    """Build the Iris / File / Edit / Collection / Run / Window /
    Help menu bar. Every action defers to the existing frontend handler for
    the matching button id, so behaviour matches clicking that button."""
    return [
        Menu(
            "Iris",
            [
                MenuAction("About Iris", lambda: window.create_confirmation_dialog(
                    "Iris", "A native macOS console for the lending APIs."
                )),
                MenuSeparator(),
                MenuAction("Quit Iris", window.destroy),
            ],
        ),
        Menu(
            "File",
            [
                MenuAction("New Request", _click(window, "newMenuBtn")),
                MenuSeparator(),
                MenuAction("Import Collection…", _click(window, "importCollectionBtn")),
                MenuAction("Export Collection…", _click(window, "exportCollectionBtn")),
                MenuSeparator(),
                MenuAction("Manage Environments…", _click(window, "manageEnvBtn")),
            ],
        ),
        Menu(
            "Edit",
            [
                MenuAction("Beautify Body", _click(window, "beautifyBodyBtn")),
                MenuAction("Bulk Edit Headers", _click(window, "bulkEditHeadersBtn")),
            ],
        ),
        Menu(
            "Collection",
            [
                MenuAction("Duplicate Request", _click(window, "duplicateBtn")),
                MenuAction("Save Request", _click(window, "saveBtn")),
                MenuAction("Save Auth", _click(window, "saveAuthBtn")),
                MenuSeparator(),
                MenuAction("Send Request", _click(window, "sendBtn")),
            ],
        ),
        Menu(
            "Run",
            [
                MenuAction("Console", _switch_view(window, "viewConsoleBtn")),
                MenuAction("Runner", _switch_view(window, "viewRunnerBtn")),
                MenuSeparator(),
                MenuAction("Preview", _click(window, "runnerPreviewBtn")),
                MenuAction("Run", _click(window, "runnerRunBtn")),
                MenuAction("Stop", _click(window, "runnerStopBtn")),
                MenuSeparator(),
                MenuAction("History", _click(window, "runnerHistoryBtn")),
                MenuAction("Export Results…", _click(window, "runnerExportBtn")),
            ],
        ),
        Menu(
            "Window",
            [
                MenuAction("Minimize", window.minimize),
                MenuAction("Toggle Full Screen", window.toggle_fullscreen),
            ],
        ),
        Menu(
            "Help",
            [
                MenuAction(
                    "Iris README",
                    lambda: window.create_confirmation_dialog(
                        "Iris",
                        "See README.md (in this app's folder) for setup and known limitations.",
                    ),
                ),
            ],
        ),
    ]
