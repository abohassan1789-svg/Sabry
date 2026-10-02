"""تقرير كشف حساب مقاول — نموذج 10 «رسم حركة الرصيد + الكشف» (2026-10-02).

* Eight cards: the account (رصيد أول المدة، صافي المستخلص، التحصيلات، المتبقي)
  and the contracts' advance (قيمة العقد، الدفعة المقدمة من العقد ونسبتها، المخصوم
  على المستخلصات، المتبقي منها).
* A line chart of الرصيد التراكمي: one point per line of the statement.
* The statement: رصيد أول المدة first, then the extracts and payments by date,
  each with its الرصيد التراكمي, and a totals row. «تحديد أعمدة الجدول» picks the
  user's 19 columns; the choice is kept per user (default: all but the rates).

Every figure comes from ``contractor_statement_report_service``.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.contractor_statement_report_service import (
    KIND_EXTRACT,
    KIND_PAYMENT,
    ContractorStatementReportService,
    empty_statement,
)
from app.ui.common.theme import GREEN, TEXT
from app.ui.screens.contracting_report_base import (
    MUTED,
    RED,
    TABLE_QSS,
    TOTAL_BG,
    ColumnChooser,
    ColumnFitter,
    ContractingReportBase,
    column_button,
    date_text,
    load_columns,
    report_settings,
    save_columns,
    table_item,
)
from app.ui.screens.contractor_contracts_screen import _money, _rate_text

PERMISSION_BASE = "contracting.contractor_statement_report"
SETTINGS_KEY = "contractor_statement_report/columns"

TEXT_COL, RATE_COL, AMOUNT_COL = "text", "rate", "amount"
# The user's 19 columns in their order: (line key, header, kind).
COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("date", "التاريخ", TEXT_COL),
    ("contractor_name", "اسم المقاول", TEXT_COL),
    ("extract_no", "رقم المستخلص", TEXT_COL),
    ("works_value", "إجمالي\nالمستخلص", AMOUNT_COL),
    ("withholding_tax_pct", "نسبة ضريبة\nالخصم", RATE_COL),
    ("withholding_tax", "قيمة ضريبة\nالخصم", AMOUNT_COL),
    ("before_tax", "صافي\nالأعمال", AMOUNT_COL),
    ("advance_payment_pct", "نسبة الدفعة\nالمقدمة", RATE_COL),
    ("advance_payment", "قيمة الدفعة\nالمقدمة", AMOUNT_COL),
    ("vat_pct", "نسبة الضرائب\nالخاصة", RATE_COL),
    ("vat_amount", "قيمة الضرائب\nالخاصة", AMOUNT_COL),
    ("works_insurance_pct", "نسبة تأمين\nالأعمال", RATE_COL),
    ("works_insurance", "قيمة تأمين\nالأعمال", AMOUNT_COL),
    ("social_insurance_pct", "نسبة التأمينات\nالاجتماعية", RATE_COL),
    ("social_insurance", "قيمة التأمينات\nالاجتماعية", AMOUNT_COL),
    ("other_deductions", "خصومات\nأخرى", AMOUNT_COL),
    ("net", "صافي\nالمستخلص", AMOUNT_COL),
    ("paid", "التحصيلات /\nالدفعات", AMOUNT_COL),
    ("balance", "الرصيد\nالتراكمي", AMOUNT_COL),
)
COLUMN_KEYS = tuple(key for key, _header, _kind in COLUMNS)
KIND = {key: kind for key, _header, kind in COLUMNS}
HEADER = {key: header.replace("\n", " ") for key, header, _kind in COLUMNS}
DEFAULT_COLUMNS = tuple(key for key in COLUMN_KEYS if KIND[key] != RATE_COL)

COLUMN_GROUPS = (
    ("بيانات الحركة", ("date", "contractor_name", "extract_no")),
    ("المستخلص", ("works_value", "before_tax", "net")),
    ("الاستقطاعات (نسبة وقيمة)", COLUMN_KEYS[4:6] + COLUMN_KEYS[7:16]),
    ("الحساب", ("paid", "balance")),
)

# (key, title, source): "totals" = the statement's, "contracts" = the advance figures.
ACCOUNT_CARDS = (
    ("opening", "إجمالي رصيد أول المدة", "totals"),
    ("net", "إجمالي صافي المستخلص", "totals"),
    ("paid", "إجمالي التحصيلات", "totals"),
    ("balance", "إجمالي المتبقي", "totals"),
)
ADVANCE_CARDS = (
    ("contract_value", "إجمالي قيمة العقد", "contracts"),
    ("advance_agreed", "إجمالي الدفعة المقدمة من العقد", "contracts"),
    ("advance_deducted", "المخصوم على المستخلصات", "contracts"),
    ("remaining_advance", "المتبقي من الدفعة المقدمة", "contracts"),
)
CARDS = ACCOUNT_CARDS + ADVANCE_CARDS
ADVANCE_KEYS = {key for key, _title, _source in ADVANCE_CARDS}
DARK_CARDS = {"balance": GREEN, "remaining_advance": "#0369A1"}

ROW_OPENING, ROW_EXTRACT, ROW_PAYMENT, ROW_TOTAL = "opening", "extract", "payment", "total"
OPENING_BG = "#EEF4F4"
PAYMENT_BG = "#F3FAF5"
BALANCE_BG = "#FFF8EA"
NET_BG = "#ECFDF3"
PAID_COLOR = "#15803D"
EXTRACT_DOT, PAYMENT_DOT, LINE_COLOR = GREEN, "#B45309", "#C0862A"


def payment_text(line: dict[str, Any]) -> str:
    """«رقم المستخلص» on a payment line: «دفعة شيك 100245 — A-H/CT-1001/EX-01» (or «— عامة»)."""
    method = " ".join(part for part in (str(line.get("payment_method") or ""), str(line.get("reference_no") or ""))
                      if part)
    return f"دفعة {method} — {line.get('extract_no') or 'عامة'}".replace("  ", " ")


def cell_text(line: dict[str, Any], key: str) -> str:
    if key == "date":
        return date_text(line.get("date"))
    if key == "extract_no" and line["kind"] == KIND_PAYMENT:
        return payment_text(line)
    if line["kind"] == KIND_PAYMENT and key not in ("contractor_name", "paid", "balance"):
        return ""
    if key == "paid" and line["kind"] == KIND_EXTRACT:
        return ""
    kind = KIND[key]
    if kind == RATE_COL:
        return f"{_rate_text(line.get(key))}%"
    if kind == AMOUNT_COL:
        return _money(line.get(key))
    return str(line.get(key) or "")


def _short_money(value: Any) -> str:
    return f"{float(value):,.0f}"


class BalanceChart(QWidget):
    """«حركة الرصيد التراكمي»: the opening balance, then one point per statement line."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(150)
        self.setLayoutDirection(Qt.LeftToRight)  # time runs left to right; the title is placed by hand
        self.points: list[tuple[Any, str]] = []  # (balance, kind)

    def set_statement(self, statement: dict[str, Any]) -> None:
        if statement["lines"] or statement["opening"]:
            self.points = [(statement["opening"], ROW_OPENING)] + [
                (line["balance"], line["kind"]) for line in statement["lines"]]
        else:
            self.points = []
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor("#E5EAF0")))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(frame, 8, 8)
        title_font = QFont(self.font())
        title_font.setBold(True)
        title_font.setPointSize(10)
        painter.setFont(title_font)
        painter.setPen(QColor(TEXT))
        painter.drawText(QRectF(14, 6, frame.width() - 28, 20), Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignVCenter,
                         "حركة الرصيد التراكمي")
        small = QFont(self.font())
        small.setPointSize(8)
        painter.setFont(small)
        for x, color, text in ((20, EXTRACT_DOT, "مستخلص يزوّد الرصيد"), (200, PAYMENT_DOT, "دفعة تقلله")):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(x, 16), 4.5, 4.5)
            painter.setPen(QColor(MUTED))
            painter.drawText(QRectF(x + 10, 6, 160, 20), Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter, text)
        if not self.points:
            painter.setPen(QColor(MUTED))
            painter.drawText(frame, Qt.AlignCenter, "مفيش حركة في الفترة دي")
            return
        values = [float(value) for value, _kind in self.points]
        # The balance's own range, so a large opening balance does not flatten the line;
        # zero joins it only when the balance goes below it.
        top, bottom = max(values), min(values)
        if bottom < 0 < top or top < 0:
            top = max(top, 0.0)
        span = (top - bottom) or max(abs(top), 1.0)
        if top == bottom:
            bottom -= span / 2
        left, right, upper, lower = 40.0, frame.width() - 40.0, 46.0, frame.height() - 18.0
        count = len(self.points)

        def at(index: int, value: float) -> QPointF:
            x = (left + right) / 2 if count == 1 else left + index * (right - left) / (count - 1)
            return QPointF(x, lower - (value - bottom) / span * (lower - upper))

        if bottom < 0 <= top:  # where zero is, once the balance went below it
            zero = at(0, 0.0).y()
            painter.setPen(QPen(QColor("#FCA5A5"), 1, Qt.DashLine))
            painter.drawLine(QPointF(left, zero), QPointF(right, zero))
        line = QPolygonF([at(i, v) for i, v in enumerate(values)])
        painter.setPen(QPen(QColor(LINE_COLOR), 2.5))
        painter.drawPolyline(line)
        for index, ((value, kind), point) in enumerate(zip(self.points, line)):
            painter.setPen(QPen(QColor("#FFFFFF"), 2))
            painter.setBrush(QColor(PAYMENT_DOT if kind == KIND_PAYMENT else EXTRACT_DOT))
            painter.drawEllipse(point, 5, 5)
            painter.setPen(QColor(RED if value < 0 else "#334155"))
            painter.drawText(QRectF(point.x() - 50, point.y() - 24, 100, 16), Qt.AlignCenter, _short_money(value))
        painter.end()


