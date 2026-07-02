"""
scripts/ingestion/unosat_normalize.py

Maps raw UNOSAT/HDX product records into MERIDIAN's common
normalized_event schema, event_category="humanitarian" -- satellite-based
damage/disaster/flood assessments and conflict-monitoring products, the
written conclusions of a rigorous imagery-analysis organization (see
unosat_fetch.py for the OSINT-strategy rationale).

HDX's CKAN schema gives structured country tagging via `groups` (ISO3
lowercase codes, e.g. 'ven' for Venezuela) -- far more reliable than
Bellingcat's text-scanning heuristic, so no country-name matching is
needed here. `dataset_date` is HDX's bracketed date-range convention
(`[START TO END]`); the start date is used as event_date.

Usage:
    python scripts/ingestion/unosat_normalize.py --input raw_unosat.json --output normalized.json

Or as a module:
    from scripts.ingestion.unosat_normalize import normalize_unosat_record, normalize_batch
"""

import re
import sys
import argparse
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.lib.world_countries import ALL_COUNTRIES
from scripts.lib.regions import GLOBAL_OTHER_REGION

_DATE_RANGE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})")


def make_meridian_event_id(source: str, source_event_id: str) -> str:
    """Deterministic ID so re-running ingestion doesn't create duplicate records."""
    raw = f"{source}:{source_event_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _parse_event_date(dataset_date: str | None) -> str | None:
    if not dataset_date:
        return None
    match = _DATE_RANGE_RE.match(dataset_date)
    return match.group(1) if match else None


def _resolve_country(groups: list[dict]) -> tuple[str | None, str, str, bool]:
    """HDX country groups key by lowercase ISO3 -- resolves the first
    group against MERIDIAN's full world-country table. No group (a
    handful of global/methodology products) falls back to Global/Other."""
    if not groups:
        return None, "Global", GLOBAL_OTHER_REGION, False
    iso3 = (groups[0].get("id") or "").upper()
    hit = ALL_COUNTRIES.get(iso3)
    if hit is None:
        display_name = groups[0].get("display_name") or groups[0].get("title") or "Global"
        return None, display_name, GLOBAL_OTHER_REGION, False
    name, region, in_core_mandate = hit
    return iso3, name, region, in_core_mandate


def _first_report_url(resources: list[dict], fallback_url: str) -> str:
    """Prefers a PDF/report-style resource link over shapefiles/
    geodatabases; falls back to the HDX dataset page."""
    for resource in resources or []:
        fmt = (resource.get("format") or "").lower()
        if fmt in ("pdf", "html", "webmap"):
            url = resource.get("download_url") or resource.get("url")
            if url:
                return url
    return fallback_url


def normalize_unosat_record(raw_record: dict) -> dict | None:
    """Maps a single raw UNOSAT/HDX package into the MERIDIAN
    normalized_event schema. Returns None if there's no usable name/title
    or parseable date -- both required for anything downstream to make
    sense of the record."""
    name = raw_record.get("name")
    title = raw_record.get("title", "")
    if not name or not title:
        return None

    event_date = _parse_event_date(raw_record.get("dataset_date"))
    if event_date is None:
        return None

    iso3, country, region, in_core_mandate = _resolve_country(raw_record.get("groups") or [])

    notes = (raw_record.get("notes") or "").strip()
    narrative_summary = title if not notes else f"{title} — {notes.splitlines()[0][:200]}"

    dataset_page_url = f"https://data.humdata.org/dataset/{name}"
    source_url = _first_report_url(raw_record.get("resources") or [], dataset_page_url)

    return {
        "meridian_event_id": make_meridian_event_id("UNOSAT", name),
        "source": "UNOSAT",
        "source_event_id": name,
        "event_date": event_date,
        "country": country,
        "iso3": iso3,
        "admin1": None,
        "region": region,
        "in_core_mandate": in_core_mandate,
        "latitude": None,
        "longitude": None,
        "event_category": "humanitarian",
        "event_subtype": (raw_record.get("dataset_source") or "UNOSAT product"),
        "actors": [],
        "fatalities": None,
        "severity_score": None,
        "narrative_summary": narrative_summary,
        "source_url": source_url,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "raw_source_data": None,
    }


def normalize_batch(raw_records: list[dict]) -> list[dict]:
    """Normalizes a list of raw UNOSAT/HDX records, skipping malformed/
    incomplete entries rather than failing the whole batch."""
    normalized = []
    skipped = 0
    for raw_record in raw_records:
        try:
            result = normalize_unosat_record(raw_record)
            if result is None:
                skipped += 1
                continue
            normalized.append(result)
        except Exception as e:
            skipped += 1
            print(f"WARNING: skipped malformed UNOSAT record "
                  f"({raw_record.get('name', 'unknown id')}): {e}", file=sys.stderr)
    if skipped:
        print(f"Normalization complete with {skipped} record(s) skipped out of {len(raw_records)}.",
              file=sys.stderr)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Normalize raw UNOSAT records into MERIDIAN schema")
    parser.add_argument("--input", type=str, required=True, help="Path to raw UNOSAT JSON (from unosat_fetch.py)")
    parser.add_argument("--output", type=str, default=None, help="Output path. Omit to print to stdout.")
    args = parser.parse_args()

    raw_records = json.loads(Path(args.input).read_text(encoding="utf-8"))
    normalized = normalize_batch(raw_records)

    output_json = json.dumps(normalized, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Wrote {len(normalized)} normalized events to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
