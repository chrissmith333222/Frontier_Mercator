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
    # Demographic/development indicators (Chris: HDI-adjacent indicators tied
    # to security/economic context -- income, education, lifespan -- plus a
    # dedicated demographics sub-tab: birth rates, working-age population,
    # male/female split). Same World Bank API/backend as the economic
    # indicators above, just a different indicator set and event_category so
    # they don't get mixed into the Macro Indicators tab.
    "SP.POP.TOTL": ("Population, total", "demographic_indicator"),
    "SP.POP.GROW": ("Population growth (annual %)", "demographic_indicator"),
    "SP.DYN.LE00.IN": ("Life expectancy at birth, total (years)", "demographic_indicator"),
    "SP.DYN.CBRT.IN": ("Birth rate, crude (per 1,000 people)", "demographic_indicator"),
    "SP.URB.TOTL.IN.ZS": ("Urban population (% of total)", "demographic_indicator"),
    "SP.POP.1564.TO.ZS": ("Working-age population, 15-64 (% of total)", "demographic_indicator"),
    "SP.POP.65UP.TO.ZS": ("Population ages 65 and above (% of total)", "demographic_indicator"),
    "SP.POP.TOTL.FE.ZS": ("Population, female (% of total)", "demographic_indicator"),
    "SE.ADT.LITR.ZS": ("Literacy rate, adult total (% ages 15+)", "demographic_indicator"),
}

DEFAULT_INDICATOR_CODES = list(INDICATORS.keys())
