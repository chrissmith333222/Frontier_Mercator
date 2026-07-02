"""
scripts/ingestion/aiddata_normalize.py

Maps raw AidData GCDF 3.0 project rows into MERIDIAN's common
normalized_event schema, event_category="investment" -- discrete Chinese
government-financed projects (loans/grants), distinct from the periodic
economic_indicator time series from World Bank/IMF. Grouped with those under
"Markets & Economy" in the dashboard (see scripts/branding.py ECON_CATEGORIES).

Usage:
    python scripts/ingestion/aiddata_normalize.py --input raw_aiddata.json --output normalized.json

Or as a module:
    from scripts.ingestion.aiddata_normalize import normalize_aiddata_record, normalize_batch
"""

import sys
import argparse
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.lib.regions import lookup_by_iso3, GLOBAL_OTHER_REGION


def make_meridian_event_id(source: str, source_event_id: str) -> str:
    """Deterministic ID so re-running ingestion doesn't create duplicate records."""
    raw = f"{source}:{source_event_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _format_amount(value) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "amount undisclosed"
    if amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.2f}B"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    return f"${amount:,.0f}"


def normalize_aiddata_record(raw_record: dict) -> dict | None:
    """Maps a single raw AidData GCDF row into the MERIDIAN normalized_event
    schema. Returns None if there's no usable country or commitment year --
    both required for anything downstream to make sense of the record."""
    record_id = raw_record.get("AidData Record ID")
    iso3 = raw_record.get("Recipient ISO-3")
    country_raw = raw_record.get("Recipient")
    commitment_year = raw_record.get("Commitment Year")

    if not record_id or not (iso3 or country_raw) or not commitment_year:
        return None

    geo = lookup_by_iso3(iso3) if iso3 else None
    if geo is not None:
        country, region, in_core_mandate = geo
    else:
        country, region, in_core_mandate = (country_raw or "Unknown"), GLOBAL_OTHER_REGION, False

    commitment_date = raw_record.get("Commitment Date (MM/DD/YYYY)")
    event_date = None
    if commitment_date:
        for candidate in (str(commitment_date)[:10],):
            try:
                event_date = datetime.strptime(candidate, "%Y-%m-%d").date().isoformat()
                break
            except ValueError:
                pass
    if event_date is None:
        try:
            event_date = f"{int(commitment_year)}-01-01"
        except (TypeError, ValueError):
            return None

    flow_type = raw_record.get("Flow Type") or "Unspecified Flow"
    sector = raw_record.get("Sector Name") or "Unspecified Sector"
    status = raw_record.get("Status") or "Unknown Status"
    amount_str = _format_amount(raw_record.get("Amount (Nominal USD)"))
    title = raw_record.get("Title") or f"{flow_type} to {country}"

    narrative_summary = f"{title} — {flow_type}, {sector}, {amount_str}, {status} ({commitment_year})"

    funding_agencies = raw_record.get("Funding Agencies")
    receiving_agencies = raw_record.get("Direct Receiving Agencies")
    actors = []
    if funding_agencies:
        actors.append({"name": str(funding_agencies), "type": "chinese_financier"})
    if receiving_agencies:
        actors.append({"name": str(receiving_agencies), "type": "recipient_agency"})

    source_urls = raw_record.get("Source URLs")
    source_url = str(source_urls).split("|")[0].strip() if source_urls else None

    return {
        "meridian_event_id": make_meridian_event_id("AidData", str(record_id)),
        "source": "AidData",
        "source_event_id": str(record_id),
        "event_date": event_date,
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
        "source_url": source_url,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "raw_source_data": None,  # 128 columns/row -- too large to keep per-record at scale
    }


def normalize_batch(raw_records: list[dict]) -> list[dict]:
    """Normalizes a list of raw AidData records, skipping malformed/incomplete
    rows rather than failing the whole batch."""
    normalized = []
    skipped = 0
    for raw_record in raw_records:
        try:
            result = normalize_aiddata_record(raw_record)
            if result is None:
                skipped += 1
                continue
            normalized.append(result)
        except Exception as e:
            skipped += 1
            print(f"WARNING: skipped malformed AidData record "
                  f"({raw_record.get('AidData Record ID', 'unknown id')}): {e}", file=sys.stderr)
    if skipped:
        print(f"Normalization complete with {skipped} record(s) skipped out of {len(raw_records)}.",
              file=sys.stderr)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Normalize raw AidData records into MERIDIAN schema")
    parser.add_argument("--input", type=str, required=True, help="Path to raw AidData JSON (from aiddata_fetch.py)")
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
