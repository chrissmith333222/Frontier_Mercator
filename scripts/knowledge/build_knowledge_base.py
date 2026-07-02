"""
scripts/knowledge/build_knowledge_base.py

Loads data/normalized/merged_dataset.json into a queryable SQLite database
(data/knowledge/meridian.db) -- the structured relationship layer behind
the Phase 5 reasoning agent. Chose SQLite over a full graph database
(Neo4j etc.) per the original architecture decision: relationship
modeling here (financiers, actors, countries, events) doesn't need real
Cypher-style graph traversal yet, a normalized relational schema covers
"who's active where, doing what, over what time period" cleanly and is
free/file-based/zero-ops.

Two tables:
  - events: one row per normalized event, indexed for the query patterns
    the reasoning agent actually needs (by country, category, date range,
    severity).
  - actor_relationships: one row per (actor, country, event) triple,
    derived from each event's `actors` field -- this is what lets the
    agent answer "which financiers/actors are active in country X" and
    "does this actor appear across multiple event categories" without
    re-parsing JSON actor lists at query time.

Usage:
    python scripts/knowledge/build_knowledge_base.py
"""

import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MERGED_DATASET_PATH = REPO_ROOT / "data" / "normalized" / "merged_dataset.json"
DB_PATH = REPO_ROOT / "data" / "knowledge" / "meridian.db"

SCHEMA = """
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS actor_relationships;

CREATE TABLE events (
    meridian_event_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    event_date TEXT NOT NULL,
    country TEXT NOT NULL,
    iso3 TEXT,
    region TEXT NOT NULL,
    in_core_mandate INTEGER NOT NULL,
    event_category TEXT NOT NULL,
    event_subtype TEXT,
    fatalities INTEGER,
    severity_score REAL,
    narrative_summary TEXT,
    source_url TEXT
);

CREATE INDEX idx_events_country ON events (iso3, event_date);
CREATE INDEX idx_events_category ON events (event_category, event_date);
CREATE INDEX idx_events_country_category ON events (iso3, event_category);

CREATE TABLE actor_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_name TEXT NOT NULL,
    actor_type TEXT,
    country TEXT NOT NULL,
    iso3 TEXT,
    event_category TEXT NOT NULL,
    event_date TEXT NOT NULL,
    meridian_event_id TEXT NOT NULL REFERENCES events(meridian_event_id)
);

CREATE INDEX idx_actor_name ON actor_relationships (actor_name);
CREATE INDEX idx_actor_country ON actor_relationships (iso3, actor_name);
"""


def build_knowledge_base(merged_dataset_path: Path = MERGED_DATASET_PATH, db_path: Path = DB_PATH) -> dict:
    """Rebuilds the SQLite knowledge base from scratch (drop + recreate)
    every run, matching the rest of the pipeline's re-run-from-source
    pattern rather than incremental upserts. Returns a small summary dict
    for logging."""
    events = json.loads(merged_dataset_path.read_text(encoding="utf-8"))

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)

        event_rows = []
        actor_rows = []
        for event in events:
            event_rows.append((
                event["meridian_event_id"], event["source"], event["event_date"],
                event["country"], event.get("iso3"), event["region"],
                1 if event["in_core_mandate"] else 0, event["event_category"],
                event.get("event_subtype"), event.get("fatalities"),
                event.get("severity_score"), event.get("narrative_summary"),
                event.get("source_url"),
            ))
            for actor in event.get("actors") or []:
                if not actor.get("name"):
                    continue
                actor_rows.append((
                    actor["name"], actor.get("type"), event["country"], event.get("iso3"),
                    event["event_category"], event["event_date"], event["meridian_event_id"],
                ))

        conn.executemany(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", event_rows
        )
        conn.executemany(
            "INSERT INTO actor_relationships "
            "(actor_name, actor_type, country, iso3, event_category, event_date, meridian_event_id) "
            "VALUES (?,?,?,?,?,?,?)", actor_rows
        )
        conn.commit()
    finally:
        conn.close()

    return {"events": len(event_rows), "actor_relationships": len(actor_rows)}


def main():
    summary = build_knowledge_base()
    print(f"Built knowledge base at {DB_PATH}: "
          f"{summary['events']:,} events, {summary['actor_relationships']:,} actor relationships",
          file=sys.stderr)


if __name__ == "__main__":
    main()
