"""
tests/test_longform_normalize.py

Tests the long-form article normalization logic (Research & Analysis
tab's data layer) against fixture data -- no live feed fetch needed.

Usage:
    python -m pytest tests/test_longform_normalize.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingestion.longform_normalize import (
    normalize_article,
    normalize_batch,
    make_article_id,
    _clean_text,
)

RFC822_ARTICLE = {
    "source": "The Economist",
    "title": "NATO ponders how to defend Eastern Europe",
    "link": "https://www.economist.com/international/2026/07/02/nato-ponders",
    "description": "German tanks are returning to a region they once razed",
    "author": None,
    "pubDate": "Thu, 02 Jul 2026 14:22:37 +0000",
    "image_url": None,
}

WITH_IMAGE_AND_HTML_DESCRIPTION = {
    "source": "The New York Times",
    "title": "Russia Hammers Ukraine's Capital",
    "link": "https://www.nytimes.com/live/2026/07/02/world/ukraine-kyiv",
    "description": "<p>At least 21 people were killed &amp; dozens hurt.</p>",
    "author": "The New York Times",
    "pubDate": "Fri, 03 Jul 2026 02:52:25 +0000",
    "image_url": "https://static01.nyt.com/images/2026/07/02/photo.jpg",
}

NO_LINK_ARTICLE = {
    "source": "Foreign Policy", "title": "Some Title", "link": "",
    "description": "", "author": None, "pubDate": "Thu, 02 Jul 2026 22:03:52 +0000", "image_url": None,
}

BAD_DATE_ARTICLE = {
    "source": "WSJ", "title": "Some Title", "link": "https://www.wsj.com/articles/x",
    "description": "", "author": None, "pubDate": "not a date", "image_url": None,
}


def test_basic_normalization():
    result = normalize_article(RFC822_ARTICLE)
    assert result["source"] == "The Economist"
    assert result["title"] == "NATO ponders how to defend Eastern Europe"
    assert result["teaser"] == "German tanks are returning to a region they once razed"
    assert result["published_date"] == "2026-07-02"
    assert result["image_url"] is None
    print("✓ test_basic_normalization passed")


def test_html_description_and_entities_cleaned():
    result = normalize_article(WITH_IMAGE_AND_HTML_DESCRIPTION)
    assert result["teaser"] == "At least 21 people were killed & dozens hurt."
    assert result["image_url"] == "https://static01.nyt.com/images/2026/07/02/photo.jpg"
    print("✓ test_html_description_and_entities_cleaned passed")


def test_clean_text_strips_tags_and_unescapes():
    assert _clean_text("<p>Hello &amp; welcome</p>") == "Hello & welcome"
    assert _clean_text("") == ""
    print("✓ test_clean_text_strips_tags_and_unescapes passed")


def test_no_link_returns_none():
    assert normalize_article(NO_LINK_ARTICLE) is None
    print("✓ test_no_link_returns_none passed")


def test_bad_date_returns_none():
    assert normalize_article(BAD_DATE_ARTICLE) is None
    print("✓ test_bad_date_returns_none passed")


def test_deterministic_id_generation():
    id1 = make_article_id("Foreign Affairs", "https://www.foreignaffairs.com/x")
    id2 = make_article_id("Foreign Affairs", "https://www.foreignaffairs.com/x")
    id3 = make_article_id("Foreign Affairs", "https://www.foreignaffairs.com/y")
    assert id1 == id2
    assert id1 != id3
    print("✓ test_deterministic_id_generation passed")


def test_batch_normalization_skips_malformed():
    batch = [RFC822_ARTICLE, WITH_IMAGE_AND_HTML_DESCRIPTION, NO_LINK_ARTICLE, BAD_DATE_ARTICLE]
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
