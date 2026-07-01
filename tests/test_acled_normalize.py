"""
meridian/tests/test_acled_normalize.py

Tests the ACLED normalization logic against fixture data — no live API calls,
no credentials needed. Run this to verify the schema mapping is correct after
any changes to acled_normalize.py.

Usage:
    python -m pytest tests/test_acled_normalize.py -v
    (or, without pytest installed: python tests/test_acled_normalize.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingestion.acled_normalize import (
    normalize_acled_event,
    normalize_batch,
    compute_severity_score,
    make_meridian_event_id,
)

# Sample raw ACLED record, shaped like real API output, used across tests.
SAMPLE_RAW_EVENT = {
    "event_id_cnty": "MLI12345",
    "event_date": "2026-06-15",
    "year": "2026",
    "event_type": "Battles",
    "country": "Mali",
    "iso3": "MLI",
    "admin1": "Gao",
    "latitude": "16.2667",
    "longitude": "-0.0500",
    "actor1": "JNIM: Group for Support of Islam and Muslims",
    "inter1": "Rebel group",
    "actor2": "Military Forces of Mali",
    "inter2": "State forces",
    "fatalities": "12",
    "notes": "On 15 June 2026, JNIM fighters clashed with Malian armed forces near Gao.",
    "source": "Reuters",
}

SAMPLE_PROTEST_EVENT = {
    "event_id_cnty": "COL98765",
    "event_date": "2026-05-01",
    "year": "2026",
    "event_type": "Protests",
    "country": "Colombia",
    "iso3": "COL",
    "admin1": "Bogota D.C.",
    "latitude": "4.7110",
    "longitude": "-74.0721",
    "actor1": "Protesters (Colombia)",
    "inter1": "Protesters",
    "actor2": "",
    "inter2": "",
    "fatalities": "0",
    "notes": "Labor union protest in central Bogota over pension reform.",
    "source": "El Tiempo",
}

MALFORMED_EVENT = {
    "event_id_cnty": "XXX00000",
    "event_date": "2026-01-01",
    "event_type": "Battles",
    "country": "Nowhereland",  # not in COUNTRY_TO_MERIDIAN_REGION — should still work, just flagged
    "latitude": "not-a-number",  # should be handled gracefully, not crash
    "longitude": "",
    "fatalities": "not-a-number",
}


def test_basic_field_mapping():
    result = normalize_acled_event(SAMPLE_RAW_EVENT)
    assert result["source"] == "ACLED"
    assert result["source_event_id"] == "MLI12345"
    assert result["country"] == "Mali"
    assert result["event_date"] == "2026-06-15"
    assert result["event_category"] == "conflict"
    assert result["event_subtype"] == "Battles"
    print("✓ test_basic_field_mapping passed")


def test_region_mapping():
    result = normalize_acled_event(SAMPLE_RAW_EVENT)
    assert result["region"] == "West Africa / Sahel"

    result2 = normalize_acled_event(SAMPLE_PROTEST_EVENT)
    assert result2["region"] == "Andean Region"
    print("✓ test_region_mapping passed")


def test_unmapped_country_returns_none():
    # "Nowhereland" is outside MERIDIAN's Africa/LatAm mandate, so the event
    # should be dropped (return None) rather than included with a placeholder
    # region — ACLED's API-side region filter isn't reliable, so this mandate
    # check is the real gate. See normalize_acled_event's docstring.
    result = normalize_acled_event(MALFORMED_EVENT)
    assert result is None
    print("✓ test_unmapped_country_returns_none passed")


def test_severity_scoring():
    battle_score = compute_severity_score(SAMPLE_RAW_EVENT)  # Battles, 12 fatalities
    protest_score = compute_severity_score(SAMPLE_PROTEST_EVENT)  # Protests, 0 fatalities

    assert battle_score > protest_score, "Battles with fatalities should score higher than peaceful protests"
    assert 0 <= battle_score <= 10
    assert 0 <= protest_score <= 10

    # Mass casualty event should approach but not exceed the cap
    mass_casualty = {**SAMPLE_RAW_EVENT, "fatalities": "500"}
    mass_score = compute_severity_score(mass_casualty)
    assert mass_score == 10.0
    print(f"✓ test_severity_scoring passed (battle={battle_score}, protest={protest_score}, mass={mass_score})")


def test_actor_extraction():
    result = normalize_acled_event(SAMPLE_RAW_EVENT)
    assert len(result["actors"]) == 2
    assert result["actors"][0]["name"] == "JNIM: Group for Support of Islam and Muslims"
    assert result["actors"][0]["type"] == "Rebel group"
    print("✓ test_actor_extraction passed")


def test_deterministic_id_generation():
    id1 = make_meridian_event_id("ACLED", "MLI12345")
    id2 = make_meridian_event_id("ACLED", "MLI12345")
    id3 = make_meridian_event_id("ACLED", "MLI99999")
    assert id1 == id2, "Same input should always produce the same ID (for dedup on re-runs)"
    assert id1 != id3, "Different inputs should produce different IDs"
    print("✓ test_deterministic_id_generation passed")


def test_batch_normalization_skips_bad_records_gracefully():
    truly_broken = {"this_is_not": "a valid ACLED record at all"}
    batch = [SAMPLE_RAW_EVENT, SAMPLE_PROTEST_EVENT, truly_broken]
    results = normalize_batch(batch)
    # Even the "truly broken" record should normalize (everything is .get() with
    # defaults), but this test documents the expected graceful-degradation behavior
    assert len(results) >= 2
    print(f"✓ test_batch_normalization_skips_bad_records_gracefully passed ({len(results)}/3 normalized)")


def test_raw_data_preserved_for_audit():
    result = normalize_acled_event(SAMPLE_RAW_EVENT)
    assert result["raw_source_data"] == SAMPLE_RAW_EVENT
    print("✓ test_raw_data_preserved_for_audit passed")


if __name__ == "__main__":
    # Allows running without pytest installed
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
