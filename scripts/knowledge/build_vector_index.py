"""
scripts/knowledge/build_vector_index.py

Builds a semantic search index over every event in merged_dataset.json,
using Voyage AI embeddings (Anthropic's recommended embedding partner for
RAG with Claude). This is what upgrades the reasoning agent from "answer
questions about one country" (structured SQL retrieval only, see
scripts/knowledge/queries.py) to "answer open-ended cross-cutting
questions" (e.g. "where is China investing near active conflict zones
region-wide") -- structured filters alone can't do that kind of
similarity-based retrieval.

Backend/batch script, same pattern as build_knowledge_base.py and
reasoning_agent.py: never called from the deployed Streamlit app, keeps
the `voyageai` SDK and API key off Streamlit Cloud. Output is a local
numpy archive (data/knowledge/embeddings.npz -- gitignored/regenerable,
same as meridian.db), not a full vector-database server (Chroma etc.) --
64k events at ~1024 dimensions is a ~260MB matrix, well within what numpy
cosine-similarity search handles in well under a second, so a dedicated
vector DB isn't earning its complexity yet at this scale.

Requires VOYAGE_API_KEY in .env (not committed -- see .env.example).

Usage (CLI):
    python scripts/knowledge/build_vector_index.py

Usage (as a module):
    from scripts.knowledge.build_vector_index import build_vector_index
    build_vector_index()
"""

import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MERGED_DATASET_PATH = REPO_ROOT / "data" / "normalized" / "merged_dataset.json"
EMBEDDINGS_PATH = REPO_ROOT / "data" / "knowledge" / "embeddings.npz"
EMBEDDING_MODEL = os.environ.get("VOYAGE_EMBEDDING_MODEL", "voyage-3.5")
BATCH_SIZE = 128


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


def _embedding_text(event: dict) -> str:
    """Embeds a lightly-enriched version of the event, not just the bare
    narrative -- putting country/category in the embedded text (not just
    as separate filterable metadata) improves retrieval for queries that
    imply a category or region without naming it explicitly."""
    return f"{event['country']} | {event['event_category']}: {event.get('narrative_summary') or ''}"


def build_vector_index(
    merged_dataset_path: Path = MERGED_DATASET_PATH,
    output_path: Path = EMBEDDINGS_PATH,
    client=None,
) -> dict:
    """Embeds every event's text via Voyage and writes an (ids, vectors)
    archive. `client` is injectable for tests. Returns a summary dict."""
    events = json.loads(merged_dataset_path.read_text(encoding="utf-8"))
    if client is None:
        client = _get_voyage_client()

    ids = []
    vectors = []
    for batch_start in range(0, len(events), BATCH_SIZE):
        batch = events[batch_start:batch_start + BATCH_SIZE]
        texts = [_embedding_text(e) for e in batch]
        result = client.embed(texts, model=EMBEDDING_MODEL, input_type="document")
        ids.extend(e["meridian_event_id"] for e in batch)
        vectors.extend(result.embeddings)
        print(f"  embedded {min(batch_start + BATCH_SIZE, len(events))}/{len(events)}", file=sys.stderr)

    ids_array = np.array(ids, dtype=object)
    vectors_array = np.array(vectors, dtype=np.float32)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output_path, ids=ids_array, vectors=vectors_array)

    return {"events": len(ids), "dimensions": vectors_array.shape[1] if len(vectors) else 0}


def main():
    summary = build_vector_index()
    print(f"Built vector index at {EMBEDDINGS_PATH}: "
          f"{summary['events']:,} events, {summary['dimensions']} dimensions", file=sys.stderr)


if __name__ == "__main__":
    main()
