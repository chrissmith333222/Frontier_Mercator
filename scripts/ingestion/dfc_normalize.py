"""
scripts/ingestion/dfc_normalize.py

Maps raw DFC Annual Project Data rows into MERIDIAN's common
normalized_event schema, event_category="investment" -- the U.S.
government counterpart to AidData's Chinese financing records, grouped
together under "Markets & Economy" / Investment Projects in the dashboard.

DFC's "Country" field uses plain English names that mostly, but not
always, match MERIDIAN's canonical country names (a handful of variant
spellings like "Cote D'Ivoire" or "Burma"), plus regional/aggregate rows
("Africa Regional", "Worldwide", "Redacted") that don't map to any single
country -- those fall back to "Global / Other Monitoring" like every other
source's unmapped records.

DFC's "Committed" amount is denominated in whatever currency the deal was
struck in (see the "Currency" column) -- the vast majority are USD, but a
small number of legacy/local-currency deals are not, and there's no FX
column to convert them. Only USD-denominated amounts are formatted as a
dollar figure; everything else is reported as a raw amount + currency code
rather than mislabeled as USD.

Usage:
    python scripts/ingestion/dfc_normalize.py --input raw_dfc.json --output normalized.json

Or as a module:
    from scripts.ingestion.dfc_normalize import normalize_dfc_record, normalize_batch
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

# DFC country-field variants that don't exactly match MERIDIAN's canonical
# pycountry-derived names.
_NAME_ALIASES = {
    "cote d'ivoire": "Ivory Coast",
    "democratic republic of congo": "Democratic Republic of Congo",
    "burma": "Myanmar",
    "trinidad & tobago": "Trinidad and Tobago",
    "st. kitts and nevis": "Saint Kitts and Nevis",
    "st. vincent and the grenadines": "Saint Vincent and the Grenadines",
    "south korea": "Korea, Republic of",
    "antigua and barbuda": "Antigua and Barbuda",
    "bosnia and herzegovina": "Bosnia and Herzegovina",
    "west bank and gaza": "Gaza Strip",
    "north macedonia": "North Macedonia",
    "laos": "Lao People's Democratic Republic",
}

# name (lowercased) -> (iso3, canonical_name, region, in_core_mandate)
_NAME_LOOKUP = {
    name.lower(): (iso3, name, region, in_core_mandate)
    for iso3, (name, region, in_core_mandate) in ALL_COUNTRIES.items()
}


def _lookup_country(raw_name: str) -> tuple[str | None, str, str, bool]:
    """Resolves a DFC country string to (iso3_or_None, name, region,
    in_core_mandate). Regional/aggregate rows (e.g. 'Africa Regional',
    'Worldwide', 'Redacted') fall back to Global/Other Monitoring."""
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


def _format_amount(value, currency: str | None) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "amount undisclosed"
    is_usd = currency in (None, "", "USD")
    if not is_usd:
        return f"{amount:,.0f} {currency}"
    if amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.2f}B"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    return f"${amount:,.0f}"


def normalize_dfc_record(raw_record: dict) -> dict | None:
    """Maps a single raw DFC project row into the MERIDIAN normalized_event
    schema. Returns None if there's no usable project number, country, or
    fiscal year -- all required for anything downstream to make sense of
    the record."""
    project_number = raw_record.get("Project Number")
    country_raw = raw_record.get("Country")
    fiscal_year = raw_record.get("Fiscal Year")

    if not project_number or not country_raw:
        return None
    try:
        fiscal_year = int(fiscal_year)
    except (TypeError, ValueError):
        return None

    iso3, country, region, in_core_mandate = _lookup_country(str(country_raw))

    currency = raw_record.get("Currency")
    amount_str = _format_amount(raw_record.get("Committed"), currency)
    project_type = raw_record.get("Project Type") or "Unspecified Type"
    sector = raw_record.get("NAICS Sector") or "Unspecified Sector"
    support_type = raw_record.get("Support Type") or "Unspecified Support"
    project_name = raw_record.get("Project Name") or f"DFC {project_type} project in {country}"

    narrative_summary = f"{project_name} — {support_type}, {sector}, {amount_str} (FY{fiscal_year})"

    actors = [{"name": "U.S. International Development Finance Corporation", "type": "us_financier"}]
    originating_agency = raw_record.get("Originating Agency")
    if originating_agency and originating_agency != "DFC":
        actors.append({"name": str(originating_agency), "type": "originating_agency"})

    return {
        "meridian_event_id": make_meridian_event_id("DFC", str(project_number)),
        "source": "DFC",
        "source_event_id": str(project_number),
        "event_date": f"{fiscal_year}-01-01",
        "country": country,
        "iso3": iso3,
        "admin1": None,
        "region": region,
        "in_core_mandate": in_core_mandate,
        "latitude": None,
        "longitude": None,
        "event_category": "investment",
        "event_subtype": sector,
        "actors": actors,
        "fatalities": None,
        "severity_score": None,
        "narrative_summary": narrative_summary,
        "source_url": raw_record.get("Project Profile URL"),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "raw_source_data": None,
    }


def normalize_batch(raw_records: list[dict]) -> list[dict]:
    """Normalizes a list of raw DFC records, skipping malformed/incomplete
    rows rather than failing the whole batch."""
    normalized = []
    skipped = 0
    for raw_record in raw_records:
        try:
            result = normalize_dfc_record(raw_record)
            if result is None:
                skipped += 1
                continue
            normalized.append(result)
        except Exception as e:
            skipped += 1
            print(f"WARNING: skipped malformed DFC record "
                  f"({raw_record.get('Project Number', 'unknown id')}): {e}", file=sys.stderr)
    if skipped:
        print(f"Normalization complete with {skipped} record(s) skipped out of {len(raw_records)}.",
              file=sys.stderr)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Normalize raw DFC records into MERIDIAN schema")
    parser.add_argument("--input", type=str, required=True, help="Path to raw DFC JSON (from dfc_fetch.py)")
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
