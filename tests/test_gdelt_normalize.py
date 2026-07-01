"""
meridian/tests/test_gdelt_normalize.py

Tests the GDELT normalization logic against fixture data — no live API calls
needed. Run this to verify the schema mapping after any changes to
gdelt_normalize.py.

Usage:
    python -m pytest tests/test_gdelt_normalize.py -v
    (or, without pytest installed: python tests/test_gdelt_normalize.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingestion.gdelt_normalize import (
    normalize_gdelt_event,
    normalize_batch,
    compute_severity_score,
    make_meridian_event_id,
)

# Sample raw GDELT record shaped like real 2.0 export output (fight event, Mali).
SAMPLE_FIGHT_EVENT = {
    "GLOBALEVENTID": "1234567890",
    "SQLDATE": "20260615",
    "Actor1Name": "JNIM",
    "Actor1Type1Code": "REB",
    "Actor2Name": "MALI",
    "Actor2Type1Code": "GOV",
    "EventCode": "193",
    "EventRootCode": "19",
    "GoldsteinScale": "-9.0",
    "ActionGeo_Type": "3",
    "ActionGeo_FullName": "Gao, Mali",
    "ActionGeo_CountryCode": "ML",
    "ActionGeo_ADM1Code": "ML05",
    "ActionGeo_Lat": "16.2667",
    "ActionGeo_Long": "-0.0500",
    "SOURCEURL": "https://example.com/article",
}

# Sample protest event, Colombia — lower severity, non-mandate-adjacent check.
SAMPLE_PROTEST_EVENT = {
    "GLOBALEVENTID": "9876543210",
    "SQLDATE": "20260501",
    "Actor1Name": "PROTESTERS",
    "Actor1Type1Code": "",
    "Actor2Name": "",
    "Actor2Type1Code": "",
    "EventCode": "1411",
    "EventRootCode": "14",
    "GoldsteinScale": "-6.5",
    "ActionGeo_Type": "3",
    "ActionGeo_FullName": "Bogota, Colombia",
    "ActionGeo_CountryCode": "CO",
    "ActionGeo_ADM1Code": "CO03",
    "ActionGeo_Lat": "4.7110",
    "ActionGeo_Long": "-74.0721",
    "SOURCEURL": "https://example.com/article2",
}

NON_MANDATE_EVENT = {
    "GLOBALEVENTID": "1111111111",
    "SQLDATE": "20260101",
    "EventRootCode": "19",
    "GoldsteinScale": "-10.0",
    "ActionGeo_CountryCode": "US",  # outside MERIDIAN's Africa/LatAm mandate
}

MALFORMED_EVENT = {
    "GLOBALEVENTID": "2222222222",
    "SQLDATE": "not-a-date",
    "EventRootCode": "19",
    "ActionGeo_CountryCode": "ML",
    "ActionGeo_Lat": "not-a-number",
    "ActionGeo_Long": "",
}


def test_basic_field_mapping():
    result = normalize_gdelt_event(SAMPLE_FIGHT_EVENT)
    assert result["source"] == "GDELT"
    assert result["source_event_id"] == "1234567890"
    assert result["country"] == "Mali"
    assert result["iso3"] == "MLI"
    assert result["event_date"] == "2026-06-15"
    assert result["event_category"] == "conflict"
    print("✓ test_basic_field_mapping passed")


def test_region_mapping():
    result = normalize_gdelt_event(SAMPLE_FIGHT_EVENT)
    assert result["region"] == "West Africa / Sahel"

    result2 = normalize_gdelt_event(SAMPLE_PROTEST_EVENT)
    assert result2["region"] == "Andean Region"
    assert result2["event_category"] == "protest_civil_unrest"
    print("✓ test_region_mapping passed")


def test_non_mandate_country_returns_none():
    result = normalize_gdelt_event(NON_MANDATE_EVENT)
    assert result is None, "Events outside MERIDIAN's Africa/LatAm mandate should not normalize"
    print("✓ test_non_mandate_country_returns_none passed")


def test_malformed_record_handled_gracefully():
    result = normalize_gdelt_event(MALFORMED_EVENT)
    assert result is not None
    assert result["event_date"] is None
    assert result["latitude"] is None
    assert result["longitude"] is None
    print("✓ test_malformed_record_handled_gracefully passed")


def test_severity_scoring():
    fight_score = compute_severity_score(SAMPLE_FIGHT_EVENT)     # Fight, Goldstein -9.0
    protest_score = compute_severity_score(SAMPLE_PROTEST_EVENT)  # Protest, Goldstein -6.5

    assert fight_score > protest_score, "Violent conflict should score higher than protest"
    assert 0 <= fight_score <= 10
    assert 0 <= protest_score <= 10

    max_conflict = {**SAMPLE_FIGHT_EVENT, "EventRootCode": "20", "GoldsteinScale": "-10.0"}
    max_score = compute_severity_score(max_conflict)
    assert max_score == 10.0
    print(f"✓ test_severity_scoring passed (fight={fight_score}, protest={protest_score}, max={max_score})")


def test_actor_extraction():
    result = normalize_gdelt_event(SAMPLE_FIGHT_EVENT)
    assert len(result["actors"]) == 2
    assert result["actors"][0]["name"] == "JNIM"
    assert result["actors"][0]["type"] == "REB"
    print("✓ test_actor_extraction passed")


def test_deterministic_id_generation():
    id1 = make_meridian_event_id("GDELT", "1234567890")
    id2 = make_meridian_event_id("GDELT", "1234567890")
    id3 = make_meridian_event_id("GDELT", "9999999999")
    assert id1 == id2
    assert id1 != id3
    print("✓ test_deterministic_id_generation passed")


def test_batch_normalization_filters_and_skips():
    batch = [SAMPLE_FIGHT_EVENT, SAMPLE_PROTEST_EVENT, NON_MANDATE_EVENT]
    results = normalize_batch(batch)
    assert len(results) == 2, "Non-mandate-country event should be filtered out, not error"
    print(f"✓ test_batch_normalization_filters_and_skips passed ({len(results)}/3 normalized)")


def test_raw_data_preserved_for_audit():
    result = normalize_gdelt_event(SAMPLE_FIGHT_EVENT)
    assert result["raw_source_data"] == SAMPLE_FIGHT_EVENT
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
