"""
scripts/lib/worldbank_indicators.py

Curated set of World Bank indicators relevant to MERIDIAN's investment/risk
mandate — not the full World Bank catalog (thousands of indicators), just the
handful that matter for emerging-market macro screening. Each maps to a
human-readable label and a MERIDIAN event_category.
"""

# indicator_code -> (label, event_category)
INDICATORS = {
    "NY.GDP.MKTP.KD.ZG": ("GDP growth (annual %)", "economic_indicator"),
    "FP.CPI.TOTL.ZG": ("Inflation, consumer prices (annual %)", "economic_indicator"),
    "DT.DOD.DECT.CD": ("External debt stocks, total (current US$)", "economic_indicator"),
    "BX.KLT.DINV.WD.GD.ZS": ("Foreign direct investment, net inflows (% of GDP)", "economic_indicator"),
    "BN.CAB.XOKA.GD.ZS": ("Current account balance (% of GDP)", "economic_indicator"),
    "SL.UEM.TOTL.ZS": ("Unemployment, total (% of labor force)", "economic_indicator"),
}

DEFAULT_INDICATOR_CODES = list(INDICATORS.keys())
