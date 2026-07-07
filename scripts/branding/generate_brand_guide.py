"""
scripts/branding/generate_brand_guide.py

Generates a complete Frontier Mercator Group brand guidelines PDF -- colors
(with hex codes), fonts, logo usage, and supplementary marks -- so Chris has
a single, copy-pasteable reference for letterhead, email signatures, intro
letters, and other branded documents without pulling values out of the site.

Pulls color/font values directly from scripts/branding.py (the single
source of truth already used by the site and PDF reports), so this guide
can never drift out of sync with what's actually deployed.

Usage:
    python scripts/branding/generate_brand_guide.py
    # writes Frontier_Mercator_Brand_Guidelines.pdf to the repo root
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image,
)
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from svglib.svglib import svg2rlg
from io import BytesIO

from scripts import branding as b

OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "Frontier_Mercator_Brand_Guidelines.pdf"
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"

PAGE_BG = colors.HexColor(b.BG)
TEXT_PRIMARY = colors.HexColor(b.TEXT_PRIMARY)
TEXT_MUTED = colors.HexColor(b.TEXT_MUTED)
GOLD = colors.HexColor(b.GOLD)
NAVY = colors.HexColor(b.NAVY)

TITLE_STYLE = ParagraphStyle("BGTitle", fontName="Helvetica-Bold", fontSize=30, textColor=TEXT_PRIMARY, leading=34)
SUBTITLE_STYLE = ParagraphStyle("BGSubtitle", fontName="Helvetica", fontSize=13, textColor=GOLD, leading=18, spaceAfter=6)
SECTION_STYLE = ParagraphStyle("BGSection", fontName="Helvetica-Bold", fontSize=18, textColor=TEXT_PRIMARY, spaceBefore=18, spaceAfter=10)
SUBHEAD_STYLE = ParagraphStyle("BGSubhead", fontName="Helvetica-Bold", fontSize=12, textColor=GOLD, spaceBefore=10, spaceAfter=4)
BODY_STYLE = ParagraphStyle("BGBody", fontName="Helvetica", fontSize=10, textColor=TEXT_PRIMARY, leading=15, spaceAfter=6)
MUTED_STYLE = ParagraphStyle("BGMuted", fontName="Helvetica", fontSize=8.5, textColor=TEXT_MUTED, leading=12)
MONO_STYLE = ParagraphStyle("BGMono", fontName="Courier", fontSize=9, textColor=TEXT_PRIMARY, leading=13)


def _paint_bg(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(PAGE_BG)
    canvas.rect(0, 0, LETTER[0], LETTER[1], fill=1, stroke=0)
    canvas.restoreState()


def _color_swatch_table(entries: list[tuple[str, str, str]]) -> Table:
    """entries: (name, hex, usage_note). Renders a swatch block + name +
    hex + usage as one table row per color."""
    rows = []
    for name, hexcode, usage in entries:
        swatch = Table([[""]], colWidths=[0.9 * inch], rowHeights=[0.5 * inch])
        swatch.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(hexcode)),
            ("BOX", (0, 0), (-1, -1), 0.75, TEXT_MUTED),
        ]))
        label = Paragraph(f"<b>{name}</b><br/><font name='Courier' size=9>{hexcode}</font><br/>{usage}", BODY_STYLE)
        rows.append([swatch, label])
    table = Table(rows, colWidths=[1.1 * inch, 5.2 * inch])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _svg_image(path: Path, width: float, height: float):
    drawing = svg2rlg(str(path))
    if drawing is None:
        return Paragraph(f"[missing: {path.name}]", MUTED_STYLE)
    scale = min(width / drawing.width, height / drawing.height)
    drawing.width, drawing.height = drawing.width * scale, drawing.height * scale
    drawing.scale(scale, scale)
    return drawing


def build_brand_guide() -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
        leftMargin=0.8 * inch, rightMargin=0.8 * inch,
    )
    story = []

    # --- Cover ---
    story.append(Spacer(1, 1.6 * inch))
    story.append(_svg_image(STATIC_DIR / "fm_emblem.svg", 1.4 * inch, 1.4 * inch))
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("FRONTIER MERCATOR", TITLE_STYLE))
    story.append(Paragraph("Intelligence for the Frontier", SUBTITLE_STYLE))
    story.append(Spacer(1, 0.5 * inch))
    story.append(Paragraph("Brand Guidelines", ParagraphStyle(
        "CoverSub", fontName="Helvetica", fontSize=16, textColor=TEXT_MUTED,
    )))
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph(
        "Colors, typography, logo usage, and supplementary marks for consistent use across "
        "email, letterhead, presentations, and printed materials.",
        MUTED_STYLE,
    ))
    story.append(PageBreak())

    # --- Color Palette ---
    story.append(Paragraph("Color Palette", SECTION_STYLE))
    story.append(Paragraph(
        "Dark theme is the brand standard across the site and all reports -- not a dark-mode "
        "option, THE design. Use these values exactly; do not eyeball or approximate from a "
        "screenshot.",
        BODY_STYLE,
    ))
    story.append(Paragraph("Core Brand", SUBHEAD_STYLE))
    story.append(_color_swatch_table([
        ("Navy", b.NAVY, "Deep brand navy. Primary header bands, strong accent fills."),
        ("Slate", b.SLATE, "Brand secondary gray. Body chrome, secondary UI elements."),
        ("Gold", b.GOLD, "Brand accent -- the \"Mercator\" (merchant) half of the name. Use "
                          "sparingly: rules, hover states, section dividers. Never a primary fill."),
        ("Accent Gray", b.ACCENT, "Light gray. Interactive/active states -- deliberately no blue tint."),
    ]))
    story.append(Paragraph("Surfaces", SUBHEAD_STYLE))
    story.append(_color_swatch_table([
        ("Background", b.BG, "Page/canvas background."),
        ("Panel", b.PANEL, "Card, table-header, and panel backgrounds."),
        ("Panel Alt", b.PANEL_ALT, "Alternating panel shade (zebra striping)."),
        ("Border", b.BORDER, "Hairline borders and dividers on dark surfaces."),
    ]))
    story.append(Paragraph("Text", SUBHEAD_STYLE))
    story.append(_color_swatch_table([
        ("Primary Text", b.TEXT_PRIMARY, "Body copy, headings on dark backgrounds."),
        ("Muted Text", b.TEXT_MUTED, "Captions, secondary/de-emphasized copy."),
    ]))
    story.append(Paragraph("Severity Scale (data encoding only)", SUBHEAD_STYLE))
    story.append(Paragraph(
        "These four colors are reserved for risk/severity data visualization (maps, scorecards, "
        "tickers) -- not general UI chrome. Do not reuse them decoratively.",
        MUTED_STYLE,
    ))
    story.append(_color_swatch_table([
        ("Critical", b.CRITICAL, "Highest severity/risk."),
        ("High", b.HIGH, "Elevated severity/risk."),
        ("Medium", b.MEDIUM, "Moderate severity/risk."),
        ("Low", b.LOW, "Low severity/risk; positive market movement."),
    ]))
    story.append(PageBreak())

    # --- Typography ---
    story.append(Paragraph("Typography", SECTION_STYLE))
    story.append(Paragraph("Display / Wordmark", SUBHEAD_STYLE))
    story.append(Paragraph(
        "Used only for the large \"FRONTIER MERCATOR\" wordmark -- sharp, angular letterforms, "
        "never rounded (Lockheed Martin's wordmark is the reference point). Applied with a slight "
        "skew transform on the live site.",
        BODY_STYLE,
    ))
    story.append(Paragraph(f"<font face='Helvetica-Bold' size=22>Rajdhani</font> (primary) -- "
                            f"free, Google Fonts", BODY_STYLE))
    story.append(Paragraph(f"Fallback stack: {b.DISPLAY_FONT_STACK}", MONO_STYLE))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Body / UI", SUBHEAD_STYLE))
    story.append(Paragraph(
        "Used for everything else -- body copy, tables, captions, buttons. Bahnschrift is bundled "
        "with Windows and listed first so Windows visitors get it natively; Barlow Semi Condensed "
        "(Google Fonts) is the free lookalike for Mac/Linux/mobile so the brand voice doesn't "
        "silently degrade to a generic system font.",
        BODY_STYLE,
    ))
    story.append(Paragraph("<font face='Helvetica' size=16>Bahnschrift</font> (primary, Windows-native)", BODY_STYLE))
    story.append(Paragraph(f"Fallback stack: {b.FONT_STACK}", MONO_STYLE))
    story.append(PageBreak())

    # --- Logo Usage ---
    story.append(Paragraph("Logo & Emblem Usage", SECTION_STYLE))
    story.append(Paragraph("Primary Emblem", SUBHEAD_STYLE))
    logo_row = Table([[
        _svg_image(STATIC_DIR / "fm_emblem.svg", 1.1 * inch, 1.1 * inch),
        Paragraph(
            "The hexagonal compass mark -- a nested hexagon/diamond motif suggesting both "
            "navigation (the Mercator projection) and a cut gem (frontier value). Renders on "
            "the site's dark navy background; always display it on a dark surface, never on "
            "white/light without adapting stroke colors for contrast.",
            BODY_STYLE,
        ),
    ]], colWidths=[1.4 * inch, 4.9 * inch])
    logo_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(logo_row)
    story.append(Spacer(1, 10))
    story.append(Paragraph("Wordmark Lockup", SUBHEAD_STYLE))
    story.append(Paragraph(
        "Standard lockup: emblem, then \"FRONTIER MERCATOR\" in the display font, tagline "
        "\"Intelligence for the Frontier\" beneath in Gold. Keep the emblem-to-wordmark spacing "
        "proportional to the emblem's own height (roughly 0.4x) -- don't crowd them.",
        BODY_STYLE,
    ))
    story.append(Paragraph("Clear Space & Minimum Size", SUBHEAD_STYLE))
    story.append(Paragraph(
        "Maintain clear space around the emblem equal to at least half its height on every side. "
        "Do not shrink the emblem below 24px / 0.25in -- the nested hexagon detail degrades "
        "illegibly below that.",
        BODY_STYLE,
    ))
    story.append(Paragraph("Don't", SUBHEAD_STYLE))
    story.append(Paragraph(
        "Don't recolor the emblem outside the palette above. Don't rotate it. Don't place it on "
        "busy photographic backgrounds without a solid navy plate beneath it. Don't stretch the "
        "wordmark to a different aspect ratio.",
        BODY_STYLE,
    ))
    story.append(PageBreak())

    # --- Supplementary Marks ---
    story.append(Paragraph("Supplementary Marks", SECTION_STYLE))
    story.append(Paragraph(
        "New marks in the same visual language as the primary emblem (nested geometric forms, "
        "thin hairline strokes, brand palette only) -- for use where a secondary or product-"
        "specific mark is more appropriate than the primary company emblem.",
        BODY_STYLE,
    ))
    for filename, title, desc in [
        ("parallax_mark.svg", "Parallax Product Mark",
         "For the Parallax platform specifically, distinct from the Frontier Mercator company "
         "emblem -- two offset angular planes suggesting a shift in vantage point (the optical "
         "meaning of \"parallax\"), the platform's own visual signature."),
        ("mercator_mark.svg", "Mercator Tribute Mark",
         "A compass-rose/meridian motif referencing Gerardus Mercator, the company's namesake -- "
         "for use in formal/historical contexts (About page, formal correspondence)."),
        ("world_map_mark.svg", "World Map Motif",
         "A minimal line-art world map for use as a watermark, letterhead footer element, or "
         "section divider where a literal \"global reach\" visual is wanted."),
    ]:
        row = Table([[
            _svg_image(STATIC_DIR / filename, 1.3 * inch, 1.0 * inch),
            Paragraph(f"<b>{title}</b><br/>{desc}", BODY_STYLE),
        ]], colWidths=[1.6 * inch, 4.7 * inch])
        row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
        story.append(row)

    story.append(Spacer(1, 20))
    story.append(Paragraph(
        "Frontier Mercator Group -- Brand Guidelines. Internal reference document.",
        MUTED_STYLE,
    ))

    doc.build(story, onFirstPage=_paint_bg, onLaterPages=_paint_bg)
    return buffer.getvalue()


def main():
    pdf_bytes = build_brand_guide()
    OUTPUT_PATH.write_bytes(pdf_bytes)
    print(f"Wrote {len(pdf_bytes):,} bytes to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
