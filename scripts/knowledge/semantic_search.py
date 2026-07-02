"""
scripts/knowledge/semantic_search.py

Query-time half of the vector index built by build_vector_index.py.
Embeds a natural-language query, ranks every event in the index by cosine
similarity, and returns the top-k full event records (joined back from
the SQLite knowledge base) -- the retrieval step behind open-ended,
cross-cutting questions that scripts/knowledge/queries.py's structured
filters can't answer (queries.py answers "tell me about country X";
this answers "where else does this pattern show up").

Usage (as a module):
    from scripts.knowledge.semantic_search import semantic_search
    results = semantic_search("Chinese port financing near active conflict zones")
"""

import sys
import os
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
from dotenv import load_dotenv

from scripts.knowledge.build_vector_index import EMBEDDINGS_PATH, EMBEDDING_MODEL
from scripts.knowledge.build_knowledge_base import DB_PATH

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _get_voyage_client():
    load_dotenv()
    api_key = os.environ.get("VOYAGE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "VOYAGE_API_KEY is not set. Add it to your .env file "
            "(see .env.example) -- never paste it into chat."
        )
    import voyageai
    return voyageai.Client(api_key=api_key)


def _load_index(embeddings_path: Path):
    if not embeddings_path.exists():
        raise RuntimeError(
            f"No vector index found at {embeddings_path} -- run "
            f"`python scripts/knowledge/build_vector_index.py` first."
        )
    data = np.load(embeddings_path, allow_pickle=True)
    return data["ids"], data["vectors"]


def _cosine_top_k(query_vector: np.ndarray, vectors: np.ndarray, k: int) -> np.ndarray:
    query_norm = query_vector / (np.linalg.norm(query_vector) + 1e-10)
    matrix_norms = np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-10
    normalized = vectors / matrix_norms
    scores = normalized @ query_norm
    top_k_idx = np.argpartition(-scores, min(k, len(scores) - 1))[:k]
    return top_k_idx[np.argsort(-scores[top_k_idx])], scores[top_k_idx[np.argsort(-scores[top_k_idx])]]


def semantic_search(
    query: str,
    k: int = 20,
    client=None,
    embeddings_path: Path = EMBEDDINGS_PATH,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """Embeds `query`, finds the k most similar events in the index, and
    returns full event dicts (joined from the SQLite knowledge base),
    each annotated with a `similarity_score`. `client` is injectable for
    tests (a fake with a matching `.embed(...)` surface)."""
    ids, vectors = _load_index(embeddings_path)
    if client is None:
        client = _get_voyage_client()

    query_result = client.embed([query], model=EMBEDDING_MODEL, input_type="query")
    query_vector = np.array(query_result.embeddings[0], dtype=np.float32)

    top_idx, scores = _cosine_top_k(query_vector, vectors, k)
    top_ids = [str(ids[i]) for i in top_idx]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" * len(top_ids))
        rows = {
            row["meridian_event_id"]: dict(row)
            for row in conn.execute(
                f"SELECT * FROM events WHERE meridian_event_id IN ({placeholders})", top_ids
            )
        }
    finally:
        conn.close()

    results = []
    for event_id, score in zip(top_ids, scores):
        if event_id in rows:
            event = rows[event_id]
            event["similarity_score"] = float(score)
            results.append(event)
    return results
