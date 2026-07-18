"""
scripts/reports/pdf_report.py

Generates client-ready PDF intelligence briefs (Country Intelligence Brief,
Regional Executive Summary) branded for Frontier Mercator Group. No internal
tool/codename ("Parallax") appears anywhere in the output — these are the
client-facing deliverable, and should read like a professional research
product, not a dev tool export.

Dark theme, matching the dashboard (see scripts/branding.py for the shared
palette) — Chris wants the dark, Bloomberg-terminal-adjacent identity to
carry through to the printed/downloaded reports, not just the site.

Data-driven (quantified event/severity statistics from ACLED/GDELT, plus a
macroeconomic snapshot from World Bank/IMF). Country briefs also include a
Claude-generated pattern-analysis section when a cached assessment exists
(see scripts/analysis/reasoning_agent.py) -- a preliminary statistical
synthesis grounded strictly in the ingested event data, not an investment
recommendation or forecast. Regions/countries without a cached assessment
yet just get the statistical snapshot, same as before.

Usage (as a module, called from dashboard.py):
    from scripts.reports.pdf_report import generate_country_brief, generate_regional_brief
    pdf_bytes = generate_country_brief(df, "Mozambique")
"""

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable, HRFlowable,
)
from svglib.svglib import svg2rlg

import json

from scripts import branding as b
from scripts.lib.world_countries import ALL_COUNTRIES

_NAME_TO_ISO3 = {name: iso3 for iso3, (name, _region, _mandate) in ALL_COUNTRIES.items()}
_ANALYSIS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "analysis"
_SCORECARD_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "scorecards"


def _load_scorecard(country: str) -> dict | None:
    """Reads a pre-generated risk scorecard (scripts/analytics/risk_scorecard.py)
    for `country`, if one exists -- same cache the dashboard's Risk
    Scorecard badges read from. Previously only shown in the Streamlit UI,
    never in the PDF itself, which left the printed brief without the
    single "how bad is this" number an institutional readahead leads with."""
    iso3 = _NAME_TO_ISO3.get(country)
    if not iso3:
        return None
    path = _SCORECARD_DIR / f"{iso3}_scorecard.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _load_cached_assessment(country: str) -> dict | None:
    """Reads a pre-generated AI assessment for `country`, if one exists.
    Same cache the dashboard's Reports tab reads from -- see
    scripts/analysis/reasoning_agent.py for how these get generated."""
    iso3 = _NAME_TO_ISO3.get(country)
    if not iso3:
        return None
    path = _ANALYSIS_DIR / f"{iso3}_assessment.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

# The emblem (not the old photographic logo -- retired everywhere per
# Chris's 2026-07-02 direction) is the one brand mark used across the site
# and reports now, so it never drifts out of sync in one product or the other.
EMBLEM_PATH = Path(__file__).resolve().parent.parent.parent / "static" / "fm_emblem.svg"


class _EmblemFlowable(Flowable):
    """Wraps the SVG emblem (via svglib) at a fixed size for the report header."""

    def __init__(self, size: float = 1.0 * inch):
        super().__init__()
        self.size = size
        self.drawing = svg2rlg(str(EMBLEM_PATH))
        scale = size / self.drawing.width
        self.drawing.width *= scale
        self.drawing.height *= scale
        self.drawing.scale(scale, scale)
        self.width = self.height = size
        self.hAlign = "CENTER"

    def draw(self):
        self.drawing.drawOn(self.canv, 0, 0)

# Pull the shared palette (defined once in scripts/branding.py) into reportlab colors.
PAGE_BG = colors.HexColor(b.BG)
PANEL = colors.HexColor(b.PANEL)
BORDER = colors.HexColor(b.BORDER)
NAVY = colors.HexColor(b.NAVY)
ACCENT = colors.HexColor(b.ACCENT)
TEXT_PRIMARY = colors.HexColor(b.TEXT_PRIMARY)
TEXT_MUTED = colors.HexColor(b.TEXT_MUTED)
CRITICAL = colors.HexColor(b.CRITICAL)
HIGH = colors.HexColor(b.HIGH)
MEDIUM = colors.HexColor(b.MEDIUM)
LOW = colors.HexColor(b.LOW)

STYLES = getSampleStyleSheet()
TITLE_STYLE = ParagraphStyle(
    "BriefTitle", parent=STYLES["Title"], textColor=TEXT_PRIMARY, fontSize=20, spaceAfter=4,
)
SUBTITLE_STYLE = ParagraphStyle(
    "BriefSubtitle", parent=STYLES["Normal"], textColor=ACCENT, fontSize=11, spaceAfter=12,
)
SECTION_STYLE = ParagraphStyle(
    "SectionHeader", parent=STYLES["Heading2"], textColor=TEXT_PRIMARY, fontSize=13,
    spaceBefore=14, spaceAfter=6,
)
BODY_STYLE = ParagraphStyle(
    "Body", parent=STYLES["Normal"], fontSize=9.5, textColor=TEXT_PRIMARY, leading=13,
)
DISCLAIMER_STYLE = ParagraphStyle(
    "Disclaimer", parent=STYLES["Normal"], fontSize=7.5, textColor=TEXT_MUTED, leading=10,
)
CELL_STYLE = ParagraphStyle(
    "TableCell", parent=STYLES["Normal"], fontSize=7.5, leading=9.5, textColor=TEXT_PRIMARY,
)
CELL_HEADER_STYLE = ParagraphStyle(
    "TableCellHeader", parent=STYLES["Normal"], fontSize=7.5, leading=9.5,
    textColor=TEXT_PRIMARY, fontName="Helvetica-Bold",
)


