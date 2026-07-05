"""
tests/test_daily_digest.py

Tests the daily status digest's content assembly and SMTP-send plumbing
-- no real network, git, or mailbox needed. build_digest_text() takes
its three inputs as injectable arguments specifically so this suite
never has to shell out to git or run the real test suite recursively.

Usage:
    python -m pytest tests/test_daily_digest.py -v
"""

import sys
import os
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from scripts.reports.daily_digest import build_digest_text, send_digest_email


def test_build_digest_text_includes_all_sections():
    text = build_digest_text(
        git_log="abc1234 Add new source",
        freshness=[("acled", "2026-07-01 12:00:00"), ("gdelt", "2026-07-03 08:00:00")],
        test_summary="218 passed in 5.27s",
    )
    assert "abc1234 Add new source" in text
    assert "acled: last ingested 2026-07-01 12:00:00" in text
    assert "218 passed in 5.27s" in text
    assert "Daily Status" in text


def test_build_digest_text_handles_empty_freshness_list():
    text = build_digest_text(git_log="", freshness=[], test_summary="0 passed")
    assert "DATA FRESHNESS" in text


def test_send_digest_email_raises_without_credentials(monkeypatch):
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("DIGEST_TO_EMAIL", raising=False)
    with pytest.raises(RuntimeError, match="SMTP_USERNAME"):
        send_digest_email("some digest text")


def test_send_digest_email_logs_in_and_sends_with_injected_client(monkeypatch):
    monkeypatch.setenv("SMTP_USERNAME", "research@frontiermercator.com")
    monkeypatch.setenv("SMTP_PASSWORD", "fake-password")
    monkeypatch.setenv("DIGEST_TO_EMAIL", "chris@example.com")

    fake_client = MagicMock()
    send_digest_email("digest body text", smtp_client=fake_client)

    fake_client.login.assert_called_once_with("research@frontiermercator.com", "fake-password")
    fake_client.send_message.assert_called_once()
    sent_message = fake_client.send_message.call_args[0][0]
    assert sent_message["To"] == "chris@example.com"
    assert sent_message["From"] == "research@frontiermercator.com"
    assert "digest body text" in sent_message.get_content()


if __name__ == "__main__":
    test_functions = [v for k, v in list(globals().items()) if k.startswith("test_")]
    print(f"Running {len(test_functions)} tests...\n")
    failures = 0
    for test_fn in test_functions:
        try:
            test_fn()
            print(f"passed {test_fn.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAILED {test_fn.__name__}: {e}")
    print(f"\n{len(test_functions) - failures}/{len(test_functions)} tests passed.")
    if failures:
        sys.exit(1)
