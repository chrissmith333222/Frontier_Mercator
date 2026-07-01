"""
meridian/scripts/lib/gdelt_geo.py

Shared geography lookup for GDELT ingestion. GDELT's "Geo" fields (ActionGeo_*)
use 2-character FIPS 10-4 country codes, NOT ISO3 and NOT the same codes GDELT's
own "Actor" fields use (those are CAMEO/ISO-alpha based). This module maps
FIPS 10-4 -> (country name, ISO3, MERIDIAN region), restricted to MERIDIAN's
Africa + Latin America mandate.

Region groupings intentionally mirror scripts/ingestion/acled_normalize.py's
COUNTRY_TO_MERIDIAN_REGION so events from both sources bucket into the same
regions. If you change one, change the other.

Source for FIPS 10-4 codes: standard FIPS 10-4 country code table (verified
against Wikipedia's List of FIPS country codes, July 2026).
"""

# FIPS 10-4 code -> (country name, ISO3, MERIDIAN region)
FIPS_TO_COUNTRY = {
    # West Africa / Sahel
    "ML": ("Mali", "MLI", "West Africa / Sahel"),
    "UV": ("Burkina Faso", "BFA", "West Africa / Sahel"),
    "NG": ("Niger", "NER", "West Africa / Sahel"),
    "NI": ("Nigeria", "NGA", "West Africa / Sahel"),
    "GV": ("Guinea", "GIN", "West Africa / Sahel"),
    "SG": ("Senegal", "SEN", "West Africa / Sahel"),
    "GH": ("Ghana", "GHA", "West Africa / Sahel"),
    "IV": ("Ivory Coast", "CIV", "West Africa / Sahel"),
    "CD": ("Chad", "TCD", "West Africa / Sahel"),
    "MR": ("Mauritania", "MRT", "West Africa / Sahel"),
    "SL": ("Sierra Leone", "SLE", "West Africa / Sahel"),
    "LI": ("Liberia", "LBR", "West Africa / Sahel"),
    "BN": ("Benin", "BEN", "West Africa / Sahel"),
    "TO": ("Togo", "TGO", "West Africa / Sahel"),
    "PU": ("Guinea-Bissau", "GNB", "West Africa / Sahel"),
    "GA": ("Gambia", "GMB", "West Africa / Sahel"),
    # East Africa / Horn
    "ET": ("Ethiopia", "ETH", "East Africa / Horn"),
    "SO": ("Somalia", "SOM", "East Africa / Horn"),
    "SU": ("Sudan", "SDN", "East Africa / Horn"),
    "OD": ("South Sudan", "SSD", "East Africa / Horn"),
    "KE": ("Kenya", "KEN", "East Africa / Horn"),
    "UG": ("Uganda", "UGA", "East Africa / Horn"),
    "TZ": ("Tanzania", "TZA", "East Africa / Horn"),
    "ER": ("Eritrea", "ERI", "East Africa / Horn"),
    "DJ": ("Djibouti", "DJI", "East Africa / Horn"),
    "RW": ("Rwanda", "RWA", "East Africa / Horn"),
    "BY": ("Burundi", "BDI", "East Africa / Horn"),
    # Southern Africa
    "SF": ("South Africa", "ZAF", "Southern Africa"),
    "ZI": ("Zimbabwe", "ZWE", "Southern Africa"),
    "MZ": ("Mozambique", "MOZ", "Southern Africa"),
    "ZA": ("Zambia", "ZMB", "Southern Africa"),
    "MI": ("Malawi", "MWI", "Southern Africa"),
    "BC": ("Botswana", "BWA", "Southern Africa"),
    "WA": ("Namibia", "NAM", "Southern Africa"),
    "AO": ("Angola", "AGO", "Southern Africa"),
    "LT": ("Lesotho", "LSO", "Southern Africa"),
    "WZ": ("Eswatini", "SWZ", "Southern Africa"),
    # Central Africa
    "CG": ("Democratic Republic of Congo", "COD", "Central Africa"),
    "CM": ("Cameroon", "CMR", "Central Africa"),
    "CT": ("Central African Republic", "CAF", "Central Africa"),
    "CF": ("Republic of Congo", "COG", "Central Africa"),
    "GB": ("Gabon", "GAB", "Central Africa"),
    "EK": ("Equatorial Guinea", "GNQ", "Central Africa"),
    # North Africa
    "EG": ("Egypt", "EGY", "North Africa"),
    "MO": ("Morocco", "MAR", "North Africa"),
    "AG": ("Algeria", "DZA", "North Africa"),
    "TS": ("Tunisia", "TUN", "North Africa"),
    "LY": ("Libya", "LBY", "North Africa"),
    # Andean
    "PE": ("Peru", "PER", "Andean Region"),
    "BL": ("Bolivia", "BOL", "Andean Region"),
    "CO": ("Colombia", "COL", "Andean Region"),
    "EC": ("Ecuador", "ECU", "Andean Region"),
    "VE": ("Venezuela", "VEN", "Andean Region"),
    # Southern Cone
    "AR": ("Argentina", "ARG", "Southern Cone"),
    "BR": ("Brazil", "BRA", "Southern Cone"),
    "CI": ("Chile", "CHL", "Southern Cone"),
    "UY": ("Uruguay", "URY", "Southern Cone"),
    "PA": ("Paraguay", "PRY", "Southern Cone"),
    # Mexico / Central America / Caribbean
    "MX": ("Mexico", "MEX", "Mexico"),
    "ES": ("El Salvador", "SLV", "Central America & Caribbean"),
    "HO": ("Honduras", "HND", "Central America & Caribbean"),
    "GT": ("Guatemala", "GTM", "Central America & Caribbean"),
    "NU": ("Nicaragua", "NIC", "Central America & Caribbean"),
    "CS": ("Costa Rica", "CRI", "Central America & Caribbean"),
    "PM": ("Panama", "PAN", "Central America & Caribbean"),
    "HA": ("Haiti", "HTI", "Central America & Caribbean"),
    "DR": ("Dominican Republic", "DOM", "Central America & Caribbean"),
    "CU": ("Cuba", "CUB", "Central America & Caribbean"),
    "JM": ("Jamaica", "JAM", "Central America & Caribbean"),
}