def _severity_color(score: float):
    if score >= 7:
        return CRITICAL
    if score >= 5:
        return HIGH
    if score >= 3:
        return MEDIUM
    return LOW


def _paint_dark_background(canvas, doc):
    """Fills the full page with the brand dark background before anything else
    is drawn, so the report reads as a dark-themed product end to end."""
    canvas.saveState()
    canvas.setFillColor(PAGE_BG)
    canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], stroke=0, fill=1)
    canvas.restoreState()


def _header_flowables(title: str, subtitle: str) -> list:
    flowables = []
    if EMBLEM_PATH.exists():
        flowables.append(_EmblemFlowable(size=0.9 * inch))
        flowables.append(Spacer(1, 8))
    flowables.append(Paragraph(title, TITLE_STYLE))
    flowables.append(Paragraph(subtitle, SUBTITLE_STYLE))
    flowables.append(HRFlowable(width="100%", thickness=2, color=ACCENT, spaceAfter=10))
    return flowables


def _summary_table(df_scope: pd.DataFrame) -> tuple[Table, str]:
    """df_scope here is already filtered to conflict-category events only
    (see _build_pdf) -- the merged multi-source dataset also contains
    economic_indicator and news-signal rows with null severity_score, which
    would otherwise inflate "Total Events" with non-conflict data."""
    total_events = len(df_scope)
    critical = int((df_scope["severity_score"] >= 7).sum())
    high = int(((df_scope["severity_score"] >= 5) & (df_scope["severity_score"] < 7)).sum())
    fatalities = int(df_scope["fatalities"].fillna(0).sum())
    countries = df_scope["country"].nunique()
    date_range = ""
    dates = pd.to_datetime(df_scope["event_date"], errors="coerce").dropna()
    if len(dates) > 0:
        date_range = f"{dates.min().strftime('%d %b %Y')} – {dates.max().strftime('%d %b %Y')}"

    data = [
        ["Total Events", "Critical (≥7)", "High (5–6.9)", "Fatalities", "Countries Covered"],
        [str(total_events), str(critical), str(high), f"{fatalities:,}", str(countries)],
    ]
    table = Table(data, colWidths=[1.5 * inch] * 5)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), TEXT_PRIMARY),
        ("BACKGROUND", (0, 1), (-1, 1), PANEL),
        ("TEXTCOLOR", (0, 1), (-1, 1), TEXT_PRIMARY),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
    ]))
    return table, date_range


def _events_table(df_scope: pd.DataFrame, limit: int = 15) -> Table:
    top = df_scope.sort_values("severity_score", ascending=False).head(limit)
    header = [Paragraph(h, CELL_HEADER_STYLE) for h in ["Date", "Country", "Category", "Sev.", "Summary"]]
    rows = [header]
    for _, ev in top.iterrows():
        summary = str(ev.get("narrative_summary", ""))[:160]
        sev = ev.get("severity_score", 0)
        sev_style = ParagraphStyle(
            "Sev", parent=CELL_STYLE, textColor=_severity_color(sev), fontName="Helvetica-Bold",
        )
        rows.append([
            Paragraph(str(ev.get("event_date", ""))[:10], CELL_STYLE),
            Paragraph(str(ev.get("country", "")), CELL_STYLE),
            Paragraph(str(ev.get("event_category", "")).replace("_", " ").title(), CELL_STYLE),
            Paragraph(f"{sev:.1f}", sev_style),
            Paragraph(summary, CELL_STYLE),
        ])
    table = Table(rows, colWidths=[0.8 * inch, 0.8 * inch, 1.1 * inch, 0.4 * inch, 2.9 * inch], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAGE_BG, PANEL]),
    ]
    table.setStyle(TableStyle(style))
    return table


def _macro_snapshot_table(econ_scope: pd.DataFrame) -> Table | None:
    """Latest reading per indicator for the report's country/region scope,
    from World Bank/IMF economic_indicator events. Returns None if there's
    nothing to show (e.g. World Bank/IMF haven't been run for this country)."""
    if len(econ_scope) == 0:
        return None
    latest = (
        econ_scope.sort_values("event_date")
        .drop_duplicates(subset=["country", "event_subtype"], keep="last")
        .sort_values(["country", "event_subtype"])
    )
    header = [Paragraph(h, CELL_HEADER_STYLE) for h in ["Country", "Indicator", "Latest Value", "Source"]]
    rows = [header]
    for _, ev in latest.iterrows():
        summary = str(ev.get("narrative_summary", ""))
        rows.append([
            Paragraph(str(ev.get("country", "")), CELL_STYLE),
            Paragraph(summary.split(":")[0], CELL_STYLE),
            Paragraph(summary.split(":", 1)[1].strip() if ":" in summary else summary, CELL_STYLE),
            Paragraph(str(ev.get("source", "")), CELL_STYLE),
        ])
    table = Table(rows, colWidths=[1.2 * inch, 2.3 * inch, 1.7 * inch, 0.9 * inch], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAGE_BG, PANEL]),
    ]))
    return table


