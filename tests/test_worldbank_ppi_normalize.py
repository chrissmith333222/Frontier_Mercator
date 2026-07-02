"""
tests/test_worldbank_ppi_normalize.py

Tests the World Bank PPI normalization logic against fixture data -- no
live download needed.

Usage:
    python -m pytest tests/test_worldbank_ppi_normalize.py -v
    (or, without pytest installed: python tests/test_worldbank_ppi_normalize.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingestion.worldbank_ppi_normalize import (
    normalize_ppi_record,
    normalize_batch,
    make_meridian_event_id,
)

KENYA_RECORD = {
    "ID": 123,
    "IY": 2015,
    "country": "Kenya",
    "Region": "SSA",
    "FCY": 2015,
    "type": "Greenfield project",
    "stype": "Build, operate, and transfer",
    "status_n": "Active",
    "sector": "Energy",
    "ssector": "Electricity",
    "investment": 225.0,
    "name": "Example Wind Farm",
}

BILLION_SCALE_RECORD = {
    "ID": 124,
    "IY": 2018,
    "country": "Brazil",
    "FCY": 2018,
    "type": "Concession",
    "status_n": "Active",
    "sector": "Transport",
    "ssector": "Airports",
    "investment": 3500.0,
    "name": "Example Airport Concession",
}

ALIAS_COUNTRY_RECORD = {
    "ID": 125,
    "IY": 2010,
    "country": "Congo, Dem. Rep.",
    "FCY": 2010,
    "type": "Greenfield project",
    "status_n": "Active",
    "sector": "ICT",
    "investment": 50.0,
    "name": "Example Telecom Project",
}

ACCENTED_COUNTRY_RECORD = {
    "ID": 126,
    "IY": 2012,
    "country": "Côte d'Ivoire",
    "FCY": 2012,
    "type": "Divestiture",
    "status_n": "Concluded",
    "sector": "Energy",
    "investment": 12.0,
    "name": "Example Divestiture",
}

NAN_INVESTMENT_RECORD = {
    "ID": 129,
    "IY": 2016,
    "country": "Kenya",
    "FCY": 2016,
    "type": "Concession",
    "status_n": "Active",
    "sector": "Water and Sanitation",
    "investment": float("nan"),
    "name": "Example NaN Amount Project",
}

NO_INVESTMENT_AMOUNT_RECORD = {
    "ID": 127,
    "IY": 1993,
    "country": "Russian Federation",
    "FCY": 1993,
    "type": "Divestiture",
    "status_n": "Active",
    "sector": "Energy",
    "investment": None,
    "name": "Example Legacy Divestiture",
}

SAME_ID_YEAR_TRANCHE_1 = {
    "ID": 200,
    "IY": 1994,
    "country": "Ivory Coast",
    "FCY": 1994,
    "type": "Greenfield project",
    "status_n": "Active",
    "sector": "Energy",
    "investment": 70.0,
    "name": "CIPREL",
    "_row_index": 300,
}

SAME_ID_YEAR_TRANCHE_2 = {
    "ID": 200,
    "IY": 1994,
    "country": "Ivory Coast",
    "FCY": 1994,
    "type": "Greenfield project",
    "status_n": "Active",
    "sector": "Energy",
    "investment": 105.6,
    "name": "CIPREL",
    "_row_index": 301,
}

NO_COUNTRY_RECORD = {
    "ID": 128,
    "IY": 2015,
    "country": "",
    "investment": 10.0,
}

NO_ID_RECORD = {
    "ID": None,
    "IY": 2015,
    "country": "Kenya",
    "investment": 10.0,
}


def test_record_normalizes_with_millions_formatting():
    result = normalize_ppi_record(KENYA_RECORD)
    assert result["source"] == "WorldBankPPI"
    assert result["country"] == "Kenya"
    assert result["iso3"] == "KEN"
    assert result["in_core_mandate"] is True
    assert result["event_category"] == "investment"
    assert result["event_date"] == "2015-01-01"
    assert "$225.0M" in result["narrative_summary"]
    print("✓ test_record_normalizes_with_millions_formatting passed")


def test_billion_scale_amount_formatted_in_billions():
    result = normalize_ppi_record(BILLION_SCALE_RECORD)
    assert "$3.50B" in result["narrative_summary"]
    print("✓ test_billion_scale_amount_formatted_in_billions passed")


def test_country_alias_resolves_to_canonical_name():
    result = normalize_ppi_record(ALIAS_COUNTRY_RECORD)
    assert result["country"] == "Democratic Republic of Congo"
    assert result["iso3"] == "COD"
    print("✓ test_country_alias_resolves_to_canonical_name passed")


def test_accented_country_name_resolves():
    result = normalize_ppi_record(ACCENTED_COUNTRY_RECORD)
    assert result["country"] == "Ivory Coast"
    assert result["iso3"] == "CIV"
    print("✓ test_accented_country_name_resolves passed")


def test_nan_investment_amount_handled_gracefully():
    result = normalize_ppi_record(NAN_INVESTMENT_RECORD)
    assert result is not None
    assert "amount undisclosed" in result["narrative_summary"]
    assert "$nan" not in result["narrative_summary"].lower()
    print("✓ test_nan_investment_amount_handled_gracefully passed")


def test_missing_investment_amount_handled_gracefully():
    result = normalize_ppi_record(NO_INVESTMENT_AMOUNT_RECORD)
    assert result is not None
    assert "amount undisclosed" in result["narrative_summary"]
    print("✓ test_missing_investment_amount_handled_gracefully passed")


def test_same_project_and_year_tranches_get_distinct_ids():
    result1 = normalize_ppi_record(SAME_ID_YEAR_TRANCHE_1)
    result2 = normalize_ppi_record(SAME_ID_YEAR_TRANCHE_2)
    assert result1 is not None and result2 is not None
    assert result1["meridian_event_id"] != result2["meridian_event_id"]
    assert result1["source_event_id"] != result2["source_event_id"]
    print("✓ test_same_project_and_year_tranches_get_distinct_ids passed")


def test_no_country_returns_none():
    result = normalize_ppi_record(NO_COUNTRY_RECORD)
    assert result is None
    print("✓ test_no_country_returns_none passed")


def test_no_project_id_returns_none():
    result = normalize_ppi_record(NO_ID_RECORD)
    assert result is None
    print("✓ test_no_project_id_returns_none passed")


def test_deterministic_id_generation():
    id1 = make_meridian_event_id("WorldBankPPI", "123:2015")
    id2 = make_meridian_event_id("WorldBankPPI", "123:2015")
    id3 = make_meridian_event_id("WorldBankPPI", "123:2007")
    assert id1 == id2
    assert id1 != id3
    print("✓ test_deterministic_id_generation passed")


def test_batch_normalization_skips_malformed():
    batch = [KENYA_RECORD, ALIAS_COUNTRY_RECORD, NO_COUNTRY_RECORD, NO_ID_RECORD]
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
