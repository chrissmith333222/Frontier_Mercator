"""
Frontier Mercator Group — Intelligence Dashboard
Real-time geopolitical intelligence visualization for Africa and Latin America.
"""

import streamlit as st
import json
import pandas as pd
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go
from pathlib import Path

from scripts.reports.pdf_report import generate_country_brief, generate_regional_brief
from scripts import branding as b

# Page config
st.set_page_config(
    page_title="Frontier Mercator — Intelligence for the Frontier",
    page_icon=str(Path(__file__).parent / "Frontier_Mercator_Logo.jpg"),
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for branding — dark theme, shared palette from scripts/branding.py
st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@400;500;600&family=Montserrat:wght@700;800&display=swap');

    * {{
        font-family: {b.FONT_STACK};
    }}

    .fm-wordmark {{
        font-family: {b.DISPLAY_FONT_STACK};
        font-weight: 800;
        font-size: 3.2rem;
        letter-spacing: 4px;
        text-align: center;
        color: {b.TEXT_PRIMARY};
        margin: 0.5rem 0 0 0;
    }}

    .fm-tagline {{
        text-align: center;
        font-style: italic;
        color: {b.ACCENT};
        font-size: 1.1rem;
        margin-bottom: 1rem;
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
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_events():
    """Load normalized ACLED events from data directory."""
    data_path = Path(__file__).parent / "data" / "normalized" / "acled_latest_normalized.json"
    if data_path.exists():
        with open(data_path, 'r') as f:
            return json.load(f)
    return []


@st.cache_data
def prepare_dataframe(events):
    """Convert events to pandas dataframe for analysis. Keeps every event,
    core mandate (Africa/LatAm) and extended monitoring (Europe, Middle East,
    Global/Other) alike — the map and analytics should show all of it. Default
    filtering to prioritize the core mandate happens via the sidebar region
    selector below, not by dropping data here."""
    df = pd.DataFrame(events)
    df['event_date'] = pd.to_datetime(df['event_date'], errors='coerce')
    df['severity_label'] = df['severity_score'].apply(b.severity_label)
    return df


def render_header():
    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.image(str(Path(__file__).parent / "Frontier_Mercator_Logo.jpg"), width=140)
    st.markdown('<div class="fm-wordmark">FRONTIER MERCATOR</div>', unsafe_allow_html=True)
    st.markdown('<div class="fm-tagline">Intelligence for the Frontier</div>', unsafe_allow_html=True)
    st.markdown('<div class="header-line"></div>', unsafe_allow_html=True)


def render_footer(df):
    st.markdown("---")
    st.markdown(
        "<div class='fm-footer'>"
        "<p><b>Frontier Mercator Group</b> | Intelligence for the Frontier</p>"
        f"<p>Data updated: {df['ingested_at'].max() if 'ingested_at' in df.columns else 'Unknown'}</p>"
        "</div>",
        unsafe_allow_html=True,
    )


render_header()

events = load_events()
if not events:
    st.error("No data loaded. Ensure acled_latest_normalized.json exists in data/normalized/")
    st.stop()

df = prepare_dataframe(events)

# Sidebar filters
st.sidebar.markdown("### Filters")
min_severity = st.sidebar.slider(
    "Minimum Severity Score", min_value=0.0, max_value=10.0, value=0.0, step=0.5
)

all_regions = sorted(df['region'].dropna().unique())
core_regions = sorted(df.loc[df.get('in_core_mandate', True) == True, 'region'].dropna().unique())  # noqa: E712
extended_regions = sorted(set(all_regions) - set(core_regions))

include_extended = st.sidebar.checkbox(
    "Include extended monitoring (Europe, Middle East, Global)", value=True,
)
default_regions = all_regions if include_extended else core_regions

selected_regions = st.sidebar.multiselect(
    "Regions", options=all_regions, default=default_regions,
)

df_filtered = df[
    (df['severity_score'] >= min_severity) & (df['region'].isin(selected_regions))
].copy()

# Key metrics row
st.markdown("### Dashboard Overview")
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric(
        "Total Events",
        f"{len(df_filtered):,}",
        f"Latest: {df_filtered['event_date'].max().strftime('%Y-%m-%d') if len(df_filtered) > 0 else 'N/A'}"
    )
with col2:
    critical = len(df_filtered[df_filtered['severity_score'] >= 7])
    st.metric("Critical Events", critical)
with col3:
    high = len(df_filtered[(df_filtered['severity_score'] >= 5) & (df_filtered['severity_score'] < 7)])
    st.metric("High Severity", high)
with col4:
    st.metric("Countries", df_filtered['country'].nunique())
with col5:
    total_fatalities = df_filtered['fatalities'].fillna(0).sum()
    st.metric("Total Fatalities", f"{int(total_fatalities):,}")

st.markdown("---")

# Main visualization tabs — no emoji icons, plain professional labels
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["Severity Map", "Analytics", "Critical Events", "Reports", "About"]
)

with tab1:
    st.markdown("### Event Severity Map")
    st.markdown(
        "Geographic distribution of events. Shows the Africa/LatAm core mandate by default — "
        "enable extended monitoring in the sidebar to add Europe, Middle East, and Global/Other. "
        "Satellite basemap."
    )

    map_center = [-5, 20]
    m = folium.Map(
        location=map_center,
        zoom_start=3,
        tiles=None,
    )
    # High-resolution color satellite imagery (Esri World Imagery), matching
    # the "Bloomberg terminal meets Palantir Gotham" visual target better than
    # a flat/light basemap.
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Satellite",
        overlay=False,
        control=False,
    ).add_to(m)
    # Subtle dark reference labels on top of imagery for country/city names
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png",
        attr="CartoDB",
        name="Labels",
        overlay=True,
        control=False,
    ).add_to(m)

    for _, event in df_filtered.iterrows():
        if pd.notna(event['latitude']) and pd.notna(event['longitude']):
            severity = event['severity_score']
            color = b.severity_color(severity)
            popup_text = f"""
            <b>{event['country']}</b> — {event['event_date']}<br>
            <b>Type:</b> {event['event_category']}<br>
            <b>Severity:</b> {severity:.1f}/10<br>
            <b>Summary:</b> {event['narrative_summary'][:100]}...<br>
            """
            folium.CircleMarker(
                location=[event['latitude'], event['longitude']],
                radius=5 + (severity / 2),
                popup=folium.Popup(popup_text, max_width=300),
                color=color,
                fill=True,
                fillColor=color,
                fillOpacity=0.85,
                weight=1,
                opacity=0.9,
            ).add_to(m)

    st_folium(m, width=1200, height=600)

