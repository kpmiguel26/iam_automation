"""
File: scripts/build_architecture_brief_docx.py
Purpose: Provides an operational utility for build architecture brief docx.
Responsibilities: Exposes or coordinates: set_cell_shading, set_cell_margins, set_table_borders, set_repeat_table_header, set_cell_width, set_table_geometry, ….
Dependencies: docx, PIL
Inputs/outputs: Inputs: command-line arguments and configured paths. Outputs: validation messages, files, or process status.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "architecture_presentation" / "iam_architecture_brief.md"
OUT = ROOT / "docs" / "architecture_presentation" / "IAM_Automation_Architecture_Brief.docx"
DIAGRAM_PNG = ROOT / "docs" / "diagrams" / "png"
LABELED_DIAGRAM_PNG = ROOT / "docs" / "architecture_presentation" / "diagram_pages"

BLUE = RGBColor(46, 116, 181)
DARK_BLUE = RGBColor(31, 77, 120)
INK = RGBColor(31, 41, 55)
MUTED = RGBColor(75, 85, 99)
LIGHT_FILL = "F2F4F7"
BORDER = "CBD5E1"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(table, top=80, start=120, bottom=80, end=120) -> None:
    tbl_pr = table._tbl.tblPr
    margins = tbl_pr.first_child_found_in("w:tblCellMar")
    if margins is None:
        margins = OxmlElement("w:tblCellMar")
        tbl_pr.append(margins)
    for tag, value in {"top": top, "start": start, "bottom": bottom, "end": end}.items():
        node = margins.find(qn(f"w:{tag}"))
        if node is None:
            node = OxmlElement(f"w:{tag}")
            margins.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_borders(table, color=BORDER, size="6") -> None:
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


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_cell_width(cell, width_dxa: int) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(width_dxa))
    tc_w.set(qn("w:type"), "dxa")


def set_table_geometry(table, widths: list[int]) -> None:
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False
    tbl = table._tbl
    tbl_pr = tbl.tblPr
    tbl_w = tbl_pr.first_child_found_in("w:tblW")
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(sum(widths)))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_ind = tbl_pr.first_child_found_in("w:tblInd")
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), "120")
    tbl_ind.set(qn("w:type"), "dxa")
    grid = tbl.tblGrid
    if grid is None:
        grid = OxmlElement("w:tblGrid")
        tbl.insert(0, grid)
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    for row in table.rows:
        for idx, cell in enumerate(row.cells):
            set_cell_width(cell, widths[idx])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def style_run(run, bold=False, italic=False, color=INK, size=11) -> None:
    run.bold = bold
    run.italic = italic
    run.font.name = "Calibri"
    run.font.size = Pt(size)
    run.font.color.rgb = color


def add_para(doc: Document, text: str = "", style: str | None = None):
    para = doc.add_paragraph(style=style)
    if text:
        add_inline_text(para, text)
    return para


def add_inline_text(para, text: str) -> None:
    parts = re.split(r"(`[^`]+`|\*\*[^*]+\*\*)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("`") and part.endswith("`"):
            run = para.add_run(part[1:-1])
            style_run(run, color=DARK_BLUE, size=10)
        elif part.startswith("**") and part.endswith("**"):
            run = para.add_run(part[2:-2])
            style_run(run, bold=True)
        else:
            run = para.add_run(part)
            style_run(run)


def configure_styles(doc: Document) -> None:
    section = doc.sections[0]
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.1

    for name, size, color, before, after in [
        ("Heading 1", 16, BLUE, 16, 8),
        ("Heading 2", 13, BLUE, 12, 6),
        ("Heading 3", 12, DARK_BLUE, 8, 4),
    ]:
        style = styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.color.rgb = color
        style.font.bold = True
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    for name in ("List Bullet", "List Number"):
        style = styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(11)
        style.paragraph_format.space_after = Pt(8)
        style.paragraph_format.line_spacing = 1.167


def add_cover(doc: Document) -> None:
    title = doc.add_paragraph()
    title.paragraph_format.space_after = Pt(8)
    run = title.add_run("IAM Automation Architecture Brief")
    style_run(run, bold=True, color=RGBColor(11, 37, 69), size=24)

    subtitle = doc.add_paragraph()
    subtitle.paragraph_format.space_after = Pt(18)
    run = subtitle.add_run("Single-writer request-and-approval architecture for Access snapshots, SharePoint requests, audit, and Excel outputs")
    style_run(run, color=MUTED, size=12)

    table = doc.add_table(rows=4, cols=2)
    table.style = "Table Grid"
    set_table_borders(table)
    set_cell_margins(table)
    set_table_geometry(table, [2200, 7000])
    rows = [
        ("Prepared for", "IAM and Operations Stakeholders"),
        ("Date", "July 17, 2026"),
        ("Status", "Corrected POC architecture"),
        ("Primary decision", "Use single-writer approval workflow with immutable requests"),
    ]
    for row, (label, value) in zip(table.rows, rows):
        set_cell_shading(row.cells[0], LIGHT_FILL)
        row.cells[0].paragraphs[0].add_run(label).bold = True
        row.cells[1].paragraphs[0].add_run(value)

    doc.add_paragraph()
    callout = doc.add_paragraph()
    callout.paragraph_format.left_indent = Inches(0.15)
    callout.paragraph_format.right_indent = Inches(0.15)
    callout.paragraph_format.space_before = Pt(8)
    callout.paragraph_format.space_after = Pt(12)
    run = callout.add_run(
        "Recommended POC path: requesters submit immutable JSON files; only an Administrator/Writer imports, approves, applies, audits, exports, and publishes versioned Access snapshots."
    )
    style_run(run, bold=True, color=DARK_BLUE)
    doc.add_section(WD_SECTION.NEW_PAGE)


def add_header_footer(doc: Document) -> None:
    for section in doc.sections:
        header = section.header.paragraphs[0]
        header.text = "IAM Automation Architecture Brief"
        header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for run in header.runs:
            style_run(run, color=MUTED, size=9)
        footer = section.footer.paragraphs[0]
        footer.text = "Proof-of-concept architecture"
        footer.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in footer.runs:
            style_run(run, color=MUTED, size=9)


def parse_table(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    rows = []
    idx = start
    while idx < len(lines) and lines[idx].strip().startswith("|"):
        raw_cells = [cell.strip() for cell in lines[idx].strip().strip("|").split("|")]
        if not all(set(cell.replace(" ", "")) <= {"-", ":"} for cell in raw_cells):
            rows.append(raw_cells)
        idx += 1
    return rows, idx


def add_table(doc: Document, rows: list[list[str]]) -> None:
    if not rows:
        return
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    set_table_borders(table)
    set_cell_margins(table)
    if len(rows[0]) == 3:
        widths = [2100, 2600, 4660]
    elif len(rows[0]) == 2:
        widths = [2600, 6760]
    else:
        widths = [int(9360 / len(rows[0]))] * len(rows[0])
    set_table_geometry(table, widths)
    set_repeat_table_header(table.rows[0])
    for r_idx, row in enumerate(rows):
        for c_idx, value in enumerate(row):
            cell = table.cell(r_idx, c_idx)
            if r_idx == 0:
                set_cell_shading(cell, LIGHT_FILL)
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            add_inline_text(paragraph, value)
            for run in paragraph.runs:
                run.font.size = Pt(10)
                if r_idx == 0:
                    run.bold = True


def diagram_title(path: Path) -> str:
    stem = re.sub(r"^\d+_", "", path.stem)
    return stem.replace("_", " ").title()


def configure_landscape_section(section) -> None:
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width = Inches(11)
    section.page_height = Inches(8.5)
    section.top_margin = Inches(0.55)
    section.bottom_margin = Inches(0.55)
    section.left_margin = Inches(0.65)
    section.right_margin = Inches(0.65)
    section.header_distance = Inches(0.3)
    section.footer_distance = Inches(0.3)


def add_diagram(
    doc: Document,
    path: Path,
    title: str | None = None,
    *,
    max_width_in: float = 6.35,
    max_height_in: float = 5.35,
    show_title: bool = True,
    show_note: bool = True,
) -> None:
    if not path.exists():
        return
    resolved_title = title or diagram_title(path)
    if show_title:
        caption = doc.add_paragraph(style="Heading 2")
        caption.add_run(resolved_title)
    pic_para = doc.add_paragraph()
    pic_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = pic_para.add_run()
    with Image.open(path) as image:
        width_px, height_px = image.size
    projected_height = max_width_in * (height_px / width_px)
    if projected_height > max_height_in:
        run.add_picture(str(path), height=Inches(max_height_in))
    else:
        run.add_picture(str(path), width=Inches(max_width_in))
    if show_note:
        note = doc.add_paragraph()
        note.alignment = WD_ALIGN_PARAGRAPH.CENTER
        note.paragraph_format.space_after = Pt(10)
        note_text = f"Source: {path.relative_to(ROOT)}"
        if not show_title:
            note_text = f"{resolved_title} | {note_text}"
        note_run = note.add_run(note_text)
        style_run(note_run, color=MUTED, size=8)


def labeled_diagram(path: Path) -> Path:
    LABELED_DIAGRAM_PNG.mkdir(parents=True, exist_ok=True)
    out = LABELED_DIAGRAM_PNG / f"{path.stem}_labeled.png"
    title = diagram_title(path)
    source = f"Source: {path.relative_to(ROOT)}"
    with Image.open(path).convert("RGB") as image:
        margin_x = 60
        title_h = 90
        source_h = 44
        canvas = Image.new("RGB", (image.width + margin_x * 2, image.height + title_h + source_h), "white")
        draw = ImageDraw.Draw(canvas)
        try:
            title_font = ImageFont.truetype("Arial.ttf", 42)
            source_font = ImageFont.truetype("Arial.ttf", 22)
        except OSError:
            title_font = ImageFont.load_default()
            source_font = ImageFont.load_default()
        draw.text((margin_x, 24), title, fill=(46, 116, 181), font=title_font)
        canvas.paste(image, (margin_x, title_h))
        draw.text((margin_x, title_h + image.height + 8), source, fill=(75, 85, 99), font=source_font)
        canvas.save(out)
    return out


def add_diagram_appendix(doc: Document) -> None:
    diagrams = sorted(DIAGRAM_PNG.glob("*.png"))
    if not diagrams:
        return
    doc.add_section(WD_SECTION.NEW_PAGE)
    doc.add_paragraph("Diagram Appendix", style="Heading 1")
    intro = doc.add_paragraph()
    add_inline_text(
        intro,
        "The following diagrams were rendered from the Mermaid source files in docs/diagrams/source and embedded as PNGs for presentation use.",
    )
    for idx, path in enumerate(diagrams, start=1):
        doc.add_page_break()
        add_diagram(
            doc,
            labeled_diagram(path),
            max_width_in=6.35,
            max_height_in=7.15,
            show_title=False,
            show_note=False,
        )


def build_doc() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    lines = text.splitlines()
    doc = Document()
    configure_styles(doc)
    add_cover(doc)

    in_mermaid = False
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        if stripped.startswith(("Prepared for:", "Date:", "Status:")):
            i += 1
            continue
        if stripped.startswith("```mermaid"):
            in_mermaid = True
            add_diagram(
                doc,
                DIAGRAM_PNG / "03_corrected_single_writer_architecture.png",
                "Corrected Single-Writer Architecture",
                max_height_in=4.8,
            )
            i += 1
            continue
        if in_mermaid:
            if stripped == "```":
                in_mermaid = False
            i += 1
            continue
        if not stripped:
            i += 1
            continue
        if stripped.startswith("# "):
            # Cover already carries title.
            i += 1
            continue
        if stripped.startswith("## "):
            doc.add_paragraph(stripped[3:], style="Heading 1")
        elif stripped.startswith("### "):
            doc.add_paragraph(stripped[4:], style="Heading 2")
        elif stripped.startswith("|"):
            rows, next_i = parse_table(lines, i)
            add_table(doc, rows)
            i = next_i - 1
        elif stripped.startswith("- "):
            para = doc.add_paragraph(style="List Bullet")
            add_inline_text(para, stripped[2:])
        elif re.match(r"^\d+\.\s", stripped):
            para = doc.add_paragraph(style="List Bullet")
            add_inline_text(para, re.sub(r"^\d+\.\s", "", stripped))
        else:
            add_para(doc, stripped)
        i += 1

    add_diagram_appendix(doc)
    add_header_footer(doc)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build_doc()
