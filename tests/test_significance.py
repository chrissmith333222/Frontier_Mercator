"""
tests/test_significance.py

Tests the significance/"hotness" scoring and source-diversity cap used by
the News & Social Signal tab and the Unified Intelligence Map -- both the
score's ability to surface high-severity/breaking events without a
severity_score, and the diversify_top_n guard against one source (e.g.
one with artificially fresh dates) crowding out every other source.

Usage:
    python -m pytest tests/test_significance.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.analytics.significance import (
    compute_significance_score,
    diversify_top_n,
    compute_tier_thresholds,
    significance_tier,
    top_n_badges,
    SIGNIFICANCE_HOT_THRESHOLD,
)

FIXTURE_DF = pd.DataFrame([
    # High severity_score conflict event -- should score high regardless of keywords.
    {"source": "ACLED", "event_date": "2026-06-01", "severity_score": 9.0,
     "fatalities": 20, "narrative_summary": "Clashes near border region."},
    # No severity_score at all, but a clear breaking-keyword hit -- should still score high.
    {"source": "GDELT", "event_date": "2026-06-01", "severity_score": None,
     "fatalities": None, "narrative_summary": "BREAKING: military coup declared, president detained."},
    # No severity_score, no keywords, old date -- should score low.
    {"source": "Infobae", "event_date": "2026-01-01", "severity_score": None,
     "fatalities": None, "narrative_summary": "Local council holds routine budget meeting."},
    # No severity_score, no keywords, most recent date -- should score higher than the stale one above.
    {"source": "JeuneAfrique", "event_date": "2026-06-15", "severity_score": None,
     "fatalities": None, "narrative_summary": "Trade delegation visits regional partners."},
])


def test_high_severity_event_scores_high():
    scores = compute_significance_score(FIXTURE_DF)
    assert scores.iloc[0] >= SIGNIFICANCE_HOT_THRESHOLD


def test_breaking_keyword_boosts_score_without_severity():
    scores = compute_significance_score(FIXTURE_DF)
    assert scores.iloc[1] >= SIGNIFICANCE_HOT_THRESHOLD


def test_stale_uneventful_story_scores_lowest():
    scores = compute_significance_score(FIXTURE_DF)
    assert scores.iloc[2] == scores.min()


def test_more_recent_story_outscores_stale_story_all_else_equal():
    scores = compute_significance_score(FIXTURE_DF)
    assert scores.iloc[3] > scores.iloc[2]


def test_scores_stay_within_0_to_10():
    scores = compute_significance_score(FIXTURE_DF)
    assert scores.min() >= 0
    assert scores.max() <= 10


def test_diversify_caps_dominant_source():
    # 20 GDELT rows all scored higher than the other sources -- without a
    # cap, GDELT alone would fill every slot in the top 10. Four other
    # sources with 3 rows each give enough non-GDELT capacity (12) to
    # reach n=10 without needing to backfill into GDELT above its cap.
    rows = []
    for i in range(20):
        rows.append({"source": "GDELT", "score": 9.0 - i * 0.01})
    for source_i in range(4):
        for row_i in range(3):
            rows.append({"source": f"Other{source_i}", "score": 5.0 - row_i * 0.01})
    df = pd.DataFrame(rows)

    result = diversify_top_n(df, "score", n=10, max_per_source=3)
    assert (result["source"] == "GDELT").sum() == 3
    assert result["source"].nunique() >= 4


def test_diversify_backfills_when_caps_leave_list_short():
    # Only 2 sources total, cap of 1 each -- can't reach n=10, so it must
    # backfill from the overall ranking rather than returning a short list.
    df = pd.DataFrame([
        {"source": "A", "score": 9.0}, {"source": "A", "score": 8.0}, {"source": "A", "score": 7.0},
        {"source": "B", "score": 6.0},
    ])
    result = diversify_top_n(df, "score", n=4, max_per_source=1)
    assert len(result) == 4


def test_diversify_returns_fewer_than_n_if_dataset_is_smaller():
    df = pd.DataFrame([{"source": "A", "score": 5.0}, {"source": "B", "score": 4.0}])
    result = diversify_top_n(df, "score", n=10, max_per_source=5)
    assert len(result) == 2


def test_tiers_are_not_all_urgent_for_a_ranked_top_n_list():
    # A "top 30 by score" list is, by construction, mostly high scorers --
    # a fixed absolute threshold would badge nearly all of them "urgent".
    # Percentile-relative tiers should still differentiate within the list.
    scores = pd.Series([2.7, 3.68, 3.68, 3.68, 4.42, 6.15, 6.15, 6.15, 7.33, 7.34, 7.35, 7.7])
    thresholds = compute_tier_thresholds(scores)
    tiers = [significance_tier(s, thresholds) for s in scores]
    assert tiers.count("urgent") < len(scores)
    assert None in tiers or "medium" in tiers  # not literally everything badged


def test_urgent_tier_requires_absolute_floor_even_if_relatively_highest():
    # If every score in scope is low, the highest-of-a-low-batch item
    # still shouldn't be labeled "urgent" -- that's a false alarm.
    scores = pd.Series([1.0, 1.2, 1.5, 1.8, 2.0])
    thresholds = compute_tier_thresholds(scores)
    tiers = [significance_tier(s, thresholds) for s in scores]
    assert "urgent" not in tiers
    assert "top" not in tiers


def test_high_absolute_score_gets_urgent_tier():
    scores = pd.Series([1.0, 2.0, 3.0, 9.5])
    thresholds = compute_tier_thresholds(scores)
    assert significance_tier(9.5, thresholds) == "urgent"
    assert significance_tier(1.0, thresholds) is None


def test_empty_scores_thresholds_never_match_anything():
    thresholds = compute_tier_thresholds(pd.Series([], dtype=float))
    assert significance_tier(10.0, thresholds) is None


def test_top_n_badges_caps_at_exactly_three():
    scores = pd.Series([9.0, 8.0, 7.0, 6.0, 5.0, 4.0], index=["a", "b", "c", "d", "e", "f"])
    badges = top_n_badges(scores, n=3)
    assert len(badges) == 3
    assert badges["a"] == "urgent"
    assert badges["b"] == "top"
    assert badges["c"] == "top"
    assert "d" not in badges and "e" not in badges and "f" not in badges


def test_top_n_badges_handles_fewer_items_than_n():
    scores = pd.Series([5.0, 3.0], index=["x", "y"])
    badges = top_n_badges(scores, n=3)
    assert len(badges) == 2
    assert badges["x"] == "urgent"
    assert badges["y"] == "top"


def test_top_n_badges_empty_series_returns_empty_dict():
    assert top_n_badges(pd.Series([], dtype=float)) == {}


if __name__ == "__main__":
    test_functions = [v for k, v in list(globals().items()) if k.startswith("test_")]
    print(f"Running {len(test_functions)} tests...\n")
    failures = 0
    for test_fn in test_functions:
        try:
            test_fn()
            print(f"passed {test_fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAILED {test_fn.__name__}: {e}")
    print(f"\n{len(test_functions) - failures}/{len(test_functions)} tests passed.")
    if failures:
        sys.exit(1)
