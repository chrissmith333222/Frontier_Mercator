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


def lookup_country(fips_code: str) -> tuple[str, str, str] | None:
    """Returns (country_name, iso3, meridian_region) for a FIPS 10-4 code, or
    None if it's outside MERIDIAN's Africa/LatAm mandate (e.g. US, CH, UK)."""
    return FIPS_TO_COUNTRY.get(fips_code)
