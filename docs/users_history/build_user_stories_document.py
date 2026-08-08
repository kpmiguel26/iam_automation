"""
File: docs/users_history/build_user_stories_document.py
Purpose: Provides the build user stories document component of IAM Automation.
Responsibilities: Exposes or coordinates: set_cell_shading, set_cell_margins, set_table_borders, set_table_widths, set_run, add_inline_runs, ….
Dependencies: docx
Inputs/outputs: Inputs: application arguments, configured paths, and persisted runtime data. Outputs: domain results, state changes, or operational records.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs" / "users_history.md"
OUTPUT_DIR = ROOT / "docs" / "users_history"
DOCX_PATH = OUTPUT_DIR / "IAM_Automation_User_Stories_and_Stakeholder_Guide.docx"
LOGO = ROOT / "iam_automation" / "static" / "kaiser_permanente_logo.png"

NAVY = "0B2545"
TEAL = "007C83"
BLUE = "2E74B5"
MUTED = "667085"
LIGHT = "F2F4F7"
PALE_TEAL = "EAF6F5"
WHITE = "FFFFFF"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=90, start=120, bottom=90, end=120) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    margins = tc_pr.first_child_found_in("w:tcMar")
    if margins is None:
        margins = OxmlElement("w:tcMar")
        tc_pr.append(margins)
    for side, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = margins.find(qn(f"w:{side}"))
        if node is None:
            node = OxmlElement(f"w:{side}")
            margins.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_borders(table, color="D0D5DD", size="6") -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = f"w:{edge}"
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), size)
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), color)


def set_table_widths(table, widths) -> None:
    table.autofit = False
    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            cell.width = Inches(width)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_margins(cell)


def set_run(run, *, size=11, color="1F2937", bold=False, italic=False, font="Calibri"):
    run.font.name = font
    run._element.rPr.rFonts.set(qn("w:ascii"), font)
    run._element.rPr.rFonts.set(qn("w:hAnsi"), font)
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)
    run.bold = bold
    run.italic = italic


def add_inline_runs(paragraph, text, *, size=10.5, color="1F2937"):
    """Render the small Markdown subset used by the stakeholder source."""
    pattern = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")
    cursor = 0
    for match in pattern.finditer(text):
        if match.start() > cursor:
            set_run(paragraph.add_run(text[cursor:match.start()]), size=size, color=color)
        token = match.group(0)
        if token.startswith("**"):
            set_run(paragraph.add_run(token[2:-2]), size=size, color=color, bold=True)
        else:
            set_run(paragraph.add_run(token[1:-1]), size=size, color=NAVY, font="Courier New")
        cursor = match.end()
    if cursor < len(text):
        set_run(paragraph.add_run(text[cursor:]), size=size, color=color)


def add_paragraph(doc, text="", *, size=10.5, color="1F2937", bold=False, italic=False, after=6, align=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = 1.1
    if align is not None:
        p.alignment = align
    if text:
        if bold or italic:
            set_run(p.add_run(text), size=size, color=color, bold=bold, italic=italic)
        else:
            add_inline_runs(p, text, size=size, color=color)
    return p


def add_bullet(doc, text, level=0):
    p = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.1
    add_inline_runs(p, text)
    return p


def add_table(doc, rows):
    if not rows:
        return
    header = rows[0]
    table = doc.add_table(rows=1, cols=len(header))
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.style = "Table Grid"
    for index, value in enumerate(header):
        cell = table.rows[0].cells[index]
        set_cell_shading(cell, NAVY)
        paragraph = cell.paragraphs[0]
        paragraph.paragraph_format.space_after = Pt(0)
        set_run(paragraph.add_run(value), size=8.5, color=WHITE, bold=True)
    for row_index, values in enumerate(rows[1:], start=1):
        cells = table.add_row().cells
        for index, value in enumerate(values):
            cell = cells[index]
            if row_index % 2 == 0:
                set_cell_shading(cell, LIGHT)
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            add_inline_runs(paragraph, value, size=8.2, color="344054")
    widths = [0.6, 2.1, 2.75, 1.05] if len(header) == 4 else [1.65, 2.15, 2.7]
    if len(header) == 2:
        widths = [1.55, 4.95]
    set_table_widths(table, widths)
    set_table_borders(table)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def parse_table(lines, start):
    rows = []
    index = start
    while index < len(lines) and lines[index].strip().startswith("|"):
        values = [part.strip() for part in lines[index].strip().strip("|").split("|")]
        if not all(set(value) <= {"-", ":", " "} for value in values):
            rows.append(values)
        index += 1
    return rows, index


def add_source_content(doc):
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    index = 0
    ordered_number = 0
    while index < len(lines) and not lines[index].startswith("## 1. Purpose"):
        index += 1
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            ordered_number = 0
            index += 1
            continue
        if line.startswith("### "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(4)
            set_run(p.add_run(line[4:]), size=12, color=TEAL, bold=True)
            index += 1
            continue
        if line.startswith("## "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after = Pt(6)
            set_run(p.add_run(line[3:]), size=16, color=BLUE, bold=True)
            index += 1
            continue
        if line.startswith("|"):
            rows, index = parse_table(lines, index)
            add_table(doc, rows)
            continue
        if line.startswith("- "):
            add_bullet(doc, line[2:])
            ordered_number = 0
            index += 1
            continue
        if re.match(r"^\d+\. ", line):
            ordered_number += 1
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.25)
            p.paragraph_format.first_line_indent = Inches(-0.25)
            p.paragraph_format.space_after = Pt(3)
            set_run(p.add_run(f"{ordered_number}. "), size=10.5, bold=True)
            add_inline_runs(p, re.sub(r"^\d+\. ", "", line))
            index += 1
            continue
        if line.startswith("**") and line.endswith("**"):
            add_paragraph(doc, line.replace("**", ""), size=9.5, color=MUTED, italic=True, after=5)
            index += 1
            continue
        add_paragraph(doc, line, after=5)
        ordered_number = 0
        index += 1


def build_document():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, OUTPUT_DIR / "users_history.md")

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.75)
    section.bottom_margin = Inches(0.75)
    section.left_margin = Inches(0.85)
    section.right_margin = Inches(0.85)
    section.header_distance = Inches(0.35)
    section.footer_distance = Inches(0.35)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Calibri"
    normal._element.rPr.rFonts.set(qn("w:ascii"), "Calibri")
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), "Calibri")
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = RGBColor.from_string("1F2937")

    header = section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    set_run(header.add_run("IAM AUTOMATION  |  STAKEHOLDER GUIDE"), size=8, color=MUTED, bold=True)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(footer.add_run("Kaiser Permanente  |  IAM Automation  |  Working stakeholder draft"), size=8, color=MUTED)

    if LOGO.is_file():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_after = Pt(22)
        p.add_run().add_picture(str(LOGO), width=Inches(2.4))
    add_paragraph(doc, "IAM AUTOMATION", size=11, color=TEAL, bold=True, after=5)
    add_paragraph(doc, "User Stories and Stakeholder Guide", size=25, color=NAVY, bold=True, after=8)
    add_paragraph(doc, "Product scope, user journeys, screens, configuration and delivery status", size=13, color=MUTED, after=20)

    metadata = [
        ["Document owner", "IAM Automation Product and Engineering"],
        ["Audience", "Business stakeholders, Product Management, Operations, QA and Engineering"],
        ["Version", "Working stakeholder draft - July 24, 2026"],
        ["Implementation branch", "feature/admin-control-center"],
        ["Primary runtime", "Local Flask/Waitress webapp with PySide6 control panel"],
    ]
    add_table(doc, [["Document control", "Value"], *metadata])
    add_paragraph(doc, "This document describes the application behavior implemented to date and identifies the remaining work required before production ingestion and stakeholder acceptance.", size=10.5, color="344054", after=14)
    doc.add_page_break()
    add_source_content(doc)

    doc.core_properties.title = "IAM Automation User Stories and Stakeholder Guide"
    doc.core_properties.subject = "Stakeholder requirements, application screens and delivery status"
    doc.core_properties.author = "IAM Automation Team"
    doc.core_properties.keywords = "IAM, automation, user stories, stakeholders, approvals, ingestion"
    doc.save(DOCX_PATH)
    return DOCX_PATH


if __name__ == "__main__":
    print(build_document())
