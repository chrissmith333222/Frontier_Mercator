"""
tests/test_investment_theses.py

Tests the investment-thesis engine's data logic: instrument validation
(hallucinated tickers dropped, futures allowed only in the aggressive
tier), malformed-output coercion (JSON-stringified and double-nested
thesis payloads, both observed live), and universe verification. No
network or API calls.

Usage:
    python -m pytest tests/test_investment_theses.py -v
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analytics.investment_theses import _validate_instruments, _coerce_thesis_dicts
from scripts.lib.instrument_universe import INSTRUMENTS, verify_universe

FAKE_UNIVERSE = {
    "COPX": ("Global X Copper Miners ETF", "sector_etf", "Copper miners"),
    "EEM": ("iShares MSCI Emerging Markets ETF", "regional_etf", "Broad EM"),
}


def _thesis(instruments):
    return {
        "headline": "Copper outperforms",
        "geography": "Zambia", "sector": "Copper", "horizon_months": 12,
        "conviction": "high", "rationale": "r", "supporting_signals": [], "risks": [],
        "instruments": instruments,
    }


def test_validate_drops_hallucinated_tickers():
    theses = [_thesis({
        "conservative": [{"ticker": "EEM", "role": "broad"}],
        "moderate": [{"ticker": "FAKETICKER", "role": "made up"}],
    })]
    result = _validate_instruments(theses, FAKE_UNIVERSE)
    assert len(result[0]["instruments"]["conservative"]) == 1
    assert result[0]["instruments"]["moderate"] == []
    print("✓ test_validate_drops_hallucinated_tickers passed")


def test_validate_attaches_metadata():
    theses = [_thesis({"conservative": [{"ticker": "COPX", "role": "focused"}], "moderate": []})]
    result = _validate_instruments(theses, FAKE_UNIVERSE)
    inst = result[0]["instruments"]["conservative"][0]
    assert inst["name"] == "Global X Copper Miners ETF"
    assert inst["layer"] == "sector_etf"
    print("✓ test_validate_attaches_metadata passed")


def test_validate_allows_futures_only_in_aggressive_tier():
    theses = [_thesis({
        "conservative": [{"ticker": "HG=F", "role": "copper futures"}],
        "moderate": [],
        "aggressive": [{"ticker": "HG=F", "role": "copper futures"}],
    })]
    result = _validate_instruments(theses, FAKE_UNIVERSE)
    assert result[0]["instruments"]["conservative"] == []  # futures too risky for this tier
    assert len(result[0]["instruments"]["aggressive"]) == 1
    assert result[0]["instruments"]["aggressive"][0]["layer"] == "futures"
    print("✓ test_validate_allows_futures_only_in_aggressive_tier passed")


def test_coerce_parses_json_stringified_thesis_items():
    stringified = json.dumps(_thesis({"conservative": [], "moderate": []}))
    result = _coerce_thesis_dicts([stringified, "not json at all"])
    assert len(result) == 1
    assert result[0]["headline"] == "Copper outperforms"
    print("✓ test_coerce_parses_json_stringified_thesis_items passed")


def test_coerce_unwraps_double_nested_payload():
    """Observed live: the model emitted the ENTIRE tool payload as the
    single array item -- {"theses": [{"theses": [...real...]}]}."""
    inner = [_thesis({"conservative": [], "moderate": []}),
              _thesis({"conservative": [], "moderate": []})]
    result = _coerce_thesis_dicts([{"theses": inner, "instruments": {}}])
    assert len(result) == 2
    assert all("headline" in t for t in result)
    print("✓ test_coerce_unwraps_double_nested_payload passed")


def test_verify_universe_drops_untradeable(monkeypatch):
    import pandas as pd

    def fake_history(symbol):
        if symbol == "EEM":
            return pd.DataFrame({"Close": [10.0]})
        return pd.DataFrame()  # everything else: no recent trades

    verified = verify_universe(history_fn=fake_history)
    assert list(verified) == ["EEM"]
    print("✓ test_verify_universe_drops_untradeable passed")


def test_stringified_instruments_dict_recovered():
    theses = [_thesis(json.dumps({"conservative": [{"ticker": "EEM", "role": "broad"}], "moderate": []}))]
    result = _validate_instruments(theses, FAKE_UNIVERSE)
    assert len(result[0]["instruments"]["conservative"]) == 1
    print("✓ test_stringified_instruments_dict_recovered passed")


if __name__ == "__main__":
    import inspect
    test_functions = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"Running {len(test_functions)} tests...\n")
    failures = 0
    for test_fn in test_functions:
        try:
            if "monkeypatch" in inspect.signature(test_fn).parameters:
                test_fn(None)
            else:
                test_fn()
        except AssertionError as e:
            failures += 1
            print(f"✗ {test_fn.__name__} FAILED: {e}")
    print(f"\n{len(test_functions) - failures}/{len(test_functions)} tests passed.")
    if failures:
        sys.exit(1)
