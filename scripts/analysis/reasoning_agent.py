"""
scripts/analysis/reasoning_agent.py

Phase 5: the Claude-powered synthesis layer on top of the knowledge base
(scripts/knowledge/queries.py). Takes a country's structured event data
(conflict, economic indicators, investment activity, OSINT/humanitarian
signals, actor relationships) and asks Claude to produce a grounded
trend/relationship assessment -- explicitly instructed to reason only
from the data provided and cite specific events, not to speculate beyond
it or draw on general world knowledge about the country.

This is a backend/batch script, not something the deployed Streamlit app
calls live: it reads the local SQLite knowledge base, calls the Anthropic
API once per country, and writes the result to
data/analysis/<iso3>_assessment.json. dashboard.py and pdf_report.py just
read that cached JSON -- keeps the `anthropic` SDK and API key off the
Streamlit Cloud deployment entirely, avoiding another dependency/secrets-
management deploy risk on a project that's already hit real trouble with
heavy/fragile dependencies (see project memory on the pandas/reportlab
deploy failures).

Requires ANTHROPIC_API_KEY in .env (not committed -- see .env.example).

Usage (CLI):
    python scripts/analysis/reasoning_agent.py --iso3 KEN
    python scripts/analysis/reasoning_agent.py --all-core-mandate

Usage (as a module):
    from scripts.analysis.reasoning_agent import generate_country_assessment
    assessment = generate_country_assessment("KEN", "Kenya")
"""

import sys
import os
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv

from scripts.knowledge.queries import country_snapshot, countries_with_data

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ANALYSIS_DIR = REPO_ROOT / "data" / "analysis"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """You are an intelligence analyst for Frontier Mercator Group, producing internal \
research notes on emerging-market investment risk (Africa/Latin America focus, with extended \
monitoring elsewhere). You will be given structured, machine-collected event data for one country: \
recent conflict/unrest events, economic indicators, investment/development-finance activity, \
humanitarian/OSINT signals, and the actors most active in that country across all of the above.

Ground rules, followed strictly:
1. Reason ONLY from the data provided in the user message. Do not draw on general background \
knowledge about the country's history, politics, or economy that isn't reflected in the data given.
2. If the data is thin, contradictory, or doesn't support a conclusion, say so explicitly rather \
than filling the gap with plausible-sounding speculation.
3. Every claim in "key_relationships" and "risk_flags" must be traceable to specific events in the \
data -- reference them by date and source (e.g. "ACLED, 2026-03-14").
4. This is a preliminary statistical/pattern synthesis, not a finished investment recommendation. \
Do not tell the reader whether to invest; describe what the data shows.

Respond with ONLY a JSON object (no markdown fences, no commentary outside the JSON) matching this \
shape:
{
  "trend_summary": "3-5 sentences on the overall pattern across categories in the given window",
  "key_relationships": ["2-5 bullet-style strings describing notable actor/event/category intersections, each citing specific dates/sources"],
  "risk_flags": ["0-5 bullet-style strings on specific risk patterns visible in the data, each citing specific dates/sources"],
  "data_caveats": "1-3 sentences on what this data window does NOT cover or where confidence is low"
}"""


def _build_user_message(snapshot: dict, country_name: str) -> str:
    return (
        f"Country: {country_name} ({snapshot['iso3']})\n\n"
        f"Event counts by category:\n{json.dumps(snapshot['category_counts'], indent=2)}\n\n"
        f"Recent conflict/unrest events (most recent/severe first):\n"
        f"{json.dumps(snapshot['top_conflict_events'], indent=2, default=str)}\n\n"
        f"Latest economic indicators:\n"
        f"{json.dumps(snapshot['latest_economic_indicators'], indent=2, default=str)}\n\n"
        f"Investment/development-finance activity:\n"
        f"{json.dumps(snapshot['top_investment_projects'], indent=2, default=str)}\n\n"
        f"Humanitarian/OSINT signals:\n"
        f"{json.dumps(snapshot['humanitarian_and_osint_signals'], indent=2, default=str)}\n\n"
        f"Most active actors in this country (across all categories):\n"
        f"{json.dumps(snapshot['top_active_actors'], indent=2, default=str)}"
    )


