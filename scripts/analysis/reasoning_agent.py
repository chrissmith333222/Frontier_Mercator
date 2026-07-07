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

Also supports open-ended, cross-cutting questions that aren't scoped to
one country (e.g. "where is China investing near active conflict zones
region-wide") via generate_cross_cutting_assessment(), which retrieves
relevant events by semantic similarity (scripts/knowledge/semantic_search.py,
Voyage embeddings) instead of the fixed per-category SQL filters
country_snapshot() uses -- structured filters alone can't find "events
related to this idea" the way similarity search can.

Usage (CLI):
    python scripts/analysis/reasoning_agent.py --iso3 KEN
    python scripts/analysis/reasoning_agent.py --all-core-mandate
    python scripts/analysis/reasoning_agent.py --query "Chinese port financing near conflict zones"

Usage (as a module):
    from scripts.analysis.reasoning_agent import generate_country_assessment, generate_cross_cutting_assessment
    assessment = generate_country_assessment("KEN", "Kenya")
    answer = generate_cross_cutting_assessment("Chinese port financing near conflict zones")
"""

import sys
import os
import re
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv

from scripts.knowledge.queries import country_snapshot, countries_with_data
from scripts.knowledge.semantic_search import semantic_search

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ANALYSIS_DIR = REPO_ROOT / "data" / "analysis"
CUSTOM_ANALYSIS_DIR = ANALYSIS_DIR / "custom"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """You are a senior analyst at Frontier Mercator Group, writing the analytical \
sections of a client-facing country intelligence brief for institutional investors (Africa/Latin \
America focus, with extended monitoring elsewhere). You will be given structured, machine-collected \
event data for one country -- conflict/unrest events, economic indicators, investment/development-\
finance activity, humanitarian/OSINT signals, most-active actors -- and, when available, a summary \
of recent open-web reporting.

VOICE AND REGISTER -- this is the product's differentiator, follow it exactly:
- Write like an investment prospectus crossed with a government intelligence assessment crossed \
with a journal article: confident, declarative, so-what-first. The reader is a portfolio principal \
who cares about conclusions, not methodology.
- NEVER write "the data shows", "the dataset", "in the data provided", "records indicate", "events \
in this window", or any phrasing that exposes that a database sits under this report. Attribute \
conclusions to their real-world sources instead: "IMF projections indicate...", "ACLED-recorded \
incidents through June...", "DFC's recent commitments concentrate in...", or simply state the \
conclusion directly.
- Never expose internal field names (no snake_case like "political_violence_targeting_civilians" \
-- write "political violence against civilians"), record counts as hedges, or scoring machinery.
- Keep source-and-date attributions (e.g. "(ACLED, June 2026)") -- those read as professional \
citations, not machinery.

ANALYTICAL GROUND RULES, still followed strictly:
1. Ground every claim in the supplied event data and (when provided) the open-web reporting \
summary. Do not draw on unstated background knowledge; do not invent facts, figures, or sources.
2. If the available material is thin or contradictory on some point, handle it the way an \
intelligence product does: state the assessed picture with calibrated confidence language ("limited \
reporting suggests", "assessed with low confidence") rather than either speculating or lapsing into \
database-speak.
3. Every claim in "key_relationships", "risk_flags", and the four dimension-analysis fields must \
be traceable to a specific event, figure, or reported development, cited by source and date.
4. Describe risks and opportunities; do not issue buy/sell directives.

Record your assessment using the record_country_assessment tool."""

_ASSESSMENT_TOOL = {
    "name": "record_country_assessment",
    "description": "Records the structured pattern-analysis assessment for one country.",
    "input_schema": {
        "type": "object",
        "properties": {
            "security_analysis": {
                "type": "string",
                "description": "2-4 sentences of plain-language analysis specifically explaining the "
                                "security/conflict picture -- what's driving the Security risk score, "
                                "citing specific conflict/explosion events by date and source.",
            },
            "political_stability_analysis": {
                "type": "string",
                "description": "2-4 sentences specifically on political stability -- protest/civil "
                                "unrest and political-violence-targeting-civilians patterns, citing "
                                "specific events by date and source.",
            },
            "economic_analysis": {
                "type": "string",
                "description": "2-4 sentences specifically on the macroeconomic picture -- what the "
                                "latest inflation/current account/debt/GDP growth figures show, citing "
                                "the specific indicator values and their source (World Bank/IMF). Where "
                                "genuinely relevant, weave in demographic/development context (population "
                                "growth, working-age share, urbanization, literacy) as the development "
                                "backdrop against which the macro trend sits -- only if the data supports "
                                "a specific point, not as a routine add-on.",
            },
            "investment_analysis": {
                "type": "string",
                "description": "2-4 sentences specifically on investment/development-finance activity "
                                "-- who is financing what in this country, citing specific projects, "
                                "financiers, sectors, and dates from the data.",
            },
            "key_relationships": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-5 bullet-style strings describing notable actor/event/category "
                                "intersections, each citing specific dates/sources.",
            },
            "investment_opportunities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1-4 bullet-style strings on concrete, sector-specific investment "
                                "opportunities grounded in the financing activity, macro trends, and "
                                "recent reporting -- the investment-prospectus register (e.g. 'DFC and "
                                "World Bank PPI commitments concentrate in renewable generation, with "
                                "the Menengai geothermal expansion (2024) signaling bankable "
                                "public-private structures in the power sector'). Each cites its "
                                "source(s). Opportunities, not recommendations -- name what the "
                                "activity signals, not what to buy. Empty if the material genuinely "
                                "supports none.",
            },
            "risk_flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "0-5 bullet-style strings on specific risk patterns visible in the "
                                "data, each citing specific dates/sources.",
            },
            "data_caveats": {
                "type": "string",
                "description": "1-3 sentences on what this data window does NOT cover or where "
                                "confidence is low.",
            },
            "executive_summary": {
                "type": "string",
                "description": "Generate this LAST, after every other field above, since it must "
                                "synthesize them -- up to 3 paragraphs, the equivalent of handing the "
                                "finished brief to a colleague and asking 'summarize this in 3 "
                                "paragraphs covering key takeaways, opportunities, and risks.' "
                                "Paragraph 1: the overall picture and the single most important "
                                "takeaway for a portfolio principal deciding whether to keep reading. "
                                "Paragraph 2: the standout opportunity signal(s) from investment_opportunities "
                                "and investment_analysis, stated concretely. Paragraph 3: the standout "
                                "risk(s) from risk_flags and the security/political-stability analysis, "
                                "and what would need to be true for the picture to improve or worsen. "
                                "Separate paragraphs with a blank line. Same voice/register as everything "
                                "else -- no buy/sell directives, cite sources/dates, no database-speak. "
                                "This is what a reader who only reads one section should read.",
            },
        },
        "required": [
            "security_analysis", "political_stability_analysis",
            "economic_analysis", "investment_analysis", "key_relationships",
            "investment_opportunities", "risk_flags", "data_caveats", "executive_summary",
        ],
    },
}

CROSS_CUTTING_SYSTEM_PROMPT = """You are an intelligence analyst for Frontier Mercator Group. You \
will be given an analyst's open-ended question and a set of events retrieved by semantic similarity \
search across the full multi-country, multi-source dataset (conflict, economic, investment/\
development-finance, humanitarian/OSINT). The retrieved events may span many countries -- your job \
is to synthesize what they show in relation to the question, not to answer from general knowledge.

Ground rules, followed strictly:
1. Reason ONLY from the retrieved events provided. Do not draw on general background knowledge \
about the countries/actors/topics involved that isn't reflected in the data given.
2. The retrieval is similarity-based, not exhaustive or guaranteed relevant -- some retrieved events \
may be irrelevant noise. Say so if the retrieved set doesn't actually support an answer to the \
question, rather than forcing a synthesis out of weak matches.
3. Every claim must be traceable to specific events -- reference them by country, date, and source.
4. This is a preliminary statistical/pattern synthesis, not a finished investment recommendation.

Record your assessment using the record_cross_cutting_assessment tool."""

_CROSS_CUTTING_TOOL = {
    "name": "record_cross_cutting_assessment",
    "description": "Records the structured answer to an open-ended, cross-country pattern query.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "3-6 sentences directly answering the question based on the "
                                "retrieved events, or explaining why the retrieved events don't "
                                "support a confident answer.",
            },
            "supporting_evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-8 bullet-style strings, each citing a specific retrieved event "
                                "(country, date, source) that supports the answer.",
            },
            "countries_involved": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Countries where this pattern is most evident in the retrieved events.",
            },
            "data_caveats": {
                "type": "string",
                "description": "1-3 sentences on retrieval quality/coverage limitations for this query.",
            },
        },
        "required": ["answer", "supporting_evidence", "countries_involved", "data_caveats"],
    },
}


def _normalize_tool_output(analysis: dict, schema: dict) -> dict:
    """Forcing tool_choice strongly encourages schema conformance but
    doesn't guarantee it -- a real run against a data-thin/ambiguous
    query returned "supporting_evidence" as a single string containing
    embedded pseudo-XML tags (e.g. "\\n<item>...</item>\\n<item>...")
    instead of a JSON array, and omitted the required "countries_involved"
    key entirely. Rather than let a malformed sub-field crash the
    dashboard/PDF rendering (which iterates list fields expecting a list
    of strings), normalize defensively: missing fields get sensible
    empty defaults, and a string value in an array-typed field gets
    split back into a list instead of being iterated character-by-character."""
    normalized = dict(analysis)
    for field_name, field_schema in schema["input_schema"]["properties"].items():
        value = normalized.get(field_name)
        if field_schema["type"] == "array":
            if value is None:
                normalized[field_name] = []
            elif isinstance(value, str):
                # Strip a pseudo-XML wrapper if present (a real run of
                # report_qa.py returned `<parameter name="...">[...]` around
                # an otherwise-valid JSON array), then try json.loads before
                # falling back to <item>-tag / newline splitting.
                stripped = re.sub(r'^<parameter[^>]*>\s*|\s*</parameter>$', "", value.strip())
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        normalized[field_name] = [str(item) for item in parsed]
                        continue
                except (json.JSONDecodeError, ValueError):
                    pass
                items = re.findall(r"<item>(.*?)</item>", stripped, re.DOTALL)
                if not items:
                    items = [line.strip() for line in stripped.splitlines() if line.strip()]
                normalized[field_name] = [re.sub(r"</?[a-z_]+>", "", item).strip() for item in items] or [stripped]
        elif field_schema["type"] == "string":
            if value is None:
                normalized[field_name] = ""
            elif not isinstance(value, str):
                normalized[field_name] = str(value)
            else:
                # Strip stray tag fragments Claude occasionally leaves in
                # string fields (e.g. a malformed `<data_caveats">` prefix).
                normalized[field_name] = re.sub(r"</?[a-z_]+\"?>", "", value).strip()
    return normalized


def _build_user_message(snapshot: dict, country_name: str) -> str:
    return (
        f"Country: {country_name} ({snapshot['iso3']})\n\n"
        f"Event counts by category:\n{json.dumps(snapshot['category_counts'], indent=2)}\n\n"
        f"Recent conflict/unrest events (most recent/severe first):\n"
        f"{json.dumps(snapshot['top_conflict_events'], indent=2, default=str)}\n\n"
        f"Latest economic indicators:\n"
        f"{json.dumps(snapshot['latest_economic_indicators'], indent=2, default=str)}\n\n"
        f"Latest demographic/development indicators (population, age structure, life expectancy, "
        f"literacy -- economic-development context for security and investment trends):\n"
        f"{json.dumps(snapshot.get('latest_demographic_indicators', []), indent=2, default=str)}\n\n"
        f"Investment/development-finance activity:\n"
        f"{json.dumps(snapshot['top_investment_projects'], indent=2, default=str)}\n\n"
        f"Humanitarian/OSINT signals:\n"
        f"{json.dumps(snapshot['humanitarian_and_osint_signals'], indent=2, default=str)}\n\n"
        f"Most active actors in this country (across all categories):\n"
        f"{json.dumps(snapshot['top_active_actors'], indent=2, default=str)}"
    )


def _build_cross_cutting_user_message(query: str, events: list[dict]) -> str:
    trimmed = [
        {k: v for k, v in e.items() if k not in ("raw_source_data",)}
        for e in events
    ]
    return (
        f"Question: {query}\n\n"
        f"Retrieved events (ranked by semantic similarity to the question, most similar first):\n"
        f"{json.dumps(trimmed, indent=2, default=str)}"
    )


_REVIEWER_GUIDANCE_PATH = REPO_ROOT / "data" / "report_qa" / "reviewer_guidance.md"


def _load_reviewer_guidance() -> str:
    """The closing half of the report-QA feedback loop (see
    scripts/analysis/report_qa.py): that script has an LLM reviewer grade
    a generated report and distill concrete generation-prompt improvements
    into reviewer_guidance.md; this appends them to the system prompt so
    every FUTURE assessment is generated with the reviewer's corrections
    baked in. Returns "" when no QA pass has run yet (the loop degrades
    gracefully to exactly the old behavior). Capped defensively so a
    malformed/bloated guidance file can't blow up the prompt."""
    try:
        guidance = _REVIEWER_GUIDANCE_PATH.read_text(encoding="utf-8").strip()
    except (OSError, FileNotFoundError):
        return ""
    if not guidance:
        return ""
    return "\n\nEditorial reviewer guidance from prior report QA (apply these):\n" + guidance[:4000]


def _call_with_forced_tool(client, model: str, system_prompt: str, tool: dict, user_message: str,
                            context_label: str) -> dict:
    """Shared call path for both generate_country_assessment and
    generate_cross_cutting_assessment: forces the given tool, validates
    the response wasn't truncated, and returns the parsed tool input.
    Forcing tool_choice guarantees a validated tool_use block with .input
    already parsed as a dict per the input_schema -- no manual
    JSON.loads/markdown-fence-stripping of free-form text needed, which
    is what caused intermittent malformed-JSON failures (unescaped
    characters in Claude's raw text output) before this was added."""
    response = client.messages.create(
        model=model,
        max_tokens=6000,
        system=system_prompt,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": user_message}],
    )
    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            f"Claude response for {context_label} was truncated (hit max_tokens) -- "
            f"raise max_tokens in reasoning_agent.py rather than trying to use a cut-off tool call."
        )
    tool_blocks = [block for block in response.content if getattr(block, "type", None) == "tool_use"]
    if not tool_blocks:
        raise RuntimeError(f"No tool_use block in Claude response for {context_label}; "
                            f"got block types: {[getattr(b, 'type', type(b).__name__) for b in response.content]}")
    return _normalize_tool_output(tool_blocks[0].input, tool)


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


