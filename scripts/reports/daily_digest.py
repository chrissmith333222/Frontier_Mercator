"""
scripts/reports/daily_digest.py

Chris's ask: an automated daily status email so he doesn't have to check
in on the project to know what's happening -- new data ingested, git
activity, test health, and anything that needs his attention (e.g. a
failed ingestion run, a stale source).

Two separable pieces, deliberately kept apart:
  1. build_digest_text() -- pure content assembly (git log, per-source
     data freshness, test pass/fail), fully testable without touching a
     network or a mailbox.
  2. send_digest_email() -- the actual SMTP send, using Namecheap Private
     Email's standard settings (mail.privateemail.com:465, SSL) via
     credentials that live ONLY in .env, never in chat or committed to
     the repo. `smtp_client` is injectable for tests.

Not run automatically on its own -- something has to invoke this on a
schedule (Windows Task Scheduler locally, or Claude Code's scheduled
cloud-agent feature, which can clone the repo fresh each run). See
.env.example for the credentials this needs.

Usage (CLI):
    python scripts/reports/daily_digest.py --send
    python scripts/reports/daily_digest.py            # prints digest text only, no email
"""

import os
import sys
import ssl
import smtplib
import argparse
import subprocess
import json
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
NORMALIZED_DIR = REPO_ROOT / "data" / "normalized"

SMTP_HOST = "mail.privateemail.com"
SMTP_PORT = 465


def _recent_git_log(since: str = "24 hours ago") -> str:
    """Commit subjects since `since`, oldest first -- swallows any git
    error (e.g. running somewhere without git history) rather than
    failing the whole digest over a cosmetic section."""
    try:
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--pretty=format:%h %s", "--reverse"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip() or "No commits in the last 24 hours."
    except Exception as e:
        return f"(git log unavailable: {e})"


def _source_freshness() -> list[tuple[str, str]]:
    """Last-ingested timestamp per source, from each *_latest_normalized.json's
    newest ingested_at -- the "is anything stale" check Chris keeps
    running into manually. Returns (source_name, freshness_description)."""
    rows = []
    for path in sorted(NORMALIZED_DIR.glob("*_latest_normalized.json")):
        source_name = path.stem.replace("_latest_normalized", "")
        try:
            events = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            rows.append((source_name, "unreadable"))
            continue
        if not events:
            rows.append((source_name, "no events"))
            continue
        latest_ingested = max((e.get("ingested_at", "") for e in events), default="")
        rows.append((source_name, latest_ingested[:19].replace("T", " ") if latest_ingested else "unknown"))
    return rows


def _test_summary() -> str:
    """Runs the test suite and returns a one-line pass/fail summary --
    swallows any subprocess error into the summary string rather than
    raising, since a broken test run is exactly the kind of thing this
    digest exists to surface, not something that should crash the digest
    itself."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
        )
        tail_lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
        return tail_lines[-1] if tail_lines else "(no test output)"
    except Exception as e:
        return f"(test run failed to execute: {e})"


def build_digest_text(
    git_log: str | None = None, freshness: list[tuple[str, str]] | None = None,
    test_summary: str | None = None,
) -> str:
    """Assembles the plain-text digest body. All three inputs are
    injectable for tests; when omitted, each is computed for real
    (git log, per-source freshness, live test run)."""
    if git_log is None:
        git_log = _recent_git_log()
    if freshness is None:
        freshness = _source_freshness()
    if test_summary is None:
        test_summary = _test_summary()

    freshness_lines = "\n".join(f"  {name}: last ingested {ts}" for name, ts in freshness)
    date_str = datetime.now(timezone.utc).strftime("%A, %d %B %Y")

    return (
        f"Frontier Mercator / Parallax -- Daily Status ({date_str})\n"
        f"{'=' * 60}\n\n"
        f"COMMITS (last 24h):\n{git_log}\n\n"
        f"DATA FRESHNESS (per source, last ingested):\n{freshness_lines}\n\n"
        f"TEST SUITE:\n  {test_summary}\n\n"
        f"{'=' * 60}\n"
        f"This is an automated status email. Reply is not monitored.\n"
    )


def send_digest_email(body: str, smtp_client=None) -> None:
    """Sends `body` as a plain-text email from research@frontiermercator.com
    to the address in DIGEST_TO_EMAIL. `smtp_client` is injectable for
    tests (a fake context-manager-free object with a matching
    `.login(...)`/`.send_message(...)` surface) -- omit it in real use to
    connect to Namecheap Private Email over SSL."""
    load_dotenv()
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    to_email = os.environ.get("DIGEST_TO_EMAIL")
    if not username or not password or not to_email:
        raise RuntimeError(
            "SMTP_USERNAME, SMTP_PASSWORD, and DIGEST_TO_EMAIL must all be set in .env -- "
            "never paste credentials into chat."
        )

    message = EmailMessage()
    message["Subject"] = "Frontier Mercator -- Daily Status"
    message["From"] = username
    message["To"] = to_email
    message.set_content(body)

    if smtp_client is not None:
        smtp_client.login(username, password)
        smtp_client.send_message(message)
        return

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
        server.login(username, password)
        server.send_message(message)


def main():
    parser = argparse.ArgumentParser(description="Build (and optionally send) the daily status digest")
    parser.add_argument("--send", action="store_true", help="Actually send the email. Omit to just print the digest text.")
    args = parser.parse_args()

    digest = build_digest_text()
    print(digest, file=sys.stderr)

    if args.send:
        send_digest_email(digest)
        print("Digest email sent.", file=sys.stderr)


if __name__ == "__main__":
    main()
