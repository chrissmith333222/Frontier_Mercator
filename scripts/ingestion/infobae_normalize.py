"""
scripts/ingestion/infobae_normalize.py

Maps raw Infobae (Spanish-language) articles into MERIDIAN's common
normalized_event schema, event_category="other" (News & Social Signal
bucket, same as Bellingcat/GDELT's "other" items). Infobae doesn't tag a
clean country field, so country/region is inferred by scanning the
(Spanish) title against known country names -- same heuristic pattern as
bellingcat_normalize.py, extended with accent-stripping and a small
Spanish-name alias map, since Spanish country names are sometimes
identical to English once accents are stripped (México -> mexico matches
directly) and sometimes a completely different word (Alemania -> Germany,
which needs an explicit alias).

Usage:
    python scripts/ingestion/infobae_normalize.py --input raw_infobae.json --output normalized.json

Or as a module:
    from scripts.ingestion.infobae_normalize import normalize_infobae_article, normalize_batch
"""

import sys
import re
import argparse
import json
import hashlib
import unicodedata
from email.utils import parsedate_to_datetime
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.lib.world_countries import ALL_COUNTRIES
from scripts.lib.regions import GLOBAL_OTHER_REGION

# Spanish country names that differ from English by more than just accents
# (accented variants like "México"/"Perú"/"Panamá" resolve directly once
# accents are stripped, since they already match the English lookup key).
SPANISH_NAME_ALIASES = {
    "alemania": "Germany", "espana": "Spain", "francia": "France",
    "rusia": "Russia", "reino unido": "United Kingdom", "gran bretana": "United Kingdom",
    "estados unidos": "United States", "eeuu": "United States", "ee.uu.": "United States",
    "ucrania": "Ukraine", "sudafrica": "South Africa", "costa de marfil": "Ivory Coast",
    "paises bajos": "Netherlands", "holanda": "Netherlands",
    "corea del sur": "Korea, Republic of", "corea del norte": "Korea, Democratic People's Republic of",
    "arabia saudita": "Saudi Arabia", "arabia saudi": "Saudi Arabia", "suiza": "Switzerland",
    "grecia": "Greece", "turquia": "Turkey", "egipto": "Egypt", "japon": "Japan",
    "marruecos": "Morocco", "argelia": "Algeria", "tunez": "Tunisia", "libia": "Libya",
    "italia": "Italy", "polonia": "Poland", "hungria": "Hungary", "suecia": "Sweden",
    "noruega": "Norway", "dinamarca": "Denmark", "finlandia": "Finland",
    "irlanda": "Ireland", "austria": "Austria", "belgica": "Belgium",
    "nueva zelanda": "New Zealand", "australia": "Australia",
    "filipinas": "Philippines", "vietnam": "Viet Nam", "camboya": "Cambodia",
    "tailandia": "Thailand", "indonesia": "Indonesia", "malasia": "Malaysia",
}

# name (lowercased, accent-stripped) -> (iso3, canonical_name, region, in_core_mandate)
_NAME_LOOKUP = {
    name.lower(): (iso3, name, region, in_core_mandate)
    for iso3, (name, region, in_core_mandate) in ALL_COUNTRIES.items()
    if len(name) > 3
}


def _strip_accents(text: str) -> str:
    """Removes diacritics (México -> Mexico, São Paulo -> Sao Paulo) so
    Spanish/Portuguese country-name variants match the English lookup
    table without needing an alias entry for every accented letter."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _detect_country(text: str) -> tuple[str | None, str, str, bool]:
    """Scans (accent-stripped) text for a mentioned country name. Returns
    (iso3_or_None, country_name_or_'Global', region, in_core_mandate)."""
    text_lower = _strip_accents(text.lower())
    for alias, canonical_name in SPANISH_NAME_ALIASES.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", text_lower):
            hit = _NAME_LOOKUP.get(canonical_name.lower())
            if hit:
                iso3, name, region, in_core_mandate = hit
                return iso3, name, region, in_core_mandate
    for name_lower, (iso3, name, region, in_core_mandate) in _NAME_LOOKUP.items():
        if re.search(r"\b" + re.escape(_strip_accents(name_lower)) + r"\b", text_lower):
            return iso3, name, region, in_core_mandate
    return None, "Global", GLOBAL_OTHER_REGION, False


def make_meridian_event_id(source: str, source_event_id: str) -> str:
    """Deterministic ID so re-running ingestion doesn't create duplicate records."""
    raw = f"{source}:{source_event_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def normalize_infobae_article(raw_article: dict) -> dict | None:
    """Maps a single raw Infobae RSS item into the MERIDIAN
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

    iso3, country, region, in_core_mandate = _detect_country(title)

    return {
        "meridian_event_id": make_meridian_event_id("Infobae", guid),
        "source": "Infobae",
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
        "event_subtype": "Spanish-language news (Infobae)",
        "actors": [],
        "fatalities": None,
        "severity_score": None,
        "narrative_summary": title,
        "source_url": raw_article.get("link"),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "raw_source_data": None,
    }


def normalize_batch(raw_articles: list[dict]) -> list[dict]:
    """Normalizes a list of raw Infobae articles, skipping malformed
    entries rather than failing the whole batch."""
    normalized = []
    skipped = 0
    for raw_article in raw_articles:
        try:
            result = normalize_infobae_article(raw_article)
            if result is None:
                skipped += 1
                continue
            normalized.append(result)
        except Exception as e:
            skipped += 1
            print(f"WARNING: skipped malformed Infobae article: {e}", file=sys.stderr)
    if skipped:
        print(f"Normalization complete with {skipped} record(s) skipped out of {len(raw_articles)}.",
              file=sys.stderr)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Normalize raw Infobae articles into MERIDIAN schema")
    parser.add_argument("--input", type=str, required=True, help="Path to raw Infobae JSON (from infobae_fetch.py)")
    parser.add_argument("--output", type=str, default=None, help="Output path. Omit to print to stdout.")
    args = parser.parse_args()

    raw_articles = json.loads(Path(args.input).read_text(encoding="utf-8"))
    normalized = normalize_batch(raw_articles)

    output_json = json.dumps(normalized, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Wrote {len(normalized)} normalized events to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
