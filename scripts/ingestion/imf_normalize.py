"""
scripts/ingestion/imf_normalize.py

Maps raw IMF WEO indicator records (from imf_fetch.py's flat {"indicator",
"iso3", "year", "value"} shape) into MERIDIAN's common normalized_event
schema. Same conventions as worldbank_normalize.py: each record is an
"economic_indicator" event dated to year-end, severity_score left null (a
single macro reading isn't inherently a 0-10 severity judgment on its own).

Usage:
    python scripts/ingestion/imf_normalize.py --input raw_imf.json --output normalized.json

Or as a module:
    from scripts.ingestion.imf_normalize import normalize_imf_record, normalize_batch
"""

import sys
import argparse
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.lib.regions import lookup_by_iso3, GLOBAL_OTHER_REGION
from scripts.lib.imf_indicators import INDICATORS


def make_meridian_event_id(source: str, source_event_id: str) -> str:
    """Deterministic ID so re-running ingestion doesn't create duplicate records."""
    raw = f"{source}:{source_event_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _format_value(value: float, indicator_code: str) -> str:
    if indicator_code in ("NGDP_RPCH", "PCPIPCH", "GGXWDG_NGDP", "BCA_NGDPD", "LUR"):
        return f"{value:.1f}%"
    return f"{value:.2f}"


def normalize_imf_record(raw_record: dict) -> dict | None:
    """Maps a single raw IMF indicator record into the MERIDIAN
    normalized_event schema. Returns None if the value is missing/null
    (IMF WEO data frequently has gaps, especially for smaller economies) or
    the year is unparseable."""
    value = raw_record.get("value")
    if value is None:
        return None

    try:
        event_date = f"{int(raw_record.get('year')):04d}-12-31"
    except (ValueError, TypeError):
        return None

    iso3 = raw_record.get("iso3", "")
    geo = lookup_by_iso3(iso3)
    if geo is not None:
        country_name, region, in_core_mandate = geo
    else:
        country_name, region, in_core_mandate = iso3, GLOBAL_OTHER_REGION, False

    indicator_code = raw_record.get("indicator", "")
    indicator_label = INDICATORS.get(indicator_code, (indicator_code,))[0]
    source_event_id = f"{iso3}:{indicator_code}:{raw_record.get('year')}"

    return {
        "meridian_event_id": make_meridian_event_id("IMF", source_event_id),
        "source": "IMF",
        "source_event_id": source_event_id,
        "event_date": event_date,
        "country": country_name,
        "iso3": iso3,
        "admin1": None,
        "region": region,
        "in_core_mandate": in_core_mandate,
        "latitude": None,
        "longitude": None,
        "event_category": "economic_indicator",
        "event_subtype": indicator_code,
        "actors": [],
        "fatalities": None,
        "severity_score": None,
        "narrative_summary": f"{indicator_label}: {_format_value(value, indicator_code)} ({raw_record.get('year')})",
        "source_url": "https://www.imf.org/en/Publications/WEO",
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "raw_source_data": raw_record,
    }


def normalize_batch(raw_records: list[dict]) -> list[dict]:
    """Normalizes a list of raw IMF records, skipping records with no value
    or unparseable years rather than failing the whole batch."""
    normalized = []
    skipped = 0
    for raw_record in raw_records:
        try:
            result = normalize_imf_record(raw_record)
            if result is None:
                skipped += 1
                continue
            normalized.append(result)
        except Exception as e:
            skipped += 1
            print(f"WARNING: skipped malformed IMF record: {e}", file=sys.stderr)
    if skipped:
        print(f"Normalization complete with {skipped} record(s) skipped out of {len(raw_records)}.",
              file=sys.stderr)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Normalize raw IMF records into MERIDIAN schema")
    parser.add_argument("--input", type=str, required=True, help="Path to raw IMF JSON (from imf_fetch.py)")
    parser.add_argument("--output", type=str, default=None, help="Output path. Omit to print to stdout.")
    args = parser.parse_args()

    raw_records = json.loads(Path(args.input).read_text())
    normalized = normalize_batch(raw_records)

    output_json = json.dumps(normalized, indent=2)
    if args.output:
        Path(args.output).write_text(output_json)
        print(f"Wrote {len(normalized)} normalized events to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
