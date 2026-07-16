"""
scripts/reports/outlook_charts.py

Reportlab-native chart builders for the standalone Regional Economic
Outlook PDFs (Chris, 2026-07-16: each region's outlook stands alone with
"3-5 of the absolutely most relevant charts... both economic and security
data as needed. I like visual aids").

Uses reportlab.graphics.charts (already a dependency via reportlab) rather
than matplotlib/kaleido -- no new packages, and the charts inherit the
brand dark theme directly. Every chart builder degrades to "skip" when the
region lacks the underlying data, so sparse regions get fewer charts
rather than empty axes.
"""

import re

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.graphics.shapes import Drawing, String, Rect
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie

from scripts import branding as b

PAGE_BG = colors.HexColor(b.BG)
PANEL = colors.HexColor(b.PANEL)
PANEL_ALT = colors.HexColor(b.PANEL_ALT)
BORDER = colors.HexColor(b.BORDER)
TEXT_PRIMARY = colors.HexColor(b.TEXT_PRIMARY)
TEXT_MUTED = colors.HexColor(b.TEXT_MUTED)
GOLD = colors.HexColor(b.GOLD)
SLATE = colors.HexColor(b.SLATE)
CHART_SERIES = [GOLD, SLATE, colors.HexColor(b.LOW), colors.HexColor(b.HIGH),
                 colors.HexColor(b.MEDIUM), colors.HexColor(b.CRITICAL),
                 colors.HexColor(b.ACCENT)]


def _parse_indicator_value(summary: str) -> float | None:
    match = re.search(r":\s*(-?[\d.]+)", str(summary))
    try:
        return float(match.group(1)) if match else None
    except ValueError:
        return None


def _chart_title(drawing: Drawing, title: str, width: float):
    drawing.add(String(width / 2, drawing.height - 12, title, fontName="Helvetica-Bold",
                        fontSize=9, fillColor=TEXT_PRIMARY, textAnchor="middle"))


def styled_bar_chart(labels: list, values: list, title: str, color=None) -> Drawing:
    """Country-comparison bar chart in the brand dark theme."""
    width, height = 5.9 * inch, 2.3 * inch
    drawing = Drawing(width, height)
    drawing.add(Rect(0, 0, width, height, fillColor=PANEL, strokeColor=BORDER, strokeWidth=0.5))
    chart = VerticalBarChart()
    chart.x, chart.y = 35, 32
    chart.width, chart.height = width - 55, height - 62
    chart.data = [values]
    chart.categoryAxis.categoryNames = labels
    chart.bars[0].fillColor = color or GOLD
    chart.bars.strokeColor = None
    chart.valueAxis.labels.fillColor = TEXT_MUTED
    chart.valueAxis.labels.fontSize = 6.5
    chart.valueAxis.strokeColor = BORDER
    chart.valueAxis.gridStrokeColor = PANEL_ALT
    chart.valueAxis.visibleGrid = 1
    chart.categoryAxis.labels.fillColor = TEXT_MUTED
    chart.categoryAxis.labels.fontSize = 6.5
    chart.categoryAxis.labels.angle = 30
    chart.categoryAxis.labels.boxAnchor = "ne"
    chart.categoryAxis.strokeColor = BORDER
    drawing.add(chart)
    _chart_title(drawing, title, width)
    return drawing


def styled_line_chart(x_labels: list, values: list, title: str) -> Drawing:
    """Time-series line chart (e.g. monthly security events)."""
    width, height = 5.9 * inch, 2.1 * inch
    drawing = Drawing(width, height)
    drawing.add(Rect(0, 0, width, height, fillColor=PANEL, strokeColor=BORDER, strokeWidth=0.5))
    chart = HorizontalLineChart()
    chart.x, chart.y = 35, 26
    chart.width, chart.height = width - 55, height - 54
    chart.data = [values]
    chart.categoryAxis.categoryNames = x_labels
    chart.lines[0].strokeColor = GOLD
    chart.lines[0].strokeWidth = 1.6
    chart.valueAxis.labels.fillColor = TEXT_MUTED
    chart.valueAxis.labels.fontSize = 6.5
    chart.valueAxis.strokeColor = BORDER
    chart.valueAxis.gridStrokeColor = PANEL_ALT
    chart.valueAxis.visibleGrid = 1
    chart.valueAxis.valueMin = 0
    chart.categoryAxis.labels.fillColor = TEXT_MUTED
    chart.categoryAxis.labels.fontSize = 6
    chart.categoryAxis.labels.angle = 30
    chart.categoryAxis.labels.boxAnchor = "ne"
    chart.categoryAxis.strokeColor = BORDER
    drawing.add(chart)
    _chart_title(drawing, title, width)
    return drawing


