"""
scripts/ingestion/jeuneafrique_fetch.py

Fetches Jeune Afrique's public RSS feed -- a major pan-African French-
language news magazine (Paris-based, wide editorial reach across
Francophone West/Central/North Africa). Second non-English source after
Infobae (Spanish/pan-Latin America), part of the same "don't just cover
these regions through an English/Western lens" expansion Chris asked for.

No auth needed, no bot-protection encountered (plain requests with a
standard User-Agent works).

Usage (CLI):
    python scripts/ingestion/jeuneafrique_fetch.py --output raw_jeuneafrique.json

Usage (as a module):
    from scripts.ingestion.jeuneafrique_fetch import fetch_recent_articles
    articles = fetch_recent_articles()
"""

import sys
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests

FEED_URL = "https://www.jeuneafrique.com/feed/"


def fetch_recent_articles() -> list[dict]:
    """Fetches Jeune Afrique's RSS feed (typically the ~20 most recent
    published articles) and returns each as a raw dict."""
    response = requests.get(FEED_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Jeune Afrique feed fetch failed: status {response.status_code}")

    root = ET.fromstring(response.content)
    articles = []
    for item in root.iter("item"):
        articles.append({
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "pubDate": (item.findtext("pubDate") or "").strip(),
            "guid": (item.findtext("guid") or "").strip(),
        })
    return articles


def main():
    parser = argparse.ArgumentParser(description="Fetch recent Jeune Afrique articles")
    parser.add_argument("--output", type=str, default=None,
                         help="Write raw JSON output to this file path. Omit to print to stdout.")
    args = parser.parse_args()

    articles = fetch_recent_articles()
    print(f"Fetched {len(articles)} raw Jeune Afrique articles", file=sys.stderr)

    output_json = json.dumps(articles, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
