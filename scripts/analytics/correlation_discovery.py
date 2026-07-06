"""
scripts/analytics/correlation_discovery.py

Chris's cross-cutting correlation engine: "run a regression alongside
multiple variables to understand causal or correlation relationships...
lots and lots of times across regions, countries, and data types to help
discover correlation and insights that previously would have been
hidden... I don't want to see every single regression you run, just ones
that provide key insights."

Three stages, exactly mirroring that ask:
  1. build_country_panel(): country-month panel series from the merged
     dataset (conflict/protest/political-violence/investment event counts
     and mean conflict severity) plus monthly commodity prices
     (scripts/lib/commodity_data.py).
  2. scan_correlations(): Pearson correlation on every (country series x
     commodity) and (country series x country series) pair, at lags 0-3
     months, for every core-mandate country with enough data. Screens
     with a Fisher z-transform p-value (stdlib math.erf -- scipy is
     deliberately NOT a dependency of this project) and hard thresholds
     on effect size, significance, and sample size. Hundreds/thousands of
     tests run; only the strongest survive -- and because that many tests
     GUARANTEE some spurious "significant" hits (multiple-comparisons
     problem), the thresholds are strict and stage 3 exists.
  3. Claude filter (curate_insights()): the surviving statistical hits go
     to Claude, which is explicitly told these may be spurious and asked
     to select only findings that are economically plausible AND
     investment-relevant, writing each up in plain language with the
     mandatory correlation-is-not-causation caveat. Output saved to
     data/insights/discovered_insights.json (committed, read statically
     by the dashboard -- same cached-artifact pattern as assessments).

This is correlation screening, NOT causal inference -- no
instrumental variables, no controls, no identification strategy. The
system prompt forces every published insight to carry that caveat.

Usage:
    python scripts/analytics/correlation_discovery.py            # scan + curate + save
    python scripts/analytics/correlation_discovery.py --scan-only  # just print stats, no LLM call
"""

import sys
import os
import json
import math
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from scripts.lib.commodity_data import load_commodity_prices
from scripts import branding as b

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MERGED_PATH = REPO_ROOT / "data" / "normalized" / "merged_dataset.json"
INSIGHTS_PATH = REPO_ROOT / "data" / "insights" / "discovered_insights.json"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

MIN_MONTHS = 18          # minimum overlapping months for a pair to be tested
MIN_ABS_R = 0.45         # minimum |Pearson r| to survive screening
MAX_P_VALUE = 0.005      # strict, because we run hundreds of tests (multiple comparisons)
MAX_LAG_MONTHS = 3

CURATION_SYSTEM_PROMPT = """You are a quantitative research reviewer at an emerging-markets \
investment firm. You will receive a list of statistically significant correlations discovered by \
an automated screen over country-month event data (conflict, protest, political violence, \
development-finance investment activity) and monthly commodity prices.

Critical context: the screen ran hundreds of tests, so SOME of these hits are guaranteed to be \
spurious despite passing significance thresholds (multiple-comparisons problem), and correlation \
is never causation. Your job is to select ONLY the findings that are (a) economically plausible -- \
there's a believable mechanism connecting the two series, (b) genuinely investment-relevant -- they \
could shape an allocation, entry-timing, or risk-monitoring decision for a frontier-markets \
investor, and (c) non-obvious enough to be worth surfacing. Reject mechanical artifacts (two series \
that both just trend upward), tautologies (conflict correlating with political violence in the same \
country), and anything whose only plausible explanation is chance.

For each finding you keep, write 2-3 sentences of plain-language insight for an investor audience, \
name the plausible mechanism, and state the correlation-is-not-causation caveat concretely (what \
confounder or reverse causality could explain it). Record via the record_curated_insights tool."""

