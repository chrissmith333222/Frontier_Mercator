"""
scripts/lib/instrument_universe.py

Curated universe of real, publicly tradeable instruments -- the bridge
between Parallax's analytical insights and Chris's "so what / what now"
goal: for any thesis the platform generates ("agriculture in West Africa
outperforms over 12 months"), there is almost never a direct
"Benin Agriculture ETF" -- instead you work down an investment stack of
increasingly specific instruments (regional ETF -> sector ETF -> commodity
-> individual company), trading directness of exposure against liquidity
and risk.

Every entry: ticker -> (name, layer, exposure_note). Layers follow the
stack Chris specced (2026-07-07):
  - regional_etf: country/region equity baskets (most liquid, least specific)
  - sector_etf: global sector/theme baskets
  - commodity: commodity funds/futures-based ETFs (+ the direct futures
    tickers already tracked in commodity_data.py)
  - company: individual listed equities/ADRs with genuine emerging/frontier
    exposure (least liquid path, most specific)

Tickers are VERIFIED against Yahoo Finance at thesis-generation time
(verify_universe() below) -- delisted/renamed funds get dropped from the
universe offered to the model rather than shipped to the site. Frontier
ETFs delist often (VanEck Africa AFK closed 2020, Nigeria NGE closed 2021
-- both deliberately absent), so nothing here is assumed permanently valid.

This is a research-mapping tool, not investment advice -- the dashboard
and PDF surfaces carry the same disclaimer as every other analytical
output on the platform.
"""

