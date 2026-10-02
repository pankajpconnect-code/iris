"""Native macOS file/folder picker dialogs for the CSV runner UI.

Split out of runner_commands.py, which is already at this repo's 500-line
limit — these two functions are self-contained (just an osascript call) and
don't need to live alongside the command-building logic.
"""

import os
import subprocess
import sys

import runner_commands


class PickerCancelled(Exception):
    """Raised when the user dismisses the native picker instead of choosing a file/folder."""


def _run_osascript(script):
    result = subprocess.run(
        ["osascript", "-e", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        # AppleScript reports the Carbon userCanceledErr as "(-128)" regardless
        # of OS locale/wording, so match on the code rather than the message text.
        if "-128" in message:
            raise PickerCancelled()
        raise ValueError(message or "Selection was cancelled")
    return result.stdout.strip()


def choose_csv_file():
    if sys.platform != "darwin":
        raise ValueError("Native CSV chooser is currently supported on macOS only")
    script = (
        'POSIX path of (choose file with prompt "Choose CSV file" '
        'of type {"public.comma-separated-values-text", "public.text", "csv"})'
    )
    path = _run_osascript(script)
    return runner_commands.inspect_csv_path(path)


def choose_output_folder():
    if sys.platform != "darwin":
        raise ValueError("Native folder chooser is currently supported on macOS only")
    script = 'POSIX path of (choose folder with prompt "Choose failed rows output folder")'
    folder = _run_osascript(script).rstrip("/")
    if not os.path.isdir(folder):
        raise ValueError("Selected output folder was not found")
    return {
        "outputFolder": folder,
        "retryCsv": runner_commands._retry_csv_path("", folder),
    }
