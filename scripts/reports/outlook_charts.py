"""
scripts/reports/outlook_charts.py

Publication-grade chart builders for the Regional Economic Outlook PDFs,
rebuilt 2026-07-16 after Chris rejected the reportlab stock-chart look
("middle school ish... slanted country titles crossing boundaries, no
date stamps"). The reference points are the graphics desks at The
Economist / NYT / FT, whose chart anatomy this module reproduces with
reportlab primitives (full control, no new dependencies):

  - The TITLE is the takeaway, written as a sentence ("Guinea is pulling
    away from its neighbours"), not a variable name.
  - A subtitle carries the measure, unit, and period ("Real GDP growth,
    latest reading or 2026 projection, %").
  - Country comparisons are HORIZONTAL bars: labels sit left of the bar
    on the same baseline -- nothing is ever rotated -- and the value is
    printed at the end of each bar, so no y-axis is needed at all.
  - One highlighted series/bar in the brand gold carries the story; the
    rest stay muted slate. A short accent rule sits above the title.
  - A source-and-date line anchors the bottom ("Source: IMF/World Bank
    via Frontier Mercator platform · data as of Jul 2026").
  - No chart junk: no boxes around the plot, no gridline forests, no
    legends where direct labeling works.

Charts are chosen by the ANALYSIS, not by quota -- the outlook generator
(scripts/analytics/regional_outlook.py) has the model nominate at most a
few visuals that genuinely land its punchiest points, each tied to a
section of the report; this module renders those nominations from real
platform data (never from model-supplied numbers) and silently skips any
the data can't support.
"""

import re
from datetime import datetime, timezone

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.graphics.shapes import Drawing, String, Rect, Line, PolyLine, Circle

from scripts import branding as b

PAGE_BG = colors.HexColor(b.BG)
PANEL_ALT = colors.HexColor(b.PANEL_ALT)
BORDER = colors.HexColor(b.BORDER)
TEXT_PRIMARY = colors.HexColor(b.TEXT_PRIMARY)
TEXT_MUTED = colors.HexColor(b.TEXT_MUTED)
GOLD = colors.HexColor(b.GOLD)
SLATE = colors.HexColor(b.SLATE)

CHART_WIDTH = 6.6 * inch  # centered within a 7.1in text column

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"


def _parse_indicator_value(summary: str) -> float | None:
    match = re.search(r":\s*(-?[\d.]+)", str(summary))
    try:
        return float(match.group(1)) if match else None
    except ValueError:
        return None


def _header(drawing: Drawing, headline: str, subtitle: str, width: float, top: float) -> float:
    """Accent rule + takeaway headline + measure/unit/period subtitle.
    Returns the y coordinate below the header block."""
    drawing.add(Rect(0, top - 3, 24, 3, fillColor=GOLD, strokeColor=None))
    y = top - 17
    drawing.add(String(0, y, headline, fontName=_FONT_BOLD, fontSize=10.5,
                        fillColor=TEXT_PRIMARY))
    y -= 12
    drawing.add(String(0, y, subtitle, fontName=_FONT, fontSize=7.5, fillColor=TEXT_MUTED))
    return y - 8


def _source_line(drawing: Drawing, source: str):
    stamp = datetime.now(timezone.utc).strftime("%b %Y")
    drawing.add(String(0, 2, f"Source: {source} · data as of {stamp}",
                        fontName=_FONT, fontSize=6.5, fillColor=TEXT_MUTED))


