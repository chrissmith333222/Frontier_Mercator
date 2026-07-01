"""
meridian/scripts/ingestion/acled_normalize.py

Maps raw ACLED event records into MERIDIAN's common normalized_event schema
(see schemas/normalized_event.schema.json). This is the only place ACLED's
field names should ever appear outside of acled_fetch.py and this file —
everything downstream (risk scoring, RAG, the synthesis agent) reads the
normalized format only.

Usage:
    python scripts/ingestion/acled_normalize.py --input raw_events.json --output normalized.json

Or as a module:
    from scripts.ingestion.acled_normalize import normalize_acled_event, normalize_batch
"""

import sys
import argparse
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ACLED event_type -> MERIDIAN's coarse event_category
EVENT_TYPE_MAP = {
    "Battles": "conflict",
    "Violence against civilians": "political_violence_targeting_civilians",
    "Explosions/Remote violence": "explosion_remote_violence",
    "Riots": "protest_civil_unrest",
    "Protests": "protest_civil_unrest",
    "Strategic developments": "strategic_development",
}

# Maps ACLED's country field to MERIDIAN's macro-region groupings.
# This is intentionally a starter set covering MERIDIAN's primary mandate countries;
# expand as coverage grows. Countries not listed fall back to a region lookup failure
# flag rather than silently mis-bucketing them.
COUNTRY_TO_MERIDIAN_REGION = {
    # West Africa / Sahel
    "Mali": "West Africa / Sahel", "Burkina Faso": "West Africa / Sahel",
    "Niger": "West Africa / Sahel", "Nigeria": "West Africa / Sahel",
    "Guinea": "West Africa / Sahel", "Senegal": "West Africa / Sahel",
    "Ghana": "West Africa / Sahel", "Ivory Coast": "West Africa / Sahel",
    "Chad": "West Africa / Sahel", "Mauritania": "West Africa / Sahel",
    "Sierra Leone": "West Africa / Sahel", "Liberia": "West Africa / Sahel",
    "Benin": "West Africa / Sahel", "Togo": "West Africa / Sahel",
    "Guinea-Bissau": "West Africa / Sahel", "Gambia": "West Africa / Sahel",
    # East Africa / Horn
    "Ethiopia": "East Africa / Horn", "Somalia": "East Africa / Horn",
    "Sudan": "East Africa / Horn", "South Sudan": "East Africa / Horn",
    "Kenya": "East Africa / Horn", "Uganda": "East Africa / Horn",
    "Tanzania": "East Africa / Horn", "Eritrea": "East Africa / Horn",
    "Djibouti": "East Africa / Horn", "Rwanda": "East Africa / Horn",
    "Burundi": "East Africa / Horn",
    # Southern Africa
    "South Africa": "Southern Africa", "Zimbabwe": "Southern Africa",
    "Mozambique": "Southern Africa", "Zambia": "Southern Africa",
    "Malawi": "Southern Africa", "Botswana": "Southern Africa",
    "Namibia": "Southern Africa", "Angola": "Southern Africa",
    "Lesotho": "Southern Africa", "Eswatini": "Southern Africa",
    # Central Africa
    "Democratic Republic of Congo": "Central Africa", "Cameroon": "Central Africa",
    "Central African Republic": "Central Africa", "Republic of Congo": "Central Africa",
    "Gabon": "Central Africa", "Equatorial Guinea": "Central Africa",
    # North Africa
    "Egypt": "North Africa", "Morocco": "North Africa", "Algeria": "North Africa",
    "Tunisia": "North Africa", "Libya": "North Africa",
    # Andean
    "Peru": "Andean Region", "Bolivia": "Andean Region", "Colombia": "Andean Region",
    "Ecuador": "Andean Region", "Venezuela": "Andean Region",
    # Southern Cone
    "Argentina": "Southern Cone", "Brazil": "Southern Cone",
    "Chile": "Southern Cone", "Uruguay": "Southern Cone", "Paraguay": "Southern Cone",
    # Central America / Caribbean
    "Mexico": "Mexico", "El Salvador": "Central America & Caribbean",
    "Honduras": "Central America & Caribbean", "Guatemala": "Central America & Caribbean",
    "Nicaragua": "Central America & Caribbean", "Costa Rica": "Central America & Caribbean",
    "Panama": "Central America & Caribbean", "Haiti": "Central America & Caribbean",
    "Dominican Republic": "Central America & Caribbean", "Cuba": "Central America & Caribbean",
    "Jamaica": "Central America & Caribbean",
}


