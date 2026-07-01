"""
scripts/lib/regions.py

Shared ISO3/name -> (region, in_core_mandate) lookups, derived from the FIPS
geography tables already defined in scripts/lib/gdelt_geo.py (which is the
source of truth since it carries ISO3 codes alongside FIPS codes). Sources
that key by ISO3 (World Bank, IMF, AfDB, ...) or by plain country name
(ACLED, ReliefWeb, ...) can both use this instead of maintaining their own
country/region dicts.

If a country isn't in either the core mandate or extended-monitoring lists,
lookups return None — callers should fall back to GLOBAL_OTHER_REGION with
in_core_mandate=False, consistent with every other MERIDIAN source.
"""

from scripts.lib.gdelt_geo import FIPS_TO_COUNTRY, EXTENDED_FIPS_TO_COUNTRY

GLOBAL_OTHER_REGION = "Global / Other Monitoring"

# iso3 -> (country_name, region, in_core_mandate)
ISO3_TO_INFO: dict[str, tuple[str, str, bool]] = {}
# country_name -> (iso3, region, in_core_mandate)
NAME_TO_INFO: dict[str, tuple[str, str, bool]] = {}

for _name, _iso3, _region in FIPS_TO_COUNTRY.values():
    ISO3_TO_INFO[_iso3] = (_name, _region, True)
    NAME_TO_INFO[_name] = (_iso3, _region, True)

for _name, _iso3, _region in EXTENDED_FIPS_TO_COUNTRY.values():
    ISO3_TO_INFO[_iso3] = (_name, _region, False)
    NAME_TO_INFO[_name] = (_iso3, _region, False)


def lookup_by_iso3(iso3: str) -> tuple[str, str, bool] | None:
    """Returns (country_name, region, in_core_mandate) for an ISO3 code, or
    None if outside both the core mandate and extended monitoring lists."""
    return ISO3_TO_INFO.get(iso3)


def lookup_by_name(name: str) -> tuple[str, str, bool] | None:
    """Returns (iso3, region, in_core_mandate) for a country name, or None if
    outside both the core mandate and extended monitoring lists."""
    return NAME_TO_INFO.get(name)
