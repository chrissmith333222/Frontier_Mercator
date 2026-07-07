"""
scripts/ingestion/unctad_maritime_fetch.py

Fetches UNCTAD's maritime/shipping statistics via their bulk-download API
(unctadstat-api.unctad.org/bulkdownload/<dataset>/<file>, no auth, no key
-- verified live 2026-07-07) and writes a compact per-country JSON the
dashboard's Shipping & Maritime tab reads statically.

This is aggregate COUNTRY-LEVEL shipping data (connectivity index, port
performance, container throughput, seaborne trade volumes) -- NOT live
vessel/AIS tracking, which has no free source (MarineTraffic et al. are
paid; that remains a documented gap, same conclusion as the original
architecture research). Chris approved this scope explicitly (2026-07-07):
trade-flow context per country over live ship positions.

Four datasets, all verified to parse:
  - US.LSCI: Liner Shipping Connectivity Index, quarterly, 2006-present.
    How well-connected a country is to global container networks --
    UNCTAD's own headline indicator for market access.
  - US.PortCalls: median time in port + vessel age by ship type, yearly.
    Port efficiency proxy ("All ships" kept, per-ship-type dropped).
  - US.ContPortThroughput: container throughput (TEU), yearly.
  - US.SeaborneTrade: goods loaded/discharged (thousand tons), yearly.
    Total loaded + discharged kept; per-cargo-type breakdown dropped to
    keep the output file small.

Output goes to data/normalized/maritime_stats.json as its own compact file
(same pattern as commodity_prices.json) rather than into merged_dataset.json
-- the merged file already carries a 70MB git-size warning, and this data is
indicator-style time series, not discrete events.

Usage:
    python scripts/ingestion/unctad_maritime_fetch.py
"""

import sys
import io
import csv
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# requests/py7zr deliberately NOT imported at module level: the deployed
# Streamlit app imports this module just for load_maritime_stats() (reading
# the pre-generated JSON), and py7zr isn't in the deployed requirements --
# only the offline fetch path needs it. See _fetch_csv_rows.
from scripts.lib.regions import ISO3_TO_INFO

API_BASE = "https://unctadstat-api.unctad.org/bulkdownload"
OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "normalized" / "maritime_stats.json"

# UNCTAD labels countries by name (plus UN M49 numeric codes, which don't
# map cleanly to ISO3 without an extra table) -- match on name, with
# aliases for the countries UNCTAD spells differently than world_countries.
UNCTAD_NAME_ALIASES = {
    "Côte d'Ivoire": "Ivory Coast",
    "Congo, Democratic Republic of the": "Democratic Republic of Congo",
    "Congo, Dem. Rep. of the": "Democratic Republic of Congo",
    "Democratic Republic of the Congo": "Democratic Republic of Congo",
    "Congo": "Republic of Congo",
    "Tanzania, United Republic of": "Tanzania",
    "United Republic of Tanzania": "Tanzania",
    "Bolivia (Plurinational State of)": "Bolivia",
    "Venezuela (Bolivarian Republic of)": "Venezuela",
    "Iran (Islamic Republic of)": "Iran",
    "Syrian Arab Republic": "Syria",
    "Türkiye": "Turkey",
    "Russian Federation": "Russia",
    "Egypt": "Egypt",
    "Cabo Verde": "Cape Verde",
    "Gambia": "Gambia",
    "Eswatini": "Eswatini",
    "Viet Nam": "Vietnam",
    "Korea, Republic of": "South Korea",
    "Republic of Korea": "South Korea",
    "Moldova, Republic of": "Moldova",
    "Republic of Moldova": "Moldova",
    "North Macedonia": "North Macedonia",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    "Dominican Republic": "Dominican Republic",
    "United Arab Emirates": "United Arab Emirates",
    "Saudi Arabia": "Saudi Arabia",
}

_TRACKED_NAMES = {name for name, _region, _mandate in ISO3_TO_INFO.values()}


def _resolve_country(economy_label: str) -> str | None:
    """Maps an UNCTAD Economy Label to a tracked country name, or None if
    it's a region/aggregate or a country outside the tracked set."""
    name = UNCTAD_NAME_ALIASES.get(economy_label, economy_label)
    return name if name in _TRACKED_NAMES else None