class ContractorStatementReportScreen(ContractingReportBase):
    TITLE = "تقرير كشف حساب مقاول"
    ICON = "📒"
    PERMISSION_BASE = PERMISSION_BASE

    def __init__(self, service: ContractorStatementReportService | None = None,
                 parent: QWidget | None = None, settings: QSettings | None = None) -> None:
        self.settings = settings or report_settings()
        self.statement: dict[str, Any] = empty_statement()
        self.row_kinds: list[str] = []
        self.visible_columns = load_columns(self.settings, SETTINGS_KEY, COLUMN_KEYS, DEFAULT_COLUMNS)
        super().__init__(service or ContractorStatementReportService(), parent)

    # -- layout ------------------------------------------------------------------------

    def _build_body(self, root: QVBoxLayout) -> None:
        root.addLayout(self._build_cards())
        self.chart = BalanceChart()
        root.addWidget(self.chart)
        root.addLayout(self._build_toolbar())
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([header for _key, header, _kind in COLUMNS])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(TABLE_QSS)
        header = self.table.horizontalHeader()
        header.setMinimumHeight(46)
        header.setDefaultAlignment(Qt.AlignCenter)
        self.fitter = ColumnFitter(self.table)
        root.addWidget(self.table, 1)
        self._apply_columns()

    def _build_cards(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)
        self.card_values: dict[str, QLabel] = {}
        self.card_hints: dict[str, QLabel] = {}
        self._card_styles: dict[str, str] = {}
        for index, (key, title, _source) in enumerate(CARDS):
            if index == len(ACCOUNT_CARDS):
                layout.addSpacing(10)  # the account | the contracts' advance
            dark = DARK_CARDS.get(key)
            card = QFrame()
            card.setObjectName(f"card_{key}")
            background, border, caption_color, value_color = (
                (dark, dark, "#E0F2FE", "#FFFFFF") if dark else ("#FFFFFF", "#E5EAF0", MUTED, TEXT))
            if not dark and key in ADVANCE_KEYS:
                background = "#F8FBFF"
            card.setStyleSheet(
                f"QFrame#card_{key} {{ background:{background}; border:1px solid {border}; border-radius:9px; }}"
                "QLabel { background:transparent; border:none; }"
            )
            inner = QVBoxLayout(card)
            inner.setContentsMargins(12, 7, 12, 7)
            inner.setSpacing(1)
            caption = QLabel(title)
            caption.setStyleSheet(f"font-size:12px; font-weight:800; color:{caption_color};")
            value = QLabel("0.00")
            value.setAlignment(Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter)
            self._card_styles[key] = f"font-size:18px; font-weight:900; color:{value_color};"
            value.setStyleSheet(self._card_styles[key])
            hint = QLabel("")
            hint.setStyleSheet(f"font-size:11px; font-weight:700; color:{caption_color};")
            inner.addWidget(caption)
            inner.addWidget(value)
            inner.addWidget(hint)
            self.card_values[key] = value
            self.card_hints[key] = hint
            layout.addWidget(card, 1)
        return layout

    def _build_toolbar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)
        self.chooser = ColumnChooser(COLUMN_GROUPS, HEADER, DEFAULT_COLUMNS, self.set_visible_columns)
        self.columns_button, self.columns_menu = column_button(self.chooser)
        self.columns_count = self._caption("")
        layout.addWidget(self.columns_button)
        layout.addWidget(self.columns_count)
        layout.addStretch(1)
        self.count_label = self._caption("")
        layout.addWidget(self.count_label)
        return layout

    # -- filters -----------------------------------------------------------------------

    def load_choices(self) -> None:
        super().load_choices()
        # A statement is one contractor's: start on the first one.
        if self.contractor_combo.currentData() is None and self.contractor_combo.count() > 1:
            self.contractor_combo.setCurrentIndex(1)

    # -- columns -----------------------------------------------------------------------

    def set_visible_columns(self, keys: tuple[str, ...] | list[str]) -> None:
        chosen = set(keys)
        self.visible_columns = tuple(key for key in COLUMN_KEYS if key in chosen)
        save_columns(self.settings, SETTINGS_KEY, self.visible_columns)
        self._apply_columns()
        self._fill_table()  # the opening and totals labels sit on the visible columns

    def _apply_columns(self) -> None:
        for column, key in enumerate(COLUMN_KEYS):
            self.table.setColumnHidden(column, key not in self.visible_columns)
        self.columns_count.setText(f"ظاهر {len(self.visible_columns)} من {len(COLUMNS)} عمود")
        self.chooser.sync(self.visible_columns)
        self.fitter.fit()

    # -- running -----------------------------------------------------------------------

    def run_report(self) -> None:
        filters = self.filters()
        self.statement = self.service.statement(**filters)
        totals, contracts = self.statement["totals"], self.statement["contracts"]
        sources = {"totals": totals, "contracts": contracts}
        for key, _title, source in CARDS:
            value = sources[source][key]
            label = self.card_values[key]
            label.setText(_money(value))
            negative = DARK_CARDS.get(key) and "#FECACA" or RED
            label.setStyleSheet(self._card_styles[key] + (f" color:{negative};" if value < 0 else ""))
        self.card_hints["advance_agreed"].setText(f"نسبة {_rate_text(round(contracts['advance_pct'], 3))}% من قيمة العقود")
        self.card_hints["contract_value"].setText(f"{contracts['count']} عقود")
        self.card_hints["advance_deducted"].setText(
            f"حتى {date_text(filters['date_to'])}" if filters["date_to"] else "كل المستخلصات")
        self.card_hints["opening"].setText("قبل " + date_text(filters["date_from"]) if filters["date_from"]
                                           else "الرصيد الجاري في بطاقة المقاول")
        self.card_hints["balance"].setText("له" if totals["balance"] >= 0 else "عليه")
        self.card_hints["net"].setText(f"{totals['extracts_count']} مستخلصات")
        self.card_hints["paid"].setText(f"{totals['payments_count']} دفعات")
        if filters["contractor_id"] is None:
            self.count_label.setText("اختار المقاول لعرض كشف الحساب")
        else:
            self.count_label.setText(f"{totals['extracts_count']} مستخلصات · {totals['payments_count']} دفعات")
        self.chart.set_statement(self.statement)
        self._fill_table()

    def _label_columns(self) -> tuple[int, int]:
        """(first column, span) that the opening / totals label covers: the visible text columns."""
        text_columns = [i for i, key in enumerate(COLUMN_KEYS) if KIND[key] == TEXT_COL]
        visible = [i for i in text_columns if COLUMN_KEYS[i] in self.visible_columns]
        if not visible:
            return -1, 0
        return visible[0], text_columns[-1] - visible[0] + 1

    def _fill_table(self) -> None:
        table = self.table
        table.clearSpans()
        table.setRowCount(0)  # no stale cell from a longer run survives
        self.row_kinds = []
        if self.contractor_combo.currentData() is None:
            self.fitter.fit()
            return
        date_from = self.filters()["date_from"]
        caption = (f"رصيد أول المدة — قبل {date_text(date_from)}" if date_from
                   else "رصيد أول المدة — الرصيد الجاري في بطاقة المقاول")
        self._add_label_row(ROW_OPENING, caption, {"balance": self.statement["opening"]}, OPENING_BG)
        for line in self.statement["lines"]:
            self._add_line(line)
        totals = self.statement["totals"]
        caption = f"الإجمالي — {totals['extracts_count']} مستخلصات · {totals['payments_count']} دفعات"
        self._add_label_row(ROW_TOTAL, caption, totals, TOTAL_BG)
        self.fitter.fit()

    def _new_row(self, kind: str, height: int) -> int:
        index = self.table.rowCount()
        self.table.insertRow(index)
        self.table.setRowHeight(index, height)
        self.row_kinds.append(kind)
        return index

    def _add_line(self, line: dict[str, Any]) -> None:
        payment = line["kind"] == KIND_PAYMENT
        index = self._new_row(ROW_PAYMENT if payment else ROW_EXTRACT, 32)
        for column, key in enumerate(COLUMN_KEYS):
            negative = key == "balance" and line["balance"] < 0
            item = table_item(cell_text(line, key), negative=negative,
                              bold=key in ("net", "paid", "balance"))
            if payment:
                item.setBackground(QBrush(QColor(PAYMENT_BG)))
            if key == "net" and not payment:
                item.setBackground(QBrush(QColor(NET_BG)))
            if key == "balance":
                item.setBackground(QBrush(QColor(BALANCE_BG)))
            if key == "paid" and payment:
                item.setForeground(QBrush(QColor(PAID_COLOR)))
            self.table.setItem(index, column, item)

    def _add_label_row(self, kind: str, text: str, values: dict[str, Any], background: str) -> None:
        index = self._new_row(kind, 36)
        first, span = self._label_columns()
        for column, key in enumerate(COLUMN_KEYS):
            if KIND[key] == AMOUNT_COL and key in values:
                item = table_item(_money(values[key]), bold=True, negative=values[key] < 0)
            else:
                item = table_item(text if column == first else "", bold=True)
            item.setBackground(QBrush(QColor(BALANCE_BG if key == "balance" and kind == ROW_OPENING else background)))
            self.table.setItem(index, column, item)
        if span > 1:
            self.table.setSpan(index, first, 1, span)
