"""
tests/test_reliefweb_normalize.py

Tests the ReliefWeb normalization logic against fixture data — no live API
calls, no appname needed. Run this to verify the schema mapping after any
changes to reliefweb_normalize.py.

Usage:
    python -m pytest tests/test_reliefweb_normalize.py -v
    (or, without pytest installed: python tests/test_reliefweb_normalize.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingestion.reliefweb_normalize import (
    normalize_reliefweb_report,
    normalize_batch,
    compute_severity_score,
    make_meridian_event_id,
)

# Sample raw ReliefWeb report, shaped like real API v2 output, single country.
SAMPLE_REPORT = {
    "id": "4123456",
    "fields": {
        "title": "Mali: Displacement Situation Report, June 2026",
        "url": "https://reliefweb.int/report/mali/example",
        "date": {"created": "2026-06-20T10:00:00+00:00", "original": "2026-06-19T00:00:00+00:00"},
        "country": [{"name": "Mali", "iso3": "MLI"}],
        "source": [{"name": "OCHA"}],
        "format": [{"name": "Situation Report"}],
        "disaster_type": [{"name": "Population Movement"}],
        "body": "An estimated 50,000 people have been displaced in the Mopti region...",
    },
}

# Multi-country report — should expand into 2 normalized events.
MULTI_COUNTRY_REPORT = {
    "id": "4123999",
    "fields": {
        "title": "Sahel Regional Overview",
        "url": "https://reliefweb.int/report/sahel/example",
        "date": {"created": "2026-06-15T00:00:00+00:00"},
        "country": [{"name": "Mali", "iso3": "MLI"}, {"name": "Niger", "iso3": "NER"}],
        "source": [{"name": "UNHCR"}],
        "format": [{"name": "News and Press Release"}],
        "disaster_type": [],
        "body": "Regional displacement trends across the Sahel...",
    },
}

EXTENDED_COUNTRY_REPORT = {
    "id": "4124000",
    "fields": {
        "title": "Syria: Emergency Response Plan",
        "url": "https://reliefweb.int/report/syria/example",
        "date": {"created": "2026-06-10T00:00:00+00:00"},
        "country": [{"name": "Syria", "iso3": "SYR"}],
        "source": [{"name": "OCHA"}],
        "format": [{"name": "Emergency Response Plan"}],
        "disaster_type": [{"name": "Complex Emergency"}],
        "body": "",
    },
}

NO_DATE_REPORT = {
    "id": "4124111",
    "fields": {
        "title": "Malformed report with no date",
        "country": [{"name": "Mali", "iso3": "MLI"}],
    },
}

NO_COUNTRY_REPORT = {
    "id": "4124222",
    "fields": {
        "title": "Malformed report with no country",
        "date": {"created": "2026-06-01T00:00:00+00:00"},
        "country": [],
    },
}


def test_basic_field_mapping():
    results = normalize_reliefweb_report(SAMPLE_REPORT)
    assert len(results) == 1
    result = results[0]
    assert result["source"] == "ReliefWeb"
    assert result["country"] == "Mali"
    assert result["iso3"] == "MLI"
    assert result["event_date"] == "2026-06-19"
    assert result["event_category"] == "humanitarian"
    assert result["in_core_mandate"] is True
    assert result["region"] == "West Africa / Sahel"
    print("✓ test_basic_field_mapping passed")


def test_multi_country_report_expands():
    results = normalize_reliefweb_report(MULTI_COUNTRY_REPORT)
    assert len(results) == 2
    countries = {r["country"] for r in results}
    assert countries == {"Mali", "Niger"}
    # IDs must differ even though they share a source report
    assert results[0]["meridian_event_id"] != results[1]["meridian_event_id"]
    print("✓ test_multi_country_report_expands passed")


def test_extended_monitoring_country():
    results = normalize_reliefweb_report(EXTENDED_COUNTRY_REPORT)
    assert len(results) == 1
    assert results[0]["region"] == "Middle East"
    assert results[0]["in_core_mandate"] is False
    print("✓ test_extended_monitoring_country passed")


def test_severity_scoring():
    sitrep_score = compute_severity_score(SAMPLE_REPORT["fields"])       # Situation Report + Pop Movement
    news_score = compute_severity_score(MULTI_COUNTRY_REPORT["fields"])  # News, no disaster type
    emergency_score = compute_severity_score(EXTENDED_COUNTRY_REPORT["fields"])  # Emergency Plan + Complex Emergency

    assert sitrep_score > news_score
    assert emergency_score > sitrep_score
    assert 0 <= news_score <= 10
    print(f"✓ test_severity_scoring passed (sitrep={sitrep_score}, news={news_score}, emergency={emergency_score})")


def test_no_date_returns_empty():
    results = normalize_reliefweb_report(NO_DATE_REPORT)
    assert results == []
    print("✓ test_no_date_returns_empty passed")


def test_no_country_returns_empty():
    results = normalize_reliefweb_report(NO_COUNTRY_REPORT)
    assert results == []
    print("✓ test_no_country_returns_empty passed")


def test_deterministic_id_generation():
    id1 = make_meridian_event_id("ReliefWeb", "4123456:MLI")
    id2 = make_meridian_event_id("ReliefWeb", "4123456:MLI")
    id3 = make_meridian_event_id("ReliefWeb", "4123456:NER")
    assert id1 == id2
    assert id1 != id3
    print("✓ test_deterministic_id_generation passed")


def test_batch_normalization_skips_and_expands():
    batch = [SAMPLE_REPORT, MULTI_COUNTRY_REPORT, NO_DATE_REPORT, NO_COUNTRY_REPORT]
    results = normalize_batch(batch)
    # 1 (Mali) + 2 (Mali, Niger) = 3; the two malformed reports contribute 0
    assert len(results) == 3
    print(f"✓ test_batch_normalization_skips_and_expands passed ({len(results)} events from {len(batch)} reports)")


def test_raw_data_preserved_for_audit():
    results = normalize_reliefweb_report(SAMPLE_REPORT)
    assert results[0]["raw_source_data"] == SAMPLE_REPORT
    print("✓ test_raw_data_preserved_for_audit passed")


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