def _fetch_web_context(client, country_name: str, model: str = DEFAULT_MODEL) -> str:
    """Live web-search pass before the assessment call -- Chris: "is the
    tool still pulling from and referencing the web...? I want it to be
    interacting with the web to make sure we have the most complete
    product." Uses Anthropic's hosted web-search server tool with auto
    tool choice (a forced tool_choice would prevent the search tool from
    running, which is why this is a separate pass from the forced
    record_country_assessment call). Returns "" on ANY failure -- web
    search has real transient outages (observed live), and a country
    assessment should degrade to data-only rather than fail outright."""
    try:
        response = client.messages.create(
            model=model,
            max_tokens=2000,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}],
            messages=[{
                "role": "user",
                "content": (
                    f"Search the web for significant political, security, economic, and "
                    f"investment developments in {country_name} from the last 60 days. "
                    f"Summarize the genuinely important developments in up to 400 words, "
                    f"attributing each to its source and date. Only include things you "
                    f"actually found -- no filler."
                ),
            }],
        )
        text = "\n".join(blk.text for blk in response.content if getattr(blk, "type", None) == "text").strip()
        return text
    except Exception as e:
        print(f"    web-context fetch failed for {country_name} (continuing data-only): {e}",
              file=sys.stderr)
        return ""


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

    user_message = _build_user_message(snapshot, country_name)
    web_context = _fetch_web_context(client, country_name, model=model)
    if web_context:
        user_message += (
            "\n\nRecent open-web reporting (from live web search -- attribute to the named "
            "outlets/dates, weigh against the structured data above):\n" + web_context
        )

    analysis = _call_with_forced_tool(
        client, model, SYSTEM_PROMPT + _load_reviewer_guidance(), _ASSESSMENT_TOOL,
        user_message, context_label=f"{country_name} ({iso3})",
    )

    return {
        "iso3": iso3,
        "country": country_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "total_events_analyzed": total_events,
        "category_counts": snapshot["category_counts"],
        "analysis": analysis,
    }