def _demographic_snapshot_table(demo_scope: pd.DataFrame) -> Table | None:
    """Latest reading + trend (vs. earliest available reading) per
    demographic/development indicator for the report's country/region scope
    -- population, age structure, life expectancy, literacy. Returns None if
    nothing to show. The Trend column is computed deterministically (no LLM
    call) from the earliest vs. latest value in scope, same math as the
    dashboard's Demographics tab callout -- this is what makes the PDF show
    a trend, not just a single frozen reading, per Chris's ask."""
    if len(demo_scope) == 0:
        return None
    header = [Paragraph(h, CELL_HEADER_STYLE) for h in ["Country", "Indicator", "Latest Value", "Trend"]]
    rows = [header]
    for (country, subtype), group in demo_scope.groupby(["country", "event_subtype"]):
        ordered = group.sort_values("event_date")
        latest_summary = str(ordered.iloc[-1].get("narrative_summary", ""))
        indicator_label = latest_summary.split(":")[0]
        latest_value_text = latest_summary.split(":", 1)[1].strip() if ":" in latest_summary else latest_summary

        parsed = ordered["narrative_summary"].str.extract(r":\s*(-?[\d.]+)").astype(float)[0]
        trend_text = "—"
        if len(ordered) > 1 and pd.notna(parsed.iloc[0]) and pd.notna(parsed.iloc[-1]):
            first_val, last_val = parsed.iloc[0], parsed.iloc[-1]
            first_year = str(ordered["event_date"].iloc[0])[:4]
            delta = last_val - first_val
            # Percentage-of-total series (working-age share, urbanization,
            # etc.) can sit near/cross zero -- "% change of a %" is
            # misleading there, so show a point change instead. See the
            # matching fix in dashboard.py's _render_indicator_explorer.
            is_percentage_series = "%" in latest_value_text
            if is_percentage_series:
                arrow = "+" if delta > 0 else ("-" if delta < 0 else "")
                trend_text = f"{arrow}{abs(delta):.1f} pts since {first_year}"
            elif first_val != 0:
                arrow = "+" if delta > 0 else ("-" if delta < 0 else "")
                trend_text = f"{arrow}{abs(delta / first_val * 100):.1f}% since {first_year}"

        rows.append([
            Paragraph(str(country), CELL_STYLE),
            Paragraph(indicator_label, CELL_STYLE),
            Paragraph(latest_value_text, CELL_STYLE),
            Paragraph(trend_text, CELL_STYLE),
        ])
    if len(rows) == 1:
        return None
    table = Table(rows, colWidths=[1.2 * inch, 2.1 * inch, 1.3 * inch, 1.5 * inch], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAGE_BG, PANEL]),
    ]))
    return table


def _investment_table(investment_scope: pd.DataFrame, limit: int = 10) -> Table | None:
    """Largest development-finance projects (AidData Chinese financing +
    DFC U.S. financing) for the report's country/region scope, sorted by
    narrative text since amount isn't broken out as its own column in the
    schema (it's baked into narrative_summary) -- sorted by date instead,
    most recent first, which is a reasonable proxy for relevance in a
    snapshot report."""
    if len(investment_scope) == 0:
        return None
    top = investment_scope.sort_values("event_date", ascending=False).head(limit)
    header = [Paragraph(h, CELL_HEADER_STYLE) for h in ["Date", "Financier", "Country", "Sector", "Project"]]
    rows = [header]
    for _, ev in top.iterrows():
        rows.append([
            Paragraph(str(ev.get("event_date", ""))[:10], CELL_STYLE),
            Paragraph(str(ev.get("source", "")), CELL_STYLE),
            Paragraph(str(ev.get("country", "")), CELL_STYLE),
            Paragraph(str(ev.get("event_subtype", "")).title(), CELL_STYLE),
            Paragraph(str(ev.get("narrative_summary", ""))[:130], CELL_STYLE),
        ])
    table = Table(rows, colWidths=[0.7 * inch, 0.6 * inch, 0.9 * inch, 1.1 * inch, 2.8 * inch], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAGE_BG, PANEL]),
    ]))
    return table


def _scorecard_badges_table(scorecard: dict | None) -> Table | None:
    """Renders the decomposed 0-10 risk scorecard (Overall/Security/
    Political Stability/Economic) as color-coded badges -- the same
    severity palette used everywhere else on this dashboard/report, so a
    reader gets the "how bad is this" read without parsing a paragraph
    first. Returns None if no scorecard is cached for this country."""
    if not scorecard:
        return None
    scores = scorecard["scores"]
    badges = [
        ("Overall", scorecard["overall_risk"]),
        ("Security", scores["security_risk"]),
        ("Political Stability", scores["political_stability_risk"]),
        ("Economic", scores["economic_risk"]),
    ]
    header = [Paragraph(label, CELL_HEADER_STYLE) for label, _ in badges]
    values = []
    for _label, val in badges:
        style = ParagraphStyle(
            "ScoreVal", parent=CELL_STYLE, textColor=_severity_color(val),
            fontName="Helvetica-Bold", fontSize=13, alignment=1,
        )
        values.append(Paragraph(f"{val:.1f}", style))
    table = Table([header, values], colWidths=[1.7 * inch] * 4)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), TEXT_PRIMARY),
        ("BACKGROUND", (0, 1), (-1, 1), PANEL),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
    ]))
    return table


