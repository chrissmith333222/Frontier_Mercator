"""
scripts/analytics/significance.py

Computes a 0-10 "significance" (aka "hotness") score for every event in
the merged dataset -- the thing Chris asked for explicitly: "prioritizing
which posts/news stories/flashes/or current events are the most
important" and "if something is 'hot' or 'breaking' or 'urgent' we
should have a way to make that data point stand out from the rest of
the white noise."

This runs LIVE in the dashboard over the already-loaded DataFrame (like
relationship_graph.py), not as a precomputed batch artifact -- it needs
to react to whatever filters/date-range the user currently has applied,
and it's cheap (no API calls, just vectorized pandas math).

The score blends four independent signals, each individually weak but
useful together:
  1. severity_score, where the source already provides one (ACLED/GDELT
     conflict events) -- the strongest available signal, weighted heaviest.
  2. Recency -- newer events matter more for a "what's happening now"
     view; decays over the trailing window rather than a hard cutoff.
  3. Fatalities -- a log-scaled boost, since 1 vs 50 fatalities matters
     a lot more than 50 vs 51.
  4. Breaking/urgent keyword match in the narrative text -- a cheap proxy
     for editorial urgency (coups, attacks, sanctions, market crashes,
     resignations, etc.) that catches high-importance events lacking a
     severity_score at all (most news/social and investment events).

This is explicitly a heuristic significance proxy, not a validated
newsworthiness model -- flagged as "preliminary" in the UI same as every
other derived-signal feature on this dashboard.

Usage (as a module):
    from scripts.analytics.significance import compute_significance_score, diversify_top_n
    df["significance_score"] = compute_significance_score(df)
    top = diversify_top_n(df, "significance_score", n=30, max_per_source=8)
"""

import re

import numpy as np
import pandas as pd

# Case-insensitive terms that, when present in a narrative summary, signal
# elevated urgency/newsworthiness even for events with no native severity
# score (most news/social/investment events don't have one at all).
BREAKING_KEYWORDS = [
    "breaking", "urgent", "emergency", "coup", "assassinat", "explosion",
    "attack", "airstrike", "air strike", "massacre", "killed", "dead", "deaths",
    "collapse", "crash", "resign", "sanction", "seized", "seizure", "arrested",
    "arrest warrant", "state of emergency", "martial law", "invasion", "invaded",
    "default", "bailout", "coup d'etat", "coup d'état", "overthrow", "uprising",
    "insurrection", "detained", "kidnap", "hostage", "blast", "bombing",
]
_BREAKING_PATTERN = re.compile("|".join(re.escape(term) for term in BREAKING_KEYWORDS), re.IGNORECASE)

# Deprecated fixed threshold, kept only for reference -- replaced by
# compute_tier_thresholds()/significance_tier() below. A fixed absolute
# cutoff badges almost everything or almost nothing depending on how the
# score distribution happens to sit that day, and a ranked top-N list is,
# by construction, mostly high scorers -- Chris: "every single event on
# our news and social signal tab is a 'top signal'... you need to be
# judicious." Percentile-relative tiers fix that.
SIGNIFICANCE_HOT_THRESHOLD = 7.0

# Absolute floors alongside the percentile cutoffs below -- on a
# genuinely quiet day where every score is low, nothing should get
# badged "urgent" purely for being the *relatively* highest of a
# uniformly unremarkable batch.
_ABSOLUTE_FLOORS = {"urgent": 6.5, "top": 4.5, "medium": 3.0}


def compute_tier_thresholds(scores: pd.Series) -> dict:
    """Derives Urgent/Top/Medium cutoffs from the distribution of scores
    currently in view, rather than one fixed number for all contexts --
    keeps the tiers meaningfully selective regardless of what's currently
    filtered/displayed (a small, recent-heavy scope has a different score
    spread than the full multi-year dataset)."""
    if len(scores) == 0:
        return {"urgent": 10.1, "top": 10.1, "medium": 10.1}
    return {
        "urgent": scores.quantile(0.95),
        "top": scores.quantile(0.80),
        "medium": scores.quantile(0.55),
    }


def significance_tier(score: float, thresholds: dict) -> str | None:
    """Returns 'urgent', 'top', 'medium', or None (routine -- no badge).
    Requires both the percentile cutoff AND the absolute floor, so a tier
    reflects genuine significance, not just relative rank within whatever
    happens to be on screen."""
    if score >= thresholds["urgent"] and score >= _ABSOLUTE_FLOORS["urgent"]:
        return "urgent"
    if score >= thresholds["top"] and score >= _ABSOLUTE_FLOORS["top"]:
        return "top"
    if score >= thresholds["medium"] and score >= _ABSOLUTE_FLOORS["medium"]:
        return "medium"
    return None


