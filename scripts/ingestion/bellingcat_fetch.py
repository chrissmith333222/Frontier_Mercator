"""
scripts/ingestion/bellingcat_fetch.py

Fetches Bellingcat's published investigations via their public RSS feed --
open-source investigative journalism, often grounded in satellite imagery/
geolocation analysis (this is part of the OSINT/imagery strategy: rather
than building our own computer-vision pipeline, we ingest the *conclusions*
of organizations already doing rigorous imagery-based investigation). No
auth needed, but the feed sits behind Cloudflare bot management like World
Bank did -- same curl_cffi fix applies.

Usage (CLI):
    python scripts/ingestion/bellingcat_fetch.py --output raw_bellingcat.json

Usage (as a module):
    from scripts.ingestion.bellingcat_fetch import fetch_recent_articles
    articles = fetch_recent_articles()
"""

import sys
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from curl_cffi import requests as curl_requests

FEED_URL = "https://www.bellingcat.com/feed/"


def fetch_recent_articles() -> list[dict]:
    """Fetches Bellingcat's RSS feed (typically the ~20 most recent
    published investigations/guides) and returns each as a raw dict."""
    response = curl_requests.get(FEED_URL, impersonate="chrome", timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Bellingcat feed fetch failed: status {response.status_code}")

    root = ET.fromstring(response.text)
    articles = []
    for item in root.iter("item"):
        categories = [c.text for c in item.findall("category") if c.text]
        articles.append({
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "pubDate": (item.findtext("pubDate") or "").strip(),
            "description": (item.findtext("description") or "").strip(),
            "categories": categories,
            "guid": (item.findtext("guid") or "").strip(),
        })
    return articles


def main():
    parser = argparse.ArgumentParser(description="Fetch recent Bellingcat investigations")
    parser.add_argument("--output", type=str, default=None,
                         help="Write raw JSON output to this file path. Omit to print to stdout.")
    args = parser.parse_args()

    articles = fetch_recent_articles()
    print(f"Fetched {len(articles)} raw Bellingcat articles", file=sys.stderr)

    output_json = json.dumps(articles, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
