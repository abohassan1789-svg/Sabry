"""نافذة «ملخص البونات» — قسم التوريدات (كشف الحساب).

The Access subreport ``Test`` (HelpSaSubreport2) shown on demand from the account
statement: the party's بونات grouped by (item, price, volume), each group with its
count, gross value and metres, and the three footer totals — إجمالي البونات /
إجمالي النقلات / إجمالي الأمتار.

Pure UI: the caller hands it a :class:`BonSummary`; no database access here.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.tawrid_customer_statement_service import BonSummary
from app.ui.common.theme import GREEN, GREEN_DARK, _button_style


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


def _vol(value: Decimal) -> str:
    return f"{value.normalize():f}"


class TawridBonSummaryDialog(QDialog):
    """Read-only «ملخص البونات» table for one party over the chosen period."""

    def __init__(
        self,
        summary: BonSummary,
        title_suffix: str = "",
        parent: QWidget | None = None,
        accent: str = GREEN,
        accent_dark: str = GREEN_DARK,
    ) -> None:
        super().__init__(parent)
        self.summary = summary
        # The header/footer accent — green for the customer statement, royal blue
        # for the tractor statement — so the dialog matches the screen it opens from.
        self._accent = accent
        self._accent_dark = accent_dark
        self.setWindowTitle("ملخص البونات" + (f" — {title_suffix}" if title_suffix else ""))
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(760, 560)
        self._build_ui(title_suffix)
        self._fill()

    def _build_ui(self, title_suffix: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        header = QFrame()
        header.setStyleSheet(f"QFrame {{ background:{self._accent}; border-radius:8px; }}")
        hbox = QVBoxLayout(header)
        hbox.setContentsMargins(14, 9, 14, 9)
        htitle = QLabel("ملخص البونات")
        htitle.setStyleSheet("color:#FFFFFF; font-size:17px; font-weight:900; background:transparent;")
        hbox.addWidget(htitle)
        if title_suffix:
            hsub = QLabel(title_suffix)
            hsub.setStyleSheet(
                "color:rgba(255,255,255,0.85); font-size:12px; font-weight:700; background:transparent;"
            )
            hbox.addWidget(hsub)
        root.addWidget(header)

        self.columns = self.summary.columns
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels([c.label for c in self.columns])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setStyleSheet(
            "QTableWidget { background:#FFFFFF; alternate-background-color:#F8FAFC; "
            "border:1px solid #E2E8F0; gridline-color:#E5E7EB; font-size:13px; }"
            f"QHeaderView::section {{ background:{self._accent}; color:#FFFFFF; font-weight:900; "
            "border:none; padding:9px 8px; }"
        )
        root.addWidget(self.table, 1)

        # Totals strip: إجمالي البونات / إجمالي النقلات / إجمالي الأمتار. Neutral
        # ground so it reads under any accent; the figures carry the accent colour.
        totals = QFrame()
        totals.setStyleSheet(
            "QFrame { background:#F1F5F9; border:1px solid #E2E8F0; border-radius:8px; }"
            "QLabel { border:none; background:transparent; }"
        )
        trow = QHBoxLayout(totals)
        trow.setContentsMargins(16, 10, 16, 10)
        trow.setSpacing(24)
        self.total_value = self._total_label("إجمالي البونات")
        self.total_count = self._total_label("إجمالي النقلات")
        self.total_meters = self._total_label("إجمالي الأمتار")
        trow.addWidget(self.total_value)
        trow.addWidget(self.total_count)
        trow.addWidget(self.total_meters)
        trow.addStretch(1)
        root.addWidget(totals)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close = QPushButton("إغلاق")
        close.setFixedHeight(36)
        close.setMinimumWidth(110)
        close.setStyleSheet(_button_style(self._accent, self._accent_dark))
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        root.addLayout(bottom)

    def _total_label(self, caption: str) -> QLabel:
        label = QLabel(f"{caption}: —")
        label.setProperty("caption", caption)
        label.setStyleSheet(f"color:{self._accent_dark}; font-size:14px; font-weight:900;")
        return label

    def _fill(self) -> None:
        rows = self.summary.rows
        self.table.setRowCount(len(rows))
        for r_index, row in enumerate(rows):
            cells = {
                "serial": str(r_index + 1),
                "item": row.item,
                "count": str(row.count),
                "price": _money(row.price),
                "volume": _vol(row.volume),
                "gross": _money(row.gross),
                "meters": _vol(row.meters),
            }
            for c_index, column in enumerate(self.columns):
                item = QTableWidgetItem(cells.get(column.key, ""))
                item.setTextAlignment(
                    Qt.AlignRight | Qt.AlignVCenter if column.key == "item" else Qt.AlignCenter
                )
                self.table.setItem(r_index, c_index, item)
        self.total_value.setText(f"إجمالي البونات: {_money(self.summary.total_value)}")
        self.total_count.setText(f"إجمالي النقلات: {self.summary.total_count:,}")
        self.total_meters.setText(f"إجمالي الأمتار: {_vol(self.summary.total_meters)}")
