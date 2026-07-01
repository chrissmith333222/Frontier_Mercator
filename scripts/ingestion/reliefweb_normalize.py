"""
scripts/ingestion/reliefweb_normalize.py

Maps raw ReliefWeb (UN OCHA) report records into MERIDIAN's common
normalized_event schema (see schemas/normalized_event.schema.json). This is
the only place ReliefWeb's field names should appear outside of
reliefweb_fetch.py and this file.

A single ReliefWeb report can reference multiple countries — this module
emits one normalized event per (report, country) pair, consistent with every
other source giving one location per event.

Reuses the region/mandate dicts already defined in acled_normalize.py
(COUNTRY_TO_MERIDIAN_REGION, EXTENDED_COUNTRY_TO_REGION, GLOBAL_OTHER_REGION)
rather than redefining them a third time — ReliefWeb, like ACLED, gives plain
country names, so the same lookup applies directly.

Usage:
    python scripts/ingestion/reliefweb_normalize.py --input raw_reliefweb.json --output normalized.json

Or as a module:
    from scripts.ingestion.reliefweb_normalize import normalize_reliefweb_report, normalize_batch
"""

import sys
import argparse
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.ingestion.acled_normalize import (
    COUNTRY_TO_MERIDIAN_REGION, EXTENDED_COUNTRY_TO_REGION, GLOBAL_OTHER_REGION,
)

# ReliefWeb "format" (document type) -> a coarse severity base. Situation
# reports and appeals track active crises and score higher than general news/
# analysis. Intentionally simple and transparent, same convention as the
# ACLED/GDELT scorers.
FORMAT_SEVERITY_BASE = {
    "Appeal": 5.0,
    "Situation Report": 4.5,
    "Emergency Response Plan": 5.0,
    "Assessment": 3.5,
    "Evaluation and Lessons Learned": 2.5,
    "Analysis": 2.5,
    "News and Press Release": 2.0,
    "Map": 1.5,
}
DEFAULT_SEVERITY_BASE = 2.0

# Disaster types associated with active conflict/displacement score a bit
# higher than purely weather/climate-driven ones, reflecting the security-
# analysis half of MERIDIAN's mandate (not just humanitarian tracking).
DISASTER_TYPE_BUMP = {
    "Complex Emergency": 2.0,
    "Population Movement": 1.5,
    "Epidemic": 1.0,
}


def make_meridian_event_id(source: str, source_event_id: str) -> str:
    """Deterministic ID so re-running ingestion doesn't create duplicate records."""
    raw = f"{source}:{source_event_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def compute_severity_score(fields: dict) -> float:
    formats = fields.get("format", []) or []
    format_name = formats[0].get("name") if formats else None
    base = FORMAT_SEVERITY_BASE.get(format_name, DEFAULT_SEVERITY_BASE)

    disaster_types = fields.get("disaster_type", []) or []
    bump = 0.0
    for dt in disaster_types:
        bump = max(bump, DISASTER_TYPE_BUMP.get(dt.get("name"), 0.0))

    return min(round(base + bump, 1), 10.0)


def _assign_region(country_name: str) -> tuple[str, bool]:
    if country_name in COUNTRY_TO_MERIDIAN_REGION:
        return COUNTRY_TO_MERIDIAN_REGION[country_name], True
    if country_name in EXTENDED_COUNTRY_TO_REGION:
        return EXTENDED_COUNTRY_TO_REGION[country_name], False
    return GLOBAL_OTHER_REGION, False


def normalize_reliefweb_report(raw_report: dict) -> list[dict]:
    """Maps a single raw ReliefWeb report into one or more MERIDIAN normalized
    events — one per country the report references. Returns an empty list if
    the report has no usable country or date (malformed)."""
    fields = raw_report.get("fields", {})
    report_id = str(raw_report.get("id", ""))
    title = fields.get("title", "")

    date_info = fields.get("date", {}) or {}
    event_date_raw = date_info.get("original") or date_info.get("created")
    if not event_date_raw:
        return []
    try:
        event_date = datetime.fromisoformat(event_date_raw.replace("Z", "+00:00")).date().isoformat()
    except (ValueError, AttributeError):
        return []

    countries = fields.get("country", []) or []
    if not countries:
        return []

    sources = fields.get("source", []) or []
    source_name = sources[0].get("name") if sources else None

    severity = compute_severity_score(fields)
    body_snippet = (fields.get("body") or "")[:500]

    normalized = []
    for country_info in countries:
        country_name = country_info.get("name", "")
        if not country_name:
            continue
        region, in_core_mandate = _assign_region(country_name)
        source_event_id = f"{report_id}:{country_info.get('iso3', country_name)}"

        normalized.append({
            "meridian_event_id": make_meridian_event_id("ReliefWeb", source_event_id),
            "source": "ReliefWeb",
            "source_event_id": source_event_id,
            "event_date": event_date,
            "country": country_name,
            "iso3": country_info.get("iso3"),
            "admin1": None,
            "region": region,
            "in_core_mandate": in_core_mandate,
            "latitude": None,
            "longitude": None,
            "event_category": "humanitarian",
            "event_subtype": (fields.get("format") or [{}])[0].get("name"),
            "actors": [{"name": source_name, "type": "reporting_source"}] if source_name else [],
            "fatalities": None,
            "severity_score": severity,
            "narrative_summary": title or body_snippet[:200],
            "source_url": fields.get("url"),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "raw_source_data": raw_report,
        })
    return normalized


def normalize_batch(raw_reports: list[dict]) -> list[dict]:
    """Normalizes a list of raw ReliefWeb reports, skipping records that fail
    to normalize rather than failing the whole batch."""
    normalized = []
    skipped = 0
    for raw_report in raw_reports:
        try:
            results = normalize_reliefweb_report(raw_report)
            if not results:
                skipped += 1
                continue
            normalized.extend(results)
        except Exception as e:
            skipped += 1
            print(f"WARNING: skipped malformed ReliefWeb record "
                  f"({raw_report.get('id', 'unknown id')}): {e}", file=sys.stderr)
    if skipped:
        print(f"Normalization complete with {skipped} record(s) skipped out of {len(raw_reports)}.",
              file=sys.stderr)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Normalize raw ReliefWeb reports into MERIDIAN schema")
    parser.add_argument("--input", type=str, required=True, help="Path to raw ReliefWeb JSON (from reliefweb_fetch.py)")
    parser.add_argument("--output", type=str, default=None, help="Output path. Omit to print to stdout.")
    args = parser.parse_args()

    raw_reports = json.loads(Path(args.input).read_text())
    normalized = normalize_batch(raw_reports)

    output_json = json.dumps(normalized, indent=2)
    if args.output:
        Path(args.output).write_text(output_json)
        print(f"Wrote {len(normalized)} normalized events to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
