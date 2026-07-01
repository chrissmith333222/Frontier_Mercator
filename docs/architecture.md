# Parallax — Architecture & Build Roadmap

**Org:** Frontier Mercator Group | **Agent/Tool:** Parallax | **Tagline:** Intelligence for the Frontier
**Site:** frontiermercator.com | **Codename:** MERIDIAN (internal repo name, pre-dates final branding)

## Mission

Personal geopolitical/investment intelligence platform for Africa and Latin America emerging
markets, combining Bloomberg-terminal-style data density with Palantir-Gotham-style entity/
relationship reasoning. Backs an investment strategy + geopolitical consulting practice.
Investment philosophy: maximize returns while aligning with US strategic interests; higher
risk tolerance for VC/PE, frontier startups, and development finance.

**Global monitoring scope (added 2026-07-01):** given the interconnected nature of markets
and security, ingestion also tracks Europe and the Middle East ("extended monitoring"), and
retains any other country as "Global / Other Monitoring" rather than discarding it. Every
normalized event carries an `in_core_mandate` boolean. Country/Sub-Regional/Regional briefs
and the main dashboard view stay filtered to `in_core_mandate=True` (Africa/LatAm) by default;
extended/global events are ingested and tagged now, with episodic one-off reports on
non-mandate countries/regions planned as a future surface (see Build Phases, step 8) once they
cross an interest threshold (e.g. a major conflict, election, or market shock).

## The Loop (4 layers, continuously running)

```
 ┌─────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐
 │  1. INGEST  │──▶│  2. CURATE   │──▶│  3. ANALYZE   │──▶│  4. PRESENT  │
 │  raw pulls  │   │  clean/dedup │   │  Parallax     │   │  briefs +    │
 │  from APIs  │   │  entity-     │   │  reasoning +  │   │  dashboard + │
 │             │   │  resolve     │   │  forecasting  │   │  chatbot     │
 └─────────────┘   └──────────────┘   └───────────────┘   └──────────────┘
        ▲                                                        │
        └────────────────── feedback / new source discovery ─────┘
```

Data pulls refresh **weekly**. Reports publish **daily (regional), weekly (sub-regional),
monthly (country)**. The chatbot queries live + cached data on demand, any time.

## Layer 1 — Ingestion

Pattern established by the ACLED module (`scripts/lib/*_auth.py`, `scripts/ingestion/*_fetch.py`,
`*_normalize.py`, one schema in `schemas/normalized_event.schema.json`). Each source is its
own self-contained module so it can be built, tested, and debugged independently.

| Source | Status | Auth | Notes |
|---|---|---|---|
| ACLED | ✅ built | OAuth | Conflict/protest events |
| GDELT | next | none (free) | 15-min global event feed, district-level geo |
| ReliefWeb (OCHA) | next | none (free) | Humanitarian/displacement |
| World Bank API | next | none (free) | GDP, inflation, debt, FDI |
| IMF Data API | next | none (free) | BoP, fiscal, FX |
| AfDB Open Data | next | none (free) | African infra/project pipelines |
| UNCTAD Stat | next | none (free) | FDI flows, commodity exposure |
| V-Dem | next | download (annual) | Regime/autocratization scoring |
| Fragile States Index | next | download (annual) | 12-indicator stability score |
| Transparency Intl CPI | next | download (annual) | Corruption risk |
| GTD (START) | next | download | Terrorism incidents |
| VIIRS nighttime lights | next | none (free, NOAA) | GDP proxy, conflict-zone recovery |
| NASA FIRMS | next | none (free) | Fire detection, agri/conflict stress |
| Sentinel Hub | later | free tier key | Satellite imagery, land use |
| MarineTraffic | later | paid API | Vessel tracking — evaluate cost vs. budget before committing |
| AllAfrica / MercoPress / El País | later | scrape or RSS | Regional news, no official free API |

**Dropped:** CrowdTangle (shut down by Meta, Aug 2024) and X/Twitter API (cheapest paid tier
~$200/mo, would consume the entire project budget). Social signal is deferred until budget
allows; GDELT + ACLED + news aggregators cover most politically material events in the interim.

