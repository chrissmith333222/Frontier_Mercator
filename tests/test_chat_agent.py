"""
tests/test_chat_agent.py

Tests the Phase 1 chat assistant's plumbing (data search tool, Excel/PDF
export tools, and the multi-round tool-calling loop) with a fake Anthropic
client -- no real API key or network call needed.

Usage:
    python -m pytest tests/test_chat_agent.py -v
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from openpyxl import load_workbook
from io import BytesIO

from scripts.analysis.chat_agent import (
    run_chat_turn,
    _search_intelligence_data,
    _export_excel,
    _export_pdf,
    _to_plain_block,
    MAX_TOOL_ROUNDS,
)

FIXTURE_DF = pd.DataFrame([
    {
        "meridian_event_id": "e1", "source": "ACLED", "event_date": "2026-03-14",
        "country": "Kenya", "event_category": "conflict", "severity_score": 6.5,
        "fatalities": 4, "narrative_summary": "Clashes reported near border region.",
        "source_url": "https://acleddata.com", "actors": [{"name": "Government of Kenya"}],
    },
    {
        "meridian_event_id": "e2", "source": "AidData", "event_date": "2026-01-10",
        "country": "Kenya", "event_category": "investment", "severity_score": None,
        "fatalities": None, "narrative_summary": "China Eximbank financed a road project.",
        "source_url": "https://aiddata.org", "actors": [{"name": "China Eximbank"}],
    },
    {
        "meridian_event_id": "e3", "source": "GDELT", "event_date": "2026-02-01",
        "country": "Nigeria", "event_category": "conflict", "severity_score": 3.0,
        "fatalities": 0, "narrative_summary": "Protest reported in Lagos.",
        "source_url": "https://gdeltproject.org", "actors": [],
    },
])


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text

    def model_dump(self):
        return {"type": "text", "text": self.text}


class _FakeToolUseBlock:
    def __init__(self, name, tool_input, block_id="tool_1"):
        self.type = "tool_use"
        self.name = name
        self.input = tool_input
        self.id = block_id

    def model_dump(self):
        return {"type": "tool_use", "name": self.name, "input": self.input, "id": self.id}


class _FakeResponse:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        # Snapshot messages at call time -- run_chat_turn mutates the same
        # list object across rounds, so without a copy every recorded call
        # would alias the final post-loop state instead of what was
        # actually sent on that specific round.
        snapshot = dict(kwargs)
        snapshot["messages"] = list(kwargs["messages"])
        self.calls.append(snapshot)
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def test_search_filters_by_country():
    result = json.loads(_search_intelligence_data(FIXTURE_DF, {"query": "", "country": "Kenya"}))
    assert result["result_count"] == 2
    assert all(e["country"] == "Kenya" for e in result["events"])


def test_search_filters_by_keyword():
    result = json.loads(_search_intelligence_data(FIXTURE_DF, {"query": "road project"}))
    assert result["result_count"] == 1
    assert result["events"][0]["source"] == "AidData"


def test_search_filters_by_category():
    result = json.loads(_search_intelligence_data(FIXTURE_DF, {"query": "", "category": "conflict"}))
    assert result["result_count"] == 2


def test_search_no_matches_returns_empty():
    result = json.loads(_search_intelligence_data(FIXTURE_DF, {"query": "nonexistent keyword xyz"}))
    assert result["result_count"] == 0
    assert result["events"] == []


def test_export_excel_produces_valid_workbook():
    confirmation, file_record = _export_excel({
        "filename": "test export!!",
        "sheets": [{"name": "Events", "headers": ["Country", "Date"], "rows": [["Kenya", "2026-03-14"]]}],
    })
    assert "test_export" in confirmation
    assert file_record["filename"] == "test_export.xlsx"
    wb = load_workbook(BytesIO(file_record["bytes"]))
    assert wb["Events"]["A1"].value == "Country"
    assert wb["Events"]["A2"].value == "Kenya"


def test_export_pdf_produces_nonempty_bytes():
    confirmation, file_record = _export_pdf({
        "filename": "brief", "title": "Kenya Snapshot",
        "sections": [{"heading": "Overview", "body": "Some findings here."}],
    })
    assert file_record["filename"] == "brief.pdf"
    assert file_record["bytes"][:4] == b"%PDF"
    assert "1 section" in confirmation


def test_to_plain_block_handles_plain_dicts_and_objects():
    assert _to_plain_block({"type": "text", "text": "hi"}) == {"type": "text", "text": "hi"}
    assert _to_plain_block(_FakeTextBlock("hi")) == {"type": "text", "text": "hi"}


def test_run_chat_turn_answers_directly_without_tools():
    client = _FakeClient([
        _FakeResponse([_FakeTextBlock("Hello, how can I help?")], stop_reason="end_turn"),
    ])
    result = run_chat_turn(FIXTURE_DF, history=[], user_message="hi", client=client)
    assert result["reply"] == "Hello, how can I help?"
    assert result["generated_files"] == []


def test_run_chat_turn_executes_search_tool_then_answers():
    client = _FakeClient([
        _FakeResponse(
            [_FakeToolUseBlock("search_intelligence_data", {"query": "", "country": "Kenya"})],
            stop_reason="tool_use",
        ),
        _FakeResponse([_FakeTextBlock("Kenya has 2 events on file.")], stop_reason="end_turn"),
    ])
    result = run_chat_turn(FIXTURE_DF, history=[], user_message="What's happening in Kenya?", client=client)
    assert result["reply"] == "Kenya has 2 events on file."
    # Second call's messages should include the tool_result from the first round.
    second_call_messages = client.messages.calls[1]["messages"]
    tool_result_msg = second_call_messages[-1]
    assert tool_result_msg["role"] == "user"
    assert tool_result_msg["content"][0]["type"] == "tool_result"


def test_run_chat_turn_collects_generated_file_from_export_tool():
    client = _FakeClient([
        _FakeResponse(
            [_FakeToolUseBlock("export_excel", {
                "filename": "kenya_report",
                "sheets": [{"name": "Sheet1", "headers": ["A"], "rows": [["b"]]}],
            })],
            stop_reason="tool_use",
        ),
        _FakeResponse([_FakeTextBlock("Here's your file.")], stop_reason="end_turn"),
    ])
    result = run_chat_turn(FIXTURE_DF, history=[], user_message="export this", client=client)
    assert len(result["generated_files"]) == 1
    assert result["generated_files"][0]["filename"] == "kenya_report.xlsx"


def test_run_chat_turn_raises_after_exceeding_max_tool_rounds():
    responses = [
        _FakeResponse(
            [_FakeToolUseBlock("search_intelligence_data", {"query": "x"}, block_id=f"t{i}")],
            stop_reason="tool_use",
        )
        for i in range(MAX_TOOL_ROUNDS)
    ]
    client = _FakeClient(responses)
    try:
        run_chat_turn(FIXTURE_DF, history=[], user_message="loop forever", client=client)
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "tool-call rounds" in str(e)


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
