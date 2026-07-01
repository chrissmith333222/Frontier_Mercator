"""
scripts/curation/dedupe.py

Cross-source deduplication for conflict-category events. ACLED and GDELT
can both report the same real-world event (e.g. a protest in Bamako on the
same day) -- without dedup, that event double-counts in every stat on the
Conflict & Security dashboard and the unified map.

Approach: bucket candidate duplicates by (country, event_date) -- comparing
every event to every other event is O(n^2) and doesn't scale past a few
thousand records (GDELT alone can be tens of thousands), but only events
sharing a country and exact date can plausibly be the same incident, which
shrinks each bucket to a handful of candidates. Within a bucket, flag pairs
whose narrative_summary text is similar enough (difflib ratio) as probable
duplicates and keep only the higher-reliability source's copy.

Source reliability order (highest kept first): ACLED > ReliefWeb > GDELT.
ACLED is manually curated by named sources with a fatality count; GDELT is
automated CAMEO coding from raw news mentions and is noisier -- when they
describe the same incident, ACLED's record is the better one to keep.
"""

from collections import defaultdict
from difflib import SequenceMatcher

SOURCE_PRIORITY = {"ACLED": 0, "ReliefWeb": 1, "GDELT": 2, "WorldBank": 3, "IMF": 3}

SIMILARITY_THRESHOLD = 0.6


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a or "", b or "").ratio()


def dedupe_conflict_events(events: list[dict]) -> tuple[list[dict], int]:
    """Returns (deduped_events, number_removed). Only events with
    event_category in the conflict set are compared against each other;
    economic/news events pass through untouched (a GDP reading and a news
    mention can't be "the same incident" as a conflict event anyway)."""
    from scripts.branding import CONFLICT_CATEGORIES

    conflict_events = [e for e in events if e.get("event_category") in CONFLICT_CATEGORIES]
    other_events = [e for e in events if e.get("event_category") not in CONFLICT_CATEGORIES]

    buckets = defaultdict(list)
    for event in conflict_events:
        key = (event.get("country"), event.get("event_date"))
        buckets[key].append(event)

    kept = []
    removed_count = 0

    for bucket in buckets.values():
        if len(bucket) == 1:
            kept.append(bucket[0])
            continue

        # Sort by source priority so the best copy of each duplicate group
        # survives; then greedily group remaining events by text similarity.
        bucket_sorted = sorted(bucket, key=lambda e: SOURCE_PRIORITY.get(e.get("source"), 9))
        used = [False] * len(bucket_sorted)

        for i, event in enumerate(bucket_sorted):
            if used[i]:
                continue
            kept.append(event)
            used[i] = True
            for j in range(i + 1, len(bucket_sorted)):
                if used[j]:
                    continue
                # Only ever collapse events from *different* sources. Two
                # events from the same source sharing a country/date are
                # virtually always distinct real incidents (a source doesn't
                # duplicate-report itself under two different IDs) -- and
                # GDELT's auto-generated "{actor1} <-> {actor2} (CAMEO n)"
                # summaries are formulaic enough that same-source text
                # similarity produces massive false positives (verified:
                # 650 distinct GDELT events for one country/day, all
                # superficially "similar" by this metric).
                if bucket_sorted[j].get("source") == event.get("source"):
                    continue
                if _similarity(event.get("narrative_summary", ""),
                                bucket_sorted[j].get("narrative_summary", "")) >= SIMILARITY_THRESHOLD:
                    used[j] = True
                    removed_count += 1

    return kept + other_events, removed_count
