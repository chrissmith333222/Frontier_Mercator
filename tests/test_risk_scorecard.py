"""
tests/test_risk_scorecard.py

Tests the risk scorecard's threshold functions and full country-scorecard
computation against a small temporary knowledge base -- no real API key
or knowledge base needed.

Usage:
    python -m pytest tests/test_risk_scorecard.py -v
"""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.knowledge.build_knowledge_base import build_knowledge_base
from scripts.analytics.risk_scorecard import (
    build_country_scorecard,
    _inflation_risk,
    _current_account_risk,
    _debt_risk,
    _growth_risk,
)

TODAY = "2026-06-01"


def _make_temp_kb(events: list[dict]) -> Path:
    tmp_dir = Path(tempfile.mkdtemp())
    dataset_path = tmp_dir / "merged_dataset.json"
    dataset_path.write_text(json.dumps(events), encoding="utf-8")
    db_path = tmp_dir / "meridian.db"
    build_knowledge_base(merged_dataset_path=dataset_path, db_path=db_path)
    return db_path


def _conflict_event(event_id, iso3, country, date, severity):
    return {
        "meridian_event_id": event_id, "source": "ACLED", "source_event_id": event_id,
        "event_date": date, "country": country, "iso3": iso3, "admin1": None,
        "region": "East Africa / Horn", "in_core_mandate": True,
        "event_category": "conflict", "event_subtype": "Battles", "actors": [],
        "fatalities": 2, "severity_score": severity,
        "narrative_summary": "Clashes reported.", "source_url": None,
        "ingested_at": "2026-06-01T00:00:00Z",
    }


def _indicator_event(event_id, iso3, country, date, subtype, summary):
    return {
        "meridian_event_id": event_id, "source": "WorldBank", "source_event_id": event_id,
        "event_date": date, "country": country, "iso3": iso3, "admin1": None,
        "region": "East Africa / Horn", "in_core_mandate": True,
        "event_category": "economic_indicator", "event_subtype": subtype, "actors": [],
        "fatalities": None, "severity_score": None,
        "narrative_summary": summary, "source_url": None,
        "ingested_at": "2026-06-01T00:00:00Z",
    }


def test_inflation_risk_thresholds():
    assert _inflation_risk(2.0) == 1
    assert _inflation_risk(5.0) == 4
    assert _inflation_risk(15.0) == 7
    assert _inflation_risk(50.0) == 10
    print("✓ test_inflation_risk_thresholds passed")


def test_current_account_risk_more_negative_is_higher_risk():
    assert _current_account_risk(2.0) == 1     # surplus, low risk
    assert _current_account_risk(-1.0) == 3
    assert _current_account_risk(-8.0) == 10
    print("✓ test_current_account_risk_more_negative_is_higher_risk passed")


def test_debt_risk_thresholds():
    assert _debt_risk(30) == 2
    assert _debt_risk(75) == 7
    assert _debt_risk(120) == 10
    print("✓ test_debt_risk_thresholds passed")


def test_growth_risk_lower_growth_is_higher_risk():
    assert _growth_risk(6.0) == 1       # strong growth, low risk
    assert _growth_risk(1.0) == 5       # sluggish growth, moderate risk
    assert _growth_risk(-5.0) == 9      # recession, high risk
    print("✓ test_growth_risk_lower_growth_is_higher_risk passed")


def test_build_scorecard_computes_all_dimensions_with_full_data():
    events = [
        _conflict_event("e1", "KEN", "Kenya", "2026-03-01", 7.0),
        _conflict_event("e2", "KEN", "Kenya", "2026-04-01", 6.0),
        _indicator_event("e3", "KEN", "Kenya", "2025-12-31", "FP.CPI.TOTL.ZG", "Inflation, consumer prices (annual %): 6.5% (2025)"),
        _indicator_event("e4", "KEN", "Kenya", "2025-12-31", "BN.CAB.XOKA.GD.ZS", "Current account balance (% of GDP): -4.1% (2025)"),
        _indicator_event("e5", "KEN", "Kenya", "2025-12-31", "GGXWDG_NGDP", "General government gross debt (% of GDP): 71.6% (2025)"),
        _indicator_event("e6", "KEN", "Kenya", "2025-12-31", "NY.GDP.MKTP.KD.ZG", "GDP growth (annual %): 4.8% (2025)"),
    ]
    db_path = _make_temp_kb(events)
    scorecard = build_country_scorecard("KEN", "Kenya", db_path=db_path)

    assert scorecard["scores"]["security_risk"] is not None
    assert scorecard["scores"]["economic_risk"] is not None
    assert scorecard["overall_risk"] is not None
    assert scorecard["methodology_inputs"]["security"]["event_count"] == 2
    assert scorecard["methodology_inputs"]["economic"]["raw_values"]["inflation"] == 6.5
    print("✓ test_build_scorecard_computes_all_dimensions_with_full_data passed")


def test_build_scorecard_handles_missing_dimensions_gracefully():
    """A country with only conflict data (no economic indicators ingested
    yet) should still produce a scorecard -- missing dimensions are None,
    not a crash, and overall_risk averages only what's computable."""
    events = [_conflict_event("e1", "SOM", "Somalia", "2026-03-01", 8.0)]
    db_path = _make_temp_kb(events)
    scorecard = build_country_scorecard("SOM", "Somalia", db_path=db_path)

    assert scorecard["scores"]["economic_risk"] is None
    assert scorecard["scores"]["security_risk"] is not None
    assert scorecard["overall_risk"] == scorecard["scores"]["security_risk"] or \
        scorecard["overall_risk"] == round(
            (scorecard["scores"]["security_risk"] + scorecard["scores"]["political_stability_risk"]) / 2, 1
        )
    print("✓ test_build_scorecard_handles_missing_dimensions_gracefully passed")


def test_build_scorecard_no_data_at_all():
    events = [_conflict_event("e1", "KEN", "Kenya", "2026-03-01", 5.0)]
    db_path = _make_temp_kb(events)
    scorecard = build_country_scorecard("NGA", "Nigeria", db_path=db_path)
    assert scorecard["scores"]["security_risk"] is None
    assert scorecard["scores"]["economic_risk"] is None
    assert scorecard["scores"]["political_stability_risk"] == 0.0
    print("✓ test_build_scorecard_no_data_at_all passed")


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
