"""
scripts/ingestion/dfc_fetch.py

Fetches the U.S. International Development Finance Corporation's (DFC)
Annual Project Data -- the U.S. government's counterpart to AidData's
Chinese development finance dataset, useful for the same "who's investing
here" analysis from the other side (U.S. loans/guarantees/equity/insurance
across ~120 countries, legacy OPIC deals included back to the 1960s).

Static bulk Excel download, no auth, no Cloudflare protection encountered
(unlike World Bank/Bellingcat) -- plain `requests` with a standard User-
Agent works. DFC republishes this file once per fiscal year under a
filename that includes the FY, so re-running this script will need its
DATASET_URL updated when DFC cuts a new fiscal-year file (check
https://www.dfc.gov/our-impact/transaction-data for the current link).

Usage (CLI):
    python scripts/ingestion/dfc_fetch.py --output raw_dfc.json

Usage (as a module):
    from scripts.ingestion.dfc_fetch import fetch_all_records
    records = fetch_all_records()
"""

import sys
import argparse
import json
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests
import openpyxl

DATASET_URL = (
    "https://www.dfc.gov/sites/default/files/media/documents/"
    "FY24%20DFC%20Annual%20Project%20Data_508.xlsx"
)
SHEET_NAME = "Project Data"


def fetch_all_records() -> list[dict]:
    """Downloads the current DFC Annual Project Data workbook and returns
    every project row as a dict keyed by the sheet's own column headers.
    The sheet has a title row above the real header row, so the header is
    the second row, not the first."""
    response = requests.get(DATASET_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(f"DFC download failed: status {response.status_code}")

    wb = openpyxl.load_workbook(io.BytesIO(response.content), read_only=True, data_only=True)
    ws = wb[SHEET_NAME]
    rows = ws.iter_rows(values_only=True)
    next(rows)  # title row ("Project Data")
    header = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(next(rows))]

    records = []
    for row_index, row in enumerate(rows):
        record = dict(zip(header, row))
        # Skip fully blank trailing rows
        if record.get("Project Number") is None:
            continue
        # A meaningful number of rows have "Redacted" as the literal
        # Project Number (classified/sensitive deals) -- that string alone
        # isn't a unique key, so every redacted row needs a distinguishing
        # position marker for downstream ID generation.
        record["_row_index"] = row_index
        records.append(record)

    return records


def main():
    parser = argparse.ArgumentParser(description="Fetch DFC Annual Project Data")
    parser.add_argument("--output", type=str, default=None,
                         help="Write raw JSON output to this file path. Omit to print to stdout.")
    args = parser.parse_args()

    records = fetch_all_records()
    print(f"Fetched {len(records)} raw DFC project records", file=sys.stderr)

    def _json_safe(value):
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
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
