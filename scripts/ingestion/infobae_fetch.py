"""
scripts/ingestion/infobae_fetch.py

Fetches Infobae's public RSS feed -- a major pan-Latin American Spanish-
language news outlet (Argentina-based, wide reach across Mexico,
Colombia, Peru, Brazil, and beyond). Part of the non-English/non-Western
regional source expansion Chris asked for: everything ingested so far
was English-language (ACLED, GDELT, World Bank/IMF, AidData, DFC, World
Bank PPI, UNOSAT, Bellingcat) -- this is the first source that gives
authentic local-language reporting rather than only English-language
coverage of these regions.

No auth needed, no bot-protection encountered (plain requests with a
standard User-Agent works, unlike the Cloudflare-fronted sources).

Usage (CLI):
    python scripts/ingestion/infobae_fetch.py --output raw_infobae.json

Usage (as a module):
    from scripts.ingestion.infobae_fetch import fetch_recent_articles
    articles = fetch_recent_articles()
"""

import sys
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests

FEED_URL = "https://www.infobae.com/arc/outboundfeeds/rss/"

# RSS's "content" module namespace -- Infobae's feed embeds each article's
# lead image as an <img> tag inside <content:encoded>, which ElementTree
# needs the full namespace URI (not the "content:" prefix) to find.
_CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"


def fetch_recent_articles() -> list[dict]:
    """Fetches Infobae's RSS feed (typically the ~20-30 most recent
    published articles across all sections) and returns each as a raw
    dict, including the raw content:encoded HTML (used downstream to pull
    out a thumbnail image -- Chris asked for a visual per news item, same
    as the WSJ/NYT "grabber" thumbnail pattern)."""
    response = requests.get(FEED_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Infobae feed fetch failed: status {response.status_code}")

    root = ET.fromstring(response.content)
    articles = []
    for item in root.iter("item"):
        articles.append({
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "pubDate": (item.findtext("pubDate") or "").strip(),
            "guid": (item.findtext("guid") or "").strip(),
            "content_encoded": item.findtext(_CONTENT_NS) or "",
        })
    return articles


def main():
    parser = argparse.ArgumentParser(description="Fetch recent Infobae articles")
    parser.add_argument("--output", type=str, default=None,
                         help="Write raw JSON output to this file path. Omit to print to stdout.")
    args = parser.parse_args()

    articles = fetch_recent_articles()
    print(f"Fetched {len(articles)} raw Infobae articles", file=sys.stderr)

    output_json = json.dumps(articles, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
