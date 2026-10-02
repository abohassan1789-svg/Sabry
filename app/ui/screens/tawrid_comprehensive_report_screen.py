"""شاشة التقرير الشامل — قسم التوريدات (Tawrid comprehensive report).

The Access report ``ReportAll`` («تقرير شامل»), re-created as a **read-only
report**, not a CRUD screen. Unlike the three account statements it is a flat
**detail listing over the tickets (البونات) only** — no vouchers, no opening
balance, no running balance, no donut. Instead:

* **five optional filters** (من/إلى تاريخ · المورد · العميل · الجرار/المقطورة ·
  الصنف), each «طابق أو تجاهل لو فاضي»;
* every row shows all **three price layers** (customer / hauler / crusher);
* the footer carries **five totals** — تكلفة العميل/السائق/المورد + تكعيب
  العميل/المورد — shown as the card strip (in place of the statements' donut).

The **visual design, preview, print, PDF and Excel are taken from «كشف حساب
عميل»** at the user's explicit instruction («نفس طريقة العرض ونفس كل حاجة»): a
coloured header, a filter row, a card strip, a wide table and a totals strip,
with the same Chromium print stack. The accent is **slate ``#334155``** — a
neutral tone distinct from the green/amber/blue of the three statements, because
this report spans every party.

All values come from :class:`TawridComprehensiveReportService`; nothing here runs
SQL.
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
    QComboBox,
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

from app.services.tawrid_comprehensive_report_service import (
    ReportFilters,
    ReportResult,
    TawridComprehensiveReportService,
)
from app.ui.common.theme import BORDER, TEXT, _button_style
from app.ui.dialogs.tawrid_customer_picker import TawridCustomerPickerDialog
from app.ui.dialogs.tawrid_supplier_picker import TawridSupplierPickerDialog
from app.ui.dialogs.tawrid_tractor_picker import TawridTractorPickerDialog

REPORT_TITLE = "التقرير الشامل"

# Slate accent — neutral, distinct from the statements (green/amber/blue).
SLATE = "#334155"
SLATE_DARK = "#1E293B"
SLATE_TINT = "#EEF1F5"
MUTED = "#64748B"
MONEY = "#0F172A"
VOLUME = "#0F766E"
ANY_LABEL = "— كل الأصناف —"
NOT_PICKED = "— الكل —"


def _money(value: Decimal | int | float | None) -> str:
    """Thousands-separated, two decimals. Negative shown as ``1,234.00-``."""
    amount = Decimal(str(value or 0))
    text = f"{abs(amount):,.2f}"
    return f"{text}-" if amount < 0 else text


def _vol(value: Decimal | int | float | None) -> str:
    amount = Decimal(str(value or 0))
    return f"{amount.normalize():f}" if amount else "0"


class TawridComprehensiveReportScreen(QWidget):
    """RTL read-only comprehensive tickets report with five optional filters."""

    HEADER_SUBTITLE = "تقرير تفصيلي بالبونات — الطبقات الثلاث (عميل/سائق/مورد) بخمسة فلاتر اختيارية"

    def __init__(
        self,
        service: TawridComprehensiveReportService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service or TawridComprehensiveReportService()
        self.selected_supplier: dict[str, Any] | None = None
        self.selected_customer: dict[str, Any] | None = None
        self.selected_tractor: dict[str, Any] | None = None
        self.current_result: ReportResult | None = None
        self.setWindowTitle(REPORT_TITLE)
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1440, 880)
        self._build_ui()
        self._load_items()

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
            f"QFrame {{ background:{SLATE}; border-radius:10px; }}"
            "QLabel { background:transparent; color:#FFFFFF; }"
        )
        box = QVBoxLayout(header)
        box.setContentsMargins(18, 12, 18, 12)
        box.setSpacing(2)
        title = QLabel(REPORT_TITLE)
        title.setStyleSheet("font-size:23px; font-weight:900;")
        subtitle = QLabel(self.HEADER_SUBTITLE)
        subtitle.setStyleSheet("font-size:13px; font-weight:700; color:#E2E8F0;")
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

        # Row 0: the three party pickers.
        grid.addWidget(self._caption("المورد / الكسّارة"), 0, 0)
        self.supplier_label = self._picked_label()
        grid.addWidget(self.supplier_label, 0, 1)
        grid.addWidget(self._pick_button("اختيار", self.pick_supplier), 0, 2)

        grid.addWidget(self._caption("العميل"), 0, 3)
        self.customer_label = self._picked_label()
        grid.addWidget(self.customer_label, 0, 4)
        grid.addWidget(self._pick_button("اختيار", self.pick_customer), 0, 5)

        grid.addWidget(self._caption("الجرار / المقطورة"), 0, 6)
        self.tractor_label = self._picked_label()
        grid.addWidget(self.tractor_label, 0, 7)
        grid.addWidget(self._pick_button("اختيار", self.pick_tractor), 0, 8)

        # Row 1: dates + item + clear-party buttons.
        grid.addWidget(self._caption("من تاريخ"), 1, 0)
        self.from_date = self._date_edit()
        grid.addWidget(self.from_date, 1, 1)
        grid.addWidget(self._caption("إلى تاريخ"), 1, 3)
        self.to_date = self._date_edit()
        grid.addWidget(self.to_date, 1, 4)
        grid.addWidget(self._caption("الصنف"), 1, 6)
        self.item_combo = QComboBox()
        self.item_combo.setMinimumHeight(38)
        self.item_combo.setStyleSheet(
            "QComboBox { background:#F8FAFC; border:1px solid #CBD5E1; border-radius:7px; "
            "padding:5px 8px; font-weight:700; }"
        )
        grid.addWidget(self.item_combo, 1, 7)
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

        self.show_button = self._action_button("عرض التقرير", SLATE, SLATE_DARK, self.show_report)
        row.addWidget(self.show_button)
        self.reset_button = self._action_button("مسح الفلاتر", "#6B7280", "#4B5563", self.reset_filters)
        row.addWidget(self.reset_button)
        row.addStretch(1)

        self.preview_button = self._action_button("معاينة", "#334155", "#1E293B", self.preview_report)
        row.addWidget(self.preview_button)
        self.print_button = self._action_button("طباعة", "#334155", "#1E293B", self.print_report)
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
            ("total_cus", "إجمالي تكلفة العميل", "#4338CA"),
            ("total_man", "إجمالي تكلفة السائق", "#0F766E"),
            ("total_res", "إجمالي تكلفة المورد", "#B45309"),
            ("cus_volume", "إجمالي تكعيب العميل", SLATE),
            ("res_volume", "إجمالي تكعيب المورد", SLATE),
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
            "QTableWidget { background:#FFFFFF; alternate-background-color:#F8FAFC; border:none; "
            "gridline-color:#E5E7EB; font-size:13px; }"
            f"QHeaderView::section {{ background:{SLATE}; color:#FFFFFF; font-weight:900; "
            "border:none; padding:10px 6px; }"
            "QTableWidget::item:selected { background:#DBE2EC; color:#111827; }"
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.empty_label = QLabel("اضبط الفلاتر (اختياريّة) ثم اضغط «عرض التقرير».")
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
            f"QFrame#t {{ background:{SLATE_TINT}; border:1px solid #CBD5E1; border-radius:10px; }}"
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
        self.total_cus_label = QLabel("ت.العميل: —")
        self.total_man_label = QLabel("ت.السائق: —")
        self.total_res_label = QLabel("ت.المورد: —")
        for lab, color in (
            (self.total_cus_label, "#4338CA"),
            (self.total_man_label, "#0F766E"),
            (self.total_res_label, "#B45309"),
        ):
            lab.setStyleSheet(f"color:{color}; font-size:15px; font-weight:900;")
            row.addWidget(lab)
        return frame

    # -- small builders --------------------------------------------------

    def _caption(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(f"color:{MUTED}; font-size:12px; font-weight:800;")
        return lab

    def _picked_label(self) -> QLabel:
        lab = QLabel(NOT_PICKED)
        lab.setMinimumWidth(180)
        lab.setStyleSheet(
            "font-weight:900; color:#111827; background:#F8FAFC; border:1px solid #E2E8F0; "
            "border-radius:7px; padding:8px 12px;"
        )
        return lab

    def _pick_button(self, text: str, handler) -> QPushButton:
        btn = QPushButton(text)
        btn.setMinimumHeight(38)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(_button_style(SLATE, SLATE_DARK))
        btn.clicked.connect(handler)
        return btn

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

    def _load_items(self) -> None:
        self.item_combo.clear()
        self.item_combo.addItem(ANY_LABEL, None)
        try:
            for name in self.service.distinct_items():
                self.item_combo.addItem(name, name)
        except Exception as exc:  # noqa: BLE001 - an empty combo must not break the screen
            QMessageBox.warning(self, "تعذّر تحميل الأصناف", str(exc))

    # -- the pickers -----------------------------------------------------

    def pick_supplier(self) -> None:
        try:
            rows = self.service.supplier_picker_rows()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "تعذّر تحميل الكسّارات", str(exc))
            return
        dialog = TawridSupplierPickerDialog(rows, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected:
            return
        chosen = dialog.selected
        self.selected_supplier = {
            "supplier_id": chosen.get("supplier_id"),
            "supplier_name": chosen.get("supplier_name"),
        }
        self.supplier_label.setText(str(chosen.get("supplier_name") or ""))

    def pick_customer(self) -> None:
        try:
            rows = self.service.customer_picker_rows()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "تعذّر تحميل العملاء", str(exc))
            return
        dialog = TawridCustomerPickerDialog(rows, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected:
            return
        chosen = dialog.selected
        self.selected_customer = {
            "customer_id": chosen.get("customer_id"),
            "customer_name": chosen.get("customer_name"),
        }
        self.customer_label.setText(str(chosen.get("customer_name") or ""))

    def pick_tractor(self) -> None:
        try:
            rows = self.service.tractor_picker_rows()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "تعذّر تحميل الجرارات", str(exc))
            return
        dialog = TawridTractorPickerDialog(rows, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected:
            return
        chosen = dialog.selected
        name = chosen.get("driver_name") or chosen.get("trailer_no") or ""
        self.selected_tractor = {
            "tractor_id": chosen.get("tractor_id"),
            "tractor_name": name,
            "trailer_no": chosen.get("trailer_no"),
        }
        trailer = chosen.get("trailer_no")
        label = str(name) + (f" — مقطورة {trailer}" if trailer else "")
        self.tractor_label.setText(label)

    # -- run -------------------------------------------------------------

    def _current_filters(self) -> ReportFilters:
        return ReportFilters(
            date_from=self._date_value(self.from_date),
            date_to=self._date_value(self.to_date),
            supplier_id=(self.selected_supplier or {}).get("supplier_id"),
            customer_id=(self.selected_customer or {}).get("customer_id"),
            tractor_id=(self.selected_tractor or {}).get("tractor_id"),
            item_name=self.item_combo.currentData(),
        )

    def show_report(self) -> None:
        filters = self._current_filters()
        if filters.date_from and filters.date_to and filters.date_from > filters.date_to:
            QMessageBox.warning(self, "تواريخ غير صحيحة", "«من تاريخ» بعد «إلى تاريخ».")
            return
        try:
            result = self.service.build(filters)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "تعذّر عرض التقرير", str(exc))
            return
        self.current_result = result
        self._fill(result)

    def reset_filters(self) -> None:
        self.selected_supplier = None
        self.selected_customer = None
        self.selected_tractor = None
        self.current_result = None
        for lab in (self.supplier_label, self.customer_label, self.tractor_label):
            lab.setText(NOT_PICKED)
        self.from_date.setDate(_dt.date.today())
        self.to_date.setDate(_dt.date.today())
        self.item_combo.setCurrentIndex(0)
        self.table.setRowCount(0)
        self.table.setVisible(True)
        self.empty_label.setText("اضبط الفلاتر (اختياريّة) ثم اضغط «عرض التقرير».")
        self.empty_label.setVisible(True)
        self.count_label.setText("")
        for key, cap in (
            ("total_cus", "ت.العميل"), ("total_man", "ت.السائق"), ("total_res", "ت.المورد"),
        ):
            getattr(self, f"{key}_label").setText(f"{cap}: —")
        for value in self.cards.values():
            value.setText("—")

    # -- render ----------------------------------------------------------

    def _fill(self, result: ReportResult) -> None:
        rows = result.rows
        export = self.service.export_rows(result)
        self.table.setRowCount(len(rows))
        money_keys = {c.key for c in self.columns if c.money}
        volume_keys = {c.key for c in self.columns if c.volume}
        for r_index, cells in enumerate(export):
            for c_index, column in enumerate(self.columns):
                item = QTableWidgetItem(cells.get(column.key, ""))
                item.setTextAlignment(
                    (Qt.AlignRight if column.align == "right" else Qt.AlignCenter)
                    | Qt.AlignVCenter
                )
                if column.key in money_keys:
                    item.setForeground(QColor(MONEY))
                elif column.key in volume_keys:
                    item.setForeground(QColor(VOLUME))
                self.table.setItem(r_index, c_index, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        has_rows = len(rows) > 0
        self.table.setVisible(has_rows)
        self.empty_label.setVisible(not has_rows)
        if not has_rows:
            self.empty_label.setText("لا توجد بونات مطابقة للفلاتر المحددة.")

        totals = result.totals
        self.count_label.setText(f"عدد البونات: {totals.count:,}")
        self.total_cus_label.setText(f"ت.العميل: {_money(totals.total_cus)}")
        self.total_man_label.setText(f"ت.السائق: {_money(totals.total_man)}")
        self.total_res_label.setText(f"ت.المورد: {_money(totals.total_res)}")
        self.cards["total_cus"].setText(_money(totals.total_cus))
        self.cards["total_man"].setText(_money(totals.total_man))
        self.cards["total_res"].setText(_money(totals.total_res))
        self.cards["cus_volume"].setText(_vol(totals.cus_volume))
        self.cards["res_volume"].setText(_vol(totals.res_volume))

    # -- export / print --------------------------------------------------

    def _filter_lines(self) -> list[str]:
        f = self._current_filters()
        date_from = f.date_from or "البداية"
        date_to = f.date_to or "النهاية"
        lines = [f"الفترة: من {date_from} إلى {date_to}"]
        if self.selected_supplier:
            lines.append(f"المورد: {self.selected_supplier.get('supplier_name')}")
        if self.selected_customer:
            lines.append(f"العميل: {self.selected_customer.get('customer_name')}")
        if self.selected_tractor:
            lines.append(f"الجرار/المقطورة: {self.selected_tractor.get('tractor_name')}")
        if f.item_name:
            lines.append(f"الصنف: {f.item_name}")
        lines.append(f"تاريخ الإصدار: {_dt.datetime.now():%Y-%m-%d %H:%M}")
        return lines

    def _filter_label(self) -> str:
        parts: list[str] = []
        if self.selected_supplier:
            parts.append(f"المورد: {self.selected_supplier.get('supplier_name')}")
        if self.selected_customer:
            parts.append(f"العميل: {self.selected_customer.get('customer_name')}")
        if self.selected_tractor:
            parts.append(f"المقطورة: {self.selected_tractor.get('tractor_name')}")
        item = self.item_combo.currentData()
        if item:
            parts.append(f"الصنف: {item}")
        return " · ".join(parts)

    def _summary_lines(self, result: ReportResult) -> list[str]:
        t = result.totals
        return [
            f"إجمالي تكلفة العميل: {_money(t.total_cus)}",
            f"إجمالي تكلفة السائق: {_money(t.total_man)}",
            f"إجمالي تكلفة المورد: {_money(t.total_res)}",
            f"إجمالي تكعيب العميل: {_vol(t.cus_volume)}",
            f"إجمالي تكعيب المورد: {_vol(t.res_volume)}",
            f"عدد البونات: {t.count:,}",
        ]

    def export_excel(self) -> None:
        if not self._ensure_ran():
            return
        from app.reports.excel_exporter import ExcelExporter

        path, _sel = QFileDialog.getSaveFileName(
            self, "حفظ التقرير", f"{REPORT_TITLE}.xlsx", "Excel Files (*.xlsx)"
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
            "filter_label": self._filter_label(),
            "date_from_label": result.filters.date_from or "البداية",
            "date_to_label": result.filters.date_to or "النهاية",
            "empty_message": "لا توجد بونات مطابقة للفلاتر المحددة",
            "rows": self.service.export_rows(result),
            "totals": {
                "total_cus": _money(t.total_cus),
                "total_man": _money(t.total_man),
                "total_res": _money(t.total_res),
                "cus_volume": _vol(t.cus_volume),
                "res_volume": _vol(t.res_volume),
                "count": f"{t.count:,}",
            },
        }

    def preview_report(self) -> None:
        if not self._ensure_ran():
            return
        try:
            from app.ui.screens.tawrid_comprehensive_report_print import (
                TawridReportPreviewDialog,
            )
            dialog = TawridReportPreviewDialog(self._print_data(), self)
        except Exception as exc:  # noqa: BLE001 - QtWebEngine may be unavailable
            QMessageBox.warning(self, "المعاينة غير متاحة", f"تعذّر فتح المعاينة:\n{exc}")
            return
        dialog.exec()

    def print_report(self) -> None:
        if not self._ensure_ran():
            return
        from app.ui.screens.tawrid_comprehensive_report_print import (
            TawridReportPrintOptionsDialog,
            print_report,
        )
        options = TawridReportPrintOptionsDialog(self)
        if options.exec() != QDialog.Accepted:
            return
        try:
            print_report(self, self._print_data(), options.columns())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "الطباعة غير متاحة", f"تعذّرت الطباعة:\n{exc}")

    def export_pdf(self) -> None:
        if not self._ensure_ran():
            return
        from app.ui.screens.tawrid_comprehensive_report_print import (
            TawridReportPrintOptionsDialog,
            export_report_to_pdf,
        )
        options = TawridReportPrintOptionsDialog(self)
        if options.exec() != QDialog.Accepted:
            return
        try:
            export_report_to_pdf(self, self._print_data(), options.columns())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "التصدير غير متاح", f"تعذّر إنشاء PDF:\n{exc}")

    def _ensure_ran(self) -> bool:
        if self.current_result is None:
            QMessageBox.warning(self, "لا توجد بيانات", "اعرض التقرير أولًا.")
            return False
        return True
