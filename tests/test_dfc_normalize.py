"""
tests/test_dfc_normalize.py

Tests the DFC normalization logic against fixture data -- no live
download needed.

Usage:
    python -m pytest tests/test_dfc_normalize.py -v
    (or, without pytest installed: python tests/test_dfc_normalize.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingestion.dfc_normalize import (
    normalize_dfc_record,
    normalize_batch,
    make_meridian_event_id,
)

KENYA_USD_RECORD = {
    "Fiscal Year": 2023,
    "Project Number": 9000123456,
    "Project Type": "DI",
    "Region": "Sub-Saharan Africa",
    "Country": "Kenya",
    "Department": "DFC",
    "Project Name": "SCALE-NonMSME- D. Light Limited",
    "Committed": 4_500_000,
    "NAICS Sector": "Finance and Insurance",
    "Project Description": "Off-grid solar financing.",
    "Project Profile URL": "https://www.dfc.gov/project/d-light",
    "Originating Agency": "DFC",
    "Support Type": "Direct Lending",
    "Currency": "USD",
}

LOCAL_CURRENCY_RECORD = {
    "Fiscal Year": 2022,
    "Project Number": 9000999999,
    "Project Type": "DI",
    "Country": "Kenya",
    "Project Name": "SCALE-NonMSME- Example Local Deal",
    "Committed": 4_500_000,
    "NAICS Sector": "Finance and Insurance",
    "Support Type": "Direct Lending",
    "Currency": "KES",
}

ALIAS_COUNTRY_RECORD = {
    "Fiscal Year": 2021,
    "Project Number": 9000111222,
    "Country": "Cote D'Ivoire",
    "Project Name": "Test Project",
    "Committed": 1_000_000,
    "Currency": "USD",
    "NAICS Sector": "Agriculture",
    "Support Type": "Guarantee",
}

REGIONAL_AGGREGATE_RECORD = {
    "Fiscal Year": 2020,
    "Project Number": 9000333444,
    "Country": "Africa Regional",
    "Project Name": "Regional Fund",
    "Committed": 10_000_000,
    "Currency": "USD",
    "NAICS Sector": "Finance and Insurance",
    "Support Type": "Equity",
}

NO_COUNTRY_RECORD = {
    "Fiscal Year": 2020,
    "Project Number": 9000555666,
    "Country": "",
    "Committed": 1000,
}

BAD_YEAR_RECORD = {
    "Fiscal Year": "TBD",
    "Project Number": 9000777888,
    "Country": "Ghana",
    "Committed": 1000,
}


def test_usd_record_normalizes_with_dollar_formatting():
    result = normalize_dfc_record(KENYA_USD_RECORD)
    assert result["source"] == "DFC"
    assert result["country"] == "Kenya"
    assert result["iso3"] == "KEN"
    assert result["in_core_mandate"] is True
    assert result["event_category"] == "investment"
    assert result["event_date"] == "2023-01-01"
    assert "$4.5M" in result["narrative_summary"]
    print("✓ test_usd_record_normalizes_with_dollar_formatting passed")


def test_non_usd_amount_not_mislabeled_as_dollars():
    result = normalize_dfc_record(LOCAL_CURRENCY_RECORD)
    assert "$" not in result["narrative_summary"]
    assert "KES" in result["narrative_summary"]
    print("✓ test_non_usd_amount_not_mislabeled_as_dollars passed")


def test_country_alias_resolves_to_canonical_name():
    result = normalize_dfc_record(ALIAS_COUNTRY_RECORD)
    assert result["country"] == "Ivory Coast"
    assert result["iso3"] == "CIV"
    print("✓ test_country_alias_resolves_to_canonical_name passed")


def test_regional_aggregate_falls_back_to_global_other():
    result = normalize_dfc_record(REGIONAL_AGGREGATE_RECORD)
    assert result is not None
    assert result["iso3"] is None
    assert result["region"] == "Global / Other Monitoring"
    assert result["in_core_mandate"] is False
    print("✓ test_regional_aggregate_falls_back_to_global_other passed")


def test_no_country_returns_none():
    result = normalize_dfc_record(NO_COUNTRY_RECORD)
    assert result is None
    print("✓ test_no_country_returns_none passed")


def test_bad_fiscal_year_returns_none():
    result = normalize_dfc_record(BAD_YEAR_RECORD)
    assert result is None
    print("✓ test_bad_fiscal_year_returns_none passed")


def test_deterministic_id_generation():
    id1 = make_meridian_event_id("DFC", "9000123456")
    id2 = make_meridian_event_id("DFC", "9000123456")
    id3 = make_meridian_event_id("DFC", "9000999999")
    assert id1 == id2
    assert id1 != id3
    print("✓ test_deterministic_id_generation passed")


def test_batch_normalization_skips_malformed():
    batch = [KENYA_USD_RECORD, LOCAL_CURRENCY_RECORD, NO_COUNTRY_RECORD, BAD_YEAR_RECORD]
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
