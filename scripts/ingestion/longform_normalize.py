"""
scripts/ingestion/longform_normalize.py

Maps raw long-form articles (scripts/ingestion/longform_fetch.py) into
the schema used by the Research & Analysis tab (see
schemas/longform_article.schema.json). Deliberately separate from
normalized_event.schema.json / scripts/curation/build_merged_dataset.py
-- these are reading material, not discrete dated events, so they don't
belong on the Unified Intelligence Map or in the event-scored News &
Social Signal tab.

Usage:
    python scripts/ingestion/longform_normalize.py --input raw_longform.json --output normalized.json

Or as a module:
    from scripts.ingestion.longform_normalize import normalize_article, normalize_batch
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

_TAG_STRIP_PATTERN = re.compile(r"<[^>]+>")


def _clean_text(raw: str) -> str:
    """Strips any stray HTML tags and unescapes entities in a feed's
    description field -- some feeds (WSJ, NYT) put plain text there,
    others occasionally wrap it in a <p> or similar."""
    if not raw:
        return ""
    text = _TAG_STRIP_PATTERN.sub("", raw)
    return html.unescape(text).strip()


def make_article_id(source: str, link: str) -> str:
    """Deterministic ID so re-running ingestion doesn't create duplicate records."""
    raw = f"{source}:{link}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def normalize_article(raw_article: dict) -> dict | None:
    """Maps a single raw long-form article into the schema used by the
    Research & Analysis tab. Returns None if there's no usable link or
    publish date."""
    source = raw_article.get("source", "")
    link = raw_article.get("link", "")
    title = raw_article.get("title", "")
    if not link or not title:
        return None

    pub_date = raw_article.get("pubDate", "")
    try:
        published_date = parsedate_to_datetime(pub_date).date().isoformat()
    except (TypeError, ValueError):
        try:
            published_date = datetime.fromisoformat(pub_date).date().isoformat()
        except (TypeError, ValueError):
            return None

    return {
        "article_id": make_article_id(source, link),
        "source": source,
        "title": _clean_text(title),
        "teaser": _clean_text(raw_article.get("description", "")) or None,
        "author": raw_article.get("author"),
        "link": link,
        "image_url": raw_article.get("image_url"),
        "published_date": published_date,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }


def normalize_batch(raw_articles: list[dict]) -> list[dict]:
    """Normalizes a list of raw long-form articles, skipping malformed
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
            print(f"WARNING: skipped malformed long-form article: {e}", file=sys.stderr)
    if skipped:
        print(f"Normalization complete with {skipped} record(s) skipped out of {len(raw_articles)}.",
              file=sys.stderr)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Normalize raw long-form articles")
    parser.add_argument("--input", type=str, required=True, help="Path to raw long-form JSON (from longform_fetch.py)")
    parser.add_argument("--output", type=str, default=None, help="Output path. Omit to print to stdout.")
    args = parser.parse_args()

    raw_articles = json.loads(Path(args.input).read_text(encoding="utf-8"))
    normalized = normalize_batch(raw_articles)

    output_json = json.dumps(normalized, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Wrote {len(normalized)} normalized articles to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