# ticker -> (name, layer, exposure_note)
INSTRUMENTS = {
    # --- Regional / country ETFs ---
    # NOTE on absent "obvious" candidates, all verified dead 2026-07-07 (no
    # trades in last 5 sessions): FM (iShares Frontier & Select EM --
    # liquidated), EGPT (VanEck Egypt), GULF (WisdomTree ME Dividend),
    # NIB/JO (iPath cocoa/coffee ETNs, delisted 2018), plus AFK (VanEck
    # Africa, closed 2020) and NGE (Nigeria, closed 2021). There is
    # currently NO liquid US-listed frontier-Africa country ETF -- regional
    # exposure goes through EM baskets, sector ETFs, or single names.
    "EEM":  ("iShares MSCI Emerging Markets ETF", "regional_etf", "Broad EM benchmark"),
    "VWO":  ("Vanguard FTSE Emerging Markets ETF", "regional_etf", "Broad EM benchmark, lower fee"),
    "EZA":  ("iShares MSCI South Africa ETF", "regional_etf", "South Africa large/mid caps"),
    "ILF":  ("iShares Latin America 40 ETF", "regional_etf", "LatAm large caps (Brazil/Mexico heavy)"),
    "EWZ":  ("iShares MSCI Brazil ETF", "regional_etf", "Brazil large caps"),
    "EWW":  ("iShares MSCI Mexico ETF", "regional_etf", "Mexico large caps"),
    "ECH":  ("iShares MSCI Chile ETF", "regional_etf", "Chile equities (copper-economy proxy)"),
    "EPU":  ("iShares MSCI Peru ETF", "regional_etf", "Peru equities (mining-economy proxy)"),
    "GXG":  ("Global X MSCI Colombia ETF", "regional_etf", "Colombia equities"),
    "ARGT": ("Global X MSCI Argentina ETF", "regional_etf", "Argentina equities"),
    "KSA":  ("iShares MSCI Saudi Arabia ETF", "regional_etf", "Saudi Arabia equities"),
    "TUR":  ("iShares MSCI Turkey ETF", "regional_etf", "Turkey equities"),
    "VNM":  ("VanEck Vietnam ETF", "regional_etf", "Vietnam (frontier-manufacturing proxy)"),

    # --- Sector / theme ETFs ---
    "MOO":  ("VanEck Agribusiness ETF", "sector_etf", "Global agribusiness value chain (equipment, seeds, fertilizer, processing)"),
    "VEGI": ("iShares MSCI Global Agriculture Producers ETF", "sector_etf", "Global agriculture producers"),
    "PICK": ("iShares MSCI Global Metals & Mining Producers ETF", "sector_etf", "Global diversified miners ex-gold"),
    "COPX": ("Global X Copper Miners ETF", "sector_etf", "Copper miners (DRC/Zambia/Chile/Peru exposure via producers)"),
    "GDX":  ("VanEck Gold Miners ETF", "sector_etf", "Gold miners (significant West African mine exposure)"),
    "LIT":  ("Global X Lithium & Battery Tech ETF", "sector_etf", "Lithium/battery value chain"),
    "URA":  ("Global X Uranium ETF", "sector_etf", "Uranium miners (incl. Niger/Namibia exposure via producers)"),
    "REMX": ("VanEck Rare Earth/Strategic Metals ETF", "sector_etf", "Rare earth & strategic metals producers"),
    "SLX":  ("VanEck Steel ETF", "sector_etf", "Steel producers (iron-ore demand proxy)"),
    "SEA":  ("U.S. Global Sea to Sky Cargo ETF", "sector_etf", "Marine shipping & air freight"),
    "BOAT": ("SonicShares Global Shipping ETF", "sector_etf", "Global marine shipping pure-play"),
    "PAVE": ("Global X U.S. Infrastructure Development ETF", "sector_etf", "US infrastructure buildout (equipment/materials read-through)"),
    "IGF":  ("iShares Global Infrastructure ETF", "sector_etf", "Global listed infrastructure (utilities, transport, energy)"),
    "GUNR": ("FlexShares Global Upstream Natural Resources ETF", "sector_etf", "Upstream natural resources (energy, metals, agriculture, water, timber)"),
    "XLE":  ("Energy Select Sector SPDR Fund", "sector_etf", "US large-cap energy"),
    "ITA":  ("iShares U.S. Aerospace & Defense ETF", "sector_etf", "Aerospace & defense (great-power-competition read-through)"),
    "PHO":  ("Invesco Water Resources ETF", "sector_etf", "Water infrastructure & treatment"),

    # --- Commodity funds (futures-based ETFs; direct futures live in commodity_data.py) ---
    "DBA":  ("Invesco DB Agriculture Fund", "commodity", "Diversified agriculture futures basket"),
    "CANE": ("Teucrium Sugar Fund", "commodity", "Sugar futures"),
    "WEAT": ("Teucrium Wheat Fund", "commodity", "Wheat futures"),
    "CORN": ("Teucrium Corn Fund", "commodity", "Corn futures"),
    "SOYB": ("Teucrium Soybean Fund", "commodity", "Soybean futures"),
    "USO":  ("United States Oil Fund", "commodity", "WTI crude futures"),
    "UNG":  ("United States Natural Gas Fund", "commodity", "Natural gas futures"),
    "GLD":  ("SPDR Gold Shares", "commodity", "Physical gold"),
    "SLV":  ("iShares Silver Trust", "commodity", "Physical silver"),
    "CPER": ("United States Copper Index Fund", "commodity", "Copper futures"),

    # --- Individual companies (ADRs / US-listed with genuine frontier-EM exposure) ---
    "FCX":   ("Freeport-McMoRan", "company", "Copper/gold producer (Indonesia, Americas; DRC exposure sold but copper-price proxy)"),
    "VALE":  ("Vale S.A.", "company", "Brazilian iron ore/nickel giant"),
    "RIO":   ("Rio Tinto", "company", "Diversified miner (Guinea Simandou iron ore, Mongolia copper)"),
    "BHP":   ("BHP Group", "company", "Diversified miner"),
    "IVPAF": ("Ivanhoe Mines", "company", "DRC copper (Kamoa-Kakula) -- direct central-Africa mining exposure"),
    "FQVLF": ("First Quantum Minerals", "company", "Copper (Zambia, Panama) -- direct African copperbelt exposure"),
    "CAT":   ("Caterpillar", "company", "Mining/construction equipment (infrastructure-buildout supplier read)"),
    "DE":    ("Deere & Company", "company", "Agricultural equipment"),
    "NTR":   ("Nutrien", "company", "Fertilizer (potash/nitrogen) -- ag-intensification supplier read"),
    "MOS":   ("Mosaic Company", "company", "Fertilizer (phosphate/potash)"),
    "ADM":   ("Archer-Daniels-Midland", "company", "Agricultural origination/processing (buys West African crops)"),
    "BG":    ("Bunge Global", "company", "Agricultural origination/processing"),
    "BTI":   ("British American Tobacco", "company", "Deep Africa/EM consumer distribution"),
    "MTNOY": ("MTN Group ADR", "company", "Pan-African telecom (Nigeria/Ghana/SA) -- digitization proxy"),
    # Safaricom deliberately absent: no working US OTC/ADR ticker on Yahoo
    # (candidates SAFRF/SAFRY resolve to Safran, the French aerospace firm
    # -- identity verified 2026-07-07). Airtel Africa's London listing is
    # the tradeable East/West-Africa telecom + mobile-money exposure.
    "AAF.L": ("Airtel Africa plc (London)", "company", "African telecom/mobile money across 14 markets -- digitization proxy"),
    "NU":    ("Nu Holdings", "company", "Brazil/Mexico/Colombia digital banking"),
    "MELI":  ("MercadoLibre", "company", "LatAm e-commerce/fintech"),
    "PBR":   ("Petrobras ADR", "company", "Brazilian oil major"),
    "EC":    ("Ecopetrol ADR", "company", "Colombian oil major"),
    "GOLD":  ("Barrick Mining", "company", "Gold/copper (Mali, Tanzania, DRC mines) -- direct African production exposure"),
    "TTE":   ("TotalEnergies ADR", "company", "Oil major with Mozambique LNG, Uganda pipeline exposure"),
    "NGLOY": ("Anglo American ADR", "company", "Diversified miner (Southern Africa platinum/diamonds/copper)"),
}


def verify_universe(history_fn=None) -> dict:
    """Returns the subset of INSTRUMENTS that actually traded in the last
    five sessions on Yahoo Finance. fast_info/lastPrice is NOT sufficient
    here -- it returns stale cached prices for liquidated funds (caught
    live 2026-07-07: the delisted iPath cocoa/coffee ETNs still reported a
    lastPrice). Requiring recent trade history means a closed fund can
    never appear in thesis output. `history_fn(symbol) -> DataFrame` is
    injectable for tests."""
    import warnings

    if history_fn is None:
        import yfinance as yf

        def history_fn(symbol):
            return yf.Ticker(symbol).history(period="5d")

    verified = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for symbol, meta in INSTRUMENTS.items():
            try:
                if not history_fn(symbol).empty:
                    verified[symbol] = meta
            except Exception:
                continue
    return verified
