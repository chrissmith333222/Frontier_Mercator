"""
scripts/lib/market_data.py

Live stock/index quote fetching for the Markets & Economy dashboard's
ticker banner. Unlike almost everything else in this project, this is
called LIVE from the deployed Streamlit app, not pre-cached and
committed -- a deliberate departure from the established "keep API calls
off the deployed app" pattern used for the Anthropic/Voyage reasoning
pipeline. That pattern exists specifically to keep paid, secret-keyed API
calls and their cost/abuse surface off the public site; neither applies
here: Yahoo Finance quote data via yfinance needs no API key (nothing to
protect) and is free (no per-call cost to control), and "live" is the
entire point of a market ticker -- a cached yesterday's price would
defeat the feature.

Usage (as a module):
    from scripts.lib.market_data import fetch_market_snapshot
    snapshot = fetch_market_snapshot()
"""

import warnings

import yfinance as yf

# US benchmark indices.
US_INDICES = [
    ("^DJI", "Dow Jones"),
    ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq"),
]

# Foreign markets -- a deliberate mix of major global exchanges plus the
# two core-mandate regions' own benchmarks (Brazil, Argentina, South
# Africa), not just the usual London/Tokyo/Hong Kong set.
FOREIGN_INDICES = [
    ("^FTSE", "London (FTSE 100)"),
    ("^GDAXI", "Frankfurt (DAX)"),
    ("^N225", "Tokyo (Nikkei 225)"),
    ("^HSI", "Hong Kong (Hang Seng)"),
    ("^BVSP", "São Paulo (Bovespa)"),
    ("^MERV", "Buenos Aires (Merval)"),
    ("^JN0U.JO", "Johannesburg (FTSE/JSE Top 40)"),
]

# "Biggest American companies or relevant market movers" -- mega-cap
# benchmarks everyone recognizes, plus a deliberate second half tied to
# this platform's own investment thesis (critical minerals/mining,
# infrastructure, defense, energy) rather than a generic tech-only list.
MARKET_MOVERS = [
    ("AAPL", "Apple"),
    ("MSFT", "Microsoft"),
    ("NVDA", "NVIDIA"),
    ("AMZN", "Amazon"),
    ("GOOGL", "Alphabet"),
    ("FCX", "Freeport-McMoRan (copper/critical minerals)"),
    ("CAT", "Caterpillar (infrastructure/mining equipment)"),
    ("LMT", "Lockheed Martin (defense)"),
    ("XOM", "ExxonMobil (energy/commodities)"),
]


def _fetch_quotes(symbol_labels: list[tuple[str, str]], tickers_factory=None) -> list[dict]:
    """Fetches last price + previous close for each (symbol, label) pair
    via a single batched yf.Tickers call, skipping any symbol that fails
    or has incomplete data rather than crashing the whole snapshot --
    Yahoo Finance's free endpoint is not guaranteed-uptime, and one bad
    ticker shouldn't take down the whole ticker banner. `tickers_factory`
    is injectable for tests (a fake with a matching `.tickers` dict
    surface); omit it in real use to call the live yf.Tickers."""
    if tickers_factory is None:
        tickers_factory = yf.Tickers
    symbols = [s for s, _ in symbol_labels]

    quotes = []
    # yfinance's internal pandas/numpy calls emit noisy DeprecationWarnings
    # lazily -- during fast_info property access on each ticker, not just
    # at Tickers() construction -- so the suppression needs to wrap the
    # whole fetch loop, not just the constructor call.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tickers = tickers_factory(" ".join(symbols))
        for symbol, label in symbol_labels:
            try:
                info = tickers.tickers[symbol].fast_info
                price = info.get("lastPrice")
                prev_close = info.get("previousClose")
                if price is None or prev_close is None or prev_close == 0:
                    continue
                change = price - prev_close
                change_pct = (change / prev_close) * 100
                quotes.append({
                    "symbol": symbol, "label": label,
                    "price": round(price, 2), "change": round(change, 2),
                    "change_pct": round(change_pct, 2),
                })
            except Exception:
                continue
    return quotes


def fetch_market_snapshot(tickers_factory=None) -> dict:
    """Returns {"us_indices", "foreign_indices", "movers"}, each a list of
    quote dicts. Any category can come back empty if Yahoo Finance is
    unreachable -- callers should handle an all-empty snapshot gracefully
    (show a "market data unavailable" message, not crash). `tickers_factory`
    is injectable for tests."""
    from datetime import datetime, timezone
    return {
        "us_indices": _fetch_quotes(US_INDICES, tickers_factory),
        "foreign_indices": _fetch_quotes(FOREIGN_INDICES, tickers_factory),
        "movers": _fetch_quotes(MARKET_MOVERS, tickers_factory),
        # When the quotes were actually pulled from Yahoo Finance -- the
        # dashboard caches this snapshot (5-min TTL) AND Streamlit only
        # reruns on user interaction, so displayed quotes can be older
        # than they look; Chris asked for an explicit "current as of"
        # stamp after catching stale values at market open.
        "fetched_at": datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC"),
    }
