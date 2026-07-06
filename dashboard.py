"""
Frontier Mercator Group — Intelligence Dashboard
Real-time geopolitical and economic intelligence for Africa and Latin America.
"""

import streamlit as st
import json
import pandas as pd
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go
import streamlit.components.v1 as components
from pathlib import Path

from scripts.reports.pdf_report import generate_country_brief, generate_regional_brief, generate_custom_report
from scripts.reports.report_archive import archive_report, list_archived_reports
from scripts.knowledge.relationship_graph import build_country_graph, build_plotly_figure
from scripts import branding as b
from scripts.lib.worldbank_indicators import INDICATORS as WORLDBANK_INDICATOR_LABELS
from scripts.lib.imf_indicators import INDICATORS as IMF_INDICATOR_LABELS
from scripts.lib.world_countries import ALL_COUNTRIES, get_centroid
from scripts.lib.market_data import fetch_market_snapshot
from scripts.analysis.chat_agent import run_chat_turn, MAX_TURNS_PER_SESSION
from scripts.analytics.significance import (
    compute_significance_score, diversify_top_n, compute_tier_thresholds, significance_tier, top_n_badges,
)
from scripts.analytics.conflict_signal_promotion import detect_corroborated_conflict_signals

INDICATOR_LABELS = {code: label for code, (label, _cat) in {
    **WORLDBANK_INDICATOR_LABELS, **IMF_INDICATOR_LABELS,
}.items()}

DATA_DIR = Path(__file__).parent / "data" / "normalized"
ANALYSIS_DIR = Path(__file__).parent / "data" / "analysis"
CONFLICT_CATEGORIES = b.CONFLICT_CATEGORIES
ECON_CATEGORIES = b.ECON_CATEGORIES
NEWS_CATEGORIES = b.NEWS_CATEGORIES

NAME_TO_ISO3 = {name: iso3 for iso3, (name, _region, _mandate) in ALL_COUNTRIES.items()}


def load_cached_assessment(country_name: str) -> dict | None:
    """Reads a pre-generated AI assessment (scripts/analysis/reasoning_agent.py,
    run as a local/backend batch job -- never called live from this deployed
    app) for the given country name, if one exists. Returns None if no
    assessment has been generated for this country yet."""
    iso3 = NAME_TO_ISO3.get(country_name)
    if not iso3:
        return None
    path = ANALYSIS_DIR / f"{iso3}_assessment.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _risk_badge_html(label: str, value: float | None) -> str:
    """Renders one risk-scorecard sub-score as a color-coded badge (using
    the same severity palette as conflict-event severity elsewhere in the
    dashboard, since both are 0-10-higher-is-worse scales) rather than a
    plain st.metric -- a quick visual "is this red or green" read matters
    more here than for most metrics, given these feed risk assessments."""
    if value is None:
        return (
            f'<div class="fm-risk-badge" style="border-color:{b.BORDER};">'
            f'<div class="fm-risk-badge-label">{label}</div>'
            f'<div class="fm-risk-badge-value" style="color:{b.TEXT_MUTED};">N/A</div>'
            f"</div>"
        )
    color = b.severity_color(value)
    return (
        f'<div class="fm-risk-badge" style="border-color:{color};">'
        f'<div class="fm-risk-badge-label">{label}</div>'
        f'<div class="fm-risk-badge-value" style="color:{color};">{value:.1f}</div>'
        f"</div>"
    )


def load_scorecard(country_name: str) -> dict | None:
    """Reads a pre-generated risk scorecard (scripts/analytics/risk_scorecard.py,
    run as a local/backend batch job -- the underlying computation needs
    the SQLite knowledge base, which isn't committed/available in the
    deployed app) for the given country name, if one exists."""
    iso3 = NAME_TO_ISO3.get(country_name)
    if not iso3:
        return None
    path = ANALYSIS_DIR.parent / "scorecards" / f"{iso3}_scorecard.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_custom_analyses() -> list[dict]:
    """Reads every cached cross-cutting assessment (data/analysis/custom/,
    generated offline via reasoning_agent.py --query ... --save), newest
    first. Returns an empty list if none have been generated yet."""
    custom_dir = ANALYSIS_DIR / "custom"
    if not custom_dir.exists():
        return []
    analyses = []
    for path in custom_dir.glob("*.json"):
        try:
            analyses.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return sorted(analyses, key=lambda a: a.get("generated_at", ""), reverse=True)


@st.cache_data
def load_longform_articles() -> list[dict]:
    """Reads the Research & Analysis tab's reading material (scripts/
    ingestion/longform_fetch.py + longform_normalize.py -- The Economist,
    NYT, Foreign Affairs, Foreign Policy, WSJ's own free public RSS
    feeds), newest first. Returns an empty list if the ingestion script
    hasn't been run yet."""
    path = Path(__file__).parent / "data" / "longform" / "articles.json"
    if not path.exists():
        return []
    try:
        articles = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return sorted(articles, key=lambda a: a.get("published_date", ""), reverse=True)


def render_research_analysis_tab(articles: list[dict]):
    """Card-grid reading list of scholarly/policy/long-form journalism --
    Chris's ask for a WSJ/NYT-style "grabber" thumbnail per piece, kept
    deliberately separate from the event-driven News & Social Signal tab
    and the Unified Intelligence Map (these are commentary/analysis, not
    discrete dated events)."""
    st.markdown(
        "Long-form journalism, policy analysis, and commentary from major outlets — reading "
        "material to build context, not event data. Pulled from each outlet's own free, "
        "publicly-published RSS feed (headline and teaser only); the full piece opens on the "
        "publisher's own site, where your own subscription applies as normal."
    )
    if not articles:
        st.info(
            "No long-form articles ingested yet. Run "
            "`python scripts/ingestion/longform_fetch.py` and `longform_normalize.py` to populate this tab."
        )
        return

    sources = sorted({a["source"] for a in articles})
    selected_sources = st.multiselect("Source", options=sources, default=sources, key="longform_sources")
    scope = [a for a in articles if a["source"] in selected_sources]
    st.caption(f"{len(scope)} articles")

    cols = st.columns(3)
    for i, article in enumerate(scope[:60]):
        with cols[i % 3]:
            if article.get("image_url"):
                st.markdown(
                    f'<img src="{article["image_url"]}" style="width:100%;aspect-ratio:16/9;'
                    f'object-fit:cover;border-radius:4px;margin-bottom:0.4rem;">',
                    unsafe_allow_html=True,
                )
            st.markdown(f"**{article['title']}**")
            st.caption(f"{article['source']} · {article['published_date']}")
            if article.get("teaser"):
                st.markdown(article["teaser"])
            st.markdown(f"[Read full article →]({article['link']})")
            st.markdown("---")


