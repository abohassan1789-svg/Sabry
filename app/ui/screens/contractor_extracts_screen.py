"""شاشة مستخلصات المقاولين — النموذجان 8 و9 كتبويبين (2026-09-25).

As with عقود المقاولين, the user asked for two mockups side by side as tabs:

* «بطاقة المقاول» (نموذج 8): pick a contractor and one of his contracts at the
  top (with the contract's value / executed / remaining / count), see its
  extracts as cards, and edit the selected one in the panel on the left.
* «مؤشرات العقد» (نموذج 9): pick a contract, see its KPIs (value, executed,
  remaining, net due, progress) and the extract form beside the history table.

The contract number brings in the contractor, company, project, value and the
contract's four rates — shown for reference only. The arithmetic lives in
``contractor_extract_service.extract_amounts``. Both tabs work on the same
contract and extract; switching tabs is locked while editing, and the contract
can be changed while creating a new extract (not while editing one).
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from PySide6.QtCore import QDate, QRegularExpression, Qt, QTimer
from PySide6.QtGui import QKeySequence, QRegularExpressionValidator, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.security.session_context import SESSION
from app.services.contracting_approval import ApprovalError, approved_only
from app.services.contractor_contract_service import RATE_FIELDS, to_decimal
from app.services.contractor_extract_service import (
    DEFAULT_VAT_PCT,
    DEFAULT_WORKS_INSURANCE_PCT,
    SOCIAL_OPTIONS,
    WITHHOLDING_OPTIONS,
    ContractorExtractService,
    ExtractError,
    advance_balance,
    contract_progress,
    extract_amounts,
)
from app.ui.common.theme import GREEN, GREEN_DARK, TEXT, _button_style
from app.ui.dialogs.contractor_extract_picker import ContractorExtractPickerDialog
from app.ui.screens.approval_controls import ApprovalControls, draft_suffix, status_chip
from app.ui.common.live_lists import notify_data_changed
from app.ui.screens.contractor_contracts_screen import (
    _COMBO_QSS,
    _EDITOR_QSS,
    RATE_COLORS,
    _caption,
    _card_frame,
    _money,
    _rate_text,
    _select_data,
)

PERMISSION_BASE = "contracting.contractor_extracts"
BLUE = "#0369A1"
MUTED = "#475569"
AMBER = "#B45309"
RED = "#B91C1C"
CARD_COLUMNS = 2
TAB_CARDS, TAB_KPI = 0, 1

# key -> (rate column, control kind, colour, what the rate is applied to)
LINES: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("advance_payment", "نسبة الدفعة المقدمة", "advance_payment_pct", "spin", "#0369A1", "× إجمالي المستخلص"),
    ("withholding_tax", "نسبة ضرائب الخصم", "withholding_tax_pct", "list", "#B45309", "× صافي الأعمال"),
    ("works_insurance", "نسبة تأمين الأعمال", "works_insurance_pct", "spin", "#6D28D9", "× إجمالي المستخلص"),
    ("social_insurance", "نسبة التأمينات الاجتماعية", "social_insurance_pct", "list", "#0F766E", "× إجمالي المستخلص"),
)
LIST_OPTIONS = {"withholding_tax_pct": WITHHOLDING_OPTIONS, "social_insurance_pct": SOCIAL_OPTIONS}
NET_FORMULA = ("الصافي = إجمالي المستخلص − المقدمة − ضريبة الخصم − تأمين الأعمال − التأمينات − خصومات أخرى")


def _date_text(value: Any) -> str:
    return f"{value:%Y-%m-%d}" if isinstance(value, (datetime.date, datetime.datetime)) else str(value or "")


def contract_info_html(contract: dict[str, Any] | None) -> str:
    """One line of what the contract number brings in, plus its rates — for reference."""
    if not contract:
        return "<span style='color:#94A3B8'>اختار العقد لعرض بياناته.</span>"
    chips = " ".join(
        f"<span style='color:{RATE_COLORS[key][0]}; background:{RATE_COLORS[key][1]};'>&nbsp;"
        f"{label.replace('نسبة ', '')} {_rate_text(contract.get(key))}%&nbsp;</span>"
        for key, label in RATE_FIELDS
    )
    return (
        f"<b>{contract.get('contract_no') or ''}</b> · {contract.get('contractor_name') or ''} · "
        f"{contract.get('company_name') or ''} · {contract.get('project_name') or ''} · "
        f"قيمة العقد <b>{_money(contract.get('contract_value'))}</b><br>"
        f"<span style='color:{MUTED}'>نسب العقد (للعلم فقط):</span> {chips}"
    )


class RateCombo(QComboBox):
    """A rate list the user can also type into (user, 2026-10-02): the usual
    choices drop down, any other rate 0–100 can be written in, «%» optional."""

    def __init__(self, options: tuple[Decimal, ...], color: str) -> None:
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMinimumHeight(36)
        self.setFixedWidth(110)
        self.setLayoutDirection(Qt.LeftToRight)
        self.setStyleSheet(
            f"QComboBox {{ background:#FFFFFF; border:1.5px solid {color}; border-radius:7px; "
            f"padding:4px 8px; font-size:15px; font-weight:900; color:{color}; }}"
            "QComboBox:disabled { background:#F8FAFC; }"
        )
        for option in options:
            self.addItem(f"{_rate_text(option)}%", str(option))
        self.lineEdit().setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,3}([.,]\d{0,3})?\s*%?")))
        self.lineEdit().editingFinished.connect(lambda: self.set_value(self.value()))

    def value(self) -> Decimal:
        return to_decimal(self.currentText().replace(",", "."))

    def set_value(self, value: Any) -> None:
        wanted = to_decimal(value)
        index = next((i for i in range(self.count()) if to_decimal(self.itemData(i)) == wanted), -1)
        if index >= 0:
            self.setCurrentIndex(index)
        self.setEditText(f"{_rate_text(wanted)}%")


class ExtractForm(QWidget):
    """One extract's inputs and every computed amount. ``wide`` = tab 9's layout."""

    def __init__(self, wide: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.wide = wide
        self._suggested_no = ""
        self._ready = False  # recalc() waits until every widget exists
        # The advance-payment balance needs the contract and its other extracts.
        self._contract: dict[str, Any] | None = None
        self._extracts: list[dict[str, Any]] = []
        self._extract_id: Any = None

        self.extract_no = self._line_edit("رقم المستخلص", ltr=True)
        self.extract_date = QDateEdit()
        self.extract_date.setCalendarPopup(True)
        self.extract_date.setDisplayFormat("yyyy-MM-dd")
        self.extract_date.setDate(QDate.currentDate())
        self.extract_date.setMinimumHeight(38)
        self.extract_date.setLayoutDirection(Qt.LeftToRight)
        self.extract_date.setStyleSheet(_EDITOR_QSS)
        self.extract_date.dateChanged.connect(self.recalc)  # the date orders the advance balance
        self.works_value = self._line_edit("0.00", ltr=True)
        self.works_value.textChanged.connect(self.recalc)
        self.works_value.editingFinished.connect(lambda: self._format_money(self.works_value))
        self.vat_pct = self._spin("#475569")
        self.vat_pct.setValue(float(DEFAULT_VAT_PCT))
        self.before_tax = self._line_edit("", ltr=True)
        self.before_tax.setReadOnly(True)
        self.before_tax.setFocusPolicy(Qt.NoFocus)
        self.other_deductions = self._line_edit("0.00", ltr=True)
        self.other_deductions.setStyleSheet(_EDITOR_QSS.replace(GREEN, RED))
        self.other_deductions.textChanged.connect(self.recalc)
        self.other_deductions.editingFinished.connect(lambda: self._format_money(self.other_deductions))

        self.rates: dict[str, QWidget] = {}
        self.amounts: dict[str, QLabel] = {}
        for key, _label, column, kind, color, _base in LINES:
            if kind == "spin":
                control = self._spin(color)
            else:
                control = RateCombo(LIST_OPTIONS[column], color)
                control.currentTextChanged.connect(self.recalc)
            self.rates[column] = control
            self.amounts[key] = self._amount_label(color)
        self.amounts["other_deductions"] = self._amount_label(RED)
        self.net_label = QLabel("0.00")
        self.net_label.setStyleSheet(f"font-size:{24 if wide else 20}px; font-weight:900; color:#FFFFFF; background:transparent;")

        self.advance_cells: dict[str, QLabel] = {}
        self.advance_warning = QLabel("")
        self.advance_warning.setStyleSheet(f"font-size:12px; font-weight:900; color:{RED}; background:transparent;")
        self.advance_warning.hide()

        self.contract_info = QLabel("")
        self.contract_info.setWordWrap(True)
        self.contract_info.setTextFormat(Qt.RichText)
        self.contract_info.setStyleSheet(
            "font-size:12px; font-weight:800; color:#1F2937; background:#F8FAFC; border:1px dashed #CBD5E1; "
            "border-radius:8px; padding:6px 10px;"
        )

        (self._build_wide if wide else self._build_compact)()
        self.set_editing(False)
        self._ready = True
        self.recalc()

    # -- widgets -------------------------------------------------------------

    def _line_edit(self, placeholder: str, ltr: bool = False) -> QLineEdit:
        editor = QLineEdit()
        editor.setMinimumHeight(38)
        editor.setPlaceholderText(placeholder)
        editor.setStyleSheet(_EDITOR_QSS)
        if ltr:
            editor.setLayoutDirection(Qt.LeftToRight)
            editor.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return editor

    def _spin(self, color: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0, 100)
        spin.setDecimals(2)
        spin.setSingleStep(0.5)
        spin.setSuffix(" %")
        spin.setMinimumHeight(36)
        spin.setFixedWidth(110)
        spin.setLayoutDirection(Qt.LeftToRight)
        spin.setAlignment(Qt.AlignCenter)
        spin.setStyleSheet(
            f"QDoubleSpinBox {{ background:#FFFFFF; border:1.5px solid {color}; border-radius:7px; "
            f"padding:4px 6px; font-size:15px; font-weight:900; color:{color}; }}"
            "QDoubleSpinBox:read-only { background:#F8FAFC; }"
        )
        spin.valueChanged.connect(self.recalc)
        return spin

    def _amount_label(self, color: str) -> QLabel:
        label = QLabel("0.00")
        label.setMinimumWidth(130)
        label.setAlignment(Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter)
        label.setStyleSheet(
            "background:#EEF2F6; border:1px solid #CBD5E1; border-radius:7px; padding:7px 10px; "
            f"font-size:14px; font-weight:900; color:{color};"
        )
        return label

    def _labelled(self, caption: str, editor: QWidget, hint: str = "") -> QWidget:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addWidget(_caption(caption, 13))
        if editor.maximumWidth() < 1000:
            # A fixed-width box (the tax rate) sits under its label, not at the far end.
            # Absolute: the box is itself left-to-right, so a plain AlignLeft is not mirrored.
            column.addWidget(editor, 0, Qt.AlignRight | Qt.AlignAbsolute)
        else:
            column.addWidget(editor)
        if hint:
            column.addWidget(_caption(hint, 11, "#64748B"))
        return box

    def _lines_grid(self, with_base: bool) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        amount_col = 3 if with_base else 2
        for row, (key, label, column, _kind, color, base) in enumerate(LINES):
            caption = QLabel(f"<span style='color:{color}'>■</span>&nbsp;&nbsp;{label}")
            caption.setStyleSheet(f"font-size:14px; font-weight:900; color:{TEXT}; background:transparent; border:none;")
            grid.addWidget(caption, row, 0)
            grid.addWidget(self.rates[column], row, 1)
            if with_base:
                grid.addWidget(_caption(base, 12, "#64748B"), row, 2)
            grid.addWidget(self.amounts[key], row, amount_col)
        row = len(LINES)
        caption = QLabel(f"<span style='color:{RED}'>■</span>&nbsp;&nbsp;خصومات أخرى")
        caption.setStyleSheet(f"font-size:14px; font-weight:900; color:{TEXT}; background:transparent; border:none;")
        grid.addWidget(caption, row, 0)
        self.other_deductions.setFixedWidth(150 if with_base else 110)
        grid.addWidget(self.other_deductions, row, 1, 1, 2 if with_base else 1)
        grid.addWidget(self.amounts["other_deductions"], row, amount_col)
        grid.setColumnStretch(amount_col + 1 if self.wide else 0, 1)
        return grid

    def _net_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("net_bar")
        bar.setStyleSheet(f"QFrame#net_bar {{ background:{GREEN}; border-radius:10px; }} QLabel {{ background:transparent; color:#FFFFFF; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 8, 14, 8)
        title = QLabel("صافي المستخلص")
        title.setStyleSheet("font-size:16px; font-weight:900;")
        row.addWidget(title)
        if self.wide:
            formula = QLabel(NET_FORMULA)
            formula.setStyleSheet("font-size:11px; font-weight:700; color:#D1FAE0;")
            row.addWidget(formula, 1)
        else:
            row.addStretch(1)
        row.addWidget(self.net_label)
        return bar

    def _advance_strip(self) -> QFrame:
        """مقدمة العقد ← المخصوم في مستخلصات سابقة ← هذا المستخلص ← المتبقي."""
        strip = QFrame()
        strip.setObjectName("advance_strip")
        strip.setStyleSheet(
            "QFrame#advance_strip { background:#F0F9FF; border:1px solid #BAE6FD; border-radius:10px; }"
            "QLabel { background:transparent; border:none; }"
        )
        column = QVBoxLayout(strip)
        column.setContentsMargins(12, 6, 12, 6)
        column.setSpacing(2)
        head = QHBoxLayout()
        head.addWidget(_caption("رصيد الدفعة المقدمة", 13, BLUE))
        head.addStretch(1)
        head.addWidget(self.advance_warning)
        column.addLayout(head)
        cells = QHBoxLayout()
        cells.setSpacing(6)
        for key, caption, color in (("agreed", "مقدمة العقد", TEXT), ("previous", "مخصوم سابقاً", MUTED),
                                    ("this", "هذا المستخلص", BLUE), ("remaining", "المتبقي", GREEN_DARK)):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            cell.addWidget(_caption(caption, 11, "#64748B"))
            value = _caption("0.00", 14 if self.wide else 13, color)
            self.advance_cells[key] = value
            cell.addWidget(value)
            cells.addLayout(cell, 1)
            if key != "remaining":
                cells.addWidget(_caption("=" if key == "this" else "−", 13, "#94A3B8"))
        column.addLayout(cells)
        return strip

    def _build_wide(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 14)
        root.setSpacing(10)
        root.addWidget(_caption("المستخلص الحالي", 16, GREEN))
        root.addWidget(self.contract_info)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        cells = (("رقم المستخلص", self.extract_no, "يبدأ برقم العقد · قابل للتعديل"),
                 ("التاريخ", self.extract_date, ""), ("إجمالي المستخلص (ج.م)", self.works_value, ""),
                 ("نسبة الضريبة", self.vat_pct, "افتراضي 14%"),
                 ("صافي الأعمال", self.before_tax, "= إجمالي المستخلص ÷ (1 + الضريبة)"))
        for col, (caption, editor, hint) in enumerate(cells):
            # Top-aligned so a cell with a hint line doesn't push its neighbours down.
            grid.addWidget(self._labelled(caption, editor, hint), 0, col, Qt.AlignTop)
        for col in range(5):
            grid.setColumnStretch(col, 1)
        root.addLayout(grid)
        root.addLayout(self._lines_grid(with_base=True))
        root.addWidget(self._advance_strip())
        root.addWidget(self._net_bar())
        root.addStretch(1)

    def _build_compact(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 6, 14, 6)
        root.setSpacing(5)
        root.addWidget(_caption("تفاصيل المستخلص المحدد", 16, GREEN))
        root.addWidget(self.contract_info)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.addWidget(self._labelled("رقم المستخلص", self.extract_no), 0, 0)
        grid.addWidget(self._labelled("التاريخ", self.extract_date), 0, 1)
        grid.addWidget(self._labelled("إجمالي المستخلص (ج.م)", self.works_value), 1, 0)
        grid.addWidget(self._labelled("نسبة الضريبة", self.vat_pct), 1, 1)
        grid.addWidget(self._labelled("صافي الأعمال", self.before_tax), 2, 0, 1, 2)
        root.addLayout(grid)
        root.addSpacing(4)
        root.addLayout(self._lines_grid(with_base=False))
        root.addWidget(self._advance_strip())
        root.addWidget(self._net_bar())
        root.addStretch(1)

    # -- values ------------------------------------------------------------------

    def _set_rate(self, column: str, value: Any) -> None:
        control = self.rates[column]
        if isinstance(control, RateCombo):
            control.set_value(value)
        else:
            control.setValue(float(to_decimal(value)))

    def _rate(self, column: str) -> Decimal:
        control = self.rates[column]
        if isinstance(control, RateCombo):
            return control.value()
        return Decimal(str(round(control.value(), 3)))

    def set_contract(self, contract: dict[str, Any] | None) -> None:
        self._contract = contract
        self.contract_info.setText(contract_info_html(contract))
        self.recalc()

    def set_advance_context(self, extracts: list[dict[str, Any]], extract_id: Any) -> None:
        """The contract's extracts, and which of them is on screen (None = a new one).

        Only the approved ones count in the balance: a draft never takes from the advance.
        """
        self._extracts = approved_only(extracts)
        self._extract_id = extract_id
        self.recalc()

    def fill(self, record: dict[str, Any]) -> None:
        self.extract_no.setText(str(record.get("extract_no") or ""))
        date = record.get("extract_date")
        if isinstance(date, (datetime.date, datetime.datetime)):
            self.extract_date.setDate(QDate(date.year, date.month, date.day))
        self.works_value.setText(_money(record.get("works_value")))
        self.vat_pct.setValue(float(to_decimal(record.get("vat_pct"))))
        for _key, _label, column, *_rest in LINES:
            self._set_rate(column, record.get(column))
        self.other_deductions.setText(_money(record.get("other_deductions")))
        self._suggested_no = ""
        self.recalc()

    def clear(self) -> None:
        self.extract_no.clear()
        self.extract_date.setDate(QDate.currentDate())
        self.works_value.clear()
        self.vat_pct.setValue(float(DEFAULT_VAT_PCT))
        for _key, _label, column, *_rest in LINES:
            self._set_rate(column, 0)
        self.rates["works_insurance_pct"].setValue(float(DEFAULT_WORKS_INSURANCE_PCT))
        self.other_deductions.setText("0.00")
        self._suggested_no = ""
        self.recalc()

    def start_new(self, extract_no: str, contract: dict[str, Any] | None) -> None:
        """A blank extract with the defaults the user asked for."""
        self.clear()
        self.apply_new_contract(extract_no, contract)

    def apply_new_contract(self, extract_no: str, contract: dict[str, Any] | None) -> None:
        """While creating: re-seed the number and the contract-based defaults.

        The advance rate, ضريبة الخصم and التأمينات come from the contract
        (any rate, not only a list choice). A number the user already typed is kept.
        """
        typed = self.extract_no.text().strip()
        if not typed or typed == self._suggested_no:
            self.extract_no.setText(extract_no)
            self._suggested_no = extract_no
        contract = contract or {}
        self._set_rate("advance_payment_pct", contract.get("advance_payment_pct") or 0)
        self._set_rate("withholding_tax_pct", contract.get("tax_discount_pct"))
        self._set_rate("social_insurance_pct", contract.get("social_insurance_pct"))
        self.set_contract(contract or None)

    def values(self) -> dict[str, Any]:
        data = {
            "extract_no": self.extract_no.text(),
            "extract_date": self.extract_date.date().toString("yyyy-MM-dd"),
            "works_value": self.works_value.text(),
            "vat_pct": Decimal(str(round(self.vat_pct.value(), 3))),
            "other_deductions": self.other_deductions.text(),
        }
        for _key, _label, column, *_rest in LINES:
            data[column] = self._rate(column)
        return data

    def recalc(self) -> None:
        if not self._ready:
            return
        values = self.values()
        amounts = extract_amounts(values)
        self.before_tax.setText(_money(amounts["before_tax"]))
        balance = advance_balance(self._contract, self._extracts, dict(values, extract_id=self._extract_id))
        for key, label in self.advance_cells.items():
            label.setText(_money(balance[key]))
        over = balance["remaining"] < 0
        self.advance_cells["remaining"].setStyleSheet(
            f"font-size:{14 if self.wide else 13}px; font-weight:900; color:{RED if over else GREEN_DARK}; background:transparent;")
        self.advance_warning.setText(f"تجاوز مقدمة العقد بـ {_money(-balance['remaining'])}" if over else "")
        self.advance_warning.setVisible(over)
        for key, label in self.amounts.items():
            label.setText(_money(amounts[key]))
        self.net_label.setText(_money(amounts["net"]))

    def _format_money(self, editor: QLineEdit) -> None:
        text = editor.text().strip()
        if text and not editor.isReadOnly():
            editor.setText(_money(to_decimal(text)))

    def set_editing(self, editing: bool) -> None:
        for editor in (self.extract_no, self.works_value, self.other_deductions):
            editor.setReadOnly(not editing)
        self.extract_date.setReadOnly(not editing)
        self.extract_date.setCalendarPopup(editing)
        for control in [self.vat_pct, *self.rates.values()]:
            if isinstance(control, QComboBox):
                control.setEnabled(editing)
            else:
                control.setReadOnly(not editing)
                control.setButtonSymbols(QDoubleSpinBox.UpDownArrows if editing else QDoubleSpinBox.NoButtons)


class ContractorExtractsScreen(QWidget):
    def __init__(self, service: ContractorExtractService | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service or ContractorExtractService()
        self.contract_id: Any = None
        self.contract: dict[str, Any] | None = None
        self.extract_rows: list[dict[str, Any]] = []
        self.current_id: Any = None
        self.current_record: dict[str, Any] | None = None
        self.mode = "view"
        self._cards: dict[Any, QPushButton] = {}
        # A contractor the user picked who has no contract open (index 0 shown by
        # default is not a pick): a reload stays on him.
        self._picked_contractor: Any = None

        self._perm_create = SESSION.can(f"{PERMISSION_BASE}.create")
        self._perm_edit = SESSION.can(f"{PERMISSION_BASE}.edit")
        self._perm_save = SESSION.can(f"{PERMISSION_BASE}.save")
        self._perm_delete = SESSION.can(f"{PERMISSION_BASE}.delete")

        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet("QWidget { font-family: 'Segoe UI', 'Tahoma', 'Arial'; }")
        self.approval = ApprovalControls(self, PERMISSION_BASE, locked_when_approved=True)
        self._build_ui()
        self.search_shortcut = QShortcut(QKeySequence("F1"), self)
        self.search_shortcut.activated.connect(self.open_search)
        self.refresh_all()

    @property
    def form(self) -> ExtractForm:
        return self.card_form if self.tabs.currentIndex() == TAB_CARDS else self.kpi_form

    @property
    def forms(self) -> tuple[ExtractForm, ExtractForm]:
        return self.card_form, self.kpi_form

    # -- layout ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border:none; }"
            "QTabBar::tab { background:#FFFFFF; color:#334155; border:1px solid #D9E2EC; border-bottom:none; "
            "border-top-left-radius:8px; border-top-right-radius:8px; padding:9px 22px; margin-left:4px; "
            "font-size:14px; font-weight:900; }"
            f"QTabBar::tab:selected {{ background:{GREEN}; color:#FFFFFF; border-color:{GREEN}; }}"
            "QTabBar::tab:disabled { color:#94A3B8; }"
        )
        self.tabs.addTab(self._build_cards_tab(), "👷  بطاقة المقاول (نموذج 8)")
        self.tabs.addTab(self._build_kpi_tab(), "📊  مؤشرات العقد (نموذج 9)")
        self.tabs.currentChanged.connect(lambda _i: self._mark_selection())
        root.addWidget(self.tabs, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setStyleSheet(
            f"QFrame {{ background:{GREEN}; border-radius:6px; }}"
            "QLabel { background:transparent; color:#FFFFFF; }"
        )
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)
        icon = QLabel("🧾")
        icon.setFixedSize(54, 54)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            "background:rgba(255,255,255,0.16); border:1px solid rgba(255,255,255,0.28); "
            "border-radius:7px; font-size:24px; font-weight:900;"
        )
        title = QLabel("مستخلصات المقاولين")
        title.setStyleSheet("font-size:27px; font-weight:900;")
        username = (SESSION.user or {}).get("username") if SESSION.user else None
        self.header_user = QLabel(f"المستخدم: {username or '—'}")
        self.header_date = QLabel("")
        for label in (self.header_user, self.header_date):
            label.setStyleSheet(
                "background:rgba(255,255,255,0.14); border:1px solid rgba(255,255,255,0.24); "
                "border-radius:6px; padding:9px 14px; font-weight:800;"
            )
        layout.addWidget(icon)
        layout.addWidget(title, 1)
        layout.addWidget(self.header_user)
        layout.addWidget(self.header_date)
        self.header_timer = QTimer(self)
        self.header_timer.timeout.connect(self._update_datetime)
        self.header_timer.start(1000)
        self._update_datetime()
        return header

    def _update_datetime(self) -> None:
        now = datetime.datetime.now()
        self.header_date.setText(f"التاريخ: {now:%Y-%m-%d} | الوقت: {now:%H:%M:%S}")

    def _build_toolbar(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet("QFrame { background:#FFFFFF; border:1px solid #E5EAF0; border-radius:7px; }")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(7)
        self.new_button = QPushButton("مستخلص جديد")
        self.edit_button = QPushButton("تعديل")
        self.save_button = QPushButton("حفظ")
        self.delete_button = QPushButton("حذف")
        self.cancel_button = QPushButton("إلغاء")
        self.refresh_button = QPushButton("تحديث")
        self.search_button = QPushButton("بحث (F1)")
        self.exit_button = QPushButton("خروج")
        buttons = [
            (self.new_button, QStyle.SP_FileIcon, "#1A7A3C", "#166534"),
            (self.edit_button, QStyle.SP_FileDialogDetailedView, "#64748B", "#475569"),
            (self.save_button, QStyle.SP_DialogSaveButton, "#2563EB", "#1D4ED8"),
            (self.delete_button, QStyle.SP_TrashIcon, "#DC2626", "#B91C1C"),
            (self.cancel_button, QStyle.SP_DialogCancelButton, "#6B7280", "#4B5563"),
            (self.refresh_button, QStyle.SP_BrowserReload, "#FFFFFF", "#F3F4F6"),
            (self.search_button, QStyle.SP_FileDialogContentsView, "#0369A1", "#075985"),
            (self.exit_button, QStyle.SP_ArrowBack, "#374151", "#1F2937"),
        ]
        for button, icon, bg, hover in buttons:
            button.setFixedHeight(38)
            button.setIcon(self.style().standardIcon(icon))
            if bg == "#FFFFFF":
                button.setStyleSheet(
                    "QPushButton { background:#FFFFFF;color:#374151;border:1px solid #D1D5DB;"
                    "border-radius:6px;font-weight:800;padding:7px 12px; }"
                    f"QPushButton:hover {{ background:{hover}; }}"
                )
            else:
                button.setStyleSheet(_button_style(bg, hover))
            layout.addWidget(button)
            if button is self.save_button:
                self.approval.add_buttons(layout)
        layout.addStretch(1)
        layout.addWidget(self.approval.badge)
        self.mode_badge = QLabel("عرض")
        self.mode_badge.setAlignment(Qt.AlignCenter)
        self.mode_badge.setMinimumWidth(100)
        self.mode_badge.setStyleSheet(
            "background:#ECFDF3;color:#087443;border:1px solid #B7E4C7;border-radius:7px;"
            "padding:8px 12px;font-weight:900;"
        )
        layout.addWidget(self.mode_badge)
        self.new_button.clicked.connect(self.new_extract)
        self.approval.approve_button.clicked.connect(self.approve_record)
        self.approval.unapprove_button.clicked.connect(self.unapprove_record)
        self.edit_button.clicked.connect(self.edit_record)
        self.save_button.clicked.connect(self.save_record)
        self.delete_button.clicked.connect(self.delete_record)
        self.cancel_button.clicked.connect(self.cancel_edit)
        self.refresh_button.clicked.connect(self.refresh_all)
        self.search_button.clicked.connect(self.open_search)
        self.exit_button.clicked.connect(self.window().close)
        return bar

    def _picker(self, min_width: int) -> QComboBox:
        combo = QComboBox()
        combo.setMinimumHeight(40)
        combo.setMinimumWidth(min_width)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setStyleSheet(
            f"QComboBox {{ background:#F8FAFC; border:2px solid {GREEN}; border-radius:8px; padding:6px 10px; "
            f"font-size:15px; font-weight:900; color:{TEXT}; }}"
            "QComboBox:disabled { background:#F1F5F9; color:#64748B; }"
        )
        return combo

    def _stat_cell(self, caption: str, color: str) -> tuple[QFrame, QLabel]:
        cell = QFrame()
        cell.setObjectName("stat_cell")
        cell.setStyleSheet("QFrame#stat_cell { border:none; border-right:1px solid #D9E2EC; }")
        column = QVBoxLayout(cell)
        column.setContentsMargins(12, 0, 12, 0)
        column.setSpacing(3)
        column.addWidget(_caption(caption, 12, MUTED))
        value = _caption("—", 17, color)
        column.addWidget(value)
        return cell, value

    # -- tab 8: contractor card + extract cards --------------------------------------

    def _build_cards_tab(self) -> QWidget:
        page = QWidget()
        page_row = QHBoxLayout(page)
        page_row.setContentsMargins(0, 8, 0, 0)
        page_row.setSpacing(10)
        column = QVBoxLayout()
        column.setSpacing(10)

        bar = _card_frame("extract_contractor_bar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)
        avatar = QLabel("👷")
        avatar.setFixedSize(56, 56)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet("background:#EAFBF0; border-radius:12px; font-size:28px;")
        row.addWidget(avatar)
        for caption, attr, width in (("اسم المقاول", "contractor_picker", 230), ("رقم العقد", "contract_picker_a", 190)):
            box = QVBoxLayout()
            box.setSpacing(4)
            box.addWidget(_caption(caption, 12, MUTED))
            combo = self._picker(width)
            setattr(self, attr, combo)
            box.addWidget(combo)
            row.addLayout(box)
        self.contractor_picker.currentIndexChanged.connect(self._on_contractor_picked)
        self.contract_picker_a.currentIndexChanged.connect(
            lambda _i: self._on_contract_picked(self.contract_picker_a.currentData()))
        self.card_stats: dict[str, QLabel] = {}
        for key, caption, color in (("value", "قيمة العقد", TEXT), ("done", "المُنفّذ", BLUE),
                                    ("remaining", "المتبقي", AMBER), ("count", "عدد المستخلصات", TEXT)):
            cell, value = self._stat_cell(caption, color)
            self.card_stats[key] = value
            row.addWidget(cell)
        row.addStretch(1)
        column.addWidget(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background:transparent; }")
        self.cards_host = QWidget()
        self.cards_grid = QGridLayout(self.cards_host)
        self.cards_grid.setContentsMargins(0, 0, 0, 0)
        self.cards_grid.setSpacing(10)
        self.cards_grid.setAlignment(Qt.AlignTop)
        for col in range(CARD_COLUMNS):
            self.cards_grid.setColumnStretch(col, 1)
        scroll.setWidget(self.cards_host)
        column.addWidget(scroll, 1)
        page_row.addLayout(column, 1)

        panel = _card_frame("extract_panel")
        panel.setFixedWidth(500)
        panel_col = QVBoxLayout(panel)
        panel_col.setContentsMargins(0, 0, 0, 0)
        self.card_form = ExtractForm(wide=False)
        panel_scroll = QScrollArea()
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setFrameShape(QFrame.NoFrame)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel_scroll.setWidget(self.card_form)
        panel_col.addWidget(panel_scroll)
        page_row.addWidget(panel, 0)
        return page

    def _build_extract_card(self, record: dict[str, Any]) -> QPushButton:
        amounts = extract_amounts(record)
        button = QPushButton()
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(150)
        column = QVBoxLayout(button)
        column.setContentsMargins(14, 12, 14, 12)
        column.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(_caption(str(record["extract_no"]), 14, GREEN))
        top.addWidget(status_chip(record.get("status")))
        top.addStretch(1)
        top.addWidget(_caption(f"📅 {_date_text(record.get('extract_date'))}", 12, MUTED))
        column.addLayout(top)
        works = QHBoxLayout()
        works.addWidget(_caption("إجمالي المستخلص", 13, MUTED))
        works.addStretch(1)
        works.addWidget(_caption(_money(amounts["works_value"]), 17, TEXT))
        column.addLayout(works)
        # The value split: each deduction, then what is left (the net).
        split = QFrame()
        split.setFixedHeight(10)
        split_row = QHBoxLayout(split)
        split_row.setContentsMargins(0, 0, 0, 0)
        split_row.setSpacing(1)
        parts = [(amounts[key], color) for key, _l, _c, _k, color, _b in LINES]
        parts += [(amounts["other_deductions"], RED), (max(amounts["net"], Decimal(0)), "#86EFAC")]
        for amount, color in parts:
            if amount > 0:
                piece = QFrame()
                piece.setStyleSheet(f"background:{color}; border:none;")
                split_row.addWidget(piece, max(1, int(amount)))
        column.addWidget(split)
        net = QFrame()
        net.setObjectName("card_net")
        net.setStyleSheet("QFrame#card_net { background:#EAFBF0; border-radius:8px; }")
        net_row = QHBoxLayout(net)
        net_row.setContentsMargins(10, 6, 10, 6)
        net_row.addWidget(_caption("الصافي", 13, GREEN_DARK))
        net_row.addStretch(1)
        net_row.addWidget(_caption(_money(amounts["net"]), 18, GREEN_DARK))
        column.addWidget(net)
        for widget in button.findChildren(QWidget):
            widget.setAttribute(Qt.WA_TransparentForMouseEvents)
        button.clicked.connect(lambda _c=False, xid=record["extract_id"]: self._on_extract_clicked(xid))
        self._cards[record["extract_id"]] = button
        return button

    # -- tab 9: contract KPIs + form + history ------------------------------------------

    def _build_kpi_tab(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 8, 0, 0)
        column.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        picker_card = _card_frame("kpi_picker")
        picker_col = QVBoxLayout(picker_card)
        picker_col.setContentsMargins(12, 8, 12, 8)
        picker_col.setSpacing(4)
        picker_col.addWidget(_caption("رقم العقد", 12, MUTED))
        self.contract_picker_b = self._picker(300)
        self.contract_picker_b.currentIndexChanged.connect(
            lambda _i: self._on_contract_picked(self.contract_picker_b.currentData()))
        picker_col.addWidget(self.contract_picker_b)
        top.addWidget(picker_card)
        self.kpis: dict[str, QLabel] = {}
        for key, caption, color in (("value", "قيمة العقد", TEXT), ("done", "إجمالي الأعمال المنفذة", BLUE),
                                    ("remaining", "المتبقي من العقد", AMBER), ("net", "إجمالي الصافي المستحق", GREEN_DARK)):
            tile = _card_frame(f"kpi_{key}")
            tile_col = QVBoxLayout(tile)
            tile_col.setContentsMargins(14, 8, 14, 8)
            tile_col.setSpacing(3)
            tile_col.addWidget(_caption(caption, 12, MUTED))
            value = _caption("—", 19, color)
            self.kpis[key] = value
            tile_col.addWidget(value)
            top.addWidget(tile, 1)
        progress_tile = _card_frame("kpi_progress")
        progress_col = QVBoxLayout(progress_tile)
        progress_col.setContentsMargins(14, 8, 14, 8)
        progress_col.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(_caption("نسبة التنفيذ", 12, MUTED))
        head.addStretch(1)
        self.kpis["percent"] = _caption("0.0%", 16, TEXT)
        head.addWidget(self.kpis["percent"])
        progress_col.addLayout(head)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(12)
        self.progress.setStyleSheet(
            "QProgressBar { background:#F1F5F9; border:none; border-radius:6px; }"
            f"QProgressBar::chunk {{ background:{GREEN}; border-radius:6px; }}"
        )
        progress_col.addWidget(self.progress)
        top.addWidget(progress_tile, 1)
        column.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(10)
        form_card = _card_frame("kpi_form_card")
        form_col = QVBoxLayout(form_card)
        form_col.setContentsMargins(0, 0, 0, 0)
        self.kpi_form = ExtractForm(wide=True)
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setFrameShape(QFrame.NoFrame)
        form_scroll.setWidget(self.kpi_form)
        form_col.addWidget(form_scroll)
        body.addWidget(form_card, 1)

        history = _card_frame("kpi_history")
        history.setFixedWidth(430)
        history_col = QVBoxLayout(history)
        history_col.setContentsMargins(12, 12, 12, 12)
        history_col.setSpacing(8)
        history_col.addWidget(_caption("مستخلصات العقد", 15, GREEN))
        self.history = QTableWidget(0, 4)
        self.history.setHorizontalHeaderLabels(["رقم المستخلص", "التاريخ", "الإجمالي", "الصافي"])
        self.history.verticalHeader().setVisible(False)
        self.history.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.history.setStyleSheet(
            "QTableWidget { border:none; font-size:13px; font-weight:700; gridline-color:#E5E7EB; }"
            f"QHeaderView::section {{ background:{GREEN}; color:#FFFFFF; font-weight:900; padding:6px; border:none; }}"
            "QTableWidget::item:selected { background:#DCFCE7; color:#111827; }"
        )
        self.history.cellClicked.connect(self._on_history_clicked)
        history_col.addWidget(self.history, 1)
        body.addWidget(history, 0)
        column.addLayout(body, 1)
        return page

    # -- pickers -------------------------------------------------------------------------

    def _fill_combo(self, combo: QComboBox, rows: list[dict[str, Any]], text, key: str, keep: Any) -> None:
        combo.blockSignals(True)
        combo.clear()
        for row in rows:
            combo.addItem(text(row), row[key])
        _select_data(combo, keep)
        combo.blockSignals(False)

    def refresh_all(self) -> None:
        if self._busy():
            return
        try:
            contractors = self.service.contractor_choices()
            contracts = self.service.contract_choices()
        except Exception as exc:
            self._show_error("تعذّر تحميل العقود", exc)
            contractors, contracts = [], []
        contract_id = self.contract_id
        # The open contract's contractor; with no contract, the one the user picked.
        keep = (self.contract or {}).get("contractor_id") or self._picked_contractor
        if contract_id is not None and contract_id not in {c["contract_id"] for c in contracts}:
            # Unapproved or deleted elsewhere: only approved contracts stay open.
            contract_id = None
        self._fill_combo(self.contractor_picker, contractors,
                         lambda r: f"{r['contractor_code']} — {r['contractor_name']}", "contractor_id", keep)
        self._fill_combo(self.contract_picker_b, contracts,
                         lambda r: f"{r['contract_no']} — {r['contractor_name']} — {r['project_name']}",
                         "contract_id", contract_id)
        if contract_id is None:
            listed = keep is not None and any(r["contractor_id"] == keep for r in contractors)
            mine = [c for c in contracts if c["contractor_id"] == keep] if listed else []
            if mine or not listed:
                contract_id = (mine or contracts or [{"contract_id": None}])[0]["contract_id"]
            else:
                self._picked_contractor = keep
                self._fill_contract_picker_a([], None)  # still on him, no contract yet
        self.mode = "view"
        self.set_contract(contract_id, keep_extract=self.current_id)

    def reload_lists(self) -> None:
        """Data changed in another screen: refill the lists, keeping the selection.

        Never mid-edit: refresh_all would stop on «احفظ التعديلات أو ألغِها الأول».
        """
        if self.mode in {"new", "edit"}:
            return
        self.refresh_all()

    def _on_contractor_picked(self, _index: int) -> None:
        contractor_id = self.contractor_picker.currentData()
        self._picked_contractor = contractor_id  # a real pick: programmatic fills block signals
        try:
            contracts = self.service.contract_choices(contractor_id)
        except Exception:
            contracts = []
        self._fill_contract_picker_a(contracts, None)
        self._on_contract_picked(contracts[0]["contract_id"] if contracts else None)

    def _fill_contract_picker_a(self, contracts: list[dict[str, Any]], keep: Any) -> None:
        self._fill_combo(self.contract_picker_a, contracts, lambda r: f"{r['contract_no']} — {r['project_name']}",
                         "contract_id", keep)

    def _on_contract_picked(self, contract_id: Any) -> None:
        if self.mode == "edit" or contract_id == self.contract_id:
            return
        self.set_contract(contract_id)

    def set_contract(self, contract_id: Any, keep_extract: Any = None) -> None:
        """Show *contract_id* in both tabs; in «new» mode re-seed the new extract."""
        try:
            self.contract = self.service.get_contract(contract_id) if contract_id is not None else None
            self.extract_rows = self.service.extracts(contract_id) if self.contract else []
        except Exception as exc:
            self._show_error("تعذّر تحميل العقد", exc)
            self.contract, self.extract_rows = None, []
        self.contract_id = self.contract["contract_id"] if self.contract else None
        if self.contract:
            self._picked_contractor = None  # the open contract decides the contractor now

        # Keep all three pickers on this contract.
        if self.contract:
            self.contractor_picker.blockSignals(True)
            _select_data(self.contractor_picker, self.contract["contractor_id"])
            self.contractor_picker.blockSignals(False)
            try:
                mine = self.service.contract_choices(self.contract["contractor_id"])
            except Exception:
                mine = []
            self._fill_contract_picker_a(mine, self.contract_id)
            self.contract_picker_b.blockSignals(True)
            # -1 when this (older) list lacks the contract: never show another one.
            self.contract_picker_b.setCurrentIndex(self.contract_picker_b.findData(self.contract_id))
            self.contract_picker_b.blockSignals(False)
        else:
            # No contract open: the «all contracts» list must not show someone else's.
            self.contract_picker_b.blockSignals(True)
            self.contract_picker_b.setCurrentIndex(-1)
            self.contract_picker_b.blockSignals(False)
        for form in self.forms:
            form.set_contract(self.contract)
            form.set_advance_context(self.extract_rows, None if self.mode == "new" else self.current_id)
        self._fill_views()

        if self.mode == "new":
            try:
                number = self.service.next_extract_no(self.contract_id) if self.contract_id else ""
            except Exception:
                number = ""
            self.form.apply_new_contract(number, self.contract)
            return
        ids = [row["extract_id"] for row in self.extract_rows]
        if keep_extract in ids:
            self.load_extract(keep_extract)
        elif ids:
            self.load_extract(ids[-1])  # the latest extract
        else:
            self._show_empty()

    # -- the views ---------------------------------------------------------------------------

    def _fill_views(self) -> None:
        # The figures count approved extracts only; the cards and the table list the drafts too.
        progress = contract_progress((self.contract or {}).get("contract_value"), approved_only(self.extract_rows))
        has = self.contract is not None
        self.card_stats["value"].setText(_money(progress["contract_value"]) if has else "—")
        self.card_stats["done"].setText(_money(progress["works_total"]) if has else "—")
        self.card_stats["remaining"].setText(_money(progress["remaining"]) if has else "—")
        self.card_stats["count"].setText(str(progress["count"]) if has else "—")
        self.kpis["value"].setText(_money(progress["contract_value"]) if has else "—")
        self.kpis["done"].setText(_money(progress["works_total"]) if has else "—")
        self.kpis["remaining"].setText(_money(progress["remaining"]) if has else "—")
        self.kpis["net"].setText(_money(progress["net_total"]) if has else "—")
        percent = progress["percent"]
        self.kpis["percent"].setText(f"{percent:.1f}%")
        self.progress.setValue(int(min(max(percent, 0), 100) * 10))

        # tab 8: the cards
        while self.cards_grid.count():
            # Hold the widget: after setParent(None) the item no longer returns it.
            widget = self.cards_grid.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._cards = {}
        if not has:
            empty = _caption("أضف عقد من شاشة «عقود المقاولين» أولاً، أو اختار مقاول له عقود.", 15, "#94A3B8")
            empty.setAlignment(Qt.AlignCenter)
            self.cards_grid.addWidget(empty, 0, 0, 1, CARD_COLUMNS)
        else:
            for index, record in enumerate(self.extract_rows):
                self.cards_grid.addWidget(self._build_extract_card(record), index // CARD_COLUMNS, index % CARD_COLUMNS)
            self.new_card_button = QPushButton("＋\nمستخلص جديد لهذا العقد")
            self.new_card_button.setMinimumHeight(150)
            self.new_card_button.setCursor(Qt.PointingHandCursor)
            self.new_card_button.setEnabled(self._perm_create)
            self.new_card_button.setStyleSheet(
                "QPushButton { border:2px dashed #94A3B8; border-radius:12px; background:transparent; "
                "font-size:15px; font-weight:900; color:#475569; }"
                "QPushButton:hover { background:#F1F5F9; }"
            )
            self.new_card_button.clicked.connect(self.new_extract)
            position = len(self.extract_rows)
            self.cards_grid.addWidget(self.new_card_button, position // CARD_COLUMNS, position % CARD_COLUMNS)

        # tab 9: the history table, with a totals row
        rows = self.extract_rows
        self.history.setRowCount(len(rows) + (1 if rows else 0))
        for index, record in enumerate(rows):
            amounts = extract_amounts(record)
            values = [f"{record['extract_no']}{draft_suffix(record)}", _date_text(record.get("extract_date")),
                      _money(amounts["works_value"]), _money(amounts["net"])]
            for col, text in enumerate(values):
                item = QTableWidgetItem(str(text))
                item.setData(Qt.UserRole, record["extract_id"])
                if col >= 2:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self.history.setItem(index, col, item)
        if rows:
            total_row = len(rows)
            for col, text in enumerate(["إجمالي المعتمد", f"{progress['count']} مستخلص",
                                        _money(progress["works_total"]), _money(progress["net_total"])]):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsEnabled)
                item.setForeground(Qt.darkGreen)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                if col >= 2:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self.history.setItem(total_row, col, item)
        self._mark_selection()

    def _mark_selection(self) -> None:
        for extract_id, button in self._cards.items():
            selected = str(extract_id) == str(self.current_id)
            button.setStyleSheet(
                f"QPushButton {{ background:{'#F0FDF4' if selected else '#FFFFFF'}; border-radius:12px; "
                f"border:{'2px solid ' + GREEN if selected else '1px solid #D9E2EC'}; text-align:right; }}"
                "QPushButton:hover { background:#F8FAFC; }"
            )
        self.history.blockSignals(True)
        self.history.clearSelection()
        for row in range(self.history.rowCount()):
            item = self.history.item(row, 0)
            if item is not None and str(item.data(Qt.UserRole)) == str(self.current_id):
                self.history.selectRow(row)
        self.history.blockSignals(False)

    def _on_extract_clicked(self, extract_id: Any) -> None:
        if self._busy():
            return
        self.load_extract(extract_id)

    def _on_history_clicked(self, row: int, _col: int) -> None:
        item = self.history.item(row, 0)
        extract_id = item.data(Qt.UserRole) if item is not None else None
        if extract_id is None:
            return
        if self._busy():
            self._mark_selection()
            return
        self.load_extract(extract_id)

    # -- loading --------------------------------------------------------------------------------

    def load_extract(self, extract_id: Any) -> None:
        try:
            record = self.service.get_extract(extract_id)
        except Exception as exc:
            self._show_error("فشل تحميل المستخلص", exc)
            return
        if not record:
            self._show_empty()
            return
        self.current_id, self.current_record = record["extract_id"], dict(record)
        for form in self.forms:
            form.fill(record)
            form.set_advance_context(self.extract_rows, record["extract_id"])
        self.set_mode("view")
        self._mark_selection()

    def _show_empty(self) -> None:
        self.current_id, self.current_record = None, None
        for form in self.forms:
            form.clear()
            form.set_contract(self.contract)
            form.set_advance_context(self.extract_rows, None)
        self.set_mode("view")
        self._mark_selection()

    # -- «بحث» (F1) ---------------------------------------------------------------------------------

    def open_search(self) -> None:
        """Find any extract; open its contract on it in both tabs."""
        if self._busy():
            return
        dialog = ContractorExtractPickerDialog(self.service.search_extracts, self)
        if dialog.exec() != ContractorExtractPickerDialog.Accepted or not dialog.selected:
            return
        chosen = dialog.selected
        self.set_contract(chosen["contract_id"], keep_extract=chosen["extract_id"])

    # -- new / edit / save / delete --------------------------------------------------------------

    def _busy(self) -> bool:
        if self.mode in {"new", "edit"}:
            QMessageBox.information(self, "جاري التعديل", "احفظ التعديلات أو ألغِها الأول.")
            return True
        return False

    def new_extract(self) -> None:
        if self._busy() or not self._perm_create:
            return
        if self.contract_id is None:
            QMessageBox.information(self, "اختار العقد", "اختار رقم العقد الأول، وبعدين اضغط «مستخلص جديد».")
            return
        try:
            number = self.service.next_extract_no(self.contract_id)
        except Exception:
            number = ""
        self.form.start_new(number, self.contract)
        self.form.set_advance_context(self.extract_rows, None)
        self.set_mode("new")
        self._mark_selection()
        self.form.works_value.setFocus()

    def _status(self) -> Any:
        return (self.current_record or {}).get("status") if self.current_id is not None else None

    def edit_record(self) -> None:
        if (self.current_id is not None and self.mode == "view" and self._perm_edit
                and self.approval.may_edit(self._status())):
            self.set_mode("edit")

    def save_record(self) -> None:
        if self.mode not in {"new", "edit"}:
            return
        data = self.form.values()
        if self.mode == "new":
            data["contract_id"], record_id = self.contract_id, None
        else:
            data["contract_id"], record_id = (self.current_record or {}).get("contract_id"), self.current_id
        try:
            saved = self.service.save_extract(data, record_id, allow_approved=self.approval.is_admin)
        except (ExtractError, ApprovalError) as exc:
            QMessageBox.warning(self, "لا يمكن الحفظ", str(exc))
            return
        except Exception as exc:
            self._show_error("فشل حفظ المستخلص", exc)
            return
        self.mode = "view"
        self.set_contract(data["contract_id"], keep_extract=saved)
        notify_data_changed(self)
        QMessageBox.information(self, "تم الحفظ", self.approval.saved_message(self._status(), "المستخلص"))

    def cancel_edit(self) -> None:
        self.mode = "view"
        self.set_contract(self.contract_id, keep_extract=self.current_id)

    def delete_record(self) -> None:
        if (self.current_id is None or self.mode != "view" or not self._perm_delete
                or not self.approval.may_delete(self._status())):
            return
        answer = QMessageBox.question(
            self, "تأكيد الحذف", f"هل تريد حذف المستخلص «{(self.current_record or {}).get('extract_no', '')}»؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.delete_extract(self.current_id, allow_approved=self.approval.is_admin)
        except (ExtractError, ApprovalError) as exc:
            QMessageBox.warning(self, "لا يمكن الحذف", str(exc))
            return
        except Exception as exc:
            self._show_error("لا يمكن حذف المستخلص", exc)
            return
        self.current_id = None
        self.set_contract(self.contract_id)
        notify_data_changed(self)

    # -- اعتماد / إلغاء الاعتماد ------------------------------------------------------------------

    def approve_record(self) -> None:
        if self.current_id is None or self.mode != "view" or not self.approval.can_approve:
            return
        extract_id, number = self.current_id, (self.current_record or {}).get("extract_no", "")
        if self.approval.approve(f"المستخلص «{number}»",
                                 lambda: self.service.approve(extract_id, self.approval.user_id())):
            self.set_contract(self.contract_id, keep_extract=extract_id)
            QMessageBox.information(self, "تم", "تم اعتماد المستخلص.")

    def unapprove_record(self) -> None:
        if self.current_id is None or self.mode != "view" or not self.approval.can_unapprove:
            return
        extract_id, number = self.current_id, (self.current_record or {}).get("extract_no", "")
        if self.approval.unapprove(f"المستخلص «{number}»", lambda: self.service.unapprove(extract_id)):
            self.set_contract(self.contract_id, keep_extract=extract_id)
            QMessageBox.information(self, "تم", "تم إلغاء اعتماد المستخلص، ورجع مسودة.")

    # -- modes ----------------------------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        editing = mode in {"new", "edit"}
        for form in self.forms:
            form.set_editing(editing and form is self.form)
        has_record = self.current_id is not None
        status = self._status()
        self.new_button.setEnabled(not editing and self._perm_create)
        self.edit_button.setEnabled(not editing and has_record and self._perm_edit and self.approval.may_edit(status))
        self.delete_button.setEnabled(not editing and has_record and self._perm_delete
                                      and self.approval.may_delete(status))
        self.save_button.setEnabled(editing and self._perm_save)
        self.cancel_button.setEnabled(editing)
        self.approval.update(editing, status, self.edit_button, self.delete_button)
        self.search_button.setEnabled(not editing)
        # The contract may change while creating (it re-seeds the new extract), not while editing.
        for picker in (self.contractor_picker, self.contract_picker_a, self.contract_picker_b):
            picker.setEnabled(mode != "edit")
        self.tabs.tabBar().setEnabled(not editing)
        if hasattr(self, "new_card_button"):
            try:
                self.new_card_button.setEnabled(not editing and self._perm_create)
            except RuntimeError:
                pass  # the card was rebuilt
        self.mode_badge.setText({"view": "عرض", "new": "جديد", "edit": "تعديل"}.get(mode, mode))

    def _show_error(self, title: str, exc: Exception) -> None:
        QMessageBox.critical(self, title, str(exc))
