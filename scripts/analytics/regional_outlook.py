"""
scripts/analytics/regional_outlook.py

The Regional Economic Outlook -- Chris's executive product (2026-07-16):
an overarching, region-level document conveying big-picture macro/regional
takeaways and opportunities. Mostly narrative/executive-summary register,
with quantitative data (GDP growth, FDI, inflation, current account)
woven into each opportunity to give it "quantitative meat."

For each core-mandate region (9: West Africa/Sahel, East Africa/Horn,
Southern Africa, Central Africa, North Africa, Andean, Southern Cone,
Central America & Caribbean, Mexico) the generator assembles:
  - the latest macro readings per country in the region (deterministic,
    straight from the World Bank/IMF indicator events)
  - the region's country assessments (executive summaries + investment
    opportunities, themselves grounded in the full event dataset and live
    web research at their generation time)
  - cross-cutting correlation insights and investment theses touching the
    region
and makes ONE forced-tool Claude call per region (~9 bounded calls per
full run -- flagged to Chris per the standing cost rule; roughly the cost
of regenerating 4-5 country assessments).

Output: data/insights/regional_outlook.json, rendered as a downloadable
branded PDF on the Reports page (scripts/reports/pdf_report.py
generate_regional_outlook_pdf) -- no API calls at render time, same
offline-artifact pattern as everything else.

Usage:
    python scripts/analytics/regional_outlook.py                # all regions
    python scripts/analytics/regional_outlook.py --region "North Africa"
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.analysis.reasoning_agent import _call_with_forced_tool, _get_client, DEFAULT_MODEL
from scripts.lib.regions import ISO3_TO_INFO

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MERGED_PATH = REPO_ROOT / "data" / "normalized" / "merged_dataset.json"
ANALYSIS_DIR = REPO_ROOT / "data" / "analysis"
INSIGHTS_PATH = REPO_ROOT / "data" / "insights" / "discovered_insights.json"
THESES_PATH = REPO_ROOT / "data" / "insights" / "investment_theses.json"
OUTPUT_PATH = REPO_ROOT / "data" / "insights" / "regional_outlook.json"

# Indicator codes worth quoting in an executive macro product.
_MACRO_CODES = {
    "NY.GDP.MKTP.KD.ZG": "GDP growth",
    "FP.CPI.TOTL.ZG": "Inflation",
    "BX.KLT.DINV.WD.GD.ZS": "FDI net inflows (% GDP)",
    "BN.CAB.XOKA.GD.ZS": "Current account (% GDP)",
    "SL.UEM.TOTL.ZS": "Unemployment",
    "NGDP_RPCH": "Real GDP growth (IMF)",
    "PCPIPCH": "Inflation (IMF)",
    "GGXWDG_NGDP": "Gov't debt (% GDP, IMF)",
}

SYSTEM_PROMPT = """You are the chief economist at Frontier Mercator Group, writing the firm's \
flagship REGIONAL ECONOMIC OUTLOOK -- the executive product a portfolio principal or institutional \
client reads to get the big-picture macro story and investment opportunities for one region.

Register: this is predominantly NARRATIVE -- confident, declarative, executive-summary prose in \
the same voice as the firm's country briefs (investment prospectus x intelligence assessment x \
journal article). Weave the quantitative data INTO the sentences ("with Ghanaian inflation easing \
to 8.1% while FDI inflows hold above 2% of GDP...") -- numbers give the narrative its meat, but \
the argument carries the piece, not tables.

Rules:
1. Ground every claim in the supplied material: the macro readings, the country assessment \
findings, the correlation insights, and the thesis signals. Cite sources naturally in prose \
("World Bank, 2025", "IMF projections", "UNCTAD connectivity data"). Never invent figures.
2. Think REGIONALLY: the value of this product is the cross-country synthesis -- shared dynamics, \
divergences between neighbors, where the region fits in global flows. Don't just summarize each \
country in sequence.
3. Each opportunity is a self-contained executive narrative (a strong paragraph), quantitative \
anchors included, naming the countries where the opportunity is concentrated.
4. Be honest about risks -- one clear-eyed paragraph, not boilerplate.
5. No buy/sell directives; describe where the opportunities and risks sit.

