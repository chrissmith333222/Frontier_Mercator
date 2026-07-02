"""
scripts/analytics/risk_scorecard.py

Decomposed, comparable country risk scorecards -- the "break one blended
score into inspectable sub-dimensions on a consistent 0-10 scale" pattern
used by Bloomberg's geopolitical risk scores and Verisk Maplecroft, rather
than a single opaque composite number. Three dimensions, chosen because
they map cleanly onto data this project actually has (no sanctions/PEP,
trade-flow, or FX/reserves data yet -- see project memory on data-
completeness gaps):

  - Security Risk: conflict + explosion/remote-violence events (has a
    native 0-10 severity_score already).
  - Political Stability Risk: protest/civil-unrest + political-violence-
    against-civilians event frequency (these categories don't reliably
    carry a severity_score, so this dimension is frequency-based).
  - Economic Risk: inflation, current account balance, government debt
    (%GDP), and GDP growth, each mapped to 0-10 via simple published-
    threshold heuristics (modeled loosely on IMF/World Bank debt-
    sustainability traffic-light conventions) and averaged.

This is a deterministic, transparent scoring formula, not a rated
agency's proprietary model or an AI judgment call -- every sub-score is
directly traceable to a threshold function, which matters given this
feeds "investment risk" claims. All sub-scores plus an overall average
are written to data/scorecards/<iso3>_scorecard.json (git-committed,
same static-artifact pattern as country assessments/custom analyses --
the deployed dashboard reads this file, it doesn't compute scores live).

Usage (CLI):
    python scripts/analytics/risk_scorecard.py --iso3 KEN
    python scripts/analytics/risk_scorecard.py --all-core-mandate

Usage (as a module):
    from scripts.analytics.risk_scorecard import build_country_scorecard
    scorecard = build_country_scorecard("KEN", "Kenya")
"""

import sys
import json
import argparse
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.knowledge.build_knowledge_base import DB_PATH
from scripts.knowledge.queries import countries_with_data

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCORECARD_DIR = REPO_ROOT / "data" / "scorecards"

SECURITY_CATEGORIES = ("conflict", "explosion_remote_violence")
STABILITY_CATEGORIES = ("protest_civil_unrest", "political_violence_targeting_civilians")

# Indicator concept -> the WorldBank/IMF codes that represent it (checked
# in order; first one with data for the country wins). Both sources use
# different codes for the same concept, see scripts/lib/worldbank_indicators.py
# and scripts/lib/imf_indicators.py.
INDICATOR_CODES = {
    "inflation": ["FP.CPI.TOTL.ZG", "PCPIPCH"],
    "current_account": ["BN.CAB.XOKA.GD.ZS", "BCA_NGDPD"],
    "debt_pct_gdp": ["GGXWDG_NGDP"],  # World Bank's debt indicator is total USD, not %GDP -- IMF's is comparable across countries
    "gdp_growth": ["NY.GDP.MKTP.KD.ZG", "NGDP_RPCH"],
}


def _threshold_score(value: float, breakpoints: list[tuple[float, float]]) -> float:
    """breakpoints is a list of (value_at_or_below, score) pairs, ascending
    by value; returns the score for the first breakpoint the value doesn't
    exceed, or the last score if it exceeds all of them."""
    for threshold, score in breakpoints:
        if value <= threshold:
            return score
    return breakpoints[-1][1]


def _inflation_risk(pct: float) -> float:
    return _threshold_score(pct, [(3, 1), (8, 4), (20, 7), (float("inf"), 10)])


def _current_account_risk(pct_of_gdp: float) -> float:
    # More negative (larger external financing need) = higher risk.
    return _threshold_score(-pct_of_gdp, [(0, 1), (2, 3), (5, 6), (float("inf"), 10)])


def _debt_risk(pct_of_gdp: float) -> float:
    return _threshold_score(pct_of_gdp, [(40, 2), (60, 4), (90, 7), (float("inf"), 10)])


def _growth_risk(pct: float) -> float:
    # Lower/negative growth = higher risk.
    return _threshold_score(-pct, [(-4, 1), (-2, 3), (0, 5), (float("inf"), 9)])


_RISK_FUNCTIONS = {
    "inflation": _inflation_risk,
    "current_account": _current_account_risk,
    "debt_pct_gdp": _debt_risk,
    "gdp_growth": _growth_risk,
}


