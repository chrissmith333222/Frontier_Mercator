"""
tests/test_pdf_citations.py

Tests the Chicago-style endnote citation helpers in pdf_report.py --
that citations cover exactly the sources actually present in a report's
scope, in Chicago notes format, plus the AI-synthesis methodology note
when narrative sections are present.

Usage:
    python -m pytest tests/test_pdf_citations.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.reports.pdf_report import (
    _collect_citations,
    _endnote_flowables,
    SOURCE_CITATIONS,
)

SCOPE_DF = pd.DataFrame([
    {"source": "ACLED", "event_category": "conflict"},
    {"source": "ACLED", "event_category": "conflict"},
    {"source": "IMF", "event_category": "economic_indicator"},
    {"source": "DFC", "event_category": "investment"},
])


def test_citations_cover_only_sources_in_scope():
    citations = _collect_citations(SCOPE_DF, has_ai_analysis=False)
    joined = " ".join(citations)
    assert "acleddata.com" in joined
    assert "imf.org" in joined
    assert "dfc.gov" in joined
    assert "gdeltproject.org" not in joined  # GDELT isn't in this scope


def test_ai_analysis_adds_methodology_note():
    with_ai = _collect_citations(SCOPE_DF, has_ai_analysis=True)
    without_ai = _collect_citations(SCOPE_DF, has_ai_analysis=False)
    assert len(with_ai) == len(without_ai) + 1
    assert "Claude" in with_ai[-1]


def test_citations_are_chicago_style_with_accessed_date():
    citations = _collect_citations(SCOPE_DF, has_ai_analysis=False)
    for citation in citations:
        assert "accessed" in citation
        assert citation.endswith(".")


def test_every_schema_source_has_a_citation_entry():
    # Guard against adding a new ingestion source without a citation --
    # every source in the normalized_event schema enum must be citable.
    import json
    schema = json.loads(
        (Path(__file__).resolve().parent.parent / "schemas" / "normalized_event.schema.json")
        .read_text(encoding="utf-8")
    )
    schema_sources = set(schema["properties"]["source"]["enum"])
    # ReliefWeb/VDem/AllAfrica are in the schema enum but have never been
    # ingested (no fetch script yet) -- exempt until they actually exist.
    not_yet_ingested = {"ReliefWeb", "VDem", "AllAfrica"}
    missing = schema_sources - set(SOURCE_CITATIONS) - not_yet_ingested
    assert not missing, f"Sources missing a citation entry: {missing}"


def test_endnote_flowables_numbered_and_empty_safe():
    flowables = _endnote_flowables(["First citation.", "Second citation."])
    assert len(flowables) == 3  # heading + 2 notes
    assert _endnote_flowables([]) == []


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