with tab2:
    st.markdown("### Analytical Dashboard")

    col1, col2 = st.columns(2)

    with col1:
        severity_counts = df_filtered['severity_label'].value_counts().reindex(
            ['Critical', 'High', 'Medium', 'Low']
        )
        fig = go.Figure(data=[
            go.Bar(
                x=severity_counts.index, y=severity_counts.values,
                marker=dict(color=[b.CRITICAL, b.HIGH, b.MEDIUM, b.LOW]),
                text=severity_counts.values, textposition='auto',
                hovertemplate='<b>%{x}</b><br>Count: %{y}<extra></extra>',
            )
        ])
        fig.update_layout(
            title="Events by Severity Level", xaxis_title="Severity", yaxis_title="Count",
            template="plotly_dark", paper_bgcolor=b.PANEL, plot_bgcolor=b.PANEL,
            height=400, margin=dict(l=40, r=40, t=60, b=40),
        )
        st.plotly_chart(fig, width="stretch")

    with col2:
        region_counts = df_filtered['region'].value_counts().head(10)
        fig = go.Figure(data=[
            go.Bar(
                y=region_counts.index, x=region_counts.values, orientation='h',
                marker=dict(color=b.ACCENT),
                text=region_counts.values, textposition='auto',
                hovertemplate='<b>%{y}</b><br>Count: %{x}<extra></extra>',
            )
        ])
        fig.update_layout(
            title="Top 10 Regions by Event Count", xaxis_title="Count", yaxis_title="Region",
            template="plotly_dark", paper_bgcolor=b.PANEL, plot_bgcolor=b.PANEL,
            height=400, margin=dict(l=150, r=40, t=60, b=40),
        )
        st.plotly_chart(fig, width="stretch")

    events_by_date = df_filtered.groupby(df_filtered['event_date'].dt.to_period('M')).size()
    events_by_date.index = events_by_date.index.to_timestamp()

    fig = go.Figure(data=[
        go.Scatter(
            x=events_by_date.index, y=events_by_date.values, mode='lines+markers',
            line=dict(color=b.ACCENT, width=2), marker=dict(size=8),
            fill='tozeroy', fillcolor='rgba(110, 143, 199, 0.2)',
            hovertemplate='<b>%{x|%B %Y}</b><br>Events: %{y}<extra></extra>',
        )
    ])
    fig.update_layout(
        title="Events Over Time", xaxis_title="Date", yaxis_title="Count",
        template="plotly_dark", paper_bgcolor=b.PANEL, plot_bgcolor=b.PANEL,
        height=400, margin=dict(l=40, r=40, t=60, b=40),
    )
    st.plotly_chart(fig, width="stretch")