## Layer 2 — Curation

- **Deduplication** across sources reporting the same event (e.g. ACLED and GDELT both
  catching a protest).
- **Entity resolution**: canonical IDs for countries, sub-national regions, armed groups,
  companies, commodities, and people — a shared lookup table so "Cabo Delgado," "Cabo
  Delgado Province," and "northern Mozambique" resolve to one entity.
- **Reliability scoring**: weight sources by known accuracy/latency (ACLED and official
  UN/IFI data > aggregated news > single-outlet reporting).
- Output: cleaned, entity-tagged records land in SQLite, ready for the knowledge layer.

## Layer 3 — Knowledge & Reasoning

**Storage (local-first, chosen for zero-cost/low-friction, migrates cleanly to cloud later):**
- **SQLite** — structured facts: entities, relationships, events, economic indicators.
  A `relationships` table (entity_a, relation_type, entity_b, evidence, confidence, date)
  serves as the lightweight knowledge graph — sufficient for the relationship density this
  project needs before a full graph database (e.g. Neo4j) would pay for itself.
- **Chroma** — vector store for semantic search over normalized documents, past reports,
  and analytical notes, so Parallax and the chatbot can retrieve relevant context by meaning,
  not just keyword.

**Parallax (the reasoning agent), via Claude API:**
- System prompt encodes the Parallax persona + analytical frameworks (PMESII-PT, DIME,
  three-horizon scenario planning, IC tradecraft language) and regional expertise
  (named sub-regions, armed groups, minerals, financial hubs — specificity over generic
  "African risk" framing).
- Tool-use access to SQLite (structured queries) and Chroma (semantic retrieval).
- Specialized modules: critical minerals, China/Russia engagement tracker, remittance
  economics, climate overlay.
- Produces four rigid-schema output formats:
  1. **Country Intelligence Brief** (monthly)
  2. **Sub-Regional Brief** (weekly)
  3. **Regional Executive Summary** (daily)
  4. **Event Flash** (ad hoc, triggered by significant events)
- Each brief must cover: investment opportunities (specific markets/commodities/companies),
  risk assessment (financial, political, expropriation, climate, demand/demographic), capital
  allocation recommendations, forecasted political/conflict developments — all quantified
  where possible, IC-tradecraft language for uncertainty ("we assess," "reporting indicates").

## Layer 4 — Presentation

**frontiermercator.com** — Next.js dashboard, deployed to Vercel (free tier), DNS pointed at
the domain Chris already owns. Runs locally during active development; goes live early per
Chris's preference rather than staying localhost-only.

- Report library (the four formats), browsable by region/country/date.
- Interactive maps (Mapbox or Leaflet, free tier) overlaying conflict events, economic
  indicators, and investment flags geographically.
- News/social highlight feed with source links.
- **Chatbot** — same Claude API + Parallax persona, wired to the live knowledge base, so
  Chris can query on-demand and generate ad hoc reports directly on the site (not a separate
  tool he has to leave the site for).

## Build Phases

1. ✅ Architecture + roadmap (this doc)
2. Ingestion pipeline expansion (GDELT → ReliefWeb → World Bank/IMF → the rest), each
   following the ACLED module pattern
3. Curation: cleaning, entity resolution, reliability scoring
4. Knowledge layer: SQLite schema + Chroma vector store
5. Parallax reasoning/forecasting agent + the four output formats
6. Frontier Mercator web app + chatbot (local first)
7. Deploy to Vercel, point frontiermercator.com
8. Interactive maps, automated report scheduling (daily/weekly/monthly), continuous
   learning loop (source discovery, signal validation agents)

## Budget notes ($200 total)

Nearly all data sources above are free. The two ongoing costs are Claude API usage
(report generation + chatbot — the main budget driver) and Vercel/hosting (free tier
should suffice at this scale). MarineTraffic and Sentinel Hub paid tiers, if pursued,
should be evaluated against remaining budget before committing — do not add paid sources
without checking in first.