def _latest_indicator_values(conn: sqlite3.Connection, iso3: str) -> dict[str, float]:
    """For each indicator concept, finds the most recent value among its
    known WB/IMF codes for this country. Values are parsed out of
    narrative_summary text (e.g. "Inflation: 4.2% (2025)") since the
    normalized schema doesn't break the numeric value into its own
    column -- see scripts/ingestion/worldbank_normalize.py's _format_value."""
    import re
    values = {}
    for concept, codes in INDICATOR_CODES.items():
        for code in codes:
            rows = conn.execute(
                "SELECT narrative_summary FROM events WHERE iso3 = ? AND event_subtype = ? "
                "ORDER BY event_date DESC LIMIT 1",
                (iso3, code),
            ).fetchall()
            if rows:
                match = re.search(r"(-?\d+\.?\d*)\s*%", rows[0][0])
                if match:
                    values[concept] = float(match.group(1))
                    break
    return values


def build_country_scorecard(iso3: str, country_name: str, db_path: Path = DB_PATH) -> dict:
    """Computes the three risk dimensions for one country from the
    knowledge base. Returns a dict with each sub-score (0-10, higher =
    higher risk), an overall average of whichever dimensions had enough
    data to compute, and the raw inputs behind each score for
    transparency."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        max_date_row = conn.execute("SELECT MAX(event_date) FROM events WHERE iso3 = ?", (iso3,)).fetchone()
        as_of = max_date_row[0] if max_date_row and max_date_row[0] else datetime.now(timezone.utc).date().isoformat()
        window_start = (datetime.fromisoformat(as_of[:10]) - timedelta(days=365)).date().isoformat()

        security_events = conn.execute(
            f"SELECT severity_score FROM events WHERE iso3 = ? AND event_date >= ? "
            f"AND event_category IN ({','.join('?' * len(SECURITY_CATEGORIES))}) AND severity_score IS NOT NULL",
            (iso3, window_start, *SECURITY_CATEGORIES),
        ).fetchall()
        stability_count = conn.execute(
            f"SELECT COUNT(*) FROM events WHERE iso3 = ? AND event_date >= ? "
            f"AND event_category IN ({','.join('?' * len(STABILITY_CATEGORIES))})",
            (iso3, window_start, *STABILITY_CATEGORIES),
        ).fetchone()[0]

        indicator_values = _latest_indicator_values(conn, iso3)
    finally:
        conn.close()

    scores = {}
    inputs = {"as_of": as_of, "trailing_window_days": 365}

    if security_events:
        severities = [row[0] for row in security_events]
        avg_severity = sum(severities) / len(severities)
        frequency_score = min(10, len(severities) / 5)
        scores["security_risk"] = round(0.6 * avg_severity + 0.4 * frequency_score, 1)
        inputs["security"] = {"event_count": len(severities), "avg_severity": round(avg_severity, 2)}
    else:
        scores["security_risk"] = None
        inputs["security"] = {"event_count": 0}

    scores["political_stability_risk"] = round(min(10, stability_count / 4), 1) if stability_count else 0.0
    inputs["political_stability"] = {"event_count": stability_count}

    econ_sub_scores = {}
    for concept, value in indicator_values.items():
        econ_sub_scores[concept] = _RISK_FUNCTIONS[concept](value)
    scores["economic_risk"] = round(sum(econ_sub_scores.values()) / len(econ_sub_scores), 1) if econ_sub_scores else None
    inputs["economic"] = {"raw_values": indicator_values, "sub_scores": econ_sub_scores}

    computable = [v for v in scores.values() if v is not None]
    overall = round(sum(computable) / len(computable), 1) if computable else None

    return {
        "iso3": iso3,
        "country": country_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scores": scores,
        "overall_risk": overall,
        "methodology_inputs": inputs,
    }


def save_scorecard(scorecard: dict, output_dir: Path = SCORECARD_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{scorecard['iso3']}_scorecard.json"
    path.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description="Build a decomposed country risk scorecard")
    parser.add_argument("--iso3", type=str, help="Single country ISO3 code, e.g. KEN")
    parser.add_argument("--all-core-mandate", action="store_true",
                         help="Generate scorecards for every core-mandate country with data")
    parser.add_argument("--min-events", type=int, default=10)
    args = parser.parse_args()

    if not args.iso3 and not args.all_core_mandate:
        parser.error("Specify --iso3 <CODE> or --all-core-mandate")

    if args.iso3:
        countries = [c for c in countries_with_data() if c["iso3"] == args.iso3]
    else:
        countries = [c for c in countries_with_data() if c["in_core_mandate"] and c["n"] >= args.min_events]

    print(f"Building scorecards for {len(countries)} countries...", file=sys.stderr)
    for c in countries:
        scorecard = build_country_scorecard(c["iso3"], c["country"])
        path = save_scorecard(scorecard)
        print(f"  {c['country']} ({c['iso3']}): overall={scorecard['overall_risk']} -> {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
