"""
scripts/curation/entity_resolution.py

Canonicalizes actor names across sources. GDELT gives actors in raw CAMEO
ALL-CAPS form ("UNITED STATES", "CHINA"); ACLED gives more natural names
("Military Forces of Mali"). Neither is wrong, but mixing them in one
dataset makes filtering/search inconsistent (e.g. searching "China" misses
"CHINA"). This normalizes casing and maps known aliases for major state/
institutional actors to one canonical form, applied to the `actors` field
of normalized events from any source.

This is a starter alias map, not a full entity-resolution system (that's
still Phase 4 -- a real knowledge graph with fuzzy matching across arbitrary
entities). It covers the state actors and institutions relevant to
MERIDIAN's mandate (Great Power Competition dashboard, mandate countries).
"""

import re

# Raw form (as seen in GDELT/ACLED, case-insensitive) -> canonical name.
# Keys are matched after uppercasing, so list them in any case.
ALIAS_MAP = {
    "UNITED STATES": "United States", "USA": "United States", "US": "United States",
    "UNITED STATES OF AMERICA": "United States",
    "CHINA": "China", "PRC": "China", "PEOPLES REPUBLIC OF CHINA": "China",
    "RUSSIA": "Russia", "RUSSIAN FEDERATION": "Russia",
    "IRAN": "Iran", "ISLAMIC REPUBLIC OF IRAN": "Iran",
    "UNITED KINGDOM": "United Kingdom", "UK": "United Kingdom", "BRITAIN": "United Kingdom",
    "EUROPEAN UNION": "European Union", "EU": "European Union",
    "UNITED NATIONS": "United Nations", "UN": "United Nations",
    "NORTH ATLANTIC TREATY ORGANIZATION": "NATO", "NATO": "NATO",
    "SAUDI ARABIA": "Saudi Arabia",
    "GOVERNMENT": "Government", "MILITARY": "Military", "POLICE": "Police",
    "REBEL GROUP": "Rebel Group", "PROTESTERS": "Protesters", "CIVILIANS": "Civilians",
    # DFC's legacy originating-agency provenance tags -- these are real
    # historical acronyms (the naive title-casing fallback below would
    # otherwise turn "OPIC" into the unreadable "Opic"), not aliases to be
    # collapsed into DFC itself: they intentionally stay distinct from
    # "U.S. International Development Finance Corporation" because they
    # record which legacy program originated a given deal pre-2019 merger.
    "OPIC": "OPIC (Overseas Private Investment Corporation, DFC predecessor)",
    "DCA": "DCA (Development Credit Authority, DFC predecessor)",
}


def canonicalize_actor_name(raw_name: str) -> str:
    """Maps a raw actor name to its canonical form if known; otherwise
    applies a light title-case normalization so ALL-CAPS GDELT names don't
    visually clash with ACLED's naturally-cased names."""
    if not raw_name:
        return raw_name
    key = raw_name.strip().upper()
    if key in ALIAS_MAP:
        return ALIAS_MAP[key]
    # Leave mixed-case names (already natural, e.g. ACLED) untouched; only
    # re-case names that are entirely uppercase (GDELT's raw CAMEO form).
    if raw_name.isupper():
        return re.sub(r"\b\w", lambda m: m.group().upper(), raw_name.lower())
    return raw_name


def resolve_event_actors(event: dict) -> dict:
    """Returns a copy of `event` with its actors field canonicalized."""
    actors = event.get("actors") or []
    resolved = [
        {**actor, "name": canonicalize_actor_name(actor.get("name", ""))}
        for actor in actors
    ]
    return {**event, "actors": resolved}


def resolve_batch(events: list[dict]) -> list[dict]:
    return [resolve_event_actors(e) for e in events]
