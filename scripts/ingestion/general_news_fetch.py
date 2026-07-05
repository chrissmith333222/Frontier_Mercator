"""
scripts/ingestion/general_news_fetch.py

Fetches general-newspaper RSS feeds (NYT, WSJ) for the News & Social
Signal tab. Chris moved these here explicitly: "let's push news sources
like WSJ, NYT and other newspapers to that news and social signal tab"
-- keeping the Research & Analysis tab for policy/academic long-form
pieces (Economist, Foreign Affairs, Foreign Policy, JSTOR Daily, War on
the Rocks) and general current-events newspaper coverage here instead,
alongside GDELT/Infobae/Jeune Afrique/Bellingcat.

Same free-public-RSS-only scope as scripts/ingestion/longform_fetch.py
(headline + teaser, no login, no paywall bypass) -- just routed to the
event-oriented normalized_event schema (via general_news_normalize.py)
instead of the article-reading-list schema, since this feed populates a
country-taggable, significance-scored, event-driven tab.

Usage (CLI):
    python scripts/ingestion/general_news_fetch.py --output raw_general_news.json

Usage (as a module):
    from scripts.ingestion.general_news_fetch import fetch_all_feeds
    articles = fetch_all_feeds()
"""

import sys
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests

# (source name, feed URL) -- verified reachable, genuinely RSS, as of
# 2026-07-03. Extend this list for "other newspapers" later (same
# verify-before-build discipline as every other source in this repo).
FEEDS = [
    ("The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    ("The Wall Street Journal", "https://feeds.a.dj.com/rss/RSSWorldNews.xml"),
]

_MEDIA_CONTENT_TAG = "{http://search.yahoo.com/mrss/}content"


def _extract_image_url(item: ET.Element) -> str | None:
    media_content = item.find(_MEDIA_CONTENT_TAG)
    if media_content is not None and media_content.get("url"):
        return media_content.get("url")
    enclosure = item.find("enclosure")
    if enclosure is not None and enclosure.get("url"):
        return enclosure.get("url")
    return None


def _fetch_feed(source: str, url: str) -> list[dict]:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"{source} feed fetch failed: status {response.status_code}")

    root = ET.fromstring(response.content)
    articles = []
    for item in root.iter("item"):
        articles.append({
            "source": source,
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "description": (item.findtext("description") or "").strip(),
            "pubDate": (item.findtext("pubDate") or "").strip(),
            "guid": (item.findtext("guid") or "").strip(),
            "categories": [c.text for c in item.findall("category") if c.text],
            "image_url": _extract_image_url(item),
        })
    return articles


def fetch_all_feeds() -> list[dict]:
    """Fetches every feed in FEEDS, skipping (with a warning) any single
    feed that errors out rather than failing the whole batch."""
    all_articles = []
    for source, url in FEEDS:
        try:
            articles = _fetch_feed(source, url)
            all_articles.extend(articles)
            print(f"  {source}: {len(articles)} articles", file=sys.stderr)
        except Exception as e:
            print(f"  WARNING: {source} feed fetch failed, skipping: {e}", file=sys.stderr)
    return all_articles


def main():
    parser = argparse.ArgumentParser(description="Fetch general-newspaper RSS feeds")
    parser.add_argument("--output", type=str, default=None,
                         help="Write raw JSON output to this file path. Omit to print to stdout.")
    args = parser.parse_args()

    articles = fetch_all_feeds()
    print(f"Fetched {len(articles)} raw general-news articles total", file=sys.stderr)

    output_json = json.dumps(articles, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
