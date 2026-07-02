"""
tests/test_bellingcat_normalize.py

Tests the Bellingcat normalization logic against fixture data -- no live
feed fetch needed.

Usage:
    python -m pytest tests/test_bellingcat_normalize.py -v
    (or, without pytest installed: python tests/test_bellingcat_normalize.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingestion.bellingcat_normalize import (
    normalize_bellingcat_article,
    normalize_batch,
    make_meridian_event_id,
)

MALI_ARTICLE = {
    "title": "Geolocating Recent Clashes in Northern Mali",
    "link": "https://www.bellingcat.com/news/2026/06/15/mali-clashes/",
    "pubDate": "Mon, 15 Jun 2026 10:00:00 +0000",
    "description": "An investigation into recent fighting.",
    "categories": ["Africa", "Mali", "Conflict"],
    "guid": "https://www.bellingcat.com/?p=12345",
}

GLOBAL_METHOD_ARTICLE = {
    "title": "Burning Forests: Tools for Tracking and Reporting Wildfire Damage",
    "link": "https://www.bellingcat.com/resources/how-tos/2026/06/30/wildfire-tools/",
    "pubDate": "Tue, 30 Jun 2026 08:00:00 +0000",
    "description": "A guide to open source wildfire analysis.",
    "categories": ["Environment", "How-Tos"],
    "guid": "https://www.bellingcat.com/?p=52910",
}

NO_TITLE_ARTICLE = {
    "title": "",
    "link": "https://www.bellingcat.com/?p=1",
    "pubDate": "Tue, 30 Jun 2026 08:00:00 +0000",
    "guid": "https://www.bellingcat.com/?p=1",
}

BAD_DATE_ARTICLE = {
    "title": "Some Title",
    "link": "https://www.bellingcat.com/?p=2",
    "pubDate": "not a date",
    "guid": "https://www.bellingcat.com/?p=2",
}


def test_detects_country_from_title_and_categories():
    result = normalize_bellingcat_article(MALI_ARTICLE)
    assert result["source"] == "Bellingcat"
    assert result["country"] == "Mali"
    assert result["iso3"] == "MLI"
    assert result["region"] == "West Africa / Sahel"
    assert result["in_core_mandate"] is True
    assert result["event_category"] == "other"
    print("✓ test_detects_country_from_title_and_categories passed")


def test_falls_back_to_global_when_no_country_mentioned():
    result = normalize_bellingcat_article(GLOBAL_METHOD_ARTICLE)
    assert result is not None
    assert result["country"] == "Global"
    assert result["region"] == "Global / Other Monitoring"
    assert result["in_core_mandate"] is False
    print("✓ test_falls_back_to_global_when_no_country_mentioned passed")


def test_event_date_parsed_from_rfc822():
    result = normalize_bellingcat_article(MALI_ARTICLE)
    assert result["event_date"] == "2026-06-15"
    print("✓ test_event_date_parsed_from_rfc822 passed")


def test_no_title_returns_none():
    result = normalize_bellingcat_article(NO_TITLE_ARTICLE)
    assert result is None
    print("✓ test_no_title_returns_none passed")


def test_bad_date_returns_none():
    result = normalize_bellingcat_article(BAD_DATE_ARTICLE)
    assert result is None
    print("✓ test_bad_date_returns_none passed")


def test_deterministic_id_generation():
    id1 = make_meridian_event_id("Bellingcat", "https://www.bellingcat.com/?p=12345")
    id2 = make_meridian_event_id("Bellingcat", "https://www.bellingcat.com/?p=12345")
    id3 = make_meridian_event_id("Bellingcat", "https://www.bellingcat.com/?p=99999")
    assert id1 == id2
    assert id1 != id3
    print("✓ test_deterministic_id_generation passed")


def test_batch_normalization_skips_malformed():
    batch = [MALI_ARTICLE, GLOBAL_METHOD_ARTICLE, NO_TITLE_ARTICLE, BAD_DATE_ARTICLE]
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
