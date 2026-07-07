"""
scripts/analytics/investment_theses.py

The "so what / what now" engine (Chris, 2026-07-07): converts everything
the platform knows -- correlation insights, all 69 country assessments'
investment-opportunity findings, commodity price momentum, and shipping-
connectivity trends -- into a small set of concrete INVESTMENT THESES,
each mapped down the "investment stack" to real, verified, tradeable
instruments at three risk tiers:

  conservative -> broad regional/sector ETFs (most liquid, least specific)
  moderate     -> focused sector ETFs, commodity funds, large multinationals
  aggressive   -> single stocks, direct futures, least-liquid pure plays

Because there is almost never a "Benin Agriculture ETF", the mapping works
through the closest expressible exposure (regional fund, value-chain
multinational, commodity future) -- the model chooses ONLY from the
verified instrument universe (scripts/lib/instrument_universe.py), and a
post-generation validation pass drops any instrument it invents anyway,
so a hallucinated or delisted ticker can never reach the site.

Follows the correlation_discovery.py pattern: backend-only batch script
(one bounded Claude call, never runs on the deployed app), output read
statically by the dashboard's Markets & Economy > Investment Insights tab.

Research/educational output, not individualized investment advice -- the
rendering surfaces carry the same disclaimer as the rest of the platform.

Usage:
    python scripts/analytics/investment_theses.py
    python scripts/analytics/investment_theses.py --max-theses 6
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.analysis.reasoning_agent import _call_with_forced_tool, _get_client, DEFAULT_MODEL
from scripts.lib.instrument_universe import verify_universe
from scripts.lib.commodity_data import load_commodity_prices, COMMODITIES
from scripts.ingestion.unctad_maritime_fetch import load_maritime_stats
from scripts.lib.world_countries import ALL_COUNTRIES

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INSIGHTS_PATH = REPO_ROOT / "data" / "insights" / "discovered_insights.json"
ANALYSIS_DIR = REPO_ROOT / "data" / "analysis"
OUTPUT_PATH = REPO_ROOT / "data" / "insights" / "investment_theses.json"

SYSTEM_PROMPT = """You are the senior investment strategist at Frontier Mercator Group, converting \
the firm's own multi-source intelligence (conflict/security events, macro indicators, development-\
finance flows, commodity prices, shipping connectivity, demographic trends) into actionable \
investment theses for emerging and frontier markets.

Your method is top-down thematic investing: start from what the intelligence actually shows, form \
a falsifiable thesis with a timeframe, then work DOWN the investment stack to the closest \
expressible instruments. Frontier markets rarely have direct instruments -- a thesis on Beninese \
agriculture gets expressed through regional funds, value-chain multinationals that buy West \
African crops, or the underlying commodity, and you say explicitly which layer each instrument \
sits at and what compromise it makes versus the pure thesis.

Rules:
1. Every thesis must be grounded in the supplied intelligence -- cite the specific signals \
(insights, country findings, price/connectivity trends) that support it. No generic EM optimism.
2. Timeframe required: state an explicit horizon in months for each thesis.
3. Instruments: choose ONLY from the supplied verified instrument list (tickers exactly as \
given). Any ticker not on the list will be discarded. For each instrument, one sentence on WHY \
it expresses this thesis and what compromise it makes (e.g. "broad LatAm fund -- diluted but \
liquid exposure to the Peru copper story").
4. Risk tiers reflect instrument character, not conviction: conservative = broad/liquid ETFs; \
moderate = focused sector/country funds and large multinationals; aggressive = single stocks, \
direct commodity exposure, least-liquid pure plays. Populate at least conservative and moderate \
for every thesis; aggressive only when a genuine pure play exists on the list.
5. State the risks that would break each thesis (political, currency, liquidity, execution) -- \
frontier instruments carry structural risks (spreads, tracking error, concentration) beyond the \
thesis being wrong.
6. Voice: confident, declarative, prospectus register. No hedging boilerplate, no "the data \
shows" phrasing -- attribute to real-world sources ("ACLED-recorded unrest", "IMF projections", \
"UNCTAD connectivity data").
7. These are research theses describing how a view COULD be expressed -- not directives to buy \
or sell, and never sized to any individual's situation.