Record your outlook using the record_regional_outlook tool."""

_OUTLOOK_TOOL = {
    "name": "record_regional_outlook",
    "description": "Records the regional economic outlook.",
    "input_schema": {
        "type": "object",
        "properties": {
            "regional_narrative": {
                "type": "string",
                "description": "2-3 paragraphs (separated by blank lines): the region's big-picture "
                                "macro story right now -- growth picture, capital flows, the one or "
                                "two dynamics an executive must understand. Cross-country synthesis, "
                                "quantitative anchors woven into the prose.",
            },
            "opportunities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short headline for the opportunity, e.g. 'East African logistics corridors'."},
                        "narrative": {
                            "type": "string",
                            "description": "One strong executive paragraph: the opportunity, why now, "
                                            "which countries, with the quantitative evidence woven in "
                                            "(growth rates, FDI figures, project financing, price "
                                            "trends), sources cited in prose.",
                        },
                        "key_data_points": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "2-4 crisp quantitative anchors backing the narrative, each "
                                            "with source (e.g. 'Kenya real GDP growth 4.5% (IMF, 2026)').",
                        },
                    },
                    "required": ["title", "narrative", "key_data_points"],
                },
                "description": "2-4 region-level opportunities.",
            },
            "risk_outlook": {
                "type": "string",
                "description": "One clear-eyed paragraph on what could derail the regional picture, "
                                "grounded in the security/political findings supplied.",
            },
        },
        "required": ["regional_narrative", "opportunities", "risk_outlook"],
    },
}


def _core_regions() -> dict:
    """region -> [(iso3, country_name), ...] for core-mandate countries."""
    regions: dict[str, list] = {}
    for iso3, (name, region, mandate) in ISO3_TO_INFO.items():
        if mandate:
            regions.setdefault(region, []).append((iso3, name))
    return regions


def _latest_macro_by_country(events: list[dict], countries: set[str]) -> dict:
    """{country: {indicator_label: 'value (year, source)'}} -- latest reading
    per tracked macro indicator, straight from the normalized events."""
    latest: dict[str, dict] = {}
    best_date: dict[tuple, str] = {}
    for e in events:
        if e.get("country") not in countries:
            continue
        if e.get("event_category") not in ("economic_indicator",):
            continue
        code = e.get("event_subtype", "")
        label = _MACRO_CODES.get(code)
        if label is None:
            continue
        key = (e["country"], label)
        if e["event_date"] <= best_date.get(key, ""):
            continue
        best_date[key] = e["event_date"]
        summary = e.get("narrative_summary", "")
        value = summary.split(":", 1)[1].strip() if ":" in summary else summary
        latest.setdefault(e["country"], {})[label] = f"{value} ({e['event_date'][:4]}, {e['source']})"
    return latest


def _assessment_material(region_countries: list) -> list[str]:
    """Executive-summary first paragraphs + investment opportunities from
    each country assessment in the region."""
    material = []
    for iso3, name in region_countries:
        path = ANALYSIS_DIR / f"{iso3}_assessment.json"
        if not path.exists():
            continue
        try:
            analysis = json.loads(path.read_text(encoding="utf-8")).get("analysis", {})
        except (json.JSONDecodeError, OSError):
            continue
        exec_summary = (analysis.get("executive_summary") or "").split("\n\n")[0]
        if exec_summary:
            material.append(f"[{name} -- assessment] {exec_summary}")
        for opp in analysis.get("investment_opportunities", [])[:2]:
            material.append(f"[{name} -- opportunity] {opp}")
    return material


def _cross_cutting_material(region: str, region_country_names: set[str]) -> list[str]:
    """Correlation insights + thesis headlines touching this region's countries."""
    material = []
    if INSIGHTS_PATH.exists():
        data = json.loads(INSIGHTS_PATH.read_text(encoding="utf-8"))
        for ins in data.get("insights", []):
            if ins.get("country") in region_country_names:
                material.append(f"[correlation insight] {ins['headline']} -- {ins['detail']}")
    if THESES_PATH.exists():
        data = json.loads(THESES_PATH.read_text(encoding="utf-8"))
        for thesis in data.get("theses", []):
            geo = str(thesis.get("geography", ""))
            if any(c in geo for c in region_country_names) or region.split("/")[0].strip() in geo:
                material.append(f"[investment thesis] {thesis.get('headline', '')}")
    return material


