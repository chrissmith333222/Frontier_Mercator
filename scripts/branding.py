"""
scripts/branding.py

Single source of truth for Frontier Mercator Group's visual identity — color
palette, fonts — shared by the Streamlit dashboard and the PDF report
generator so both surfaces stay visually consistent. Change a color here,
not in dashboard.py or pdf_report.py directly.

Dark theme is the standard now (site + reports), per Chris's direction:
sharper, more professional, Bloomberg-terminal-adjacent. Severity colors are
brightened relative to the original light-mode palette so they stay legible
against dark backgrounds.
"""

# Base surfaces
BG = "#060B14"            # page background
PANEL = "#101A2E"         # card / table-header / panel background
PANEL_ALT = "#0B1220"     # slightly darker alternating panel (zebra rows, etc.)
BORDER = "#243252"        # hairline borders/dividers on dark surfaces

# Brand core (kept from the original identity, Chris likes these)
NAVY = "#091E42"          # deep brand navy — used as a strong accent/header band
SLATE = "#505F79"         # brand secondary
ACCENT = "#6E8FC7"        # brightened slate, used for interactive/active states

# Text
TEXT_PRIMARY = "#EDEFF4"
TEXT_MUTED = "#8A97B3"

# Severity scale — brightened for contrast against dark backgrounds
CRITICAL = "#FF5C4D"
HIGH = "#FFB03B"
MEDIUM = "#9B8CFF"
LOW = "#2ED8A0"

FONT_STACK = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"


def severity_color(score: float) -> str:
    if score >= 7:
        return CRITICAL
    if score >= 5:
        return HIGH
    if score >= 3:
        return MEDIUM
    return LOW


def severity_label(score: float) -> str:
    if score >= 7:
        return "Critical"
    if score >= 5:
        return "High"
    if score >= 3:
        return "Medium"
    return "Low"