def generate_cross_cutting_assessment(
    query: str, k: int = 20, model: str = DEFAULT_MODEL, client=None, search_client=None
) -> dict:
    """Answers an open-ended, cross-country question by retrieving the k
    most semantically similar events (scripts/knowledge/semantic_search.py,
    Voyage embeddings) and asking Claude to synthesize a grounded answer.
    `client` is the Anthropic client (injectable for tests); `search_client`
    is the Voyage client used inside semantic_search (also injectable)."""
    events = semantic_search(query, k=k, client=search_client)
    if len(events) < 2:
        raise RuntimeError(
            f"Only {len(events)} event(s) retrieved for query {query!r} -- too little to "
            f"synthesize an answer. Try a broader query or check the vector index is built."
        )

    if client is None:
        client = _get_client()
    analysis = _call_with_forced_tool(
        client, model, CROSS_CUTTING_SYSTEM_PROMPT, _CROSS_CUTTING_TOOL,
        _build_cross_cutting_user_message(query, events), context_label=f"query {query!r}",
    )

    return {
        "query": query,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "events_retrieved": len(events),
        "analysis": analysis,
    }


def save_assessment(assessment: dict, output_dir: Path = ANALYSIS_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{assessment['iso3']}_assessment.json"
    path.write_text(json.dumps(assessment, indent=2), encoding="utf-8")
    return path


def _slugify_query(query: str, max_length: int = 60) -> str:
    """Turns a free-text query into a filesystem-safe filename stem, e.g.
    'Chinese port financing near conflict zones?' -> 'chinese-port-financing-near-conflict-zones'."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    return slug[:max_length].rstrip("-") or "query"


def save_cross_cutting_assessment(assessment: dict, output_dir: Path = CUSTOM_ANALYSIS_DIR) -> Path:
    """Saves a cross-cutting assessment under a slug derived from its
    query text plus a short hash suffix (so two different queries that
    happen to slugify the same, or the same query re-run later, don't
    silently overwrite each other)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    import hashlib
    query_hash = hashlib.sha256(assessment["query"].encode("utf-8")).hexdigest()[:8]
    slug = _slugify_query(assessment["query"])
    path = output_dir / f"{slug}-{query_hash}.json"
    path.write_text(json.dumps(assessment, indent=2), encoding="utf-8")
    return path


def _generate_with_retries(iso3: str, country_name: str, max_attempts: int = 3) -> dict:
    """Retries transient failures (network/connection errors) with a short
    backoff. Does NOT retry thin-data or truncated-response errors --
    those are deterministic and retrying wastes an API call for the same
    failure."""
    import time
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return generate_country_assessment(iso3, country_name)
        except Exception as e:
            last_error = e
            transient = "connection" in str(e).lower() or "timeout" in str(e).lower()
            if not transient or attempt == max_attempts:
                raise
            wait_seconds = 2 * attempt
            print(f"    retrying {country_name} ({iso3}) after transient error "
                  f"(attempt {attempt}/{max_attempts}): {e}", file=sys.stderr)
            time.sleep(wait_seconds)
    raise last_error


def main():
    parser = argparse.ArgumentParser(description="Generate a Claude-synthesized country assessment")
    parser.add_argument("--iso3", type=str, help="Single country ISO3 code to assess, e.g. KEN")
    parser.add_argument("--all-core-mandate", action="store_true",
                         help="Generate assessments for every core-mandate country with data")
    parser.add_argument("--query", type=str,
                         help="Open-ended cross-country question, answered via semantic retrieval "
                              "+ synthesis instead of a fixed per-country snapshot. Requires the "
                              "vector index (scripts/knowledge/build_vector_index.py) to be built.")
    parser.add_argument("--top-k", type=int, default=20,
                         help="Number of events to retrieve for --query mode (default 20)")
    parser.add_argument("--save", action="store_true",
                         help="With --query, save the result to data/analysis/custom/ so it's "
                              "picked up by the dashboard's Custom Analysis section and PDF export "
                              "-- omit for a one-off ad-hoc answer that isn't published anywhere.")
    parser.add_argument("--min-events", type=int, default=10,
                         help="Skip countries with fewer than this many events (default 10)")
    parser.add_argument("--skip-existing", action="store_true",
                         help="Skip countries that already have a cached assessment file -- "
                              "use this to resume/retry-failed after a partial run without "
                              "re-spending API calls on countries that already succeeded.")
    args = parser.parse_args()

    if args.query:
        result = generate_cross_cutting_assessment(args.query, k=args.top_k)
        print(json.dumps(result, indent=2))
        if args.save:
            path = save_cross_cutting_assessment(result)
            print(f"Saved to {path}", file=sys.stderr)
        return

    if not args.iso3 and not args.all_core_mandate:
        parser.error("Specify --iso3 <CODE>, --all-core-mandate, or --query <question>")

    if args.iso3:
        countries = [c for c in countries_with_data() if c["iso3"] == args.iso3]
        if not countries:
            print(f"No data found for {args.iso3}", file=sys.stderr)
            sys.exit(1)
    else:
        countries = [c for c in countries_with_data() if c["in_core_mandate"] and c["n"] >= args.min_events]

    if args.skip_existing:
        before = len(countries)
        countries = [c for c in countries if not (ANALYSIS_DIR / f"{c['iso3']}_assessment.json").exists()]
        print(f"Skipping {before - len(countries)} countries with an existing cached assessment.", file=sys.stderr)

    print(f"Generating assessments for {len(countries)} countries...", file=sys.stderr)
    succeeded, failed = 0, 0
    for c in countries:
        try:
            assessment = _generate_with_retries(c["iso3"], c["country"])
            path = save_assessment(assessment)
            print(f"  OK  {c['country']} ({c['iso3']}) -> {path}", file=sys.stderr)
            succeeded += 1
        except Exception as e:
            print(f"  FAIL {c['country']} ({c['iso3']}): {e}", file=sys.stderr)
            failed += 1

    print(f"Done: {succeeded} succeeded, {failed} failed.", file=sys.stderr)


if __name__ == "__main__":
    main()
