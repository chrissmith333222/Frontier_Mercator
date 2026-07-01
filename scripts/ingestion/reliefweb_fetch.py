"""
scripts/ingestion/reliefweb_fetch.py

Fetches raw ReliefWeb (UN OCHA) situation reports/appeals/news, scoped to
MERIDIAN's Africa/LatAm mandate countries plus extended monitoring (Europe,
Middle East). Returns raw records — does NOT normalize them. See
reliefweb_normalize.py for the mapping into MERIDIAN's common schema.

ReliefWeb API v2 (v1 was decommissioned). As of 1 November 2025, ReliefWeb
requires a pre-approved "appname" for all API calls — you can't just invent
one. Request one at https://apidoc.reliefweb.int/ (short form, reviewed by
ReliefWeb, approval comes by email), then set RELIEFWEB_APPNAME in .env.
See docs/reliefweb_setup.md.

Usage (CLI):
    python scripts/ingestion/reliefweb_fetch.py --days-back 7
    python scripts/ingestion/reliefweb_fetch.py --days-back 7 --country Mali

Usage (as a module):
    from scripts.ingestion.reliefweb_fetch import fetch_recent_reports
    reports = fetch_recent_reports(days_back=7)
"""

import sys
import os
import argparse
import json
from pathlib import Path
from datetime import date, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass

RELIEFWEB_API_URL = "https://api.reliefweb.int/v2/reports"
DEFAULT_LIMIT = 200  # ReliefWeb caps at 1000/call, 1000/day per appname


def _get_appname() -> str:
    appname = os.environ.get("RELIEFWEB_APPNAME")
    if not appname:
        raise RuntimeError(
            "RELIEFWEB_APPNAME is not set. ReliefWeb requires a pre-approved appname "
            "(since 1 Nov 2025) — request one at https://apidoc.reliefweb.int/ and set "
            "it in .env. See docs/reliefweb_setup.md."
        )
    return appname


def fetch_recent_reports(
    days_back: int = 7,
    countries: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """
    Fetch ReliefWeb reports from the last `days_back` days, optionally scoped
    to a list of country names (ReliefWeb's own country taxonomy names, e.g.
    "Mali", "Colombia"). Omit `countries` to fetch across all countries
    (still date-scoped) — useful for a first pull, but noisier.
    """
    appname = _get_appname()

    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    from_iso = f"{start_date.isoformat()}T00:00:00+00:00"
    to_iso = f"{end_date.isoformat()}T23:59:59+00:00"

    conditions = [
        {"field": "date.created", "value": {"from": from_iso, "to": to_iso}},
    ]
    if countries:
        conditions.append({"field": "country", "value": countries, "operator": "OR"})

    payload = {
        "appname": appname,
        "filter": {"operator": "AND", "conditions": conditions},
        "sort": ["date.created:desc"],
        "limit": limit,
        "fields": {
            "include": [
                "title", "url", "date.created", "date.original",
                "country.name", "country.iso3", "source.name",
                "format.name", "disaster_type.name", "body",
            ]
        },
    }

    response = requests.post(RELIEFWEB_API_URL, json=payload, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(
            f"ReliefWeb fetch failed: status {response.status_code}, body: {response.text[:500]}"
        )

    data = response.json()
    return data.get("data", [])


def main():
    parser = argparse.ArgumentParser(description="Fetch recent ReliefWeb reports for MERIDIAN")
    parser.add_argument("--days-back", type=int, default=7, help="How many days back to fetch")
    parser.add_argument("--country", type=str, action="append", default=None,
                         help="Restrict to one country (repeatable). Omit for all countries.")
    parser.add_argument("--output", type=str, default=None,
                         help="Write raw JSON output to this file path. Omit to print to stdout.")
    args = parser.parse_args()

    reports = fetch_recent_reports(days_back=args.days_back, countries=args.country)

    print(f"Fetched {len(reports)} raw ReliefWeb reports "
          f"(last {args.days_back} days, countries: {args.country or 'all'})", file=sys.stderr)

    output_json = json.dumps(reports, indent=2)
    if args.output:
        Path(args.output).write_text(output_json)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
