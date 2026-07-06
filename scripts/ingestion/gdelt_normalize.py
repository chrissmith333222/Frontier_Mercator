"""
meridian/scripts/ingestion/gdelt_normalize.py

Maps raw GDELT 2.0 event records into MERIDIAN's common normalized_event
schema (see schemas/normalized_event.schema.json). This is the only place
GDELT's field names/CAMEO codes should appear outside of gdelt_fetch.py and
this file.

Usage:
    python scripts/ingestion/gdelt_normalize.py --input raw_gdelt.json --output normalized.json

Or as a module:
    from scripts.ingestion.gdelt_normalize import normalize_gdelt_event, normalize_batch
"""

import sys
import re
import html
import argparse
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests

from scripts.lib.gdelt_geo import lookup_any_country

# CAMEO EventRootCode -> a human-readable label for narrative_summary.
# GDELT's raw Events table (unlike its GKG/mentions tables) has no
# headline/summary field at all -- just actor codes, a numeric CAMEO
# event code, and a source URL -- so a bare "(CAMEO 190)" was genuinely
# meaningless to a reader. All 20 CAMEO root categories are covered here
# (not just the 7 that map to a MERIDIAN event_category below), since
# even "other"-bucketed events deserve a readable label.
CAMEO_ROOT_LABELS = {
    "01": "made a public statement", "02": "made an appeal",
    "03": "expressed intent to cooperate", "04": "held consultations",
    "05": "engaged in diplomatic cooperation", "06": "engaged in material cooperation",
    "07": "provided aid", "08": "yielded/de-escalated", "09": "was investigated",
    "10": "issued a demand", "11": "expressed disapproval", "12": "issued a rejection",
    "13": "issued a threat", "14": "was the site of a protest",
    "15": "exhibited a military posture", "16": "reduced relations",
    "17": "was coerced", "18": "was the site of an assault",
    "19": "was the site of fighting", "20": "was the site of unconventional mass violence",
}

# CAMEO EventRootCode -> MERIDIAN's coarse event_category.
# GDELT's own taxonomy (CAMEO 1.1b3) is far more granular (20 root codes,
# hundreds of sub-codes) — this collapses it to the same categories ACLED
# events map into, so both sources merge cleanly downstream.
EVENT_ROOT_CODE_MAP = {
    "14": "protest_civil_unrest",       # Protest
    "15": "strategic_development",      # Exhibit military posture
    "16": "strategic_development",      # Reduce relations
    "17": "conflict",                   # Coerce
    "18": "political_violence_targeting_civilians",  # Assault
    "19": "conflict",                   # Fight
    "20": "explosion_remote_violence",  # Use unconventional mass violence
}

# Base severity by EventRootCode, mirroring ACLED's transparent-scoring approach.
BASE_SEVERITY_BY_ROOT_CODE = {
    "14": 3.0, "15": 4.0, "16": 3.0, "17": 5.0, "18": 6.5, "19": 6.0, "20": 7.0,
}


def compute_severity_score(record: dict) -> float:
    """
    MERIDIAN's 0-10 severity score for a GDELT event: base score from the
    CAMEO event root code, adjusted upward by how conflictual GDELT's own
    Goldstein Scale rates the event (Goldstein runs -10 to +10; more negative
    = more conflictual). Capped at 10, same convention as the ACLED scorer.
    """
    root_code = record.get("EventRootCode", "")
    base = BASE_SEVERITY_BY_ROOT_CODE.get(root_code, 1.5)

    try:
        goldstein = float(record.get("GoldsteinScale", 0) or 0)
    except (ValueError, TypeError):
        goldstein = 0.0

    goldstein_bump = max(0.0, -goldstein / 10.0 * 3.0)  # 0 to 3.0 as goldstein -> -10

    return min(round(base + goldstein_bump, 1), 10.0)


