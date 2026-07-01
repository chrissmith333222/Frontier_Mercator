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

from scripts.reports.pdf_report import generate_country_brief, generate_regional_brief
from scripts import branding as b
from scripts.lib.worldbank_indicators import INDICATORS as WORLDBANK_INDICATOR_LABELS
from scripts.lib.imf_indicators import INDICATORS as IMF_INDICATOR_LABELS
from scripts.lib.world_countries import ALL_COUNTRIES, get_centroid

INDICATOR_LABELS = {code: label for code, (label, _cat) in {
    **WORLDBANK_INDICATOR_LABELS, **IMF_INDICATOR_LABELS,
}.items()}

DATA_DIR = Path(__file__).parent / "data" / "normalized"
CONFLICT_CATEGORIES = b.CONFLICT_CATEGORIES
ECON_CATEGORY = b.ECON_CATEGORY
NEWS_CATEGORIES = b.NEWS_CATEGORIES

# Page config
st.set_page_config(
    page_title="Frontier Mercator — Intelligence for the Frontier",
    page_icon=str(Path(__file__).parent / "Frontier_Mercator_Logo.jpg"),
    layout="wide",
    initial_sidebar_state="collapsed"
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

    .fm-header-block {{
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        width: 100%;
        margin: 1rem 0 0 0;
    }}

    .fm-emblem-large {{
        width: 130px;
        height: 130px;
    }}

    .fm-wordmark {{
        font-family: {b.DISPLAY_FONT_STACK};
        font-weight: 700;
        font-size: 3.4rem;
        letter-spacing: 3px;
        text-align: center;
        color: {b.TEXT_PRIMARY};
        transform: skew(-6deg);
        margin: 0.75rem 0 0 0;
    }}

    .stMetric {{
        background-color: {b.PANEL};
        border: 1px solid {b.BORDER};
        border-left: 4px solid {b.ACCENT};
        padding: 1.5rem;
        border-radius: 4px;
    }}

    .stTabs [data-baseweb="tab-list"] button {{
        color: {b.TEXT_MUTED};
        border-bottom: 2px solid transparent;
    }}

    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {{
        color: {b.TEXT_PRIMARY};
        border-bottom: 3px solid {b.ACCENT};
    }}

    h1, h2, h3 {{
        color: {b.TEXT_PRIMARY};
        font-weight: 600;
        letter-spacing: -0.5px;
    }}

    .header-line {{
        height: 3px;
        background: linear-gradient(90deg, {b.ACCENT} 0%, {b.NAVY} 100%);
        margin-bottom: 2rem;
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
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_events():
    """Loads and merges normalized events from every ingested source
    (ACLED, GDELT, World Bank, IMF -- ReliefWeb once Chris's appname is
    approved). Each source writes its own <source>_latest_normalized.json;
    merging here means adding a new source is just dropping its file in
    data/normalized/, no dashboard code changes needed."""
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


def render_conflict_dashboard(df_filtered):
    st.markdown(
        "Security-relevant events — conflict, protest, political violence — from ACLED and GDELT."
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

    analytics_tab, critical_tab = st.tabs(["Analytics", "Critical Events"])
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
            st.plotly_chart(fig, width="stretch")

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
            st.plotly_chart(fig, width="stretch")

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
        st.plotly_chart(fig, width="stretch")

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


def render_markets_dashboard(econ_df):
    st.markdown(
        "Macroeconomic indicators — GDP growth, inflation, external debt, current account, "
        "unemployment — from World Bank and IMF."
    )
    if len(econ_df) == 0:
        st.info("No economic indicator data loaded yet.")
        return

    col1, col2 = st.columns(2)
    with col1:
        country_choice = st.selectbox(
            "Country", options=sorted(econ_df['country'].dropna().unique()), key="econ_country"
        )
    with col2:
        indicators = sorted(econ_df['event_subtype'].dropna().unique())
        indicator_choice = st.selectbox(
            "Indicator", options=indicators, key="econ_indicator",
            format_func=lambda code: INDICATOR_LABELS.get(code, code),
        )

    subset = econ_df[
        (econ_df['country'] == country_choice) & (econ_df['event_subtype'] == indicator_choice)
    ].sort_values('event_date')

    if len(subset) > 0:
        st.markdown(f"#### {INDICATOR_LABELS.get(indicator_choice, indicator_choice)} — {country_choice}")
        # narrative_summary carries the formatted value (e.g. "GDP growth
        # (annual %): 3.2% (2025)") since severity_score is null for economic_
        # indicator events -- parse the number back out for charting.
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
        st.plotly_chart(fig, width="stretch")

        table = subset[['event_date', 'source', 'narrative_summary']].rename(
            columns={'event_date': 'Date', 'source': 'Source', 'narrative_summary': 'Value'}
        )
        st.dataframe(table, width="stretch", hide_index=True)
    else:
        st.info("No data for this country/indicator combination.")

    st.markdown("#### Latest Snapshot Across Tracked Countries")
    latest = (
        econ_df[econ_df['event_subtype'] == indicator_choice]
        .sort_values('event_date')
        .drop_duplicates('country', keep='last')
        [['country', 'region', 'event_date', 'narrative_summary']]
        .rename(columns={
            'country': 'Country', 'region': 'Region',
            'event_date': 'Latest Data', 'narrative_summary': 'Value',
        })
        .sort_values('Country')
    )
    st.dataframe(latest, width="stretch", hide_index=True)


def render_news_dashboard(news_df):
    st.markdown(
        "Broader political/economic/diplomatic signal from GDELT, beyond direct conflict events. "
        "**Preliminary** — this is GDELT's own event coding, not a curated news feed; dedicated "
        "news/social source integration is planned."
    )
    if len(news_df) == 0:
        st.info("No news/social signal data loaded yet.")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Signal Events (last window)", f"{len(news_df):,}")
    with col2:
        st.metric("Countries Covered", news_df['country'].nunique())

    top = news_df.sort_values('event_date', ascending=False).head(30)
    for _, event in top.iterrows():
        st.markdown(f"**{event['country']}** — {event['event_date']}  \n"
                    f"{event['narrative_summary']}"
                    + (f"  \n[Source]({event['source_url']})" if pd.notna(event.get('source_url')) else ""))
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

            top = subset.sort_values('event_date', ascending=False).head(20)
            for _, event in top.iterrows():
                st.markdown(
                    f"**{event['country']}** — {event['event_date']} "
                    f"*({b.type_label(event['event_category'])})*  \n{event['narrative_summary']}"
                )
                st.markdown("---")


def render_unified_map(df):
    """Standalone aggregator map at the bottom of the page, combining
    conflict, economic, and news/social events in one filterable view --
    Chris's "Palantir Gotham" reference. Circles are colored by category
    type and sized by severity_score where available; economic/news events
    without a severity score get a fixed mid-size placeholder until the
    Phase 5 reasoning agent can assign real significance scores. Economic
    events have no native lat/lon (they're country-level annual stats), so
    they're plotted at the country's centroid instead."""
    st.markdown("## Unified Intelligence Map")
    st.markdown(
        "Every category at once — conflict (red), markets/economy (amber), news/social signal "
        "(cyan). Filter by type, region, severity, and date to narrow in on what matters to you."
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
        date_range = st.date_input(
            "Date range", value=(min_date, max_date) if min_date is not None else None,
            key="unified_map_dates",
        )

    scope = df[df['event_category'].apply(lambda c: b.type_label(c) in type_options)]
    if map_regions:
        scope = scope[scope['region'].isin(map_regions)]
    if isinstance(date_range, tuple) and len(date_range) == 2 and date_range[0] is not None:
        start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
        scope = scope[(scope['event_date'] >= start) & (scope['event_date'] <= end)]
    is_conflict = scope['event_category'].isin(CONFLICT_CATEGORIES)
    scope = scope[~is_conflict | (scope['severity_score'] >= map_min_severity)]

    MAX_MAP_MARKERS = 2000
    if len(scope) > MAX_MAP_MARKERS:
        # Cap per category, not globally -- conflict events vastly outnumber
        # economic/news events, so a global top-N-by-severity cut would show
        # conflict markers only and silently drop the other two colors
        # entirely, defeating the point of a *unified* map.
        n_types = scope['event_category'].apply(b.type_label).nunique() or 1
        per_type_cap = MAX_MAP_MARKERS // n_types
        scope = (
            scope.assign(_rank=scope['severity_score'].fillna(3.0))
            .groupby(scope['event_category'].apply(b.type_label), group_keys=False)
            .apply(lambda g: g.sort_values('_rank', ascending=False).head(per_type_cap))
        )
        st.caption(
            f"Showing up to {per_type_cap:,} highest-significance events per category "
            f"({len(scope):,} of {len(df):,} total matching events)."
        )

    m = folium.Map(location=[10, 10], zoom_start=2, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Satellite", overlay=False, control=False,
    ).add_to(m)
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png",
        attr="CartoDB", name="Labels", overlay=True, control=False,
    ).add_to(m)

    for _, event in scope.iterrows():
        lat, lon = event['latitude'], event['longitude']
        if pd.isna(lat) or pd.isna(lon):
            centroid = get_centroid(event.get('iso3', ''))
            if centroid is None:
                continue
            lat, lon = centroid
        significance = event['severity_score'] if pd.notna(event['severity_score']) else 3.0
        color = b.type_color(event['event_category'])
        popup_text = (
            f"<b>{event['country']}</b> — {event['event_date']}<br>"
            f"<b>Category:</b> {b.type_label(event['event_category'])} "
            f"({str(event['event_category']).replace('_', ' ')})<br>"
            f"<b>Summary:</b> {str(event['narrative_summary'])[:150]}<br>"
        )
        folium.CircleMarker(
            location=[lat, lon], radius=4 + (significance / 1.5),
            popup=folium.Popup(popup_text, max_width=300),
            color=color, fill=True, fillColor=color,
            fillOpacity=0.8, weight=1, opacity=0.9,
        ).add_to(m)

    st_folium(m, width=1200, height=650, key="unified_map")


render_header()
render_video_hero()

events = load_events()
if not events:
    st.error("No data loaded. Run the ingestion scripts to populate data/normalized/.")
    st.stop()

df = prepare_dataframe(events)

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

econ_df = df[df['event_category'] == ECON_CATEGORY].copy()
news_df = df[df['event_category'].isin(NEWS_CATEGORIES)].copy()

st.markdown("---")

dash1, dash2, dash3, dash4, dash5, dash6 = st.tabs(
    ["Conflict & Security", "Markets & Economy", "News & Social Signal",
     "Great Power Competition", "Reports", "About"]
)

with dash1:
    render_conflict_dashboard(conflict_filtered)

with dash2:
    render_markets_dashboard(econ_df)

with dash3:
    render_news_dashboard(news_df)

with dash4:
    render_greatpower_dashboard(df)

with dash5:
    st.markdown("### Intelligence Briefs")
    st.markdown(
        "Generate a branded PDF brief from current data. Country briefs summarize a single "
        "country's event picture; regional briefs roll up all countries in a selected region. "
        "Africa/LatAm core-mandate countries and regions are listed first, extended-monitoring "
        "(Europe, Middle East) next, then every other country in the world -- pick any of them "
        "for an episodic report even if little or no data has been ingested for it yet."
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
            st.download_button(
                "Download PDF", data=pdf_bytes,
                file_name=f"Frontier_Mercator_{country_choice.replace(' ', '_')}_Brief.pdf",
                mime="application/pdf", key="dl_country_brief",
            )
    with report_col2:
        st.markdown("#### Regional Executive Summary")
        region_choice = st.selectbox("Region", options=region_options, key="region_brief_select")
        if st.button("Generate Regional Brief", key="gen_regional_brief"):
            pdf_bytes = generate_regional_brief(df, region_choice)
            st.download_button(
                "Download PDF", data=pdf_bytes,
                file_name=f"Frontier_Mercator_{region_choice.replace(' ', '_').replace('/', '-')}_Brief.pdf",
                mime="application/pdf", key="dl_regional_brief",
            )

with dash6:
    st.markdown("### About This Platform")
    st.markdown("""
    Frontier Mercator Group's intelligence platform provides structured, real-time analysis of
    conflict, political risk, macroeconomic conditions, and emerging market trends across Africa
    and Latin America, with episodic monitoring of global developments (Europe, Middle East, and
    beyond) where they bear on the core mandate.

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
    """)

st.markdown("---")
render_unified_map(df)

render_footer(df)
