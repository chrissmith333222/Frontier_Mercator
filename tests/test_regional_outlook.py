"""
tests/test_regional_outlook.py

Tests the Regional Economic Outlook's deterministic data-assembly logic
(macro-reading extraction, region grouping, graceful-empty load) and the
PDF renderer -- no network or API calls.

Usage:
    python -m pytest tests/test_regional_outlook.py -v
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analytics.regional_outlook import (
    _core_regions, _latest_macro_by_country, load_regional_outlook,
)
from scripts.reports.pdf_report import generate_regional_outlook_pdf

FIXTURE_EVENTS = [
    {"country": "Kenya", "event_category": "economic_indicator", "event_subtype": "NY.GDP.MKTP.KD.ZG",
     "event_date": "2025-12-31", "source": "WorldBank",
     "narrative_summary": "GDP growth (annual %): 4.5% (2025)"},
    {"country": "Kenya", "event_category": "economic_indicator", "event_subtype": "NY.GDP.MKTP.KD.ZG",
     "event_date": "2024-12-31", "source": "WorldBank",
     "narrative_summary": "GDP growth (annual %): 5.0% (2024)"},  # older -- must lose
    {"country": "Kenya", "event_category": "economic_indicator", "event_subtype": "SP.POP.TOTL",
     "event_date": "2025-12-31", "source": "WorldBank",
     "narrative_summary": "Population, total: 43.8M (2025)"},  # not a quoted macro code -- excluded
    {"country": "Ghana", "event_category": "conflict", "event_subtype": "battle",
     "event_date": "2025-12-31", "source": "ACLED", "narrative_summary": "irrelevant"},
]


def test_core_regions_cover_all_mandate_countries():
    regions = _core_regions()
    assert "West Africa / Sahel" in regions
    total = sum(len(countries) for countries in regions.values())
    assert total == 69
    print("✓ test_core_regions_cover_all_mandate_countries passed")


def test_latest_macro_keeps_newest_reading_only():
    result = _latest_macro_by_country(FIXTURE_EVENTS, {"Kenya"})
    assert result["Kenya"]["GDP growth"] == "4.5% (2025) (2025, WorldBank)"
    assert "Population" not in str(result["Kenya"].keys())
    print("✓ test_latest_macro_keeps_newest_reading_only passed")


def test_latest_macro_ignores_out_of_scope_countries():
    result = _latest_macro_by_country(FIXTURE_EVENTS, {"Ghana"})
    assert result == {}  # Ghana only has a conflict event, no macro readings
    print("✓ test_latest_macro_ignores_out_of_scope_countries passed")


def test_load_returns_empty_when_missing(tmp_path):
    assert load_regional_outlook(tmp_path / "nope.json") == {}
    print("✓ test_load_returns_empty_when_missing passed")


def test_pdf_renders_from_outlook_fixture():
    outlook = {
        "generated_at": "2026-07-16T12:00:00+00:00",
        "regions": {
            "East Africa / Horn": {
                "regional_narrative": "Growth holds firm.\n\nCapital keeps flowing.",
                "opportunities": [{
                    "title": "Logistics corridors",
                    "narrative": "Port throughput is rising with Kenya GDP growth at 4.5% (IMF, 2026).",
                    "key_data_points": ["Kenya GDP growth 4.5% (IMF, 2026)", "Mombasa TEU +8% (UNCTAD)"],
                }],
                "risk_outlook": "Election-cycle unrest is the watch item.",
            },
        },
    }
    pdf_bytes = generate_regional_outlook_pdf(outlook)
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 2000  # a real one-region render is ~3KB
    print("✓ test_pdf_renders_from_outlook_fixture passed")


def test_pdf_renders_even_when_sections_sparse():
    outlook = {"generated_at": "2026-07-16T12:00:00+00:00",
               "regions": {"Mexico": {"regional_narrative": "One paragraph only.",
                                        "opportunities": [], "risk_outlook": ""}}}
    pdf_bytes = generate_regional_outlook_pdf(outlook)
    assert pdf_bytes[:5] == b"%PDF-"
    print("✓ test_pdf_renders_even_when_sections_sparse passed")


if __name__ == "__main__":
    import tempfile
    test_functions = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"Running {len(test_functions)} tests...\n")
    failures = 0
    for test_fn in test_functions:
        try:
            if "tmp_path" in test_fn.__code__.co_varnames[:test_fn.__code__.co_argcount]:
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
