"""تقرير كشف حساب مقاول — نموذج 10 «رسم حركة الرصيد + الكشف» (2026-10-02).

* Four cards of four figures (user, 2026-10-07): one per نوع الحساب — الرصيد الجاري،
  تأمين الأعمال، التأمينات الاجتماعية: رصيد أول المدة، مستخلصات، دفعات، متبقي — and
  the contracts' advance (قيمة العقد، الدفعة المقدمة، المخصوم، المتبقي).
* إجمالي ضرائب الخصم (user, 2026-10-07): a fifth card, shown only — the card's
  ضرائب الخصم + the extracts' ضريبة الخصم; no balance uses it.
* A line chart of the three running balances, one line per نوع الحساب.
* One tab per نوع الحساب over the statement: رصيد أول المدة first, then the
  extracts and that type's payments by date, each with its الرصيد التراكمي, and a
  totals row. «تحديد أعمدة الجدول» picks the user's columns (plus «نوع الحساب»);
  each tab keeps its own choice per user (user, 2026-10-07). A tab opens on the
  movement's identity and its three figures: what the extracts add to that type
  (صافي المستخلص / قيمة تأمين الأعمال / قيمة التأمينات الاجتماعية)، التحصيلات، الرصيد التراكمي.

Every figure comes from ``contractor_statement_report_service``.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QTabBar,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.contractor_payment_service import (
    ACCOUNT_TYPES,
    CURRENT_BALANCE,
    SOCIAL_INSURANCE,
    WORKS_INSURANCE,
)
from app.services.contractor_statement_report_service import (
    ACCOUNT_HELD,
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
    ("account_type", "نوع الحساب", TEXT_COL),  # user, 2026-10-07
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
# Each tab opens on its own three figures (user, 2026-10-07): the identity of the movement,
# what the extracts add to that نوع الحساب, the collections and the running balance.
IDENTITY_COLUMNS = ("date", "contractor_name", "extract_no", "account_type")
TAB_DEFAULTS: dict[str, tuple[str, ...]] = {
    CURRENT_BALANCE: IDENTITY_COLUMNS + ("net", "paid", "balance"),
    WORKS_INSURANCE: IDENTITY_COLUMNS + ("works_insurance", "paid", "balance"),
    SOCIAL_INSURANCE: IDENTITY_COLUMNS + ("social_insurance", "paid", "balance"),
}
TAB_SETTINGS = {CURRENT_BALANCE: "current", WORKS_INSURANCE: "works_insurance",
                SOCIAL_INSURANCE: "social_insurance"}  # each tab's own saved choice

COLUMN_GROUPS = (
    ("بيانات الحركة", ("date", "contractor_name", "extract_no", "account_type")),
    ("المستخلص", ("works_value", "before_tax", "net")),
    ("الاستقطاعات (نسبة وقيمة)", tuple(key for key in COLUMN_KEYS[COLUMN_KEYS.index("withholding_tax_pct"):
                                                               COLUMN_KEYS.index("net")] if key != "before_tax")),
    ("الحساب", ("paid", "balance")),
)

# The cards (user, 2026-10-07): one per نوع الحساب, four figures each, then the contracts' advance.
# (key, title, accent, the opening's caption on the card, figures: (figure key, caption)).
ACCOUNT_FIGURES = (("opening", "رصيد أول المدة"), ("held", "مستخلصات"), ("paid", "دفعات"), ("balance", "متبقي"))
ACCOUNT_CARDS = (
    (CURRENT_BALANCE, "الرصيد الجاري", GREEN, "الرصيد الجاري", ACCOUNT_FIGURES),
    (WORKS_INSURANCE, "تأمين الأعمال", "#0369A1", "تأمين الأعمال", ACCOUNT_FIGURES),
    (SOCIAL_INSURANCE, "التأمينات الاجتماعية", "#7C3AED", "التأمينات الاجتماعية", ACCOUNT_FIGURES),
)
CONTRACTS_CARD = ("contracts", "الدفعة المقدمة من العقود", "#B45309", "",
                  (("contract_value", "قيمة العقد"), ("advance_agreed", "الدفعة المقدمة"),
                   ("advance_deducted", "المخصوم"), ("remaining_advance", "المتبقي")))
# Shown only: the card's ضرائب الخصم + the extracts' (user, 2026-10-07); no balance uses it.
WITHHOLDING_CARD = ("withholding", "إجمالي ضرائب الخصم", "#BE123C", "",
                    (("opening", "رصيد أول المدة"), ("held", "مستخلصات"), ("total", "الإجمالي")))
CARDS = ACCOUNT_CARDS + (CONTRACTS_CARD, WITHHOLDING_CARD)
ACCENT = {key: accent for key, _title, accent, _field, _figures in CARDS}
CARD_FIELD = {key: field for key, _title, _accent, field, _figures in ACCOUNT_CARDS}  # the contractor card's field
TAB_TITLES = {key: title for key, title, _accent, _field, _figures in ACCOUNT_CARDS}

ROW_OPENING, ROW_EXTRACT, ROW_PAYMENT, ROW_TOTAL = "opening", "extract", "payment", "total"
OPENING_BG = "#EEF4F4"
PAYMENT_BG = "#F3FAF5"
BALANCE_BG = "#FFF8EA"
NET_BG = "#ECFDF3"
PAID_COLOR = "#15803D"


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
    if line["kind"] == KIND_PAYMENT and key not in ("contractor_name", "account_type", "paid", "balance"):
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
    """«حركة الرصيد التراكمي»: one line per نوع الحساب — the openings, then one point per
    movement of the period (an extract moves the three, a payment its own type)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(150)
        self.setLayoutDirection(Qt.LeftToRight)  # time runs left to right; the title is placed by hand
        self.series: dict[str, list[float]] = {}

    def set_statement(self, statement: dict[str, Any]) -> None:
        timeline = statement.get("timeline") or []
        moved = len(timeline) > 1 or any(timeline and value for value in timeline[0]["balances"].values())
        self.series = ({account: [float(point["balances"][account]) for point in timeline]
                        for account in ACCOUNT_TYPES} if moved else {})
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
        for index, account in enumerate(ACCOUNT_TYPES):  # the legend
            x = 20 + index * 150
            painter.setPen(QPen(QColor(ACCENT[account]), 3))
            painter.drawLine(QPointF(x - 6, 16), QPointF(x + 6, 16))
            painter.setPen(QColor(MUTED))
            painter.drawText(QRectF(x + 12, 6, 130, 20), Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter,
                             TAB_TITLES[account])
        if not self.series:
            painter.setPen(QColor(MUTED))
            painter.drawText(frame, Qt.AlignCenter, "مفيش حركة في الفترة دي")
            return
        values = [value for line in self.series.values() for value in line]
        # The balances' own range, so a large opening does not flatten the lines;
        # zero joins it only when a balance goes below it.
        top, bottom = max(values), min(values)
        if bottom < 0 < top or top < 0:
            top = max(top, 0.0)
        span = (top - bottom) or max(abs(top), 1.0)
        if top == bottom:
            bottom -= span / 2
        left, right, upper, lower = 40.0, frame.width() - 90.0, 40.0, frame.height() - 14.0
        count = len(next(iter(self.series.values())))

        def at(index: int, value: float) -> QPointF:
            x = (left + right) / 2 if count == 1 else left + index * (right - left) / (count - 1)
            return QPointF(x, lower - (value - bottom) / span * (lower - upper))

        if bottom < 0 <= top:  # where zero is, once a balance went below it
            zero = at(0, 0.0).y()
            painter.setPen(QPen(QColor("#FCA5A5"), 1, Qt.DashLine))
            painter.drawLine(QPointF(left, zero), QPointF(right, zero))
        ends = []
        for account, line_values in self.series.items():
            color = QColor(ACCENT[account])
            points = [at(i, v) for i, v in enumerate(line_values)]
            painter.setPen(QPen(color, 2.5))
            painter.drawPolyline(QPolygonF(points))
            painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
            painter.setBrush(color)
            for point in points:
                painter.drawEllipse(point, 3.5, 3.5)
            ends.append((points[-1], line_values[-1], account))
        # Each line ends on its balance; labels that would overlap are pushed apart.
        last_y = None
        for point, value, account in sorted(ends, key=lambda end: end[0].y()):
            y = point.y() if last_y is None else max(point.y(), last_y + 14)
            last_y = y
            painter.setPen(QColor(RED if value < 0 else ACCENT[account]))
            painter.drawText(QRectF(point.x() + 6, y - 8, 84, 16),
                             Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter, _short_money(value))
        painter.end()


