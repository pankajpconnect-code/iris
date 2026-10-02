"""Runtime helpers for the Iris .app bundle: Python interpreter
resolution (a Finder-launched app inherits only /usr/bin:/bin:/usr/sbin:/sbin,
not the user's shell PATH) and a single-instance probe against the chosen
port so two launches never write to the same flat-file stores concurrently.
"""
import glob
import json
import os
import urllib.error
import urllib.request

MIN_PYTHON = (3, 11)

CANDIDATE_PATTERNS = [
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "/Library/Frameworks/Python.framework/Versions/*/bin/python3",
]


class NoSuitablePythonError(RuntimeError):
    """Raised when no python3 >= MIN_PYTHON is found on any candidate path."""


def _version_tuple(python_path):
    import subprocess

    out = subprocess.run(
        [python_path, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
        capture_output=True, text=True, timeout=5,
    )
    if out.returncode != 0:
        raise ValueError(out.stderr.strip())
    major, minor = out.stdout.strip().split()
    return (int(major), int(minor))


def find_python(min_version=MIN_PYTHON):
    """Probe explicit candidate paths for a python3 >= min_version. Never
    falls through to /usr/bin/python3 (macOS system python, often < 3.11).
    Raises NoSuitablePythonError with a named, actionable message if none
    qualify — silent fallthrough to an old interpreter is the failure mode
    this exists to prevent."""
    checked = []
    for pattern in CANDIDATE_PATTERNS:
        for candidate in sorted(glob.glob(pattern)):
            if not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
                continue
            try:
                version = _version_tuple(candidate)
            except Exception as exc:
                checked.append(f"{candidate} (unusable: {exc})")
                continue
            checked.append(f"{candidate} (found {version[0]}.{version[1]})")
            if version >= min_version:
                return candidate
    raise NoSuitablePythonError(
        "No python3 >= {}.{} found among candidates: {}. Install Python "
        "{}.{}+ (e.g. via Homebrew: brew install python@3.12) and relaunch "
        "Iris.".format(
            min_version[0], min_version[1],
            "; ".join(checked) if checked else "none present",
            min_version[0], min_version[1],
        )
    )


def probe_running_instance(port, timeout=0.5):
    """Return True if a server already answers /api/runs on this port —
    i.e. an Iris instance is already up."""
    url = f"http://127.0.0.1:{port}/api/runs"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return "runs" in body
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False