with tab3:
    st.markdown("### Critical Events (Severity ≥ 7)")
    st.markdown("High-impact events requiring immediate attention.")

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
                    st.markdown(f"*{event['event_category'].replace('_', ' ').title()}*")
                    st.markdown(f"**Summary:** {event['narrative_summary']}")
                    if event['fatalities'] and event['fatalities'] > 0:
                        st.markdown(f"**Fatalities:** {int(event['fatalities'])}")
                    st.markdown("---")
    else:
        st.info("No critical events with severity ≥ 7 in the current filter.")

with tab4:
    st.markdown("### Intelligence Briefs")
    st.markdown(
        "Generate a branded PDF brief from current data. Country briefs summarize a single "
        "country's event picture; regional briefs roll up all countries in a selected region. "
        "Africa/LatAm core-mandate countries and regions are listed first; extended-monitoring "
        "options (Europe, Middle East, Global/Other) are available below them for episodic reports."
    )

    # Core-mandate options first, then extended — matches the "prioritize Africa/
    # LatAm, but allow episodic global reports" direction.
    country_mandate = df.drop_duplicates("country").set_index("country")["in_core_mandate"]
    country_options = sorted(country_mandate.index, key=lambda c: (not country_mandate[c], c))

    region_mandate = df.drop_duplicates("region").set_index("region")["in_core_mandate"]
    region_options = sorted(region_mandate.index, key=lambda r: (not region_mandate[r], r))

    report_col1, report_col2 = st.columns(2)

    with report_col1:
        st.markdown("#### Country Intelligence Brief")
        country_choice = st.selectbox("Country", options=country_options, key="country_brief_select")
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

with tab5:
    st.markdown("### About This Platform")
    st.markdown("""
    Frontier Mercator Group's geopolitical intelligence platform provides structured,
    real-time analysis of conflict, political risk, and emerging market trends across
    Africa and Latin America, with episodic monitoring of global developments (Europe,
    Middle East, and beyond) where they bear on the core mandate.

    #### Data Sources
    - **ACLED:** Armed Conflict Location & Event Data — geo-coded conflict and protest events
    - **GDELT:** global event database, 15-minute update cadence
    - Regional updates: ReliefWeb, UN OCHA, World Bank, IMF (coming soon)

    #### Methodology
    Events are normalized to a common schema and scored using:
    - **Event type classification** — from each source's native typology (battles, riots, protests, etc.)
    - **Fatality / conflict-intensity weighting** — casualty impact and tone on severity
    - **Geographic precision** — location accuracy

    Severity scores range from 0–10, with 7+ flagged as requiring immediate review.

    #### Intelligence Standards
    - All analysis follows IC tradecraft conventions
    - Confidence levels: "we assess," "reporting indicates," "key intelligence gap"
    - Source attribution required for all claims
    - Designed for professional use in investment and national security contexts
    """)

render_footer(df)
