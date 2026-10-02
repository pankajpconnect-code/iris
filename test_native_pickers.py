"""Unit tests for native_pickers.py's osascript cancellation handling."""

import subprocess

import pytest

import native_pickers


class _FakeResult:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_choose_csv_file_raises_picker_cancelled_when_user_cancels(monkeypatch):
    monkeypatch.setattr(native_pickers.sys, "platform", "darwin")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _FakeResult(1, stderr="15:125: execution error: User canceled. (-128)"),
    )
    with pytest.raises(native_pickers.PickerCancelled):
        native_pickers.choose_csv_file()


def test_choose_output_folder_raises_picker_cancelled_when_user_cancels(monkeypatch):
    monkeypatch.setattr(native_pickers.sys, "platform", "darwin")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _FakeResult(1, stderr="15:125: execution error: User canceled. (-128)"),
    )
    with pytest.raises(native_pickers.PickerCancelled):
        native_pickers.choose_output_folder()


def test_choose_csv_file_still_raises_value_error_for_other_failures(monkeypatch):
    monkeypatch.setattr(native_pickers.sys, "platform", "darwin")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _FakeResult(1, stderr="some other osascript failure"),
    )
    with pytest.raises(ValueError, match="some other osascript failure"):
        native_pickers.choose_csv_file()
