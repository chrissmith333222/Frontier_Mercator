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




def test_single_region_pdf_renders_with_charts():
    """Standalone per-region outlook: narrative + charts from real-shaped
    fixture data (GDP/inflation readings for 3 countries, 12 months of
    conflict events, investment mix) -- all four chart types exercised."""
    import pandas as pd
    from scripts.reports.pdf_report import generate_single_region_outlook_pdf

    rows = []
    for country, gdp, cpi in [("Kenya", 4.5, 6.4), ("Tanzania", 5.2, 3.1), ("Uganda", 6.0, 4.0)]:
        rows.append({"region": "East Africa / Horn", "country": country,
                      "event_category": "economic_indicator", "event_subtype": "NY.GDP.MKTP.KD.ZG",
                      "event_date": "2025-12-31", "source": "WorldBank",
                      "narrative_summary": f"GDP growth (annual %): {gdp}% (2025)"})
        rows.append({"region": "East Africa / Horn", "country": country,
                      "event_category": "economic_indicator", "event_subtype": "FP.CPI.TOTL.ZG",
                      "event_date": "2025-12-31", "source": "WorldBank",
                      "narrative_summary": f"Inflation, consumer prices (annual %): {cpi}% (2025)"})
    for month in range(1, 13):
        for _ in range(3):
            rows.append({"region": "East Africa / Horn", "country": "Kenya",
                          "event_category": "conflict", "event_subtype": "battle",
                          "event_date": f"2025-{month:02d}-15", "source": "ACLED",
                          "narrative_summary": "clash"})
    for source in ["AidData"] * 5 + ["DFC"] * 3 + ["WorldBankPPI"] * 2:
        rows.append({"region": "East Africa / Horn", "country": "Kenya",
                      "event_category": "investment", "event_subtype": "energy",
                      "event_date": "2024-01-01", "source": source,
                      "narrative_summary": "project"})
    df = pd.DataFrame(rows)

    section = {
        "regional_narrative": "Growth holds.\n\nCapital flows continue.",
        "opportunities": [{
            "title": "Logistics", "narrative": "Ports rising.",
            "key_data_points": ["Kenya GDP 4.5% (IMF)"],
            "timing_case": "As of Q3 2026, port financing reaches close this quarter.",
            "expression": [{"ticker": "SEA", "name": "U.S. Global Sea to Sky Cargo ETF",
                             "note": "shipping exposure, diluted"}],
        }],
        "risk_outlook": "Election unrest is the watch item.",
        "visuals": [
            {"takeaway_headline": "Uganda leads the region's growth pack",
             "metric": "gdp_growth", "highlight_country": "Uganda", "section": "narrative"},
            {"takeaway_headline": "Cocoa prices are still working for exporters",
             "metric": "commodity_trend", "commodity": "Cocoa", "section": "risk"},
        ],
    }
    # Both nominated visuals must actually render from this fixture data
    # (asserted directly -- byte size is a poor proxy for chart presence).
    from scripts.reports.outlook_charts import render_nominated_visual
    for visual in section["visuals"]:
        assert render_nominated_visual(visual, df) is not None, visual["metric"]

    pdf = generate_single_region_outlook_pdf("East Africa / Horn", section,
                                              "2026-07-16T12:00:00+00:00", df)
    assert pdf[:5] == b"%PDF-"
    print("ok test_single_region_pdf_renders_with_charts")


def test_nominated_visuals_render_or_skip_on_data():
    import pandas as pd
    from scripts.reports.outlook_charts import render_nominated_visual
    # Sparse region: a one-country GDP bar can't render (needs >= 2), an
    # unknown metric never renders -- silence, not empty axes.
    df = pd.DataFrame([{"region": "Mexico", "country": "Mexico",
                         "event_category": "economic_indicator", "event_subtype": "NY.GDP.MKTP.KD.ZG",
                         "event_date": "2025-12-31", "source": "WorldBank",
                         "narrative_summary": "GDP growth (annual %): 1.9% (2025)"}])
    assert render_nominated_visual(
        {"takeaway_headline": "H", "metric": "gdp_growth", "section": "narrative"}, df) is None
    assert render_nominated_visual(
        {"takeaway_headline": "H", "metric": "not_a_metric", "section": "narrative"}, df) is None
    # A missing headline is also a skip -- the title IS the takeaway.
    assert render_nominated_visual({"metric": "gdp_growth", "section": "narrative"}, df) is None
    print("ok test_nominated_visuals_render_or_skip_on_data")


def test_expression_tickers_validated_against_universe():
    from scripts.analytics.regional_outlook import _coerce_opportunities
    instruments = {"COPX": ("Global X Copper Miners ETF", "sector_etf", "copper")}
    section = {
        "opportunities": [{"title": "T", "narrative": "N", "key_data_points": [],
                            "timing_case": "now",
                            "expression": [{"ticker": "COPX", "note": "fits"},
                                            {"ticker": "FAKE", "note": "hallucinated"}]}],
        "visuals": [],
    }
    result = _coerce_opportunities(section, instruments)
    expr = result["opportunities"][0]["expression"]
    assert len(expr) == 1
    assert expr[0]["ticker"] == "COPX"
    assert expr[0]["name"] == "Global X Copper Miners ETF"
    print("ok test_expression_tickers_validated_against_universe")


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