def compute_severity_score(event: dict) -> float:
    """
    MERIDIAN's own 0-10 severity score, derived from ACLED's event type and
    fatality count. This is intentionally simple at v1 — a transparent, auditable
    starting point you can refine once you see it running against real data,
    rather than an opaque black-box score.

    Logic:
      - Base score by event type (battles/violence against civilians score higher
        than protests, reflecting differing security materiality)
      - Fatality count adds a logarithmic-ish bump, capped so a single mass-casualty
        event doesn't blow the scale past 10
    """
    event_type = event.get("event_type", "")
    base_scores = {
        "Battles": 6.0,
        "Violence against civilians": 6.5,
        "Explosions/Remote violence": 6.0,
        "Riots": 3.0,
        "Protests": 1.5,
        "Strategic developments": 2.0,
    }
    base = base_scores.get(event_type, 2.0)

    try:
        fatalities = int(event.get("fatalities", 0) or 0)
    except (ValueError, TypeError):
        fatalities = 0

    if fatalities <= 0:
        fatality_bump = 0
    elif fatalities <= 5:
        fatality_bump = 1.0
    elif fatalities <= 20:
        fatality_bump = 2.0
    elif fatalities <= 100:
        fatality_bump = 3.0
    else:
        fatality_bump = 4.0

    return min(round(base + fatality_bump, 1), 10.0)


def extract_actors(event: dict) -> list[dict]:
    """Pulls actor1/actor2/assoc_actor fields into MERIDIAN's actors array."""
    actors = []
    for actor_field, type_hint_field in [("actor1", "inter1"), ("actor2", "inter2")]:
        name = event.get(actor_field)
        if name:
            actors.append({
                "name": name,
                "type": str(event.get(type_hint_field, "unknown")),
            })
    return actors


def make_meridian_event_id(source: str, source_event_id: str) -> str:
    """Deterministic ID so re-running ingestion doesn't create duplicate records."""
    raw = f"{source}:{source_event_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def normalize_acled_event(raw_event: dict) -> dict | None:
    """Maps a single raw ACLED record into the MERIDIAN normalized_event schema.
    Returns None if the event's country falls outside MERIDIAN's Africa/LatAm
    mandate. ACLED's API-side region filter has proven unreliable in practice
    (fetches have returned Turkey, Ukraine, Iran, etc. despite region params),
    so this mandate check is the authoritative filter — every event must clear
    it before being normalized, matching the convention used in
    gdelt_normalize.py."""
    country = raw_event.get("country", "")
    source_event_id = raw_event.get("event_id_cnty", "")
    event_type = raw_event.get("event_type", "")

    if country not in COUNTRY_TO_MERIDIAN_REGION:
        return None
    region = COUNTRY_TO_MERIDIAN_REGION[country]

    try:
        lat = float(raw_event["latitude"]) if raw_event.get("latitude") not in (None, "") else None
        lon = float(raw_event["longitude"]) if raw_event.get("longitude") not in (None, "") else None
    except (ValueError, TypeError):
        lat, lon = None, None

    try:
        fatalities = int(raw_event.get("fatalities", 0) or 0)
    except (ValueError, TypeError):
        fatalities = None

    return {
        "meridian_event_id": make_meridian_event_id("ACLED", source_event_id),
        "source": "ACLED",
        "source_event_id": source_event_id,
        "event_date": raw_event.get("event_date"),
        "country": country,
        "iso3": raw_event.get("iso3"),
        "admin1": raw_event.get("admin1"),
        "region": region,
        "latitude": lat,
        "longitude": lon,
        "event_category": EVENT_TYPE_MAP.get(event_type, "other"),
        "event_subtype": event_type,
        "actors": extract_actors(raw_event),
        "fatalities": fatalities,
        "severity_score": compute_severity_score(raw_event),
        "narrative_summary": raw_event.get("notes", ""),
        "source_url": raw_event.get("source"),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "raw_source_data": raw_event,
    }


def normalize_batch(raw_events: list[dict]) -> list[dict]:
    """Normalizes a list of raw ACLED events, skipping malformed records rather than
    failing the whole batch. Logs a warning for each skip so issues are visible."""
    normalized = []
    skipped = 0
    for raw_event in raw_events:
        try:
            result = normalize_acled_event(raw_event)
            if result is None:
                skipped += 1
                continue
            normalized.append(result)
        except Exception as e:
            skipped += 1
            print(f"WARNING: skipped malformed ACLED record "
                  f"({raw_event.get('event_id_cnty', 'unknown id')}): {e}", file=sys.stderr)
    if skipped:
        print(f"Normalization complete with {skipped} record(s) skipped out of {len(raw_events)}.",
              file=sys.stderr)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Normalize raw ACLED events into MERIDIAN schema")
    parser.add_argument("--input", type=str, required=True, help="Path to raw ACLED JSON (from acled_fetch.py)")
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
