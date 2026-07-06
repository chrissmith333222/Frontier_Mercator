"""
tests/test_market_data.py

Tests the market data snapshot's quote computation (change/change_pct
math) and graceful-degradation behavior with a fake yfinance Tickers
factory -- no real network call needed.

Usage:
    python -m pytest tests/test_market_data.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib.market_data import fetch_market_snapshot, _fetch_quotes


class _FakeFastInfo(dict):
    """yfinance's real fast_info is dict-like but not a plain dict;
    plain dict with .get() is a sufficient fake for this module's needs."""
    pass


class _FakeTicker:
    def __init__(self, fast_info):
        self.fast_info = fast_info


class _FakeTickers:
    def __init__(self, symbol_str, fixtures):
        self.tickers = {
            symbol: _FakeTicker(fixtures.get(symbol, {}))
            for symbol in symbol_str.split()
        }


def _make_factory(fixtures):
    return lambda symbol_str: _FakeTickers(symbol_str, fixtures)


def test_fetch_quotes_computes_change_and_percent():
    fixtures = {"AAPL": {"lastPrice": 110.0, "previousClose": 100.0}}
    quotes = _fetch_quotes([("AAPL", "Apple")], tickers_factory=_make_factory(fixtures))
    assert len(quotes) == 1
    assert quotes[0]["price"] == 110.0
    assert quotes[0]["change"] == 10.0
    assert quotes[0]["change_pct"] == 10.0
    print("✓ test_fetch_quotes_computes_change_and_percent passed")


def test_fetch_quotes_negative_change_for_a_decline():
    fixtures = {"XOM": {"lastPrice": 90.0, "previousClose": 100.0}}
    quotes = _fetch_quotes([("XOM", "ExxonMobil")], tickers_factory=_make_factory(fixtures))
    assert quotes[0]["change"] == -10.0
    assert quotes[0]["change_pct"] == -10.0
    print("✓ test_fetch_quotes_negative_change_for_a_decline passed")


def test_fetch_quotes_skips_symbol_with_missing_price():
    fixtures = {
        "AAPL": {"lastPrice": 110.0, "previousClose": 100.0},
        "BROKEN": {},  # no lastPrice/previousClose at all
    }
    quotes = _fetch_quotes(
        [("AAPL", "Apple"), ("BROKEN", "Broken Ticker")],
        tickers_factory=_make_factory(fixtures),
    )
    assert len(quotes) == 1
    assert quotes[0]["symbol"] == "AAPL"
    print("✓ test_fetch_quotes_skips_symbol_with_missing_price passed")


def test_fetch_quotes_skips_symbol_that_raises():
    class _RaisingTickers:
        def __init__(self, symbol_str):
            class _Raiser:
                @property
                def fast_info(self):
                    raise RuntimeError("network error")
            self.tickers = {s: (_Raiser() if s == "BROKEN" else _FakeTicker({"lastPrice": 1.0, "previousClose": 1.0}))
                             for s in symbol_str.split()}

    quotes = _fetch_quotes(
        [("AAPL", "Apple"), ("BROKEN", "Broken Ticker")],
        tickers_factory=_RaisingTickers,
    )
    assert len(quotes) == 1
    assert quotes[0]["symbol"] == "AAPL"
    print("✓ test_fetch_quotes_skips_symbol_that_raises passed")


def test_fetch_market_snapshot_returns_all_three_categories():
    fixtures = {"^DJI": {"lastPrice": 50000.0, "previousClose": 49500.0}}
    snapshot = fetch_market_snapshot(tickers_factory=_make_factory(fixtures))
    assert set(snapshot.keys()) == {"us_indices", "foreign_indices", "movers", "fetched_at"}
    assert "UTC" in snapshot["fetched_at"]  # freshness stamp shown above the ticker
    dji = next((q for q in snapshot["us_indices"] if q["symbol"] == "^DJI"), None)
    assert dji is not None
    assert dji["change"] == 500.0
    print("✓ test_fetch_market_snapshot_returns_all_three_categories passed")


def test_fetch_market_snapshot_empty_when_all_unavailable():
    snapshot = fetch_market_snapshot(tickers_factory=_make_factory({}))
    assert snapshot["us_indices"] == []
    assert snapshot["foreign_indices"] == []
    assert snapshot["movers"] == []
    print("✓ test_fetch_market_snapshot_empty_when_all_unavailable passed")


if __name__ == "__main__":
    test_functions = [v for k, v in list(globals().items()) if k.startswith("test_")]
    print(f"Running {len(test_functions)} tests...\n")
    failures = 0
    for test_fn in test_functions:
        try:
            test_fn()
        except AssertionError as e:
            failures += 1
            print(f"✗ {test_fn.__name__} FAILED: {e}")
    print(f"\n{len(test_functions) - failures}/{len(test_functions)} tests passed.")
    if failures:
        sys.exit(1)
