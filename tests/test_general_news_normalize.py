"""
tests/test_general_news_normalize.py

Tests the general-newspaper (NYT/WSJ) normalization logic against
fixture data -- no live feed fetch needed.

Usage:
    python -m pytest tests/test_general_news_normalize.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingestion.general_news_normalize import (
    normalize_article,
    normalize_batch,
    make_meridian_event_id,
    _clean_text,
)

NYT_ARTICLE_WITH_IMAGE = {
    "source": "The New York Times",
    "title": "Russia Hammers Ukraine's Capital in Deadly Attacks",
    "link": "https://www.nytimes.com/live/2026/07/02/world/ukraine-kyiv-russia-attack",
    "description": "At least 21 people were killed in Kyiv, the local authorities said.",
    "pubDate": "Fri, 03 Jul 2026 02:52:25 +0000",
    "guid": "https://www.nytimes.com/live/2026/07/02/world/ukraine-kyiv-russia-attack",
    "categories": ["World", "Europe"],
    "image_url": "https://static01.nyt.com/images/2026/07/02/photo.jpg",
}

WSJ_ARTICLE_NO_IMAGE = {
    "source": "The Wall Street Journal",
    "title": "Palestinians Stream Back to Northern Gaza on Foot",
    "link": "https://www.wsj.com/articles/palestinians-flock-back",
    "description": "Israel allowed displaced Gazans to begin crossing a military zone.",
    "pubDate": "Mon, 27 Jan 2025 14:23:00 -0500",
    "guid": "WP-WSJ-0002354638",
    "categories": ["Middle East News"],
    "image_url": None,
}

NO_LINK_ARTICLE = {
    "source": "The New York Times", "title": "Some Title", "link": "",
    "description": "", "pubDate": "Fri, 03 Jul 2026 02:52:25 +0000", "guid": "", "categories": [],
    "image_url": None,
}

BAD_DATE_ARTICLE = {
    "source": "The Wall Street Journal", "title": "Some Title", "link": "https://www.wsj.com/x",
    "description": "", "pubDate": "not a date", "guid": "https://www.wsj.com/x", "categories": [],
    "image_url": None,
}


def test_basic_field_mapping():
    result = normalize_article(NYT_ARTICLE_WITH_IMAGE)
    assert result["source"] == "The New York Times"
    assert result["event_category"] == "other"
    assert result["event_date"] == "2026-07-03"
    assert result["image_url"] == "https://static01.nyt.com/images/2026/07/02/photo.jpg"
    print("✓ test_basic_field_mapping passed")


def test_country_detected_from_title_and_description():
    result = normalize_article(NYT_ARTICLE_WITH_IMAGE)
    assert result["country"] == "Ukraine"
    print("✓ test_country_detected_from_title_and_description passed")


def test_narrative_summary_en_always_none_english_source():
    result = normalize_article(WSJ_ARTICLE_NO_IMAGE)
    assert result["narrative_summary_en"] is None
    print("✓ test_narrative_summary_en_always_none_english_source passed")


def test_event_datetime_preserves_time_of_day():
    result = normalize_article(NYT_ARTICLE_WITH_IMAGE)
    assert result["event_datetime"].startswith("2026-07-03T02:52:25")
    print("✓ test_event_datetime_preserves_time_of_day passed")


def test_no_link_returns_none():
    assert normalize_article(NO_LINK_ARTICLE) is None
    print("✓ test_no_link_returns_none passed")


def test_bad_date_returns_none():
    assert normalize_article(BAD_DATE_ARTICLE) is None
    print("✓ test_bad_date_returns_none passed")


def test_deterministic_id_generation():
    id1 = make_meridian_event_id("The New York Times", "https://www.nytimes.com/x")
    id2 = make_meridian_event_id("The New York Times", "https://www.nytimes.com/x")
    id3 = make_meridian_event_id("The New York Times", "https://www.nytimes.com/y")
    assert id1 == id2
    assert id1 != id3
    print("✓ test_deterministic_id_generation passed")


def test_clean_text_strips_html():
    assert _clean_text("<p>Hello &amp; world</p>") == "Hello & world"
    print("✓ test_clean_text_strips_html passed")


def test_batch_normalization_skips_malformed():
    batch = [NYT_ARTICLE_WITH_IMAGE, WSJ_ARTICLE_NO_IMAGE, NO_LINK_ARTICLE, BAD_DATE_ARTICLE]
    results = normalize_batch(batch)
    assert len(results) == 2
    print(f"✓ test_batch_normalization_skips_malformed passed ({len(results)}/4 normalized)")


if __name__ == "__main__":
    test_functions = [v for k, v in list(globals().items()) if k.startswith("test_")]
    print(f"Running {len(test_functions)} tests...\n")
    failures = 0
    for test_fn in test_functions:
        try:
            test_fn()
        except AssertionError as e:
            failures += 1
            print(f"✗ {test_fn.__name__} FAILED: {e}")
    print(f"\n{len(test_functions) - failures}/{len(test_functions)} tests passed.")
    if failures:
        sys.exit(1)
