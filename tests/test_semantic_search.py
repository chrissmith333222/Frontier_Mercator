"""
tests/test_semantic_search.py

Tests semantic_search's cosine-similarity ranking and index-joining logic
with a fake Voyage client and a small temporary knowledge base + vector
index -- no real API key or network call needed.

Usage:
    python -m pytest tests/test_semantic_search.py -v
"""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from scripts.knowledge.build_knowledge_base import build_knowledge_base
from scripts.knowledge.semantic_search import semantic_search, _cosine_top_k

FIXTURE_EVENTS = [
    {
        "meridian_event_id": "e1", "source": "AidData", "source_event_id": "s1",
        "event_date": "2026-01-10", "country": "Kenya", "iso3": "KEN", "admin1": None,
        "region": "East Africa / Horn", "in_core_mandate": True,
        "event_category": "investment", "event_subtype": "Transport", "actors": [],
        "fatalities": None, "severity_score": None,
        "narrative_summary": "China Eximbank financed a port expansion project.",
        "source_url": "https://aiddata.org", "ingested_at": "2026-01-11T00:00:00Z",
    },
    {
        "meridian_event_id": "e2", "source": "ACLED", "source_event_id": "s2",
        "event_date": "2026-02-01", "country": "Mozambique", "iso3": "MOZ", "admin1": None,
        "region": "Southern Africa", "in_core_mandate": True,
        "event_category": "conflict", "event_subtype": "Battles", "actors": [],
        "fatalities": 3, "severity_score": 6.0,
        "narrative_summary": "Clashes near the port area.",
        "source_url": "https://acleddata.com", "ingested_at": "2026-02-02T00:00:00Z",
    },
    {
        "meridian_event_id": "e3", "source": "WorldBank", "source_event_id": "s3",
        "event_date": "2025-12-31", "country": "Kenya", "iso3": "KEN", "admin1": None,
        "region": "East Africa / Horn", "in_core_mandate": True,
        "event_category": "economic_indicator", "event_subtype": "NY.GDP.MKTP.KD.ZG", "actors": [],
        "fatalities": None, "severity_score": None,
        "narrative_summary": "GDP growth: 5.2% (2025)",
        "source_url": "https://data.worldbank.org", "ingested_at": "2026-01-01T00:00:00Z",
    },
]


class _FakeEmbeddingResult:
    def __init__(self, embeddings):
        self.embeddings = embeddings


class _FakeVoyageClient:
    """Returns a fixed, hand-picked vector per call so ranking is
    deterministic and inspectable, rather than simulating real semantics."""
    def __init__(self, query_vector):
        self.query_vector = query_vector

    def embed(self, texts, model=None, input_type=None):
        return _FakeEmbeddingResult([self.query_vector for _ in texts])


def _make_temp_kb_and_index():
    tmp_dir = Path(tempfile.mkdtemp())
    dataset_path = tmp_dir / "merged_dataset.json"
    dataset_path.write_text(json.dumps(FIXTURE_EVENTS), encoding="utf-8")
    db_path = tmp_dir / "meridian.db"
    build_knowledge_base(merged_dataset_path=dataset_path, db_path=db_path)

    # Hand-crafted vectors: e1 and e2 both "close" to the query direction,
    # e3 orthogonal/far -- lets the test assert ranking without needing
    # real embeddings.
    ids = np.array(["e1", "e2", "e3"], dtype=object)
    vectors = np.array([
        [1.0, 0.0, 0.0],   # e1: identical to query
        [0.9, 0.1, 0.0],   # e2: close to query
        [0.0, 1.0, 0.0],   # e3: orthogonal to query
    ], dtype=np.float32)
    embeddings_path = tmp_dir / "embeddings.npz"
    np.savez_compressed(embeddings_path, ids=ids, vectors=vectors)

    return db_path, embeddings_path


def test_cosine_top_k_ranks_closest_vectors_first():
    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vectors = np.array([
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.9, 0.1, 0.0],
    ], dtype=np.float32)
    top_idx, scores = _cosine_top_k(query, vectors, k=2)
    assert list(top_idx) == [0, 2]  # exact match first, then the close one
    assert scores[0] > scores[1]
    print("✓ test_cosine_top_k_ranks_closest_vectors_first passed")


def test_semantic_search_returns_ranked_events_with_metadata():
    db_path, embeddings_path = _make_temp_kb_and_index()
    fake_voyage = _FakeVoyageClient(query_vector=[1.0, 0.0, 0.0])

    results = semantic_search(
        "port financing", k=2, client=fake_voyage,
        embeddings_path=embeddings_path, db_path=db_path,
    )

    assert len(results) == 2
    assert results[0]["meridian_event_id"] == "e1"
    assert results[0]["country"] == "Kenya"
    assert "similarity_score" in results[0]
    assert results[0]["similarity_score"] > results[1]["similarity_score"]
    print("✓ test_semantic_search_returns_ranked_events_with_metadata passed")


def test_semantic_search_raises_without_index():
    from scripts.knowledge.semantic_search import _load_index
    missing_path = Path(tempfile.mkdtemp()) / "does_not_exist.npz"
    raised = False
    try:
        _load_index(missing_path)
    except RuntimeError as e:
        raised = "build_vector_index" in str(e)
    assert raised
    print("✓ test_semantic_search_raises_without_index passed")


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
