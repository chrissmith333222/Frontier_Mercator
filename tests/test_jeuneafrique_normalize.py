"""
tests/test_jeuneafrique_normalize.py

Tests the Jeune Afrique normalization logic (French accent-stripping and
alias-based country detection, including RDC/Cote d'Ivoire-style
abbreviations that don't exist in Spanish) against fixture data -- no
live feed fetch needed.

Usage:
    python -m pytest tests/test_jeuneafrique_normalize.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingestion.jeuneafrique_normalize import (
    normalize_jeuneafrique_article,
    normalize_batch,
    make_meridian_event_id,
    _strip_accents,
)

ACCENTED_COUNTRY_ARTICLE = {
    "title": "Bénin : le gouvernement annonce de nouvelles mesures économiques",
    "link": "https://www.jeuneafrique.com/benin/2026/07/02/note/",
    "pubDate": "Thu, 02 Jul 2026 02:15:00 +0000",
    "guid": "https://www.jeuneafrique.com/?p=2001",
}

ALIAS_ABBREVIATION_ARTICLE = {
    "title": "RDC : comment les rebelles progressent dans l'est du pays",
    "link": "https://www.jeuneafrique.com/rdc/2026/07/02/note-2/",
    "pubDate": "Thu, 02 Jul 2026 03:00:00 +0000",
    "guid": "https://www.jeuneafrique.com/?p=2002",
}

APOSTROPHE_COUNTRY_ARTICLE = {
    "title": "Cote d'Ivoire : le prix du cacao stimule l'appetit des investisseurs",
    "link": "https://www.jeuneafrique.com/civ/2026/07/02/note-3/",
    "pubDate": "Thu, 02 Jul 2026 04:00:00 +0000",
    "guid": "https://www.jeuneafrique.com/?p=2003",
}

NO_COUNTRY_ARTICLE = {
    "title": "10 choses a savoir sur le nouveau selectionneur des Lions",
    "link": "https://www.jeuneafrique.com/sport/2026/07/02/note-4/",
    "pubDate": "Thu, 02 Jul 2026 02:15:19 +0000",
    "guid": "https://www.jeuneafrique.com/?p=2004",
}

NO_TITLE_ARTICLE = {
    "title": "",
    "link": "https://www.jeuneafrique.com/?p=2005",
    "guid": "https://www.jeuneafrique.com/?p=2005",
    "pubDate": "Thu, 02 Jul 2026 02:15:19 +0000",
}

BAD_DATE_ARTICLE = {
    "title": "Some Title",
    "link": "https://www.jeuneafrique.com/?p=2006",
    "guid": "https://www.jeuneafrique.com/?p=2006",
    "pubDate": "not a date",
}


def test_strip_accents_removes_diacritics():
    assert _strip_accents("Bénin") == "Benin"
    assert _strip_accents("Côte") == "Cote"
    assert _strip_accents("Général") == "General"
    print("✓ test_strip_accents_removes_diacritics passed")


def test_accented_country_name_resolves_via_accent_stripping():
    result = normalize_jeuneafrique_article(ACCENTED_COUNTRY_ARTICLE)
    assert result["source"] == "JeuneAfrique"
    assert result["country"] == "Benin"
    assert result["iso3"] == "BEN"
    assert result["in_core_mandate"] is True
    assert result["event_category"] == "other"
    print("✓ test_accented_country_name_resolves_via_accent_stripping passed")


def test_french_abbreviation_alias_resolves():
    result = normalize_jeuneafrique_article(ALIAS_ABBREVIATION_ARTICLE)
    assert result["country"] == "Democratic Republic of Congo"
    assert result["iso3"] == "COD"
    print("✓ test_french_abbreviation_alias_resolves passed")


def test_apostrophe_country_name_resolves():
    result = normalize_jeuneafrique_article(APOSTROPHE_COUNTRY_ARTICLE)
    assert result["country"] == "Ivory Coast"
    assert result["iso3"] == "CIV"
    print("✓ test_apostrophe_country_name_resolves passed")


def test_no_country_mentioned_falls_back_to_global():
    result = normalize_jeuneafrique_article(NO_COUNTRY_ARTICLE)
    assert result is not None
    assert result["country"] == "Global"
    assert result["region"] == "Global / Other Monitoring"
    assert result["in_core_mandate"] is False
    print("✓ test_no_country_mentioned_falls_back_to_global passed")


def test_event_date_parsed_from_rfc822():
    result = normalize_jeuneafrique_article(ACCENTED_COUNTRY_ARTICLE)
    assert result["event_date"] == "2026-07-02"
    print("✓ test_event_date_parsed_from_rfc822 passed")


def test_no_title_returns_none():
    result = normalize_jeuneafrique_article(NO_TITLE_ARTICLE)
    assert result is None
    print("✓ test_no_title_returns_none passed")


def test_bad_date_returns_none():
    result = normalize_jeuneafrique_article(BAD_DATE_ARTICLE)
    assert result is None
    print("✓ test_bad_date_returns_none passed")


def test_deterministic_id_generation():
    id1 = make_meridian_event_id("JeuneAfrique", "https://www.jeuneafrique.com/?p=2001")
    id2 = make_meridian_event_id("JeuneAfrique", "https://www.jeuneafrique.com/?p=2001")
    id3 = make_meridian_event_id("JeuneAfrique", "https://www.jeuneafrique.com/?p=9999")
    assert id1 == id2
    assert id1 != id3
    print("✓ test_deterministic_id_generation passed")


def test_batch_normalization_skips_malformed():
    batch = [ACCENTED_COUNTRY_ARTICLE, ALIAS_ABBREVIATION_ARTICLE, NO_TITLE_ARTICLE, BAD_DATE_ARTICLE]
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