def _executive_summary_flowables(
    scorecard: dict | None, assessment: dict | None,
    conflict_scope: pd.DataFrame, econ_scope: pd.DataFrame, investment_scope: pd.DataFrame,
) -> list:
    """A 3-5 sentence synthesis at the top of the brief -- the "read this
    first" paragraph an institutional readahead (portfolio memo, sovereign
    risk note) leads with, rather than making the reader assemble the
    picture themselves from tables. Prefers the AI-synthesized trend
    summary + top risk flag when a cached assessment exists; falls back to
    a plain data-driven summary (event/investment counts) when it doesn't,
    so every brief gets SOME framing sentence rather than jumping straight
    into raw tables."""
    flowables = [Paragraph("Executive Summary", SECTION_STYLE)]
    if assessment:
        analysis = assessment["analysis"]
        # executive_summary is the up-to-3-paragraph synthesis (Chris: read
        # like asking Claude/ChatGPT to "summarize this PDF in 3 paragraphs
        # covering key takeaways, opportunities, and risk"). Falls back to
        # the older trend_summary field for the countries whose cached
        # assessment predates this field, so their brief still gets SOME
        # framing rather than an empty section.
        summary_text = analysis.get("executive_summary") or analysis.get("trend_summary", "")
        for para in summary_text.split("\n\n"):
            if para.strip():
                flowables.append(Paragraph(para.strip(), BODY_STYLE))
                flowables.append(Spacer(1, 4))
        if not analysis.get("executive_summary") and analysis.get("risk_flags"):
            flowables.append(Paragraph(f"Most notable risk flag: {analysis['risk_flags'][0]}", BODY_STYLE))
    else:
        n_conflict, n_econ, n_invest = len(conflict_scope), len(econ_scope), len(investment_scope)
        flowables.append(Paragraph(
            f"This scope has {n_conflict:,} conflict/security event(s), {n_econ:,} macroeconomic "
            f"indicator reading(s), and {n_invest:,} investment/development-finance record(s) on file "
            f"in the current dataset. No AI-synthesized pattern analysis has been generated for this "
            f"scope yet -- see the tables below for the underlying data.",
            BODY_STYLE,
        ))
    if scorecard:
        flowables.append(Paragraph(
            f"Overall risk score: {scorecard['overall_risk']:.1f}/10 "
            f"({b.severity_label(scorecard['overall_risk'])}).",
            BODY_STYLE,
        ))
    flowables.append(Spacer(1, 8))
    return flowables


def _bullet_text(item: str) -> str:
    """Strips a leading "- "/bullet the model sometimes writes inside
    bullet-array items -- the PDF prepends its own bullet glyph, so
    without this the rendered line reads "• - ..."."""
    return item.strip().removeprefix("- ").removeprefix("• ").strip()


def _analysis_flowables(assessment: dict | None) -> list:
    """Renders the cross-cutting parts of the cached AI pattern-analysis
    (see scripts/analysis/reasoning_agent.py) that don't belong to one
    specific section -- notable relationships spanning categories, risk
    flags, and data caveats. The per-dimension narrative paragraphs
    (security/political-stability/economic/investment analysis) are
    rendered inline within their own sections instead (see _build_pdf) --
    BTI-style, a score paired with its explanation, not a separate wall of
    text at the end. Returns an empty list when no assessment is cached."""
    if not assessment:
        return []
    analysis = assessment["analysis"]
    flowables = []
    # Investment Opportunities leads this closing block -- the World Bank
    # Compact-with-Africa prospectus Chris supplied as a reference is
    # organized around sector-specific OPPORTUNITY blocks, not just risk;
    # his product goal is "identifying biggest opportunities and risks for
    # holistic investment," so upside framing gets equal billing with the
    # risk flags rather than the report reading as risk-only.
    if analysis.get("investment_opportunities"):
        flowables.append(Paragraph("Investment Opportunities", SECTION_STYLE))
        for item in analysis["investment_opportunities"]:
            flowables.append(Paragraph(f"&bull; {_bullet_text(item)}", BODY_STYLE))
    flowables.extend([
        Paragraph("Notable Relationships & Risk Flags", SECTION_STYLE),
        Paragraph(
            f"Generated {assessment['generated_at'][:10]}. Preliminary synthesis -- "
            f"not an investment recommendation or forecast.",
            DISCLAIMER_STYLE,
        ),
    ])
    if analysis.get("key_relationships"):
        flowables.append(Spacer(1, 4))
        flowables.append(Paragraph("<b>Notable relationships:</b>", BODY_STYLE))
        for item in analysis["key_relationships"]:
            flowables.append(Paragraph(f"&bull; {_bullet_text(item)}", BODY_STYLE))
    if analysis.get("risk_flags"):
        flowables.append(Spacer(1, 4))
        flowables.append(Paragraph("<b>Risk flags:</b>", BODY_STYLE))
        for item in analysis["risk_flags"]:
            flowables.append(Paragraph(f"&bull; {_bullet_text(item)}", BODY_STYLE))
    if analysis.get("data_caveats"):
        flowables.append(Spacer(1, 4))
        flowables.append(Paragraph(f"Coverage note: {analysis['data_caveats']}", DISCLAIMER_STYLE))
    return flowables


