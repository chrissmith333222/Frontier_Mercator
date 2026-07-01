"""
scripts/lib/world_countries.py

Full-world country lookup (every ISO3166 country/territory, ~244), so the
report generator's country picker isn't limited to countries that already
have ingested event data (Chris's ask: "find and select any country in the
world"). Core-mandate (Africa/LatAm) and extended-monitoring (Europe/Middle
East) countries keep their detailed sub-region from scripts/lib/regions.py;
every other country gets a broad continent-based bucket via
pycountry_convert, still tagged in_core_mandate=False.

Centroid coordinates (scripts/lib/country_centroids.json, ISO3 -> [lat, lon])
came from github.com/gavinr/world-countries-centroids and are used to plot
country-level events (economic indicators, which have no native lat/lon)
on the unified map.
"""

import json
from pathlib import Path

import pycountry
import pycountry_convert as pc

from scripts.lib.regions import ISO3_TO_INFO

_CENTROIDS_PATH = Path(__file__).parent / "country_centroids.json"
COUNTRY_CENTROIDS: dict[str, tuple[float, float]] = {
    iso3: tuple(latlon) for iso3, latlon in json.loads(_CENTROIDS_PATH.read_text()).items()
}

_CONTINENT_TO_REGION = {
    "AF": "Africa (Other Monitoring)",
    "AS": "Asia (Other Monitoring)",
    "EU": "Europe",
    "NA": "North America",
    "SA": "South America (Other Monitoring)",
    "OC": "Oceania",
}


def _build_all_countries() -> dict[str, tuple[str, str, bool]]:
    """iso3 -> (country_name, region, in_core_mandate) for every ISO3166
    country. Core mandate + extended monitoring keep their detailed region
    from regions.py; everything else gets a continent-level bucket."""
    all_countries = dict(ISO3_TO_INFO)  # start with core + extended (already iso3 -> (name, region, mandate))

    for country in pycountry.countries:
        iso3 = getattr(country, "alpha_3", None)
        if not iso3 or iso3 in all_countries:
            continue
        try:
            continent_code = pc.country_alpha2_to_continent_code(country.alpha_2)
            region = _CONTINENT_TO_REGION.get(continent_code, "Global / Other Monitoring")
        except (KeyError, AttributeError):
            region = "Global / Other Monitoring"
        all_countries[iso3] = (country.name, region, False)

    return all_countries


ALL_COUNTRIES = _build_all_countries()


def get_centroid(iso3: str) -> tuple[float, float] | None:
    return COUNTRY_CENTROIDS.get(iso3)
