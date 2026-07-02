"""
tests/test_aiddata_normalize.py

Tests the AidData GCDF normalization logic against fixture data shaped like
real dataset rows -- no live download needed.

Usage:
    python -m pytest tests/test_aiddata_normalize.py -v
    (or, without pytest installed: python tests/test_aiddata_normalize.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingestion.aiddata_normalize import (
    normalize_aiddata_record,
    normalize_batch,
    make_meridian_event_id,
)

# Shaped like a real GCDF 3.0 row (trimmed to the fields normalize.py reads).
NIGERIA_LOAN_RECORD = {
    "AidData Record ID": 89451,
    "Recipient": "Nigeria",
    "Recipient ISO-3": "NGA",
    "Commitment Year": 2021,
    "Commitment Date (MM/DD/YYYY)": "2021-01-01 00:00:00",
    "Title": "CBN makes RMB 3.3106 billion drawdown under currency swap agreement with PBOC in 2021",
    "Flow Type": "Loan",
    "Sector Name": "BANKING AND FINANCIAL SERVICES",
    "Status": "Completion",
    "Amount (Nominal USD)": 513271317.83,
    "Funding Agencies": "People's Bank of China (PBC)",
    "Direct Receiving Agencies": "Central Bank of Nigeria (CBN)",
    "Source URLs": "https://www.imf.org/example.pdf |https://example.com/other.pdf",
}

EXTENDED_COUNTRY_RECORD = {
    "AidData Record ID": 12345,
    "Recipient": "Pakistan",
    "Recipient ISO-3": "PAK",
    "Commitment Year": 2019,
    "Commitment Date (MM/DD/YYYY)": None,
    "Title": "Port infrastructure loan",
    "Flow Type": "Loan",
    "Sector Name": "TRANSPORT AND STORAGE",
    "Status": "Implementation",
    "Amount (Nominal USD)": 2_500_000_000,
    "Funding Agencies": "China Development Bank",
    "Direct Receiving Agencies": None,
    "Source URLs": None,
}

NO_YEAR_RECORD = {
    "AidData Record ID": 99999,
    "Recipient": "Kenya",
    "Recipient ISO-3": "KEN",
    "Commitment Year": None,
    "Title": "Malformed record",
}

NO_ID_RECORD = {
    "AidData Record ID": None,
    "Recipient": "Kenya",
    "Recipient ISO-3": "KEN",
    "Commitment Year": 2020,
}


def test_basic_field_mapping():
    result = normalize_aiddata_record(NIGERIA_LOAN_RECORD)
    assert result["source"] == "AidData"
    assert result["country"] == "Nigeria"
    assert result["iso3"] == "NGA"
    assert result["event_date"] == "2021-01-01"
    assert result["event_category"] == "investment"
    assert result["in_core_mandate"] is True
    assert result["region"] == "West Africa / Sahel"
    assert "$513.3M" in result["narrative_summary"]
    print("✓ test_basic_field_mapping passed")


def test_falls_back_to_commitment_year_when_no_date():
    result = normalize_aiddata_record(EXTENDED_COUNTRY_RECORD)
    assert result is not None
    assert result["event_date"] == "2019-01-01"
    assert result["region"] == "Middle East"  # Pakistan is in the extended list
    assert result["in_core_mandate"] is False
    assert "$2.50B" in result["narrative_summary"]
    print("✓ test_falls_back_to_commitment_year_when_no_date passed")


def test_actors_extracted():
    result = normalize_aiddata_record(NIGERIA_LOAN_RECORD)
    names = [a["name"] for a in result["actors"]]
    assert "People's Bank of China (PBC)" in names
    assert "Central Bank of Nigeria (CBN)" in names
    print("✓ test_actors_extracted passed")


def test_source_url_takes_first_of_list():
    result = normalize_aiddata_record(NIGERIA_LOAN_RECORD)
    assert result["source_url"] == "https://www.imf.org/example.pdf"
    print("✓ test_source_url_takes_first_of_list passed")


def test_missing_year_returns_none():
    result = normalize_aiddata_record(NO_YEAR_RECORD)
    assert result is None
    print("✓ test_missing_year_returns_none passed")


def test_missing_id_returns_none():
    result = normalize_aiddata_record(NO_ID_RECORD)
    assert result is None
    print("✓ test_missing_id_returns_none passed")


def test_deterministic_id_generation():
    id1 = make_meridian_event_id("AidData", "89451")
    id2 = make_meridian_event_id("AidData", "89451")
    id3 = make_meridian_event_id("AidData", "89452")
    assert id1 == id2
    assert id1 != id3
    print("✓ test_deterministic_id_generation passed")


def test_batch_normalization_skips_malformed():
    batch = [NIGERIA_LOAN_RECORD, EXTENDED_COUNTRY_RECORD, NO_YEAR_RECORD, NO_ID_RECORD]
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