def build_country_bar(headline: str, subtitle: str, items: list[tuple[str, float]],
                       source: str, unit_suffix: str = "%",
                       highlight: str | None = None) -> Drawing:
    """Economist-anatomy horizontal bar chart: one row per country, label
    left of the bar, value printed at the bar's end, highlighted story-bar
    in gold, everything horizontal."""
    items = items[:12]
    row_height = 15
    header_height = 40
    footer_height = 12
    height = header_height + len(items) * row_height + footer_height
    drawing = Drawing(CHART_WIDTH, height)
    drawing.hAlign = "CENTER"

    plot_top = _header(drawing, headline, subtitle, CHART_WIDTH, height)

    label_width = 108
    value_gap = 4
    max_abs = max(abs(v) for _l, v in items) or 1.0
    # Bars start after the label column; negative values draw leftward from
    # a shifted baseline so mixed-sign series (current account) stay honest.
    has_negative = any(v < 0 for _l, v in items)
    plot_left = label_width + 8
    plot_width = CHART_WIDTH - plot_left - 46
    zero_x = plot_left + (plot_width * (abs(min(0.0, min(v for _l, v in items))) / (
        max_abs + abs(min(0.0, min(v for _l, v in items))))) if has_negative else 0)
    scale = (plot_width - (zero_x - plot_left)) / max_abs if not has_negative else (
        plot_width / (max_abs + abs(min(0.0, min(v for _l, v in items)))))

    y = plot_top - row_height
    for label, value in items:
        bar_color = GOLD if (highlight and label == highlight) else SLATE
        bar_len = abs(value) * scale
        x0 = zero_x if value >= 0 else zero_x - bar_len
        drawing.add(String(label_width, y + 2.5, label, fontName=_FONT, fontSize=7.5,
                            fillColor=TEXT_PRIMARY, textAnchor="end"))
        drawing.add(Rect(x0, y, max(bar_len, 0.75), row_height - 5.5,
                          fillColor=bar_color, strokeColor=None))
        value_text = f"{value:+.1f}{unit_suffix}" if has_negative else f"{value:.1f}{unit_suffix}"
        value_x = (zero_x + bar_len + value_gap) if value >= 0 else (zero_x + value_gap)
        drawing.add(String(value_x, y + 2.5, value_text, fontName=_FONT_BOLD, fontSize=7,
                            fillColor=TEXT_PRIMARY))
        y -= row_height
    if has_negative:
        drawing.add(Line(zero_x, y + row_height - 3, zero_x, plot_top - 3,
                          strokeColor=BORDER, strokeWidth=0.6))

    _source_line(drawing, source)
    return drawing


def _fmt_value(v: float) -> str:
    """Adaptive precision: 5,753 for big numbers, 6.24 for a copper-style
    per-pound price -- a bare rounded "6" loses the story."""
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"


