"""
meridian/scripts/ingestion/acled_fetch.py

Fetches raw ACLED event data, scoped to MERIDIAN's regional mandate (Africa +
Latin America) and a configurable lookback window. Returns raw records — does NOT
normalize them. See acled_normalize.py for the mapping into MERIDIAN's common schema.

Usage (CLI):
    python scripts/ingestion/acled_fetch.py --days-back 7
    python scripts/ingestion/acled_fetch.py --days-back 1 --region "Western Africa"

Usage (as a module, e.g. from n8n's Execute Command node or another script):
    from scripts.ingestion.acled_fetch import fetch_recent_events
    events = fetch_recent_events(days_back=7)
"""

import sys
import argparse
import json
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests
from scripts.lib.acled_auth import get_auth_headers

ACLED_READ_URL = "https://acleddata.com/api/acled/read"

# ACLED region codes covering MERIDIAN's mandate (Africa + Latin America).
# Per ACLED docs, regions are passed as numeric codes, not strings, in the API.
# These map to ACLED's Table 2 region codes.
MERIDIAN_REGION_CODES = {
    "Western Africa": 1,
    "Middle Africa": 2,
    "Eastern Africa": 3,
    "Southern Africa": 4,
    "Northern Africa": 5,
    "South America": 11,
    "Caribbean": 12,
    "Central America": 13,
}

DEFAULT_PAGE_LIMIT = 500  # well under ACLED's 5000 cap, keeps responses manageable


def fetch_recent_events(
    days_back: int = 7,
    region_codes: list[int] | None = None,
    max_pages: int = 10,
) -> list[dict]:
    """
    Fetch ACLED events from the last `days_back` days, restricted to the given
    region codes (defaults to ALL MERIDIAN regions: all of Africa + all of LatAm).

    Paginates automatically up to max_pages to handle high-event-volume windows
    without silently truncating at ACLED's per-request limit.
    """
    if region_codes is None:
        region_codes = list(MERIDIAN_REGION_CODES.values())

    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)

    headers = get_auth_headers()
    all_events = []
    page = 1

    region_filter = "|".join(str(c) for c in region_codes)

    while page <= max_pages:
        params = {
            "_format": "json",
            "event_date": f"{start_date.isoformat()}|{end_date.isoformat()}",
            "event_date_where": "BETWEEN",
            "region": region_filter,
            "limit": DEFAULT_PAGE_LIMIT,
            "page": page,
        }

        response = requests.get(ACLED_READ_URL, headers=headers, params=params, timeout=60)

        if response.status_code != 200:
            raise RuntimeError(
                f"ACLED fetch failed on page {page}: status {response.status_code}, "
                f"body: {response.text[:500]}"
            )

        payload = response.json()
        records = payload.get("data", [])
        all_events.extend(records)

        # Stop paginating once a page comes back with fewer records than the limit
        if len(records) < DEFAULT_PAGE_LIMIT:
            break
        page += 1

    return all_events


def main():
    parser = argparse.ArgumentParser(description="Fetch recent ACLED events for MERIDIAN")
    parser.add_argument("--days-back", type=int, default=7, help="How many days back to fetch")
    parser.add_argument(
        "--region",
        type=str,
        default=None,
        help="Restrict to one named region (e.g. 'Western Africa'). Omit for all MERIDIAN regions.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write raw JSON output to this file path. Omit to print to stdout.",
    )
    args = parser.parse_args()

    region_codes = None
    if args.region:
        if args.region not in MERIDIAN_REGION_CODES:
            print(f"Unknown region '{args.region}'. Valid options: {list(MERIDIAN_REGION_CODES.keys())}")
            sys.exit(1)
        region_codes = [MERIDIAN_REGION_CODES[args.region]]

    events = fetch_recent_events(days_back=args.days_back, region_codes=region_codes)

    print(f"Fetched {len(events)} raw ACLED events "
          f"(last {args.days_back} days, region(s): {args.region or 'all MERIDIAN regions'})",
          file=sys.stderr)

    output_json = json.dumps(events, indent=2)
    if args.output:
        Path(args.output).write_text(output_json)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
