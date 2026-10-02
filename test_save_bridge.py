"""Tests for save_bridge._escape — caught by an independent review:
json.dumps(value)[1:-1] already produces a correctly quote/backslash-
escaped AppleScript string-literal body, but a trailing
.replace('"', '\\"') re-escaped the quote characters json.dumps had
already escaped, corrupting the generated `osascript -e` command whenever
a suggested filename contained a `"`.
"""

import save_bridge


def test_escape_quote_is_singly_escaped_not_doubled():
    assert save_bridge._escape('say "hi".txt') == 'say \\"hi\\".txt'


def test_escape_backslash_is_correctly_escaped():
    assert save_bridge._escape("C:\\path") == "C:\\\\path"


def test_escape_plain_text_is_unchanged():
    assert save_bridge._escape("plain-name.csv") == "plain-name.csv"
