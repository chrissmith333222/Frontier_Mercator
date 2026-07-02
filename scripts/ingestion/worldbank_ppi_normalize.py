"""
scripts/ingestion/worldbank_ppi_normalize.py

Maps raw World Bank PPI Database rows into MERIDIAN's common
normalized_event schema, event_category="investment" -- private-sector
infrastructure investment commitments, distinct from AidData/DFC's
government development finance. Grouped with those under "Markets &
Economy" / Investment Projects in the dashboard.

The PPI dataset uses World-Bank-style country names ("Congo, Dem. Rep.",
"Egypt, Arab Rep.", "Lao PDR", "Russian Federation", "Vietnam", etc.) that
don't match MERIDIAN's canonical pycountry-derived names ("Democratic
Republic of Congo", "Egypt", "Lao People's Democratic Republic", "Russia",
"Viet Nam") -- resolved via an alias map, same pattern as
dfc_normalize.py. A couple of entries carry correctly-encoded accented
characters (e.g. "Côte d'Ivoire", "São Tomé and Principe") that display as
replacement-character mojibake in some terminals/consoles -- that's a
rendering artifact of the viewer, not a defect in the underlying UTF-8
data, so the alias keys below use the real accented characters.

The same underlying infrastructure project can appear as multiple rows
(one per funding/implementation update over time), so source_event_id
combines the PPI project ID with its record year rather than using the ID
alone.

Usage:
    python scripts/ingestion/worldbank_ppi_normalize.py --input raw_ppi.json --output normalized.json

Or as a module:
    from scripts.ingestion.worldbank_ppi_normalize import normalize_ppi_record, normalize_batch
"""

import sys
import argparse
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.lib.world_countries import ALL_COUNTRIES
from scripts.lib.regions import GLOBAL_OTHER_REGION

# World-Bank-style country name variants that don't exactly match
# MERIDIAN's canonical pycountry-derived names. The two garbled entries
# reflect a genuine encoding defect in the published PPI .dta file.
_NAME_ALIASES = {
    "congo, dem. rep.": "Democratic Republic of Congo",
    "congo, rep.": "Republic of Congo",
    "côte d'ivoire": "Ivory Coast",
    "egypt, arab rep.": "Egypt",
    "iran, islamic rep.": "Iran",
    "korea, dem. people's rep": "Korea, Democratic People's Republic of",
    "kyrgyz republic": "Kyrgyzstan",
    "lao pdr": "Lao People's Democratic Republic",
    "cape verde": "Cabo Verde",
    "gambia, the": "Gambia",
    "guyana, cr": "Guyana",
    "st. kitts and nevis": "Saint Kitts and Nevis",
    "st. lucia": "Saint Lucia",
    "st. vincent and grenadines": "Saint Vincent and the Grenadines",
    "são tomé and principe": "Sao Tome and Principe",
    "turkiye": "Turkey",
    "venezuela, rb": "Venezuela",
    "yemen, rep.": "Yemen",
    "west bank and gaza": "Gaza Strip",
    "syrian arab republic": "Syria",
    "russian federation": "Russia",
    "vietnam": "Viet Nam",
}

# name (lowercased) -> (iso3, canonical_name, region, in_core_mandate)
_NAME_LOOKUP = {
    name.lower(): (iso3, name, region, in_core_mandate)
    for iso3, (name, region, in_core_mandate) in ALL_COUNTRIES.items()
}


def _lookup_country(raw_name: str) -> tuple[str | None, str, str, bool]:
    """Resolves a PPI country string to (iso3_or_None, name, region,
    in_core_mandate). Unmatched entries fall back to Global/Other
    Monitoring like every other MERIDIAN source's unmapped records."""
    key = raw_name.strip().lower()
    key = _NAME_ALIASES.get(key, key)
    hit = _NAME_LOOKUP.get(key.lower())
    if hit:
        iso3, name, region, in_core_mandate = hit
        return iso3, name, region, in_core_mandate
    return None, raw_name, GLOBAL_OTHER_REGION, False


