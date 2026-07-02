"""
scripts/ingestion/aiddata_fetch.py

Fetches AidData's Global Chinese Development Finance Dataset (GCDF 3.0) --
20,985 Chinese government-financed projects (loans + grants) across 165
low/middle-income countries, 2000-2021 commitments. This is the concrete
"who's investing here" (China) data source Chris asked for. No auth needed:
AidData publishes a direct-download zip, no registration/API key.

Unlike the live-API sources, this is a static bulk dataset AidData updates
periodically (not continuously) -- re-running this script re-downloads the
current published version rather than polling for new records.

Usage (CLI):
    python scripts/ingestion/aiddata_fetch.py --output raw_aiddata.json

Usage (as a module):
    from scripts.ingestion.aiddata_fetch import fetch_all_records
    records = fetch_all_records()
"""

import sys
import argparse
import json
import zipfile
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests
import openpyxl

DATASET_URL = (
    "https://docs.aiddata.org/ad4/datasets/"
    "AidDatas_Global_Chinese_Development_Finance_Dataset_Version_3_0.zip"
)
XLSX_PATH_IN_ZIP = (
    "AidDatas_Global_Chinese_Development_Finance_Dataset_Version_3_0/"
    "AidDatasGlobalChineseDevelopmentFinanceDataset_v3.0.xlsx"
)
SHEET_NAME = "GCDF_3.0"


def fetch_all_records() -> list[dict]:
    """Downloads the current GCDF 3.0 zip, extracts the main workbook, and
    returns every project row as a dict keyed by the workbook's own column
    headers (128 columns -- see AidData's "Field Definitions" PDF in the zip
    for the full data dictionary; normalize.py only uses a subset)."""
    response = requests.get(DATASET_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(f"AidData download failed: status {response.status_code}")

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        with zf.open(XLSX_PATH_IN_ZIP) as f:
            wb = openpyxl.load_workbook(io.BytesIO(f.read()), read_only=True, data_only=True)

    ws = wb[SHEET_NAME]
    rows = ws.iter_rows(values_only=True)
    header = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(next(rows))]

    records = []
    for row in rows:
        record = dict(zip(header, row))
        # Skip fully blank trailing rows (openpyxl sometimes yields a few past the real data)
        if record.get("AidData Record ID") is None:
            continue
        records.append(record)

    return records


def main():
    parser = argparse.ArgumentParser(description="Fetch AidData Global Chinese Development Finance dataset")
    parser.add_argument("--output", type=str, default=None,
                         help="Write raw JSON output to this file path. Omit to print to stdout.")
    args = parser.parse_args()

    records = fetch_all_records()
    print(f"Fetched {len(records)} raw AidData project records", file=sys.stderr)

    # openpyxl can yield datetime objects for date columns -- not JSON
    # serializable as-is, so stringify anything that isn't a plain type.
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
