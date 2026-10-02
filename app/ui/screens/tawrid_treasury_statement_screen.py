"""شاشة كشف حساب الخزينة — قسم التوريدات (Tawrid treasury / cash-book statement).

The Access report ``A-khazina`` («كشف حساب الخزينه»), re-created as a **read-only
report** on the same visual template as «التقرير الشامل» (coloured header, filter
row, card strip, wide table, totals strip, Chromium print stack). Unlike the three
account statements it spans no single party — it is the **treasury cash book**: a
unified list of the three voucher tables (قبض عملاء = مقبوضات, صرف كسّارات +
صرف جرارات = مدفوعات), filtered by a **date range only**.

Each row shows النوع · الطرف · مقبوضات · مدفوعات · **رصيد تراكمي** · البيان (the
النوع/الطرف/رصيد are the user-requested enrichment over the raw Access columns).
The footer carries the three Access totals — إجمالي المقبوضات (``d3``), إجمالي
المدفوعات (``d4``) and الرصيد الحالي (``Text80 = d3 − d4``) — as the card strip.

The accent is **gold ``#A16207``** — distinct from the green/amber/blue/slate of
the four existing Tawrid reports. Receipts render green, payments red.

All values come from :class:`TawridTreasuryStatementService`; nothing here runs SQL.
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

from app.services.tawrid_treasury_statement_service import (
    ReportFilters,
    ReportResult,
    TawridTreasuryStatementService,
)
from app.ui.common.theme import BORDER, _button_style

REPORT_TITLE = "كشف حساب الخزينة"

# Gold accent — distinct from the statements (green/amber/blue) and the
# comprehensive report (slate).
GOLD = "#A16207"
GOLD_DARK = "#854D0E"
GOLD_TINT = "#FEF9E7"
MUTED = "#6B7280"
INK = "#0F172A"
RECEIPT = "#047857"   # مقبوضات — green (money in)
PAYMENT = "#B91C1C"   # مدفوعات — red (money out)


def _money(value: Decimal | int | float | None) -> str:
    """Thousands-separated, two decimals. Negative shown as ``1,234.00-``."""
    amount = Decimal(str(value or 0))
    text = f"{abs(amount):,.2f}"
    return f"{text}-" if amount < 0 else text


class TawridTreasuryStatementScreen(QWidget):
    """RTL read-only treasury cash book filtered by a date range."""

    HEADER_SUBTITLE = "كشف موحّد لحركة النقد — مقبوضات العملاء ومدفوعات الكسّارات والجرارات برصيد تراكمي"

    def __init__(
        self,
        service: TawridTreasuryStatementService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service or TawridTreasuryStatementService()
        self.current_result: ReportResult | None = None
        self.setWindowTitle(REPORT_TITLE)
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1280, 860)
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
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self._build_cards())
        layout.addWidget(self._build_table(), 1)
        layout.addWidget(self._build_totals())
        scroll.setWidget(content)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setStyleSheet(
            f"QFrame {{ background:{GOLD}; border-radius:10px; }}"
            "QLabel { background:transparent; color:#FFFFFF; }"
        )
        box = QVBoxLayout(header)
        box.setContentsMargins(18, 12, 18, 12)
        box.setSpacing(2)
        title = QLabel(REPORT_TITLE)
        title.setStyleSheet("font-size:23px; font-weight:900;")
        subtitle = QLabel(self.HEADER_SUBTITLE)
        subtitle.setStyleSheet("font-size:13px; font-weight:700; color:#FEF3C7;")
        box.addWidget(title)
        box.addWidget(subtitle)
        return header

    def _build_filters(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame#f {{ background:#FFFFFF; border:1px solid {BORDER}; border-radius:10px; }}"
        )
        frame.setObjectName("f")
        grid = QGridLayout(frame)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.addWidget(self._caption("من تاريخ"), 0, 0)
        self.from_date = self._date_edit()
        grid.addWidget(self.from_date, 0, 1)
        grid.addWidget(self._caption("إلى تاريخ"), 0, 2)
        self.to_date = self._date_edit()
        grid.addWidget(self.to_date, 0, 3)
        grid.setColumnStretch(4, 1)
        return frame

    def _build_toolbar(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame#tb {{ background:#FFFFFF; border:1px solid {BORDER}; border-radius:10px; }}"
        )
        frame.setObjectName("tb")
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)

        self.show_button = self._action_button("عرض الكشف", GOLD, GOLD_DARK, self.show_report)
        row.addWidget(self.show_button)
        self.reset_button = self._action_button("مسح الفلاتر", "#6B7280", "#4B5563", self.reset_filters)
        row.addWidget(self.reset_button)
        row.addStretch(1)

        self.preview_button = self._action_button("معاينة", GOLD_DARK, "#713F12", self.preview_report)
        row.addWidget(self.preview_button)
        self.print_button = self._action_button("طباعة", GOLD_DARK, "#713F12", self.print_report)
        row.addWidget(self.print_button)
        self.pdf_button = self._action_button("PDF", "#B91C1C", "#991B1B", self.export_pdf)
        row.addWidget(self.pdf_button)
        self.excel_button = self._action_button("تصدير Excel", "#0F766E", "#0B5F58", self.export_excel)
        row.addWidget(self.excel_button)
        return frame

    def _build_cards(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.cards: dict[str, QLabel] = {}
        specs = (
            ("total_dr", "إجمالي المقبوضات", RECEIPT),
            ("total_cr", "إجمالي المدفوعات", PAYMENT),
            ("balance", "الرصيد الحالي", GOLD_DARK),
        )
        for key, caption, color in specs:
            row.addWidget(self._stat_card(key, caption, color), 1)
        return holder

    def _stat_card(self, key: str, caption: str, fg: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background:#FFFFFF; border:1px solid {BORDER}; border-radius:12px; }}"
        )
        col = QVBoxLayout(card)
        col.setContentsMargins(14, 13, 14, 13)
        col.setSpacing(6)
        cap = QLabel(caption)
        cap.setStyleSheet(f"font-size:12px; font-weight:700; color:{MUTED}; background:transparent;")
        value = QLabel("—")
        value.setStyleSheet(f"font-size:20px; font-weight:900; color:{fg}; background:transparent;")
        value.setLayoutDirection(Qt.LeftToRight)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        col.addWidget(cap)
        col.addWidget(value)
        self.cards[key] = value
        return card

    def _build_table(self) -> QWidget:
        wrapper = QFrame()
        wrapper.setStyleSheet(
            f"QFrame {{ background:#FFFFFF; border:1px solid {BORDER}; border-radius:10px; }}"
        )
        box = QVBoxLayout(wrapper)
        box.setContentsMargins(10, 10, 10, 10)
        self.columns = self.service.columns
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
            "QTableWidget { background:#FFFFFF; alternate-background-color:#FEFCE8; border:none; "
            "gridline-color:#E5E7EB; font-size:13px; }"
            f"QHeaderView::section {{ background:{GOLD}; color:#FFFFFF; font-weight:900; "
            "border:none; padding:10px 6px; }"
            "QTableWidget::item:selected { background:#FDE9B8; color:#111827; }"
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.empty_label = QLabel("اضبط الفترة (اختياريّة) ثم اضغط «عرض الكشف».")
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
            f"QFrame#t {{ background:{GOLD_TINT}; border:1px solid #FDE68A; border-radius:10px; }}"
            "QLabel { border:none; background:transparent; }"
        )
        frame.setObjectName("t")
        row = QHBoxLayout(frame)
        row.setContentsMargins(16, 11, 16, 11)
        row.setSpacing(24)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(f"color:{MUTED}; font-weight:800;")
        row.addWidget(self.count_label)
        row.addStretch(1)
        self.total_dr_label = QLabel("المقبوضات: —")
        self.total_cr_label = QLabel("المدفوعات: —")
        self.balance_label = QLabel("الرصيد: —")
        for lab, color in (
            (self.total_dr_label, RECEIPT),
            (self.total_cr_label, PAYMENT),
            (self.balance_label, GOLD_DARK),
        ):
            lab.setStyleSheet(f"color:{color}; font-size:15px; font-weight:900;")
            row.addWidget(lab)
        return frame

    # -- small builders --------------------------------------------------

    def _caption(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(f"color:{MUTED}; font-size:12px; font-weight:800;")
        return lab

    def _action_button(self, text: str, bg: str, bg2: str, handler) -> QPushButton:
        btn = QPushButton(text)
        btn.setMinimumHeight(38)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(_button_style(bg, bg2))
        btn.clicked.connect(handler)
        return btn

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

    # -- run -------------------------------------------------------------

    def _current_filters(self) -> ReportFilters:
        return ReportFilters(
            date_from=self._date_value(self.from_date),
            date_to=self._date_value(self.to_date),
        )

    def show_report(self) -> None:
        filters = self._current_filters()
        if filters.date_from and filters.date_to and filters.date_from > filters.date_to:
            QMessageBox.warning(self, "تواريخ غير صحيحة", "«من تاريخ» بعد «إلى تاريخ».")
            return
        try:
            result = self.service.build(filters)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "تعذّر عرض الكشف", str(exc))
            return
        self.current_result = result
        self._fill(result)

    def reset_filters(self) -> None:
        self.current_result = None
        self.from_date.setDate(_dt.date.today())
        self.to_date.setDate(_dt.date.today())
        self.table.setRowCount(0)
        self.table.setVisible(True)
        self.empty_label.setText("اضبط الفترة (اختياريّة) ثم اضغط «عرض الكشف».")
        self.empty_label.setVisible(True)
        self.count_label.setText("")
        self.total_dr_label.setText("المقبوضات: —")
        self.total_cr_label.setText("المدفوعات: —")
        self.balance_label.setText("الرصيد: —")
        for value in self.cards.values():
            value.setText("—")

    # -- render ----------------------------------------------------------

    def _fill(self, result: ReportResult) -> None:
        rows = result.rows
        export = self.service.export_rows(result)
        self.table.setRowCount(len(rows))
        colour_by_key = {"dr": RECEIPT, "cr": PAYMENT, "balance": INK}
        for r_index, cells in enumerate(export):
            for c_index, column in enumerate(self.columns):
                item = QTableWidgetItem(cells.get(column.key, ""))
                item.setTextAlignment(
                    (Qt.AlignRight if column.align == "right" else Qt.AlignCenter)
                    | Qt.AlignVCenter
                )
                if column.key in colour_by_key:
                    item.setForeground(QColor(colour_by_key[column.key]))
                self.table.setItem(r_index, c_index, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        has_rows = len(rows) > 0
        self.table.setVisible(has_rows)
        self.empty_label.setVisible(not has_rows)
        if not has_rows:
            self.empty_label.setText("لا توجد حركات مطابقة للفترة المحددة.")

        totals = result.totals
        self.count_label.setText(f"عدد الحركات: {totals.count:,}")
        self.total_dr_label.setText(f"المقبوضات: {_money(totals.total_dr)}")
        self.total_cr_label.setText(f"المدفوعات: {_money(totals.total_cr)}")
        self.balance_label.setText(f"الرصيد: {_money(totals.balance)}")
        self.cards["total_dr"].setText(_money(totals.total_dr))
        self.cards["total_cr"].setText(_money(totals.total_cr))
        self.cards["balance"].setText(_money(totals.balance))

    # -- export / print --------------------------------------------------

    def _filter_lines(self) -> list[str]:
        f = self._current_filters()
        date_from = f.date_from or "البداية"
        date_to = f.date_to or "النهاية"
        return [
            f"الفترة: من {date_from} إلى {date_to}",
            f"تاريخ الإصدار: {_dt.datetime.now():%Y-%m-%d %H:%M}",
        ]

    def _summary_lines(self, result: ReportResult) -> list[str]:
        t = result.totals
        return [
            f"إجمالي المقبوضات: {_money(t.total_dr)}",
            f"إجمالي المدفوعات: {_money(t.total_cr)}",
            f"الرصيد الحالي: {_money(t.balance)}",
            f"عدد الحركات: {t.count:,}",
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
        result = self.current_result
        t = result.totals
        return {
            "title": REPORT_TITLE,
            "filter_label": "",
            "date_from_label": result.filters.date_from or "البداية",
            "date_to_label": result.filters.date_to or "النهاية",
            "empty_message": "لا توجد حركات مطابقة للفترة المحددة",
            "rows": self.service.export_rows(result),
            "totals": {
                "total_dr": _money(t.total_dr),
                "total_cr": _money(t.total_cr),
                "balance": _money(t.balance),
                "count": f"{t.count:,}",
            },
        }

    def preview_report(self) -> None:
        if not self._ensure_ran():
            return
        try:
            from app.ui.screens.tawrid_treasury_statement_print import (
                TawridTreasuryPreviewDialog,
            )
            dialog = TawridTreasuryPreviewDialog(self._print_data(), self)
        except Exception as exc:  # noqa: BLE001 - QtWebEngine may be unavailable
            QMessageBox.warning(self, "المعاينة غير متاحة", f"تعذّر فتح المعاينة:\n{exc}")
            return
        dialog.exec()

    def print_report(self) -> None:
        if not self._ensure_ran():
            return
        from app.ui.screens.tawrid_treasury_statement_print import (
            TawridTreasuryPrintOptionsDialog,
            print_report,
        )
        options = TawridTreasuryPrintOptionsDialog(self)
        if options.exec() != QDialog.Accepted:
            return
        try:
            print_report(self, self._print_data(), options.columns())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "الطباعة غير متاحة", f"تعذّرت الطباعة:\n{exc}")

    def export_pdf(self) -> None:
        if not self._ensure_ran():
            return
        from app.ui.screens.tawrid_treasury_statement_print import (
            TawridTreasuryPrintOptionsDialog,
            export_report_to_pdf,
        )
        options = TawridTreasuryPrintOptionsDialog(self)
        if options.exec() != QDialog.Accepted:
            return
        try:
            export_report_to_pdf(self, self._print_data(), options.columns())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "التصدير غير متاح", f"تعذّر إنشاء PDF:\n{exc}")

    def _ensure_ran(self) -> bool:
        if self.current_result is None:
            QMessageBox.warning(self, "لا توجد بيانات", "اعرض الكشف أولًا.")
            return False
        return True