def build_trend_line(headline: str, subtitle: str, points: list[tuple[str, float]],
                      source: str) -> Drawing:
    """Editorial time-series line: sparse horizontal date labels (first /
    middle / last -- never rotated), endpoint emphasized with a dot and a
    printed value, muted baseline gridlines only."""
    height = 130
    drawing = Drawing(CHART_WIDTH, height)
    drawing.hAlign = "CENTER"

    plot_top = _header(drawing, headline, subtitle, CHART_WIDTH, height)
    plot_bottom = 22
    plot_left, plot_right = 6, CHART_WIDTH - 46
    plot_h = plot_top - plot_bottom - 6

    values = [v for _l, v in points]
    vmin, vmax = min(values), max(values)
    span = (vmax - vmin) or 1.0
    vmin_padded = vmin - span * 0.08
    span_padded = span * 1.16

    def xy(i: int, v: float):
        x = plot_left + (plot_right - plot_left) * (i / max(len(points) - 1, 1))
        y = plot_bottom + plot_h * ((v - vmin_padded) / span_padded)
        return x, y

    # Two muted horizontal reference lines (min/max). Labels are skipped
    # when they'd collide with the emphasized endpoint value (caught on
    # visual review: the endpoint printing over the max label).
    _ex, end_y_probe = xy(len(points) - 1, values[-1])
    for ref in (vmin, vmax):
        _x, ry = xy(0, ref)
        drawing.add(Line(plot_left, ry, plot_right, ry, strokeColor=PANEL_ALT, strokeWidth=0.6))
        if abs(ry - end_y_probe) > 10:
            drawing.add(String(plot_right + 4, ry - 2, _fmt_value(ref), fontName=_FONT,
                                fontSize=6.5, fillColor=TEXT_MUTED))

    coords = []
    for i, (_label, value) in enumerate(points):
        coords.extend(xy(i, value))
    drawing.add(PolyLine(coords, strokeColor=GOLD, strokeWidth=1.6))

    end_x, end_y = xy(len(points) - 1, values[-1])
    drawing.add(Circle(end_x, end_y, 2.2, fillColor=GOLD, strokeColor=None))
    drawing.add(String(end_x + 5, end_y + 3, _fmt_value(values[-1]), fontName=_FONT_BOLD,
                        fontSize=7.5, fillColor=TEXT_PRIMARY))

    # Sparse, horizontal date labels: first, middle, last.
    for i in (0, len(points) // 2, len(points) - 1):
        x, _y = xy(i, values[i])
        anchor = "start" if i == 0 else ("end" if i == len(points) - 1 else "middle")
        drawing.add(String(x, plot_bottom - 10, points[i][0], fontName=_FONT, fontSize=6.5,
                            fillColor=TEXT_MUTED, textAnchor=anchor))

    _source_line(drawing, source)
    return drawing


# --- Metric registry: what the model may nominate, and how each metric is
# --- computed from the region's slice of the merged dataset. The model
# --- picks WHICH story to visualize; the numbers only ever come from here.

def _latest_by_country(region_scope: pd.DataFrame, codes: set) -> list[tuple[str, float]]:
    subset = region_scope[
        (region_scope["event_category"] == "economic_indicator")
        & (region_scope["event_subtype"].isin(codes))
    ]
    if subset.empty:
        return []
    latest = subset.sort_values("event_date").drop_duplicates("country", keep="last")
    values = []
    for _, row in latest.iterrows():
        value = _parse_indicator_value(row["narrative_summary"])
        if value is not None:
            values.append((row["country"], value))
    return sorted(values, key=lambda kv: kv[1], reverse=True)


# NOTE: a monthly-conflict-event trend metric was built and REMOVED
# (2026-07-16): the platform's event ingestion only became continuous in
# mid-2026, so a monthly count line measures the firm's own coverage
# ramp-up, not actual violence trends -- caught on visual review when the
# "trend" ran 9 -> 1,123 events/month. Do not reintroduce until there are
# 12+ months of stable ingestion to draw on.


def _commodity_series(commodity: str, months: int = 24) -> list[tuple[str, float]]:
    """Monthly closes for one tracked commodity from the cached price file
    -- complete, evenly-spaced coverage (unlike event counts), so a trend
    line here is honest."""
    from scripts.lib.commodity_data import load_commodity_prices
    prices = load_commodity_prices()
    series = prices.get(commodity)
    if not series:
        return []
    tail = sorted(series)[-months:]
    if len(tail) < 6:
        return []
    labels = [pd.Timestamp(m + "-01").strftime("%b %y") for m in tail]
    return list(zip(labels, [float(series[m]) for m in tail]))


METRICS = {
    "gdp_growth": {
        "kind": "bar", "codes": {"NY.GDP.MKTP.KD.ZG", "NGDP_RPCH"},
        "subtitle": "Real GDP growth, latest reading/projection, %",
        "source": "IMF WEO / World Bank via Frontier Mercator platform", "unit": "%",
    },
    "inflation": {
        "kind": "bar", "codes": {"FP.CPI.TOTL.ZG", "PCPIPCH"},
        "subtitle": "Consumer price inflation, latest reading, %",
        "source": "IMF / World Bank via Frontier Mercator platform", "unit": "%",
    },
    "fdi_pct_gdp": {
        "kind": "bar", "codes": {"BX.KLT.DINV.WD.GD.ZS"},
        "subtitle": "Foreign direct investment, net inflows, % of GDP, latest",
        "source": "World Bank via Frontier Mercator platform", "unit": "%",
    },
    "govt_debt": {
        "kind": "bar", "codes": {"GGXWDG_NGDP"},
        "subtitle": "General government gross debt, % of GDP, latest",
        "source": "IMF WEO via Frontier Mercator platform", "unit": "%",
    },
    "current_account": {
        "kind": "bar", "codes": {"BN.CAB.XOKA.GD.ZS"},
        "subtitle": "Current account balance, % of GDP, latest",
        "source": "World Bank via Frontier Mercator platform", "unit": "%",
    },
    "commodity_trend": {
        "kind": "line",
        "subtitle": "Monthly closing price, trailing 24 months",
        "source": "Yahoo Finance futures via Frontier Mercator platform",
    },
}


def render_nominated_visual(visual: dict, region_scope: pd.DataFrame) -> Drawing | None:
    """Renders one model-nominated visual from real platform data. Returns
    None (skip silently) when the metric is unknown or the region's data
    can't support it -- a nomination is a request, not a guarantee."""
    metric = METRICS.get(str(visual.get("metric", "")))
    if metric is None:
        return None
    headline = str(visual.get("takeaway_headline", "")).strip()
    if not headline:
        return None

    if metric["kind"] == "bar":
        items = _latest_by_country(region_scope, metric["codes"])
        if len(items) < 2:
            return None
        highlight = visual.get("highlight_country")
        return build_country_bar(headline, metric["subtitle"], items, metric["source"],
                                  unit_suffix=metric["unit"],
                                  highlight=highlight if any(l == highlight for l, _v in items) else None)

    if metric["kind"] == "line":
        commodity = str(visual.get("commodity", "")).strip()
        points = _commodity_series(commodity)
        if not points:
            return None
        subtitle = f"{commodity} — {metric['subtitle']}"
        return build_trend_line(headline, subtitle, points, metric["source"])

    return None
