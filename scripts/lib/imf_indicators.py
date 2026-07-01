"""
scripts/lib/imf_indicators.py

Curated set of IMF World Economic Outlook indicators (via the DataMapper
API), mirroring the same handful of macro dimensions tracked from World Bank
(scripts/lib/worldbank_indicators.py) — deliberately overlapping sources so
gaps in one can be cross-checked against the other.
"""

# indicator_code -> (label, event_category)
INDICATORS = {
    "NGDP_RPCH": ("Real GDP growth (annual %)", "economic_indicator"),
    "PCPIPCH": ("Inflation, average consumer prices (annual %)", "economic_indicator"),
    "GGXWDG_NGDP": ("General government gross debt (% of GDP)", "economic_indicator"),
    "BCA_NGDPD": ("Current account balance (% of GDP)", "economic_indicator"),
    "LUR": ("Unemployment rate (%)", "economic_indicator"),
}

DEFAULT_INDICATOR_CODES = list(INDICATORS.keys())
