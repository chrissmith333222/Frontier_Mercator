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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MERGED_DATASET_PATH = REPO_ROOT / "data" / "normalized" / "merged_dataset.json"
EMBEDDINGS_PATH = REPO_ROOT / "data" / "knowledge" / "embeddings.npz"
EMBEDDING_MODEL = os.environ.get("VOYAGE_EMBEDDING_MODEL", "voyage-3.5")
BATCH_SIZE = 128
# Voyage free accounts without a payment method on file are capped at 3
# requests/minute (the free 200M-token allotment still applies either
# way -- adding a card only raises the rate limit, doesn't change cost).
# This spaces batches to stay under that cap by default; safe to lower
# via VOYAGE_MIN_SECONDS_BETWEEN_BATCHES once a payment method is added.
MIN_SECONDS_BETWEEN_BATCHES = float(os.environ.get("VOYAGE_MIN_SECONDS_BETWEEN_BATCHES", "21"))
CHECKPOINT_EVERY_N_BATCHES = 5


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


def _embed_with_retry(client, texts: list[str], max_attempts: int = 20):
    """Retries rate-limit errors with growing (capped) backoff -- Voyage's
    RateLimitError on unpaid accounts is expected/routine here, not
    exceptional, since we deliberately run under the free-tier cap. Voyage's
    own SDK already retries internally before raising, so by the time this
    sees the error the account is genuinely still throttled -- a high
    attempt count with a capped wait is what actually gets an unpaid
    account through the full dataset rather than dying partway."""
    for attempt in range(1, max_attempts + 1):
        try:
            return client.embed(texts, model=EMBEDDING_MODEL, input_type="document")
        except Exception as e:
            error_text = f"{type(e).__name__} {e}".lower().replace(" ", "")
            is_rate_limit = "ratelimit" in error_text
            if not is_rate_limit or attempt == max_attempts:
                raise
            wait_seconds = min(30 * attempt, 180)
            print(f"    rate limited, waiting {wait_seconds}s (attempt {attempt}/{max_attempts})...",
                  file=sys.stderr)
            time.sleep(wait_seconds)


def build_vector_index(
    merged_dataset_path: Path = MERGED_DATASET_PATH,
    output_path: Path = EMBEDDINGS_PATH,
    client=None,
    resume: bool = False,
) -> dict:
    """Embeds every event's text via Voyage and writes an (ids, vectors)
    archive. `client` is injectable for tests. With `resume=True`, skips
    events already present in an existing output_path archive and appends
    to it -- lets a run interrupted partway (or deliberately stopped and
    restarted, e.g. after adding a Voyage payment method to raise the
    rate limit) pick back up instead of re-embedding from scratch.
    Checkpoints progress to disk periodically for the same reason."""
    events = json.loads(merged_dataset_path.read_text(encoding="utf-8"))
    if client is None:
        client = _get_voyage_client()

    ids: list = []
    vectors: list = []
    if resume and output_path.exists():
        existing = np.load(output_path, allow_pickle=True)
        ids = list(existing["ids"])
        vectors = list(existing["vectors"])
        already_done = set(ids)
        events = [e for e in events if e["meridian_event_id"] not in already_done]
        print(f"  resuming: {len(already_done):,} events already embedded, "
              f"{len(events):,} remaining", file=sys.stderr)

    def _checkpoint():
        output_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            output_path,
            ids=np.array(ids, dtype=object),
            vectors=np.array(vectors, dtype=np.float32),
        )

    last_request_time = 0.0
    for batch_num, batch_start in enumerate(range(0, len(events), BATCH_SIZE), start=1):
        elapsed = time.monotonic() - last_request_time
        if elapsed < MIN_SECONDS_BETWEEN_BATCHES:
            time.sleep(MIN_SECONDS_BETWEEN_BATCHES - elapsed)

        batch = events[batch_start:batch_start + BATCH_SIZE]
        texts = [_embedding_text(e) for e in batch]
        result = _embed_with_retry(client, texts)
        last_request_time = time.monotonic()

        ids.extend(e["meridian_event_id"] for e in batch)
        vectors.extend(result.embeddings)
        print(f"  embedded {batch_start + len(batch)}/{len(events)} "
              f"(this run; {len(ids)} total in index)", file=sys.stderr)

        if batch_num % CHECKPOINT_EVERY_N_BATCHES == 0:
            _checkpoint()

    _checkpoint()
    dims = len(vectors[0]) if vectors else 0
    return {"events": len(ids), "dimensions": dims}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build the Voyage embedding index over all events")
    parser.add_argument("--resume", action="store_true",
                         help="Resume an interrupted run instead of starting over -- skips events "
                              "already in the existing embeddings.npz.")
    args = parser.parse_args()

    summary = build_vector_index(resume=args.resume)
    print(f"Built vector index at {EMBEDDINGS_PATH}: "
          f"{summary['events']:,} events, {summary['dimensions']} dimensions", file=sys.stderr)


if __name__ == "__main__":
    main()
