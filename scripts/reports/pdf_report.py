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

Current version is data-driven (quantified event/severity statistics computed
directly from normalized ACLED/GDELT records). It does NOT yet include Claude-
generated narrative analysis (investment recommendations, forecasts) — that
lands once the Parallax reasoning agent (Phase 5 of the roadmap) is built.
Until then, treat these as a statistical snapshot brief, not a full analytical
product.

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
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable,
)

from scripts import branding as b

LOGO_PATH = Path(__file__).resolve().parent.parent.parent / "Frontier_Mercator_Logo.jpg"

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
    if LOGO_PATH.exists():
        flowables.append(Image(str(LOGO_PATH), width=1.3 * inch, height=0.87 * inch))
        flowables.append(Spacer(1, 8))
    flowables.append(Paragraph(title, TITLE_STYLE))
    flowables.append(Paragraph(subtitle, SUBTITLE_STYLE))
    flowables.append(HRFlowable(width="100%", thickness=2, color=ACCENT, spaceAfter=10))
    return flowables


def _summary_table(df_scope: pd.DataFrame) -> tuple[Table, str]:
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


def _footer_flowables() -> list:
    generated = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")
    return [
        Spacer(1, 16),
        HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=6),
        Paragraph(
            f"Frontier Mercator Group — Intelligence for the Frontier. "
            f"Generated {generated}. Statistical snapshot derived from open-source event data "
            f"(ACLED, GDELT). Analytical narrative and investment recommendations are added once "
            f"upstream source coverage and analytical review are complete. Distribution restricted "
            f"to authorized recipients.",
            DISCLAIMER_STYLE,
        ),
    ]


def _build_pdf(title: str, subtitle: str, df_scope: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
    )

    story = _header_flowables(title, subtitle)

    summary_table, date_range = _summary_table(df_scope)
    if date_range:
        story.append(Paragraph(f"<b>Reporting period:</b> {date_range}", BODY_STYLE))
        story.append(Spacer(1, 6))
    story.append(summary_table)

    story.append(Paragraph("Highest-Severity Events", SECTION_STYLE))
    if len(df_scope) > 0:
        story.append(_events_table(df_scope))
    else:
        story.append(Paragraph("No events recorded for this scope in the current dataset.", BODY_STYLE))

    story.extend(_footer_flowables())

    doc.build(story, onFirstPage=_paint_dark_background, onLaterPages=_paint_dark_background)
    return buffer.getvalue()


def generate_country_brief(df: pd.DataFrame, country: str) -> bytes:
    """Generates a Country Intelligence Brief PDF for a single country, returned as bytes."""
    df_scope = df[df["country"] == country]
    title = f"{country} — Country Intelligence Brief"
    subtitle = "Frontier Mercator Group | Emerging Market Intelligence"
    return _build_pdf(title, subtitle, df_scope)


def generate_regional_brief(df: pd.DataFrame, region: str) -> bytes:
    """Generates a Regional Executive Summary PDF covering all countries in a region."""
    df_scope = df[df["region"] == region]
    title = f"{region} — Regional Executive Summary"
    subtitle = "Frontier Mercator Group | Emerging Market Intelligence"
    return _build_pdf(title, subtitle, df_scope)
