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
for Nigeria/Angola, iron ore for Guinea/Liberia/Mauritania/Brazil,
cotton for Mali/Burkina Faso/Benin, orange juice for Brazil, etc.).

Cobalt and titanium have no genuine Yahoo Finance futures ticker --
verified directly (not assumed): the tickers that look right by mnemonic
("CB=F", "TIO=F") actually resolve to Cash-Settled Butter and Iron Ore
respectively, not cobalt/titanium. Iron Ore turned out to be a real,
useful addition in its own right (kept below); the butter mismatch was
discarded. Lithium and uranium have no direct futures either, but do
have liquid sector ETFs (LIT, URA) that serve as an investable proxy for
the underlying commodity theme -- labeled "(ETF proxy)" wherever shown so
it's never confused with an actual spot/futures price.

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
    "PA=F": "Palladium",
    "ALI=F": "Aluminum",
    "TIO=F": "Iron Ore",
    "CL=F": "Crude Oil (WTI)",
    "BZ=F": "Crude Oil (Brent)",
    "NG=F": "Natural Gas",
    "KC=F": "Coffee",
    "CC=F": "Cocoa",
    "SB=F": "Sugar",
    "ZW=F": "Wheat",
    "ZC=F": "Corn",
    "ZS=F": "Soybeans",
    "ZR=F": "Rice",
    "CT=F": "Cotton",
    "LE=F": "Live Cattle",
    "OJ=F": "Orange Juice",
    "LIT": "Lithium (ETF proxy)",
    "URA": "Uranium (ETF proxy)",
}

# event_category/type grouping for the dashboard's Commodities tab, since a
# flat 21-row list is harder to scan than one organized by theme (Chris:
# "gaining a picture of the global market and investment opportunities and
# risk across regions and countries").
COMMODITY_GROUPS = {
    "Energy": ["Crude Oil (WTI)", "Crude Oil (Brent)", "Natural Gas"],
    "Metals": ["Copper", "Gold", "Silver", "Platinum", "Palladium", "Aluminum", "Iron Ore"],
    "Battery/Critical Minerals": ["Lithium (ETF proxy)", "Uranium (ETF proxy)"],
    "Agriculture": ["Coffee", "Cocoa", "Sugar", "Wheat", "Corn", "Soybeans", "Rice", "Cotton",
                     "Live Cattle", "Orange Juice"],
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


def fetch_commodity_snapshot(tickers_factory=None) -> dict:
    """Live current price + daily change per commodity, grouped by
    COMMODITY_GROUPS -- the Commodities tab's equivalent of the stock
    ticker's live snapshot (scripts/lib/market_data.py). Reuses
    market_data's _fetch_quotes helper (same free, keyless Yahoo Finance
    quote fetch, same "live calls are fine here, nothing paid/secret to
    protect" reasoning as the stock ticker) rather than duplicating it.
    Returns {"groups": {group_name: [quote, ...]}, "fetched_at": ...}."""
    from datetime import datetime, timezone
    from scripts.lib.market_data import _fetch_quotes

    symbol_labels = list(COMMODITIES.items())
    quotes = _fetch_quotes(symbol_labels, tickers_factory)
    quotes_by_label = {q["label"]: q for q in quotes}

    groups = {}
    for group_name, labels in COMMODITY_GROUPS.items():
        group_quotes = [quotes_by_label[label] for label in labels if label in quotes_by_label]
        if group_quotes:
            groups[group_name] = group_quotes

    return {
        "groups": groups,
        "fetched_at": datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC"),
    }


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
