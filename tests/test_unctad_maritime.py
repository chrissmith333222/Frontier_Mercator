"""
tests/test_unctad_maritime.py

Tests the UNCTAD maritime ingestion's data logic -- country-name
resolution (aliases, aggregates), value parsing, and the graceful-empty
load path. No network calls: _fetch_csv_rows is stubbed with fixture rows.

Usage:
    python -m pytest tests/test_unctad_maritime.py -v
"""

import sys
import json
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.ingestion.unctad_maritime_fetch as maritime


def test_resolve_country_passes_tracked_names_through():
    assert maritime._resolve_country("Kenya") == "Kenya"
    print("✓ test_resolve_country_passes_tracked_names_through passed")


def test_resolve_country_applies_unctad_aliases():
    assert maritime._resolve_country("Côte d'Ivoire") == "Ivory Coast"
    assert maritime._resolve_country("Tanzania, United Republic of") == "Tanzania"
    assert maritime._resolve_country("Bolivia (Plurinational State of)") == "Bolivia"
    print("✓ test_resolve_country_applies_unctad_aliases passed")


def test_resolve_country_drops_aggregates_and_untracked():
    assert maritime._resolve_country("World") is None
    assert maritime._resolve_country("Northern Africa") is None
    assert maritime._resolve_country("American Samoa") is None
    print("✓ test_resolve_country_drops_aggregates_and_untracked passed")


def test_fetch_lsci_shapes_series_and_normalizes_quarters():
    fixture_rows = [
        {"Quarter": "2024Q01", "Economy Label": "Kenya", "Index (Average Q1 2023 = 100)": "75.5"},
        {"Quarter": "2024Q02", "Economy Label": "Kenya", "Index (Average Q1 2023 = 100)": "76.1"},
        {"Quarter": "2024Q01", "Economy Label": "World", "Index (Average Q1 2023 = 100)": "100.0"},
        {"Quarter": "2024Q01", "Economy Label": "Ghana", "Index (Average Q1 2023 = 100)": ""},
    ]
    with patch.object(maritime, "_fetch_csv_rows", return_value=fixture_rows):
        result = maritime.fetch_lsci()
    assert result == {"Kenya": {"2024Q1": 75.5, "2024Q2": 76.1}}
    print("✓ test_fetch_lsci_shapes_series_and_normalizes_quarters passed")


def test_fetch_port_calls_keeps_all_ships_only():
    # "Russian Federation" also exercises the alias path -- UNCTAD's port
    # calls dataset only covers ~23 major economies, and of those only the
    # extended-monitoring ones (Russia, Turkey, European states) are in the
    # platform's tracked set. China/US/East Asia are NOT tracked countries.
    fixture_rows = [
        {"Year": "2023", "Economy Label": "Russian Federation", "CommercialMarket Label": "All ships",
         "Median time in port (days)": "1.05", "Average age of vessels (years)": "15"},
        {"Year": "2023", "Economy Label": "Russian Federation", "CommercialMarket Label": "Container ships",
         "Median time in port (days)": "0.8", "Average age of vessels (years)": "12"},
    ]
    with patch.object(maritime, "_fetch_csv_rows", return_value=fixture_rows):
        result = maritime.fetch_port_calls()
    assert result == {"Russia": {"2023": {"median_time_in_port_days": 1.05, "avg_vessel_age_years": 15.0}}}
    print("✓ test_fetch_port_calls_keeps_all_ships_only passed")


def test_fetch_seaborne_trade_keeps_totals_only():
    fixture_rows = [
        {"Year": "2024", "Economy Label": "Kenya", "CargoType Label": "Total goods loaded",
         "Metric tons in thousands": "3125.644"},
        {"Year": "2024", "Economy Label": "Kenya", "CargoType Label": "Total goods discharged",
         "Metric tons in thousands": "13464.15"},
        {"Year": "2024", "Economy Label": "Kenya", "CargoType Label": "Crude oil loaded",
         "Metric tons in thousands": "50.0"},
    ]
    with patch.object(maritime, "_fetch_csv_rows", return_value=fixture_rows):
        result = maritime.fetch_seaborne_trade()
    assert result == {"Kenya": {"2024": {"loaded_kt": 3125.644, "discharged_kt": 13464.15}}}
    print("✓ test_fetch_seaborne_trade_keeps_totals_only passed")


def test_load_maritime_stats_returns_empty_when_missing(tmp_path):
    assert maritime.load_maritime_stats(tmp_path / "nope.json") == {}
    print("✓ test_load_maritime_stats_returns_empty_when_missing passed")


def test_load_maritime_stats_reads_cached_file(tmp_path):
    path = tmp_path / "maritime_stats.json"
    path.write_text(json.dumps({"lsci": {"Kenya": {"2024Q1": 75.5}}}), encoding="utf-8")
    assert maritime.load_maritime_stats(path)["lsci"]["Kenya"]["2024Q1"] == 75.5
    print("✓ test_load_maritime_stats_reads_cached_file passed")


if __name__ == "__main__":
    test_functions = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"Running {len(test_functions)} tests...\n")
    failures = 0
    for test_fn in test_functions:
        try:
            if "tmp_path" in test_fn.__code__.co_varnames[:test_fn.__code__.co_argcount]:
                import tempfile
                with tempfile.TemporaryDirectory() as td:
                    test_fn(Path(td))
            else:
                test_fn()
        except AssertionError as e:
            failures += 1
            print(f"✗ {test_fn.__name__} FAILED: {e}")
    print(f"\n{len(test_functions) - failures}/{len(test_functions)} tests passed.")
    if failures:
        sys.exit(1)
