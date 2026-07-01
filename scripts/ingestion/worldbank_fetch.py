"""
scripts/ingestion/worldbank_fetch.py

Fetches raw World Bank indicator data (GDP growth, inflation, debt, FDI,
current account, unemployment — see scripts/lib/worldbank_indicators.py) for
MERIDIAN's mandate countries. No auth needed — World Bank's API is fully
open. Returns raw records — does NOT normalize them. See
worldbank_normalize.py for the mapping into MERIDIAN's common schema.

Usage (CLI):
    python scripts/ingestion/worldbank_fetch.py --countries NGA,KEN,COL --years-back 5
    python scripts/ingestion/worldbank_fetch.py --years-back 5   # all tracked countries

Usage (as a module):
    from scripts.ingestion.worldbank_fetch import fetch_indicator_data
    records = fetch_indicator_data(["NGA", "KEN"], years_back=5)
"""

import sys
import time
import argparse
import json
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from curl_cffi import requests as curl_requests
from scripts.lib.regions import ISO3_TO_INFO
from scripts.lib.worldbank_indicators import DEFAULT_INDICATOR_CODES

WORLD_BANK_API_URL = "https://api.worldbank.org/v2/country/{countries}/indicator/{indicator}"
DEFAULT_PER_PAGE = 1000

# World Bank's API sits behind Cloudflare bot management, which silently hangs
# (0 bytes back, no error) on the plain `requests` library's TLS fingerprint —
# a browser User-Agent alone isn't enough, Cloudflare fingerprints the TLS
# handshake itself. curl_cffi impersonates a real Chrome TLS fingerprint,
# which clears it (verified: plain `requests` times out, `curl` and
# `curl_cffi` both succeed instantly against the same endpoint).
IMPERSONATE_BROWSER = "chrome"
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5


def _get_with_retry(url: str, params: dict):
    """Cloudflare's bot check in front of World Bank's API is probabilistic
    under bursty automated traffic -- the exact same query can hang with no
    response, or come back with a transient error page (obesrved: a 400
    "Request Error" IIS page), on one attempt and return real data on the
    next. Retry with backoff on both failure modes rather than failing the
    whole fetch over one flaky request."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = curl_requests.get(url, params=params, impersonate=IMPERSONATE_BROWSER, timeout=60)
        except curl_requests.exceptions.Timeout as e:
            last_error = f"timeout: {e}"
            response = None
        if response is not None and response.status_code == 200:
            return response
        if response is not None:
            last_error = f"status {response.status_code}: {response.text[:200]}"
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"World Bank request failed after {MAX_RETRIES} attempts: {last_error}")


def fetch_indicator_data(
    countries: list[str] | None = None,
    indicator_codes: list[str] | None = None,
    years_back: int = 5,
) -> list[dict]:
    """
    Fetches World Bank indicator records for the given ISO3 country codes
    (defaults to every country MERIDIAN tracks — core mandate + extended
    monitoring) and indicator codes (defaults to the curated list in
    worldbank_indicators.py), for the last `years_back` years.
    """
    if countries is None:
        countries = sorted(ISO3_TO_INFO.keys())
    if indicator_codes is None:
        indicator_codes = DEFAULT_INDICATOR_CODES

    end_year = date.today().year
    start_year = end_year - years_back
    country_path = ";".join(countries)

    all_records = []
    for indicator in indicator_codes:
        url = WORLD_BANK_API_URL.format(countries=country_path, indicator=indicator)
        page = 1
        while True:
            params = {
                "format": "json",
                "per_page": DEFAULT_PER_PAGE,
                "date": f"{start_year}:{end_year}",
                "page": page,
            }
            response = _get_with_retry(url, params)
            payload = response.json()
            if not isinstance(payload, list) or len(payload) < 2:
                break  # World Bank returns an error object (not [meta, data]) for bad requests
            meta, records = payload[0], payload[1] or []
            all_records.extend(records)
            if page >= meta.get("pages", 1):
                break
            page += 1

    return all_records


def main():
    parser = argparse.ArgumentParser(description="Fetch World Bank indicator data for MERIDIAN")
    parser.add_argument("--countries", type=str, default=None,
                         help="Comma-separated ISO3 codes (e.g. NGA,KEN,COL). Omit for all tracked countries.")
    parser.add_argument("--years-back", type=int, default=5, help="How many years back to fetch")
    parser.add_argument("--output", type=str, default=None,
                         help="Write raw JSON output to this file path. Omit to print to stdout.")
    args = parser.parse_args()

    countries = args.countries.split(",") if args.countries else None
    records = fetch_indicator_data(countries=countries, years_back=args.years_back)

    print(f"Fetched {len(records)} raw World Bank indicator records "
          f"(last {args.years_back} years, countries: {args.countries or 'all tracked'})", file=sys.stderr)

    output_json = json.dumps(records, indent=2)
    if args.output:
        Path(args.output).write_text(output_json)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
