"""
scripts/analytics/conflict_signal_promotion.py

Chris's ask: "if there is a new story or social media post about a
terrorist attack, that is also now a conflict or security data point --
we need probably at least 2 sources for validation... I just want our
conflict data to be dynamic and not stale."

ACLED/GDELT are refreshed manually, not on a schedule (see
scripts/ingestion/*_fetch.py -- there's no cron/scheduler in this repo
yet), so the Conflict & Security tab can go stale between runs even
though the News & Social Signal sources (GDELT itself, Infobae, Jeune
Afrique, Bellingcat) may already be reporting something newer. This
module finds conflict-shaped news/social events that are CORROBORATED
by at least `min_sources` distinct sources reporting on the same
country within a short date window -- a single outlet's language isn't
enough signal on its own (one Reuters wire story republished with
different phrasing isn't independent corroboration, and one offhand
mention of "attack" in an unrelated headline definitely isn't), but two
or more distinct sources independently describing conflict-shaped
activity in the same country/window is a real signal worth surfacing
even before ACLED's next manual refresh catches up.

This does NOT replace ACLED as the vetted, structured conflict dataset
-- promoted signals are shown as a clearly-labeled "preliminary,
unverified" supplement, not merged into ACLED's own severity-scored
event stream.

Usage (as a module):
    from scripts.analytics.conflict_signal_promotion import detect_corroborated_conflict_signals
    promoted = detect_corroborated_conflict_signals(news_df)
"""

import re

import pandas as pd

# Narrower and more specific than significance.py's general BREAKING_KEYWORDS
# -- this is specifically about conflict/security-shaped language, not
# general "urgent news" (a market crash or a political resignation isn't
# a conflict signal, even though it might be breaking news).
CONFLICT_SIGNAL_KEYWORDS = [
    "attack", "airstrike", "air strike", "explosion", "bombing", "blast",
    "gunmen", "gunman", "ambush", "clash", "clashes", "shooting", "shootout",
    "militant", "insurgent", "terrorist", "terrorism", "raid", "shelling",
    "assassinat", "massacre", "kidnap", "hostage", "armed group", "rebel",
    "coup", "uprising", "insurrection", "mortar", "gunfire", "killed in",
]
_CONFLICT_SIGNAL_PATTERN = re.compile(
    "|".join(re.escape(term) for term in CONFLICT_SIGNAL_KEYWORDS), re.IGNORECASE
)


def detect_corroborated_conflict_signals(
    news_df: pd.DataFrame, min_sources: int = 2, date_window_days: int = 1,
) -> pd.DataFrame:
    """Returns the subset of `news_df` that matches conflict-shaped
    language AND has at least `min_sources` distinct sources reporting on
    the same country within a `date_window_days`-day window -- corroborated
    signal, not a single outlet's unverified mention. Returns an empty
    DataFrame (same columns) if nothing qualifies."""
    if len(news_df) == 0:
        return news_df.iloc[0:0]

    text = news_df.get("narrative_summary", pd.Series("", index=news_df.index)).fillna("").astype(str)
    # Prefer the English translation for keyword matching when available,
    # since CONFLICT_SIGNAL_KEYWORDS is an English word list -- otherwise
    # a genuinely conflict-shaped Spanish/French headline would never match.
    translated = news_df.get("narrative_summary_en")
    if translated is not None:
        text = translated.fillna(text)
    matches = news_df[text.str.contains(_CONFLICT_SIGNAL_PATTERN, na=False)].copy()
    if len(matches) == 0:
        return news_df.iloc[0:0]

    dates = pd.to_datetime(matches["event_date"], errors="coerce")
    # Bucket into date_window_days-wide windows so "yesterday" and "today"
    # mentions of the same unfolding event still group together, rather
    # than requiring the exact same calendar date.
    day_number = dates.dt.normalize().values.astype("datetime64[D]").astype("int64")
    matches["_window_bucket"] = day_number // date_window_days

    group_cols = ["country", "_window_bucket"]
    source_counts = matches.groupby(group_cols)["source"].transform("nunique")
    corroborated = matches[source_counts >= min_sources].drop(columns="_window_bucket")
    return corroborated.sort_values("event_date", ascending=False)