def _fetch_csv_rows(dataset: str, filename: str) -> list[dict]:
    """Downloads one UNCTAD bulk 7z archive and returns its CSV rows as
    dicts. The archive always contains exactly one CSV."""
    import requests
    import py7zr

    url = f"{API_BASE}/{dataset}/{filename}"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(f"UNCTAD download failed for {dataset}: status {response.status_code}")
    # py7zr 1.x dropped the in-memory read()/readall() API -- extract to a
    # temp dir and read the single CSV from disk instead.
    with tempfile.TemporaryDirectory() as tmp_dir:
        with py7zr.SevenZipFile(io.BytesIO(response.content)) as archive:
            archive.extractall(tmp_dir)
        for csv_path in Path(tmp_dir).rglob("*.csv"):
            text = csv_path.read_text(encoding="utf-8-sig")
            return list(csv.DictReader(io.StringIO(text)))
    raise RuntimeError(f"UNCTAD archive for {dataset} contained no CSV")


def _parse_float(value: str) -> float | None:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def fetch_lsci() -> dict:
    """Liner Shipping Connectivity Index -> {country: {"YYYYQn": value}}."""
    series: dict[str, dict] = {}
    for row in _fetch_csv_rows("US.LSCI", "US_LSCI"):
        country = _resolve_country(row["Economy Label"])
        value = _parse_float(row.get("Index (Average Q1 2023 = 100)"))
        if country is None or value is None:
            continue
        quarter = row["Quarter"].replace("Q0", "Q")  # 2006Q01 -> 2006Q1
        series.setdefault(country, {})[quarter] = value
    return series


def fetch_port_calls() -> dict:
    """Port performance ("All ships" only) ->
    {country: {year: {"median_time_in_port_days", "avg_vessel_age_years"}}}."""
    series: dict[str, dict] = {}
    for row in _fetch_csv_rows("US.PortCalls", "US_PortCalls"):
        if row.get("CommercialMarket Label") != "All ships":
            continue
        country = _resolve_country(row["Economy Label"])
        if country is None:
            continue
        entry = {}
        median_days = _parse_float(row.get("Median time in port (days)"))
        vessel_age = _parse_float(row.get("Average age of vessels (years)"))
        if median_days is not None:
            entry["median_time_in_port_days"] = median_days
        if vessel_age is not None:
            entry["avg_vessel_age_years"] = vessel_age
        if entry:
            series.setdefault(country, {})[row["Year"]] = entry
    return series


def fetch_container_throughput() -> dict:
    """Container port throughput -> {country: {year: TEU}}."""
    series: dict[str, dict] = {}
    for row in _fetch_csv_rows("US.ContPortThroughput", "US_ContPortThroughput"):
        country = _resolve_country(row["Economy Label"])
        value = _parse_float(row.get("TEU (Twenty foot Equivalent Unit)"))
        if country is None or value is None:
            continue
        series.setdefault(country, {})[row["Year"]] = value
    return series


def fetch_seaborne_trade() -> dict:
    """Seaborne trade (totals only) ->
    {country: {year: {"loaded_kt", "discharged_kt"}}}."""
    key_by_label = {
        "Total goods loaded": "loaded_kt",
        "Total goods discharged": "discharged_kt",
    }
    series: dict[str, dict] = {}
    for row in _fetch_csv_rows("US.SeaborneTrade", "US_SeaborneTrade"):
        key = key_by_label.get(row.get("CargoType Label", ""))
        if key is None:
            continue
        country = _resolve_country(row["Economy Label"])
        value = _parse_float(row.get("Metric tons in thousands"))
        if country is None or value is None:
            continue
        series.setdefault(country, {}).setdefault(row["Year"], {})[key] = value
    return series


def load_maritime_stats(path: Path = OUTPUT_PATH) -> dict:
    """Reads the cached maritime stats file. Returns {} if it hasn't been
    generated yet, so the dashboard degrades gracefully."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def main():
    stats = {"fetched_at": datetime.now(timezone.utc).isoformat()}
    for key, fetch_fn in [
        ("lsci", fetch_lsci),
        ("port_calls", fetch_port_calls),
        ("container_throughput", fetch_container_throughput),
        ("seaborne_trade", fetch_seaborne_trade),
    ]:
        try:
            stats[key] = fetch_fn()
            print(f"  {key}: {len(stats[key])} countries", file=sys.stderr)
        except Exception as e:
            # One dataset being down shouldn't zero out the other three --
            # keep whatever already exists in the cached file for that key.
            print(f"  WARNING: {key} failed ({e}), keeping previous data if any", file=sys.stderr)
            stats[key] = load_maritime_stats().get(key, {})

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print(f"Wrote maritime stats to {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
