"""
scripts/ingestion/bellingcat_normalize.py

Maps raw Bellingcat RSS articles into MERIDIAN's common normalized_event
schema, event_category="other" (lands in the News & Social Signal bucket
alongside GDELT's broader coding). Bellingcat doesn't tag articles with a
clean country field, so country/region is inferred by scanning the title +
categories for a known country name -- a simple heuristic, not NLP entity
extraction. Articles that don't mention any tracked country still get kept
(region="Global / Other Monitoring") since Bellingcat's thematic
investigations (open-source method guides, cross-border topics) are still
useful signal even without a single-country tag.

Usage:
    python scripts/ingestion/bellingcat_normalize.py --input raw_bellingcat.json --output normalized.json

Or as a module:
    from scripts.ingestion.bellingcat_normalize import normalize_bellingcat_article, normalize_batch
"""

import sys
import re
import argparse
import json
import hashlib
from email.utils import parsedate_to_datetime
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.lib.world_countries import ALL_COUNTRIES
from scripts.lib.regions import GLOBAL_OTHER_REGION

# name (lowercased) -> (iso3, canonical_name, region, in_core_mandate)
_NAME_LOOKUP = {
    name.lower(): (iso3, name, region, in_core_mandate)
    for iso3, (name, region, in_core_mandate) in ALL_COUNTRIES.items()
    if len(name) > 3  # skip very short names prone to false-positive substring matches
}


def _detect_country(text: str) -> tuple[str | None, str, str, bool]:
    """Scans text for a mentioned country name. Returns
    (iso3_or_None, country_name_or_'Global', region, in_core_mandate)."""
    text_lower = text.lower()
    for name_lower, (iso3, name, region, in_core_mandate) in _NAME_LOOKUP.items():
        if re.search(r"\b" + re.escape(name_lower) + r"\b", text_lower):
            return iso3, name, region, in_core_mandate
    return None, "Global", GLOBAL_OTHER_REGION, False


def make_meridian_event_id(source: str, source_event_id: str) -> str:
    """Deterministic ID so re-running ingestion doesn't create duplicate records."""
    raw = f"{source}:{source_event_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def normalize_bellingcat_article(raw_article: dict) -> dict | None:
    """Maps a single raw Bellingcat RSS item into the MERIDIAN
    normalized_event schema. Returns None if there's no usable link/guid or
    publish date."""
    guid = raw_article.get("guid") or raw_article.get("link")
    title = raw_article.get("title", "")
    if not guid or not title:
        return None

    pub_date = raw_article.get("pubDate", "")
    try:
        event_date = parsedate_to_datetime(pub_date).date().isoformat()
    except (TypeError, ValueError):
        return None

    search_text = title + " " + " ".join(raw_article.get("categories", []) or [])
    iso3, country, region, in_core_mandate = _detect_country(search_text)

    return {
        "meridian_event_id": make_meridian_event_id("Bellingcat", guid),
        "source": "Bellingcat",
        "source_event_id": guid,
        "event_date": event_date,
        "country": country,
        "iso3": iso3,
        "admin1": None,
        "region": region,
        "in_core_mandate": in_core_mandate,
        "latitude": None,
        "longitude": None,
        "event_category": "other",
        "event_subtype": (raw_article.get("categories") or [None])[0],
        "actors": [],
        "fatalities": None,
        "severity_score": None,
        "narrative_summary": title,
        "source_url": raw_article.get("link"),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "raw_source_data": None,
    }


def normalize_batch(raw_articles: list[dict]) -> list[dict]:
    """Normalizes a list of raw Bellingcat articles, skipping malformed
    entries rather than failing the whole batch."""
    normalized = []
    skipped = 0
    for raw_article in raw_articles:
        try:
            result = normalize_bellingcat_article(raw_article)
            if result is None:
                skipped += 1
                continue
            normalized.append(result)
        except Exception as e:
            skipped += 1
            print(f"WARNING: skipped malformed Bellingcat article: {e}", file=sys.stderr)
    if skipped:
        print(f"Normalization complete with {skipped} record(s) skipped out of {len(raw_articles)}.",
              file=sys.stderr)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Normalize raw Bellingcat articles into MERIDIAN schema")
    parser.add_argument("--input", type=str, required=True, help="Path to raw Bellingcat JSON (from bellingcat_fetch.py)")
    parser.add_argument("--output", type=str, default=None, help="Output path. Omit to print to stdout.")
    args = parser.parse_args()

    raw_articles = json.loads(Path(args.input).read_text(encoding="utf-8"))
    normalized = normalize_batch(raw_articles)

    output_json = json.dumps(normalized, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Wrote {len(normalized)} normalized events to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
