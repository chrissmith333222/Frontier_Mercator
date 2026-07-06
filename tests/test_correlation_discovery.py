"""
tests/test_correlation_discovery.py

Tests the correlation-discovery engine's statistical stages (panel
builder, Fisher p-value screen, lag alignment) plus the LLM curation
plumbing with a fake client -- no network or API key needed.

Usage:
    python -m pytest tests/test_correlation_discovery.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from scripts.analytics.correlation_discovery import (
    build_country_panel,
    scan_correlations,
    curate_insights,
    _fisher_p_value,
    MIN_MONTHS,
)


def _make_events(country: str, months: list[str], category: str, severity=None) -> list[dict]:
    return [
        {"country": country, "event_date": f"{m}-15", "event_category": category,
         "severity_score": severity, "in_core_mandate": True}
        for m in months
    ]


def test_fisher_p_value_small_for_strong_correlation_large_n():
    assert _fisher_p_value(0.8, 50) < 0.001
    assert _fisher_p_value(0.1, 20) > 0.5
    assert _fisher_p_value(0.9, 3) == 1.0  # degenerate n


def test_build_country_panel_counts_by_month():
    events = (
        _make_events("Kenya", ["2025-01", "2025-01", "2025-02"], "conflict", severity=6.0)
        + _make_events("Kenya", ["2025-01"], "investment")
        + _make_events("Ghana", ["2025-01"], "conflict", severity=3.0)  # other country excluded
    )
    df = pd.DataFrame(events)
    panel = build_country_panel(df, "Kenya")
    assert panel.loc["2025-01", "conflict_events"] == 2
    assert panel.loc["2025-02", "conflict_events"] == 1
    assert panel.loc["2025-01", "investment_events"] == 1
    assert panel.loc["2025-01", "mean_conflict_severity"] == 6.0


def test_scan_finds_planted_commodity_correlation():
    # Plant a strong correlation: conflict counts that track a fake
    # commodity series exactly over 24 months.
    rng = np.random.default_rng(7)
    months = [f"2024-{m:02d}" for m in range(1, 13)] + [f"2025-{m:02d}" for m in range(1, 13)]
    base = rng.normal(50, 15, size=24).clip(min=1)
    events = []
    for month, level in zip(months, base):
        events.extend(_make_events("Kenya", [month] * int(level // 10 + 1), "conflict", severity=5.0))
    df = pd.DataFrame(events)
    commodities = {"FakeMetal": {m: float(v) for m, v in zip(months, base)}}

    hits = scan_correlations(df, commodities)
    assert any(
        h["country"] == "Kenya" and h["series_y"] == "FakeMetal" and h["lag_months"] == 0
        for h in hits
    ), f"planted correlation not found; hits={hits}"


def test_scan_skips_countries_with_too_little_data():
    events = _make_events("Kenya", ["2025-01", "2025-02"], "conflict", severity=5.0)  # only 2 months
    df = pd.DataFrame(events)
    hits = scan_correlations(df, {"FakeMetal": {"2025-01": 10.0, "2025-02": 12.0}})
    assert hits == []


def test_scan_skips_unrest_family_tautologies():
    # conflict vs protest in the same country is trivially related --
    # the scan must not even test that pair.
    months = [f"2024-{m:02d}" for m in range(1, 13)] + [f"2025-{m:02d}" for m in range(1, 13)]
    events = []
    for i, month in enumerate(months):
        n = i + 1
        events.extend(_make_events("Kenya", [month] * n, "conflict", severity=5.0))
        events.extend(_make_events("Kenya", [month] * n, "protest_civil_unrest"))
    df = pd.DataFrame(events)
    hits = scan_correlations(df, {})
    assert not any(
        {h["series_x"], h["series_y"]} <= {"conflict_events", "protest_events", "political_violence_events", "mean_conflict_severity"}
        for h in hits
    )


class _FakeToolUseBlock:
    def __init__(self, tool_input):
        self.type = "tool_use"
        self.input = tool_input


class _FakeResponse:
    def __init__(self, tool_input):
        self.content = [_FakeToolUseBlock(tool_input)]


class _FakeClient:
    def __init__(self, tool_input):
        self.messages = type("M", (), {"create": lambda s, **kw: _FakeResponse(tool_input)})()


VALID_INSIGHT = {
    "headline": "Mozambique conflict severity tracks copper prices",
    "detail": "Rising copper prices coincide with intensified conflict in Mozambique's mining regions.",
    "caveat": "Global commodity cycles may drive both via export revenue, not a direct causal link.",
    "country": "Mozambique", "series_x": "mean_conflict_severity", "series_y": "Copper",
    "r": 0.703, "lag_months": 0, "n_months": 18,
}


def test_curate_insights_returns_structured_insights():
    client = _FakeClient({"insights": [VALID_INSIGHT]})
    result = curate_insights([{"country": "Mozambique", "series_x": "mean_conflict_severity",
                                "series_y": "Copper", "lag_months": 0, "r": 0.703,
                                "p_value": 0.0007, "n_months": 18}], client=client)
    assert len(result) == 1
    assert result[0]["headline"].startswith("Mozambique")


def test_curate_insights_empty_hits_skips_llm_call():
    assert curate_insights([], client=None) == []


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
