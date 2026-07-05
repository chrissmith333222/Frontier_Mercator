"""
scripts/ingestion/general_news_normalize.py

Maps raw general-newspaper articles (NYT, WSJ -- see general_news_fetch.py)
into MERIDIAN's common normalized_event schema, event_category="other"
(News & Social Signal bucket, same as Bellingcat/GDELT/Infobae/Jeune
Afrique). Country detection reuses bellingcat_normalize.py's plain
English keyword-match heuristic (no accent-stripping needed, unlike the
Spanish/French sources). Both feeds are already in English, so
narrative_summary_en is never populated here -- that field only exists
for genuinely non-English sources.

Usage:
    python scripts/ingestion/general_news_normalize.py --input raw_general_news.json --output normalized.json

Or as a module:
    from scripts.ingestion.general_news_normalize import normalize_article, normalize_batch
"""

import sys
import re
import argparse
import json
import hashlib
import html
from email.utils import parsedate_to_datetime
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.lib.world_countries import ALL_COUNTRIES
from scripts.lib.regions import GLOBAL_OTHER_REGION

_NAME_LOOKUP = {
    name.lower(): (iso3, name, region, in_core_mandate)
    for iso3, (name, region, in_core_mandate) in ALL_COUNTRIES.items()
    if len(name) > 3
}
_TAG_STRIP_PATTERN = re.compile(r"<[^>]+>")


def _detect_country(text: str) -> tuple[str | None, str, str, bool]:
    text_lower = text.lower()
    for name_lower, (iso3, name, region, in_core_mandate) in _NAME_LOOKUP.items():
        if re.search(r"\b" + re.escape(name_lower) + r"\b", text_lower):
            return iso3, name, region, in_core_mandate
    return None, "Global", GLOBAL_OTHER_REGION, False


def _clean_text(raw: str) -> str:
    if not raw:
        return ""
    return html.unescape(_TAG_STRIP_PATTERN.sub("", raw)).strip()


def make_meridian_event_id(source: str, source_event_id: str) -> str:
    raw = f"{source}:{source_event_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def normalize_article(raw_article: dict) -> dict | None:
    """Maps a single raw general-news RSS item into the MERIDIAN
    normalized_event schema. Returns None if there's no usable link/guid
    or publish date."""
    source = raw_article.get("source", "")
    guid = raw_article.get("guid") or raw_article.get("link")
    title = raw_article.get("title", "")
    if not guid or not title:
        return None

    pub_date = raw_article.get("pubDate", "")
    try:
        parsed_pub_date = parsedate_to_datetime(pub_date)
        event_date = parsed_pub_date.date().isoformat()
        event_datetime = parsed_pub_date.isoformat()
    except (TypeError, ValueError):
        return None

    teaser = _clean_text(raw_article.get("description", ""))
    search_text = title + " " + teaser + " " + " ".join(raw_article.get("categories") or [])
    iso3, country, region, in_core_mandate = _detect_country(search_text)

    return {
        "meridian_event_id": make_meridian_event_id(source, guid),
        "source": source,
        "source_event_id": guid,
        "event_date": event_date,
        "event_datetime": event_datetime,
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
        "narrative_summary": f"{title} — {teaser}" if teaser else title,
        "narrative_summary_en": None,  # already English -- field only used for non-English sources
        "source_url": raw_article.get("link"),
        "image_url": raw_article.get("image_url"),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "raw_source_data": None,
    }


def normalize_batch(raw_articles: list[dict]) -> list[dict]:
    """Normalizes a list of raw general-news articles, skipping malformed
    entries rather than failing the whole batch."""
    normalized = []
    skipped = 0
    for raw_article in raw_articles:
        try:
            result = normalize_article(raw_article)
            if result is None:
                skipped += 1
                continue
            normalized.append(result)
        except Exception as e:
            skipped += 1
            print(f"WARNING: skipped malformed general-news article: {e}", file=sys.stderr)
    if skipped:
        print(f"Normalization complete with {skipped} record(s) skipped out of {len(raw_articles)}.",
              file=sys.stderr)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Normalize raw general-news articles into MERIDIAN schema")
    parser.add_argument("--input", type=str, required=True, help="Path to raw JSON (from general_news_fetch.py)")
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
