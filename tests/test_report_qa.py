"""
tests/test_report_qa.py

Tests the report-QA feedback loop's plumbing (LLM review call, critique
persistence, guidance-file regeneration, and reasoning_agent picking the
guidance up) with a fake Anthropic client and a temp directory -- no real
API key, PDF generation, or network needed.

Usage:
    python -m pytest tests/test_report_qa.py -v
"""

import sys
import json
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import scripts.analysis.report_qa as report_qa
from scripts.analysis.report_qa import assess_report, save_assessment


class _FakeToolUseBlock:
    def __init__(self, tool_input):
        self.type = "tool_use"
        self.input = tool_input


class _FakeResponse:
    def __init__(self, tool_input):
        self.content = [_FakeToolUseBlock(tool_input)]


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


VALID_QA = {
    "professionalism": 7.5, "accuracy": 8.0, "citation_quality": 9.0,
    "clarity": 6.0, "structure": 8.0,
    "specific_issues": ['Raw field name "political_violence_targeting_civilians" appears unformatted in the Executive Summary.'],
    "improvement_suggestions": ["Always render event-category names in plain English (e.g. 'political violence targeting civilians'), never raw snake_case."],
}


def test_assess_report_forces_qa_tool_and_returns_scores():
    client = _FakeClient(VALID_QA)
    result = assess_report("Report text here.", "Dataset summary here.", client=client)
    assert result["professionalism"] == 7.5
    assert client.messages.last_call_kwargs["tool_choice"]["name"] == "record_report_qa"
    sent = client.messages.last_call_kwargs["messages"][0]["content"]
    assert "Report text here." in sent and "Dataset summary here." in sent


def test_save_assessment_writes_history_and_guidance(tmp_path):
    with patch.object(report_qa, "QA_DIR", tmp_path), \
         patch.object(report_qa, "GUIDANCE_PATH", tmp_path / "reviewer_guidance.md"):
        history_path = save_assessment(VALID_QA, "Kenya", "KEN")
        assert history_path.exists()
        record = json.loads(history_path.read_text(encoding="utf-8"))
        assert record["country"] == "Kenya"
        assert record["professionalism"] == 7.5

        guidance = (tmp_path / "reviewer_guidance.md").read_text(encoding="utf-8")
        assert "snake_case" in guidance


def test_guidance_is_replaced_not_appended(tmp_path):
    with patch.object(report_qa, "QA_DIR", tmp_path), \
         patch.object(report_qa, "GUIDANCE_PATH", tmp_path / "reviewer_guidance.md"):
        save_assessment(VALID_QA, "Kenya", "KEN")
        second_qa = {**VALID_QA, "improvement_suggestions": ["Second-run suggestion only."]}
        save_assessment(second_qa, "Ghana", "GHA")
        guidance = (tmp_path / "reviewer_guidance.md").read_text(encoding="utf-8")
        assert "Second-run suggestion only." in guidance
        assert "snake_case" not in guidance  # first run's advice replaced, not accumulated


def test_reasoning_agent_appends_guidance_when_present(tmp_path):
    import scripts.analysis.reasoning_agent as agent
    guidance_file = tmp_path / "reviewer_guidance.md"
    guidance_file.write_text("- Always spell out category names.", encoding="utf-8")
    with patch.object(agent, "_REVIEWER_GUIDANCE_PATH", guidance_file):
        suffix = agent._load_reviewer_guidance()
    assert "Always spell out category names." in suffix
    assert "reviewer guidance" in suffix.lower()


def test_reasoning_agent_guidance_empty_when_no_qa_has_run(tmp_path):
    import scripts.analysis.reasoning_agent as agent
    with patch.object(agent, "_REVIEWER_GUIDANCE_PATH", tmp_path / "does_not_exist.md"):
        assert agent._load_reviewer_guidance() == ""


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
