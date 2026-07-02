"""
tests/test_build_vector_index.py

Tests build_vector_index's batching, resume, and retry-on-rate-limit
logic with a fake Voyage client -- no real API key or network call
needed, and no real 21-second inter-batch waits (patches the module-level
delay constant down to 0 for the test run).

Usage:
    python -m pytest tests/test_build_vector_index.py -v
"""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import scripts.knowledge.build_vector_index as bvi_module
from scripts.knowledge.build_vector_index import build_vector_index, _embed_with_retry

FIXTURE_EVENTS = [
    {"meridian_event_id": f"e{i}", "country": "Kenya", "event_category": "investment",
     "narrative_summary": f"Event number {i}."}
    for i in range(5)
]


class _FakeEmbeddingResult:
    def __init__(self, embeddings):
        self.embeddings = embeddings


class _FakeVoyageClient:
    def __init__(self):
        self.call_count = 0

    def embed(self, texts, model=None, input_type=None):
        self.call_count += 1
        return _FakeEmbeddingResult([[1.0, 0.0] for _ in texts])


class _RateLimitedThenOkClient:
    """Fails with a rate-limit-shaped error on the first call, succeeds after."""
    def __init__(self):
        self.call_count = 0

    def embed(self, texts, model=None, input_type=None):
        self.call_count += 1
        if self.call_count == 1:
            raise RuntimeError("RateLimitError: too many requests")
        return _FakeEmbeddingResult([[1.0, 0.0] for _ in texts])


def _patch_delay(monkeypatch_value=0.0):
    original = bvi_module.MIN_SECONDS_BETWEEN_BATCHES
    bvi_module.MIN_SECONDS_BETWEEN_BATCHES = monkeypatch_value
    return original


def test_build_vector_index_embeds_all_events():
    original_delay = _patch_delay(0.0)
    original_batch_size = bvi_module.BATCH_SIZE
    bvi_module.BATCH_SIZE = 2
    try:
        tmp_dir = Path(tempfile.mkdtemp())
        dataset_path = tmp_dir / "merged_dataset.json"
        dataset_path.write_text(json.dumps(FIXTURE_EVENTS), encoding="utf-8")
        output_path = tmp_dir / "embeddings.npz"

        fake_client = _FakeVoyageClient()
        summary = build_vector_index(merged_dataset_path=dataset_path, output_path=output_path, client=fake_client)

        assert summary["events"] == 5
        data = np.load(output_path, allow_pickle=True)
        assert len(data["ids"]) == 5
        assert set(data["ids"]) == {f"e{i}" for i in range(5)}
        print("✓ test_build_vector_index_embeds_all_events passed")
    finally:
        bvi_module.MIN_SECONDS_BETWEEN_BATCHES = original_delay
        bvi_module.BATCH_SIZE = original_batch_size


def test_build_vector_index_resume_skips_already_embedded():
    original_delay = _patch_delay(0.0)
    original_batch_size = bvi_module.BATCH_SIZE
    bvi_module.BATCH_SIZE = 10
    try:
        tmp_dir = Path(tempfile.mkdtemp())
        dataset_path = tmp_dir / "merged_dataset.json"
        dataset_path.write_text(json.dumps(FIXTURE_EVENTS), encoding="utf-8")
        output_path = tmp_dir / "embeddings.npz"

        # Pre-seed the archive as if e0, e1, e2 were already embedded in a prior run.
        np.savez_compressed(
            output_path,
            ids=np.array(["e0", "e1", "e2"], dtype=object),
            vectors=np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]], dtype=np.float32),
        )

        fake_client = _FakeVoyageClient()
        summary = build_vector_index(
            merged_dataset_path=dataset_path, output_path=output_path, client=fake_client, resume=True
        )

        assert summary["events"] == 5  # 3 pre-seeded + 2 newly embedded
        assert fake_client.call_count == 1  # only e3, e4 needed embedding, fits in one batch
        print("✓ test_build_vector_index_resume_skips_already_embedded passed")
    finally:
        bvi_module.MIN_SECONDS_BETWEEN_BATCHES = original_delay
        bvi_module.BATCH_SIZE = original_batch_size


def test_embed_with_retry_recovers_from_rate_limit():
    original_sleep = bvi_module.time.sleep
    bvi_module.time.sleep = lambda seconds: None  # skip the real 30s backoff in this test
    try:
        client = _RateLimitedThenOkClient()
        result = _embed_with_retry(client, ["some text"], max_attempts=3)
        assert client.call_count == 2  # failed once, succeeded on retry
        assert result.embeddings == [[1.0, 0.0]]
    finally:
        bvi_module.time.sleep = original_sleep
    print("✓ test_embed_with_retry_recovers_from_rate_limit passed")


def test_embed_with_retry_reraises_non_rate_limit_errors():
    class _AlwaysBrokenClient:
        def embed(self, texts, model=None, input_type=None):
            raise ValueError("some unrelated bug")

    raised = False
    try:
        _embed_with_retry(_AlwaysBrokenClient(), ["text"], max_attempts=3)
    except ValueError:
        raised = True
    assert raised
    print("✓ test_embed_with_retry_reraises_non_rate_limit_errors passed")


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
