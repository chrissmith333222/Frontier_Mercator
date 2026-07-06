"""
tests/test_reasoning_agent.py

Tests the reasoning agent's plumbing (prompt construction, forced tool-use
response handling, thin-data guard) with a fake Anthropic client and a
small temporary knowledge base -- no real API key or network call needed.

Usage:
    python -m pytest tests/test_reasoning_agent.py -v
    (or, without pytest installed: python tests/test_reasoning_agent.py)
"""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from scripts.knowledge.build_knowledge_base import build_knowledge_base
from scripts.analysis.reasoning_agent import (
    generate_country_assessment,
    generate_cross_cutting_assessment,
    save_cross_cutting_assessment,
    _build_user_message,
    _slugify_query,
    _normalize_tool_output,
    _CROSS_CUTTING_TOOL,
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
    def __init__(self, tool_input, include_thinking_block=True, stop_reason="end_turn"):
        blocks = []
        if include_thinking_block:
            # Real Claude responses can include a ThinkingBlock (type=
            # "thinking") ahead of the tool_use block when extended
            # thinking is enabled -- mirror that here so the "find the
            # tool_use block" logic is exercised, not just content[0].
            blocks.append(type("ThinkingBlock", (), {"type": "thinking", "thinking": "..."})())
        blocks.append(type("ToolUseBlock", (), {"type": "tool_use", "input": tool_input,
                                                  "name": "record_country_assessment"})())
        self.content = blocks
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, tool_input):
        self._tool_input = tool_input
        self.last_call_kwargs = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return _FakeResponse(self._tool_input)


class _FakeClient:
    def __init__(self, tool_input):
        self.messages = _FakeMessages(tool_input)


VALID_ANALYSIS = {
    "trend_summary": "Mixed signal: continued Chinese-financed infrastructure alongside episodic border conflict.",
    "security_analysis": "Border clashes reported (ACLED, 2026-03-14) with no fatalities recorded.",
    "political_stability_analysis": "No protest/civil-unrest events in this window.",
    "economic_analysis": "GDP growth reported at 5.2% (World Bank, 2025).",
    "investment_analysis": "China Eximbank financed a road project (AidData, 2026-01-10).",
    "investment_opportunities": ["Transport-corridor financing activity signals bankable infrastructure appetite (AidData, 2026-01-10)."],
    "key_relationships": ["China Eximbank financed a road project (AidData, 2026-01-10) in the same window as border clashes (ACLED, 2026-03-14)."],
    "risk_flags": ["Border-area conflict event within the same reporting window as active development finance."],
    "data_caveats": "Only 3 events in this window; not enough to establish a trend with confidence.",
}


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


def test_generate_assessment_reads_tool_use_input():
    db_path = _make_temp_kb()
    import scripts.knowledge.queries as queries_module

    fake_client = _FakeClient(VALID_ANALYSIS)

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
    # Confirm the tool was actually forced, not left optional.
    assert fake_client.messages.last_call_kwargs["tool_choice"]["name"] == "record_country_assessment"
    print("✓ test_generate_assessment_reads_tool_use_input passed")


def test_generate_assessment_includes_per_dimension_analysis():
    """The BTI-style pairing (score + written paragraph per dimension) --
    security_analysis/political_stability_analysis/economic_analysis/
    investment_analysis must all come back so pdf_report.py can render
    them next to their corresponding scorecard section."""
    db_path = _make_temp_kb()
    import scripts.knowledge.queries as queries_module

    fake_client = _FakeClient(VALID_ANALYSIS)

    def _snapshot_from_temp(iso3, db_path_arg=db_path):
        return queries_module.country_snapshot(iso3, db_path=db_path_arg)

    import scripts.analysis.reasoning_agent as agent_module
    original_snapshot_fn = agent_module.country_snapshot
    agent_module.country_snapshot = _snapshot_from_temp
    try:
        result = generate_country_assessment("KEN", "Kenya", client=fake_client)
    finally:
        agent_module.country_snapshot = original_snapshot_fn

    for field in ["security_analysis", "political_stability_analysis", "economic_analysis", "investment_analysis"]:
        assert field in result["analysis"]
        assert len(result["analysis"][field]) > 0
    print("✓ test_generate_assessment_includes_per_dimension_analysis passed")


VALID_CROSS_CUTTING_ANALYSIS = {
    "answer": "China Eximbank-financed port expansion in Kenya coincides with nearby conflict activity in Mozambique's port area.",
    "supporting_evidence": ["Kenya, 2026-01-10, AidData: port expansion financing.", "Mozambique, 2026-02-01, ACLED: clashes near port area."],
    "countries_involved": ["Kenya", "Mozambique"],
    "data_caveats": "Only 2 retrieved events; not a comprehensive regional survey.",
}


def test_generate_cross_cutting_assessment_reads_tool_use_input():
    import scripts.analysis.reasoning_agent as agent_module

    fake_retrieved_events = [
        {"meridian_event_id": "e1", "country": "Kenya", "event_date": "2026-01-10",
         "source": "AidData", "narrative_summary": "Port expansion financing.", "similarity_score": 0.95},
        {"meridian_event_id": "e2", "country": "Mozambique", "event_date": "2026-02-01",
         "source": "ACLED", "narrative_summary": "Clashes near port area.", "similarity_score": 0.81},
    ]
    fake_anthropic_client = _FakeClient(VALID_CROSS_CUTTING_ANALYSIS)

    original_semantic_search = agent_module.semantic_search
    agent_module.semantic_search = lambda query, k=20, client=None: fake_retrieved_events
    try:
        result = generate_cross_cutting_assessment(
            "Chinese port financing near conflict zones", client=fake_anthropic_client
        )
    finally:
        agent_module.semantic_search = original_semantic_search

    assert result["events_retrieved"] == 2
    assert "answer" in result["analysis"]
    assert result["analysis"]["countries_involved"] == ["Kenya", "Mozambique"]
    assert fake_anthropic_client.messages.last_call_kwargs["tool_choice"]["name"] == "record_cross_cutting_assessment"
    print("✓ test_generate_cross_cutting_assessment_reads_tool_use_input passed")