def _footer_flowables(has_ai_analysis: bool = False, sources_used: list[str] | None = None) -> list:
    generated = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")
    narrative_note = (
        "Includes Claude-generated analytical narrative sections, grounded strictly in the ingested "
        "event data (see the section text and Notes above for scope and caveats)."
        if has_ai_analysis else
        "Analytical narrative and investment recommendations are added once upstream source "
        "coverage and analytical review are complete for this scope."
    )
    # Source list derived from what's actually in THIS report's scope, not a
    # hardcoded roster of everything the platform has ever ingested -- the
    # report-QA reviewer flagged (correctly) that citing e.g. Bellingcat in
    # a report containing zero Bellingcat events is a fabricated attribution.
    source_note = f"open-source event data ({', '.join(sources_used)})" if sources_used else "open-source event data"
    return [
        Spacer(1, 16),
        HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=6),
        Paragraph(
            f"Frontier Mercator Group — Intelligence for the Frontier. "
            f"Generated {generated}. Statistical snapshot derived from {source_note}. "
            f"{narrative_note} Distribution restricted to authorized recipients.",
            DISCLAIMER_STYLE,
        ),
    ]


# Chicago-style (notes-bibliography) citations for every data source that
# can appear in a report, keyed by the `source` value in the normalized
# schema. Endnotes rather than footnotes -- these are short, data-dense
# pages where per-page footnotes would clutter the layout; a single Notes
# section at the end is the cleaner convention for a portfolio/synopsis
# report. {date} is the report's generation date (Chicago requires an
# accessed date for online datasets).
SOURCE_CITATIONS = {
    "ACLED": 'Armed Conflict Location & Event Data Project (ACLED), "ACLED Curated Data," accessed {date}, https://acleddata.com.',
    "GDELT": 'The GDELT Project, "GDELT 2.0 Event Database," accessed {date}, https://www.gdeltproject.org.',
    "WorldBank": 'World Bank, "World Development Indicators," accessed {date}, https://data.worldbank.org.',
    "IMF": 'International Monetary Fund, "World Economic Outlook Database," accessed {date}, https://www.imf.org/en/Publications/WEO.',
    "AidData": 'AidData, "Global Chinese Development Finance Dataset," William & Mary, accessed {date}, https://www.aiddata.org.',
    "DFC": 'U.S. International Development Finance Corporation, "DFC Active Projects," accessed {date}, https://www.dfc.gov/our-impact/transaction-data.',
    "WorldBankPPI": 'World Bank, "Private Participation in Infrastructure (PPI) Project Database," accessed {date}, https://ppi.worldbank.org.',
    "UNOSAT": 'United Nations Satellite Centre (UNOSAT), "UNOSAT Maps and Analysis," accessed {date}, https://unosat.org.',
    "Bellingcat": 'Bellingcat, investigative reporting, accessed {date}, https://www.bellingcat.com.',
    "Infobae": 'Infobae, news reporting, accessed {date}, https://www.infobae.com.',
    "JeuneAfrique": 'Jeune Afrique, news reporting, accessed {date}, https://www.jeuneafrique.com.',
    "The New York Times": 'The New York Times, news reporting, accessed {date}, https://www.nytimes.com.',
    "The Wall Street Journal": 'The Wall Street Journal, news reporting, accessed {date}, https://www.wsj.com.',
}

_AI_SYNTHESIS_CITATION = (
    'Analytical narrative sections generated by Anthropic Claude from the ingested event data '
    'listed above, reviewed under Frontier Mercator Group editorial standards; generated {date}.'
)


def _collect_citations(scope: pd.DataFrame, has_ai_analysis: bool) -> list[str]:
    """Numbered Chicago-style endnote strings for exactly the sources that
    actually appear in this report's scope (not a boilerplate list of every
    source the platform has) plus, when AI narrative sections are present,
    a methodology note attributing them."""
    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    sources_used = sorted(str(s) for s in scope["source"].dropna().unique())
    citations = [
        SOURCE_CITATIONS[source].format(date=date_str)
        for source in sources_used if source in SOURCE_CITATIONS
    ]
    if has_ai_analysis:
        citations.append(_AI_SYNTHESIS_CITATION.format(date=date_str))
    return citations


def _endnote_flowables(citations: list[str]) -> list:
    """Renders the numbered Notes (endnotes) section. Returns an empty
    list if there's nothing to cite (e.g. an empty scope)."""
    if not citations:
        return []
    flowables = [Paragraph("Notes", SECTION_STYLE)]
    for i, citation in enumerate(citations, start=1):
        flowables.append(Paragraph(f"{i}. {citation}", DISCLAIMER_STYLE))
    return flowables


