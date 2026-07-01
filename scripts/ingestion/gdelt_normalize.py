"""
meridian/scripts/ingestion/gdelt_normalize.py

Maps raw GDELT 2.0 event records into MERIDIAN's common normalized_event
schema (see schemas/normalized_event.schema.json). This is the only place
GDELT's field names/CAMEO codes should appear outside of gdelt_fetch.py and
this file.

Usage:
    python scripts/ingestion/gdelt_normalize.py --input raw_gdelt.json --output normalized.json

Or as a module:
    from scripts.ingestion.gdelt_normalize import normalize_gdelt_event, normalize_batch
"""

import sys
import argparse
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.lib.gdelt_geo import lookup_any_country

# CAMEO EventRootCode -> MERIDIAN's coarse event_category.
# GDELT's own taxonomy (CAMEO 1.1b3) is far more granular (20 root codes,
# hundreds of sub-codes) — this collapses it to the same categories ACLED
# events map into, so both sources merge cleanly downstream.
EVENT_ROOT_CODE_MAP = {
    "14": "protest_civil_unrest",       # Protest
    "15": "strategic_development",      # Exhibit military posture
    "16": "strategic_development",      # Reduce relations
    "17": "conflict",                   # Coerce
    "18": "political_violence_targeting_civilians",  # Assault
    "19": "conflict",                   # Fight
    "20": "explosion_remote_violence",  # Use unconventional mass violence
}

# Base severity by EventRootCode, mirroring ACLED's transparent-scoring approach.
BASE_SEVERITY_BY_ROOT_CODE = {
    "14": 3.0, "15": 4.0, "16": 3.0, "17": 5.0, "18": 6.5, "19": 6.0, "20": 7.0,
}


def compute_severity_score(record: dict) -> float:
    """
    MERIDIAN's 0-10 severity score for a GDELT event: base score from the
    CAMEO event root code, adjusted upward by how conflictual GDELT's own
    Goldstein Scale rates the event (Goldstein runs -10 to +10; more negative
    = more conflictual). Capped at 10, same convention as the ACLED scorer.
    """
    root_code = record.get("EventRootCode", "")
    base = BASE_SEVERITY_BY_ROOT_CODE.get(root_code, 1.5)

    try:
        goldstein = float(record.get("GoldsteinScale", 0) or 0)
    except (ValueError, TypeError):
        goldstein = 0.0

    goldstein_bump = max(0.0, -goldstein / 10.0 * 3.0)  # 0 to 3.0 as goldstein -> -10

    return min(round(base + goldstein_bump, 1), 10.0)


def make_meridian_event_id(source: str, source_event_id: str) -> str:
    """Deterministic ID so re-running ingestion doesn't create duplicate records."""
    raw = f"{source}:{source_event_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def extract_actors(record: dict) -> list[dict]:
    """Pulls Actor1Name/Actor2Name into MERIDIAN's actors array. GDELT doesn't
    give a clean actor "type" the way ACLED's inter1/inter2 codes do, so we
    carry the raw CAMEO actor type code as-is for traceability."""
    actors = []
    for name_field, type_field in [("Actor1Name", "Actor1Type1Code"), ("Actor2Name", "Actor2Type1Code")]:
        name = record.get(name_field)
        if name:
            actors.append({
                "name": name,
                "type": record.get(type_field) or "unknown",
            })
    return actors


def normalize_gdelt_event(record: dict) -> dict | None:
    """Maps a single raw GDELT record into the MERIDIAN normalized_event schema.
    Returns None if the event's location doesn't resolve to either the core
    Africa/LatAm mandate or the extended Europe/Middle East monitoring list
    (shouldn't happen post-fetch-filtering, but defensive here too)."""
    fips_code = record.get("ActionGeo_CountryCode", "")
    geo = lookup_any_country(fips_code)
    if geo is None:
        return None
    country, iso3, region, in_core_mandate = geo

    source_event_id = record.get("GLOBALEVENTID", "")
    root_code = record.get("EventRootCode", "")
    sql_date = record.get("SQLDATE", "")  # format YYYYMMDD

    try:
        event_date = datetime.strptime(sql_date, "%Y%m%d").date().isoformat()
    except ValueError:
        event_date = None

    try:
        lat = float(record["ActionGeo_Lat"]) if record.get("ActionGeo_Lat") not in (None, "") else None
        lon = float(record["ActionGeo_Long"]) if record.get("ActionGeo_Long") not in (None, "") else None
    except (ValueError, TypeError):
        lat, lon = None, None

    actor1 = record.get("Actor1Name") or "unspecified actor"
    actor2 = record.get("Actor2Name") or "unspecified actor"
    narrative_summary = f"{actor1} <-> {actor2} (CAMEO {record.get('EventCode', '?')})"

    return {
        "meridian_event_id": make_meridian_event_id("GDELT", source_event_id),
        "source": "GDELT",
        "source_event_id": source_event_id,
        "event_date": event_date,
        "country": country,
        "iso3": iso3,
        "admin1": record.get("ActionGeo_ADM1Code"),
        "region": region,
        "in_core_mandate": in_core_mandate,
        "latitude": lat,
        "longitude": lon,
        "event_category": EVENT_ROOT_CODE_MAP.get(root_code, "other"),
        "event_subtype": record.get("EventCode"),
        "actors": extract_actors(record),
        "fatalities": None,  # GDELT doesn't report fatality counts (unlike ACLED)
        "severity_score": compute_severity_score(record),
        "narrative_summary": narrative_summary,
        "source_url": record.get("SOURCEURL"),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "raw_source_data": record,
    }


def normalize_batch(raw_events: list[dict]) -> list[dict]:
    """Normalizes a list of raw GDELT events, skipping records that fail to
    normalize (malformed or non-mandate-country) rather than failing the batch."""
    normalized = []
    skipped = 0
    for record in raw_events:
        try:
            result = normalize_gdelt_event(record)
            if result is None:
                skipped += 1
                continue
            normalized.append(result)
        except Exception as e:
            skipped += 1
            print(f"WARNING: skipped malformed GDELT record "
                  f"({record.get('GLOBALEVENTID', 'unknown id')}): {e}", file=sys.stderr)
    if skipped:
        print(f"Normalization complete with {skipped} record(s) skipped out of {len(raw_events)}.",
              file=sys.stderr)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Normalize raw GDELT events into MERIDIAN schema")
    parser.add_argument("--input", type=str, required=True, help="Path to raw GDELT JSON (from gdelt_fetch.py)")
    parser.add_argument("--output", type=str, default=None, help="Output path. Omit to print to stdout.")
    args = parser.parse_args()

    raw_events = json.loads(Path(args.input).read_text())
    normalized = normalize_batch(raw_events)

    output_json = json.dumps(normalized, indent=2)
    if args.output:
        Path(args.output).write_text(output_json)
        print(f"Wrote {len(normalized)} normalized events to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