def make_meridian_event_id(source: str, source_event_id: str) -> str:
    """Deterministic ID so re-running ingestion doesn't create duplicate records."""
    raw = f"{source}:{source_event_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def extract_actors(record: dict) -> list[dict]:
    """Pulls Actor1Name/Actor2Name into MERIDIAN's actors array. GDELT doesn't
    give a clean actor "type" the way ACLED's inter1/inter2 codes do, so we
    carry the raw CAMEO actor type code as-is for traceability."""
    actors = []
    for name_field, type_field in [("Actor1Name", "Actor1Type1Code"), ("Actor2Name", "Actor2Type1Code")]:
        name = record.get(name_field)
        if name:
            actors.append({
                "name": name,
                "type": record.get(type_field) or "unknown",
            })
    return actors


def normalize_gdelt_event(record: dict) -> dict | None:
    """Maps a single raw GDELT record into the MERIDIAN normalized_event schema.
    Returns None if the event's location doesn't resolve to either the core
    Africa/LatAm mandate or the extended Europe/Middle East monitoring list
    (shouldn't happen post-fetch-filtering, but defensive here too)."""
    fips_code = record.get("ActionGeo_CountryCode", "")
    geo = lookup_any_country(fips_code)
    if geo is None:
        return None
    country, iso3, region, in_core_mandate = geo

    source_event_id = record.get("GLOBALEVENTID", "")
    root_code = record.get("EventRootCode", "")
    sql_date = record.get("SQLDATE", "")  # format YYYYMMDD

    try:
        event_date = datetime.strptime(sql_date, "%Y%m%d").date().isoformat()
    except ValueError:
        event_date = None

    try:
        lat = float(record["ActionGeo_Lat"]) if record.get("ActionGeo_Lat") not in (None, "") else None
        lon = float(record["ActionGeo_Long"]) if record.get("ActionGeo_Long") not in (None, "") else None
    except (ValueError, TypeError):
        lat, lon = None, None

    actor1 = record.get("Actor1Name") or "unspecified actor"
    actor2 = record.get("Actor2Name") or "unspecified actor"
    action_label = CAMEO_ROOT_LABELS.get(root_code, f"was involved in a CAMEO {record.get('EventCode', '?')} event")
    narrative_summary = f"{actor1} <-> {actor2}: {action_label}"

    return {
        "meridian_event_id": make_meridian_event_id("GDELT", source_event_id),
        "source": "GDELT",
        "source_event_id": source_event_id,
        "event_date": event_date,
        "country": country,
        "iso3": iso3,
        "admin1": record.get("ActionGeo_ADM1Code"),
        "region": region,
        "in_core_mandate": in_core_mandate,
        "latitude": lat,
        "longitude": lon,
        "event_category": EVENT_ROOT_CODE_MAP.get(root_code, "other"),
        "event_subtype": record.get("EventCode"),
        "actors": extract_actors(record),
        "fatalities": None,  # GDELT doesn't report fatality counts (unlike ACLED)
        "severity_score": compute_severity_score(record),
        "narrative_summary": narrative_summary,
        "source_url": record.get("SOURCEURL"),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "raw_source_data": record,
    }


_TITLE_TAG_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# Matches enrich_headlines()'s exact "<headline> (ACTOR1 <-> ACTOR2)" output
# format -- requires "<->" inside the trailing parenthetical so this doesn't
# also match the unrelated legacy "ACTOR1 <-> ACTOR2 (CAMEO 190)" fallback
# format, which also ends in a parenthetical but isn't real article text.
_ENRICHED_SUFFIX_PATTERN = re.compile(r"^(.*)\s\(([^()]*<->[^()]*)\)$")

# Splits off a trailing " - Outlet Name" / " | Outlet Name" attribution
# suffix from a headline -- see revalidate_geolocation for why this matters.
_OUTLET_SUFFIX_PATTERN = re.compile(r"\s[-|]\s")


