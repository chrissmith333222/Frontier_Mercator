"""
scripts/ingestion/imf_fetch.py

Fetches raw IMF World Economic Outlook indicator data (via the DataMapper
API) for MERIDIAN's mandate countries. No auth needed. Returns raw records
(one dict per country/indicator/year) — does NOT normalize them. See
imf_normalize.py for the mapping into MERIDIAN's common schema.

The DataMapper API's own country/period filtering (path segments, `periods`
querystring) doesn't reliably restrict the response in practice -- a query
for one country's data came back with the full global time series for every
country regardless. Rather than depend on that, this fetch always pulls the
complete per-indicator dataset (one request each, IMF doesn't paginate this
endpoint) and filters down to tracked countries/years locally. Costs a bit
more bandwidth per call but is actually simpler and correctness-guaranteed
either way, same lesson as ACLED's unreliable region filter.

Usage (CLI):
    python scripts/ingestion/imf_fetch.py --countries NGA,KEN,COL --years-back 5
    python scripts/ingestion/imf_fetch.py --years-back 5   # all tracked countries

Usage (as a module):
    from scripts.ingestion.imf_fetch import fetch_indicator_data
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
from scripts.lib.imf_indicators import DEFAULT_INDICATOR_CODES

IMF_API_URL = "https://www.imf.org/external/datamapper/api/v1/{indicator}"
IMPERSONATE_BROWSER = "chrome"
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5


def _get_with_retry(url: str):
    """Government/IFI data APIs have repeatedly turned out to sit behind bot
    management that's flaky rather than a clean pass/fail (see World Bank) --
    retry defensively here too rather than assuming IMF is different."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = curl_requests.get(url, impersonate=IMPERSONATE_BROWSER, timeout=60)
        except curl_requests.exceptions.Timeout as e:
            last_error = f"timeout: {e}"
            response = None
        if response is not None and response.status_code == 200:
            return response
        if response is not None:
            last_error = f"status {response.status_code}: {response.text[:200]}"
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"IMF request failed after {MAX_RETRIES} attempts: {last_error}")


def fetch_indicator_data(
    countries: list[str] | None = None,
    indicator_codes: list[str] | None = None,
    years_back: int = 5,
) -> list[dict]:
    """
    Fetches IMF WEO indicator data points for the given ISO3 country codes
    (defaults to every country MERIDIAN tracks) and indicator codes (defaults
    to the curated list in imf_indicators.py), for the last `years_back`
    years. Returns a flat list of {"indicator": code, "iso3": ..., "year":
    ..., "value": ...} records, one per country/indicator/year.
    """
    if countries is None:
        countries = sorted(ISO3_TO_INFO.keys())
    if indicator_codes is None:
        indicator_codes = DEFAULT_INDICATOR_CODES

    country_set = set(countries)
    end_year = date.today().year
    start_year = end_year - years_back

    all_records = []
    for indicator in indicator_codes:
        url = IMF_API_URL.format(indicator=indicator)
        response = _get_with_retry(url)
        payload = response.json()
        by_country = payload.get("values", {}).get(indicator, {})

        for iso3, year_values in by_country.items():
            if iso3 not in country_set:
                continue
            for year_str, value in year_values.items():
                try:
                    year = int(year_str)
                except ValueError:
                    continue
                if not (start_year <= year <= end_year):
                    continue
                all_records.append({
                    "indicator": indicator,
                    "iso3": iso3,
                    "year": year_str,
                    "value": value,
                })

    return all_records


def main():
    parser = argparse.ArgumentParser(description="Fetch IMF WEO indicator data for MERIDIAN")
    parser.add_argument("--countries", type=str, default=None,
                         help="Comma-separated ISO3 codes (e.g. NGA,KEN,COL). Omit for all tracked countries.")
    parser.add_argument("--years-back", type=int, default=5, help="How many years back to fetch")
    parser.add_argument("--output", type=str, default=None,
                         help="Write raw JSON output to this file path. Omit to print to stdout.")
    args = parser.parse_args()

    countries = args.countries.split(",") if args.countries else None
    records = fetch_indicator_data(countries=countries, years_back=args.years_back)

    print(f"Fetched {len(records)} raw IMF indicator records "
          f"(last {args.years_back} years, countries: {args.countries or 'all tracked'})", file=sys.stderr)

    output_json = json.dumps(records, indent=2)
    if args.output:
        Path(args.output).write_text(output_json)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
