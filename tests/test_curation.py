"""
tests/test_curation.py

Tests entity resolution and cross-source deduplication against fixture
data -- no live data needed.

Usage:
    python -m pytest tests/test_curation.py -v
    (or, without pytest installed: python tests/test_curation.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.curation.entity_resolution import canonicalize_actor_name, resolve_event_actors
from scripts.curation.dedupe import dedupe_conflict_events


def test_canonicalize_known_alias():
    assert canonicalize_actor_name("CHINA") == "China"
    assert canonicalize_actor_name("PRC") == "China"
    assert canonicalize_actor_name("USA") == "United States"
    print("✓ test_canonicalize_known_alias passed")


def test_canonicalize_recases_all_caps_unknown():
    result = canonicalize_actor_name("STUDENT UNION")
    assert result == "Student Union"
    print("✓ test_canonicalize_recases_all_caps_unknown passed")


def test_canonicalize_leaves_natural_casing_alone():
    result = canonicalize_actor_name("JNIM: Group for Support of Islam and Muslims")
    assert result == "JNIM: Group for Support of Islam and Muslims"
    print("✓ test_canonicalize_leaves_natural_casing_alone passed")


def test_canonicalize_empty_string():
    assert canonicalize_actor_name("") == ""
    print("✓ test_canonicalize_empty_string passed")


def test_resolve_event_actors():
    event = {"actors": [{"name": "CHINA", "type": "unknown"}, {"name": "Mali Government", "type": "state"}]}
    result = resolve_event_actors(event)
    assert result["actors"][0]["name"] == "China"
    assert result["actors"][1]["name"] == "Mali Government"
    print("✓ test_resolve_event_actors passed")


DUPLICATE_A = {
    "source": "ACLED", "country": "Mali", "event_date": "2026-06-15",
    "event_category": "conflict",
    "narrative_summary": "JNIM fighters clashed with Malian armed forces near Gao, 12 killed.",
}
DUPLICATE_B = {
    "source": "GDELT", "country": "Mali", "event_date": "2026-06-15",
    "event_category": "conflict",
    "narrative_summary": "JNIM fighters clashed with Malian armed forces near Gao 12 killed",
}
SAME_SOURCE_SIMILAR_TEXT = {
    # Same source, same country/date, formulaic near-identical GDELT-style
    # text -- but a genuinely different real-world incident. Must NOT be
    # merged with DUPLICATE_B: same-source events are never deduped against
    # each other, only across sources (see dedupe.py's rationale comment).
    "source": "GDELT", "country": "Mali", "event_date": "2026-06-15",
    "event_category": "conflict",
    "narrative_summary": "UNSPECIFIED <-> MALI (CAMEO 190)",
}
DISTINCT_SAME_DAY = {
    "source": "GDELT", "country": "Mali", "event_date": "2026-06-15",
    "event_category": "protest_civil_unrest",
    "narrative_summary": "Teachers union held a demonstration in Bamako over unpaid wages.",
}
DIFFERENT_COUNTRY = {
    "source": "GDELT", "country": "Kenya", "event_date": "2026-06-15",
    "event_category": "conflict",
    "narrative_summary": "JNIM fighters clashed with Malian armed forces near Gao, 12 killed.",
}
NON_CONFLICT = {
    "source": "WorldBank", "country": "Mali", "event_date": "2026-06-15",
    "event_category": "economic_indicator",
    "narrative_summary": "GDP growth (annual %): 4.0% (2025)",
}


def test_dedupe_removes_similar_same_day_same_country():
    events = [DUPLICATE_A, DUPLICATE_B]
    result, removed = dedupe_conflict_events(events)
    assert removed == 1
    assert len(result) == 1
    assert result[0]["source"] == "ACLED"  # higher-priority source kept
    print("✓ test_dedupe_removes_similar_same_day_same_country passed")


def test_dedupe_keeps_distinct_events_same_day():
    events = [DUPLICATE_A, DISTINCT_SAME_DAY]
    result, removed = dedupe_conflict_events(events)
    assert removed == 0
    assert len(result) == 2
    print("✓ test_dedupe_keeps_distinct_events_same_day passed")


def test_dedupe_never_merges_same_source_events():
    events = [DUPLICATE_B, SAME_SOURCE_SIMILAR_TEXT]  # both GDELT, same country/date
    result, removed = dedupe_conflict_events(events)
    assert removed == 0, "Same-source events must never be merged, regardless of text similarity"
    assert len(result) == 2
    print("✓ test_dedupe_never_merges_same_source_events passed")


def test_dedupe_keeps_same_text_different_country():
    events = [DUPLICATE_A, DIFFERENT_COUNTRY]
    result, removed = dedupe_conflict_events(events)
    assert removed == 0
    assert len(result) == 2
    print("✓ test_dedupe_keeps_same_text_different_country passed")


def test_dedupe_passes_through_non_conflict_events():
    events = [DUPLICATE_A, DUPLICATE_B, NON_CONFLICT]
    result, removed = dedupe_conflict_events(events)
    assert removed == 1
    assert len(result) == 2
    assert any(e["event_category"] == "economic_indicator" for e in result)
    print("✓ test_dedupe_passes_through_non_conflict_events passed")


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
