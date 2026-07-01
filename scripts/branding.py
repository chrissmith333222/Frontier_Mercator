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

# Brand core -- strictly dark blue / gray / white now (Chris's 2026-07-02
# direction: no light/"baby" blue anywhere in the chrome). ACCENT used to be
# a brightened periwinkle (#6E8FC7); replaced with a cool light gray so
# interactive/highlight states read as gray, not blue. Severity colors
# (below) are intentionally exempt -- those are data encoding, not chrome,
# and stay fully saturated on purpose (see severity_color).
NAVY = "#091E42"          # deep brand navy — used as a strong accent/header band
SLATE = "#505F79"         # brand secondary (gray)
ACCENT = "#9AA5B4"        # light gray — interactive/active states, no blue tint

# Text
TEXT_PRIMARY = "#FFFFFF"
TEXT_MUTED = "#9AA5B4"

# Severity scale — brightened for contrast against dark backgrounds
CRITICAL = "#FF5C4D"
HIGH = "#FFB03B"
MEDIUM = "#9B8CFF"
LOW = "#2ED8A0"

# event_category groupings, shared by dashboard.py and pdf_report.py so a
# merged multi-source dataset (conflict + economic + news signal all in one
# dataframe) gets split the same way everywhere.
CONFLICT_CATEGORIES = [
    "conflict", "protest_civil_unrest", "political_violence_targeting_civilians",
    "explosion_remote_violence",
]
ECON_CATEGORY = "economic_indicator"
NEWS_CATEGORIES = ["strategic_development", "other", "humanitarian"]

# Type colors for the unified multi-category map -- distinct saturated hues
# per category (conflict/economic/news), independent of the severity scale.
# Like severity_color, these are data encoding, not chrome, so they aren't
# constrained to navy/gray/white.
TYPE_COLOR_CONFLICT = "#FF5C4D"
TYPE_COLOR_ECON = "#FFB03B"
TYPE_COLOR_NEWS = "#3DD6F5"


def type_color(category: str) -> str:
    if category in CONFLICT_CATEGORIES:
        return TYPE_COLOR_CONFLICT
    if category == ECON_CATEGORY:
        return TYPE_COLOR_ECON
    return TYPE_COLOR_NEWS


def type_label(category: str) -> str:
    if category in CONFLICT_CATEGORIES:
        return "Conflict & Security"
    if category == ECON_CATEGORY:
        return "Markets & Economy"
    return "News & Social Signal"

# Body font: Bahnschrift is Chris's pick (bundled with Windows) — listed first
# so Windows visitors get it natively. 'Barlow Semi Condensed' (loaded from
# Google Fonts in dashboard.py) is a close free lookalike for Mac/Linux/mobile
# visitors who don't have Bahnschrift installed, so the site doesn't silently
# fall back to a generic default on non-Windows machines.
FONT_STACK = "'Bahnschrift', 'Barlow Semi Condensed', 'Segoe UI', Roboto, Arial, sans-serif"

# Display font for the big "FRONTIER MERCATOR" wordmark only -- everything
# else on the site uses FONT_STACK (Bahnschrift). Chris wants sharp, angular,
# NOT rounded letterforms (Lockheed Martin wordmark as the reference point).
# 'Rajdhani' (Google Fonts, free) has hard angular cuts rather than rounded
# terminals; combined with a CSS skew transform in dashboard.py for the slant.
DISPLAY_FONT_STACK = "'Rajdhani', 'Bahnschrift', 'Segoe UI', Arial, sans-serif"


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