def _build_pdf(
    title: str, subtitle: str, scope: pd.DataFrame,
    assessment: dict | None = None, scorecard: dict | None = None,
) -> bytes:
    """`scope` is the full merged multi-source dataset already filtered to a
    country or region -- split here into conflict events (for the severity
    summary/table) and economic indicators (for the macro snapshot).
    `assessment` is an optional cached AI pattern-analysis dict and
    `scorecard` an optional cached risk scorecard (both country briefs
    only -- see scripts/analysis/reasoning_agent.py and
    scripts/analytics/risk_scorecard.py). Leads with an Executive Summary
    and the risk-score badges, institutional-readahead style, rather than
    opening straight into raw tables."""
    conflict_scope = scope[scope["event_category"].isin(b.CONFLICT_CATEGORIES)]
    econ_scope = scope[scope["event_category"] == b.ECON_CATEGORY]
    demo_scope = scope[scope["event_category"] == b.DEMO_CATEGORY]
    investment_scope = scope[scope["event_category"] == "investment"]

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
    )

    story = _header_flowables(title, subtitle)
    story.extend(_executive_summary_flowables(scorecard, assessment, conflict_scope, econ_scope, investment_scope))

    scorecard_table = _scorecard_badges_table(scorecard)
    if scorecard_table is not None:
        story.append(Paragraph("Risk Scorecard", SECTION_STYLE))
        story.append(scorecard_table)
        # Scale/methodology note -- the report-QA reviewer flagged that a
        # low Political Stability number alongside "tense political
        # environment" narrative reads as contradictory unless the reader
        # is told higher = MORE risk and the sub-scores measure different
        # things (frequency-based vs severity-based vs threshold-based).
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            "Scale: 0–10, higher = greater risk. Sub-scores are computed deterministically from "
            "ingested data, each on its own basis: Security from conflict-event frequency and "
            "severity (trailing 12 months); Political Stability from protest/civil-unrest and "
            "political-violence event frequency (trailing 12 months); Economic from the latest "
            "inflation, current-account, debt, and GDP-growth figures against published-threshold "
            "heuristics. A low score on one dimension can legitimately coexist with concerning "
            "recent narrative signal on another.",
            DISCLAIMER_STYLE,
        ))
        story.append(Spacer(1, 8))

    analysis = assessment["analysis"] if assessment else {}

    summary_table, date_range = _summary_table(conflict_scope)
    story.append(Paragraph("Political & Security Landscape", SECTION_STYLE))
    if date_range:
        story.append(Paragraph(f"<b>Reporting period:</b> {date_range}", BODY_STYLE))
        story.append(Spacer(1, 6))
    story.append(summary_table)
    # BTI-style pairing: the quantitative snapshot above, then a written
    # paragraph explaining what specifically drives it -- Chris's reference
    # example (Bertelsmann Transformation Index) pairs every numeric score
    # with plain-language analysis rather than leaving the reader to
    # interpret a table alone.
    if analysis.get("security_analysis"):
        story.append(Spacer(1, 6))
        story.append(Paragraph(analysis["security_analysis"], BODY_STYLE))
    if analysis.get("political_stability_analysis"):
        story.append(Spacer(1, 6))
        story.append(Paragraph(analysis["political_stability_analysis"], BODY_STYLE))

    macro_table = _macro_snapshot_table(econ_scope)
    if macro_table is not None:
        story.append(Paragraph("Economic Overview", SECTION_STYLE))
        story.append(macro_table)
        if analysis.get("economic_analysis"):
            story.append(Spacer(1, 6))
            story.append(Paragraph(analysis["economic_analysis"], BODY_STYLE))

    demo_table = _demographic_snapshot_table(demo_scope)
    if demo_table is not None:
        story.append(Paragraph("Demographic & Development Context", SECTION_STYLE))
        story.append(demo_table)
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "Population, age structure, and development indicators (World Bank) — economic-development "
            "backdrop for the security and macro trends above, not investment data in its own right. "
            "Trend reflects the change between the earliest and latest available reading for each series.",
            DISCLAIMER_STYLE,
        ))

    investment_table = _investment_table(investment_scope)
    if investment_table is not None:
        story.append(Paragraph("Notable Development Finance Activity", SECTION_STYLE))
        story.append(investment_table)
        if analysis.get("investment_analysis"):
            story.append(Spacer(1, 6))
            story.append(Paragraph(analysis["investment_analysis"], BODY_STYLE))

    story.append(Paragraph("Highest-Severity Events", SECTION_STYLE))
    if len(conflict_scope) > 0:
        story.append(_events_table(conflict_scope))
    else:
        story.append(Paragraph("No conflict/security events recorded for this scope in the current dataset.", BODY_STYLE))

    story.extend(_analysis_flowables(assessment))
    story.extend(_endnote_flowables(_collect_citations(scope, has_ai_analysis=assessment is not None)))
    sources_used = sorted(str(s) for s in scope["source"].dropna().unique())
    story.extend(_footer_flowables(has_ai_analysis=assessment is not None, sources_used=sources_used))

    doc.build(story, onFirstPage=_paint_dark_background, onLaterPages=_paint_dark_background)
    return buffer.getvalue()


