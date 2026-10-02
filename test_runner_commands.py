"""Tests for runner_commands.process_timeout_for — caught by an independent
review: it computed the run's stall/abort deadline from hardcoded 30s/0s
defaults, ignoring the run's actual configured per-request timeout/delay,
so a legitimately slow (but healthy) run could get killed as "stalled"
long before its own configured timeout would ever trip.
"""

import runner_commands


def test_process_timeout_for_uses_configured_timeout_and_delay():
    default_deadline = runner_commands.process_timeout_for(10)
    configured_deadline = runner_commands.process_timeout_for(10, timeout=90, delay=10)
    assert configured_deadline > default_deadline


def test_process_timeout_for_falls_back_to_defaults_when_not_configured():
    assert runner_commands.process_timeout_for(10) == runner_commands.process_timeout_for(10, timeout=None, delay=None)


def test_process_timeout_for_matches_manual_calculation_with_configured_values():
    # 10 rows * (90s timeout + 10s delay + 3s overhead) + 30s floor overhead
    assert runner_commands.process_timeout_for(10, timeout=90, delay=10) == 10 * (90 + 10 + 3) + 30


def test_preview_body_text_raw_mode_returns_body_unchanged():
    assert runner_commands.preview_body_text({"body": "raw text"}) == "raw text"
    assert runner_commands.preview_body_text({"bodyMode": "raw", "body": "x"}) == "x"


def test_preview_body_text_urlencoded_mode_joins_enabled_keyed_params():
    """Human-readable "key=value" lines, not the actual wire-encoded bytes —
    urlencode() would percent-encode any still-unresolved {{var}} braces,
    hiding exactly the token the Runner Preview panel needs to highlight."""
    request = {
        "bodyMode": "urlencoded",
        "bodyParams": [
            {"key": "grant_type", "value": "client_credentials", "enabled": True},
            {"key": "disabled_one", "value": "x", "enabled": False},
            {"key": "", "value": "no-key", "enabled": True},
        ],
    }
    assert runner_commands.preview_body_text(request) == "grant_type=client_credentials"