def fetch_article_headline(url: str, timeout: float = 4.0) -> str | None:
    """Best-effort fetch of the real headline from a GDELT event's source
    article (Chris: "I click the link and it actually describes the
    event" -- GDELT's raw Events table has no headline field at all, only
    actor codes + a CAMEO action code, but the linked article obviously
    has a real description). Returns None on any failure (dead link,
    timeout, paywall, non-HTML response) rather than raising, since this
    runs across a whole batch and most individual failures should just
    fall back to the existing CAMEO-based summary, not abort the batch."""
    if not url:
        return None
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        if response.status_code != 200:
            return None
        match = _TITLE_TAG_PATTERN.search(response.text)
        if not match:
            return None
        title = html.unescape(match.group(1)).strip()
        title = re.sub(r"\s+", " ", title)
        if len(title) < 8:
            return None
        return title[:300]
    except Exception:
        return None


def enrich_headlines(events: list[dict], max_workers: int = 20) -> int:
    """Replaces each event's narrative_summary with the real article
    headline where one can be fetched, keeping the existing CAMEO-based
    summary as the fallback. Runs fetches concurrently (GDELT batches can
    be thousands of events; a sequential per-event HTTP fetch would make
    a routine ingestion run take hours) -- opt-in via --enrich-headlines,
    not run by default, since it's slow and network-dependent in a way
    unit tests and quick local re-normalization shouldn't have to pay for.
    Returns the number of events successfully enriched."""
    events_by_url = {e["meridian_event_id"]: e for e in events if e.get("source_url")}
    enriched_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(fetch_article_headline, event["source_url"]): event_id
            for event_id, event in events_by_url.items()
        }
        for future in as_completed(futures):
            event_id = futures[future]
            headline = future.result()
            if headline:
                event = events_by_url[event_id]
                actor_context = event["narrative_summary"].split(": ", 1)
                actors = actor_context[0] if len(actor_context) == 2 else ""
                event["narrative_summary"] = f"{headline} ({actors})" if actors else headline
                enriched_count += 1
    return enriched_count


def revalidate_geolocation(events: list[dict]) -> int:
    """Cross-checks each event's ActionGeo-derived country against its
    enriched headline text (only meaningful after enrich_headlines() has
    run -- events without a real headline have nothing to cross-check
    against) and corrects the country/region/mandate/coordinates when
    the headline clearly indicates a different country than ActionGeo
    resolved to. GDELT's ActionGeo field is documented as the action's
    own location, but empirically sometimes reflects the article's
    dateline/bureau location instead -- Chris caught a real case where a
    Central African Republic attack, sourced from a Yaounde (Cameroon)
    news bureau, was mapped as a Cameroon event.

    Deliberately conservative: only reassigns when (a) the headline does
    NOT mention the current country by name, AND (b) exactly one other
    tracked country is clearly mentioned. A blind "trust whichever geo
    field disagrees with ActionGeo" heuristic is unsafe -- verified
    against this project's own ingested data that events where
    Actor1Geo/Actor2Geo both point to a country different from ActionGeo
    are often genuinely foreign-actor-in-local-event cases (e.g. a
    Chinese-financed project at a Peruvian port, correctly geocoded to
    Peru even though both actors are Shanghai-based) -- acting on actor-
    geo disagreement alone would make that case WORSE, not better. Text
    cross-validation against the real headline avoids that failure mode.

    Returns the number of events corrected."""
    from scripts.lib.gdelt_geo import NAME_TO_COUNTRY
    from scripts.lib.world_countries import get_centroid

    corrected = 0
    for event in events:
        summary = event.get("narrative_summary", "")
        # Only trust this as real article text if it matches
        # enrich_headlines()'s exact "<headline> (ACTOR1 <-> ACTOR2)"
        # format -- specifically requiring "<->" inside the trailing
        # parenthetical. A plain `.endswith(")")` check is NOT enough: a
        # real bug caught while testing this function was that un-enriched
        # events in the older "ACTOR1 <-> ACTOR2 (CAMEO 190)" fallback
        # format also end in ")", and their "headline" portion under a
        # naive split is just the GDELT actor names (e.g. "SPAIN",
        # "IRAN") -- which are frequently themselves country names,
        # causing this function to "correct" a country to match an actor
        # name with zero connection to real article content.
        match = _ENRICHED_SUFFIX_PATTERN.match(summary)
        if not match:
            continue  # not the real-headline format -- nothing genuine to cross-check
        # Strip a trailing " - Outlet Name" / " | Outlet Name" attribution
        # suffix (a very common headline convention) before scanning --
        # without this, outlet names that happen to contain a country
        # ("Daily Post Nigeria", "Israel National News", "Israel & Jewish
        # News - JNS") get mistaken for the article being about that
        # country, when the actual story may have nothing to do with it.
        headline = _OUTLET_SUFFIX_PATTERN.split(match.group(1), maxsplit=1)[0].lower()
        current_country = (event.get("country") or "").lower()
        if not current_country or current_country == "global":
            continue
        if current_country in headline:
            continue  # headline confirms the existing country -- no change needed

        mentioned = {
            info for name, info in NAME_TO_COUNTRY.items()
            if name != current_country and re.search(r"\b" + re.escape(name) + r"\b", headline)
        }
        if len(mentioned) != 1:
            continue  # ambiguous (0 or 2+ candidates) -- leave as-is rather than guess

        new_name, new_iso3, new_region, new_mandate = next(iter(mentioned))
        event["country"] = new_name
        event["iso3"] = new_iso3
        event["region"] = new_region
        event["in_core_mandate"] = new_mandate
        centroid = get_centroid(new_iso3)
        if centroid:
            event["latitude"], event["longitude"] = centroid
        corrected += 1
    return corrected