def generate_country_brief(df: pd.DataFrame, country: str) -> bytes:
    """Generates a Country Intelligence Brief PDF for a single country, returned as bytes."""
    scope = df[df["country"] == country]
    title = f"{country} — Country Intelligence Brief"
    subtitle = "Frontier Mercator Group | Emerging Market Intelligence"
    assessment = _load_cached_assessment(country)
    scorecard = _load_scorecard(country)
    return _build_pdf(title, subtitle, scope, assessment=assessment, scorecard=scorecard)


def generate_regional_brief(df: pd.DataFrame, region: str) -> bytes:
    """Generates a Regional Executive Summary PDF covering all countries in a region."""
    scope = df[df["region"] == region]
    title = f"{region} — Regional Executive Summary"
    subtitle = "Frontier Mercator Group | Emerging Market Intelligence"
    return _build_pdf(title, subtitle, scope)


def generate_custom_report(assessment: dict) -> bytes:
    """Renders a Custom Analysis PDF from a cached cross-cutting assessment
    (see scripts/analysis/reasoning_agent.py's generate_cross_cutting_assessment
    + save_cross_cutting_assessment) -- an ad-hoc, non-country/region-scoped
    question like "critical minerals VC investment opportunities in West
    Africa resulting from a recent coup or resource discovery", answered by
    semantic retrieval across the full dataset rather than a fixed filter.

    Unlike generate_country_brief/generate_regional_brief, this doesn't take
    a live DataFrame scope -- everything it renders comes from the already-
    generated cached assessment, so no AI API call happens at PDF-render
    time (same reasoning as _load_cached_assessment: keep API keys and live
    calls out of the deployed Streamlit process entirely)."""
    analysis = assessment["analysis"]

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
    )

    story = _header_flowables(
        "Custom Analysis", "Frontier Mercator Group | Emerging Market Intelligence"
    )
    story.append(Paragraph(f"<b>Question:</b> {assessment['query']}", BODY_STYLE))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Generated {assessment['generated_at'][:10]} from {assessment['events_retrieved']:,} "
        f"semantically retrieved events. Preliminary statistical synthesis, not an investment "
        f"recommendation.", DISCLAIMER_STYLE,
    ))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Answer", SECTION_STYLE))
    story.append(Paragraph(analysis.get("answer", ""), BODY_STYLE))

    if analysis.get("countries_involved"):
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            f"<b>Countries involved:</b> {', '.join(analysis['countries_involved'])}", BODY_STYLE
        ))

    if analysis.get("supporting_evidence"):
        story.append(Spacer(1, 8))
        story.append(Paragraph("Supporting Evidence", SECTION_STYLE))
        for item in analysis["supporting_evidence"]:
            story.append(Paragraph(f"&bull; {_bullet_text(item)}", BODY_STYLE))

    if analysis.get("data_caveats"):
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"Data caveats: {analysis['data_caveats']}", DISCLAIMER_STYLE))

    story.extend(_footer_flowables(has_ai_analysis=True))

    doc.build(story, onFirstPage=_paint_dark_background, onLaterPages=_paint_dark_background)
    return buffer.getvalue()


