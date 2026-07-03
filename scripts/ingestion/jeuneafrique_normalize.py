"""
scripts/ingestion/jeuneafrique_normalize.py

Maps raw Jeune Afrique (French-language) articles into MERIDIAN's common
normalized_event schema, event_category="other" (News & Social Signal
bucket, same as Infobae/Bellingcat/GDELT's "other" items). Jeune Afrique
doesn't tag a clean country field, so country/region is inferred by
scanning the (French) title against known country names -- same
accent-stripping + alias-map heuristic as infobae_normalize.py, with a
French-specific alias list this time (French country names diverge from
English more often than Spanish does -- "Cote d'Ivoire", "RDC" for DR
Congo, "Allemagne" for Germany, etc.).

Usage:
    python scripts/ingestion/jeuneafrique_normalize.py --input raw_jeuneafrique.json --output normalized.json

Or as a module:
    from scripts.ingestion.jeuneafrique_normalize import normalize_jeuneafrique_article, normalize_batch
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

# French country/region names that differ from English by more than just
# accents (accented variants like "Kénya" would resolve directly once
# accents are stripped -- these need an explicit alias because the word
# itself is different, or because French abbreviations like "RDC" are
# common in headlines).
FRENCH_NAME_ALIASES = {
    "rdc": "Democratic Republic of Congo", "congo-kinshasa": "Democratic Republic of Congo",
    "republique democratique du congo": "Democratic Republic of Congo",
    "congo-brazzaville": "Republic of Congo", "republique du congo": "Republic of Congo",
    "cote d ivoire": "Ivory Coast", "cote d'ivoire": "Ivory Coast",
    "maroc": "Morocco", "afrique du sud": "South Africa", "algerie": "Algeria",
    "tunisie": "Tunisia", "egypte": "Egypt", "libye": "Libya",
    "cameroun": "Cameroon", "tchad": "Chad", "guinee": "Guinea",
    "centrafrique": "Central African Republic", "republique centrafricaine": "Central African Republic",
    "rca": "Central African Republic", "soudan": "Sudan", "soudan du sud": "South Sudan",
    "ethiopie": "Ethiopia", "somalie": "Somalia",
    "etats-unis": "United States", "etats unis": "United States", "usa": "United States",
    "chine": "China", "russie": "Russia", "allemagne": "Germany", "espagne": "Spain",
    "royaume-uni": "United Kingdom", "grande-bretagne": "United Kingdom",
    "pays-bas": "Netherlands", "inde": "India", "japon": "Japan",
    "coree du sud": "Korea, Republic of", "coree du nord": "Korea, Democratic People's Republic of",
    "arabie saoudite": "Saudi Arabia", "emirats arabes unis": "United Arab Emirates",
    "grece": "Greece", "turquie": "Turkey", "suisse": "Switzerland", "suede": "Sweden",
    "norvege": "Norway", "autriche": "Austria", "belgique": "Belgium",
    "nouvelle-zelande": "New Zealand", "philippines": "Philippines", "thailande": "Thailand",
}

# name (lowercased, accent-stripped) -> (iso3, canonical_name, region, in_core_mandate)
_NAME_LOOKUP = {
    name.lower(): (iso3, name, region, in_core_mandate)
    for iso3, (name, region, in_core_mandate) in ALL_COUNTRIES.items()
    if len(name) > 3
}


def _strip_accents(text: str) -> str:
    """Removes diacritics (Bénin -> Benin, Côte -> Cote) so French
    country-name variants match the English lookup table without needing
    an alias entry for every accented letter."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _detect_country(text: str) -> tuple[str | None, str, str, bool]:
    """Scans (accent-stripped) text for a mentioned country name. Returns
    (iso3_or_None, country_name_or_'Global', region, in_core_mandate)."""
    text_lower = _strip_accents(text.lower())
    for alias, canonical_name in FRENCH_NAME_ALIASES.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", text_lower):
            hit = _NAME_LOOKUP.get(canonical_name.lower())
            if hit:
                iso3, name, region, in_core_mandate = hit
                return iso3, name, region, in_core_mandate
    for name_lower, (iso3, name, region, in_core_mandate) in _NAME_LOOKUP.items():
        if re.search(r"\b" + re.escape(_strip_accents(name_lower)) + r"\b", text_lower):
            return iso3, name, region, in_core_mandate
    return None, "Global", GLOBAL_OTHER_REGION, False


def _parse_pub_date(pub_date: str) -> str:
    """Jeune Afrique's feed emits pubDate as ISO 8601
    ("2026-07-02T19:39:58+00:00") rather than the RFC 822 format
    ("Thu, 02 Jul 2026 19:39:58 +0000") most RSS feeds (including
    Infobae's) use -- try RFC 822 first since that's the RSS spec's
    stated format, then fall back to ISO 8601 rather than assuming one
    or the other and silently dropping every article from a feed that
    happens to use the other format."""
    try:
        return parsedate_to_datetime(pub_date).date().isoformat()
    except (TypeError, ValueError):
        pass
    return datetime.fromisoformat(pub_date).date().isoformat()


def make_meridian_event_id(source: str, source_event_id: str) -> str:
    """Deterministic ID so re-running ingestion doesn't create duplicate records."""
    raw = f"{source}:{source_event_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def normalize_jeuneafrique_article(raw_article: dict) -> dict | None:
    """Maps a single raw Jeune Afrique RSS item into the MERIDIAN
    normalized_event schema. Returns None if there's no usable link/guid or
    publish date."""
    guid = raw_article.get("guid") or raw_article.get("link")
    title = raw_article.get("title", "")
    if not guid or not title:
        return None

    pub_date = raw_article.get("pubDate", "")
    try:
        event_date = _parse_pub_date(pub_date)
    except (TypeError, ValueError):
        return None

    iso3, country, region, in_core_mandate = _detect_country(title)

    return {
        "meridian_event_id": make_meridian_event_id("JeuneAfrique", guid),
        "source": "JeuneAfrique",
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
        "event_subtype": "French-language news (Jeune Afrique)",
        "actors": [],
        "fatalities": None,
        "severity_score": None,
        "narrative_summary": title,
        "source_url": raw_article.get("link"),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "raw_source_data": None,
    }


def normalize_batch(raw_articles: list[dict]) -> list[dict]:
    """Normalizes a list of raw Jeune Afrique articles, skipping malformed
    entries rather than failing the whole batch."""
    normalized = []
    skipped = 0
    for raw_article in raw_articles:
        try:
            result = normalize_jeuneafrique_article(raw_article)
            if result is None:
                skipped += 1
                continue
            normalized.append(result)
        except Exception as e:
            skipped += 1
            print(f"WARNING: skipped malformed Jeune Afrique article: {e}", file=sys.stderr)
    if skipped:
        print(f"Normalization complete with {skipped} record(s) skipped out of {len(raw_articles)}.",
              file=sys.stderr)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Normalize raw Jeune Afrique articles into MERIDIAN schema")
    parser.add_argument("--input", type=str, required=True, help="Path to raw Jeune Afrique JSON (from jeuneafrique_fetch.py)")
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
