"""
tests/test_infobae_normalize.py

Tests the Infobae normalization logic (Spanish-language accent-stripping
and alias-based country detection) against fixture data -- no live feed
fetch needed.

Usage:
    python -m pytest tests/test_infobae_normalize.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingestion.infobae_normalize import (
    normalize_infobae_article,
    normalize_batch,
    make_meridian_event_id,
    _strip_accents,
)

ACCENTED_COUNTRY_ARTICLE = {
    "title": "México anuncia nuevas medidas económicas tras la reunión bilateral",
    "link": "https://www.infobae.com/mexico/2026/07/03/nota/",
    "pubDate": "Fri, 03 Jul 2026 02:15:00 +0000",
    "guid": "https://www.infobae.com/?p=1001",
}

ALIAS_COUNTRY_ARTICLE = {
    "title": "Alemania y Francia firman acuerdo comercial histórico",
    "link": "https://www.infobae.com/europa/2026/07/03/nota-2/",
    "pubDate": "Fri, 03 Jul 2026 03:00:00 +0000",
    "guid": "https://www.infobae.com/?p=1002",
}

NO_COUNTRY_ARTICLE = {
    "title": "Roberto Martínez: \"Ahora comenzamos el segundo Mundial\"",
    "link": "https://www.infobae.com/america/agencias/2026/07/03/nota-3/",
    "pubDate": "Fri, 03 Jul 2026 02:15:19 +0000",
    "guid": "https://www.infobae.com/?p=1003",
}

NO_TITLE_ARTICLE = {
    "title": "",
    "link": "https://www.infobae.com/?p=1004",
    "guid": "https://www.infobae.com/?p=1004",
    "pubDate": "Fri, 03 Jul 2026 02:15:19 +0000",
}

BAD_DATE_ARTICLE = {
    "title": "Some Title",
    "link": "https://www.infobae.com/?p=1005",
    "guid": "https://www.infobae.com/?p=1005",
    "pubDate": "not a date",
}


def test_strip_accents_removes_diacritics():
    assert _strip_accents("México") == "Mexico"
    assert _strip_accents("Perú") == "Peru"
    assert _strip_accents("São Paulo") == "Sao Paulo"
    print("✓ test_strip_accents_removes_diacritics passed")


def test_accented_country_name_resolves_via_accent_stripping():
    result = normalize_infobae_article(ACCENTED_COUNTRY_ARTICLE)
    assert result["source"] == "Infobae"
    assert result["country"] == "Mexico"
    assert result["iso3"] == "MEX"
    assert result["in_core_mandate"] is True
    assert result["event_category"] == "other"
    print("✓ test_accented_country_name_resolves_via_accent_stripping passed")


def test_spanish_alias_country_name_resolves():
    result = normalize_infobae_article(ALIAS_COUNTRY_ARTICLE)
    # "Alemania" (Germany) appears first in the title, should win.
    assert result["country"] == "Germany"
    assert result["iso3"] == "DEU"
    print("✓ test_spanish_alias_country_name_resolves passed")


def test_no_country_mentioned_falls_back_to_global():
    result = normalize_infobae_article(NO_COUNTRY_ARTICLE)
    assert result is not None
    assert result["country"] == "Global"
    assert result["region"] == "Global / Other Monitoring"
    assert result["in_core_mandate"] is False
    print("✓ test_no_country_mentioned_falls_back_to_global passed")


def test_event_date_parsed_from_rfc822():
    result = normalize_infobae_article(ACCENTED_COUNTRY_ARTICLE)
    assert result["event_date"] == "2026-07-03"
    print("✓ test_event_date_parsed_from_rfc822 passed")


def test_no_title_returns_none():
    result = normalize_infobae_article(NO_TITLE_ARTICLE)
    assert result is None
    print("✓ test_no_title_returns_none passed")


def test_bad_date_returns_none():
    result = normalize_infobae_article(BAD_DATE_ARTICLE)
    assert result is None
    print("✓ test_bad_date_returns_none passed")


def test_deterministic_id_generation():
    id1 = make_meridian_event_id("Infobae", "https://www.infobae.com/?p=1001")
    id2 = make_meridian_event_id("Infobae", "https://www.infobae.com/?p=1001")
    id3 = make_meridian_event_id("Infobae", "https://www.infobae.com/?p=9999")
    assert id1 == id2
    assert id1 != id3
    print("✓ test_deterministic_id_generation passed")


def test_batch_normalization_skips_malformed():
    batch = [ACCENTED_COUNTRY_ARTICLE, ALIAS_COUNTRY_ARTICLE, NO_TITLE_ARTICLE, BAD_DATE_ARTICLE]
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
