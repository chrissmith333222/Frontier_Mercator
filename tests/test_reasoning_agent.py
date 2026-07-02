"""
tests/test_reasoning_agent.py

Tests the reasoning agent's plumbing (prompt construction, response
parsing, thin-data guard) with a fake Anthropic client and a small
temporary knowledge base -- no real API key or network call needed.

Usage:
    python -m pytest tests/test_reasoning_agent.py -v
    (or, without pytest installed: python tests/test_reasoning_agent.py)
"""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.knowledge.build_knowledge_base import build_knowledge_base
from scripts.analysis.reasoning_agent import (
    generate_country_assessment,
    _build_user_message,
)

FIXTURE_EVENTS = [
    {
        "meridian_event_id": "e1", "source": "ACLED", "source_event_id": "s1",
        "event_date": "2026-03-14", "country": "Kenya", "iso3": "KEN", "admin1": None,
        "region": "East Africa / Horn", "in_core_mandate": True,
        "event_category": "conflict", "event_subtype": "Battles", "actors": [{"name": "Government of Kenya", "type": "state_forces"}],
        "fatalities": 4, "severity_score": 6.5,
        "narrative_summary": "Clashes reported near border region.",
        "source_url": "https://acleddata.com", "ingested_at": "2026-03-15T00:00:00Z",
    },
    {
        "meridian_event_id": "e2", "source": "AidData", "source_event_id": "s2",
        "event_date": "2026-01-10", "country": "Kenya", "iso3": "KEN", "admin1": None,
        "region": "East Africa / Horn", "in_core_mandate": True,
        "event_category": "investment", "event_subtype": "Transport", "actors": [{"name": "China Eximbank", "type": "chinese_financier"}],
        "fatalities": None, "severity_score": None,
        "narrative_summary": "Road project financed.",
        "source_url": "https://aiddata.org", "ingested_at": "2026-01-11T00:00:00Z",
    },
    {
        "meridian_event_id": "e3", "source": "WorldBank", "source_event_id": "s3",
        "event_date": "2025-12-31", "country": "Kenya", "iso3": "KEN", "admin1": None,
        "region": "East Africa / Horn", "in_core_mandate": True,
        "event_category": "economic_indicator", "event_subtype": "NY.GDP.MKTP.KD.ZG", "actors": [],
        "fatalities": None, "severity_score": None,
        "narrative_summary": "GDP growth: 5.2% (2025)",
        "source_url": "https://data.worldbank.org", "ingested_at": "2026-01-01T00:00:00Z",
    },
]


class _FakeResponse:
    def __init__(self, text, include_thinking_block=True, stop_reason="end_turn"):
        blocks = []
        if include_thinking_block:
            # Real Claude responses can include a ThinkingBlock (type=
            # "thinking", no .text attribute usable the same way) ahead of
            # the text block when extended thinking is enabled -- mirror
            # that here so the "find the text block" logic is exercised.
            blocks.append(type("ThinkingBlock", (), {"type": "thinking", "thinking": "..."})())
        blocks.append(type("TextBlock", (), {"type": "text", "text": text})())
        self.content = blocks
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, response_text):
        self._response_text = response_text
        self.last_call_kwargs = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return _FakeResponse(self._response_text)


class _FakeClient:
    def __init__(self, response_text):
        self.messages = _FakeMessages(response_text)


VALID_ANALYSIS_JSON = json.dumps({
    "trend_summary": "Mixed signal: continued Chinese-financed infrastructure alongside episodic border conflict.",
    "key_relationships": ["China Eximbank financed a road project (AidData, 2026-01-10) in the same window as border clashes (ACLED, 2026-03-14)."],
    "risk_flags": ["Border-area conflict event within the same reporting window as active development finance."],
    "data_caveats": "Only 3 events in this window; not enough to establish a trend with confidence.",
})


def _make_temp_kb():
    tmp_dir = Path(tempfile.mkdtemp())
    dataset_path = tmp_dir / "merged_dataset.json"
    dataset_path.write_text(json.dumps(FIXTURE_EVENTS), encoding="utf-8")
    db_path = tmp_dir / "meridian.db"
    build_knowledge_base(merged_dataset_path=dataset_path, db_path=db_path)
    return db_path