_CURATION_TOOL = {
    "name": "record_curated_insights",
    "description": "Records the curated subset of investment-relevant correlation findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "insights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "headline": {"type": "string", "description": "One-line plain-language finding."},
                        "detail": {"type": "string", "description": "2-3 sentences: the finding, the plausible mechanism, and what it could mean for investment strategy."},
                        "caveat": {"type": "string", "description": "Concrete correlation-vs-causation caveat: what confounder or reverse causality could explain this."},
                        "country": {"type": "string"},
                        "series_x": {"type": "string"},
                        "series_y": {"type": "string"},
                        "r": {"type": "number"},
                        "lag_months": {"type": "number"},
                        "n_months": {"type": "number"},
                    },
                    "required": ["headline", "detail", "caveat", "country", "series_x", "series_y", "r", "lag_months", "n_months"],
                },
            },
        },
        "required": ["insights"],
    },
}


def _fisher_p_value(r: float, n: int) -> float:
    """Two-sided p-value for a Pearson correlation via the Fisher
    z-transform and a normal approximation (z = atanh(r) * sqrt(n-3)) --
    stdlib-only, no scipy. Standard screening approximation; fine for
    filtering, not for publication-grade inference (which stage 3's
    curation layer isn't claiming anyway)."""
    if n <= 3 or abs(r) >= 1.0:
        return 1.0 if abs(r) < 1.0 else 0.0
    z = math.atanh(r) * math.sqrt(n - 3)
    return 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))


def build_country_panel(df: pd.DataFrame, country: str) -> pd.DataFrame:
    """Country-month panel: event counts per category plus mean conflict
    severity, indexed by 'YYYY-MM' period strings."""
    scope = df[df["country"] == country].copy()
    if scope.empty:
        return pd.DataFrame()
    scope["month"] = pd.to_datetime(scope["event_date"], errors="coerce").dt.strftime("%Y-%m")
    scope = scope.dropna(subset=["month"])

    panel = pd.DataFrame(index=sorted(scope["month"].unique()))
    for category, label in [
        ("conflict", "conflict_events"),
        ("protest_civil_unrest", "protest_events"),
        ("political_violence_targeting_civilians", "political_violence_events"),
        ("investment", "investment_events"),
    ]:
        counts = scope[scope["event_category"] == category].groupby("month").size()
        panel[label] = counts
    severity = scope[scope["event_category"] == "conflict"].groupby("month")["severity_score"].mean()
    panel["mean_conflict_severity"] = severity
    return panel.fillna(0.0)


def scan_correlations(df: pd.DataFrame, commodities: dict) -> list[dict]:
    """Runs the full screen: every core-mandate country x every
    (country-series, commodity) and (country-series, country-series) pair
    x lags 0..MAX_LAG_MONTHS. Returns hits passing all thresholds, sorted
    by |r| descending. `commodities` is {name: {"YYYY-MM": price}}."""
    commodity_series = {
        name: pd.Series(prices).sort_index() for name, prices in commodities.items()
    }
    countries = sorted(df.loc[df["in_core_mandate"] == True, "country"].dropna().unique())  # noqa: E712

    hits = []
    for country in countries:
        panel = build_country_panel(df, country)
        if len(panel) < MIN_MONTHS:
            continue

        candidate_pairs = []
        panel_cols = [c for c in panel.columns if panel[c].std() > 0]
        for col in panel_cols:
            for commodity_name, series in commodity_series.items():
                candidate_pairs.append((col, panel[col], commodity_name, series))
        # Country-internal cross-category pairs (e.g. investment vs conflict) --
        # skip same-family tautologies (conflict vs political violence vs
        # protest all measure closely related unrest; correlating them is
        # trivially true and the curation prompt would reject them anyway,
        # so don't waste tests on them).
        unrest_family = {"conflict_events", "protest_events", "political_violence_events", "mean_conflict_severity"}
        for i, col_a in enumerate(panel_cols):
            for col_b in panel_cols[i + 1:]:
                if col_a in unrest_family and col_b in unrest_family:
                    continue
                candidate_pairs.append((col_a, panel[col_a], col_b, panel[col_b]))

        for name_x, series_x, name_y, series_y in candidate_pairs:
            for lag in range(0, MAX_LAG_MONTHS + 1):
                # Positive lag: X leads Y by `lag` months (X at t vs Y at t+lag).
                shifted_y = series_y.copy()
                shifted_y.index = [
                    (pd.Period(m, freq="M") - lag).strftime("%Y-%m") for m in shifted_y.index
                ]
                aligned = pd.concat([series_x, shifted_y], axis=1, join="inner").dropna()
                n = len(aligned)
                if n < MIN_MONTHS:
                    continue
                x, y = aligned.iloc[:, 0].astype(float), aligned.iloc[:, 1].astype(float)
                if x.std() == 0 or y.std() == 0:
                    continue
                r = float(np.corrcoef(x, y)[0, 1])
                if not math.isfinite(r) or abs(r) < MIN_ABS_R:
                    continue
                p = _fisher_p_value(r, n)
                if p > MAX_P_VALUE:
                    continue
                hits.append({
                    "country": country, "series_x": name_x, "series_y": name_y,
                    "lag_months": lag, "r": round(r, 3), "p_value": round(p, 6), "n_months": n,
                })
    return sorted(hits, key=lambda h: -abs(h["r"]))


