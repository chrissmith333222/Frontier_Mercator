"""
Parallax Dashboard — Frontier Mercator Group
Real-time geopolitical intelligence visualization for Africa and Latin America.
"""

import streamlit as st
import json
import pandas as pd
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
from pathlib import Path

# Page config
st.set_page_config(
    page_title="Parallax — Frontier Mercator",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for branding
st.markdown("""
<style>
    :root {
        --primary-dark: #091E42;
        --primary-mid: #505F79;
        --primary-light: #FFFFFF;
    }

    * {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    }

    .main {
        background-color: #FFFFFF;
    }

    .stMetric {
        background-color: #F5F7FA;
        border-left: 4px solid #505F79;
        padding: 1.5rem;
        border-radius: 4px;
    }

    .stTabs [data-baseweb="tab-list"] button {
        color: #505F79;
        border-bottom: 2px solid transparent;
    }

    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
        color: #091E42;
        border-bottom: 3px solid #505F79;
    }

    h1, h2, h3 {
        color: #091E42;
        font-weight: 600;
        letter-spacing: -0.5px;
    }

    .header-line {
        height: 3px;
        background: linear-gradient(90deg, #505F79 0%, #091E42 100%);
        margin-bottom: 2rem;
    }

    .metric-card {
        background-color: #F5F7FA;
        border: 1px solid #DEEBF7;
        padding: 1.5rem;
        border-radius: 4px;
        margin-bottom: 1rem;
    }

    .severity-critical {
        color: #AE2A19;
        font-weight: 600;
    }

    .severity-high {
        color: #974F0C;
        font-weight: 600;
    }

    .severity-medium {
        color: #5E4DB2;
        font-weight: 600;
    }

    .severity-low {
        color: #216E4E;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# Load data
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
    """Convert events to pandas dataframe for analysis."""
    df = pd.DataFrame(events)

    # Parse dates
    df['event_date'] = pd.to_datetime(df['event_date'], errors='coerce')

    # Severity categories
    def severity_label(score):
        if score >= 7:
            return "Critical"
        elif score >= 5:
            return "High"
        elif score >= 3:
            return "Medium"
        else:
            return "Low"

    df['severity_label'] = df['severity_score'].apply(severity_label)
    return df

# Header
col1, col2 = st.columns([1, 4])
with col1:
    st.markdown("### 🧭")
with col2:
    st.markdown("### **PARALLAX**")
    st.markdown("*Intelligence for the Frontier*")

st.markdown('<div class="header-line"></div>', unsafe_allow_html=True)

# Load and prepare data
events = load_events()
if not events:
    st.error("⚠️ No data loaded. Ensure acled_latest_normalized.json exists in data/normalized/")
    st.stop()

df = prepare_dataframe(events)

# Sidebar filters
st.sidebar.markdown("### Filters")
min_severity = st.sidebar.slider(
    "Minimum Severity Score",
    min_value=0.0,
    max_value=10.0,
    value=0.0,
    step=0.5
)

selected_regions = st.sidebar.multiselect(
    "Regions",
    options=sorted(df['region'].dropna().unique()),
    default=sorted(df['region'].dropna().unique())
)

# Filter data
df_filtered = df[
    (df['severity_score'] >= min_severity) &
    (df['region'].isin(selected_regions))
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
    st.metric("🔴 Critical Events", critical)

with col3:
    high = len(df_filtered[(df_filtered['severity_score'] >= 5) & (df_filtered['severity_score'] < 7)])
    st.metric("🟠 High Severity", high)

with col4:
    unique_countries = df_filtered['country'].nunique()
    st.metric("Countries", unique_countries)

with col5:
    total_fatalities = df_filtered['fatalities'].fillna(0).sum()
    st.metric("Total Fatalities", f"{int(total_fatalities):,}")

st.markdown("---")

# Main visualization tabs
tab1, tab2, tab3, tab4 = st.tabs(["🗺️ Severity Map", "📊 Analytics", "🔥 Critical Events", "ℹ️ About"])

with tab1:
    st.markdown("### Event Severity Map")
    st.markdown("Geographic distribution of events across Africa and Latin America.")

    # Create folium map
    map_center = [-5, 20]  # Center on Africa
    m = folium.Map(
        location=map_center,
        zoom_start=3,
        tiles="CartoDB positron"
    )

    # Add events as markers
    for idx, event in df_filtered.iterrows():
        if pd.notna(event['latitude']) and pd.notna(event['longitude']):
            severity = event['severity_score']

            # Color by severity
            if severity >= 7:
                color = '#AE2A19'  # Critical red
            elif severity >= 5:
                color = '#974F0C'  # High orange
            elif severity >= 3:
                color = '#5E4DB2'  # Medium purple
            else:
                color = '#216E4E'  # Low green

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
                fillOpacity=0.7,
                weight=1,
                opacity=0.8
            ).add_to(m)

    st_folium(m, width=1200, height=600)

with tab2:
    st.markdown("### Analytical Dashboard")

    col1, col2 = st.columns(2)

    with col1:
        # Events by severity
        severity_counts = df_filtered['severity_label'].value_counts().reindex(
            ['Critical', 'High', 'Medium', 'Low']
        )

        fig = go.Figure(data=[
            go.Bar(
                x=severity_counts.index,
                y=severity_counts.values,
                marker=dict(
                    color=['#AE2A19', '#974F0C', '#5E4DB2', '#216E4E']
                ),
                text=severity_counts.values,
                textposition='auto',
                hovertemplate='<b>%{x}</b><br>Count: %{y}<extra></extra>'
            )
        ])
        fig.update_layout(
            title="Events by Severity Level",
            xaxis_title="Severity",
            yaxis_title="Count",
            template="plotly_white",
            height=400,
            margin=dict(l=40, r=40, t=60, b=40)
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # Events by region
        region_counts = df_filtered['region'].value_counts().head(10)

        fig = go.Figure(data=[
            go.Bar(
                y=region_counts.index,
                x=region_counts.values,
                orientation='h',
                marker=dict(color='#505F79'),
                text=region_counts.values,
                textposition='auto',
                hovertemplate='<b>%{y}</b><br>Count: %{x}<extra></extra>'
            )
        ])
        fig.update_layout(
            title="Top 10 Regions by Event Count",
            xaxis_title="Count",
            yaxis_title="Region",
            template="plotly_white",
            height=400,
            margin=dict(l=150, r=40, t=60, b=40)
        )
        st.plotly_chart(fig, use_container_width=True)

    # Events over time
    events_by_date = df_filtered.groupby(df_filtered['event_date'].dt.to_period('M')).size()
    events_by_date.index = events_by_date.index.to_timestamp()

    fig = go.Figure(data=[
        go.Scatter(
            x=events_by_date.index,
            y=events_by_date.values,
            mode='lines+markers',
            line=dict(color='#505F79', width=2),
            marker=dict(size=8),
            fill='tozeroy',
            fillcolor='rgba(80, 95, 121, 0.2)',
            hovertemplate='<b>%{x|%B %Y}</b><br>Events: %{y}<extra></extra>'
        )
    ])
    fig.update_layout(
        title="Events Over Time",
        xaxis_title="Date",
        yaxis_title="Count",
        template="plotly_white",
        height=400,
        margin=dict(l=40, r=40, t=60, b=40)
    )
    st.plotly_chart(fig, use_container_width=True)

with tab3:
    st.markdown("### Critical Events (Severity ≥ 7)")
    st.markdown("High-impact events requiring immediate attention.")

    critical_events = df_filtered[df_filtered['severity_score'] >= 7].sort_values(
        'severity_score',
        ascending=False
    ).head(20)

    if len(critical_events) > 0:
        for idx, event in critical_events.iterrows():
            with st.container():
                col1, col2 = st.columns([0.15, 0.85])
                with col1:
                    severity_color = "#AE2A19" if event['severity_score'] >= 7 else "#974F0C"
                    st.markdown(
                        f"<div style='background-color: {severity_color}; padding: 1rem; border-radius: 4px; text-align: center;'>"
                        f"<span style='color: white; font-weight: 600; font-size: 1.2rem;'>{event['severity_score']:.1f}</span></div>",
                        unsafe_allow_html=True
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
    st.markdown("### About Parallax")
    st.markdown("""
    **Parallax** is Frontier Mercator Group's geopolitical intelligence platform,
    designed to provide structured, real-time analysis of conflict, political risk,
    and emerging market trends across Africa and Latin America.

    #### Data Sources
    - **ACLED:** Armed Conflict Location & Event Data — geo-coded conflict and protest events
    - Regional updates: GDELT, ReliefWeb, UN OCHA (coming soon)

    #### Methodology
    Events are normalized to a common schema and scored using:
    - **Event type classification** — from ACLED's typology (battles, riots, protests, etc.)
    - **Fatality weighting** — casualty impact on severity
    - **Geographic precision** — location accuracy

    Severity scores range from 0–10, with 7+ flagged as requiring immediate review.

    #### Intelligence Standards
    - All analysis follows IC tradecraft conventions
    - Confidence levels: "we assess," "reporting indicates," "key intelligence gap"
    - Source attribution required for all claims
    - Designed for professional use in investment and national security contexts
    """)

st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: #505F79; font-size: 0.85rem; padding: 2rem 0;'>"
    f"<p><b>Frontier Mercator Group</b> | Intelligence for the Frontier</p>"
    f"<p>Data updated: {df['ingested_at'].max() if 'ingested_at' in df.columns else 'Unknown'}</p>"
    "</div>",
    unsafe_allow_html=True
)
