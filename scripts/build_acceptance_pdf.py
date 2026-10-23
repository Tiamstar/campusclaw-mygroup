"""Build the Chinese acceptance PDF from docs/acceptance-report.md."""
import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "acceptance-report.md"
OUTPUT = ROOT / "docs" / "acceptance-report.pdf"
FONT = Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")
if not FONT.exists():
    raise SystemExit("A Chinese TrueType font is required; set FONT in this script for your system")
pdfmetrics.registerFont(TTFont("WQY", str(FONT)))
pdfmetrics.registerFontFamily("WQY", normal="WQY", bold="WQY", italic="WQY", boldItalic="WQY")

base = dict(fontName="WQY", wordWrap="CJK", textColor=colors.HexColor("#263238"))
styles = {
    "title": ParagraphStyle("title", fontSize=20, leading=30, alignment=TA_CENTER,
                            spaceAfter=14, **base),
    "h2": ParagraphStyle("h2", fontSize=13, leading=21, spaceBefore=16, spaceAfter=7,
                         keepWithNext=True, textColor=colors.HexColor("#8b1a1a"), fontName="WQY", wordWrap="CJK"),
    "body": ParagraphStyle("body", fontSize=10.2, leading=17, spaceAfter=8, **base),
    "bullet": ParagraphStyle("bullet", fontSize=10.2, leading=17, leftIndent=13,
                             firstLineIndent=-11, spaceAfter=5, **base),
    "code": ParagraphStyle("code", fontSize=8.3, leading=13, leftIndent=9, rightIndent=9,
                           borderPadding=7, backColor=colors.HexColor("#f3f5f6"),
                           spaceBefore=4, spaceAfter=10, **base),
}


def inline(value):
    value = html.escape(value)
    value = value.replace("**", "").replace("`", "")
    return value


def build_story():
    story = []
    paragraph = []
    code = []
    in_code = False

    def flush_paragraph():
        if paragraph:
            story.append(Paragraph(inline(" ".join(paragraph)), styles["body"]))
            paragraph.clear()

    def flush_code():
        if code:
            rendered = "<br/>".join(html.escape(line).replace(" ", "&nbsp;") for line in code)
            story.append(Paragraph(rendered, styles["code"]))
            code.clear()

    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            flush_paragraph()
            if in_code:
                flush_code()
            in_code = not in_code
            continue
        if in_code:
            code.append(line)
            continue
        if not line.strip():
            flush_paragraph()
        elif line.startswith("# "):
            flush_paragraph()
            story.append(Paragraph(inline(line[2:]), styles["title"]))
        elif line.startswith("## "):
            flush_paragraph()
            story.append(Paragraph(inline(line[3:]), styles["h2"]))
        elif line.startswith("- ") or re.match(r"^\d+\. ", line):
            flush_paragraph()
            story.append(Paragraph(inline(line), styles["bullet"]))
        else:
            paragraph.append(line.strip())
    flush_paragraph()
    flush_code()
    return story


def decorate(canvas, doc):
    canvas.saveState()
    canvas.setFont("WQY", 8.5)
    canvas.setFillColor(colors.HexColor("#607078"))
    canvas.drawString(18 * mm, 12 * mm, "CampusClaw · AI 应用平台验收报告")
    canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, str(doc.page))
    canvas.restoreState()


def main():
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=A4, title="CampusClaw 个人 AI 应用平台验收报告",
                            author="CampusClaw 项目组", leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm)
    doc.build(build_story(), onFirstPage=decorate, onLaterPages=decorate)
    print(OUTPUT)


if __name__ == "__main__":
    main()
