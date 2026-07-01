"""
scripts/ingestion/worldbank_normalize.py

Maps raw World Bank indicator records into MERIDIAN's common
normalized_event schema (see schemas/normalized_event.schema.json). Unlike
ACLED/GDELT/ReliefWeb, these aren't discrete incidents — each record is one
country/indicator/year data point, treated as an "economic_indicator" event
dated to the end of that year (World Bank data has year precision only, no
month/day). severity_score is left null: a single macro indicator reading
isn't inherently a 0-10 severity the way a conflict event is — that judgment
belongs to the future risk-scoring/synthesis layer that looks at indicators
in combination, not to this normalization step.

Usage:
    python scripts/ingestion/worldbank_normalize.py --input raw_worldbank.json --output normalized.json

Or as a module:
    from scripts.ingestion.worldbank_normalize import normalize_worldbank_record, normalize_batch
"""

import sys
import argparse
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.lib.regions import lookup_by_iso3, GLOBAL_OTHER_REGION
from scripts.lib.worldbank_indicators import INDICATORS


def make_meridian_event_id(source: str, source_event_id: str) -> str:
    """Deterministic ID so re-running ingestion doesn't create duplicate records."""
    raw = f"{source}:{source_event_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _format_value(value: float, indicator_code: str) -> str:
    if "GDP" in indicator_code.replace(".", "") and "ZG" in indicator_code:
        return f"{value:.1f}%"
    if indicator_code.endswith(".ZS") or indicator_code.endswith(".ZG"):
        return f"{value:.1f}%"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000_000:.2f}B" if abs(value) >= 1_000_000_000 else f"${value / 1_000_000:.1f}M"
    return f"{value:.2f}"


def normalize_worldbank_record(raw_record: dict) -> dict | None:
    """Maps a single raw World Bank indicator record into the MERIDIAN
    normalized_event schema. Returns None if the value is missing (World
    Bank frequently has gaps for the most recent 1-2 years) or the year is
    unparseable — both are expected, not errors."""
    value = raw_record.get("value")
    if value is None:
        return None

    year_str = raw_record.get("date", "")
    try:
        event_date = f"{int(year_str)}-12-31"
    except (ValueError, TypeError):
        return None

    iso3 = raw_record.get("countryiso3code", "")
    geo = lookup_by_iso3(iso3)
    if geo is not None:
        country_name, region, in_core_mandate = geo
    else:
        country_name = raw_record.get("country", {}).get("value", iso3)
        region, in_core_mandate = GLOBAL_OTHER_REGION, False

    indicator_code = raw_record.get("indicator", {}).get("id", "")
    indicator_label = INDICATORS.get(indicator_code, (raw_record.get("indicator", {}).get("value", indicator_code),))[0]
    source_event_id = f"{iso3}:{indicator_code}:{year_str}"

    return {
        "meridian_event_id": make_meridian_event_id("WorldBank", source_event_id),
        "source": "WorldBank",
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
        "narrative_summary": f"{indicator_label}: {_format_value(value, indicator_code)} ({year_str})",
        "source_url": f"https://data.worldbank.org/indicator/{indicator_code}?locations={iso3}",
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "raw_source_data": raw_record,
    }


def normalize_batch(raw_records: list[dict]) -> list[dict]:
    """Normalizes a list of raw World Bank records, skipping records with no
    value or unparseable dates rather than failing the whole batch."""
    normalized = []
    skipped = 0
    for raw_record in raw_records:
        try:
            result = normalize_worldbank_record(raw_record)
            if result is None:
                skipped += 1
                continue
            normalized.append(result)
        except Exception as e:
            skipped += 1
            print(f"WARNING: skipped malformed World Bank record: {e}", file=sys.stderr)
    if skipped:
        print(f"Normalization complete with {skipped} record(s) skipped out of {len(raw_records)}.",
              file=sys.stderr)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Normalize raw World Bank records into MERIDIAN schema")
    parser.add_argument("--input", type=str, required=True, help="Path to raw World Bank JSON (from worldbank_fetch.py)")
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