def generate_regional_outlook_pdf(outlook: dict) -> bytes:
    """Renders the Regional Economic Outlook (scripts/analytics/
    regional_outlook.py output) as a branded executive PDF -- Chris's
    big-picture macro/regional product: narrative-first, with the
    quantitative anchors rendered as crisp data-point bullets under each
    opportunity. Like generate_custom_report, this renders entirely from
    the cached artifact -- no AI/API call happens at PDF-render time."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
    )

    story = _header_flowables(
        "Regional Economic Outlook",
        "Frontier Mercator Group | Emerging Market Intelligence",
    )
    story.append(Paragraph(
        f"Generated {outlook.get('generated_at', '')[:10]}. Executive synthesis of "
        f"Frontier Mercator's multi-source intelligence -- macroeconomic indicators, "
        f"development-finance flows, security reporting, commodity and shipping data -- "
        f"by region. Research product, not investment advice.",
        DISCLAIMER_STYLE,
    ))
    story.append(Spacer(1, 10))

    region_heading = ParagraphStyle(
        "OutlookRegion", parent=SECTION_STYLE, fontSize=15, spaceBefore=18,
        textColor=colors.HexColor(b.GOLD),
    )
    opportunity_heading = ParagraphStyle(
        "OutlookOpportunity", parent=SECTION_STYLE, fontSize=11, spaceBefore=8, spaceAfter=3,
    )

    for i, (region, section) in enumerate(sorted(outlook.get("regions", {}).items())):
        if i > 0:
            story.append(Spacer(1, 6))
        story.append(Paragraph(region, region_heading))

        for para in (section.get("regional_narrative") or "").split("\n\n"):
            if para.strip():
                story.append(Paragraph(para.strip(), BODY_STYLE))
                story.append(Spacer(1, 5))

        for opp in section.get("opportunities", []):
            story.append(Paragraph(f"Opportunity: {opp.get('title', '')}", opportunity_heading))
            story.append(Paragraph(opp.get("narrative", ""), BODY_STYLE))
            story.append(Spacer(1, 3))
            for point in opp.get("key_data_points", []):
                story.append(Paragraph(f"&bull; {_bullet_text(str(point))}", BODY_STYLE))
            story.append(Spacer(1, 5))

        if section.get("risk_outlook"):
            story.append(Paragraph("Risk Outlook", opportunity_heading))
            story.append(Paragraph(section["risk_outlook"], BODY_STYLE))

    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "Prepared by Frontier Mercator Group from the firm's multi-source intelligence platform. "
        "All figures as attributed in text (World Bank, IMF, UNCTAD, AidData, DFC, ACLED, and "
        "open reporting). This document describes regional dynamics and where opportunities and "
        "risks sit; it does not constitute investment advice or a recommendation to buy or sell "
        "any security.",
        DISCLAIMER_STYLE,
    ))

    doc.build(story, onFirstPage=_paint_dark_background, onLaterPages=_paint_dark_background)
    return buffer.getvalue()

def generate_single_region_outlook_pdf(region: str, section: dict, generated_at: str,
                                        df: pd.DataFrame) -> bytes:
    """Standalone Regional Economic Outlook for ONE region. Visuals are
    MODEL-NOMINATED (see regional_outlook.py: at most a few charts, only
    where one lands the analysis's punchiest point -- no quota) and
    rendered to publication-grade anatomy by outlook_charts.py from real
    platform data, placed with the section each belongs to. Opportunities
    carry a quarter-stamped timing case ("why now") and named, verified
    instruments ("how to express it"). Renders entirely from cached
    artifacts + the already-loaded dataset -- no API call at render time."""
    from scripts.reports.outlook_charts import render_nominated_visual

    region_scope = df[df["region"] == region]

    def _visuals_for(section_name: str) -> list:
        rendered = []
        for visual in section.get("visuals", []) or []:
            if not isinstance(visual, dict) or visual.get("section") != section_name:
                continue
            drawing = render_nominated_visual(visual, region_scope)
            if drawing is not None:
                rendered.append(drawing)
        return rendered

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
    )

    story = _header_flowables(
        f"{region} — Economic Outlook",
        "Frontier Mercator Group | Emerging Market Intelligence",
    )
    story.append(Paragraph(
        f"Generated {generated_at[:10]}. Executive synthesis of Frontier Mercator's "
        f"multi-source intelligence for {region}. Research product, not investment advice.",
        DISCLAIMER_STYLE,
    ))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Regional Assessment", SECTION_STYLE))
    for para in (section.get("regional_narrative") or "").split(chr(10) * 2):
        if para.strip():
            story.append(Paragraph(para.strip(), BODY_STYLE))
            story.append(Spacer(1, 5))
    for drawing in _visuals_for("narrative"):
        story.append(Spacer(1, 10))
        story.append(drawing)
        story.append(Spacer(1, 12))

    opportunity_heading = ParagraphStyle(
        "SingleOutlookOpp", parent=SECTION_STYLE, fontSize=11, spaceBefore=8, spaceAfter=3,
        textColor=colors.HexColor(b.GOLD),
    )
    why_now_style = ParagraphStyle(
        "OutlookWhyNow", parent=BODY_STYLE, leftIndent=10,
    )
    expression_style = ParagraphStyle(
        "OutlookExpression", parent=BODY_STYLE, leftIndent=10, textColor=TEXT_MUTED,
    )
    if section.get("opportunities"):
        story.append(Paragraph("Opportunities", SECTION_STYLE))
        for opp in section["opportunities"]:
            if not isinstance(opp, dict):
                continue
            story.append(Paragraph(opp.get("title", ""), opportunity_heading))
            story.append(Paragraph(opp.get("narrative", ""), BODY_STYLE))
            story.append(Spacer(1, 3))
            for point in opp.get("key_data_points", []):
                story.append(Paragraph(f"&bull; {_bullet_text(str(point))}", BODY_STYLE))
            if opp.get("timing_case"):
                story.append(Spacer(1, 3))
                story.append(Paragraph(f"<b>Why now:</b> {opp['timing_case']}", why_now_style))
            expression = [e for e in opp.get("expression", []) if isinstance(e, dict)]
            if expression:
                parts = "; ".join(
                    f"<b>{e.get('ticker', '')}</b> ({e.get('name', '')}) — {e.get('note', '')}"
                    for e in expression
                )
                story.append(Spacer(1, 3))
                story.append(Paragraph(f"<b>How to express it:</b> {parts}", expression_style))
            story.append(Spacer(1, 7))
    for drawing in _visuals_for("opportunities"):
        story.append(Spacer(1, 10))
        story.append(drawing)
        story.append(Spacer(1, 12))

    if section.get("risk_outlook"):
        story.append(Paragraph("Risk Outlook", SECTION_STYLE))
        story.append(Paragraph(section["risk_outlook"], BODY_STYLE))
        for drawing in _visuals_for("risk"):
            story.append(Spacer(1, 10))
            story.append(drawing)
            story.append(Spacer(1, 12))

    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "Prepared by Frontier Mercator Group from the firm's multi-source intelligence "
        "platform. All figures as attributed (World Bank, IMF, UNCTAD, AidData, DFC, ACLED, "
        "and open reporting). Named instruments describe how a view could be expressed and "
        "are not recommendations to buy or sell any security.",
        DISCLAIMER_STYLE,
    ))

    doc.build(story, onFirstPage=_paint_dark_background, onLaterPages=_paint_dark_background)
    return buffer.getvalue()
