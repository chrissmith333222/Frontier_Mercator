"""
tests/test_unosat_normalize.py

Tests the UNOSAT normalization logic against fixture data -- no live
HDX fetch needed.

Usage:
    python -m pytest tests/test_unosat_normalize.py -v
    (or, without pytest installed: python tests/test_unosat_normalize.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingestion.unosat_normalize import (
    normalize_unosat_record,
    normalize_batch,
    make_meridian_event_id,
)

VENEZUELA_EARTHQUAKE_RECORD = {
    "name": "unosat-live-webmap-m-7-5-caracas-earthquake-24-june-2026",
    "title": "UNOSAT Live webmap - M 7.5 - Caracas earthquake (24 June 2026)",
    "notes": "UNOSAT code: EQ20260625VEN, GDACS ID: 1548377\nThis application provides geospatial information...",
    "dataset_date": "[2026-06-25T00:00:00 TO 2026-06-25T23:59:59]",
    "dataset_source": "UN Operational Satellite Applications Programme (UNOSAT)",
    "groups": [{"id": "ven", "display_name": "Venezuela (Bolivarian Republic of)"}],
    "resources": [
        {"format": "Geodatabase", "download_url": "https://unosat.org/static/.../gdb.zip"},
        {"format": "PDF", "download_url": "https://unosat.org/static/.../report.pdf"},
    ],
}

NO_GROUPS_RECORD = {
    "name": "unosat-global-methodology-note",
    "title": "UNOSAT Global Flood Detection Methodology",
    "notes": "A general note on methodology, not tied to one country.",
    "dataset_date": "[2024-01-15T00:00:00 TO 2024-01-15T23:59:59]",
    "dataset_source": "UNOSAT",
    "groups": [],
    "resources": [],
}

UNKNOWN_GROUP_RECORD = {
    "name": "unosat-kosovo-product",
    "title": "Some Kosovo Product",
    "notes": "Kosovo isn't in the ISO3166 country table.",
    "dataset_date": "[2023-05-01T00:00:00 TO 2023-05-01T23:59:59]",
    "groups": [{"id": "xkx", "display_name": "Kosovo"}],
    "resources": [],
}

NO_TITLE_RECORD = {
    "name": "some-name",
    "title": "",
    "dataset_date": "[2024-01-15T00:00:00 TO 2024-01-15T23:59:59]",
}

BAD_DATE_RECORD = {
    "name": "some-name",
    "title": "Some Title",
    "dataset_date": "not a date range",
}

NO_DATE_RECORD = {
    "name": "some-name",
    "title": "Some Title",
    "dataset_date": None,
}


def test_resolves_country_from_hdx_group():
    result = normalize_unosat_record(VENEZUELA_EARTHQUAKE_RECORD)
    assert result["source"] == "UNOSAT"
    assert result["country"] == "Venezuela"
    assert result["iso3"] == "VEN"
    assert result["in_core_mandate"] is True
    assert result["event_category"] == "humanitarian"
    assert result["event_date"] == "2026-06-25"
    print("✓ test_resolves_country_from_hdx_group passed")


def test_prefers_pdf_resource_over_geodatabase():
    result = normalize_unosat_record(VENEZUELA_EARTHQUAKE_RECORD)
    assert result["source_url"] == "https://unosat.org/static/.../report.pdf"
    print("✓ test_prefers_pdf_resource_over_geodatabase passed")


def test_no_groups_falls_back_to_global():
    result = normalize_unosat_record(NO_GROUPS_RECORD)
    assert result is not None
    assert result["country"] == "Global"
    assert result["iso3"] is None
    assert result["in_core_mandate"] is False
    print("✓ test_no_groups_falls_back_to_global passed")


def test_unmapped_group_falls_back_to_global_other():
    result = normalize_unosat_record(UNKNOWN_GROUP_RECORD)
    assert result is not None
    assert result["iso3"] is None
    assert result["country"] == "Kosovo"
    assert result["in_core_mandate"] is False
    print("✓ test_unmapped_group_falls_back_to_global_other passed")


def test_no_title_returns_none():
    result = normalize_unosat_record(NO_TITLE_RECORD)
    assert result is None
    print("✓ test_no_title_returns_none passed")


def test_bad_date_returns_none():
    result = normalize_unosat_record(BAD_DATE_RECORD)
    assert result is None
    print("✓ test_bad_date_returns_none passed")


def test_no_date_returns_none():
    result = normalize_unosat_record(NO_DATE_RECORD)
    assert result is None
    print("✓ test_no_date_returns_none passed")


def test_deterministic_id_generation():
    id1 = make_meridian_event_id("UNOSAT", "some-dataset")
    id2 = make_meridian_event_id("UNOSAT", "some-dataset")
    id3 = make_meridian_event_id("UNOSAT", "other-dataset")
    assert id1 == id2
    assert id1 != id3
    print("✓ test_deterministic_id_generation passed")


def test_batch_normalization_skips_malformed():
    batch = [VENEZUELA_EARTHQUAKE_RECORD, NO_GROUPS_RECORD, NO_TITLE_RECORD, BAD_DATE_RECORD]
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
