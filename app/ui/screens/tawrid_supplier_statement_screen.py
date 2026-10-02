"""شاشة كشف حساب الكسّارات — قسم التوريدات (Tawrid module), statement 2/3.

The second of the three account statements (customer / crusher / tractor). Like
the customer statement it is a **read-only report**, not a CRUD screen: pick a
crusher and a period, and it renders the ledger — every بون مورد (debit) and every
سند صرف (credit), in date order, with a **running balance** — plus the header
facts, four stat cards, a payment-ratio donut and the closing totals. It
re-creates the Access report ``ACCSUP`` («كشف حساب الكسارات») and adds the
running-balance column Access lacked.

It is the **twin of** :mod:`app.ui.screens.tawrid_customer_statement_screen`
(Model 1, «الكلاسيكي») with three differences, all of them the crusher's:

* the accent is **amber ``#B45309``** to match the الكسّارات screens, not green;
* the party is the crusher — picked with :class:`TawridSupplierPickerDialog`,
  the debit layer is ``total_res`` and the credit is a سند صرف; and
* **there is NO «ملخص البونات»** — ``ACCSUP`` carries no subreport, so the button
  is gone from the toolbar and the checkbox is gone from the print options.

All values come from :class:`TawridSupplierStatementService`; nothing here runs
SQL. A positive balance is what **we owe the crusher**; a negative one means it was
overpaid (real in the legacy data — «مكة ستون» sits at −11,125), and it is shown
as-is. With a «من تاريخ» the ledger opens on a **«رصيد سابق»** carry-forward line.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.tawrid_supplier_statement_service import (
    StatementResult,
    TawridSupplierStatementService,
)
from app.ui.common.theme import BORDER, TEXT, _button_style
# The donut and the money helper are shared verbatim with the customer statement;
# the donut takes a fill colour so the «paid» arc is amber here (green there).
from app.ui.screens.tawrid_customer_statement_screen import _DonutChart, _money
from app.ui.dialogs.tawrid_supplier_picker import TawridSupplierPickerDialog

REPORT_TITLE = "كشف حساب الكسارات"

# Amber accent (matches the الكسّارات screens) + shared neutral tokens.
AMBER = "#B45309"
AMBER_DARK = "#92400E"
AMBER_TINT = "#FDF1E3"
RED = "#B91C1C"
TRACK = "#E2E8F0"
MUTED = "#64748B"
GREEN = "#137A38"  # المدفوعات (credit) stays accounting-green


class TawridSupplierStatementScreen(QWidget):
    """RTL read-only crusher account statement (بونات المورد + سندات الصرف)."""

    HEADER_SUBTITLE = "كشف حساب تفصيلي ببونات المورد وسندات الصرف والرصيد الجاري للكسّارة"

    def __init__(
        self,
        service: TawridSupplierStatementService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service or TawridSupplierStatementService()
        self.selected_supplier: dict[str, Any] | None = None
        self.current_result: StatementResult | None = None
        self.setWindowTitle(REPORT_TITLE)
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1360, 860)
        self._build_ui()

    # -- layout ----------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(self._build_header())
        layout.addWidget(self._build_filters())
        layout.addWidget(self._build_cards())
        layout.addWidget(self._build_table(), 1)
        layout.addWidget(self._build_totals())
        scroll.setWidget(content)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setStyleSheet(
            f"QFrame {{ background:{AMBER}; border-radius:10px; }}"
            "QLabel { background:transparent; color:#FFFFFF; }"
        )
        box = QVBoxLayout(header)
        box.setContentsMargins(18, 12, 18, 12)
        box.setSpacing(2)
        title = QLabel(REPORT_TITLE)
        title.setStyleSheet("font-size:23px; font-weight:900;")
        subtitle = QLabel(self.HEADER_SUBTITLE)
        subtitle.setStyleSheet("font-size:13px; font-weight:700; color:#FDECD3;")
        box.addWidget(title)
        box.addWidget(subtitle)
        return header

    def _build_filters(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame#f {{ background:#FFFFFF; border:1px solid {BORDER}; border-radius:10px; }}"
        )
        frame.setObjectName("f")
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(10)

        row.addWidget(self._caption("الكسّارة"))
        self.supplier_label = QLabel("— لم تُختَر —")
        self.supplier_label.setMinimumWidth(240)
        self.supplier_label.setStyleSheet(
            "font-weight:900; color:#111827; background:#F8FAFC; border:1px solid #E2E8F0; "
            "border-radius:7px; padding:8px 12px;"
        )
        row.addWidget(self.supplier_label)
        self.pick_button = QPushButton("اختيار كسّارة")
        self.pick_button.setMinimumHeight(38)
        self.pick_button.setCursor(Qt.PointingHandCursor)
        self.pick_button.setStyleSheet(_button_style(AMBER, AMBER_DARK))
        self.pick_button.clicked.connect(self.pick_supplier)
        row.addWidget(self.pick_button)

        row.addSpacing(6)
        row.addWidget(self._caption("من تاريخ"))
        self.from_date = self._date_edit()
        row.addWidget(self.from_date)
        row.addWidget(self._caption("إلى تاريخ"))
        self.to_date = self._date_edit()
        row.addWidget(self.to_date)

        self.show_button = QPushButton("عرض الكشف")
        self.show_button.setMinimumHeight(38)
        self.show_button.setCursor(Qt.PointingHandCursor)
        self.show_button.setStyleSheet(_button_style(AMBER, AMBER_DARK))
        self.show_button.clicked.connect(self.show_statement)
        row.addWidget(self.show_button)

        # NB: no «ملخص البونات» button — the crusher statement has no bon summary.

        self.reset_button = QPushButton("مسح")
        self.reset_button.setMinimumHeight(38)
        self.reset_button.setCursor(Qt.PointingHandCursor)
        self.reset_button.setStyleSheet(_button_style("#6B7280", "#4B5563"))
        self.reset_button.clicked.connect(self.reset_filters)
        row.addWidget(self.reset_button)

        row.addStretch(1)

        self.preview_button = QPushButton("معاينة")
        self.preview_button.setMinimumHeight(38)
        self.preview_button.setCursor(Qt.PointingHandCursor)
        self.preview_button.setStyleSheet(_button_style("#334155", "#1E293B"))
        self.preview_button.clicked.connect(self.preview_report)
        row.addWidget(self.preview_button)

        self.print_button = QPushButton("طباعة")
        self.print_button.setMinimumHeight(38)
        self.print_button.setCursor(Qt.PointingHandCursor)
        self.print_button.setStyleSheet(_button_style("#334155", "#1E293B"))
        self.print_button.clicked.connect(self.print_report)
        row.addWidget(self.print_button)

        self.pdf_button = QPushButton("PDF")
        self.pdf_button.setMinimumHeight(38)
        self.pdf_button.setCursor(Qt.PointingHandCursor)
        self.pdf_button.setStyleSheet(_button_style("#B91C1C", "#991B1B"))
        self.pdf_button.clicked.connect(self.export_pdf)
        row.addWidget(self.pdf_button)

        self.excel_button = QPushButton("تصدير Excel")
        self.excel_button.setMinimumHeight(38)
        self.excel_button.setCursor(Qt.PointingHandCursor)
        self.excel_button.setStyleSheet(_button_style("#0F766E", "#0B5F58"))
        self.excel_button.clicked.connect(self.export_excel)
        row.addWidget(self.excel_button)
        return frame

    def _build_cards(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        # Donut card (نسبة السداد) — amber «paid» arc.
        donut_card = QFrame()
        donut_card.setStyleSheet(
            f"QFrame {{ background:#FFFFFF; border:1px solid {BORDER}; border-radius:12px; }}"
        )
        dbox = QVBoxLayout(donut_card)
        dbox.setContentsMargins(14, 12, 14, 12)
        dbox.setSpacing(6)
        dtitle = QLabel("نسبة السداد")
        dtitle.setAlignment(Qt.AlignCenter)
        dtitle.setStyleSheet("font-size:13px; font-weight:800; color:#111827; background:transparent;")
        dbox.addWidget(dtitle)
        self.donut = _DonutChart(fill=AMBER)
        self.donut.setMinimumSize(150, 150)
        dbox.addWidget(self.donut, 1)
        donut_card.setFixedWidth(210)
        row.addWidget(donut_card)

        # Four stat cards.
        self.cards: dict[str, QLabel] = {}
        self._card_captions: dict[str, QLabel] = {}
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(0)
        grid.addWidget(self._stat_card("opening", "رصيد أول المدة", TEXT, "#FFFFFF", BORDER), 0, 0)
        grid.addWidget(self._stat_card("debit", "إجمالي مدين (بونات)", RED, "#FFFFFF", BORDER), 0, 1)
        grid.addWidget(self._stat_card("credit", "إجمالي مدفوع", GREEN, "#FFFFFF", BORDER), 0, 2)
        grid.addWidget(self._stat_card("balance", "الرصيد الحالي", "#FFFFFF", AMBER, "transparent"), 0, 3)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        row.addWidget(grid_host, 1)
        return holder

    def _stat_card(self, key: str, caption: str, fg: str, bg: str, border: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background:{bg}; border:1px solid {border}; border-radius:12px; }}"
        )
        col = QVBoxLayout(card)
        col.setContentsMargins(14, 13, 14, 13)
        col.setSpacing(6)
        cap_color = "rgba(255,255,255,0.85)" if bg == AMBER else MUTED
        cap = QLabel(caption)
        cap.setStyleSheet(f"font-size:12px; font-weight:700; color:{cap_color}; background:transparent;")
        value = QLabel("—")
        value.setStyleSheet(f"font-size:21px; font-weight:900; color:{fg}; background:transparent;")
        value.setLayoutDirection(Qt.LeftToRight)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        col.addWidget(cap)
        col.addWidget(value)
        self.cards[key] = value
        self._card_captions[key] = cap
        return card

    def _build_table(self) -> QWidget:
        wrapper = QFrame()
        wrapper.setStyleSheet(
            f"QFrame {{ background:#FFFFFF; border:1px solid {BORDER}; border-radius:10px; }}"
        )
        box = QVBoxLayout(wrapper)
        box.setContentsMargins(10, 10, 10, 10)
        self.columns = self.service.CONFIG.columns
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels([c.label for c in self.columns])
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(440)
        self.table.setStyleSheet(
            "QTableWidget { background:#FFFFFF; alternate-background-color:#F8FAFC; border:none; "
            "gridline-color:#E5E7EB; font-size:13px; }"
            f"QHeaderView::section {{ background:{AMBER}; color:#FFFFFF; font-weight:900; "
            "border:none; padding:10px 8px; }"
            "QTableWidget::item:selected { background:#FBE3C7; color:#111827; }"
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.empty_label = QLabel("اختر كسّارة ثم اضغط «عرض الكشف».")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color:{MUTED}; font-size:15px; font-weight:800; padding:20px; border:none;"
        )
        box.addWidget(self.table)
        box.addWidget(self.empty_label)
        return wrapper

    def _build_totals(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame#t { background:#FCF3E7; border:1px solid #F1D6AF; border-radius:10px; }"
            "QLabel { border:none; background:transparent; }"
        )
        frame.setObjectName("t")
        row = QHBoxLayout(frame)
        row.setContentsMargins(16, 11, 16, 11)
        row.setSpacing(26)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(f"color:{MUTED}; font-weight:800;")
        row.addWidget(self.count_label)
        row.addStretch(1)
        self.total_debit_label = QLabel("إجمالي مدين: —")
        self.total_credit_label = QLabel("إجمالي دائن: —")
        self.closing_label = QLabel("الرصيد الحالي: —")
        for lab, color in (
            (self.total_debit_label, RED),
            (self.total_credit_label, GREEN),
            (self.closing_label, AMBER_DARK),
        ):
            lab.setStyleSheet(f"color:{color}; font-size:15px; font-weight:900;")
        row.addWidget(self.total_debit_label)
        row.addWidget(self.total_credit_label)
        row.addWidget(self.closing_label)
        return frame

    # -- small builders --------------------------------------------------

    def _caption(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(f"color:{MUTED}; font-size:12px; font-weight:800;")
        return lab

    def _date_edit(self) -> QDateEdit:
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd")
        edit.setSpecialValueText("")  # minimum date shows blank = "no filter"
        edit.setMinimumDate(_dt.date(1900, 1, 1))
        # Default to today (not the 1900 minimum) so the filter never shows 1-1-1900;
        # spin the field down to its blank minimum for the "all dates" view.
        edit.setDate(_dt.date.today())
        edit.setMinimumHeight(38)
        edit.setStyleSheet(
            "QDateEdit { background:#F8FAFC; border:1px solid #CBD5E1; border-radius:7px; padding:5px 8px; }"
        )
        return edit

    @staticmethod
    def _date_value(editor: QDateEdit) -> str | None:
        if editor.date() == editor.minimumDate():
            return None
        return editor.date().toString("yyyy-MM-dd")

    # -- the crusher picker ----------------------------------------------

    def pick_supplier(self) -> None:
        try:
            rows = self.service.party_picker_rows()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "تعذّر تحميل الكسّارات", str(exc))
            return
        if not rows:
            QMessageBox.information(self, "لا توجد كسّارات", "أضِف كسّارة من شاشة الكسّارات أولًا.")
            return
        # The picker expects supplier_code / supplier_name keys + a balance.
        picker_rows = [
            {
                "supplier_id": r.get("party_id"),
                "supplier_code": r.get("code"),
                "supplier_name": r.get("name"),
                "is_active": r.get("is_active"),
                "balance": r.get("balance"),
            }
            for r in rows
        ]
        dialog = TawridSupplierPickerDialog(picker_rows, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected:
            return
        chosen = dialog.selected
        self.selected_supplier = {
            "supplier_id": chosen.get("supplier_id"),
            "supplier_name": chosen.get("supplier_name"),
            "supplier_code": chosen.get("supplier_code"),
        }
        self.supplier_label.setText(str(chosen.get("supplier_name") or ""))

    # -- run -------------------------------------------------------------

    def show_statement(self) -> None:
        if self.selected_supplier is None:
            QMessageBox.warning(self, "ناقص", "اختر الكسّارة قبل عرض الكشف.")
            return
        date_from = self._date_value(self.from_date)
        date_to = self._date_value(self.to_date)
        if date_from and date_to and date_from > date_to:
            QMessageBox.warning(self, "تواريخ غير صحيحة", "«من تاريخ» بعد «إلى تاريخ».")
            return
        try:
            result = self.service.build(
                self.selected_supplier["supplier_id"], date_from, date_to
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "تعذّر عرض الكشف", str(exc))
            return
        self.current_result = result
        self._fill(result)

    def reset_filters(self) -> None:
        self.selected_supplier = None
        self.current_result = None
        self.supplier_label.setText("— لم تُختَر —")
        self.from_date.setDate(_dt.date.today())
        self.to_date.setDate(_dt.date.today())
        self.table.setRowCount(0)
        self.table.setVisible(True)
        self.empty_label.setText("اختر كسّارة ثم اضغط «عرض الكشف».")
        self.empty_label.setVisible(True)
        self.count_label.setText("")
        for lab, cap in (
            (self.total_debit_label, "إجمالي مدين"),
            (self.total_credit_label, "إجمالي دائن"),
            (self.closing_label, "الرصيد الحالي"),
        ):
            lab.setText(f"{cap}: —")
        for value in self.cards.values():
            value.setText("—")
        self._card_captions["opening"].setText("رصيد أول المدة")
        self.donut.set_ratio(0.0, "—")

    # -- render ----------------------------------------------------------

    def _fill(self, result: StatementResult) -> None:
        rows = result.rows
        export = self.service.export_rows(result)
        self.table.setRowCount(len(rows))
        for r_index, (row, cells) in enumerate(zip(rows, export)):
            for c_index, column in enumerate(self.columns):
                item = QTableWidgetItem(cells.get(column.key, ""))
                if column.key == "description":
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignCenter)
                if column.key == "debit" and row.debit:
                    item.setForeground(QColor(RED))
                elif column.key == "credit" and row.credit:
                    item.setForeground(QColor(GREEN))
                elif column.key == "running":
                    item.setForeground(QColor(TEXT))
                if row.is_opening:
                    item.setBackground(QColor(AMBER_TINT))
                    item.setForeground(QColor(AMBER_DARK))
                self.table.setItem(r_index, c_index, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        has_rows = len(rows) > 0
        self.table.setVisible(has_rows)
        self.empty_label.setVisible(not has_rows)
        if not has_rows:
            self.empty_label.setText("لا توجد حركات لهذه الكسّارة في الفترة المحددة.")

        # Totals strip (the debit/credit column sums, and the closing balance).
        col_debit = sum((r.debit for r in rows), Decimal("0"))
        col_credit = sum((r.credit for r in rows), Decimal("0"))
        self.total_debit_label.setText(f"إجمالي مدين: {_money(col_debit)}")
        self.total_credit_label.setText(f"إجمالي دائن: {_money(col_credit)}")
        self.closing_label.setText(f"الرصيد الحالي: {_money(result.closing_balance)}")
        self.count_label.setText(f"عدد الحركات: {result.movement_count:,}")

        # Stat cards.
        self._card_captions["opening"].setText(
            "رصيد سابق" if result.opening_is_carry else "رصيد أول المدة"
        )
        self.cards["opening"].setText(_money(result.opening_balance))
        self.cards["debit"].setText(_money(result.period_debit))
        self.cards["credit"].setText(_money(result.period_credit))
        self.cards["balance"].setText(_money(result.closing_balance))

        # Donut: نسبة السداد = paid ÷ (opening + debits). Ring clamps; the label
        # shows the true % and can exceed 100% when the crusher was overpaid.
        total_due = result.opening_balance + result.period_debit
        if total_due > 0:
            ratio = float(result.period_credit / total_due)
        else:
            ratio = 1.0 if result.period_credit > 0 else 0.0
        self.donut.set_ratio(ratio, f"{ratio * 100:.1f}%")

    # -- export / print --------------------------------------------------

    def _filter_lines(self) -> list[str]:
        name = self.selected_supplier.get("supplier_name") if self.selected_supplier else ""
        code = self.selected_supplier.get("supplier_code") if self.selected_supplier else ""
        date_from = self._date_value(self.from_date) or "البداية"
        date_to = self._date_value(self.to_date) or "النهاية"
        return [
            f"الكسّارة: {name}" + (f" — مسلسل {code}" if code not in (None, "") else ""),
            f"الفترة: من {date_from} إلى {date_to}",
            f"تاريخ الإصدار: {_dt.datetime.now():%Y-%m-%d %H:%M}",
        ]

    def _summary_lines(self, result: StatementResult) -> list[str]:
        opening_cap = "رصيد سابق" if result.opening_is_carry else "رصيد أول المدة"
        return [
            f"{opening_cap}: {_money(result.opening_balance)}",
            f"إجمالي مدين (بونات): {_money(result.period_debit)}",
            f"إجمالي مدفوع: {_money(result.period_credit)}",
            f"الرصيد الحالي: {_money(result.closing_balance)}",
        ]

    def export_excel(self) -> None:
        if not self._ensure_ran():
            return
        from app.reports.excel_exporter import ExcelExporter

        path, _sel = QFileDialog.getSaveFileName(
            self, "حفظ الكشف", f"{REPORT_TITLE}.xlsx", "Excel Files (*.xlsx)"
        )
        if not path:
            return
        output = Path(path)
        if output.suffix.lower() != ".xlsx":
            output = output.with_suffix(".xlsx")
        try:
            ExcelExporter().export_with_summary(
                output, REPORT_TITLE, self._filter_lines(),
                list(self.columns), self.service.export_rows(self.current_result),
                self._summary_lines(self.current_result),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "تعذّر التصدير", str(exc))
            return
        QMessageBox.information(self, "تم التصدير", f"تم حفظ الملف:\n{output}")

    # -- print data (fed to the Chromium print templates) ----------------

    def _print_data(self) -> dict[str, Any]:
        """Reshape the shown statement for the print templates.

        No «ملخص البونات» for the crusher, so no ``bon`` block is built. Every
        value comes straight from the read-only service; only the column sums
        (opening line included) are derived here, for the printed closing row."""
        result = self.current_result
        rows = []
        col_debit = Decimal("0")
        col_credit = Decimal("0")
        for r, cells in zip(result.rows, self.service.export_rows(result)):
            rows.append({**cells, "is_opening": r.is_opening})
            col_debit += r.debit
            col_credit += r.credit
        opening_label = "رصيد سابق" if result.opening_is_carry else "رصيد أول المدة"
        summary = {
            "opening_label": opening_label,
            "opening": _money(result.opening_balance),
            "debit": _money(result.period_debit),
            "credit": _money(result.period_credit),
            "closing": _money(result.closing_balance),
            "col_debit": _money(col_debit),
            "col_credit": _money(col_credit),
            "closing_label": "الرصيد الختامي المستحق للكسّارة",
        }
        return {
            "title": REPORT_TITLE,
            "customer_label": result.party_name,   # party label reused by the template
            "customer_code": result.party_code,
            "date_from_label": result.date_from or "البداية",
            "date_to_label": result.date_to or "النهاية",
            "movement_count": result.movement_count,
            "empty_message": "لا توجد حركات لهذه الكسّارة في الفترة المحددة",
            "rows": rows,
            "summary": summary,
        }

    def _print_column_keys(self) -> tuple[str, ...]:
        """The columns this statement offers the print chooser — its own config
        columns, so رقم الوش is offered here too."""
        return tuple(c.key for c in self.service.CONFIG.columns)

    def preview_report(self) -> None:
        """Open the live preview (column chooser inside; NO bon-summary checkbox)."""
        if not self._ensure_ran():
            return
        try:
            from app.ui.screens.tawrid_statement_print import TawridStatementPreviewDialog
            dialog = TawridStatementPreviewDialog(
                self._print_data(), self, show_summary_checkbox=False,
                allowed_keys=self._print_column_keys(),
            )
        except Exception as exc:  # noqa: BLE001 - QtWebEngine may be unavailable
            QMessageBox.warning(self, "المعاينة غير متاحة", f"تعذّر فتح المعاينة:\n{exc}")
            return
        dialog.exec()

    def print_report(self) -> None:
        """Ask for columns (no bon-summary option), then print (no preview window)."""
        if not self._ensure_ran():
            return
        from app.ui.screens.tawrid_statement_print import (
            TawridStatementPrintOptionsDialog,
            print_statement,
        )
        options = TawridStatementPrintOptionsDialog(
            self, show_summary_checkbox=False, allowed_keys=self._print_column_keys()
        )
        if options.exec() != QDialog.Accepted:
            return
        try:
            print_statement(self, self._print_data(), options.columns(), False)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "الطباعة غير متاحة", f"تعذّرت الطباعة:\n{exc}")

    def export_pdf(self) -> None:
        """Ask for columns (no bon-summary option), then export a PDF."""
        if not self._ensure_ran():
            return
        from app.ui.screens.tawrid_statement_print import (
            TawridStatementPrintOptionsDialog,
            export_statement_to_pdf,
        )
        options = TawridStatementPrintOptionsDialog(
            self, show_summary_checkbox=False, allowed_keys=self._print_column_keys()
        )
        if options.exec() != QDialog.Accepted:
            return
        try:
            export_statement_to_pdf(self, self._print_data(), options.columns(), False)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "التصدير غير متاح", f"تعذّر إنشاء PDF:\n{exc}")

    def _ensure_ran(self) -> bool:
        if self.current_result is None:
            QMessageBox.warning(self, "لا توجد بيانات", "اعرض الكشف أولًا.")
            return False
        return True
