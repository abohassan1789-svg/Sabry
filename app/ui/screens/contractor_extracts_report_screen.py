"""تقرير مستخلصات المقاولين — نموذج 6 «مجمّع حسب المقاول» (2026-09-26).

* Eight total cards over the table: إجمالي المستخلص، صافي الأعمال، الدفعة
  المقدمة، ضرائب الخصم، تأمين الأعمال، التأمينات الاجتماعية، الخصومات الأخرى،
  صافي المستخلص.
* «تحديد أعمدة الجدول»: a checkbox list of all 18 columns. The choice is kept
  per user; the default is the mockup's (every column but the five rates).
* The rows are grouped by contractor (or company, or project, or not at all).
  Each group opens and closes by a click on its row: open, it shows a title row,
  its extracts and «إجمالي …»; closed, one row with its totals.
* «إظهار تفاصيل الخصومات» (user, 2026-10-14, as in كشف حساب مقاول): a line under
  each extract per «خصومات أخرى» (النوع — السبب، المبلغ), with إجمالي الخصومات
  beside the button; kept per user. The «الخصومات الأخرى» card's tooltip adds
  the deductions up per type. No figure changes: they are already in الصافي.

Every figure comes from ``contractor_extracts_report_service``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.contractor_extract_service import deductions_by_type
from app.services.contractor_extracts_report_service import (
    GROUP_COMPANY,
    GROUP_CONTRACTOR,
    GROUP_NONE,
    GROUP_PROJECT,
    ContractorExtractsReportService,
    group_rows,
    report_totals,
)
from app.ui.common.theme import GREEN, TEXT, _button_style
from app.ui.screens.contracting_report_base import (
    DEDUCTION_BG,
    DEDUCTION_COLOR,
    MUTED,
    RED,
    TABLE_QSS,
    TOTAL_BG,
    ColumnChooser,
    ColumnFitter,
    ContractingReportBase,
    column_button,
    date_text,
    deduction_text,
    deductions_toggle,
    load_columns,
    load_flag,
    report_settings,
    save_columns,
    save_flag,
    table_item,
)
from app.ui.screens.contractor_contracts_screen import _money, _rate_text

PERMISSION_BASE = "contracting.contractor_extracts_report"
SETTINGS_KEY = "contractor_extracts_report/columns"
SHOW_DEDUCTIONS_KEY = "contractor_extracts_report/show_deductions"  # the details button, per user

TEXT_COL, RATE_COL, AMOUNT_COL = "text", "rate", "amount"
# The user's columns in their order: (row key, header, kind).
COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("extract_date", "تاريخ\nالمستخلص", TEXT_COL),
    ("company_name", "اسم الشركة", TEXT_COL),
    ("project_name", "اسم المشروع", TEXT_COL),
    ("contractor_name", "اسم المقاول", TEXT_COL),
    ("contract_label", "العقد", TEXT_COL),  # رقم — اسم (2026-10-13)
    ("extract_no", "رقم المستخلص", TEXT_COL),
    ("works_value", "إجمالي\nالمستخلص", AMOUNT_COL),
    ("vat_pct", "نسبة\nالضريبة", RATE_COL),
    ("before_tax", "صافي\nالأعمال", AMOUNT_COL),
    ("advance_payment_pct", "نسبة الدفعة\nالمقدمة", RATE_COL),
    ("advance_payment", "قيمة الدفعة\nالمقدمة", AMOUNT_COL),
    ("withholding_tax_pct", "نسبة ضرائب\nالخصم", RATE_COL),
    ("withholding_tax", "قيمة ضرائب\nالخصم", AMOUNT_COL),
    ("works_insurance_pct", "نسبة تأمين\nالأعمال", RATE_COL),
    ("works_insurance", "قيمة تأمين\nالأعمال", AMOUNT_COL),
    ("social_insurance_pct", "نسبة التأمينات\nالاجتماعية", RATE_COL),
    ("social_insurance", "قيمة التأمينات\nالاجتماعية", AMOUNT_COL),
    ("other_deductions", "خصومات\nأخرى", AMOUNT_COL),
    ("net", "صافي\nالمستخلص", AMOUNT_COL),
)
COLUMN_KEYS = tuple(key for key, _header, _kind in COLUMNS)
KIND = {key: kind for key, _header, kind in COLUMNS}
HEADER = {key: header.replace("\n", " ") for key, header, _kind in COLUMNS}
DEFAULT_COLUMNS = tuple(key for key in COLUMN_KEYS if KIND[key] != RATE_COL)

# The column chooser's groups, as in the mockups.
COLUMN_GROUPS = (
    ("بيانات المستخلص", COLUMN_KEYS[:6]),
    ("الأعمال", COLUMN_KEYS[6:9]),
    ("الاستقطاعات", COLUMN_KEYS[9:18]),
    ("الصافي", COLUMN_KEYS[18:]),
)

# (row key, card title); the last card is the dark one.
CARDS = (
    ("works_value", "إجمالي المستخلص"),
    ("before_tax", "إجمالي صافي الأعمال"),
    ("advance_payment", "إجمالي الدفعة المقدمة"),
    ("withholding_tax", "إجمالي ضرائب الخصم"),
    ("works_insurance", "إجمالي تأمين الأعمال"),
    ("social_insurance", "إجمالي التأمينات الاجتماعية"),
    ("other_deductions", "إجمالي الخصومات الأخرى"),
    ("net", "إجمالي صافي المستخلص"),
)

GROUP_MODES = (
    (GROUP_NONE, "بدون تجميع"),
    (GROUP_CONTRACTOR, "حسب المقاول"),
    (GROUP_COMPANY, "حسب الشركة"),
    (GROUP_PROJECT, "حسب المشروع"),
)

# Row kinds of the table, kept in ``row_kinds`` next to the group key.
ROW_EXTRACT, ROW_GROUP, ROW_SUBTOTAL, ROW_COLLAPSED, ROW_TOTAL = "extract", "group", "subtotal", "collapsed", "total"
ROW_DEDUCTION = "deduction"  # one «خصومات أخرى» line under its extract (the details button)
GROUP_BG = "#F1F5F9"
SUBTOTAL_BG = "#F0FDF4"
COLLAPSED_BG = "#FAFAF7"
NET_BG = "#ECFDF3"


def cell_text(row: dict[str, Any], key: str) -> str:
    """How a report value is written in a cell (date, text, rate or money)."""
    value = row.get(key)
    if key == "extract_date":
        return date_text(value)
    kind = KIND[key]
    if kind == RATE_COL:
        return f"{_rate_text(value)}%"
    if kind == AMOUNT_COL:
        return _money(value)
    return str(value or "")


def _count_text(count: int) -> str:
    return f"{count} مستخلص" if count == 1 else f"{count} مستخلصات"


class ContractorExtractsReportScreen(ContractingReportBase):
    TITLE = "تقرير مستخلصات المقاولين"
    ICON = "🧾"
    PERMISSION_BASE = PERMISSION_BASE
    CONTRACT_FILTER = True  # «العقد» (user, 2026-10-13)

    def __init__(self, service: ContractorExtractsReportService | None = None,
                 parent: QWidget | None = None, settings: QSettings | None = None) -> None:
        self.settings = settings or report_settings()
        self.rows: list[dict[str, Any]] = []
        self.totals: dict[str, Any] = report_totals([])
        self.group_mode = GROUP_CONTRACTOR
        self.collapsed: set[Any] = set()
        self.row_kinds: list[tuple[str, Any]] = []
        self.visible_columns = load_columns(self.settings, SETTINGS_KEY, COLUMN_KEYS, DEFAULT_COLUMNS,
                                            added=("contract_label",))
        self.show_deductions = load_flag(self.settings, SHOW_DEDUCTIONS_KEY)
        super().__init__(service or ContractorExtractsReportService(), parent)

    # -- layout ------------------------------------------------------------------------

    def _build_body(self, root: QVBoxLayout) -> None:
        root.addLayout(self._build_cards())
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
        self.table.cellClicked.connect(self._row_clicked)
        root.addWidget(self.table, 1)
        self._apply_columns()

    def _build_cards(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)
        self.card_values: dict[str, QLabel] = {}
        self._card_styles: dict[str, str] = {}
        for key, title in CARDS:
            dark = key == "net"
            card = QFrame()
            card.setObjectName(f"card_{key}")
            background, border, caption_color, value_color = (
                (GREEN, GREEN, "#D1FAE5", "#FFFFFF") if dark else ("#FFFFFF", "#E5EAF0", MUTED, TEXT))
            card.setStyleSheet(
                f"QFrame#card_{key} {{ background:{background}; border:1px solid {border}; border-radius:9px; }}"
                "QLabel { background:transparent; border:none; }"
            )
            inner = QVBoxLayout(card)
            inner.setContentsMargins(12, 8, 12, 8)
            inner.setSpacing(2)
            caption = QLabel(title)
            caption.setStyleSheet(f"font-size:12px; font-weight:800; color:{caption_color};")
            value = QLabel("0.00")
            value.setAlignment(Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter)
            self._card_styles[key] = f"font-size:18px; font-weight:900; color:{value_color};"
            value.setStyleSheet(self._card_styles[key])
            inner.addWidget(caption)
            inner.addWidget(value)
            self.card_values[key] = value
            if key == "other_deductions":
                self.deductions_card = card  # its tooltip lists the deductions per type
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
        layout.addSpacing(18)

        self.group_buttons = QButtonGroup(self)
        self.group_buttons.setExclusive(True)
        segment = QHBoxLayout()
        segment.setSpacing(0)
        for index, (mode, text) in enumerate(GROUP_MODES):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setChecked(mode == self.group_mode)
            button.setFixedHeight(34)
            button.setProperty("mode", mode)
            button.setStyleSheet(
                f"QPushButton {{ background:#FFFFFF; color:{TEXT}; border:1px solid #CBD5E1; padding:0 14px; "
                "font-size:13px; font-weight:800; }"
                f"QPushButton:checked {{ background:{GREEN}; color:#FFFFFF; border-color:{GREEN}; }}"
            )
            self.group_buttons.addButton(button, index)
            segment.addWidget(button)
        self.group_buttons.idClicked.connect(lambda index: self.set_group_mode(GROUP_MODES[index][0]))
        layout.addLayout(segment)
        self.expand_button = QPushButton("فتح الكل")
        self.collapse_button = QPushButton("قفل الكل")
        for button in (self.expand_button, self.collapse_button):
            button.setFixedHeight(34)
            button.setStyleSheet(_button_style("#64748B", "#475569"))
            layout.addWidget(button)
        self.expand_button.clicked.connect(self.expand_all)
        self.collapse_button.clicked.connect(self.collapse_all)
        layout.addSpacing(18)
        # الخصومات الأخرى تحت كل مستخلص, with their total beside the button (user, 2026-10-14).
        self.deductions_toggle = deductions_toggle(self.show_deductions)
        self.deductions_toggle.toggled.connect(self._on_deductions_toggled)
        self.deductions_total = self._caption("")
        self.deductions_total.setStyleSheet(f"font-size:13px; font-weight:900; color:{DEDUCTION_COLOR};")
        layout.addWidget(self.deductions_toggle)
        layout.addWidget(self.deductions_total)
        self._update_deductions_button()
        layout.addStretch(1)
        self.count_label = self._caption("")
        layout.addWidget(self.count_label)
        return layout

    # -- columns -----------------------------------------------------------------------

    def set_visible_columns(self, keys: tuple[str, ...] | list[str]) -> None:
        chosen = set(keys)
        self.visible_columns = tuple(key for key in COLUMN_KEYS if key in chosen)
        save_columns(self.settings, SETTINGS_KEY, self.visible_columns)
        self._apply_columns()
        self._fill_table()  # the titles and totals labels sit on the visible columns

    def _apply_columns(self) -> None:
        for column, key in enumerate(COLUMN_KEYS):
            self.table.setColumnHidden(column, key not in self.visible_columns)
        self.columns_count.setText(f"ظاهر {len(self.visible_columns)} من {len(COLUMNS)} عمود")
        self.chooser.sync(self.visible_columns)
        self.fitter.fit()

    # -- الخصومات الأخرى -----------------------------------------------------------------

    def _on_deductions_toggled(self, checked: bool) -> None:
        self.show_deductions = checked
        save_flag(self.settings, SHOW_DEDUCTIONS_KEY, checked)
        self._update_deductions_button()
        self._fill_table()

    def _update_deductions_button(self) -> None:
        self.deductions_toggle.setText("إخفاء تفاصيل الخصومات" if self.show_deductions else "إظهار تفاصيل الخصومات")
        self.deductions_total.setText(f"إجمالي الخصومات: {_money(self.totals['other_deductions'])}")

    def _update_deductions_card(self) -> None:
        """The «الخصومات الأخرى» card's tooltip: the report's deductions per type, biggest first."""
        types = deductions_by_type([line for row in self.rows for line in row.get("deductions") or []])
        self.deductions_card.setToolTip(
            "الخصومات الأخرى حسب النوع:\n" + "\n".join(f"{kind}: {_money(amount)}" for kind, amount in types)
            if types else "مفيش خصومات أخرى في التقرير ده")

    # -- grouping ----------------------------------------------------------------------

    def set_group_mode(self, mode: str) -> None:
        self.group_mode = mode
        self.collapsed.clear()
        button = self.group_buttons.button([m for m, _t in GROUP_MODES].index(mode))
        button.setChecked(True)
        self._fill_table()

    def expand_all(self) -> None:
        self.collapsed.clear()
        self._fill_table()

    def collapse_all(self) -> None:
        self.collapsed = {group["key"] for group in group_rows(self.rows, self.group_mode)}
        self._fill_table()

    def toggle_group(self, key: Any) -> None:
        self.collapsed.symmetric_difference_update({key})
        self._fill_table()

    def _row_clicked(self, row: int, _column: int) -> None:
        kind, key = self.row_kinds[row] if row < len(self.row_kinds) else ("", None)
        if kind in (ROW_GROUP, ROW_COLLAPSED):
            self.toggle_group(key)

    # -- running -----------------------------------------------------------------------

    def run_report(self) -> None:
        self.rows = self.service.report(**self.filters())
        self.totals = report_totals(self.rows)
        known = {group["key"] for group in group_rows(self.rows, self.group_mode)}
        self.collapsed &= known
        for key, label in self.card_values.items():
            label.setText(_money(self.totals[key]))
            label.setStyleSheet(self._card_styles[key] + (f" color:{RED};" if self.totals[key] < 0 else ""))
        self.count_label.setText(f"عدد المستخلصات: {self.totals['count']}")
        self._update_deductions_button()
        self._update_deductions_card()
        self._fill_table()

    def _label_columns(self) -> tuple[int, int]:
        """(first column, span) that a title or totals label covers: the visible text columns."""
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
        groups = group_rows(self.rows, self.group_mode)
        grouped = self.group_mode != GROUP_NONE
        for button in (self.expand_button, self.collapse_button):
            button.setEnabled(grouped and bool(groups))
        if not grouped:
            for row in self.rows:
                self._add_extract(row)
        for group in groups:
            count = _count_text(len(group["rows"]))
            if group["key"] in self.collapsed:
                self._add_totals(ROW_COLLAPSED, group["key"], f"＋  {group['name']}   ({count})",
                                 group["totals"], COLLAPSED_BG)
                continue
            self._add_title(group["key"], f"－  {group['name']}   ({count})")
            for row in group["rows"]:
                self._add_extract(row)
            self._add_totals(ROW_SUBTOTAL, group["key"], f"إجمالي {group['name']}", group["totals"], SUBTOTAL_BG)
        label = "الإجمالي العام" if grouped else "الإجمالي"
        self._add_totals(ROW_TOTAL, None, f"{label} — {_count_text(self.totals['count'])}", self.totals, TOTAL_BG)
        self.fitter.fit()

    def _new_row(self, kind: str, key: Any, height: int) -> int:
        index = self.table.rowCount()
        self.table.insertRow(index)
        self.table.setRowHeight(index, height)
        self.row_kinds.append((kind, key))
        return index

    def _add_extract(self, row: dict[str, Any]) -> None:
        index = self._new_row(ROW_EXTRACT, row.get("extract_id"), 34)
        for column, key in enumerate(COLUMN_KEYS):
            kind = KIND[key]
            value = row.get(key)
            item = table_item(cell_text(row, key), negative=kind == AMOUNT_COL and Decimal(value or 0) < 0,
                              bold=key in ("contractor_name", "net"))
            if key == "net":
                item.setBackground(QBrush(QColor(NET_BG)))
            self.table.setItem(index, column, item)
        if self.show_deductions:
            for deduction in row.get("deductions") or []:
                self._add_deduction_row(row.get("extract_id"), deduction)

    def _add_deduction_row(self, extract_id: Any, deduction: dict[str, Any]) -> None:
        """«• النوع — السبب» across the text columns; the amount under «خصومات أخرى» when it is
        shown, else in parentheses under صافي المستخلص, else after the text."""
        index = self._new_row(ROW_DEDUCTION, extract_id, 26)
        first, span = self._label_columns()
        amount = _money(deduction.get("amount"))
        if "other_deductions" in self.visible_columns:
            target, shown = "other_deductions", amount
        elif "net" in self.visible_columns:
            target, shown = "net", f"({amount})"
        else:
            target, shown = None, ""
        text = deduction_text(deduction) + ("" if target else f"  ({amount})")
        for column, key in enumerate(COLUMN_KEYS):
            item = table_item(text if column == first else (shown if key == target else ""))
            item.setBackground(QBrush(QColor(DEDUCTION_BG)))
            item.setForeground(QBrush(QColor(DEDUCTION_COLOR)))
            self.table.setItem(index, column, item)
        if span > 1:
            self.table.setSpan(index, first, 1, span)

    def _add_title(self, key: Any, text: str) -> None:
        index = self._new_row(ROW_GROUP, key, 34)
        # The title sits on the first visible column and spans the whole row.
        first = next((i for i, k in enumerate(COLUMN_KEYS) if k in self.visible_columns), 0)
        for column in range(len(COLUMNS)):
            item = table_item(text if column == first else "", bold=True)
            item.setBackground(QBrush(QColor(GROUP_BG)))
            item.setToolTip("اضغط لقفل المجموعة")
            self.table.setItem(index, column, item)
        if first < len(COLUMNS) - 1:
            self.table.setSpan(index, first, 1, len(COLUMNS) - first)

    def _add_totals(self, kind: str, key: Any, text: str, totals: dict[str, Any], background: str) -> None:
        index = self._new_row(kind, key, 36)
        first, span = self._label_columns()
        for column, column_key in enumerate(COLUMN_KEYS):
            if KIND[column_key] == AMOUNT_COL:
                negative = totals[column_key] < 0
                item = table_item(_money(totals[column_key]), bold=True, negative=negative)
                if kind == ROW_SUBTOTAL and not negative:
                    item.setForeground(QBrush(QColor(GREEN)))
            else:
                item = table_item(text if column == first else "", bold=True)
                if kind == ROW_SUBTOTAL:
                    item.setForeground(QBrush(QColor(GREEN)))
            item.setBackground(QBrush(QColor(background)))
            if kind == ROW_COLLAPSED:
                item.setToolTip("اضغط لفتح المجموعة")
            self.table.setItem(index, column, item)
        if span > 1:
            self.table.setSpan(index, first, 1, span)
