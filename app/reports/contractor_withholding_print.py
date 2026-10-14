"""طباعة تقرير ضرائب الخصم — نموذج 2 «الشريط الأخضر الداكن» (user, 2026-10-14).

The page looks like the screen: under نموذج 4's header (logo, name, address,
السجل الضريبي from الشركات والمشاريع) and the filter strip, the dark green band with
the figures — إجمالي المستخلص، صافي الأعمال، رصيد أول المدة + ضرائب الخصم على
المستخلصات = صافي ضرائب الخصم — then the table with a green head and a dark totals row.

The user's rules:

* Each company prints on its own pages; the header and the filter strip repeat on
  every page with «صفحة س من ص», the band only on the company's first page.
* A company's رصيد أول المدة is the whole card of every contractor with a contract
  there, even when he works for two companies (``withholding_by_company``).
* The printed columns follow «تحديد أعمدة الجدول»; the text always wraps: the columns
  share the width equally and a long name goes onto more lines.
* After the last company, «الإجمالي العام»: a table with a line per company and the
  grand total under it.
* Excel: one right-to-left sheet per company with the same header, the band's figures
  and the table; the last sheet ends with the companies' table.

The page, the preview, the printer and the PDF are :mod:`app.reports.contracting_print`'s.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.reports.contracting_print import (
    CELL_RULE,
    FLOW_PAGINATE,
    MONEY,
    PAGE_HEIGHT_PX,
    PCT,
    SLATE,
    TEXT,
    PrintColumn,
    PrintDocument,
    PrintSection,
    _STYLE,
    _add_logo,
    _decimal,
    _esc,
    _excel_value,
    _filters_html,
    _header_html,
    _sheet_title,
    cell_text,
    company_lines,
    font_px,
    label_span,
)

BAND = "#14532D"
BAND_CAPTION = "#BBF7D0"
BAND_HINT = "#86EFAC"
BAND_TINT = "#F0FDF4"
NET_TEXT = "#881337"
WITHHOLDING_TEXT = "#9F1239"
TOTAL_ROSE = "#FECDD3"
WITHHOLDING = "withholding_tax"

# The band's figures, right to left: (key, caption, the sign before it) — as on the screen.
FIGURES = (
    ("works_value", "إجمالي المستخلص", ""),
    ("before_tax", "صافي الأعمال", ""),
    ("opening", "رصيد أول المدة", ""),
    ("withholding_tax", "ضرائب الخصم على المستخلصات", "+"),
    ("net", "صافي ضرائب الخصم", "="),
)

# «الإجمالي العام»: a line per company.
COMPANY_COLUMNS = [
    PrintColumn("company_name", "الشركة", TEXT),
    PrintColumn("count", "عدد المستخلصات", TEXT),
    PrintColumn("works_value", "إجمالي المستخلص", MONEY),
    PrintColumn("before_tax", "صافي الأعمال", MONEY),
    PrintColumn("opening", "رصيد أول المدة", MONEY),
    PrintColumn("withholding_tax", "ضرائب الخصم على المستخلصات", MONEY),
    PrintColumn("net", "صافي ضرائب الخصم", MONEY),
]
GRAND_KEYS = ("works_value", "before_tax", "opening", "withholding_tax", "net")


@dataclass
class WithholdingSection(PrintSection):
    """One company's pages: its extracts, their totals and the band's figures and hints."""

    figures: dict[str, Any] = field(default_factory=dict)  # FIGURES' keys
    hints: dict[str, str] = field(default_factory=dict)    # the small line under each figure


@dataclass
class WithholdingDocument(PrintDocument):
    """``PrintDocument`` (count_noun «مستخلصات») with its own page and workbook; set
    ``grand_totals`` (``grand_figures``) when there is more than one company."""

    def html(self) -> str:
        return build_html(self)

    def excel(self, path: str | Path) -> Path:
        return export_excel(self, path)

    def company_lines(self) -> list[dict[str, Any]]:
        """«الإجمالي العام»'s lines: each company's count and figures."""
        return [{"company_name": section.company.get("company_name") or "", "count": len(section.rows),
                 **{key: section.figures.get(key) for key in GRAND_KEYS}} for section in self.sections]


def grand_figures(sections: list[WithholdingSection]) -> dict[str, Any]:
    totals: dict[str, Any] = {key: sum((_decimal(section.figures.get(key)) for section in sections), _decimal(0))
                              for key in GRAND_KEYS}
    totals["count"] = sum(len(section.rows) for section in sections)
    return totals


def _money(value: Any) -> str:
    return cell_text(PrintColumn("", "", MONEY), value)


# -- HTML -------------------------------------------------------------------------------------

_EXTRA_STYLE = f"""
.head {{ border-color:{BAND}; }}
.co {{ border-left-color:{BAND}; }}
.meta {{ border-right-color:{BAND}; }}
.title {{ background:{BAND_TINT}; }}
.title .t {{ color:{BAND}; }}
.filters {{ border-color:{BAND_CAPTION}; background:{BAND_TINT}; }}
.filters div {{ border-left-color:{BAND_CAPTION}; }}
.filters span {{ color:#166534; }}
.band {{ display:flex; align-items:stretch; background:{BAND}; border-radius:7px; padding:10px 12px; }}
.band .f {{ flex:1; display:flex; flex-direction:column; gap:1px; padding:2px 14px; min-width:0; }}
.band .f.line {{ border-left:1px solid rgba(255,255,255,0.22); }}
.band .f span {{ font-size:11.5px; font-weight:700; color:{BAND_CAPTION}; }}
.band .f b {{ font-size:18px; color:#FFFFFF; direction:ltr; text-align:right; white-space:nowrap; }}
.band .f i {{ font-style:normal; font-size:10.5px; color:{BAND_HINT}; overflow-wrap:anywhere; }}
.band .f.net {{ background:#FFFFFF; border-radius:6px; margin-right:8px; padding:4px 14px; }}
.band .f.net span, .band .f.net i {{ color:{WITHHOLDING_TEXT}; }}
.band .f.net b {{ color:{NET_TEXT}; }}
.band .s {{ color:{BAND_HINT}; font-size:24px; font-weight:700; align-self:center; padding:0 2px; }}
table.wt {{ table-layout:fixed; }}
table.wt th {{ background:{BAND}; border-color:{BAND}; }}
table.wt td {{ border-color:{CELL_RULE}; }}
table.wt td.w {{ color:{WITHHOLDING_TEXT}; font-weight:700; }}
table.wt tr.total td, table.wt tr.grand td {{ background:{BAND}; color:#FFFFFF; border-color:{BAND}; }}
table.wt tr.total td.w, table.wt tr.grand td.w {{ color:{TOTAL_ROSE}; }}
.cap {{ font-size:13px; font-weight:700; display:flex; align-items:center; gap:10px; margin-top:6px; }}
.cap b {{ background:{BAND}; color:#FFFFFF; padding:3px 16px; border-radius:4px; }}
"""


def _band_html(section: WithholdingSection) -> str:
    parts = []
    for index, (key, caption, sign) in enumerate(FIGURES):
        if sign:
            parts.append(f'<div class="s">{sign}</div>')
        css = "f net" if key == "net" else "f line" if index < 2 else "f"
        hint = section.hints.get(key, "")
        parts.append(f'<div class="{css}"><span>{_esc(caption)}</span><b>{_esc(_money(section.figures.get(key)))}</b>'
                     f'<i>{_esc(hint)}</i></div>')
    return '<div class="band">' + "".join(parts) + "</div>"


def _td(column: PrintColumn, value: Any) -> str:
    text = _esc(cell_text(column, value))
    if column.kind in (MONEY, PCT):
        css = "num w" if column.key == WITHHOLDING else "num"
        if column.kind == MONEY and _decimal(value) < 0:
            css += " neg"
        return f'<td class="{css}">{text}</td>'
    return f'<td{" class=nw" if column.nowrap else ""}>{text}</td>'


def _total_tr(columns: list[PrintColumn], label: str, totals: dict[str, Any], css: str) -> str:
    span = label_span(columns)
    cells = []
    for column in columns[span:]:
        if column.kind == MONEY and column.key in totals:
            cells.append(f'<td class="num{" w" if column.key == WITHHOLDING else ""}">'
                         f"{_esc(_money(totals[column.key]))}</td>")
        else:
            cells.append("<td></td>")
    return f'<tr class="{css}"><td colspan="{span}">{_esc(label)}</td>{"".join(cells)}</tr>'


def _table_html(document: WithholdingDocument, section: WithholdingSection) -> str:
    columns = document.columns
    head = "".join(f"<th>{_esc(column.label)}</th>" for column in columns)
    body = ["<tr>" + "".join(_td(column, row.get(column.key)) for column in columns) + "</tr>" for row in section.rows]
    if section.rows:
        body.append(_total_tr(columns, f"الإجمالي — {len(section.rows)} {document.count_noun}", section.totals, "total"))
    else:
        body.append(f'<tr><td class="empty" colspan="{len(columns)}">لا توجد مستخلصات في الفترة</td></tr>')
    return (f'<div class="split"><table class="wt" style="font-size:{font_px(columns)}px">'
            f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>")


def _grand_html(document: WithholdingDocument) -> str:
    columns = COMPANY_COLUMNS
    head = "".join(f"<th>{_esc(column.label)}</th>" for column in columns)
    body = ["<tr>" + "".join(_td(column, line.get(column.key)) for column in columns) + "</tr>"
            for line in document.company_lines()]
    grand = document.grand_totals or {}
    body.append('<tr class="grand"><td>الإجمالي العام</td>'
                f'<td>{_esc(grand.get("count", ""))}</td>'
                + "".join(f'<td class="num{" w" if key == WITHHOLDING else ""}">{_esc(_money(grand.get(key)))}</td>'
                          for key in GRAND_KEYS) + "</tr>")
    return (f'<div class="split"><div class="cap"><b class="cap-text">الإجمالي العام — كل الشركات</b></div>'
            f'<table class="wt" style="font-size:11.5px"><thead><tr>{head}</tr></thead>'
            f"<tbody>{''.join(body)}</tbody></table></div>")


def _section_html(document: WithholdingDocument, section: WithholdingSection, last: bool) -> str:
    parts = [_header_html(document, section, fixed=True), _filters_html(document, fixed=True),
             _band_html(section), _table_html(document, section)]
    if last and document.grand_totals is not None:
        parts.append(_grand_html(document))
    return '<div class="section">' + "".join(parts) + "</div>"


def build_html(document: WithholdingDocument) -> str:
    sections = "".join(_section_html(document, section, index == len(document.sections) - 1)
                       for index, section in enumerate(document.sections))
    script = FLOW_PAGINATE % {"limit": PAGE_HEIGHT_PX}
    return (
        '<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="utf-8">'
        f"<title>{_esc(document.title)}</title><style>{_STYLE}{_EXTRA_STYLE}</style></head>"
        f"<body>{sections}<script>{script}</script></body></html>"
    )


# -- Excel ------------------------------------------------------------------------------------


def export_excel(document: WithholdingDocument, path: str | Path) -> Path:
    """One right-to-left sheet per company: the header lines, the band's figures (captions,
    amounts, hints), then the table and its total; the last sheet ends with the companies."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    workbook.remove(workbook.active)
    thin, dark = Side(style="thin", color=CELL_RULE[1:]), Side(style="thin", color=BAND[1:])
    grid = Border(left=thin, right=thin, top=thin, bottom=thin)
    band_grid = Border(left=dark, right=dark, top=dark, bottom=dark)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    right = Alignment(horizontal="right", vertical="center")
    band_fill, white_fill = PatternFill("solid", fgColor=BAND[1:]), PatternFill("solid", fgColor="FFFFFF")
    white_bold = Font(bold=True, color="FFFFFF")
    money = PrintColumn("", "", MONEY)
    columns = document.columns
    used: set[str] = set()

    def head_row(sheet: Any, row_no: int, heads: list[PrintColumn]) -> int:
        for col, column in enumerate(heads, start=1):
            cell = sheet.cell(row=row_no, column=col, value=column.label)
            cell.font, cell.fill, cell.alignment, cell.border = white_bold, band_fill, center, band_grid
        sheet.row_dimensions[row_no].height = 32
        return row_no + 1

    def body_cell(sheet: Any, row_no: int, col: int, column: PrintColumn, value: Any) -> None:
        cell = sheet.cell(row=row_no, column=col)
        _excel_value(cell, column, value)
        cell.alignment, cell.border = center, grid
        if column.key == WITHHOLDING:
            cell.font = Font(bold=True, color=WITHHOLDING_TEXT[1:])

    for index, section in enumerate(document.sections):
        company = section.company
        sheet = workbook.create_sheet(_sheet_title(company.get("company_name"), used))
        sheet.sheet_view.rightToLeft = True
        last = index == len(document.sections) - 1
        width = max(len(columns), len(FIGURES), len(COMPANY_COLUMNS) if last and document.grand_totals else 0)
        first_col = 1
        if company.get("logo"):
            first_col = 2  # the logo sits in column A, beside the company lines
            _add_logo(sheet, company)
        lines = [(company.get("company_name") or "", Font(bold=True, size=16)),
                 *((line, Font(size=11, color=SLATE[1:])) for line in company_lines(company)),
                 (document.title, Font(bold=True, size=14, color=BAND[1:])),
                 (document.subtitle, Font(size=11, color=SLATE[1:])),
                 ("   |   ".join(f"{caption}: {value}" for caption, value in document.filters), Font(size=11)),
                 (f"تاريخ الطباعة: {document.printed_at:%Y-%m-%d %H:%M}   |   المستخدم: {document.printed_by or '—'}"
                  f"   |   عدد ال{document.count_noun}: {len(section.rows)}", Font(size=11, color=SLATE[1:]))]
        row_no = 1
        for text, font in lines:
            cell = sheet.cell(row=row_no, column=first_col, value=text)
            cell.font, cell.alignment = font, right
            if width > first_col:
                sheet.merge_cells(start_row=row_no, start_column=first_col, end_row=row_no, end_column=width)
            row_no += 1
        row_no += 1

        # the band: captions over amounts over hints, the net in white
        for col, (key, caption, sign) in enumerate(FIGURES, start=1):
            net = key == "net"
            cells = (sheet.cell(row=row_no, column=col, value=f"{sign} {caption}".strip()),
                     sheet.cell(row=row_no + 1, column=col),
                     sheet.cell(row=row_no + 2, column=col, value=section.hints.get(key, "")))
            _excel_value(cells[1], money, section.figures.get(key))
            fonts = (Font(bold=True, size=10, color=(WITHHOLDING_TEXT if net else BAND_CAPTION)[1:]),
                     Font(bold=True, size=13, color=(NET_TEXT if net else "#FFFFFF")[1:]),
                     Font(size=9, color=(WITHHOLDING_TEXT if net else BAND_HINT)[1:]))
            for cell, font in zip(cells, fonts):
                cell.fill, cell.font, cell.alignment, cell.border = (white_fill if net else band_fill), font, center, band_grid
        sheet.row_dimensions[row_no + 1].height = 22
        row_no += 4

        # the table
        row_no = head_row(sheet, row_no, columns)
        for row in section.rows:
            for col, column in enumerate(columns, start=1):
                body_cell(sheet, row_no, col, column, row.get(column.key))
            row_no += 1
        span = label_span(columns)
        if section.rows:
            sheet.cell(row=row_no, column=1, value=f"الإجمالي — {len(section.rows)} {document.count_noun}")
            for col, column in enumerate(columns, start=1):
                cell = sheet.cell(row=row_no, column=col)
                if col > span and column.kind == MONEY and column.key in section.totals:
                    _excel_value(cell, column, section.totals[column.key])
                color = TOTAL_ROSE if column.key == WITHHOLDING else "#FFFFFF"
                cell.fill, cell.font, cell.border, cell.alignment = band_fill, Font(bold=True, color=color[1:]), band_grid, center
            if span > 1:
                sheet.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=span)
        else:
            sheet.cell(row=row_no, column=1, value="لا توجد مستخلصات في الفترة").alignment = center
            sheet.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=len(columns))
        row_no += 2

        # «الإجمالي العام» after the last company
        if last and document.grand_totals is not None:
            sheet.cell(row=row_no, column=1, value="الإجمالي العام — كل الشركات").font = Font(bold=True, size=12,
                                                                                            color=BAND[1:])
            row_no = head_row(sheet, row_no + 1, COMPANY_COLUMNS)
            for line in document.company_lines():
                for col, column in enumerate(COMPANY_COLUMNS, start=1):
                    body_cell(sheet, row_no, col, column, line.get(column.key))
                row_no += 1
            grand = document.grand_totals
            values = ["الإجمالي العام", grand.get("count")] + [grand.get(key) for key in GRAND_KEYS]
            for col, (column, value) in enumerate(zip(COMPANY_COLUMNS, values), start=1):
                cell = sheet.cell(row=row_no, column=col)
                _excel_value(cell, column, value)
                color = TOTAL_ROSE if column.key == WITHHOLDING else "#FFFFFF"
                cell.fill, cell.font, cell.border, cell.alignment = band_fill, Font(bold=True, color=color[1:]), band_grid, center

        for col in range(1, width + 1):
            sheet.column_dimensions[get_column_letter(col)].width = 18
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)
    return output


__all__ = [
    "COMPANY_COLUMNS", "FIGURES", "GRAND_KEYS",
    "WithholdingDocument", "WithholdingSection", "build_html", "export_excel", "grand_figures",
]