def render_about_page():
    """Standalone page (routed via ?view=about, see the header nav and the
    bottom of this file) -- deliberately NOT rendered as one of the main
    st.tabs() entries, since the Unified Intelligence Map lives below the
    whole tabs widget as a page-level footer and would otherwise show up
    underneath this static page too. Chris: "I don't need to see the
    unified intelligence map on the 'about' or 'contact us' pages.\""""
    st.markdown('<div id="fm-about"></div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="fm-about-hero">
        <p>In the sixteenth century, a cartographer named Gerardus Mercator reimagined how the
        world could be viewed — flattening a sphere onto a plane so that distant shores, unfamiliar
        coastlines, and the paths between them could finally be read at a glance. His projection
        did not simplify the world, but it made visible what before was unseen.</p>
        <p>Frontier Mercator Group carries that legacy into an age where the map is no longer
        paper, and the terrain is no longer only geography. We believe that instinct and vision
        have never mattered more than they do now, in the frontier markets of the globe — where
        the world's next chapters of growth, risk, and opportunity are already being written, often
        long before they reach wider attention. Frontier Mercator stands at that frontier:
        synthesizing conflict, capital, and the quiet movements of power into a single strategic
        vantage point.</p>
        <p>Not to predict the future. To see the present clearly enough that the future stops
        being a surprise.</p>
        <p class="fm-about-signoff">FRONTIER MERCATOR — INTELLIGENCE FOR THE FRONTIER</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("---")

    st.markdown("### About This Platform")
    st.markdown("""
    Frontier Mercator Group's intelligence platform provides structured, real-time analysis of
    conflict, political risk, macroeconomic conditions, and emerging market trends across the
    world's frontier markets.

    #### Data Sources
    - **ACLED:** Armed Conflict Location & Event Data — geo-coded conflict and protest events
    - **GDELT:** global event database, 15-minute update cadence
    - **World Bank / IMF:** GDP growth, inflation, debt, current account, unemployment
    - ReliefWeb (UN OCHA humanitarian/displacement data) — pending appname approval

    #### Methodology
    Events are normalized to a common schema. Conflict events are scored 0-10 using event-type
    classification and fatality/conflict-intensity weighting; economic indicators are shown as
    reported, not severity-scored.

    #### Intelligence Standards
    - All analysis follows IC tradecraft conventions
    - Confidence levels: "we assess," "reporting indicates," "key intelligence gap"
    - Source attribution required for all claims
    - Designed for professional use in investment and national security contexts

    #### Satellite Imagery & OSINT Resources
    The Unified Intelligence Map (on the main dashboard) includes a **Recent Satellite** layer
    (NASA GIBS, ~1-day-old MODIS imagery, free/no-auth) alongside the high-resolution Esri
    base layer — use the layer control in the map's top-right corner to switch. For deeper,
    continuously-updated OSINT on specific conflict zones, these organizations already do
    this well and are worth going directly to rather than duplicating their work:
    - **[Institute for the Study of War](https://understandingwar.org)** — daily control-of-terrain
      maps for Ukraine and the Middle East
    - **[Liveuamap](https://liveuamap.com)** — crowd-sourced, geolocated live conflict event maps
      (Ukraine, Middle East, and other active theaters)
    - **[Critical Threats Project](https://criticalthreats.org)** (AEI) — Iran/Middle East-focused analysis
    - **[UNOSAT](https://unosat.org)** — UN satellite-based damage assessments for conflict/disaster zones
    - **[Sentinel Hub EO Browser](https://apps.sentinel-hub.com/eo-browser/)** — free Sentinel-1/2
      satellite imagery (Sentinel-1 radar sees through cloud cover, useful for persistently
      overcast conflict zones); planned as a proper ingested data source, not just a link
    - **[Bellingcat](https://www.bellingcat.com)** — open-source investigation methodology and findings
    """)


def render_contact_page():
    """Standalone page (routed via ?view=contact) -- see render_about_page's
    docstring for why this isn't one of the main st.tabs() entries."""
    st.markdown('<div id="fm-contact"></div>', unsafe_allow_html=True)
    # Everything inside ONE st.markdown call so the wrapping <div> actually
    # contains the content in the DOM -- Streamlit renders each st.markdown
    # call as its own isolated container, so a <div> opened in one call
    # can't wrap content from a separate later call.
    st.markdown(
        """
        <div class="fm-watermark-bg">
        <h3>Contact Us</h3>
        <p>Frontier Mercator Group works directly with investors, analysts, and institutions
        operating across the world's frontier markets. For inquiries about custom research,
        platform access, or partnership opportunities, reach out below.</p>
        <p><b>Contact:</b>
        <a href="mailto:research@frontiermercator.com">research@frontiermercator.com</a></p>
        <p>Distribution of Frontier Mercator Group intelligence products is restricted to
        authorized recipients. Reach out to discuss access.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _emblem_base64() -> str:
    import base64
    return base64.b64encode((Path(__file__).parent / "static" / "fm_emblem.svg").read_bytes()).decode("ascii")


# Computed before the CSS block below (which needs it) rather than via the
# @st.cache_data-decorated _load_base64 defined further down -- this runs
# at module top-to-bottom execution time, before that function exists.
_EMBLEM_B64 = _emblem_base64()

# Page config
st.set_page_config(
    page_title="Frontier Mercator — Intelligence for the Frontier",
    page_icon=str(Path(__file__).parent / "static" / "fm_emblem.svg"),
    layout="wide",
    # Expanded, not collapsed: the Research Assistant chat lives in the
    # sidebar now (Chris's persistent-window ask) -- with the sidebar
    # collapsed by default he literally couldn't find the chat at all,
    # since it was hidden behind the tiny ">>" toggle.
    initial_sidebar_state="expanded"
)

# Custom CSS for branding — dark theme, shared palette from scripts/branding.py.
# Everything on the site uses FONT_STACK (Bahnschrift) except the big wordmark,
# which uses DISPLAY_FONT_STACK (Rajdhani) -- sharp, angular letterforms, no
# rounded terminals, per Chris's direction (Lockheed Martin as the reference).
st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@400;500;600&family=Rajdhani:wght@600;700&display=swap');

    * {{
        font-family: {b.FONT_STACK};
    }}

    /* Horizontal layout (emblem beside the wordmark, not stacked above it)
       -- keeps total header height small so the header + full rotating
       video are both visible on load without scrolling, even with a
       larger wordmark. */
    .fm-header-block {{
        display: flex;
        flex-direction: row;
        align-items: center;
        justify-content: center;
        gap: 1rem;
        width: 100%;
        margin: 0.5rem 0 0 0;
    }}

    .fm-emblem-large {{
        width: 76px;
        height: 76px;
        flex-shrink: 0;
    }}

    .fm-wordmark {{
        font-family: {b.DISPLAY_FONT_STACK};
        font-weight: 700;
        font-size: 3.6rem;
        letter-spacing: 4px;
        text-align: left;
        color: {b.TEXT_PRIMARY};
        white-space: nowrap;
        margin: 0;
    }}
    @media (max-width: 600px) {{
        .fm-wordmark {{ font-size: 2.1rem; letter-spacing: 2px; }}
        .fm-emblem-large {{ width: 52px; height: 52px; }}
    }}

    .stMetric {{
        background-color: {b.PANEL};
        border: 1px solid {b.BORDER};
        border-left: 4px solid {b.GOLD};
        padding: 1.5rem;
        border-radius: 4px;
    }}

    .stTabs [data-baseweb="tab-list"] button {{
        color: {b.TEXT_MUTED};
        border-bottom: 2px solid transparent;
    }}

    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {{
        color: {b.TEXT_PRIMARY};
        border-bottom: 3px solid {b.GOLD};
    }}

    h1, h2, h3 {{
        color: {b.TEXT_PRIMARY};
        font-weight: 600;
        letter-spacing: -0.5px;
    }}

    .header-line {{
        height: 3px;
        background: linear-gradient(90deg, {b.GOLD} 0%, {b.NAVY} 100%);
        margin-bottom: 1rem;
    }}

    .fm-panel {{
        background-color: {b.PANEL};
        border: 1px solid {b.BORDER};
        padding: 1.25rem 1.5rem;
        border-radius: 4px;
        margin-bottom: 1rem;
    }}

    .fm-footer {{
        text-align: center;
        color: {b.TEXT_MUTED};
        font-size: 0.85rem;
        padding: 2rem 0;
    }}

    /* Streamlit dims the whole app to ~stale opacity while a rerun is in
       flight (e.g. moving a filter slider) -- Chris doesn't want the map/
       charts ever looking duller than full color, so force full opacity on
       the content and embedded iframes regardless of rerun state. */
    [data-testid="stMain"], [data-testid="stIFrame"], .element-container {{
        opacity: 1 !important;
    }}

    /* Hide Streamlit/GitHub chrome (main menu, footer "Made with Streamlit",
       toolbar, deploy button, viewer badge) -- Chris wants none of the
       platform's own branding showing on the site. Deliberately NOT hiding
       the whole header bar -- the sidebar expand/collapse control lives
       there and hiding it would break sidebar access. */
    #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
    [data-testid="stStatusWidget"], .stAppDeployButton,
    .viewerBadge_container__r5tak, .viewerBadge_link__qRIco {{
        visibility: hidden !important;
        display: none !important;
    }}

    /* Persistent top navigation bar -- stays fixed while scrolling, with a
       Home link that jumps back to the #fm-top anchor at the very start of
       the page (plain browser anchor scroll, no JS -- st.markdown strips
       <script> tags, see render_video_hero for why that approach uses
       components.html instead when JS is actually needed). Push the main
       content down by the bar's height so it doesn't sit underneath it. */
    .fm-topbar {{
        position: fixed;
        top: 0; left: 0; right: 0;
        z-index: 999999;
        height: 46px;
        background: rgba(6, 11, 20, 0.94);
        backdrop-filter: blur(6px);
        border-bottom: 1px solid {b.BORDER};
        display: flex;
        align-items: center;
        gap: 1.75rem;
        padding: 0 1.75rem;
    }}
    .fm-topbar-brand {{
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-right: auto;
    }}
    .fm-topbar-emblem {{ width: 20px; height: 20px; }}
    .fm-topbar-brand-text {{
        font-family: {b.DISPLAY_FONT_STACK};
        font-weight: 700;
        font-size: 0.8rem;
        letter-spacing: 1.5px;
        color: {b.TEXT_PRIMARY};
    }}
    .fm-topbar a {{
        color: {b.TEXT_MUTED};
        text-decoration: none;
        font-family: {b.FONT_STACK};
        font-weight: 500;
        font-size: 0.8rem;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        transition: color 0.15s ease;
    }}
    .fm-topbar a:hover {{ color: {b.GOLD}; }}
    [data-testid="stAppViewContainer"] > .main {{
        padding-top: 46px;
    }}
    /* Streamlit's block-container reserves generous top padding by default
       (space for its own hidden toolbar) -- since that toolbar is already
       hidden, shrink it so the header + full rotating video are visible on
       load without scrolling. */
    .block-container {{
        padding-top: 1.5rem !important;
    }}

    /* About page: epic/mysterious narrative hero, cascading fade-in on
       load -- each line waits its turn rather than the whole block
       appearing at once. */
    @keyframes fmFadeIn {{
        from {{ opacity: 0; transform: translateY(8px); }}
        to {{ opacity: 1; transform: translateY(0); }}
    }}
    .fm-about-hero, .fm-watermark-bg {{
        position: relative;
        max-width: 680px;
        margin: 1.5rem auto 2.5rem auto;
        text-align: center;
    }}
    /* Large, near-invisible emblem watermark behind the narrative text --
       Chris wanted more imagery presence on the site but explicitly "not
       distracting," so this stays background-only and barely-there rather
       than a photo/video (no ffmpeg available locally to extract a clean
       still frame from the hero videos without visible compression
       artifacts at this size, so the emblem -- already a vector, scales
       perfectly at any size -- was the safer choice here). Reused on the
       Contact tab too (.fm-watermark-bg) for visual consistency between
       the two lowest-traffic, most "editorial" pages on the site. */
    .fm-about-hero::before, .fm-watermark-bg::before {{
        content: "";
        position: absolute;
        top: 50%; left: 50%;
        width: 900px; height: 900px;
        transform: translate(-50%, -50%);
        background-image: url("data:image/svg+xml;base64,{_EMBLEM_B64}");
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        opacity: 0.04;
        z-index: -1;
        pointer-events: none;
    }}
    .fm-about-hero p {{
        opacity: 0;
        animation: fmFadeIn 1.6s ease-out forwards;
        font-size: 1.05rem;
        line-height: 1.75;
        color: {b.TEXT_PRIMARY};
        margin-bottom: 1.1rem;
    }}
    .fm-about-hero p:nth-of-type(1) {{ animation-delay: 0.2s; }}
    .fm-about-hero p:nth-of-type(2) {{ animation-delay: 1.4s; }}
    .fm-about-hero p:nth-of-type(3) {{ animation-delay: 2.6s; }}
    .fm-about-hero .fm-about-signoff {{
        font-family: {b.DISPLAY_FONT_STACK};
        font-weight: 700;
        letter-spacing: 2px;
        color: {b.GOLD};
        animation-delay: 3.8s;
    }}

    /* Risk scorecard badges -- color-coded (same severity palette as
       conflict events) so a "how bad is this, at a glance" read doesn't
       require reading the number. */
    .fm-risk-badges {{
        display: flex;
        gap: 0.75rem;
        margin: 0.75rem 0 1.25rem 0;
        flex-wrap: wrap;
    }}
    .fm-risk-badge {{
        background-color: {b.PANEL};
        border: 1px solid;
        border-radius: 4px;
        padding: 0.6rem 1rem;
        min-width: 90px;
        text-align: center;
    }}
    .fm-risk-badge-label {{
        font-size: 0.75rem;
        color: {b.TEXT_MUTED};
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 0.2rem;
    }}
    .fm-risk-badge-value {{
        font-family: {b.DISPLAY_FONT_STACK};
        font-weight: 700;
        font-size: 1.6rem;
    }}

    /* Tiered significance badges -- News & Social Signal tab and the
       Unified Intelligence Map both flag high-significance events (see
       scripts/analytics/significance.py) with one of three pills so they
       visually stand out from routine/lower-priority items, per Chris's
       ask to make important things "pop out of the white noise." Three
       tiers (not just one binary "hot" flag) so a ranked top-N list
       doesn't read as uniformly "everything is urgent" -- tiers are
       computed relative to the current scope's own score distribution. */
    .fm-badge {{
        display: inline-block;
        border-radius: 3px;
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        padding: 0.1rem 0.5rem;
        margin-left: 0.5rem;
        vertical-align: middle;
    }}
    .fm-badge-urgent {{ background-color: {b.CRITICAL}22; color: {b.CRITICAL}; border: 1px solid {b.CRITICAL}; }}
    .fm-badge-top {{ background-color: {b.HIGH}22; color: {b.HIGH}; border: 1px solid {b.HIGH}; }}
    .fm-badge-medium {{ background-color: {b.MEDIUM}22; color: {b.MEDIUM}; border: 1px solid {b.MEDIUM}; }}
    .fm-news-card-urgent {{ border-left: 3px solid {b.CRITICAL}; padding-left: 0.75rem; }}
    .fm-news-card-top {{ border-left: 3px solid {b.HIGH}; padding-left: 0.75rem; }}
    .fm-news-card-medium {{ border-left: 3px solid {b.MEDIUM}; padding-left: 0.75rem; }}
    .fm-news-card-routine {{ border-left: 3px solid {b.BORDER}; padding-left: 0.75rem; }}

    /* Live stock ticker banner -- a continuously scrolling marquee strip,
       trading-floor style. The track is duplicated once in the markup so
       the scroll loop is seamless (animating exactly one strip-width). */
    .fm-ticker-banner {{
        background-color: {b.PANEL};
        border-top: 1px solid {b.BORDER};
        border-bottom: 1px solid {b.BORDER};
        overflow: hidden;
        white-space: nowrap;
        padding: 0.6rem 0;
        margin-bottom: 0.75rem;
    }}
    .fm-ticker-track {{
        display: inline-block;
        animation: fmTickerScroll 60s linear infinite;
    }}
    .fm-ticker-item {{
        display: inline-block;
        font-family: {b.FONT_STACK};
        font-size: 0.9rem;
        color: {b.TEXT_PRIMARY};
        margin-right: 2.5rem;
    }}
    @keyframes fmTickerScroll {{
        from {{ transform: translateX(0); }}
        to {{ transform: translateX(-50%); }}
    }}
    .fm-quote-row {{
        display: flex;
        justify-content: space-between;
        font-size: 0.85rem;
        padding: 0.3rem 0;
        border-bottom: 1px solid {b.BORDER};
    }}
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_events():
    """Loads the curated merged dataset (entity-resolved, cross-source
    deduplicated -- see scripts/curation/build_merged_dataset.py) if it's
    been built; falls back to combining the raw per-source
    *_latest_normalized.json files directly so the dashboard still works
    before that build step has ever been run."""
    merged_path = DATA_DIR / "merged_dataset.json"
    if merged_path.exists():
        with open(merged_path, "r", encoding="utf-8") as f:
            return json.load(f)

    events = []
    for path in sorted(DATA_DIR.glob("*_latest_normalized.json")):
        with open(path, "r", encoding="utf-8") as f:
            events.extend(json.load(f))
    return events


@st.cache_data
def prepare_dataframe(events):
    """Convert events to a pandas dataframe for analysis. Keeps every event,
    core mandate (Africa/LatAm) and extended monitoring (Europe, Middle East,
    Global/Other) alike — the map and analytics should show all of it. Default
    filtering to prioritize the core mandate happens via the sidebar region
    selector below, not by dropping data here."""
    df = pd.DataFrame(events)
    df['event_date'] = pd.to_datetime(df['event_date'], errors='coerce')
    df['severity_label'] = df['severity_score'].apply(
        lambda s: b.severity_label(s) if pd.notna(s) else "N/A"
    )
    return df


@st.cache_data
def _load_base64(path: str) -> str:
    import base64
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


@st.cache_data
def _load_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


@st.cache_data(ttl=300)
def _load_market_snapshot() -> dict:
    """Live Yahoo Finance quotes, cached for 5 minutes -- Streamlit reruns
    this whole script on any widget interaction anywhere on the page, so
    without a TTL cache this would refetch on every click, not just every
    page load. 5 minutes balances "reasonably fresh" against not hammering
    Yahoo Finance's free endpoint on a busy session."""
    return fetch_market_snapshot()


@st.cache_data
def _load_discovered_insights() -> dict:
    """Reads the cached correlation-discovery insights (see
    scripts/analytics/correlation_discovery.py -- generated offline, read
    statically here, same pattern as every other AI artifact). Returns {}
    if the discovery pipeline hasn't been run yet."""
    path = Path(__file__).parent / "data" / "insights" / "discovered_insights.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


@st.cache_data
def _cached_country_graph(country: str) -> dict:
    """build_country_graph scans the full ~68k-event dataset AND runs
    networkx's spring_layout physics simulation -- uncached, it re-ran on
    EVERY rerun of this script (i.e. every widget interaction anywhere on
    the page), a real contributor to Chris's "everything takes 5 seconds"
    latency complaint. Cached per country; the underlying events list only
    changes on redeploy, so no TTL needed. Calls load_events() (itself
    cached) rather than closing over the module-level `events` global so
    the dependency is explicit regardless of definition order."""
    return build_country_graph(load_events(), country)


def _quote_color(change: float) -> str:
    if change > 0:
        return b.LOW  # green
    if change < 0:
        return b.CRITICAL  # red
    return b.TEXT_MUTED


def _quote_arrow(change: float) -> str:
    if change > 0:
        return "▲"
    if change < 0:
        return "▼"
    return "—"


def render_market_ticker():
    """Live-updating stock market tracker -- major US indices, foreign
    markets, and market movers, color-coded green/red by daily change.
    See scripts/lib/market_data.py for why this calls a live API directly
    from the deployed app (a deliberate exception to this project's usual
    "keep API calls off the deployed site" pattern)."""
    snapshot = _load_market_snapshot()
    all_quotes = snapshot["us_indices"] + snapshot["foreign_indices"] + snapshot["movers"]
    if not all_quotes:
        st.info("Market data temporarily unavailable.")
        return

    # Freshness stamp + manual refresh. Quotes refresh automatically no
    # more than every 5 minutes (cache TTL), and only when the page
    # actually reruns (any interaction) -- Streamlit can't push updates to
    # an idle page, so an untouched tab CAN show stale quotes. The stamp
    # makes that visible instead of misleading; the button forces a fresh
    # pull immediately.
    stamp_col, refresh_col = st.columns([0.8, 0.2])
    with stamp_col:
        st.caption(f"Quotes current as of: {snapshot.get('fetched_at', 'unknown')} "
                   f"(auto-refreshes every 5 min on page activity)")
    with refresh_col:
        if st.button("Refresh quotes", key="refresh_market"):
            _load_market_snapshot.clear()
            st.rerun()

    ticker_items = "".join(
        f'<span class="fm-ticker-item">{q["label"]} '
        f'<b>{q["price"]:,.2f}</b> '
        f'<span style="color:{_quote_color(q["change"])};">{_quote_arrow(q["change"])} '
        f'{q["change"]:+,.2f} ({q["change_pct"]:+.2f}%)</span></span>'
        for q in all_quotes
    )
    # Duplicate the strip once so the marquee loops seamlessly (the CSS
    # animation scrolls exactly one strip-width, so the second copy is
    # already in position to continue the illusion of an endless scroll).
    st.markdown(
        f'<div class="fm-ticker-banner"><div class="fm-ticker-track">'
        f'{ticker_items}{ticker_items}'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    st.caption(f"Live market data (Yahoo Finance, ~15-min delayed), refreshed every 5 minutes.")

    col1, col2, col3 = st.columns(3)
    for col, title, quotes in (
        (col1, "US Indices", snapshot["us_indices"]),
        (col2, "Foreign Markets", snapshot["foreign_indices"]),
        (col3, "Market Movers", snapshot["movers"]),
    ):
        with col:
            st.markdown(f"**{title}**")
            for q in quotes:
                color = _quote_color(q["change"])
                st.markdown(
                    f'<div class="fm-quote-row">'
                    f'<span>{q["label"]}</span>'
                    f'<span><b>{q["price"]:,.2f}</b> '
                    f'<span style="color:{color};">{_quote_arrow(q["change"])} {q["change_pct"]:+.2f}%</span></span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


def render_header():
    """Large centered emblem (the new brand mark) above the wordmark --
    replaces the old photographic logo entirely per Chris's direction. Built
    as one flex-centered HTML block since Streamlit columns/st.image don't
    guarantee true centering."""
    emblem_svg = _load_text(str(Path(__file__).parent / "static" / "fm_emblem.svg"))

    st.markdown(
        f"""
        <div class="fm-header-block">
            <span class="fm-emblem-large">{emblem_svg}</span>
            <div class="fm-wordmark">FRONTIER MERCATOR</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="header-line"></div>', unsafe_allow_html=True)


def render_video_hero():
    """Full-width, continuously-rotating video background sitting directly
    beneath the header, with the tagline overlaid -- Chris's "Lockheed
    Martin homepage" reference. Videos are pre-compressed (4K/100+Mbps
    originals down to 720p/~1-2Mbps, see static/videos/) and served via
    Streamlit's static file serving (enableStaticServing in config.toml).
    Uses components.html (an iframe) rather than st.markdown because
    st.markdown strips <script> tags, and the rotation needs JS."""
    video_dir = Path(__file__).parent / "static" / "videos"
    video_files = sorted(p.name for p in video_dir.glob("*.mp4"))
    if not video_files:
        return

    video_tags = "\n".join(
        f'<video class="fm-hero-video" muted playsinline '
        f'style="opacity:{1 if i == 0 else 0};" '
        f'src="app/static/videos/{name}"></video>'
        for i, name in enumerate(video_files)
    )

    html = f"""
    <style>
        html, body {{ margin:0; padding:0; background:{b.BG}; }}
        .fm-hero-video {{
            position:absolute; top:0; left:0; width:100%; height:100%;
            object-fit:cover; transition:opacity 1.2s ease-in-out;
        }}
    </style>
    <div style="position:relative; width:100%; height:440px; overflow:hidden; background:{b.BG};">
        {video_tags}
        <div style="position:absolute; inset:0;
                    background:linear-gradient(180deg, rgba(6,11,20,0.25) 0%, rgba(6,11,20,0.55) 100%);"></div>
        <div style="position:absolute; inset:0; display:flex; align-items:center; justify-content:center;">
            <span style="font-family:'Bahnschrift','Barlow Semi Condensed',sans-serif;
                         font-style:italic; font-size:2.3rem; color:#FFFFFF;
                         text-shadow:0 2px 14px rgba(0,0,0,0.75); letter-spacing:1px;">
                Intelligence for the Frontier
            </span>
        </div>
    </div>
    <script>
        const videos = Array.from(document.querySelectorAll('.fm-hero-video'));
        let current = 0;
        function playNext() {{
            videos[current].style.opacity = 0;
            current = (current + 1) % videos.length;
            const next = videos[current];
            next.currentTime = 0;
            next.style.opacity = 1;
            next.play();
        }}
        videos.forEach((v) => v.addEventListener('ended', playNext));
        videos[0].play();
    </script>
    """
    components.html(html, height=440)


def render_footer(df):
    st.markdown("---")
    st.markdown(
        "<div class='fm-footer'>"
        "<p><b>Frontier Mercator Group</b> | Intelligence for the Frontier</p>"
        f"<p>Data updated: {df['ingested_at'].max() if 'ingested_at' in df.columns else 'Unknown'}</p>"
        "</div>",
        unsafe_allow_html=True,
    )


def render_conflict_dashboard(df_filtered, news_df=None):
    st.markdown(
        "Security-relevant events — conflict, protest, political violence — from ACLED and GDELT. "
        "ACLED and GDELT are refreshed manually (not on a schedule) whenever the ingestion scripts are "
        "re-run -- see the Corroborated Signal tab for conflict-shaped news/social activity that may "
        "be more current between refreshes."
    )

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric(
            "Total Events", f"{len(df_filtered):,}",
            f"Latest: {df_filtered['event_date'].max().strftime('%Y-%m-%d') if len(df_filtered) > 0 else 'N/A'}"
        )
    with col2:
        st.metric("Critical Events", len(df_filtered[df_filtered['severity_score'] >= 7]))
    with col3:
        st.metric("High Severity", len(df_filtered[
            (df_filtered['severity_score'] >= 5) & (df_filtered['severity_score'] < 7)
        ]))
    with col4:
        st.metric("Countries", df_filtered['country'].nunique())
    with col5:
        st.metric("Total Fatalities", f"{int(df_filtered['fatalities'].fillna(0).sum()):,}")

    analytics_tab, critical_tab, corroborated_tab = st.tabs(
        ["Analytics", "Critical Events", "Corroborated Signal"]
    )
    # No separate map here by design -- the map lives once, at the bottom of
    # the page (Unified Intelligence Map), covering conflict/economic/news
    # together with a type toggle. Keeping a second map in this tab would
    # just be a redundant, conflict-only duplicate of it.

    with analytics_tab:
        col1, col2 = st.columns(2)
        with col1:
            severity_counts = df_filtered['severity_label'].value_counts().reindex(
                ['Critical', 'High', 'Medium', 'Low']
            )
            fig = go.Figure(data=[go.Bar(
                x=severity_counts.index, y=severity_counts.values,
                marker=dict(color=[b.CRITICAL, b.HIGH, b.MEDIUM, b.LOW]),
                text=severity_counts.values, textposition='auto',
                hovertemplate='<b>%{x}</b><br>Count: %{y}<extra></extra>',
            )])
            fig.update_layout(
                title="Events by Severity Level", xaxis_title="Severity", yaxis_title="Count",
                template="plotly_dark", paper_bgcolor=b.PANEL, plot_bgcolor=b.PANEL,
                height=400, margin=dict(l=40, r=40, t=60, b=40),
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            region_counts = df_filtered['region'].value_counts().head(10)
            fig = go.Figure(data=[go.Bar(
                y=region_counts.index, x=region_counts.values, orientation='h',
                marker=dict(color=b.SLATE),
                text=region_counts.values, textposition='auto',
                hovertemplate='<b>%{y}</b><br>Count: %{x}<extra></extra>',
            )])
            fig.update_layout(
                title="Top 10 Regions by Event Count", xaxis_title="Count", yaxis_title="Region",
                template="plotly_dark", paper_bgcolor=b.PANEL, plot_bgcolor=b.PANEL,
                height=400, margin=dict(l=150, r=40, t=60, b=40),
            )
            st.plotly_chart(fig, use_container_width=True)

        events_by_date = df_filtered.groupby(df_filtered['event_date'].dt.to_period('M')).size()
        events_by_date.index = events_by_date.index.to_timestamp()
        fig = go.Figure(data=[go.Scatter(
            x=events_by_date.index, y=events_by_date.values, mode='lines+markers',
            line=dict(color=b.SLATE, width=2), marker=dict(size=8),
            fill='tozeroy', fillcolor='rgba(80, 95, 121, 0.25)',
            hovertemplate='<b>%{x|%B %Y}</b><br>Events: %{y}<extra></extra>',
        )])
        fig.update_layout(
            title="Events Over Time", xaxis_title="Date", yaxis_title="Count",
            template="plotly_dark", paper_bgcolor=b.PANEL, plot_bgcolor=b.PANEL,
            height=400, margin=dict(l=40, r=40, t=60, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

    with critical_tab:
        st.markdown("#### Critical Events (Severity ≥ 7)")
        critical_events = df_filtered[df_filtered['severity_score'] >= 7].sort_values(
            'severity_score', ascending=False
        ).head(20)

        if len(critical_events) > 0:
            for _, event in critical_events.iterrows():
                with st.container():
                    col1, col2 = st.columns([0.15, 0.85])
                    with col1:
                        st.markdown(
                            f"<div style='background-color: {b.severity_color(event['severity_score'])}; "
                            f"padding: 1rem; border-radius: 4px; text-align: center;'>"
                            f"<span style='color: #060B14; font-weight: 700; font-size: 1.2rem;'>"
                            f"{event['severity_score']:.1f}</span></div>",
                            unsafe_allow_html=True,
                        )
                    with col2:
                        st.markdown(f"**{event['country']}** — {event['event_date']}")
                        st.markdown(f"*{str(event['event_category']).replace('_', ' ').title()}*")
                        st.markdown(f"**Summary:** {event['narrative_summary']}")
                        if event['fatalities'] and event['fatalities'] > 0:
                            st.markdown(f"**Fatalities:** {int(event['fatalities'])}")
                        st.markdown("---")
        else:
            st.info("No critical events with severity ≥ 7 in the current filter.")

    with corroborated_tab:
        st.markdown(
            "Conflict-shaped news/social activity (attacks, clashes, militant activity, etc.) "
            "reported by **at least 2 distinct sources** within a 1-day window -- one outlet's "
            "language alone isn't corroboration, but independent agreement across sources is a real "
            "signal worth surfacing between ACLED's manual refreshes. **Preliminary and unverified** -- "
            "not ACLED-vetted, structured conflict data; treat as a lead to investigate, not a "
            "confirmed event."
        )
        if news_df is None or len(news_df) == 0:
            st.info("No news/social signal data loaded to check for corroborated activity.")
        else:
            corroborated = detect_corroborated_conflict_signals(news_df, min_sources=2, date_window_days=1)
            if len(corroborated) == 0:
                st.info("No corroborated (2+ source) conflict-shaped signal in the currently loaded news data.")
            else:
                st.caption(f"{len(corroborated)} corroborated signal event(s) across "
                           f"{corroborated['country'].nunique()} countries.")
                for _, event in corroborated.iterrows():
                    display_text = event.get("narrative_summary_en")
                    if pd.isna(display_text) or not display_text:
                        display_text = event["narrative_summary"]
                    st.markdown(
                        f"**{event['country']}** — {event['event_date']} &nbsp;·&nbsp; *{event['source']}*  \n"
                        f"{display_text}"
                        + (f"  \n[Read full source →]({event['source_url']})"
                           if pd.notna(event.get('source_url')) else "")
                    )
                    st.markdown("---")


def render_markets_dashboard(econ_df):
    render_market_ticker()
    st.markdown(
        "Macroeconomic indicators (World Bank/IMF) and investment project tracking — "
        "who's actually putting capital into these markets, not just how the macro numbers look."
    )
    if len(econ_df) == 0:
        st.info("No economic/investment data loaded yet.")
        return

    indicators_tab, investment_tab, insights_tab = st.tabs(
        ["Macro Indicators", "Investment Projects", "Discovered Insights"]
    )

    with insights_tab:
        st.markdown(
            "Cross-cutting correlations discovered by an automated statistical screen over "
            "country-month event data and monthly commodity prices, then curated by AI for "
            "economic plausibility and investment relevance — only findings that could actually "
            "shape strategy or flag risk are surfaced, not every test that was run. "
            "**Correlation is not causation** — each finding carries its own specific caveat."
        )
        insights_data = _load_discovered_insights()
        if not insights_data or not insights_data.get("insights"):
            st.info(
                "No discovered insights yet — run "
                "`python scripts/analytics/correlation_discovery.py` to generate them."
            )
        else:
            st.caption(
                f"Generated {insights_data['generated_at'][:10]} — "
                f"{len(insights_data['insights'])} insight(s) kept from "
                f"{insights_data['total_hits_screened']} statistically significant hits "
                f"(hundreds of tests screened)."
            )
            for insight in insights_data["insights"]:
                st.markdown(
                    f'<div class="fm-news-card-top" style="margin-bottom:1rem;">'
                    f"<div><strong>{insight['headline']}</strong></div>"
                    f"<div>{insight['detail']}</div>"
                    f"<div style='color:{b.TEXT_MUTED};font-size:0.85rem;margin-top:0.3rem;'>"
                    f"Caveat: {insight['caveat']}</div>"
                    f"<div style='color:{b.TEXT_MUTED};font-size:0.8rem;margin-top:0.3rem;'>"
                    f"{insight['country']} — {insight['series_x'].replace('_', ' ')} vs "
                    f"{insight['series_y'].replace('_', ' ')} · r={insight['r']} · "
                    f"lag {int(insight['lag_months'])}mo · n={int(insight['n_months'])} months</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    with indicators_tab:
        indicator_df = econ_df[econ_df['event_category'] == b.ECON_CATEGORY]
        if len(indicator_df) == 0:
            st.info("No macro indicator data loaded yet.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                country_choice = st.selectbox(
                    "Country", options=sorted(indicator_df['country'].dropna().unique()), key="econ_country"
                )
            with col2:
                indicators = sorted(indicator_df['event_subtype'].dropna().unique())
                indicator_choice = st.selectbox(
                    "Indicator", options=indicators, key="econ_indicator",
                    format_func=lambda code: INDICATOR_LABELS.get(code, code),
                )

            subset = indicator_df[
                (indicator_df['country'] == country_choice) & (indicator_df['event_subtype'] == indicator_choice)
            ].sort_values('event_date')

            if len(subset) > 0:
                st.markdown(f"#### {INDICATOR_LABELS.get(indicator_choice, indicator_choice)} — {country_choice}")
                # narrative_summary carries the formatted value (e.g. "GDP
                # growth (annual %): 3.2% (2025)") since severity_score is
                # null for economic_indicator events -- parse the number
                # back out for charting.
                parsed = subset['narrative_summary'].str.extract(r':\s*(-?[\d.]+)').astype(float)[0]
                fig = go.Figure(data=[go.Scatter(
                    x=subset['event_date'], y=parsed, mode='lines+markers',
                    line=dict(color=b.SLATE, width=2), marker=dict(size=8),
                    hovertemplate='<b>%{x|%Y}</b><br>%{y}<extra></extra>',
                )])
                fig.update_layout(
                    template="plotly_dark", paper_bgcolor=b.PANEL, plot_bgcolor=b.PANEL,
                    height=350, margin=dict(l=40, r=40, t=20, b=40),
                )
                st.plotly_chart(fig, use_container_width=True)

                table = subset[['event_date', 'source', 'narrative_summary']].rename(
                    columns={'event_date': 'Date', 'source': 'Source', 'narrative_summary': 'Value'}
                )
                st.dataframe(table, use_container_width=True, hide_index=True)
            else:
                st.info("No data for this country/indicator combination.")

            st.markdown("#### Latest Snapshot Across Tracked Countries")
            latest = (
                indicator_df[indicator_df['event_subtype'] == indicator_choice]
                .sort_values('event_date')
                .drop_duplicates('country', keep='last')
                [['country', 'region', 'event_date', 'narrative_summary']]
                .rename(columns={
                    'country': 'Country', 'region': 'Region',
                    'event_date': 'Latest Data', 'narrative_summary': 'Value',
                })
                .sort_values('Country')
            )
            st.dataframe(latest, use_container_width=True, hide_index=True)

    with investment_tab:
        investment_df = econ_df[econ_df['event_category'] == 'investment']
        st.markdown(
            "Who's financing development here, across government and private capital — "
            "[AidData Global Chinese Development Finance Dataset](https://www.aiddata.org/data/aiddatas-global-chinese-development-finance-dataset-version-3-0) "
            "(20,985 China-financed loans/grants, 2000-2021), "
            "[DFC Annual Project Data](https://www.dfc.gov/our-impact/transaction-data) "
            "(U.S. International Development Finance Corporation loans, guarantees, equity, and insurance, "
            "legacy OPIC deals included), and the "
            "[World Bank Private Participation in Infrastructure Database](https://ppi.worldbank.org/en/ppidata) "
            "(private-sector energy/transport/water/ICT investment commitments, 1990-2024). "
            "Directly answers \"who's investing here.\""
        )
        if len(investment_df) == 0:
            st.info("No investment project data loaded yet.")
        else:
            source_options = ["All Financiers"] + sorted(investment_df['source'].dropna().unique())
            source_choice = st.selectbox("Financier", options=source_options, key="investment_source")
            if source_choice != "All Financiers":
                investment_df = investment_df[investment_df['source'] == source_choice]

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Projects", f"{len(investment_df):,}")
            with col2:
                st.metric("Countries", investment_df['country'].nunique())
            with col3:
                st.metric("Sectors", investment_df['event_subtype'].nunique())

            country_options = sorted(investment_df['country'].dropna().unique())
            country_choice = st.selectbox("Country", options=country_options, key="investment_country")

            country_projects = investment_df[investment_df['country'] == country_choice].sort_values(
                'event_date', ascending=False
            )
            st.markdown(f"#### {len(country_projects):,} Financed Projects — {country_choice}")

            sector_counts = country_projects['event_subtype'].value_counts().head(10)
            if len(sector_counts) > 0:
                fig = go.Figure(data=[go.Bar(
                    y=sector_counts.index, x=sector_counts.values, orientation='h',
                    marker=dict(color=b.TYPE_COLOR_ECON),
                    text=sector_counts.values, textposition='auto',
                )])
                fig.update_layout(
                    title="Projects by Sector", template="plotly_dark",
                    paper_bgcolor=b.PANEL, plot_bgcolor=b.PANEL,
                    height=350, margin=dict(l=200, r=40, t=40, b=40),
                )
                st.plotly_chart(fig, use_container_width=True)

            table = country_projects[['event_date', 'source', 'narrative_summary']].head(50).rename(
                columns={'event_date': 'Commitment Date', 'source': 'Financier', 'narrative_summary': 'Project'}
            )
            st.dataframe(table, use_container_width=True, hide_index=True)


def render_news_dashboard(news_df):
    st.markdown(
        "Current-events news and social signal — GDELT, Infobae, Jeune Afrique, Bellingcat, The New "
        "York Times, and The Wall Street Journal. Ranked by a significance score — not just recency — "
        "so the most important stories surface first, with a cap on how many any single source can "
        "contribute to the top list, and no source is presented as a fixed feed of its most recent "
        "stories. For deeper policy/academic long-form reading, see the Long Form Pieces tab."
    )
    if len(news_df) == 0:
        st.info("No news/social signal data loaded yet.")
        return

    # Defaults to the last 7 days -- Chris: "I want like within the last
    # week on there... I saw one from Angola that was from 2023... too
    # old." A significance-ranked top-30 list can still surface an old
    # event if nothing recent scores as high, so this is a hard filter,
    # not just a ranking nudge. Widening is available for sources that
    # don't publish daily (UNOSAT, Bellingcat) where a strict 7-day
    # window can come up thin.
    FRESHNESS_OPTIONS = {"Last 7 days": 7, "Last 14 days": 14, "Last 30 days": 30, "Last 90 days": 90, "All time": None}
    freshness_label = st.selectbox("Show events from", options=list(FRESHNESS_OPTIONS.keys()),
                                    index=0, key="news_freshness")
    freshness_days = FRESHNESS_OPTIONS[freshness_label]
    if freshness_days is not None:
        cutoff = pd.Timestamp.utcnow().tz_localize(None).normalize() - pd.Timedelta(days=freshness_days)
        news_df = news_df[news_df['event_date'] >= cutoff]

    if len(news_df) == 0:
        st.info(f"No news/social signal events in the {freshness_label.lower()} window -- try widening it.")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Signal Events (in window)", f"{len(news_df):,}")
    with col2:
        st.metric("Countries Covered", news_df['country'].nunique())
    with col3:
        st.metric("Sources", news_df['source'].nunique())

    scored = news_df.copy()
    scored["significance_score"] = compute_significance_score(scored)
    top = diversify_top_n(scored, "significance_score", n=30, max_per_source=8)

    source_mix = ", ".join(f"{src} ({n})" for src, n in top['source'].value_counts().items())
    st.caption(f"Source mix in this list: {source_mix}")

    # Hard cap of 3 badges total across this list -- Chris: "I should only
    # see the top three data points available for a specific tab marked
    # that way." Rank 1 = Urgent, ranks 2-3 = Top signal, everything else
    # gets no badge at all (replaces the earlier percentile-tier approach,
    # which could still badge more than 3 items on a wide score spread).
    badges_by_idx = top_n_badges(top["significance_score"], n=3)
    TIER_LABELS = {"urgent": "Urgent", "top": "Top signal", "medium": "Notable"}

    # Same 3-column card-grid layout as the Research & Analysis tab
    # (image on top, title/meta/body below) -- Chris asked for a
    # consistent look-and-feel across both reading-material tabs.
    cols = st.columns(3)
    for i, (idx, event) in enumerate(top.iterrows()):
        tier = badges_by_idx.get(idx)
        card_class = f"fm-news-card-{tier or 'routine'}"
        tier_badge = f'<span class="fm-badge fm-badge-{tier}">{TIER_LABELS[tier]}</span>' if tier else ""
        image_url = event.get("image_url")
        # Non-English sources (Infobae/Spanish, Jeune Afrique/French) carry
        # an English translation in narrative_summary_en when normalized
        # with --translate -- show English by default, with the original
        # available on demand, per Chris's ask.
        translation = event.get("narrative_summary_en")
        has_translation = pd.notna(translation) and translation and translation != event['narrative_summary']
        display_text = translation if has_translation else event['narrative_summary']

        with cols[i % 3]:
            if pd.notna(image_url):
                st.markdown(
                    f'<img src="{image_url}" style="width:100%;aspect-ratio:16/9;'
                    f'object-fit:cover;border-radius:4px;margin-bottom:0.4rem;">',
                    unsafe_allow_html=True,
                )
            st.markdown(
                f'<div class="{card_class}">'
                f"<div><strong>{event['country']}</strong> — {event['event_date']} &nbsp;·&nbsp; "
                f"<em>{event['source']}</em>{tier_badge}</div>"
                f"<div>{display_text}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if has_translation:
                with st.expander(f"Show original ({event['source']})"):
                    st.markdown(event['narrative_summary'])
            if pd.notna(event.get('source_url')):
                st.markdown(f"[Read full source →]({event['source_url']})")
            st.markdown("---")


# Keyword heuristic for the Great Power Competition dashboard -- there's no
# dedicated entity resolution yet (that's Phase 3/4), so this is a text-match
# stand-in over the merged dataset, not a real actor-tagged filter. Flagged
# clearly in the UI as preliminary.
CHINA_KEYWORDS = ["china", "chinese", "beijing", "prc", "belt and road"]
IRAN_KEYWORDS = ["iran", "iranian", "tehran", "irgc"]


def _keyword_mask(df_scope, keywords):
    text = (
        df_scope["narrative_summary"].fillna("").str.lower() + " " +
        df_scope["country"].fillna("").str.lower()
    )
    pattern = "|".join(keywords)
    return text.str.contains(pattern, regex=True)


def render_greatpower_dashboard(df):
    st.markdown(
        "US-China and US-Iran competition signal, drawn from the same merged conflict/economic/"
        "news dataset above. **Preliminary** — this is keyword matching over country names and "
        "event summaries (no dedicated actor/entity resolution yet), so treat it as a first-pass "
        "filter, not a definitive tally."
    )

    china_df = df[_keyword_mask(df, CHINA_KEYWORDS)]
    iran_df = df[_keyword_mask(df, IRAN_KEYWORDS)]

    china_tab, iran_tab = st.tabs(["US-China Competition", "US-Iran Conflict"])

    for tab, subset, label in [(china_tab, china_df, "China"), (iran_tab, iran_df, "Iran")]:
        with tab:
            if len(subset) == 0:
                st.info(f"No {label}-related signal in the currently loaded data.")
                continue
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Matching Events", f"{len(subset):,}")
            with col2:
                st.metric("Countries Involved", subset['country'].nunique())
            with col3:
                conflict_count = len(subset[subset['event_category'].isin(CONFLICT_CATEGORIES)])
                st.metric("Conflict-Related", conflict_count)

            # Ranked by significance, not just recency -- Chris: "mark/
            # prioritize the...great power competition and Iran conflict
            # data points by prioritization as well," capped at exactly 3
            # badges per tab (see top_n_badges' docstring for why a hard
            # cap beats a percentile tier here).
            scored_subset = subset.copy()
            scored_subset["significance_score"] = compute_significance_score(scored_subset)
            top = scored_subset.sort_values("significance_score", ascending=False).head(20)
            badges_by_idx = top_n_badges(top["significance_score"], n=3)
            TIER_LABELS = {"urgent": "Urgent", "top": "Top signal"}

            for idx, event in top.iterrows():
                tier = badges_by_idx.get(idx)
                tier_badge = f' <span class="fm-badge fm-badge-{tier}">{TIER_LABELS[tier]}</span>' if tier else ""
                st.markdown(
                    f"**{event['country']}** — {event['event_date']} "
                    f"*({b.type_label(event['event_category'])})*{tier_badge}  \n{event['narrative_summary']}",
                    unsafe_allow_html=True,
                )
                st.markdown("---")


def render_research_assistant(df):
    """The embedded chat assistant (Phase 1) -- a conversational research
    aid grounded on this platform's own curated dataset, with live web
    search and Excel/PDF export, no image generation. Unlike every other
    tab on this dashboard, this one calls the Anthropic API live from the
    deployed app (see scripts/analysis/chat_agent.py docstring for why
    that's a deliberate, one-time exception here). Enforces a simple
    per-browser-session message cap as a stopgap against runaway cost
    from one open tab -- real per-user quota enforcement needs the auth
    layer, not yet built."""
    st.markdown(
        "Ask questions grounded in Frontier Mercator's own curated data, or anything else -- "
        "the assistant can search this platform's dataset, search the live web, and generate "
        "Excel or PDF files on request. Preliminary research aid, not investment advice."
    )

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "chat_turns_used" not in st.session_state:
        st.session_state.chat_turns_used = 0
    if "chat_files" not in st.session_state:
        st.session_state.chat_files = []

    for msg in st.session_state.chat_history:
        if msg["role"] == "user" and isinstance(msg["content"], str):
            with st.chat_message("user"):
                st.markdown(msg["content"])
        elif msg["role"] == "assistant":
            texts = [b.get("text", "") for b in msg["content"] if isinstance(b, dict) and b.get("type") == "text"]
            reply = "\n".join(t for t in texts if t).strip()
            if reply:
                with st.chat_message("assistant"):
                    st.markdown(reply)

    for f in st.session_state.chat_files:
        st.download_button(
            f"Download {f['filename']}", data=f["bytes"], file_name=f["filename"],
            mime=f["mime"], key=f"chat_dl_{f['filename']}_{f['bytes'].__hash__()}",
        )

    remaining = MAX_TURNS_PER_SESSION - st.session_state.chat_turns_used
    if remaining <= 0:
        st.warning(
            f"You've reached the {MAX_TURNS_PER_SESSION}-message limit for this session. "
            f"Refresh the page to start a new session."
        )
        return

    user_input = st.chat_input("Ask about a country, event, or request a file...")
    if user_input:
        with st.chat_message("user"):
            st.markdown(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Researching..."):
                try:
                    result = run_chat_turn(df, st.session_state.chat_history, user_input)
                except Exception as e:
                    st.error(f"Something went wrong: {e}")
                    return
            st.markdown(result["reply"])
        st.session_state.chat_history = result["history"]
        st.session_state.chat_turns_used += 1
        st.session_state.chat_files.extend(result["generated_files"])
        for f in result["generated_files"]:
            st.download_button(
                f"Download {f['filename']}", data=f["bytes"], file_name=f["filename"],
                mime=f["mime"], key=f"chat_dl_new_{f['filename']}_{f['bytes'].__hash__()}",
            )
        st.caption(f"{remaining - 1} message(s) left this session.")


def render_unified_map(df):
    """Standalone aggregator map at the bottom of the page, combining
    conflict, economic, and news/social events in one filterable view --
    Chris's "Palantir Gotham" reference: the map should tell a story by
    juxtaposing discrete, dated EVENTS (a loan, an attack, a notable news
    story) so relationships between them jump out, not by overlaying
    periodic country-level statistics that aren't tied to a specific
    happening. Circles are colored by category type and sized by
    severity_score where available; events without a severity score get a
    recency-based size/opacity instead (see the recency_score block
    below). Investment events (AidData/DFC/WorldBankPPI -- a specific
    loan, grant, or backed project) have no native lat/lon since they're
    country-level, so they're plotted at the country's centroid.

    Deliberately excludes plain "economic_indicator" records (GDP growth
    %, inflation %, current account balance, etc.) -- those are periodic
    macro statistics, not discrete events, and don't belong on an
    events-and-actions map (Chris: "it shouldn't be a place to just
    overlay economic data that belongs to one country"). They're still
    fully available in the Markets & Economy tab's Macro Indicators
    charts, which is the right place for a time-series trend line."""
    st.markdown("## Unified Intelligence Map")
    st.markdown(
        "Every discrete event and action at once — conflict incidents (red), investment/financing "
        "activity like a loan or backed project (amber), news and social signal (cyan) -- so you can "
        "see, for example, a Chinese bank's loan, a DFC-backed mining investment, and a conflict "
        "incident all in the same place and window, and decide for yourself whether they're "
        "connected. Filter by type, region, severity, and date to narrow in on what matters to you."
    )

    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
    with filter_col1:
        type_options = st.multiselect(
            "Event type",
            options=["Conflict & Security", "Markets & Economy", "News & Social Signal"],
            default=["Conflict & Security", "Markets & Economy", "News & Social Signal"],
            key="unified_map_types",
        )
    with filter_col2:
        map_regions = st.multiselect(
            "Region", options=sorted(df['region'].dropna().unique()),
            default=[], key="unified_map_regions",
            help="Leave empty to include all regions.",
        )
    with filter_col3:
        map_min_severity = st.slider(
            "Min severity (conflict only)", 0.0, 10.0, 0.0, 0.5, key="unified_map_severity",
        )
    with filter_col4:
        date_bounds = df['event_date'].dropna()
        min_date, max_date = (date_bounds.min(), date_bounds.max()) if len(date_bounds) else (None, None)
        # Default to the last 5 years rather than the full historical span
        # (some sources go back decades) -- users can still widen it
        # manually via the picker's min/max bounds, but the default view
        # should emphasize recent activity, not get diluted by old data.
        default_start = max(min_date, max_date - pd.DateOffset(years=5)) if min_date is not None else None
        date_range = st.date_input(
            "Date range", value=(default_start, max_date) if min_date is not None else None,
            min_value=min_date, max_value=max_date,
            key="unified_map_dates",
        )

    scope = df[
        (df['event_category'] != 'economic_indicator')
        & df['event_category'].apply(lambda c: b.type_label(c) in type_options)
    ]
    if map_regions:
        scope = scope[scope['region'].isin(map_regions)]
    if isinstance(date_range, tuple) and len(date_range) == 2 and date_range[0] is not None:
        start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
        scope = scope[(scope['event_date'] >= start) & (scope['event_date'] <= end)]
    is_conflict = scope['event_category'].isin(CONFLICT_CATEGORIES)
    scope = scope[~is_conflict | (scope['severity_score'] >= map_min_severity)]

    # Significance score (0-10, see scripts/analytics/significance.py) --
    # the same blended severity/recency/fatalities/breaking-keyword score
    # used by the News & Social Signal tab, so "what's important" means
    # the same thing everywhere on the dashboard rather than the map using
    # a recency-only proxy while the news list uses something else.
    # Events without a native severity_score (economic indicators, most
    # news/social events) previously all fell back to the same flat
    # placeholder value, so when the marker cap below kicked in, ties broke
    # on row order (oldest-first in the source data) rather than anything
    # meaningful -- systematically dropping newer economic/news events in
    # favor of older ones. Significance now drives both which events survive
    # the cap and how prominently they're drawn (see radius/opacity below).
    significance_score = compute_significance_score(scope)

    MAX_MAP_MARKERS = 2000
    if len(scope) > MAX_MAP_MARKERS:
        # Cap per category, not globally -- conflict events vastly outnumber
        # economic/news events, so a global top-N-by-severity cut would show
        # conflict markers only and silently drop the other two colors
        # entirely, defeating the point of a *unified* map.
        n_types = scope['event_category'].apply(b.type_label).nunique() or 1
        per_type_cap = MAX_MAP_MARKERS // n_types
        scope = (
            scope.assign(_rank=significance_score)
            .groupby(scope['event_category'].apply(b.type_label), group_keys=False)
            .apply(lambda g: g.sort_values('_rank', ascending=False).head(per_type_cap))
        )
        st.caption(
            f"Showing up to {per_type_cap:,} highest-significance events per category "
            f"({len(scope):,} of {len(df):,} total matching events)."
        )
        # Recompute against the final (post-cap) scope so sizing below
        # reflects what's actually being drawn.
        significance_score = compute_significance_score(scope)

    # Tiers relative to this map scope's own score distribution -- same
    # reasoning as the News & Social Signal tab (see significance.py).
    map_tier_thresholds = compute_tier_thresholds(significance_score)

    m = folium.Map(location=[10, 10], zoom_start=2, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="High-Res Satellite (Esri)", overlay=False, control=True,
    ).add_to(m)
    # NASA GIBS: free, no-auth, near-real-time satellite imagery (MODIS,
    # ~1-day latency) -- gives an actually "up to date" imagery option
    # alongside Esri's higher-resolution but more static base layer. Chris's
    # ask for current satellite context on conflict zones/chokepoints; full
    # Sentinel Hub ingestion (higher-res, radar-capable for cloud cover) is
    # still on the roadmap as a proper ingested data source, not just a map
    # tile layer.
    gibs_date = (pd.Timestamp.utcnow() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    folium.TileLayer(
        tiles=(
            "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
            f"MODIS_Terra_CorrectedReflectance_TrueColor/default/{gibs_date}/"
            "GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg"
        ),
        attr="NASA GIBS (MODIS, near-real-time)", name=f"Recent Satellite ({gibs_date}, NASA)",
        overlay=False, control=True,
    ).add_to(m)
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png",
        attr="CartoDB", name="Labels", overlay=True, control=True,
    ).add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)

    for idx, event in scope.iterrows():
        lat, lon = event['latitude'], event['longitude']
        if pd.isna(lat) or pd.isna(lon):
            centroid = get_centroid(event.get('iso3', ''))
            if centroid is None:
                continue
            lat, lon = centroid
        # Marker size/opacity/border scale with the shared significance
        # score (see scripts/analytics/significance.py) so events that are
        # actually important -- high severity, breaking-keyword match,
        # recent -- visually pop out of the "white noise" of routine
        # markers, per Chris's explicit ask, rather than every marker
        # reading as visually equivalent regardless of importance.
        significance = significance_score.get(idx, 4.0)
        tier = significance_tier(significance, map_tier_thresholds)
        is_hot = tier in ("urgent", "top")
        fill_opacity = max(0.35, min(0.85, significance / 10))
        color = b.type_color(event['event_category'])
        # Escape user/source-controlled text before embedding in raw popup
        # HTML (folium.Popup renders it unescaped) -- narrative_summary and
        # country names can in principle contain characters that would
        # otherwise break the popup markup.
        import html as _html
        country_esc = _html.escape(str(event['country']))
        summary_esc = _html.escape(str(event['narrative_summary'])[:220])
        source_esc = _html.escape(str(event.get('source', 'Unknown')))
        tier_label = {"urgent": "URGENT", "top": "TOP SIGNAL"}.get(tier)
        popup_lines = [
            (f'<b style="color:{b.CRITICAL};">{tier_label}</b><br>' if tier_label else ""),
            f"<b>{country_esc}</b> — {event['event_date']}<br>",
            f"<b>Source:</b> {source_esc} &nbsp; "
            f"<b>Category:</b> {b.type_label(event['event_category'])} "
            f"({str(event['event_category']).replace('_', ' ')})<br>",
            f"<b>Summary:</b> {summary_esc}<br>",
        ]
        if pd.notna(event.get('fatalities')):
            popup_lines.append(f"<b>Fatalities:</b> {int(event['fatalities'])}<br>")
        source_url = event.get('source_url')
        if pd.notna(source_url) and source_url:
            url_esc = _html.escape(str(source_url), quote=True)
            popup_lines.append(f'<a href="{url_esc}" target="_blank" rel="noopener">Read full source →</a>')
        popup_text = "".join(popup_lines)
        # Hot/high-significance events get a bright gold border and a
        # heavier stroke weight so they visually stand out from routine
        # markers on the map itself, not just inside the popup -- Chris's
        # explicit ask for important things to "pop out of the white noise."
        border_color = b.GOLD if is_hot else color
        border_weight = 3 if is_hot else 1
        # Radius tuned twice per Chris's feedback: first shrunk ("too big
        # and crowded"), then bumped back up a notch ("can't click on
        # them because they're too small") -- current range ~4.5-10px is
        # the middle ground: clickable targets without the crowding.
        folium.CircleMarker(
            location=[lat, lon], radius=(5.5 if is_hot else 4.5) + (significance / 2.2),
            popup=folium.Popup(popup_text, max_width=340),
            color=border_color, fill=True, fillColor=color,
            fillOpacity=fill_opacity, weight=border_weight, opacity=min(0.95, fill_opacity + 0.15),
        ).add_to(m)

    # returned_objects=[] makes the map render-only: without it, st_folium
    # sets up bidirectional sync so every pan/zoom/click ON THE MAP fires a
    # full script rerun (the single biggest "why does everything take 5
    # seconds" contributor Chris hit) -- we never read anything back from
    # the map, so there's nothing to sync.
    st_folium(m, width=1200, height=650, key="unified_map", returned_objects=[])


st.markdown('<div id="fm-top"></div>', unsafe_allow_html=True)
st.markdown(
    f"""
    <div class="fm-topbar">
        <a href="?" class="fm-topbar-brand">
            <span class="fm-topbar-emblem">{_load_text(str(Path(__file__).parent / "static" / "fm_emblem.svg"))}</span>
            <span class="fm-topbar-brand-text">FRONTIER MERCATOR</span>
        </a>
        <a href="?">Home</a>
        <a href="?view=about">About</a>
        <a href="?view=contact">Contact</a>
    </div>
    """,
    unsafe_allow_html=True,
)

render_header()
render_video_hero()

events = load_events()
if not events:
    st.error("No data loaded. Run the ingestion scripts to populate data/normalized/.")
    st.stop()

df = prepare_dataframe(events)

# Chat lives in the sidebar (not a tab) so it's genuinely persistent --
# visible on every page/tab, not something you have to click into. Chris:
# "that inset window should be fixed on the screen." Streamlit doesn't
# support a truly floating overlay without a custom component, but the
# sidebar IS visible regardless of which main-content tab or ?view= page
# is active, which is the closest native equivalent -- rendered here,
# before the view router, so it shows on About/Contact too, not just the
# main dashboard tabs.
with st.sidebar:
    st.markdown("### 💬 Research Assistant")
    with st.expander("Open chat", expanded=True):
        render_research_assistant(df)
    st.markdown("---")

# Simple query-param page router -- About and Contact Us are deliberately
# NOT part of the main st.tabs() row anymore. The Unified Intelligence Map
# renders once, below the whole tabs widget (not inside any single tab),
# so when About/Contact were tabs in that same row the map always showed
# up underneath them too, regardless of which tab was selected -- Streamlit
# tabs don't support per-tab conditional content outside the tabs
# themselves. Routing About/Contact as separate pages instead is the clean
# fix (see render_about_page/render_contact_page's docstrings).
view = st.query_params.get("view", "dashboard")

if view == "about":
    render_about_page()
    render_footer(df)
    st.stop()
elif view == "contact":
    render_contact_page()
    render_footer(df)
    st.stop()

# --- Dashboard view (default, view == "dashboard") ---

# Sidebar filters (apply to the Conflict & Security dashboard)
st.sidebar.markdown("### Filters")
min_severity = st.sidebar.slider(
    "Minimum Severity Score", min_value=0.0, max_value=10.0, value=0.0, step=0.5
)

conflict_df_all = df[df['event_category'].isin(CONFLICT_CATEGORIES)]
all_regions = sorted(conflict_df_all['region'].dropna().unique())
core_regions = sorted(
    conflict_df_all.loc[conflict_df_all.get('in_core_mandate', True) == True, 'region'].dropna().unique()  # noqa: E712
)

include_extended = st.sidebar.checkbox(
    "Include extended monitoring (Europe, Middle East, Global)", value=True,
)
default_regions = all_regions if include_extended else core_regions
selected_regions = st.sidebar.multiselect("Regions", options=all_regions, default=default_regions)

conflict_filtered = conflict_df_all[
    (conflict_df_all['severity_score'] >= min_severity) & (conflict_df_all['region'].isin(selected_regions))
].copy()

econ_df = df[df['event_category'].isin(ECON_CATEGORIES)].copy()
news_df = df[df['event_category'].isin(NEWS_CATEGORIES)].copy()

st.markdown("---")

dash1, dash2, dash3, dash4, dash_longform, dash5 = st.tabs(
    ["Conflict & Security", "Markets & Economy", "News & Social Signal",
     "Great Power Competition", "Long Form Pieces", "Reports"]
)

with dash1:
    render_conflict_dashboard(conflict_filtered, news_df)

with dash2:
    render_markets_dashboard(econ_df)

with dash3:
    render_news_dashboard(news_df)

with dash4:
    render_greatpower_dashboard(df)

with dash_longform:
    render_research_analysis_tab(load_longform_articles())

with dash5:
    st.markdown("### Intelligence Briefs")
    st.markdown(
        "Generate a branded PDF brief from current data. Country briefs summarize a single "
        "country's event picture; regional briefs roll up all countries in a selected region. "
        "Countries and regions with the deepest current coverage are listed first, followed by "
        "every other country in the world -- pick any of them for an episodic report even if "
        "little or no data has been ingested for it yet."
    )

    # Every country in the world is selectable (Chris: "find and select any
    # country"), ordered core-mandate first, then extended, then everything
    # else -- so the Africa/LatAm focus stays the path of least resistance
    # without blocking a report on, say, Vietnam.
    _extended_regions = {"Europe", "Middle East"}
    country_options = sorted(
        ALL_COUNTRIES.items(),
        key=lambda kv: (not kv[1][2], kv[1][1] not in _extended_regions, kv[1][0]),
    )
    country_name_options = [name for _iso3, (name, _region, _mandate) in country_options]

    region_mandate = df.drop_duplicates("region").set_index("region")["in_core_mandate"]
    region_options = sorted(region_mandate.index, key=lambda r: (not region_mandate[r], r))

    report_col1, report_col2 = st.columns(2)
    with report_col1:
        st.markdown("#### Country Intelligence Brief")
        country_choice = st.selectbox("Country", options=country_name_options, key="country_brief_select")
        if st.button("Generate Country Brief", key="gen_country_brief"):
            pdf_bytes = generate_country_brief(df, country_choice)
            archive_report(pdf_bytes, report_type="country", label=country_choice)
            st.download_button(
                "Download PDF", data=pdf_bytes,
                file_name=f"Frontier_Mercator_{country_choice.replace(' ', '_')}_Brief.pdf",
                mime="application/pdf", key="dl_country_brief",
            )

        # Deliberately no inline text preview of the AI-synthesized pattern
        # analysis here -- Chris: "I don't want the country reports to
        # actually publish as text on the reports tab... pull that off the
        # active site page." Previously this rendered the full trend
        # summary/risk flags as page text for whatever country happened to
        # be the selectbox's default (alphabetically first), which read as
        # a stale report stuck on the page rather than something the user
        # asked for. The PDF (with its own Executive Summary section) is
        # now the only way to see this content -- click "Generate Country
        # Brief" above and download it.

        scorecard = load_scorecard(country_choice)
        if scorecard:
            st.markdown("##### Risk Scorecard")
            st.caption(
                "Decomposed 0-10 sub-scores (higher = more risk), computed deterministically from "
                "ingested event data -- not an AI judgment call. Security/Political Stability use a "
                "trailing 12-month window of conflict/unrest event frequency and severity; Economic "
                "uses the latest available inflation, current account, debt, and GDP growth figures "
                "against simple published-threshold heuristics."
            )
            scores = scorecard["scores"]
            badges = [
                ("Overall", scorecard["overall_risk"]),
                ("Security", scores["security_risk"]),
                ("Stability", scores["political_stability_risk"]),
                ("Economic", scores["economic_risk"]),
            ]
            badge_html = "".join(_risk_badge_html(label, value) for label, value in badges)
            st.markdown(f'<div class="fm-risk-badges">{badge_html}</div>', unsafe_allow_html=True)

        country_graph = _cached_country_graph(country_choice)
        if country_graph["nodes"]:
            st.markdown("##### Relationship Network")
            st.caption(
                f"The {len(country_graph['nodes']) - 1} most-connected actors in {country_choice}, "
                f"weighted by event count -- financiers, government bodies, and other named actors "
                f"linked to the country hub. Hover a node for its category breakdown."
            )
            st.plotly_chart(build_plotly_figure(country_graph), use_container_width=True, key="country_relationship_graph")
    with report_col2:
        st.markdown("#### Regional Executive Summary")
        region_choice = st.selectbox("Region", options=region_options, key="region_brief_select")
        if st.button("Generate Regional Brief", key="gen_regional_brief"):
            pdf_bytes = generate_regional_brief(df, region_choice)
            archive_report(pdf_bytes, report_type="regional", label=region_choice)
            st.download_button(
                "Download PDF", data=pdf_bytes,
                file_name=f"Frontier_Mercator_{region_choice.replace(' ', '_').replace('/', '-')}_Brief.pdf",
                mime="application/pdf", key="dl_regional_brief",
            )

    custom_analyses = load_custom_analyses()
    if custom_analyses:
        st.markdown("---")
        st.markdown("#### Custom Analysis")
        st.markdown(
            "Ad-hoc, cross-cutting questions that don't map to a single country or region -- "
            "answered by semantic search across the full dataset rather than a fixed filter "
            "(e.g. \"critical minerals VC investment opportunities in West Africa resulting from "
            "a recent coup or resource discovery\"). Generated offline via "
            "`scripts/analysis/reasoning_agent.py --query \"...\" --save`."
        )
        # No inline text preview of the answer here either -- same fix as
        # the Country Intelligence Brief section above (Chris doesn't want
        # report content rendered as page text, only as a downloadable
        # PDF). Just pick a question and generate the file.
        query_labels = {a["query"]: a for a in custom_analyses}
        query_choice = st.selectbox("Question", options=list(query_labels.keys()), key="custom_analysis_select")
        selected = query_labels[query_choice]
        st.caption(
            f"Generated {selected['generated_at'][:10]} from {selected['events_retrieved']:,} "
            f"retrieved events — preliminary statistical synthesis, not an investment recommendation."
        )
        if st.button("Generate PDF", key="gen_custom_report"):
            pdf_bytes = generate_custom_report(selected)
            archive_report(pdf_bytes, report_type="custom", label=selected["query"])
            st.download_button(
                "Download PDF", data=pdf_bytes,
                file_name=f"Frontier_Mercator_Custom_Analysis_{selected['query'][:40].replace(' ', '_')}.pdf",
                mime="application/pdf", key="dl_custom_report",
            )

    archived_reports = list_archived_reports()
    if archived_reports:
        st.markdown("---")
        st.markdown("#### Report Archive")
        st.markdown(
            "Every brief generated from this dashboard is saved here for later reference -- "
            "filter by type or search by name, then re-download without regenerating."
        )
        archive_col1, archive_col2 = st.columns(2)
        with archive_col1:
            type_filter = st.multiselect(
                "Report type", options=["country", "regional", "custom"],
                default=["country", "regional", "custom"], key="archive_type_filter",
            )
        with archive_col2:
            search_text = st.text_input("Search by name/query", key="archive_search")

        filtered = [
            r for r in archived_reports
            if r["report_type"] in type_filter
            and (not search_text or search_text.lower() in r["label"].lower())
        ]
        st.caption(f"{len(filtered)} of {len(archived_reports)} archived reports")
        for report in filtered[:50]:
            col_a, col_b, col_c = st.columns([3, 1, 1])
            with col_a:
                st.markdown(f"**{report['label']}** — {report['report_type']}")
            with col_b:
                st.caption(report["generated_at"][:10])
            with col_c:
                pdf_path = Path(report["pdf_path"])
                if pdf_path.exists():
                    st.download_button(
                        "Download", data=pdf_path.read_bytes(),
                        file_name=f"Frontier_Mercator_{report['label'][:40].replace(' ', '_')}.pdf",
                        mime="application/pdf", key=f"dl_archive_{report['id']}",
                    )

st.markdown("---")
render_unified_map(df)

render_footer(df)