def _recency_component(event_date: pd.Series) -> pd.Series:
    """0-10 scale, linearly decaying from the most recent date in the
    (already-filtered) scope down to 0 at the oldest -- same idea as the
    unified map's existing recency_score, just factored out so News &
    Social Signal and the map can share one definition instead of drifting."""
    dates = pd.to_datetime(event_date, errors="coerce")
    if dates.isna().all():
        return pd.Series(0.0, index=event_date.index)
    min_date, max_date = dates.min(), dates.max()
    span_days = (max_date - min_date).days
    if span_days <= 0:
        return pd.Series(10.0, index=event_date.index)
    days_from_oldest = (dates - min_date).dt.days
    return (days_from_oldest / span_days * 10).fillna(0.0)


def _fatalities_component(fatalities: pd.Series) -> pd.Series:
    """Log-scaled 0-10ish boost -- log1p(50) ~ 3.9, so this alone won't
    dominate the score, it nudges high-casualty events upward."""
    numeric = pd.to_numeric(fatalities, errors="coerce").fillna(0).clip(lower=0)
    return np.log1p(numeric)


def _keyword_component(narrative: pd.Series) -> pd.Series:
    text = narrative.fillna("").astype(str)
    return text.str.contains(_BREAKING_PATTERN).astype(float) * 10


def compute_significance_score(df: pd.DataFrame) -> pd.Series:
    """Returns a 0-10 significance score per row of `df`, blending native
    severity (where present), recency within the current scope, a
    fatalities boost, and a breaking-keyword match. Weights are tuned so
    a severity_score=10 conflict event and a keyword-flagged breaking
    story with no severity score can both land in "hot" territory --
    neither signal alone should be a hard requirement, since most
    news/social/investment events simply don't have a severity_score."""
    severity = pd.to_numeric(df.get("severity_score"), errors="coerce")
    has_severity = severity.notna()

    recency = _recency_component(df["event_date"])
    fatalities_boost = _fatalities_component(df.get("fatalities", pd.Series(0, index=df.index)))
    keyword_boost = _keyword_component(df.get("narrative_summary", pd.Series("", index=df.index)))

    base = severity.fillna(4.0)  # events with no severity score get a neutral baseline
    # Events without a severity_score (most news/social/investment events)
    # lean heavily on the breaking-keyword signal, since that's often the
    # only available urgency signal at all for that category of event.
    score = (
        base * 0.3
        + recency * 0.15
        + fatalities_boost.clip(upper=4) * 0.15
        + keyword_boost * 0.5
    )
    # Events that already carry a real severity_score shouldn't be diluted
    # as much by the keyword/fatalities heuristics designed to compensate
    # for *not* having one.
    score = np.where(has_severity, severity * 0.75 + recency * 0.15 + keyword_boost * 0.10, score)
    return pd.Series(np.clip(score, 0, 10), index=df.index)


def diversify_top_n(df: pd.DataFrame, score_col: str, n: int, source_col: str = "source",
                     max_per_source: int | None = None) -> pd.DataFrame:
    """Returns the top `n` rows by `score_col`, but caps how many rows any
    single source can contribute so one high-volume/high-recency source
    (e.g. a source that happens to have same-day dates for everything)
    can't crowd out every other source's signal -- exactly the "all the
    sources seem to be from the same source" problem Chris flagged.
    Backfills from the overall ranking if the cap leaves the list short
    of `n` (e.g. only 2 sources total)."""
    if max_per_source is None:
        max_per_source = max(1, n // max(df[source_col].nunique(), 1) + 2)

    ranked = df.sort_values(score_col, ascending=False)
    counts: dict[str, int] = {}
    picked_idx = []
    overflow_idx = []
    for idx, source in ranked[source_col].items():
        if counts.get(source, 0) < max_per_source:
            picked_idx.append(idx)
            counts[source] = counts.get(source, 0) + 1
        else:
            overflow_idx.append(idx)
        if len(picked_idx) >= n:
            break

    if len(picked_idx) < n:
        picked_idx.extend(overflow_idx[: n - len(picked_idx)])

    return ranked.loc[picked_idx]
