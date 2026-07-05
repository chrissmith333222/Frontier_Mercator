"""
scripts/ingestion/_gdelt_backfill_enrich.py

One-off backfill script: enriches every existing GDELT event's
narrative_summary with a real article headline (see enrich_headlines()
in gdelt_normalize.py), checkpointing progress to disk every CHUNK_SIZE
events so a session interruption loses at most one chunk of work instead
of the whole run. Not part of the normal ingestion pipeline -- run once
to backfill the historical backlog, then future incremental GDELT
fetches use --enrich-headlines directly.

Usage:
    python scripts/ingestion/_gdelt_backfill_enrich.py
"""

import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.ingestion.gdelt_normalize import enrich_headlines

DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "normalized" / "gdelt_latest_normalized.json"
CHUNK_SIZE = 1500


def _is_unenriched(event: dict) -> bool:
    """enrich_headlines() rewrites a successfully-enriched summary to
    "<real headline> (ACTOR1 <-> ACTOR2)" -- every un-enriched fallback
    format ("ACTOR1 <-> ACTOR2: <CAMEO label>", or the unknown-root-code
    fallback) does not end in a closing paren, so that's a reliable,
    cheap way to find what's still pending without tracking a separate
    "enriched" flag on every event."""
    return not event.get("narrative_summary", "").endswith(")")


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    pending = [e for e in data if _is_unenriched(e)]
    print(f"{len(data)} total events, {len(pending)} still un-enriched", file=sys.stderr, flush=True)

    total_enriched = 0
    for start in range(0, len(pending), CHUNK_SIZE):
        chunk = pending[start:start + CHUNK_SIZE]
        chunk_start_time = time.time()
        count = enrich_headlines(chunk, max_workers=40)
        total_enriched += count
        DATA_PATH.write_text(json.dumps(data), encoding="utf-8")
        print(
            f"  chunk {start // CHUNK_SIZE + 1}: enriched {count}/{len(chunk)} "
            f"in {time.time() - chunk_start_time:.1f}s (checkpoint saved, "
            f"{total_enriched} total so far)",
            file=sys.stderr, flush=True,
        )

    print(f"Done: {total_enriched}/{len(pending)} events enriched.", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
