"""
scripts/ingestion/worldbank_ppi_fetch.py

Fetches the World Bank's Private Participation in Infrastructure (PPI)
Database -- private-sector infrastructure investment commitments (energy,
transport, water, ICT) in developing countries, 1990-2024. This is a third
"who's investing here" angle distinct from AidData (Chinese government
finance) and DFC (U.S. government finance): PPI tracks private capital,
with development-bank (IBRD/IDA/IFC/MIGA) support flagged separately where
present.

This is a different backend from the main World Bank indicator API
(data.worldbank.org, which needs curl_cffi to get past Cloudflare) -- the
PPI site (ppi.worldbank.org / www.worldbank.org) is a standard World Bank
web property with no bot-protection encountered, so plain `requests`
works. Publishes a static bulk Stata (.dta) file covering the full
database rather than a live API; re-running this script re-downloads
whatever the current published version is.

Usage (CLI):
    python scripts/ingestion/worldbank_ppi_fetch.py --output raw_ppi.json

Usage (as a module):
    from scripts.ingestion.worldbank_ppi_fetch import fetch_all_records
    records = fetch_all_records()
"""

import sys
import argparse
import json
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests
import pandas as pd

DATASET_URL = "https://www.worldbank.org/content/dam/PPI/documents/2024-PPI-Full-DTA.dta"


def fetch_all_records() -> list[dict]:
    """Downloads the current PPI bulk Stata file and returns every project
    row as a dict keyed by the dataset's own column names (see PPI's
    "Resources"/data dictionary at ppi.worldbank.org/en/resources/ppi-resources
    for full field definitions -- normalize.py only uses a subset)."""
    response = requests.get(DATASET_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(f"World Bank PPI download failed: status {response.status_code}")

    df = pd.read_stata(io.BytesIO(response.content))
    return df.to_dict(orient="records")


def main():
    parser = argparse.ArgumentParser(description="Fetch World Bank PPI Database")
    parser.add_argument("--output", type=str, default=None,
                         help="Write raw JSON output to this file path. Omit to print to stdout.")
    args = parser.parse_args()

    records = fetch_all_records()
    print(f"Fetched {len(records)} raw PPI project records", file=sys.stderr)

    def _json_safe(value):
        if isinstance(value, float) and value != value:  # NaN
            return None
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if pd.isna(value):
            return None
        return str(value)

    clean_records = [{k: _json_safe(v) for k, v in r.items()} for r in records]

    output_json = json.dumps(clean_records, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
