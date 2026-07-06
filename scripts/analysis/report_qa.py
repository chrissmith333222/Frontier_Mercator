"""
scripts/analysis/report_qa.py

The report quality feedback loop Chris asked for: "take the generated
pdf, use another LLM to assess it for professionalism and accuracy and
then make adjustments... to systematically correct those errors for
future reports."

How the loop closes:
  1. This script generates a country brief PDF, extracts its text, and
     has Claude grade it against a rubric (professionalism, accuracy vs.
     the underlying data, citation quality, clarity, structure -- 0-10
     each) with specific issues and concrete improvement suggestions.
  2. The full critique is saved to data/report_qa/<date>_<iso3>.json
     (inspectable history of how report quality trends over time).
  3. The actionable suggestions are distilled into
     data/report_qa/reviewer_guidance.md -- which reasoning_agent.py
     reads and appends to its system prompt on every future assessment
     generation. That's the systematic correction: the next batch of
     assessments is generated WITH the reviewer's guidance baked in,
     not just logged somewhere nobody reads.

Guidance is REPLACED each run (not appended) so it can't grow without
bound or accumulate stale/contradictory advice -- each QA pass produces
the current best guidance, and the JSON history preserves everything
prior.

Backend-only (needs ANTHROPIC_API_KEY and the pypdf package, neither of
which ships to the deployed app). Run manually or from the daily
scheduled task on a weekly cadence.

Usage:
    python scripts/analysis/report_qa.py --country Kenya
"""

import sys
import os
import json
import argparse
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
QA_DIR = REPO_ROOT / "data" / "report_qa"
GUIDANCE_PATH = QA_DIR / "reviewer_guidance.md"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

QA_SYSTEM_PROMPT = """You are a senior editorial reviewer at an institutional research firm, \
assessing a country intelligence brief produced for investors (the standard: something a JPMorgan \
or a16z portfolio team would circulate as a readahead). You will receive the report's full text \
plus a compact summary of the underlying dataset it was generated from.

Grade rigorously -- a 9-10 means genuinely publication-ready for a paying institutional client; \
5-6 means readable but visibly machine-generated; below 4 means embarrassing to circulate. Check \
accuracy claims against the dataset summary where possible (event counts, indicator values, \
source names). Be specific in issues: quote the offending text. Make improvement suggestions \
concrete and implementable as generation-prompt changes (e.g. "always spell out the event-category \
label instead of the raw snake_case field name"), not vague ("be more professional").

Record your assessment using the record_report_qa tool."""

_QA_TOOL = {
    "name": "record_report_qa",
    "description": "Records the structured quality assessment of one generated report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "professionalism": {"type": "number", "description": "0-10: tone, polish, branding consistency, layout coherence as inferable from text."},
            "accuracy": {"type": "number", "description": "0-10: claims consistent with the provided dataset summary; no fabricated numbers/sources."},
            "citation_quality": {"type": "number", "description": "0-10: sources properly cited, Chicago-style notes present and correct."},
            "clarity": {"type": "number", "description": "0-10: plain-language readability; no unexplained jargon or raw field names."},
            "structure": {"type": "number", "description": "0-10: executive summary first, logical section flow, appropriate length per section."},
            "specific_issues": {
                "type": "array", "items": {"type": "string"},
                "description": "Concrete problems found, each quoting or precisely locating the offending text.",
            },
            "improvement_suggestions": {
                "type": "array", "items": {"type": "string"},
                "description": "Concrete, implementable changes to the GENERATION PROMPT that would fix the issues for future reports.",
            },
        },
        "required": ["professionalism", "accuracy", "citation_quality", "clarity", "structure",
                      "specific_issues", "improvement_suggestions"],
    },
}


def _get_client():
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to your .env file -- never paste it into chat.")
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def _dataset_summary(df, country: str) -> str:
    """Compact ground-truth summary the reviewer can check the report's
    claims against -- category counts and source mix, not the full data."""
    scope = df[df["country"] == country]
    return (
        f"Country: {country}\n"
        f"Total events in dataset: {len(scope)}\n"
        f"By category: {scope['event_category'].value_counts().to_dict()}\n"
        f"By source: {scope['source'].value_counts().to_dict()}\n"
        f"Date range: {scope['event_date'].min()} to {scope['event_date'].max()}"
    )


