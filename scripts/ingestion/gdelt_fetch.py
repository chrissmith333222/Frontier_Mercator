"""
meridian/scripts/ingestion/gdelt_fetch.py

Fetches raw GDELT 2.0 event records, scoped to MERIDIAN's Africa + Latin
America mandate. GDELT has no auth — it publishes a new event file every
15 minutes at data.gdeltproject.org. This script walks backward from the
latest available file for a configurable lookback window, downloads each
15-minute export, and keeps only rows whose event location falls in a
MERIDIAN mandate country. Returns raw records — does NOT normalize them.
See gdelt_normalize.py for the mapping into MERIDIAN's common schema.

GDELT updates every 15 min, so a full 7-day pull is ~672 files. Each file
is small (tens of KB to a few MB zipped), but that's still a lot of HTTP
requests — use --hours-back to scope pulls appropriately (e.g. 24 for a
daily top-up, 168 for a full weekly backfill).

Usage (CLI):
    python scripts/ingestion/gdelt_fetch.py --hours-back 24
    python scripts/ingestion/gdelt_fetch.py --hours-back 168 --output raw_gdelt.json

Usage (as a module):
    from scripts.ingestion.gdelt_fetch import fetch_recent_events
    events = fetch_recent_events(hours_back=24)
"""

import sys
import argparse
import csv
import io
import json
import zipfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests
from scripts.lib.gdelt_geo import MERIDIAN_FIPS_CODES, EXTENDED_FIPS_CODES

# Fetch keeps both the core Africa/LatAm mandate and the extended Europe/
# Middle East monitoring list — normalize_gdelt_event tags each record with
# in_core_mandate so downstream reports can filter appropriately.
TRACKED_FIPS_CODES = MERIDIAN_FIPS_CODES | EXTENDED_FIPS_CODES

GDELT_BASE_URL = "http://data.gdeltproject.org/gdeltv2"
LAST_UPDATE_URL = f"{GDELT_BASE_URL}/lastupdate.txt"

# The GDELT 2.0 event CSV has 61 tab-delimited columns with no header row.
# This is the full, ordered column list from GDELT's official codebook.
GDELT_EVENT_COLUMNS = [
    "GLOBALEVENTID", "SQLDATE", "MonthYear", "Year", "FractionDate",
    "Actor1Code", "Actor1Name", "Actor1CountryCode", "Actor1KnownGroupCode",
    "Actor1EthnicCode", "Actor1Religion1Code", "Actor1Religion2Code",
    "Actor1Type1Code", "Actor1Type2Code", "Actor1Type3Code",
    "Actor2Code", "Actor2Name", "Actor2CountryCode", "Actor2KnownGroupCode",
    "Actor2EthnicCode", "Actor2Religion1Code", "Actor2Religion2Code",
    "Actor2Type1Code", "Actor2Type2Code", "Actor2Type3Code",
    "IsRootEvent", "EventCode", "EventBaseCode", "EventRootCode", "QuadClass",
    "GoldsteinScale", "NumMentions", "NumSources", "NumArticles", "AvgTone",
    "Actor1Geo_Type", "Actor1Geo_FullName", "Actor1Geo_CountryCode",
    "Actor1Geo_ADM1Code", "Actor1Geo_ADM2Code", "Actor1Geo_Lat", "Actor1Geo_Long",
    "Actor1Geo_FeatureID",
    "Actor2Geo_Type", "Actor2Geo_FullName", "Actor2Geo_CountryCode",
    "Actor2Geo_ADM1Code", "Actor2Geo_ADM2Code", "Actor2Geo_Lat", "Actor2Geo_Long",
    "Actor2Geo_FeatureID",
    "ActionGeo_Type", "ActionGeo_FullName", "ActionGeo_CountryCode",
    "ActionGeo_ADM1Code", "ActionGeo_ADM2Code", "ActionGeo_Lat", "ActionGeo_Long",
    "ActionGeo_FeatureID",
    "DATEADDED", "SOURCEURL",
]

MAX_FILES_SAFETY_CAP = 800  # ~8.3 days at 15-min intervals; prevents runaway pulls


def get_latest_timestamp() -> str:
    """Reads GDELT's lastupdate.txt to find the most recent available file's
    timestamp (format: YYYYMMDDHHMMSS). The file has 3 lines (export, mentions,
    gkg) — we want the export line."""
    response = requests.get(LAST_UPDATE_URL, timeout=30)
    response.raise_for_status()
    export_line = response.text.strip().splitlines()[0]
    # Format: "<size> <md5> http://data.gdeltproject.org/gdeltv2/<timestamp>.export.CSV.zip"
    url = export_line.split(" ")[-1]
    filename = url.rsplit("/", 1)[-1]
    return filename.replace(".export.CSV.zip", "")


def fetch_recent_events(hours_back: int = 24, max_files: int | None = None) -> list[dict]:
    """
    Fetches GDELT event records from the last `hours_back` hours, filtered to
    events whose ActionGeo_CountryCode is in MERIDIAN's Africa/LatAm mandate.

    Walks backward from the latest published file in 15-minute steps. Skips
    (rather than fails on) any individual file that 404s — GDELT occasionally
    has gaps — and logs the skip.
    """
    if max_files is None:
        max_files = min(int(hours_back * 4) + 4, MAX_FILES_SAFETY_CAP)

    latest_ts = get_latest_timestamp()
    latest_dt = datetime.strptime(latest_ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)

    matched_events = []
    files_fetched = 0
    files_skipped = 0

    for i in range(max_files):
        file_dt = latest_dt - timedelta(minutes=15 * i)
        if file_dt < latest_dt - timedelta(hours=hours_back):
            break

        ts = file_dt.strftime("%Y%m%d%H%M%S")
        url = f"{GDELT_BASE_URL}/{ts}.export.CSV.zip"

        try:
            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                files_skipped += 1
                continue
            with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                csv_name = zf.namelist()[0]
                with zf.open(csv_name) as f:
                    reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"),
                                         delimiter="\t")
                    for row in reader:
                        if len(row) != len(GDELT_EVENT_COLUMNS):
                            continue
                        record = dict(zip(GDELT_EVENT_COLUMNS, row))
                        if record.get("ActionGeo_CountryCode") in TRACKED_FIPS_CODES:
                            matched_events.append(record)
            files_fetched += 1
        except (requests.RequestException, zipfile.BadZipFile) as e:
            files_skipped += 1
            print(f"WARNING: skipped GDELT file {ts}: {e}", file=sys.stderr)

    print(f"GDELT fetch complete: {files_fetched} files pulled, {files_skipped} skipped, "
          f"{len(matched_events)} tracked-country events matched (core mandate + extended monitoring).",
          file=sys.stderr)

    return matched_events


def main():
    parser = argparse.ArgumentParser(description="Fetch recent GDELT events for MERIDIAN")
    parser.add_argument("--hours-back", type=int, default=24, help="How many hours back to fetch")
    parser.add_argument("--max-files", type=int, default=None,
                         help="Safety cap on number of 15-min files to pull (default: auto-derived)")
    parser.add_argument("--output", type=str, default=None,
                         help="Write raw JSON output to this file path. Omit to print to stdout.")
    args = parser.parse_args()

    events = fetch_recent_events(hours_back=args.hours_back, max_files=args.max_files)

    output_json = json.dumps(events, indent=2)
    if args.output:
        Path(args.output).write_text(output_json)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