def normalize_batch(raw_events: list[dict]) -> list[dict]:
    """Normalizes a list of raw GDELT events, skipping records that fail to
    normalize (malformed or non-mandate-country) rather than failing the batch."""
    normalized = []
    skipped = 0
    for record in raw_events:
        try:
            result = normalize_gdelt_event(record)
            if result is None:
                skipped += 1
                continue
            normalized.append(result)
        except Exception as e:
            skipped += 1
            print(f"WARNING: skipped malformed GDELT record "
                  f"({record.get('GLOBALEVENTID', 'unknown id')}): {e}", file=sys.stderr)
    if skipped:
        print(f"Normalization complete with {skipped} record(s) skipped out of {len(raw_events)}.",
              file=sys.stderr)
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Normalize raw GDELT events into MERIDIAN schema")
    parser.add_argument("--input", type=str, required=True, help="Path to raw GDELT JSON (from gdelt_fetch.py)")
    parser.add_argument("--output", type=str, default=None, help="Output path. Omit to print to stdout.")
    parser.add_argument("--enrich-headlines", action="store_true",
                         help="Fetch each event's source article and use its real headline as the "
                              "narrative_summary where possible, falling back to the CAMEO-based "
                              "summary otherwise. Slower (one HTTP request per event, concurrently) "
                              "and network-dependent -- off by default.")
    args = parser.parse_args()

    raw_events = json.loads(Path(args.input).read_text())
    normalized = normalize_batch(raw_events)

    if args.enrich_headlines:
        enriched_count = enrich_headlines(normalized)
        print(f"Enriched {enriched_count}/{len(normalized)} events with a real article headline.",
              file=sys.stderr)
        # Geolocation cross-checking is only meaningful once a real
        # headline exists to check against, so it rides along with
        # --enrich-headlines rather than being a separate flag.
        corrected_count = revalidate_geolocation(normalized)
        print(f"Corrected {corrected_count}/{len(normalized)} events' geolocation based on "
              f"a headline/ActionGeo mismatch.", file=sys.stderr)

    output_json = json.dumps(normalized, indent=2)
    if args.output:
        Path(args.output).write_text(output_json)
        print(f"Wrote {len(normalized)} normalized events to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
