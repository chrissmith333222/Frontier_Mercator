"""
scripts/knowledge/queries.py

Read-only query helpers over the SQLite knowledge base
(data/knowledge/meridian.db) -- the retrieval layer the reasoning agent
uses to pull structured, grounded context for a given country/region
before calling Claude. Every function here returns plain dicts/lists
(JSON-serializable), never raw DB cursors, so callers can drop the result
straight into an LLM prompt or a cache file.
"""

import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = REPO_ROOT / "data" / "knowledge" / "meridian.db"


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def country_snapshot(iso3: str, db_path: Path = DB_PATH) -> dict:
    """One-stop structured pull for a country: recent high-severity
    conflict events, latest economic indicators, top investment projects
    by source, top active actors, and category counts over the full
    dataset window. This is the primary context bundle fed to the
    reasoning agent -- deliberately structured (not a text blob) so the
    agent can cite specific events."""
    conn = _connect(db_path)
    try:
        category_counts = {
            row["event_category"]: row["n"]
            for row in conn.execute(
                "SELECT event_category, COUNT(*) as n FROM events WHERE iso3 = ? GROUP BY event_category",
                (iso3,),
            )
        }

        top_conflict = [
            dict(row) for row in conn.execute(
                "SELECT event_date, event_category, event_subtype, severity_score, "
                "fatalities, narrative_summary, source, source_url FROM events "
                "WHERE iso3 = ? AND event_category IN "
                "('conflict','protest_civil_unrest','political_violence_targeting_civilians','explosion_remote_violence') "
                "ORDER BY event_date DESC, severity_score DESC LIMIT 15",
                (iso3,),
            )
        ]

        latest_indicators = [
            dict(row) for row in conn.execute(
                "SELECT event_date, event_subtype, narrative_summary, source FROM events "
                "WHERE iso3 = ? AND event_category = 'economic_indicator' "
                "ORDER BY event_date DESC LIMIT 15",
                (iso3,),
            )
        ]

        top_investment = [
            dict(row) for row in conn.execute(
                "SELECT event_date, source, event_subtype, narrative_summary, source_url FROM events "
                "WHERE iso3 = ? AND event_category = 'investment' "
                "ORDER BY event_date DESC LIMIT 20",
                (iso3,),
            )
        ]

        humanitarian_osint = [
            dict(row) for row in conn.execute(
                "SELECT event_date, source, narrative_summary, source_url FROM events "
                "WHERE iso3 = ? AND event_category IN ('humanitarian','other','strategic_development') "
                "ORDER BY event_date DESC LIMIT 10",
                (iso3,),
            )
        ]

        top_actors = [
            dict(row) for row in conn.execute(
                "SELECT actor_name, actor_type, COUNT(*) as n, "
                "GROUP_CONCAT(DISTINCT event_category) as categories "
                "FROM actor_relationships WHERE iso3 = ? "
                "GROUP BY actor_name, actor_type ORDER BY n DESC LIMIT 15",
                (iso3,),
            )
        ]

        return {
            "iso3": iso3,
            "category_counts": category_counts,
            "top_conflict_events": top_conflict,
            "latest_economic_indicators": latest_indicators,
            "top_investment_projects": top_investment,
            "humanitarian_and_osint_signals": humanitarian_osint,
            "top_active_actors": top_actors,
        }
    finally:
        conn.close()


def actor_cross_country_footprint(actor_name: str, db_path: Path = DB_PATH) -> list[dict]:
    """Every country an actor appears active in, with event counts and
    category mix -- the base query behind "where else is this financier/
    actor active" relationship questions."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT country, iso3, COUNT(*) as n, "
            "GROUP_CONCAT(DISTINCT event_category) as categories "
            "FROM actor_relationships WHERE actor_name = ? "
            "GROUP BY country, iso3 ORDER BY n DESC",
            (actor_name,),
        )
        return [dict(row) for row in rows]
    finally:
        conn.close()


def countries_with_data(db_path: Path = DB_PATH) -> list[dict]:
    """All countries present in the knowledge base with an event count --
    used to drive the "which countries have enough data for an
    assessment" check before calling the reasoning agent."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT iso3, country, in_core_mandate, COUNT(*) as n FROM events "
            "WHERE iso3 IS NOT NULL GROUP BY iso3, country, in_core_mandate ORDER BY n DESC"
        )
        return [dict(row) for row in rows]
    finally:
        conn.close()