def assess_report(report_text: str, dataset_summary: str, model: str = DEFAULT_MODEL, client=None) -> dict:
    """Runs the LLM quality review. `client` is injectable for tests."""
    if client is None:
        client = _get_client()
    response = client.messages.create(
        model=model,
        max_tokens=3000,
        system=QA_SYSTEM_PROMPT,
        tools=[_QA_TOOL],
        tool_choice={"type": "tool", "name": "record_report_qa"},
        messages=[{
            "role": "user",
            "content": f"REPORT TEXT:\n{report_text}\n\nUNDERLYING DATASET SUMMARY:\n{dataset_summary}",
        }],
    )
    tool_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
    if not tool_blocks:
        raise RuntimeError("No tool_use block in QA response")
    # Same defensive repair reasoning_agent.py needs: forced tool_choice
    # strongly encourages but doesn't guarantee schema conformance -- the
    # first real run of this script returned specific_issues as a single
    # string with embedded pseudo-XML, which downstream list-iteration then
    # walked character-by-character.
    from scripts.analysis.reasoning_agent import _normalize_tool_output
    return _normalize_tool_output(tool_blocks[0].input, _QA_TOOL)


def save_assessment(qa: dict, country: str, iso3: str) -> Path:
    """Persists the full critique JSON (history) and regenerates
    reviewer_guidance.md (the live guidance reasoning_agent.py reads).
    Guidance is replaced, not appended -- see module docstring."""
    QA_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history_path = QA_DIR / f"{date_str}_{iso3}.json"
    record = {
        "country": country, "iso3": iso3,
        "assessed_at": datetime.now(timezone.utc).isoformat(),
        **qa,
    }
    history_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    scores = {k: qa[k] for k in ["professionalism", "accuracy", "citation_quality", "clarity", "structure"]}
    guidance_lines = [
        "# Reviewer guidance for report generation",
        "",
        f"_Auto-generated by scripts/analysis/report_qa.py on {date_str} from a QA review of the "
        f"{country} brief (scores: {scores}). reasoning_agent.py appends this to its system prompt "
        f"on every assessment generation -- keep it short and actionable._",
        "",
    ]
    for suggestion in qa.get("improvement_suggestions", []):
        guidance_lines.append(f"- {suggestion}")
    GUIDANCE_PATH.write_text("\n".join(guidance_lines), encoding="utf-8")
    return history_path


def main():
    parser = argparse.ArgumentParser(description="LLM quality review of a generated country brief")
    parser.add_argument("--country", type=str, required=True, help="Country name, e.g. Kenya")
    args = parser.parse_args()

    import pandas as pd
    from scripts.reports.pdf_report import generate_country_brief
    from scripts.lib.world_countries import ALL_COUNTRIES

    name_to_iso3 = {name: iso3 for iso3, (name, _r, _m) in ALL_COUNTRIES.items()}
    iso3 = name_to_iso3.get(args.country)
    if not iso3:
        print(f"Unknown country: {args.country}", file=sys.stderr)
        sys.exit(1)

    data = json.loads((REPO_ROOT / "data" / "normalized" / "merged_dataset.json").read_text(encoding="utf-8"))
    df = pd.DataFrame(data)
    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")

    print(f"Generating {args.country} brief...", file=sys.stderr)
    pdf_bytes = generate_country_brief(df, args.country)
    report_text = extract_pdf_text(pdf_bytes)

    print("Running QA review...", file=sys.stderr)
    qa = assess_report(report_text, _dataset_summary(df, args.country))
    path = save_assessment(qa, args.country, iso3)

    scores = {k: qa[k] for k in ["professionalism", "accuracy", "citation_quality", "clarity", "structure"]}
    print(f"Scores: {scores}", file=sys.stderr)
    print(f"Issues found: {len(qa.get('specific_issues', []))}", file=sys.stderr)
    for issue in qa.get("specific_issues", []):
        print(f"  - {issue}", file=sys.stderr)
    print(f"Saved critique to {path}; guidance updated at {GUIDANCE_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