def _build_user_message(region: str, region_countries: list, events: list[dict]) -> str:
    names = {name for _iso3, name in region_countries}
    macro = _latest_macro_by_country(events, names)
    macro_lines = []
    for country in sorted(macro):
        readings = "; ".join(f"{k}: {v}" for k, v in sorted(macro[country].items()))
        macro_lines.append(f"- {country}: {readings}")

    return (
        f"REGION: {region}\n"
        f"Countries: {', '.join(sorted(names))}\n\n"
        f"LATEST MACRO READINGS (World Bank/IMF, latest available per indicator):\n"
        + ("\n".join(macro_lines) or "- none on file") + "\n\n"
        f"COUNTRY ASSESSMENT FINDINGS (from the firm's own country briefs):\n"
        + ("\n".join(f"- {m}" for m in _assessment_material(region_countries)) or "- none") + "\n\n"
        f"CROSS-CUTTING SIGNALS:\n"
        + ("\n".join(f"- {m}" for m in _cross_cutting_material(region, names)) or "- none")
    )


def _coerce_opportunities(section: dict) -> dict:
    """Repairs the malformed-tool-output variant observed live 2026-07-16:
    `opportunities` arriving as a LIST whose single item is the JSON string
    of the real array (the normalizer only repairs string-valued fields, so
    a list-wrapping-a-string sails through). Same defensive family as
    investment_theses._coerce_thesis_dicts."""
    coerced = []
    for item in section.get("opportunities", []) or []:
        if isinstance(item, dict):
            coerced.append(item)
        elif isinstance(item, str):
            try:
                parsed = json.loads(item)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, list):
                coerced.extend(p for p in parsed if isinstance(p, dict))
            elif isinstance(parsed, dict):
                coerced.append(parsed)
    section["opportunities"] = coerced
    return section


def generate_outlook(regions: list[str] | None = None, model: str = DEFAULT_MODEL,
                      client=None) -> dict:
    if client is None:
        client = _get_client()
    all_regions = _core_regions()
    targets = {r: all_regions[r] for r in (regions or sorted(all_regions))}

    print("Loading merged dataset for macro readings...", file=sys.stderr)
    events = json.loads(MERGED_PATH.read_text(encoding="utf-8"))

    sections = {}
    for region, region_countries in targets.items():
        print(f"  generating outlook: {region} ({len(region_countries)} countries)", file=sys.stderr)
        user_message = _build_user_message(region, region_countries, events)
        try:
            sections[region] = _coerce_opportunities(_call_with_forced_tool(
                client, model, SYSTEM_PROMPT, _OUTLOOK_TOOL, user_message,
                # 12k, not 8k: Central America & Caribbean (10 countries)
                # repeatedly produced an unparseable opportunities payload at
                # 8k -- consistent with the emission being squeezed at the
                # ceiling even when stop_reason doesn't report truncation.
                context_label=f"regional outlook: {region}", max_tokens=12000,
            ))
        except Exception as e:
            print(f"    FAILED for {region}: {e}", file=sys.stderr)
            if "credit balance is too low" in str(e):
                print("    CREDITS EXHAUSTED -- stopping.", file=sys.stderr)
                break

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "regions": sections,
    }


def load_regional_outlook(path: Path = OUTPUT_PATH) -> dict:
    """Reads the cached outlook. Returns {} if not yet generated."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def main():
    parser = argparse.ArgumentParser(description="Generate the Regional Economic Outlook")
    parser.add_argument("--region", type=str, default=None,
                         help="Single region name (omit for all core-mandate regions)")
    args = parser.parse_args()

    output = generate_outlook(regions=[args.region] if args.region else None)
    if args.region and OUTPUT_PATH.exists():
        # Single-region rerun merges into the existing file rather than
        # dropping the other 8 regions.
        existing = load_regional_outlook()
        existing.get("regions", {}).update(output["regions"])
        existing["generated_at"] = output["generated_at"]
        output = existing
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Wrote outlook for {len(output['regions'])} region(s) to {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
