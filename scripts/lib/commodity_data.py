"""
scripts/lib/commodity_data.py

Monthly commodity price history via Yahoo Finance futures (yfinance,
already a project dependency, free/keyless -- same reasoning as the live
stock ticker exception). This is the data layer that makes Chris's
"correlation between Chinese development bank investment and the price
of a certain commodity" analyses possible at all -- the platform had no
commodity prices ingested before this.

Tickers chosen for relevance to African/LatAm frontier-market economies
(copper for Zambia/DRC/Chile/Peru, gold for Ghana/Mali/Burkina Faso,
cocoa for Ivory Coast/Ghana, coffee for Ethiopia/Colombia/Brazil, oil
for Nigeria/Angola, etc.). Cobalt and lithium have no Yahoo Finance
futures ticker -- noted as a gap, not silently skipped.

Backend-only batch script: writes data/normalized/commodity_prices.json
(committed, small -- a few KB per commodity), read statically by the
correlation engine and dashboard.

Usage:
    python scripts/lib/commodity_data.py   # refresh the cached file
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

COMMODITIES = {
    "HG=F": "Copper",
    "GC=F": "Gold",
    "SI=F": "Silver",
    "PL=F": "Platinum",
    "CL=F": "Crude Oil (WTI)",
    "BZ=F": "Crude Oil (Brent)",
    "NG=F": "Natural Gas",
    "KC=F": "Coffee",
    "CC=F": "Cocoa",
    "SB=F": "Sugar",
    "ZW=F": "Wheat",
}

OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "normalized" / "commodity_prices.json"


def fetch_commodity_history(period: str = "5y") -> dict:
    """Fetches monthly closing prices for every commodity in COMMODITIES.
    Returns {commodity_name: {"YYYY-MM": close_price, ...}}. Skips (with a
    warning) any single ticker that fails rather than failing the batch."""
    import yfinance as yf

    result = {}
    for ticker, name in COMMODITIES.items():
        try:
            history = yf.Ticker(ticker).history(period=period, interval="1mo")
            if history.empty:
                print(f"  WARNING: no data for {name} ({ticker}), skipping", file=sys.stderr)
                continue
            monthly = {
                idx.strftime("%Y-%m"): round(float(row["Close"]), 4)
                for idx, row in history.iterrows()
            }
            result[name] = monthly
            print(f"  {name}: {len(monthly)} months", file=sys.stderr)
        except Exception as e:
            print(f"  WARNING: {name} ({ticker}) failed, skipping: {e}", file=sys.stderr)
    return result


def load_commodity_prices(path: Path = OUTPUT_PATH) -> dict:
    """Reads the cached commodity price file. Returns {} if it hasn't been
    generated yet, so callers degrade gracefully."""
    if not path.exists():
        return {}
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        return cached.get("prices", {})
    except (json.JSONDecodeError, OSError):
        return {}


def main():
    prices = fetch_commodity_history()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "prices": prices,
    }, indent=2), encoding="utf-8")
    print(f"Wrote {len(prices)} commodity series to {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