Record your theses using the record_investment_theses tool."""

_THESES_TOOL = {
    "name": "record_investment_theses",
    "description": "Records the generated investment theses with instrument mappings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "theses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "headline": {
                            "type": "string",
                            "description": "The thesis as one declarative sentence with geography, "
                                            "sector, direction, and timeframe -- e.g. 'West African "
                                            "gold producers outperform over the next 12 months as "
                                            "Sahel supply risk keeps prices bid'.",
                        },
                        "geography": {"type": "string", "description": "Country/region the thesis is about."},
                        "sector": {"type": "string", "description": "Sector/theme, e.g. 'Agriculture', 'Copper/critical minerals'."},
                        "horizon_months": {"type": "integer", "description": "Explicit thesis horizon in months."},
                        "conviction": {
                            "type": "string",
                            "enum": ["exploratory", "moderate", "high"],
                            "description": "How strongly the intelligence supports this thesis.",
                        },
                        "rationale": {
                            "type": "string",
                            "description": "1 paragraph: the causal story, citing the specific "
                                            "supporting signals by source.",
                        },
                        "supporting_signals": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "2-4 bullets, each one specific signal from the supplied "
                                            "intelligence (cite source and figure/date).",
                        },
                        "risks": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "2-4 bullets: what breaks this thesis, incl. structural "
                                            "instrument risks (liquidity, currency, tracking).",
                        },
                        "instruments": {
                            "type": "object",
                            "properties": {
                                "conservative": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "ticker": {"type": "string"},
                                            "role": {"type": "string", "description": "Why this expresses the thesis + its compromise."},
                                        },
                                        "required": ["ticker", "role"],
                                    },
                                },
                                "moderate": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "ticker": {"type": "string"},
                                            "role": {"type": "string"},
                                        },
                                        "required": ["ticker", "role"],
                                    },
                                },
                                "aggressive": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "ticker": {"type": "string"},
                                            "role": {"type": "string"},
                                        },
                                        "required": ["ticker", "role"],
                                    },
                                },
                            },
                            "required": ["conservative", "moderate"],
                        },
                    },
                    "required": ["headline", "geography", "sector", "horizon_months", "conviction",
                                  "rationale", "supporting_signals", "risks", "instruments"],
                },
            },
        },
        "required": ["theses"],
    },
}


def _commodity_momentum() -> list[str]:
    """3-month and 12-month % change per commodity from the cached monthly
    series -- deterministic trend context for the model."""
    prices = load_commodity_prices()
    lines = []
    for name, series in prices.items():
        months = sorted(series)
        if len(months) < 13:
            continue
        latest, m3, m12 = series[months[-1]], series[months[-4]], series[months[-13]]
        if not m3 or not m12:
            continue
        lines.append(f"{name}: {(latest - m3) / m3 * 100:+.1f}% over 3 months, "
                      f"{(latest - m12) / m12 * 100:+.1f}% over 12 months (latest {months[-1]})")
    return lines


def _connectivity_movers(top_n: int = 8) -> list[str]:
    """Biggest year-on-year shipping-connectivity gainers/losers (UNCTAD
    LSCI) among tracked countries."""
    lsci = load_maritime_stats().get("lsci", {})
    moves = []
    for country, series in lsci.items():
        quarters = sorted(series)
        if len(quarters) < 5:
            continue
        yoy = series[quarters[-1]] - series[quarters[-5]]
        moves.append((yoy, country, quarters[-1]))
    moves.sort(reverse=True)
    picked = moves[:top_n // 2] + moves[-top_n // 2:]
    return [f"{country}: LSCI {yoy:+.1f} pts year-on-year (as of {q})" for yoy, country, q in picked]


def _country_opportunity_bullets(max_countries: int = 69) -> list[str]:
    """Every country assessment's investment_opportunities bullets, tagged
    by country -- the per-country AI findings feeding the cross-cutting
    thesis layer."""
    bullets = []
    for iso3, (name, _region, mandate) in ALL_COUNTRIES.items():
        if not mandate:
            continue
        path = ANALYSIS_DIR / f"{iso3}_assessment.json"
        if not path.exists():
            continue
        try:
            analysis = json.loads(path.read_text(encoding="utf-8")).get("analysis", {})
        except (json.JSONDecodeError, OSError):
            continue
        for bullet in analysis.get("investment_opportunities", [])[:3]:
            bullets.append(f"[{name}] {bullet}")
    return bullets[: max_countries * 3]


def _build_user_message(universe: dict) -> str:
    insights = []
    if INSIGHTS_PATH.exists():
        data = json.loads(INSIGHTS_PATH.read_text(encoding="utf-8"))
        insights = [f"{i['headline']} -- {i['detail']} (caveat: {i['caveat']})"
                     for i in data.get("insights", [])]

    universe_lines = [f"{ticker} | {name} | {layer} | {note}"
                       for ticker, (name, layer, note) in sorted(universe.items())]
    futures_lines = [f"{ticker} | {name} futures (direct)" for ticker, name in COMMODITIES.items()
                      if not name.endswith("(ETF proxy)")]

    return (
        "INTELLIGENCE INPUTS\n\n"
        "1. Cross-cutting statistical insights (correlation discovery, already curated for "
        "plausibility):\n" + ("\n".join(f"- {s}" for s in insights) or "- none available") + "\n\n"
        "2. Per-country investment-opportunity findings (from the firm's country assessments, "
        "each grounded in development-finance, macro, and security data):\n"
        + "\n".join(f"- {b}" for b in _country_opportunity_bullets()) + "\n\n"
        "3. Commodity price momentum (Yahoo Finance monthly closes):\n"
        + "\n".join(f"- {line}" for line in _commodity_momentum()) + "\n\n"
        "4. Shipping-connectivity movers (UNCTAD Liner Shipping Connectivity Index):\n"
        + "\n".join(f"- {line}" for line in _connectivity_movers()) + "\n\n"
        "VERIFIED INSTRUMENT UNIVERSE (ticker | name | layer | exposure note) -- you may ONLY "
        "use these tickers:\n" + "\n".join(universe_lines) + "\n\n"
        "Direct commodity futures also allowed as AGGRESSIVE-tier instruments only:\n"
        + "\n".join(futures_lines)
    )


def _coerce_thesis_dicts(theses: list) -> list[dict]:
    """The forced-tool output normalizer repairs string-typed array fields,
    but an array of OBJECTS can still arrive with individual items as
    JSON-stringified dicts (observed live on this tool's first run --
    the same malformed-output family as reasoning_agent's _normalize_tool_output
    lesson, one level deeper). Parse those; drop anything unparseable."""
    coerced = []
    for item in theses:
        if isinstance(item, dict):
            if "headline" not in item and isinstance(item.get("theses"), list):
                # Observed live: the model sometimes emits the ENTIRE tool
                # payload as the first (only) array item -- a double-nested
                # {"theses": [{"theses": [...real theses...]}]}. Unwrap.
                coerced.extend(_coerce_thesis_dicts(item["theses"]))
            else:
                coerced.append(item)
        elif isinstance(item, str):
            try:
                parsed = json.loads(item)
                if isinstance(parsed, dict):
                    coerced.append(parsed)
                else:
                    print(f"    dropped non-dict thesis item: {item[:80]!r}", file=sys.stderr)
            except json.JSONDecodeError:
                print(f"    dropped unparseable thesis item: {item[:80]!r}", file=sys.stderr)
    return coerced


def _validate_instruments(theses: list, universe: dict) -> list[dict]:
    """Drops any instrument whose ticker isn't in the verified universe or
    the direct-futures list -- the model is instructed to stay on-list, but
    a hallucinated ticker must never reach the site. Attaches display
    metadata to survivors."""
    futures = {t: n for t, n in COMMODITIES.items() if not n.endswith("(ETF proxy)")}
    theses = _coerce_thesis_dicts(theses)
    for thesis in theses:
        if not isinstance(thesis.get("instruments"), dict):
            try:
                thesis["instruments"] = json.loads(thesis.get("instruments") or "{}")
            except (json.JSONDecodeError, TypeError):
                thesis["instruments"] = {}
        for tier, items in list(thesis.get("instruments", {}).items()):
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except json.JSONDecodeError:
                    items = []
            validated = []
            for item in items or []:
                if isinstance(item, str):
                    try:
                        item = json.loads(item)
                    except json.JSONDecodeError:
                        continue
                if not isinstance(item, dict):
                    continue
                ticker = str(item.get("ticker", "")).strip()
                if ticker in universe:
                    name, layer, _note = universe[ticker]
                    validated.append({**item, "ticker": ticker, "name": name, "layer": layer})
                elif ticker in futures and tier == "aggressive":
                    validated.append({**item, "ticker": ticker, "name": f"{futures[ticker]} futures",
                                       "layer": "futures"})
                else:
                    print(f"    dropped unverified instrument {ticker!r} from '{thesis.get('headline', '?')[:50]}'",
                          file=sys.stderr)
            thesis["instruments"][tier] = validated
    return theses


def generate_theses(model: str = DEFAULT_MODEL, client=None, max_theses: int = 8,
                     universe: dict | None = None) -> dict:
    if client is None:
        client = _get_client()
    if universe is None:
        print("Verifying instrument universe against live listings...", file=sys.stderr)
        universe = verify_universe()
        print(f"  {len(universe)} instruments verified as actively trading", file=sys.stderr)

    user_message = (
        _build_user_message(universe)
        + f"\n\nGenerate the {max_theses} strongest theses this intelligence genuinely supports "
        f"(fewer if the material only supports fewer -- quality over quota)."
    )

    # 16k output tokens: 8 theses x (paragraph rationale + signals + risks +
    # up to 3 instrument tiers with per-instrument role sentences) genuinely
    # runs past 8k -- observed truncation live on the first run.
    result = _call_with_forced_tool(
        client, model, SYSTEM_PROMPT, _THESES_TOOL, user_message,
        context_label="investment theses", max_tokens=16000,
    )
    theses = _validate_instruments(result.get("theses", []), universe)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "instruments_verified": len(universe),
        "theses": theses,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate investment theses with instrument mappings")
    parser.add_argument("--max-theses", type=int, default=8)
    args = parser.parse_args()

    output = generate_theses(max_theses=args.max_theses)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Wrote {len(output['theses'])} theses to {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