class ContractorStatementReportScreen(ContractingReportBase):
    TITLE = "تقرير كشف حساب مقاول"
    ICON = "📒"
    PERMISSION_BASE = PERMISSION_BASE

    def __init__(self, service: ContractorStatementReportService | None = None,
                 parent: QWidget | None = None, settings: QSettings | None = None) -> None:
        self.settings = settings or report_settings()
        self.statement: dict[str, Any] = empty_statement()
        self.account = CURRENT_BALANCE  # the tab on show
        self.row_kinds: list[str] = []
        self.tab_columns = self._load_columns()
        super().__init__(service or ContractorStatementReportService(), parent)

    @staticmethod
    def _settings_key(account: str) -> str:
        return f"{SETTINGS_KEY}/{TAB_SETTINGS[account]}"

    def _load_columns(self) -> dict[str, tuple[str, ...]]:
        """Every tab's saved choice, or that tab's own three figures if never saved."""
        return {account: load_columns(self.settings, self._settings_key(account), COLUMN_KEYS, TAB_DEFAULTS[account])
                for account in ACCOUNT_TYPES}

    @property
    def visible_columns(self) -> tuple[str, ...]:
        return self.tab_columns[self.account]

    # -- layout ------------------------------------------------------------------------

    def _build_body(self, root: QVBoxLayout) -> None:
        root.addLayout(self._build_cards())
        self.chart = BalanceChart()
        root.addWidget(self.chart)
        root.addLayout(self._build_toolbar())
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("statement_table")
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
        self.fitter.PADDING = 12  # «نوع الحساب» joined the user's 14 default columns: keep them on one screen
        root.addWidget(self.table, 1)
        self._apply_columns()

    def _build_cards(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)
        self.card_values: dict[tuple[str, str], QLabel] = {}
        self.card_hints: dict[str, QLabel] = {}
        self._card_styles: dict[tuple[str, str], str] = {}
        for key, title, accent, _field, figures in CARDS:
            card = QFrame()
            card.setObjectName(f"card_{len(self.card_hints)}")
            card.setStyleSheet(
                f"QFrame#{card.objectName()} {{ background:#FFFFFF; border:1px solid #E5EAF0; "
                f"border-top:3px solid {accent}; border-radius:9px; }}"
                "QLabel { background:transparent; border:none; }"
            )
            inner = QVBoxLayout(card)
            inner.setContentsMargins(12, 6, 12, 7)
            inner.setSpacing(3)
            head = QHBoxLayout()
            caption = QLabel(title)
            caption.setStyleSheet(f"font-size:13px; font-weight:900; color:{accent};")
            hint = QLabel("")
            hint.setStyleSheet(f"font-size:11px; font-weight:700; color:{MUTED};")
            head.addWidget(caption)
            head.addStretch(1)
            head.addWidget(hint)
            inner.addLayout(head)
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(0)
            for column, (figure, figure_caption) in enumerate(figures):
                last = column == len(figures) - 1  # المتبقي stands out
                name = QLabel(figure_caption)
                name.setStyleSheet(f"font-size:11px; font-weight:800; color:{accent if last else MUTED};")
                value = QLabel("0.00")
                value.setAlignment(Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter)
                style = f"font-size:{15 if last else 13}px; font-weight:900; color:{accent if last else TEXT};"
                value.setStyleSheet(style)
                grid.addWidget(name, 0, column)
                grid.addWidget(value, 1, column)
                grid.setColumnStretch(column, 1)
                self.card_values[(key, figure)] = value
                self._card_styles[(key, figure)] = style
            inner.addLayout(grid)
            self.card_hints[key] = hint
            layout.addWidget(card, 1)
        return layout

    def _build_toolbar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)
        self.chooser = ColumnChooser(COLUMN_GROUPS, HEADER, DEFAULT_COLUMNS, self.set_visible_columns)
        # «استعادة الافتراضي» brings back the open tab's own three figures.
        self.chooser.default_button.clicked.disconnect()
        self.chooser.default_button.clicked.connect(
            lambda _=False: self.set_visible_columns(TAB_DEFAULTS[self.account]))
        self.columns_button, self.columns_menu = column_button(self.chooser)
        self.columns_count = self._caption("")
        # One statement per نوع الحساب (user, 2026-10-07).
        self.account_tabs = QTabBar()
        self.account_tabs.setDrawBase(False)
        self.account_tabs.setExpanding(False)
        for account in ACCOUNT_TYPES:
            self.account_tabs.addTab(TAB_TITLES[account])
        self.account_tabs.setStyleSheet(
            "QTabBar::tab { background:#FFFFFF; color:#334155; border:1px solid #D9E2EC; border-radius:8px; "
            "padding:6px 18px; margin-left:6px; font-size:13px; font-weight:900; }"
            f"QTabBar::tab:selected {{ background:{GREEN}; color:#FFFFFF; border-color:{GREEN}; }}"
        )
        self.account_tabs.currentChanged.connect(self._on_account_tab)
        layout.addWidget(self.account_tabs)
        layout.addSpacing(12)
        layout.addWidget(self.columns_button)
        layout.addWidget(self.columns_count)
        layout.addStretch(1)
        self.count_label = self._caption("")
        layout.addWidget(self.count_label)
        return layout

    def _on_account_tab(self, index: int) -> None:
        self.account = ACCOUNT_TYPES[index] if 0 <= index < len(ACCOUNT_TYPES) else CURRENT_BALANCE
        self._update_count()
        self._apply_columns()  # each tab shows its own columns
        self._fill_table()

    def _account_statement(self) -> dict[str, Any]:
        return (self.statement.get("accounts") or {}).get(self.account) or self.statement

    def _update_count(self) -> None:
        totals = self._account_statement()["totals"]
        who = "كل المقاولين — " if self.filters()["contractor_id"] is None else ""
        self.count_label.setText(f"{who}{TAB_TITLES[self.account]}: {totals['extracts_count']} مستخلصات · "
                                 f"{totals['payments_count']} دفعات")

    # -- filters -----------------------------------------------------------------------

    def load_choices(self) -> None:
        super().load_choices()
        # A statement is one contractor's: start on the first one.
        if self.contractor_combo.currentData() is None and self.contractor_combo.count() > 1:
            self.contractor_combo.setCurrentIndex(1)

    # -- columns -----------------------------------------------------------------------

    def set_visible_columns(self, keys: tuple[str, ...] | list[str]) -> None:
        chosen = set(keys)
        self.tab_columns[self.account] = tuple(key for key in COLUMN_KEYS if key in chosen)
        save_columns(self.settings, self._settings_key(self.account), self.visible_columns)
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
        accounts, contracts = self.statement["accounts"], self.statement["contracts"]
        sources = {account: accounts[account]["totals"] for account in ACCOUNT_TYPES}
        sources["contracts"] = contracts
        sources["withholding"] = withholding = self.statement["withholding"]
        for key, _title, _accent, _field, figures in CARDS:
            for figure, _caption in figures:
                value = sources[key][figure]
                label = self.card_values[(key, figure)]
                label.setText(_money(value))
                label.setStyleSheet(self._card_styles[(key, figure)] + (f" color:{RED};" if value < 0 else ""))
        for account in ACCOUNT_TYPES:
            totals = sources[account]
            self.card_hints[account].setText(
                f"{totals['extracts_count']} مستخلصات · {totals['payments_count']} دفعات"
                + (f" · من {date_text(filters['date_from'])}" if filters["date_from"] else ""))
        self.card_hints["contracts"].setText(
            f"{contracts['count']} عقود · نسبة {_rate_text(round(contracts['advance_pct'], 3))}%"
            + (f" · حتى {date_text(filters['date_to'])}" if filters["date_to"] else ""))
        self.card_hints["withholding"].setText(f"{withholding['extracts_count']} مستخلصات · للعرض فقط")
        self._update_count()
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
        statement = self._account_statement()
        date_from = self.filters()["date_from"]
        cards = "بطاقات كل المقاولين" if self.contractor_combo.currentData() is None else "بطاقة المقاول"
        caption = (f"رصيد أول المدة — {TAB_TITLES[self.account]} قبل {date_text(date_from)}" if date_from
                   else f"رصيد أول المدة — {CARD_FIELD[self.account]} في {cards}")
        self._add_label_row(ROW_OPENING, caption, {"balance": statement["opening"]}, OPENING_BG)
        for line in statement["lines"]:
            self._add_line(line)
        totals = statement["totals"]
        caption = (f"الإجمالي — {TAB_TITLES[self.account]} — {totals['extracts_count']} مستخلصات · "
                   f"{totals['payments_count']} دفعات")
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
        held = ACCOUNT_HELD[self.account]  # what an extract adds to the tab's balance
        for column, key in enumerate(COLUMN_KEYS):
            negative = key == "balance" and line["balance"] < 0
            item = table_item(cell_text(line, key), negative=negative,
                              bold=key in (held, "paid", "balance"))
            if payment:
                item.setBackground(QBrush(QColor(PAYMENT_BG)))
            if key == held and not payment:
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