def test_generate_cross_cutting_assessment_raises_on_thin_retrieval():
    import scripts.analysis.reasoning_agent as agent_module
    original_semantic_search = agent_module.semantic_search
    agent_module.semantic_search = lambda query, k=20, client=None: [{"meridian_event_id": "e1"}]  # only 1
    try:
        raised = False
        try:
            generate_cross_cutting_assessment("obscure query", client=_FakeClient(VALID_CROSS_CUTTING_ANALYSIS))
        except RuntimeError:
            raised = True
        assert raised
    finally:
        agent_module.semantic_search = original_semantic_search
    print("✓ test_generate_cross_cutting_assessment_raises_on_thin_retrieval passed")


def test_normalize_tool_output_repairs_real_malformed_response():
    """This exact shape came back from a real Claude call against a
    data-thin query: supporting_evidence arrived as a single string with
    embedded pseudo-XML tags instead of a JSON array, and the required
    countries_involved key was omitted entirely. The dashboard/PDF
    rendering iterates these fields expecting a list of strings --
    without normalization, iterating a raw string yields one bullet per
    character and a missing key crashes with KeyError."""
    malformed = {
        "answer": "The retrieved event set does not support an answer to this question.",
        "supporting_evidence": (
            "\n<item>Guinea, 2016-01-01 (DFC): $150.0M direct loan.</item>"
            "\n<item>Ivory Coast, 2000-03-14 (AidData): China Eximbank loan.</item>\n"
        ),
        "data_caveats": '<data_caveats">The retrieval surfaced legacy development-finance records.',
        # countries_involved deliberately omitted, mirroring the real failure
    }
    normalized = _normalize_tool_output(malformed, _CROSS_CUTTING_TOOL)

    assert isinstance(normalized["supporting_evidence"], list)
    assert len(normalized["supporting_evidence"]) == 2
    assert "Guinea" in normalized["supporting_evidence"][0]
    assert "<item>" not in normalized["supporting_evidence"][0]

    assert normalized["countries_involved"] == []

    assert isinstance(normalized["data_caveats"], str)
    assert "<data_caveats" not in normalized["data_caveats"]
    assert normalized["data_caveats"].startswith("The retrieval surfaced")
    print("✓ test_normalize_tool_output_repairs_real_malformed_response passed")


def test_normalize_tool_output_parses_json_stringified_array_with_parameter_wrapper():
    """Second real malformed shape, from report_qa.py's first live run: an
    array field arrived as a pseudo-XML `<parameter name="...">` wrapper
    around an otherwise-valid JSON array string. The old repair split it
    on newlines, producing one garbage mega-item instead of the real list."""
    malformed = {
        "answer": "Fine.",
        "supporting_evidence": '<parameter name="supporting_evidence">["First item.", "Second item."]',
        "countries_involved": '["Kenya", "Ghana"]',
        "data_caveats": "None.",
    }
    normalized = _normalize_tool_output(malformed, _CROSS_CUTTING_TOOL)
    assert normalized["supporting_evidence"] == ["First item.", "Second item."]
    assert normalized["countries_involved"] == ["Kenya", "Ghana"]
    print("✓ test_normalize_tool_output_parses_json_stringified_array_with_parameter_wrapper passed")


def test_normalize_tool_output_leaves_well_formed_response_unchanged():
    well_formed = {
        "answer": "A clean answer.",
        "supporting_evidence": ["Evidence one.", "Evidence two."],
        "countries_involved": ["Kenya", "Mozambique"],
        "data_caveats": "A clean caveat.",
    }
    normalized = _normalize_tool_output(well_formed, _CROSS_CUTTING_TOOL)
    assert normalized == well_formed
    print("✓ test_normalize_tool_output_leaves_well_formed_response_unchanged passed")


def test_slugify_query_produces_filesystem_safe_stem():
    assert _slugify_query("Chinese port financing near conflict zones?") == "chinese-port-financing-near-conflict-zones"
    assert _slugify_query("  Multiple   spaces & punctuation!!!  ") == "multiple-spaces-punctuation"
    print("✓ test_slugify_query_produces_filesystem_safe_stem passed")


def test_save_cross_cutting_assessment_writes_expected_file():
    tmp_dir = Path(tempfile.mkdtemp())
    assessment = {
        "query": "Critical minerals VC investment in West Africa post-coup",
        "generated_at": "2026-07-02T00:00:00Z",
        "model": "claude-sonnet-5",
        "events_retrieved": 5,
        "analysis": VALID_CROSS_CUTTING_ANALYSIS,
    }
    path = save_cross_cutting_assessment(assessment, output_dir=tmp_dir)
    assert path.exists()
    assert path.name.startswith("critical-minerals-vc-investment-in-west-africa")
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert reloaded["query"] == assessment["query"]
    print("✓ test_save_cross_cutting_assessment_writes_expected_file passed")


def test_generate_assessment_raises_on_truncated_response():
    db_path = _make_temp_kb()
    import scripts.knowledge.queries as queries_module
    import scripts.analysis.reasoning_agent as agent_module

    fake_client = _FakeClient(VALID_ANALYSIS)
    fake_client.messages.create = lambda **kwargs: _FakeResponse(
        {"trend_summary": "cut off mid"}, stop_reason="max_tokens"
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
            generate_country_assessment("KEN", "Kenya", client=_FakeClient(VALID_ANALYSIS))
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