def _get_client():
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to your .env file "
            "(see .env.example) -- never paste it into chat."
        )
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def generate_country_assessment(iso3: str, country_name: str, model: str = DEFAULT_MODEL, client=None) -> dict:
    """Pulls a structured knowledge-base snapshot for `iso3`, sends it to
    Claude for synthesis, and returns the combined result (raw data +
    Claude's analysis + generation metadata). Raises RuntimeError if the
    knowledge base has too little data to be worth analyzing, or if
    ANTHROPIC_API_KEY isn't configured. `client` is injectable for tests
    (a fake with a matching `.messages.create(...)` surface) -- omit it
    in real use to get a live Anthropic client from ANTHROPIC_API_KEY."""
    snapshot = country_snapshot(iso3)
    total_events = sum(snapshot["category_counts"].values())
    if total_events < 3:
        raise RuntimeError(
            f"Only {total_events} event(s) for {country_name} ({iso3}) -- too little data for a "
            f"meaningful assessment. Skipping."
        )

    if client is None:
        client = _get_client()
    response = client.messages.create(
        model=model,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_message(snapshot, country_name)}],
    )
    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            f"Claude response for {country_name} ({iso3}) was truncated (hit max_tokens) -- "
            f"raise max_tokens in reasoning_agent.py rather than trying to parse a cut-off response."
        )
    # response.content can include non-text blocks (e.g. ThinkingBlock, if
    # extended thinking is enabled on the account/model) ahead of the
    # actual text response -- find the text block explicitly rather than
    # assuming content[0] is it.
    text_blocks = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    if not text_blocks:
        raise RuntimeError(f"No text block in Claude response for {country_name} ({iso3}); "
                            f"got block types: {[getattr(b, 'type', type(b).__name__) for b in response.content]}")
    raw_text = text_blocks[0].strip()
    # Claude occasionally wraps JSON in markdown fences despite instructions not to -- strip if present.
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()
    analysis = json.loads(raw_text)

    return {
        "iso3": iso3,
        "country": country_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "total_events_analyzed": total_events,
        "category_counts": snapshot["category_counts"],
        "analysis": analysis,
    }


def save_assessment(assessment: dict, output_dir: Path = ANALYSIS_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{assessment['iso3']}_assessment.json"
    path.write_text(json.dumps(assessment, indent=2), encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description="Generate a Claude-synthesized country assessment")
    parser.add_argument("--iso3", type=str, help="Single country ISO3 code to assess, e.g. KEN")
    parser.add_argument("--all-core-mandate", action="store_true",
                         help="Generate assessments for every core-mandate country with data")
    parser.add_argument("--min-events", type=int, default=10,
                         help="Skip countries with fewer than this many events (default 10)")
    args = parser.parse_args()

    if not args.iso3 and not args.all_core_mandate:
        parser.error("Specify --iso3 <CODE> or --all-core-mandate")

    if args.iso3:
        countries = [c for c in countries_with_data() if c["iso3"] == args.iso3]
        if not countries:
            print(f"No data found for {args.iso3}", file=sys.stderr)
            sys.exit(1)
    else:
        countries = [c for c in countries_with_data() if c["in_core_mandate"] and c["n"] >= args.min_events]

    print(f"Generating assessments for {len(countries)} countries...", file=sys.stderr)
    succeeded, failed = 0, 0
    for c in countries:
        try:
            assessment = generate_country_assessment(c["iso3"], c["country"])
            path = save_assessment(assessment)
            print(f"  OK  {c['country']} ({c['iso3']}) -> {path}", file=sys.stderr)
            succeeded += 1
        except Exception as e:
            print(f"  FAIL {c['country']} ({c['iso3']}): {e}", file=sys.stderr)
            failed += 1

    print(f"Done: {succeeded} succeeded, {failed} failed.", file=sys.stderr)


if __name__ == "__main__":
    main()
