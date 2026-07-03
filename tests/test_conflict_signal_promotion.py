"""
tests/test_conflict_signal_promotion.py

Tests the corroborated-conflict-signal detection used to feed news/social
signal into the Conflict & Security tab between ACLED's manual refreshes
-- both the keyword match and the "at least min_sources distinct sources"
corroboration requirement (Chris: "we need probably at least 2 sources
for validation").

Usage:
    python -m pytest tests/test_conflict_signal_promotion.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.analytics.conflict_signal_promotion import detect_corroborated_conflict_signals

CORROBORATED_ROWS = [
    {"source": "GDELT", "country": "Mali", "event_date": "2026-07-01",
     "narrative_summary": "Gunmen ambush military convoy near Gao.", "narrative_summary_en": None},
    {"source": "Bellingcat", "country": "Mali", "event_date": "2026-07-01",
     "narrative_summary": "Geolocating the ambush footage from Gao.", "narrative_summary_en": None},
]

SINGLE_SOURCE_ROW = [
    {"source": "Infobae", "country": "Peru", "event_date": "2026-07-01",
     "narrative_summary": "Reportan explosion en zona minera.",
     "narrative_summary_en": "Explosion reported in mining area."},
]

NO_KEYWORD_ROWS = [
    {"source": "GDELT", "country": "Kenya", "event_date": "2026-07-01",
     "narrative_summary": "Trade delegation signs new agreement.", "narrative_summary_en": None},
    {"source": "Infobae", "country": "Kenya", "event_date": "2026-07-01",
     "narrative_summary": "Trade delegation signs new agreement.", "narrative_summary_en": None},
]

FAR_APART_DATES_ROWS = [
    {"source": "GDELT", "country": "Nigeria", "event_date": "2026-06-01",
     "narrative_summary": "Militant attack reported in the northeast.", "narrative_summary_en": None},
    {"source": "Bellingcat", "country": "Nigeria", "event_date": "2026-07-01",
     "narrative_summary": "Militant attack reported in the northeast.", "narrative_summary_en": None},
]


def test_corroborated_conflict_signal_detected_across_two_sources():
    df = pd.DataFrame(CORROBORATED_ROWS)
    result = detect_corroborated_conflict_signals(df, min_sources=2)
    assert len(result) == 2
    assert set(result["source"]) == {"GDELT", "Bellingcat"}


def test_single_source_conflict_keyword_not_promoted():
    df = pd.DataFrame(SINGLE_SOURCE_ROW)
    result = detect_corroborated_conflict_signals(df, min_sources=2)
    assert len(result) == 0


def test_uses_english_translation_for_keyword_matching():
    # The Spanish text doesn't contain an English conflict keyword, but the
    # translation does -- matching should use the translation when present.
    rows = SINGLE_SOURCE_ROW + [{
        "source": "JeuneAfrique", "country": "Peru", "event_date": "2026-07-01",
        "narrative_summary": "Une autre source rapporte l'evenement.",
        "narrative_summary_en": "Another source reports the explosion.",
    }]
    df = pd.DataFrame(rows)
    result = detect_corroborated_conflict_signals(df, min_sources=2)
    assert len(result) == 2


def test_no_conflict_keywords_returns_empty():
    df = pd.DataFrame(NO_KEYWORD_ROWS)
    result = detect_corroborated_conflict_signals(df, min_sources=2)
    assert len(result) == 0


def test_dates_outside_window_not_corroborated():
    df = pd.DataFrame(FAR_APART_DATES_ROWS)
    result = detect_corroborated_conflict_signals(df, min_sources=2, date_window_days=1)
    assert len(result) == 0


def test_empty_input_returns_empty():
    df = pd.DataFrame(columns=["source", "country", "event_date", "narrative_summary", "narrative_summary_en"])
    result = detect_corroborated_conflict_signals(df)
    assert len(result) == 0


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