def curate_insights(hits: list[dict], model: str = DEFAULT_MODEL, client=None, max_hits: int = 60) -> list[dict]:
    """Stage 3: Claude selects the economically plausible,
    investment-relevant subset and writes plain-language insight text.
    `client` injectable for tests."""
    if not hits:
        return []
    if client is None:
        load_dotenv()
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to your .env file -- never paste it into chat.")
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=model,
        max_tokens=6000,
        system=CURATION_SYSTEM_PROMPT,
        tools=[_CURATION_TOOL],
        tool_choice={"type": "tool", "name": "record_curated_insights"},
        messages=[{
            "role": "user",
            "content": (
                "Statistically significant correlations from the automated screen "
                f"(top {max_hits} by |r|; lag_months > 0 means the first series leads the second):\n"
                + json.dumps(hits[:max_hits], indent=2)
            ),
        }],
    )
    tool_blocks = [blk for blk in response.content if getattr(blk, "type", None) == "tool_use"]
    if not tool_blocks:
        raise RuntimeError("No tool_use block in curation response")
    from scripts.analysis.reasoning_agent import _normalize_tool_output
    output = _normalize_tool_output(tool_blocks[0].input, _CURATION_TOOL)
    insights = output.get("insights", [])
    # _normalize_tool_output flattens unknown shapes to strings; keep only dicts.
    return [i for i in insights if isinstance(i, dict)]


def main():
    parser = argparse.ArgumentParser(description="Cross-cutting correlation discovery")
    parser.add_argument("--scan-only", action="store_true",
                         help="Run the statistical screen and print hits without the LLM curation call.")
    args = parser.parse_args()

    df = pd.DataFrame(json.loads(MERGED_PATH.read_text(encoding="utf-8")))
    commodities = load_commodity_prices()
    if not commodities:
        print("No commodity prices cached -- run scripts/lib/commodity_data.py first.", file=sys.stderr)
        sys.exit(1)

    print("Scanning correlations...", file=sys.stderr)
    hits = scan_correlations(df, commodities)
    print(f"{len(hits)} statistically significant hits "
          f"(|r|>={MIN_ABS_R}, p<={MAX_P_VALUE}, n>={MIN_MONTHS} months)", file=sys.stderr)

    if args.scan_only:
        for h in hits[:30]:
            print(f"  {h['country']}: {h['series_x']} vs {h['series_y']} "
                  f"(lag {h['lag_months']}mo): r={h['r']}, p={h['p_value']}, n={h['n_months']}")
        return

    print("Curating with Claude...", file=sys.stderr)
    insights = curate_insights(hits)
    INSIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    INSIGHTS_PATH.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_hits_screened": len(hits),
        "insights": insights,
    }, indent=2), encoding="utf-8")
    print(f"Kept {len(insights)}/{len(hits)} as investment-relevant insights -> {INSIGHTS_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