def styled_pie_chart(labels: list, values: list, title: str) -> Drawing:
    """Composition pie (e.g. development-finance mix by financier)."""
    width, height = 5.9 * inch, 2.3 * inch
    drawing = Drawing(width, height)
    drawing.add(Rect(0, 0, width, height, fillColor=PANEL, strokeColor=BORDER, strokeWidth=0.5))
    pie = Pie()
    pie.x, pie.y = 60, 22
    pie.width = pie.height = height - 58
    pie.data = values
    pie.slices.strokeColor = PAGE_BG
    pie.slices.strokeWidth = 0.75
    for i in range(len(values)):
        pie.slices[i].fillColor = CHART_SERIES[i % len(CHART_SERIES)]
    drawing.add(pie)
    total = sum(values) or 1
    legend_y = height - 34
    for i, (label, value) in enumerate(zip(labels, values)):
        swatch_x = width * 0.48
        drawing.add(Rect(swatch_x, legend_y - 2, 7, 7,
                          fillColor=CHART_SERIES[i % len(CHART_SERIES)], strokeColor=None))
        drawing.add(String(swatch_x + 11, legend_y - 1, f"{label}  ({value / total * 100:.0f}%)",
                            fontName="Helvetica", fontSize=7, fillColor=TEXT_PRIMARY))
        legend_y -= 13
    _chart_title(drawing, title, width)
    return drawing


def region_chart_flowables(region_scope: pd.DataFrame) -> list:
    """The 3-5 most relevant charts for one region, built deterministically
    from the merged dataset: GDP growth + inflation by country (economic),
    monthly security-event trend (security), development-finance mix by
    financier (investment). Returns them in that order; callers interleave
    them with the narrative sections they illustrate."""
    flowables = []

    def _latest_by_country(codes: set) -> dict:
        subset = region_scope[
            (region_scope["event_category"] == "economic_indicator")
            & (region_scope["event_subtype"].isin(codes))
        ]
        if subset.empty:
            return {}
        latest = subset.sort_values("event_date").drop_duplicates("country", keep="last")
        values = {}
        for _, row in latest.iterrows():
            value = _parse_indicator_value(row["narrative_summary"])
            if value is not None:
                values[row["country"]] = value
        return values

    gdp = _latest_by_country({"NY.GDP.MKTP.KD.ZG", "NGDP_RPCH"})
    if len(gdp) >= 2:
        items = sorted(gdp.items(), key=lambda kv: kv[1], reverse=True)[:12]
        flowables.append(styled_bar_chart(
            [k for k, _v in items], [v for _k, v in items],
            "Real GDP growth, latest reading (%, World Bank/IMF)"))

    inflation = _latest_by_country({"FP.CPI.TOTL.ZG", "PCPIPCH"})
    if len(inflation) >= 2:
        items = sorted(inflation.items(), key=lambda kv: kv[1], reverse=True)[:12]
        flowables.append(styled_bar_chart(
            [k for k, _v in items], [v for _k, v in items],
            "Consumer price inflation, latest reading (%, World Bank/IMF)", color=SLATE))

    conflict = region_scope[region_scope["event_category"].isin(b.CONFLICT_CATEGORIES)].copy()
    if len(conflict) > 10:
        conflict["month"] = conflict["event_date"].astype(str).str[:7]
        monthly = conflict.groupby("month").size().sort_index().tail(12)
        if len(monthly) >= 4:
            flowables.append(styled_line_chart(
                list(monthly.index), [float(v) for v in monthly.values],
                "Security-relevant events per month (ACLED/GDELT)"))

    investment = region_scope[region_scope["event_category"] == "investment"]
    if len(investment) > 5:
        mix = investment["source"].value_counts()
        source_labels = {"AidData": "Chinese state finance (AidData)",
                          "DFC": "U.S. DFC", "WorldBankPPI": "Private infra (PPI)"}
        flowables.append(styled_pie_chart(
            [source_labels.get(s, s) for s in mix.index],
            [float(v) for v in mix.values],
            "Development-finance activity by financier (project count)"))

    return flowables