def make_meridian_event_id(source: str, source_event_id: str) -> str:
    """Deterministic ID so re-running ingestion doesn't create duplicate records."""
    raw = f"{source}:{source_event_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _format_amount_millions(value) -> str:
    """PPI's `investment` field is denominated in millions of USD."""
    try:
        millions = float(value)
    except (TypeError, ValueError):
        return "amount undisclosed"
    if millions != millions:  # NaN
        return "amount undisclosed"
    if millions >= 1000:
        return f"${millions / 1000:.2f}B"
    return f"${millions:.1f}M"


def normalize_ppi_record(raw_record: dict) -> dict | None:
    """Maps a single raw PPI project row into the MERIDIAN normalized_event
    schema. Returns None if there's no usable project ID, country, or
    record year -- all required for anything downstream to make sense of
    the record."""
    project_id = raw_record.get("ID")
    country_raw = raw_record.get("country")
    record_year = raw_record.get("FCY") or raw_record.get("IY")

    if project_id is None or not country_raw:
        return None
    try:
        record_year = int(record_year)
    except (TypeError, ValueError):
        return None

    # (project_id, record_year) alone isn't unique -- a project can have
    # multiple distinct funding-tranche rows in the same year -- so the
    # row's stable position in the source file disambiguates them.
    row_index = raw_record.get("_row_index")
    source_event_id = f"{project_id}:{record_year}:{row_index}" if row_index is not None else f"{project_id}:{record_year}"

    iso3, country, region, in_core_mandate = _lookup_country(str(country_raw))

    amount_str = _format_amount_millions(raw_record.get("investment"))
    project_type = raw_record.get("type") or "Unspecified Type"
    sector = raw_record.get("sector") or "Unspecified Sector"
    subsector = raw_record.get("ssector") or ""
    status = raw_record.get("status_n") or "Unknown Status"
    project_name = raw_record.get("name") or f"PPI {project_type} project in {country}"

    sector_label = f"{sector} ({subsector})" if subsector and subsector != sector else sector
    narrative_summary = (
        f"{project_name} — {project_type}, {sector_label}, {amount_str}, {status} ({record_year})"
    )

    return {
        "meridian_event_id": make_meridian_event_id("WorldBankPPI", source_event_id),
        "source": "WorldBankPPI",
        "source_event_id": source_event_id,
        "event_date": f"{record_year}-01-01",
        "country": country,
        "iso3": iso3,
        "admin1": None,
        "region": region,
        "in_core_mandate": in_core_mandate,
        "latitude": None,
        "longitude": None,
        "event_category": "investment",
        "event_subtype": sector,
        "actors": [{"name": "Private sector (World Bank PPI Database)", "type": "private_financier"}],
        "fatalities": None,
        "severity_score": None,
        "narrative_summary": narrative_summary,
        "source_url": "https://ppi.worldbank.org/en/customquery",
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "raw_source_data": None,
    }


def normalize_batch(raw_records: list[dict]) -> list[dict]:
    """Normalizes a list of raw PPI records, skipping malformed/incomplete
    rows rather than failing the whole batch."""
    normalized = []
    skipped = 0
    for raw_record in raw_records:
        try:
            result = normalize_ppi_record(raw_record)
            if result is None:
                skipped += 1
                continue
            normalized.append(result)
        except Exception as e:
            skipped += 1
            print(f"WARNING: skipped malformed PPI record "
                  f"({raw_record.get('ID', 'unknown id')}): {e}", file=sys.stderr)
    if skipped:
        print(f"Normalization complete with {skipped} record(s) skipped out of {len(raw_records)}.",
              file=sys.stderr)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Normalize raw World Bank PPI records into MERIDIAN schema")
    parser.add_argument("--input", type=str, required=True, help="Path to raw PPI JSON (from worldbank_ppi_fetch.py)")
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
