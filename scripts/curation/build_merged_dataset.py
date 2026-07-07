"""
scripts/curation/build_merged_dataset.py

Combines every source's normalized_event file (data/normalized/
*_latest_normalized.json) into one curated dataset: entity names resolved
(entity_resolution.py) and cross-source conflict-event duplicates removed
(dedupe.py). Writes data/normalized/merged_dataset.json, which the dashboard
reads instead of recombining raw per-source files on every page load.

Run this after any ingestion script updates a *_latest_normalized.json file.

Usage:
    python scripts/curation/build_merged_dataset.py
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.curation.entity_resolution import resolve_batch
from scripts.curation.dedupe import dedupe_conflict_events

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "normalized"
OUTPUT_PATH = DATA_DIR / "merged_dataset.json"


def build() -> list[dict]:
    events = []
    for path in sorted(DATA_DIR.glob("*_latest_normalized.json")):
        with open(path, "r", encoding="utf-8") as f:
            events.extend(json.load(f))

    # merged_dataset.json is the PRESENTATION dataset -- it's what the
    # deployed app loads and what gets committed to git. Nothing downstream
    # reads raw_source_data from it (dashboard, knowledge base, reasoning
    # agent all ignore it), and it was the single biggest contributor to
    # this file approaching GitHub's 100MB hard limit (measured 2026-07-07).
    # The per-source *_latest_normalized.json files keep their raw payloads
    # where their normalizers retain them (ACLED, WorldBank, IMF) -- audit
    # trail preserved there, not here.
    for event in events:
        event["raw_source_data"] = None

    events = resolve_batch(events)
    events, removed = dedupe_conflict_events(events)

    print(f"Merged {len(events) + removed} source events -> {len(events)} after removing "
          f"{removed} likely cross-source duplicates.", file=sys.stderr)
    return events


def main():
    events = build()
    OUTPUT_PATH.write_text(json.dumps(events, indent=None), encoding="utf-8")
    print(f"Wrote {len(events)} events to {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
