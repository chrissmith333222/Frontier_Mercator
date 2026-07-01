"""
tests/test_worldbank_normalize.py

Tests the World Bank normalization logic against fixture data — no live API
calls needed. Run this to verify the schema mapping after any changes to
worldbank_normalize.py.

Usage:
    python -m pytest tests/test_worldbank_normalize.py -v
    (or, without pytest installed: python tests/test_worldbank_normalize.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingestion.worldbank_normalize import (
    normalize_worldbank_record,
    normalize_batch,
    make_meridian_event_id,
)

# Sample raw World Bank record, shaped like real API v2 output.
GDP_RECORD = {
    "indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"},
    "country": {"id": "NG", "value": "Nigeria"},
    "countryiso3code": "NGA",
    "date": "2025",
    "value": 4.01336180700973,
    "unit": "",
    "obs_status": "",
    "decimal": 1,
}

EXTENDED_COUNTRY_RECORD = {
    "indicator": {"id": "FP.CPI.TOTL.ZG", "value": "Inflation, consumer prices (annual %)"},
    "country": {"id": "TR", "value": "Turkiye"},
    "countryiso3code": "TUR",
    "date": "2025",
    "value": 38.2,
    "unit": "",
    "obs_status": "",
    "decimal": 1,
}

MISSING_VALUE_RECORD = {
    "indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"},
    "country": {"id": "NG", "value": "Nigeria"},
    "countryiso3code": "NGA",
    "date": "2026",
    "value": None,
    "unit": "",
    "obs_status": "",
    "decimal": 1,
}

UNKNOWN_COUNTRY_RECORD = {
    "indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"},
    "country": {"id": "US", "value": "United States"},
    "countryiso3code": "USA",
    "date": "2025",
    "value": 2.5,
    "unit": "",
    "obs_status": "",
    "decimal": 1,
}


def test_basic_field_mapping():
    result = normalize_worldbank_record(GDP_RECORD)
    assert result["source"] == "WorldBank"
    assert result["country"] == "Nigeria"
    assert result["iso3"] == "NGA"
    assert result["event_date"] == "2025-12-31"
    assert result["event_category"] == "economic_indicator"
    assert result["in_core_mandate"] is True
    assert result["region"] == "West Africa / Sahel"
    assert "4.0%" in result["narrative_summary"]
    print("✓ test_basic_field_mapping passed")


def test_missing_value_returns_none():
    result = normalize_worldbank_record(MISSING_VALUE_RECORD)
    assert result is None, "World Bank records with no value (common for recent years) should be skipped"
    print("✓ test_missing_value_returns_none passed")


def test_extended_monitoring_country():
    result = normalize_worldbank_record(EXTENDED_COUNTRY_RECORD)
    assert result is not None
    assert result["region"] == "Middle East"
    assert result["in_core_mandate"] is False
    print("✓ test_extended_monitoring_country passed")


def test_unknown_country_falls_back_to_global():
    result = normalize_worldbank_record(UNKNOWN_COUNTRY_RECORD)
    assert result is not None
    assert result["region"] == "Global / Other Monitoring"
    assert result["in_core_mandate"] is False
    print("✓ test_unknown_country_falls_back_to_global passed")


def test_deterministic_id_generation():
    id1 = make_meridian_event_id("WorldBank", "NGA:NY.GDP.MKTP.KD.ZG:2025")
    id2 = make_meridian_event_id("WorldBank", "NGA:NY.GDP.MKTP.KD.ZG:2025")
    id3 = make_meridian_event_id("WorldBank", "NGA:NY.GDP.MKTP.KD.ZG:2024")
    assert id1 == id2
    assert id1 != id3
    print("✓ test_deterministic_id_generation passed")


def test_batch_normalization_skips_missing_values():
    batch = [GDP_RECORD, EXTENDED_COUNTRY_RECORD, MISSING_VALUE_RECORD]
    results = normalize_batch(batch)
    assert len(results) == 2
    print(f"✓ test_batch_normalization_skips_missing_values passed ({len(results)}/3 normalized)")


def test_raw_data_preserved_for_audit():
    result = normalize_worldbank_record(GDP_RECORD)
    assert result["raw_source_data"] == GDP_RECORD
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
