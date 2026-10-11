"""نافذة «خصومات أخرى» — مستخلصات المقاولين (نموذج 10، اختيار المستخدم 2026-10-11).

The «إضافة خصم» button next to «خصومات أخرى» opens it. One side is the input
row (نوع الخصم، سبب الخصم، مبلغ الخصم، «+ إضافة») over the table of lines, each
with «تعديل» / «حذف»; the other side splits the total by type and shows
«إجمالي الخصومات الأخرى» with its share of the extract.

The dialog edits a copy: «موافق» hands :meth:`lines` back to the extract form,
which shows their sum in «خصومات أخرى»; nothing is written until the extract is
saved. Opened while the extract is not being edited (or is approved), it only
shows the lines.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.contractor_contract_service import to_decimal
from app.services.contractor_extract_service import (
    DEDUCTION_REASON_MAX,
    DEDUCTION_TYPE_MAX,
    deductions_by_type,
    deductions_total,
)
from app.ui.common.theme import GREEN, TEXT, _button_style

RED = "#B91C1C"
RED_DARK = "#7F1D1D"
MUTED = "#475569"
BAR_COLORS = ("#1E3A8A", "#B91C1C", "#6D28D9", "#0F766E", "#B45309", "#0369A1", "#475569")
COLUMNS = ("م", "نوع الخصم", "سبب الخصم", "المبلغ", "")
COL_ACTIONS = 4

_INPUT_QSS = (
    f"QLineEdit, QComboBox {{ background:#FFFFFF; border:1px solid #CBD5E1; border-radius:7px; "
    f"padding:6px 10px; font-size:14px; font-weight:700; color:{TEXT}; }}"
    f"QLineEdit:focus, QComboBox:focus {{ border:2px solid {GREEN}; }}"
)


def _money(value: Any) -> str:
    return f"{Decimal(str(value or 0)):,.2f}"


def _label(text: str, size: int = 13, color: str = TEXT, weight: int = 800) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"font-size:{size}px; font-weight:{weight}; color:{color}; background:transparent; border:none;")
    return label


class ExtractDeductionsDialog(QDialog):
    def __init__(self, lines: list[dict[str, Any]], types: list[str], *, editable: bool,
                 extract_no: str = "", contractor_name: str = "", works_value: Any = 0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editable = editable
        self.works_value = to_decimal(works_value)
        self._lines = [{"deduction_type": str(line.get("deduction_type") or "").strip(),
                        "reason": str(line.get("reason") or "").strip(),
                        "amount": to_decimal(line.get("amount"))} for line in lines or []]
        self._editing_row: int | None = None  # the line the input row is changing (None = adding)
        self.setWindowTitle("خصومات أخرى")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet("QDialog { background:#FFFFFF; } QWidget { font-family: 'Segoe UI', 'Tahoma', 'Arial'; }")
        self.resize(1040, 660)
        self._build(types, extract_no, contractor_name)
        self._refresh()

    # -- layout ----------------------------------------------------------------------

    def _build(self, types: list[str], extract_no: str, contractor_name: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("deductions_header")
        header.setStyleSheet(f"QFrame#deductions_header {{ background:{GREEN}; }}")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(20, 12, 20, 12)
        title = " · ".join(part for part in (extract_no, contractor_name) if part)
        header_row.addWidget(_label(f"خصومات أخرى — {title}" if title else "خصومات أخرى", 16, "#FFFFFF"))
        header_row.addStretch(1)
        root.addWidget(header)

        body = QHBoxLayout()
        body.setContentsMargins(20, 16, 20, 16)
        body.setSpacing(16)
        main = QVBoxLayout()
        main.setSpacing(12)
        main.addWidget(self._build_input_row(types))
        main.addWidget(self._build_table(), 1)
        body.addLayout(main, 1)
        body.addWidget(self._build_side_panel())
        root.addLayout(body, 1)

        footer = QFrame()
        footer.setObjectName("deductions_footer")
        footer.setStyleSheet("QFrame#deductions_footer { background:#F8FAFC; border-top:1px solid #D9E2EC; }")
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(20, 10, 20, 10)
        footer_row.setSpacing(10)
        self.ok_button = QPushButton("موافق")
        self.ok_button.setStyleSheet(_button_style(GREEN, "#0F6B30"))
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("إلغاء" if self.editable else "إغلاق")
        self.cancel_button.setStyleSheet(_button_style("#6B7280", "#4B5563"))
        self.cancel_button.clicked.connect(self.reject)
        for button in (self.ok_button, self.cancel_button):
            button.setFixedHeight(38)
            button.setMinimumWidth(110)
            footer_row.addWidget(button)
        self.ok_button.setVisible(self.editable)
        footer_row.addStretch(1)
        if not self.editable:
            footer_row.addWidget(_label("للعرض فقط — اضغط «تعديل» في شاشة المستخلص علشان تغيّر الخصومات.", 12, MUTED, 700))
        root.addWidget(footer)

    def _build_input_row(self, types: list[str]) -> QWidget:
        self.input_row = QWidget()
        row = QHBoxLayout(self.input_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.type_combo = QComboBox()
        self.type_combo.setEditable(True)
        self.type_combo.setInsertPolicy(QComboBox.NoInsert)
        self.type_combo.addItems(types)
        self.type_combo.setCurrentIndex(-1)
        self.type_combo.lineEdit().setPlaceholderText("نوع الخصم")
        self.type_combo.lineEdit().setMaxLength(DEDUCTION_TYPE_MAX)
        # Any part of a type finds it, as in the other drop lists.
        self.type_combo.completer().setFilterMode(Qt.MatchContains)
        self.type_combo.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.type_combo.setFixedWidth(190)
        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("سبب الخصم")
        self.reason_edit.setMaxLength(DEDUCTION_REASON_MAX)
        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText("0.00")
        self.amount_edit.setFixedWidth(130)
        self.amount_edit.setLayoutDirection(Qt.LeftToRight)
        self.amount_edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"[\d,]{0,15}(\.\d{0,2})?")))
        self.amount_edit.returnPressed.connect(self.add_or_update)
        for editor in (self.type_combo, self.reason_edit, self.amount_edit):
            editor.setMinimumHeight(38)
            editor.setStyleSheet(_INPUT_QSS)
        self.add_button = QPushButton("+ إضافة")
        self.add_button.setStyleSheet(_button_style(GREEN, "#0F6B30"))
        self.add_button.clicked.connect(self.add_or_update)
        self.cancel_line_button = QPushButton("إلغاء التعديل")
        self.cancel_line_button.setStyleSheet(_button_style("#6B7280", "#4B5563"))
        self.cancel_line_button.clicked.connect(self.cancel_line_edit)
        self.cancel_line_button.hide()
        for button in (self.add_button, self.cancel_line_button):
            button.setFixedHeight(38)
        row.addWidget(self.type_combo)
        row.addWidget(self.reason_edit, 1)
        row.addWidget(self.amount_edit)
        row.addWidget(self.add_button)
        row.addWidget(self.cancel_line_button)
        self.input_row.setVisible(self.editable)
        return self.input_row

    def _build_table(self) -> QTableWidget:
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        for col, width in ((0, 44), (1, 160), (3, 120), (COL_ACTIONS, 130)):
            self.table.setColumnWidth(col, width)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setColumnHidden(COL_ACTIONS, not self.editable)
        self.table.setStyleSheet(
            "QTableWidget { border:1px solid #D9E2EC; border-radius:8px; font-size:14px; gridline-color:#EEF2F6; }"
            "QHeaderView::section { background:#F1F5F9; color:#334155; font-weight:900; padding:8px; border:none; "
            "border-bottom:1px solid #D9E2EC; }"
            "QTableWidget::item:selected { background:#DCFCE7; color:#111827; }"
        )
        self.table.cellDoubleClicked.connect(lambda row, _col: self.edit_line(row))
        return self.table

    def _build_side_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("deductions_side")
        panel.setFixedWidth(290)
        panel.setStyleSheet("QFrame#deductions_side { background:#F8FAFC; border:1px solid #D9E2EC; border-radius:12px; }")
        column = QVBoxLayout(panel)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(12)
        column.addWidget(_label("توزيع الخصومات حسب النوع", 14, "#334155", 900))
        self.breakdown_host = QWidget()
        self.breakdown = QVBoxLayout(self.breakdown_host)
        self.breakdown.setContentsMargins(0, 0, 0, 0)
        self.breakdown.setSpacing(12)
        column.addWidget(self.breakdown_host)
        column.addStretch(1)
        total_box = QFrame()
        total_box.setObjectName("deductions_total")
        total_box.setStyleSheet(f"QFrame#deductions_total {{ background:{RED_DARK}; border-radius:10px; }}")
        total_col = QVBoxLayout(total_box)
        total_col.setContentsMargins(14, 12, 14, 12)
        total_col.setSpacing(2)
        total_col.addWidget(_label("إجمالي الخصومات الأخرى", 12, "#FECACA", 700))
        self.total_label = _label("0.00", 26, "#FFFFFF", 900)
        total_col.addWidget(self.total_label)
        self.count_label = _label("", 12, "#FECACA", 700)
        total_col.addWidget(self.count_label)
        column.addWidget(total_box)
        return panel

    # -- the lines --------------------------------------------------------------------------

    def lines(self) -> list[dict[str, Any]]:
        """The lines as they stand (what «موافق» hands back)."""
        return [dict(line) for line in self._lines]

    def total(self) -> Decimal:
        return deductions_total(self._lines)

    def add_or_update(self) -> None:
        if not self.editable:
            return
        kind = self.type_combo.currentText().strip()
        reason = self.reason_edit.text().strip()
        amount = to_decimal(self.amount_edit.text())
        if not kind:
            QMessageBox.warning(self, "نوع الخصم", "اختار نوع الخصم أو اكتب نوع جديد.")
            self.type_combo.setFocus()
            return
        if amount <= 0:
            QMessageBox.warning(self, "مبلغ الخصم", "اكتب مبلغ الخصم (أكبر من صفر).")
            self.amount_edit.setFocus()
            return
        line = {"deduction_type": kind, "reason": reason, "amount": amount.quantize(Decimal("0.01"))}
        if self._editing_row is None:
            self._lines.append(line)
        else:
            self._lines[self._editing_row] = line
        if self.type_combo.findText(kind) < 0:
            self.type_combo.addItem(kind)  # a new type is offered for the next line too
        self._reset_input()
        self._refresh()

    def edit_line(self, row: int) -> None:
        """Bring line *row* into the input row; «حفظ التعديل» puts it back."""
        if not self.editable or not 0 <= row < len(self._lines):
            return
        line = self._lines[row]
        self._editing_row = row
        self.type_combo.setCurrentText(line["deduction_type"])
        self.reason_edit.setText(line["reason"])
        self.amount_edit.setText(_money(line["amount"]))
        self.add_button.setText("حفظ التعديل")
        self.cancel_line_button.show()
        self.table.selectRow(row)
        self.amount_edit.setFocus()

    def cancel_line_edit(self) -> None:
        self._reset_input()
        self.table.clearSelection()

    def delete_line(self, row: int) -> None:
        if not self.editable or not 0 <= row < len(self._lines):
            return
        line = self._lines[row]
        answer = QMessageBox.question(
            self, "حذف خصم", f"حذف خصم «{line['deduction_type']}» بمبلغ {_money(line['amount'])}؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        del self._lines[row]
        if self._editing_row is not None:
            # The line being changed may have moved up, or be the one deleted.
            if self._editing_row == row:
                self._reset_input()
            elif self._editing_row > row:
                self._editing_row -= 1
        self._refresh()

    def _reset_input(self) -> None:
        self._editing_row = None
        self.type_combo.setCurrentIndex(-1)
        self.type_combo.setEditText("")
        self.reason_edit.clear()
        self.amount_edit.clear()
        self.add_button.setText("+ إضافة")
        self.cancel_line_button.hide()

    # -- showing -------------------------------------------------------------------------------

    def _refresh(self) -> None:
        self.table.setRowCount(len(self._lines))
        for row, line in enumerate(self._lines):
            values = (str(row + 1), line["deduction_type"], line["reason"], _money(line["amount"]))
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                if col == 3:
                    item.setForeground(Qt.darkRed)
                self.table.setItem(row, col, item)
            if self.editable:
                self.table.setCellWidget(row, COL_ACTIONS, self._row_actions(row))
        self._fill_breakdown()
        total = self.total()
        self.total_label.setText(_money(total))
        count = f"{len(self._lines)} خصم" if len(self._lines) != 1 else "خصم واحد"
        share = f" · {total / self.works_value * 100:.1f}% من المستخلص" if self.works_value > 0 else ""
        self.count_label.setText(count + share)

    def _row_actions(self, row: int) -> QWidget:
        host = QWidget()
        actions = QHBoxLayout(host)
        actions.setContentsMargins(4, 2, 4, 2)
        actions.setSpacing(4)
        for text, color, handler in (("تعديل", "#0369A1", self.edit_line), ("حذف", RED, self.delete_line)):
            button = QPushButton(text)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(
                f"QPushButton {{ background:transparent; border:none; color:{color}; font-size:13px; font-weight:800; "
                "padding:2px 6px; } QPushButton:hover { text-decoration: underline; }"
            )
            button.clicked.connect(lambda _c=False, r=row, h=handler: h(r))
            actions.addWidget(button)
        return host

    def _fill_breakdown(self) -> None:
        while self.breakdown.count():
            widget = self.breakdown.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        total = self.total()
        groups = deductions_by_type(self._lines)
        if not groups:
            empty = _label("لسه مفيش خصومات.", 13, "#94A3B8", 700)
            self.breakdown.addWidget(empty)
            return
        for index, (kind, amount) in enumerate(groups):
            share = amount / total * 100 if total > 0 else Decimal("0")
            color = BAR_COLORS[index % len(BAR_COLORS)]
            cell = QWidget()
            column = QVBoxLayout(cell)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(4)
            head = QHBoxLayout()
            head.addWidget(_label(kind, 13, TEXT, 900))
            head.addStretch(1)
            head.addWidget(_label(f"{_money(amount)} · {share:.1f}%", 12, MUTED, 800))
            column.addLayout(head)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(int(share * 10))
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            bar.setStyleSheet(
                "QProgressBar { background:#E2E8F0; border:none; border-radius:5px; }"
                f"QProgressBar::chunk {{ background:{color}; border-radius:5px; }}"
            )
            column.addWidget(bar)
            self.breakdown.addWidget(cell)
