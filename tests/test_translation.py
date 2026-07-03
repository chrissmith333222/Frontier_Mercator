"""
tests/test_translation.py

Tests the batch translation helper's plumbing (tool-call construction,
ordering, defensive padding on a mismatched response count) with a fake
Anthropic client -- no real API key or network call needed.

Usage:
    python -m pytest tests/test_translation.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib.translation import translate_batch


class _FakeToolUseBlock:
    def __init__(self, translations):
        self.type = "tool_use"
        self.input = {"translations": translations}


class _FakeResponse:
    def __init__(self, translations):
        self.content = [_FakeToolUseBlock(translations)]


class _FakeMessages:
    def __init__(self, translations):
        self._translations = translations
        self.last_call_kwargs = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return _FakeResponse(self._translations)


class _FakeClient:
    def __init__(self, translations):
        self.messages = _FakeMessages(translations)


def test_translate_batch_returns_translations_in_order():
    client = _FakeClient(["Mexico announces new measures", "Germany and France sign deal"])
    result = translate_batch(
        ["México anuncia nuevas medidas", "Alemania y Francia firman acuerdo"],
        source_language="Spanish", client=client,
    )
    assert result == ["Mexico announces new measures", "Germany and France sign deal"]


def test_translate_batch_empty_input_returns_empty_without_calling_client():
    client = _FakeClient([])
    result = translate_batch([], source_language="Spanish", client=client)
    assert result == []
    assert client.messages.last_call_kwargs is None


def test_translate_batch_single_tool_call_for_whole_batch():
    texts = ["texto uno", "texto dos", "texto tres"]
    client = _FakeClient(["text one", "text two", "text three"])
    translate_batch(texts, source_language="Spanish", client=client)
    # All three headlines should be sent in ONE message, not one call each.
    sent_message = client.messages.last_call_kwargs["messages"][0]["content"]
    assert "texto uno" in sent_message and "texto tres" in sent_message


def test_translate_batch_pads_on_short_response():
    texts = ["a", "b", "c"]
    client = _FakeClient(["translated a"])  # model only returned 1 of 3
    result = translate_batch(texts, source_language="French", client=client)
    assert len(result) == 3
    assert result[0] == "translated a"
    assert result[1] == "b" and result[2] == "c"  # fell back to originals


def test_translate_batch_truncates_on_long_response():
    texts = ["a", "b"]
    client = _FakeClient(["x", "y", "z"])  # model returned an extra item
    result = translate_batch(texts, source_language="French", client=client)
    assert result == ["x", "y"]


if __name__ == "__main__":
    test_functions = [v for k, v in list(globals().items()) if k.startswith("test_")]
    print(f"Running {len(test_functions)} tests...\n")
    failures = 0
    for test_fn in test_functions:
        try:
            test_fn()
            print(f"passed {test_fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAILED {test_fn.__name__}: {e}")
    print(f"\n{len(test_functions) - failures}/{len(test_functions)} tests passed.")
    if failures:
        sys.exit(1)