MERIDIAN_FIPS_CODES = set(FIPS_TO_COUNTRY.keys())

# Extended monitoring: Europe + Middle East, per Chris's direction (2026-07-01)
# that MERIDIAN should track global developments for episodic/one-off reports,
# while core country/regional briefs stay scoped to Africa/LatAm. Not
# exhaustive (not "the whole world") — covers the major countries in these
# two regions specifically called out. in_core_mandate is False for all of these.
EXTENDED_FIPS_TO_COUNTRY = {
    # Europe
    "UK": ("United Kingdom", "GBR", "Europe"),
    "FR": ("France", "FRA", "Europe"),
    "GM": ("Germany", "DEU", "Europe"),
    "IT": ("Italy", "ITA", "Europe"),
    "SP": ("Spain", "ESP", "Europe"),
    "PO": ("Portugal", "PRT", "Europe"),
    "NL": ("Netherlands", "NLD", "Europe"),
    "BE": ("Belgium", "BEL", "Europe"),
    "SW": ("Sweden", "SWE", "Europe"),
    "NO": ("Norway", "NOR", "Europe"),
    "DA": ("Denmark", "DNK", "Europe"),
    "FI": ("Finland", "FIN", "Europe"),
    "PL": ("Poland", "POL", "Europe"),
    "EZ": ("Czech Republic", "CZE", "Europe"),
    "LO": ("Slovakia", "SVK", "Europe"),
    "HU": ("Hungary", "HUN", "Europe"),
    "RO": ("Romania", "ROU", "Europe"),
    "BU": ("Bulgaria", "BGR", "Europe"),
    "GR": ("Greece", "GRC", "Europe"),
    "UP": ("Ukraine", "UKR", "Europe"),
    "BO": ("Belarus", "BLR", "Europe"),
    "RS": ("Russia", "RUS", "Europe"),
    "MD": ("Moldova", "MDA", "Europe"),
    "AU": ("Austria", "AUT", "Europe"),
    "SZ": ("Switzerland", "CHE", "Europe"),
    "HR": ("Croatia", "HRV", "Europe"),
    "SI": ("Serbia", "SRB", "Europe"),
    "BK": ("Bosnia and Herzegovina", "BIH", "Europe"),
    "IE": ("Ireland", "IRL", "Europe"),
    # Middle East
    "IZ": ("Iraq", "IRQ", "Middle East"),
    "IR": ("Iran", "IRN", "Middle East"),
    "SY": ("Syria", "SYR", "Middle East"),
    "LE": ("Lebanon", "LBN", "Middle East"),
    "JO": ("Jordan", "JOR", "Middle East"),
    "IS": ("Israel", "ISR", "Middle East"),
    "SA": ("Saudi Arabia", "SAU", "Middle East"),
    "YM": ("Yemen", "YEM", "Middle East"),
    "TU": ("Turkey", "TUR", "Middle East"),
    "KU": ("Kuwait", "KWT", "Middle East"),
    "BA": ("Bahrain", "BHR", "Middle East"),
    "QA": ("Qatar", "QAT", "Middle East"),
    "TC": ("United Arab Emirates", "ARE", "Middle East"),
    "MU": ("Oman", "OMN", "Middle East"),
    "WE": ("West Bank", "PSE", "Middle East"),
    "GZ": ("Gaza Strip", "PSE", "Middle East"),
    "AF": ("Afghanistan", "AFG", "Middle East"),
    "PK": ("Pakistan", "PAK", "Middle East"),
}

EXTENDED_FIPS_CODES = set(EXTENDED_FIPS_TO_COUNTRY.keys())


def lookup_country(fips_code: str) -> tuple[str, str, str] | None:
    """Returns (country_name, iso3, meridian_region) for a FIPS 10-4 code, or
    None if it's outside MERIDIAN's Africa/LatAm mandate (e.g. US, CH, UK)."""
    return FIPS_TO_COUNTRY.get(fips_code)


def lookup_any_country(fips_code: str) -> tuple[str, str, str, bool] | None:
    """Returns (country_name, iso3, region, in_core_mandate) for a FIPS 10-4
    code, checking the core Africa/LatAm mandate first, then the extended
    Europe/Middle East monitoring list. Returns None only for locations
    outside both (e.g. US, Canada, East Asia) — those are still not tracked."""
    core = FIPS_TO_COUNTRY.get(fips_code)
    if core is not None:
        return (*core, True)
    extended = EXTENDED_FIPS_TO_COUNTRY.get(fips_code)
    if extended is not None:
        return (*extended, False)
    return None