def test_build_user_message_includes_key_sections():
    snapshot = {
        "iso3": "KEN",
        "category_counts": {"conflict": 1, "investment": 1},
        "top_conflict_events": [{"event_date": "2026-03-14", "narrative_summary": "Clashes reported."}],
        "latest_economic_indicators": [],
        "top_investment_projects": [{"event_date": "2026-01-10", "narrative_summary": "Road project."}],
        "humanitarian_and_osint_signals": [],
        "top_active_actors": [{"actor_name": "China Eximbank"}],
    }
    message = _build_user_message(snapshot, "Kenya")
    assert "Kenya (KEN)" in message
    assert "Clashes reported" in message
    assert "Road project" in message
    assert "China Eximbank" in message
    print("✓ test_build_user_message_includes_key_sections passed")


def test_generate_assessment_parses_fenced_json_response():
    db_path = _make_temp_kb()
    import scripts.knowledge.queries as queries_module

    fake_client = _FakeClient(f"```json\n{VALID_ANALYSIS_JSON}\n```")

    def _snapshot_from_temp(iso3, db_path_arg=db_path):
        return queries_module.country_snapshot(iso3, db_path=db_path_arg)

    import scripts.analysis.reasoning_agent as agent_module
    original_snapshot_fn = agent_module.country_snapshot
    agent_module.country_snapshot = _snapshot_from_temp
    try:
        result = generate_country_assessment("KEN", "Kenya", client=fake_client)
    finally:
        agent_module.country_snapshot = original_snapshot_fn

    assert result["iso3"] == "KEN"
    assert result["total_events_analyzed"] == 3
    assert "trend_summary" in result["analysis"]
    assert "China Eximbank" in result["analysis"]["key_relationships"][0]
    print("✓ test_generate_assessment_parses_fenced_json_response passed")


def test_generate_assessment_raises_on_truncated_response():
    db_path = _make_temp_kb()
    import scripts.knowledge.queries as queries_module
    import scripts.analysis.reasoning_agent as agent_module

    fake_client = _FakeClient(VALID_ANALYSIS_JSON)
    fake_client.messages._response_text = None  # unused; override create() directly below
    fake_client.messages.create = lambda **kwargs: _FakeResponse(
        '{"trend_summary": "cut off mid', stop_reason="max_tokens"
    )

    original_snapshot_fn = agent_module.country_snapshot
    agent_module.country_snapshot = lambda iso3: queries_module.country_snapshot(iso3, db_path=db_path)
    try:
        raised = False
        try:
            generate_country_assessment("KEN", "Kenya", client=fake_client)
        except RuntimeError as e:
            raised = "truncated" in str(e).lower()
        assert raised
    finally:
        agent_module.country_snapshot = original_snapshot_fn
    print("✓ test_generate_assessment_raises_on_truncated_response passed")


def test_generate_assessment_raises_on_thin_data():
    tmp_dir = Path(tempfile.mkdtemp())
    dataset_path = tmp_dir / "merged_dataset.json"
    dataset_path.write_text(json.dumps([FIXTURE_EVENTS[0]]), encoding="utf-8")  # only 1 event
    db_path = tmp_dir / "meridian.db"
    build_knowledge_base(merged_dataset_path=dataset_path, db_path=db_path)

    import scripts.knowledge.queries as queries_module
    import scripts.analysis.reasoning_agent as agent_module
    original_snapshot_fn = agent_module.country_snapshot
    agent_module.country_snapshot = lambda iso3: queries_module.country_snapshot(iso3, db_path=db_path)
    try:
        raised = False
        try:
            generate_country_assessment("KEN", "Kenya", client=_FakeClient(VALID_ANALYSIS_JSON))
        except RuntimeError:
            raised = True
        assert raised
    finally:
        agent_module.country_snapshot = original_snapshot_fn
    print("✓ test_generate_assessment_raises_on_thin_data passed")


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
