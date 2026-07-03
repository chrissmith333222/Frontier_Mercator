"""
scripts/ingestion/longform_fetch.py

Fetches the free, publicly-published RSS feeds of major outlets (The
Economist, Foreign Affairs, Foreign Policy, NYT World, WSJ World) for the
Research & Analysis tab -- Chris's ask for scholarly/policy/long-form
reading material distinct from the event-driven News & Social Signal
tab, presented WSJ/NYT-style with a thumbnail "grabber" image per piece.

Important scope boundary: this ONLY ever reads each outlet's own public
RSS feed (headline + teaser/dek + link, exactly what any RSS reader
would see, no login involved). It never authenticates with a personal
subscription to pull full paywalled article text -- that would violate
each outlet's Terms of Service even with valid credentials (subscription
agreements grant personal browsing rights, not a right to scrape
programmatically) and risks Chris's own accounts. If he wants the full
text of a specific piece, the "Read full article" link takes him to the
publisher's site where his own subscription/login applies normally.

Not every outlet's feed follows the same image convention -- NYT and
Foreign Affairs use <media:content>, Foreign Policy uses <enclosure>,
WSJ and The Economist don't embed an image at all. _extract_image_url
checks all the conventions this batch of feeds actually uses; add more
if a new source needs one this doesn't already handle.

Usage (CLI):
    python scripts/ingestion/longform_fetch.py --output raw_longform.json

Usage (as a module):
    from scripts.ingestion.longform_fetch import fetch_all_feeds
    articles = fetch_all_feeds()
"""

import sys
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests

# (source name, feed URL) -- verified reachable and genuinely RSS (not an
# HTML redirect) as of 2026-07-03. Brookings and Carnegie Endowment were
# checked too but their most obvious feed URLs return their HTML homepage,
# not RSS -- skipped rather than guessing at undocumented feed paths;
# worth revisiting if their real feed URL is found later.
FEEDS = [
    ("The Economist", "https://www.economist.com/international/rss.xml"),
    ("The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    ("Foreign Affairs", "https://www.foreignaffairs.com/rss.xml"),
    ("Foreign Policy", "https://foreignpolicy.com/feed/"),
    ("The Wall Street Journal", "https://feeds.a.dj.com/rss/RSSWorldNews.xml"),
]

_MEDIA_CONTENT_TAG = "{http://search.yahoo.com/mrss/}content"


def _extract_image_url(item: ET.Element) -> str | None:
    """Checks the image conventions actually used by FEEDS above: NYT and
    Foreign Affairs use <media:content url="...">, Foreign Policy uses a
    plain <enclosure url="...">. Returns None if neither is present
    (WSJ, The Economist don't embed one)."""
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
            "author": (item.findtext("{http://purl.org/dc/elements/1.1/}creator") or "").strip() or None,
            "pubDate": (item.findtext("pubDate") or "").strip(),
            "image_url": _extract_image_url(item),
        })
    return articles


def fetch_all_feeds() -> list[dict]:
    """Fetches every feed in FEEDS, skipping (with a warning, not a hard
    failure) any single feed that errors out -- one outlet's feed being
    temporarily down shouldn't block ingesting the rest."""
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
    parser = argparse.ArgumentParser(description="Fetch long-form/analysis RSS feeds")
    parser.add_argument("--output", type=str, default=None,
                         help="Write raw JSON output to this file path. Omit to print to stdout.")
    args = parser.parse_args()

    articles = fetch_all_feeds()
    print(f"Fetched {len(articles)} raw long-form articles total", file=sys.stderr)

    output_json = json.dumps(articles, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
