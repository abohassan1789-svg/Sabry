"""شاشة سند صرف الكسّارة — قسم التوريدات (Tawrid module, phase 7).

The payment voucher: one payment handed to one crusher. It replaces the Access
table ``sanadsup`` («مدفوعات الموردين» / «مدفوعات الكسارات»). Layout is the same
**Model 9** the crusher-side mirrors from سندات قبض العملاء — «عمودان + نداء
الرصيد الجديد»:

* the entry fields sit on the right, each in its own **card** (رقم السند / التاريخ,
  الكسّارة via a picker, المبلغ as a large box with the amount spelled out, and
  the بيان);
* the left column is the live account panel — a big «الرصيد الجديد» callout, a
  **رسم دائري** (donut) of the crusher's payment ratio, and three stat cards
  (رصيد سابق ← هذا السند ← الرصيد بعده).

Like the البون، التكعيب and قبض العملاء screens there is **no voucher list on the
screen**: finding an earlier سند صرف is done through «بحث عن سند صرف»
(:class:`TawridPaymentPickerDialog`) and الأول/السابق/التالي/الأخير navigation.

The row's own INSERT/UPDATE/DELETE is the shared path (``ReviewDataService`` +
``TABLE_SPECS['tawrid_supplier_payments']``); the numbering, the joined display
record, the picker rows and the account summary come from
:class:`TawridSupplierPaymentService`.

The crusher's balance is the **mirror of the customer's**: a positive balance is
what *we owe the crusher*. Overpayment is real — «مكة ستون» sits at −11,125 in the
legacy data — so «الرصيد الجديد» goes negative cleanly and the payment ratio can
exceed 100%: the drawn ring is clamped to a full circle while the **label shows
the true percentage**. The module colour is **amber** (``#B45309``), not green.

What is deliberately different from Access, each tied to a measured fact:

* **The crusher is a real foreign key, chosen from a picker** — Access enforced
  none (here it happens to have 0 orphans, but the pattern is kept).
* **A visible, unique payment number** — ``sanadsup`` had only a row id.
* **``amount`` may be negative** — no legacy row is, but a reversal could be, and
  the balance nets it.
"""

from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.review_data_service import ReviewDataService, TABLE_SPECS
from app.services.tawrid_supplier_payment_service import (
    PaymentAccount,
    TawridSupplierPaymentService,
)
from app.ui.common.theme import _button_style
from app.ui.dialogs.tawrid_payment_picker import TawridPaymentPickerDialog
from app.ui.dialogs.tawrid_supplier_picker import TawridSupplierPickerDialog
from app.ui.screens.base_crud_screen import BaseCrudScreen

# The crusher's colour across the module (amber); المتبقّي uses a warning red.
AMBER = "#B45309"
AMBER_DARK = "#92400E"
AMBER_TINT = "#FBEEDD"
RED = "#B91C1C"
TRACK = "#E2E8F0"


def _money(value: Decimal | float | int | None) -> str:
    """Thousands-separated, two decimals. Negative shown as ``1,234.00-``."""
    amount = Decimal(str(value or 0))
    text = f"{abs(amount):,.2f}"
    return f"{text}-" if amount < 0 else text


def _num(text: Any) -> Decimal:
    """Read a money box. Blank/unparseable is zero (the column defaults to 0)."""
    cleaned = str(text or "").replace(",", "").strip()
    if cleaned == "":
        return Decimal("0")
    if cleaned.endswith("-"):
        cleaned = "-" + cleaned[:-1]
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal("0")


# -- المبلغ بالحروف (a compact Arabic tafqit for the printed voucher) -----------

_ONES = ("", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة",
         "عشرة", "أحد عشر", "اثنا عشر", "ثلاثة عشر", "أربعة عشر", "خمسة عشر",
         "ستة عشر", "سبعة عشر", "ثمانية عشر", "تسعة عشر")
_TENS = ("", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون")
_HUND = ("", "مائة", "مئتان", "ثلاثمائة", "أربعمائة", "خمسمائة", "ستمائة",
         "سبعمائة", "ثمانمائة", "تسعمائة")
# (singular, dual, plural) for each 1000-group scale.
_SCALES = (
    ("", "", ""),
    ("ألف", "ألفان", "آلاف"),
    ("مليون", "مليونان", "ملايين"),
    ("مليار", "ملياران", "مليارات"),
)


def _three(n: int) -> str:
    """Words for 0..999."""
    parts = []
    if n >= 100:
        parts.append(_HUND[n // 100])
        n %= 100
    if n >= 20:
        unit = n % 10
        if unit:
            parts.append(_ONES[unit])
        parts.append(_TENS[n // 10])
    elif n:
        parts.append(_ONES[n])
    return " و".join(parts)


def _int_words(n: int) -> str:
    """Words for a non-negative integer, joined with و across the scales."""
    if n == 0:
        return "صفر"
    groups = []
    scale = 0
    while n > 0 and scale < len(_SCALES):
        chunk = n % 1000
        if chunk:
            if scale == 0:
                groups.append(_three(chunk))
            else:
                sing, dual, plur = _SCALES[scale]
                if chunk == 1:
                    groups.append(sing)
                elif chunk == 2:
                    groups.append(dual)
                elif 3 <= chunk <= 10:
                    groups.append(f"{_three(chunk)} {plur}")
                else:
                    groups.append(f"{_three(chunk)} {sing}")
        n //= 1000
        scale += 1
    return " و".join(reversed(groups))


def _amount_in_words(value: Decimal) -> str:
    """«فقط ... جنيه لا غير», with قرش when there is a fractional part."""
    amount = Decimal(str(value or 0))
    sign = "يُخصم (مرتجع) " if amount < 0 else ""
    amount = abs(amount)
    pounds = int(amount)
    piastres = int((amount - pounds) * 100)
    words = f"فقط {sign}{_int_words(pounds)} جنيه"
    if piastres:
        words += f" و{_int_words(piastres)} قرش"
    return words + " لا غير"


# -- the donut chart -----------------------------------------------------------


class _DonutChart(QWidget):
    """A small payment-ratio donut: amber = paid, red = remaining.

    The ring is clamped to a full circle even when the crusher is overpaid; the
    centre label carries the true percentage, which the caller may set above 100%.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ratio = 0.0  # 0..1 of المستحق that is paid (clamped for the ring)
        self._label = "—"
        self.setMinimumSize(150, 150)

    def set_ratio(self, ratio: float, label: str) -> None:
        # The drawn ring is clamped to [0, 1]; the label may report the real %.
        self._ratio = max(0.0, min(1.0, ratio))
        self._label = label
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt signature
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        pen_w = max(10.0, side * 0.14)
        margin = pen_w / 2 + 4
        rect = QRectF(
            (self.width() - side) / 2 + margin,
            (self.height() - side) / 2 + margin,
            side - 2 * margin,
            side - 2 * margin,
        )
        # Track (full ring).
        track_pen = QPen(QColor(TRACK))
        track_pen.setWidth(int(pen_w))
        track_pen.setCapStyle(Qt.FlatCap)
        painter.setPen(track_pen)
        painter.drawArc(rect, 0, 360 * 16)
        # Paid arc — amber, clockwise from the top.
        span = int(-self._ratio * 360 * 16)
        if span:
            paid_pen = QPen(QColor(AMBER))
            paid_pen.setWidth(int(pen_w))
            paid_pen.setCapStyle(Qt.FlatCap)
            painter.setPen(paid_pen)
            painter.drawArc(rect, 90 * 16, span)
        # Remaining arc — red, the rest of the ring.
        rem = int(-(1 - self._ratio) * 360 * 16)
        if rem:
            red_pen = QPen(QColor(RED))
            red_pen.setWidth(int(pen_w))
            red_pen.setCapStyle(Qt.FlatCap)
            painter.setPen(red_pen)
            painter.drawArc(rect, 90 * 16 + span, rem)
        # Centre label.
        painter.setPen(QColor("#111827"))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(max(11, int(side * 0.12)))
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self._label)


class TawridSupplierPaymentsScreen(BaseCrudScreen):
    SPEC_KEY = "tawrid_supplier_payments"
    SEARCH_PLACEHOLDER = "ابحث برقم السند أو اسم الكسّارة"

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        # Populated before super().__init__ because the base constructor builds
        # the UI, which calls back into the widgets built here.
        self._backend_service: TawridSupplierPaymentService | None = None
        self._supplier_label: QLabel | None = None
        self._words_label: QLabel | None = None
        self._callout_value: QLabel | None = None
        self._callout_was: QLabel | None = None
        self._donut: _DonutChart | None = None
        self._legend: dict[str, QLabel] = {}
        self._stat_values: dict[str, QLabel] = {}
        self._filling = False
        super().__init__(service, TABLE_SPECS[self.SPEC_KEY], parent)
        self._recompute()

    # -- backend ---------------------------------------------------------

    def _backend(self) -> TawridSupplierPaymentService:
        if self._backend_service is None:
            self._backend_service = TawridSupplierPaymentService()
        return self._backend_service

    # -- toolbar ---------------------------------------------------------

    def _install_extra_toolbar_buttons(self, layout: QHBoxLayout) -> None:
        """«بحث عن سند صرف» + the record navigation that stands in for the list."""
        self.find_button = QPushButton("بحث عن سند صرف")
        self.find_button.setFixedHeight(38)
        self.find_button.setStyleSheet(_button_style("#0EA5E9", "#0284C7"))
        self.find_button.clicked.connect(self.open_lookup)
        layout.addWidget(self.find_button)

        self.nav_buttons: dict[str, QPushButton] = {}
        for key, caption in (
            ("first", "الاول"),
            ("prev", "السابق"),
            ("next", "التالي"),
            ("last", "الاخير"),
        ):
            button = QPushButton(caption)
            button.setFixedHeight(38)
            button.setStyleSheet(
                "QPushButton { background:#F1F5F9; color:#475569; border:1px solid #E2E8F0; "
                "border-radius:6px; font-weight:800; padding:7px 10px; }"
                "QPushButton:hover { background:#E2E8F0; }"
                "QPushButton:disabled { color:#CBD5E1; }"
            )
            button.clicked.connect(lambda _c=False, k=key: self._navigate(k))
            self.nav_buttons[key] = button
            layout.addWidget(button)

    # -- layout ----------------------------------------------------------

    def _build_content(self):
        content = QVBoxLayout()
        content.setSpacing(10)

        # The base class writes to ``summary_label`` on every load/new/clear, but
        # only builds it inside its form panel — which this screen replaces. Build
        # it here so those writes land, and show it as a thin caption line.
        self.summary_label = QLabel("سند جديد")
        self.summary_label.setStyleSheet("font-size:13px; font-weight:800; color:#64748B;")
        content.addWidget(self.summary_label, 0)

        stage = QHBoxLayout()
        stage.setSpacing(14)
        stage.addWidget(self._build_form_column(), 3)
        stage.addWidget(self._build_analytics_column(), 2)
        content.addLayout(stage, 1)
        content.addStretch(1)

        # The list panel stays built (the base class drives selection and the
        # record count through ``self.table``) but hidden — Model 9 has no voucher
        # list; navigation and «بحث عن سند صرف» use it instead.
        self.list_panel = self._build_list_panel()
        self.list_panel.hide()
        content.addWidget(self.list_panel, 0)
        return content

    def _editor(self, name: str) -> QLineEdit:
        by_name = {field.name: field for field in self.spec.fields}
        editor = self._make_editor(by_name[name])
        self.inputs[name] = editor
        return editor

    def _hidden_id(self, name: str) -> QLineEdit:
        editor = QLineEdit()
        editor.setReadOnly(True)
        editor.hide()
        self.inputs[name] = editor
        return editor

    def _labelled(self, caption: str, widget: QWidget) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        lab = QLabel(caption)
        lab.setStyleSheet("font-size:11.5px; font-weight:700; color:#64748B;")
        col.addWidget(lab)
        col.addWidget(widget)
        return box

    def _field_card(self) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("card")
        frame.setStyleSheet(
            "QFrame#card { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:10px; }"
        )
        col = QVBoxLayout(frame)
        col.setContentsMargins(13, 11, 13, 12)
        col.setSpacing(7)
        return frame, col

    def _build_form_column(self) -> QWidget:
        holder = QWidget()
        outer = QVBoxLayout(holder)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(11)

        # Row of two small cards: رقم السند + التاريخ.
        row = QHBoxLayout()
        row.setSpacing(11)
        no_card, no_col = self._field_card()
        no_col.addWidget(self._labelled("رقم السند", self._editor("payment_no")))
        date_card, date_col = self._field_card()
        date_col.addWidget(self._labelled("التاريخ", self._editor("payment_date")))
        row.addWidget(no_card)
        row.addWidget(date_card)
        outer.addLayout(row)

        # Crusher card (picker).
        sup_card, sup_col = self._field_card()
        self._hidden_id("supplier_id")
        pick = QWidget()
        prow = QHBoxLayout(pick)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.setSpacing(8)
        self._supplier_label = QLabel("— لم تُختَر —")
        self._supplier_label.setStyleSheet(
            "font-size:15px; font-weight:900; color:#111827; background:#F8FAFC; "
            "border:1px solid #E2E8F0; border-radius:7px; padding:8px 10px;"
        )
        self._supplier_label.setMinimumHeight(40)
        self.supplier_pick_button = QPushButton("اختيار كسّارة")
        self.supplier_pick_button.setFixedHeight(40)
        self.supplier_pick_button.setStyleSheet(_button_style(AMBER, AMBER_DARK))
        self.supplier_pick_button.clicked.connect(self.pick_supplier)
        prow.addWidget(self._supplier_label, 1)
        prow.addWidget(self.supplier_pick_button, 0)
        sup_col.addWidget(self._labelled("الكسّارة", pick))
        outer.addWidget(sup_card)

        # Amount card (big) + amount-in-words.
        amt_card = QFrame()
        amt_card.setObjectName("amt")
        amt_card.setStyleSheet(
            f"QFrame#amt {{ background:{AMBER_TINT}; border:1px solid {AMBER}55; border-radius:10px; }}"
        )
        amt_col = QVBoxLayout(amt_card)
        amt_col.setContentsMargins(13, 11, 13, 12)
        amt_col.setSpacing(6)
        amt_caption = QLabel("المبلغ المدفوع")
        amt_caption.setStyleSheet(f"font-size:11.5px; font-weight:700; color:{AMBER_DARK}; background:transparent;")
        amount_editor = self._editor("amount")
        amount_editor.setMinimumHeight(48)
        amount_editor.setStyleSheet(
            f"QLineEdit {{ background:#FFFFFF; border:1px solid {AMBER}; border-radius:8px; "
            f"padding:6px 12px; font-size:26px; font-weight:900; color:{AMBER_DARK}; }}"
            f"QLineEdit:focus {{ border:2px solid {AMBER_DARK}; }}"
            f"QLineEdit:read-only {{ background:#FBF5EC; color:{AMBER_DARK}; }}"
        )
        amount_editor.textChanged.connect(lambda _t=None: self._recompute())
        self._words_label = QLabel("—")
        self._words_label.setWordWrap(True)
        self._words_label.setStyleSheet(
            f"font-size:12px; font-weight:700; color:{AMBER_DARK}; background:transparent;"
        )
        amt_col.addWidget(amt_caption)
        amt_col.addWidget(amount_editor)
        amt_col.addWidget(self._words_label)
        outer.addWidget(amt_card)

        # Statement card.
        st_card, st_col = self._field_card()
        st_col.addWidget(self._labelled("البيان", self._editor("statement")))
        outer.addWidget(st_card)
        outer.addStretch(1)
        return holder

    def _build_analytics_column(self) -> QWidget:
        holder = QWidget()
        outer = QVBoxLayout(holder)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        # «الرصيد الجديد» callout.
        callout = QFrame()
        callout.setStyleSheet(f"QFrame {{ background:{AMBER}; border-radius:12px; }}")
        cbox = QVBoxLayout(callout)
        cbox.setContentsMargins(16, 14, 16, 14)
        cbox.setSpacing(2)
        ck = QLabel("الرصيد الجديد بعد السند")
        ck.setStyleSheet("color:rgba(255,255,255,0.9); font-size:12.5px; font-weight:700; background:transparent;")
        ck.setAlignment(Qt.AlignCenter)
        self._callout_value = QLabel("—")
        self._callout_value.setStyleSheet(
            "color:#FFFFFF; font-size:30px; font-weight:900; background:transparent;"
        )
        self._callout_value.setAlignment(Qt.AlignCenter)
        self._callout_value.setLayoutDirection(Qt.LeftToRight)
        self._callout_was = QLabel("")
        self._callout_was.setStyleSheet("color:rgba(255,255,255,0.85); font-size:12px; font-weight:700; background:transparent;")
        self._callout_was.setAlignment(Qt.AlignCenter)
        cbox.addWidget(ck)
        cbox.addWidget(self._callout_value)
        cbox.addWidget(self._callout_was)
        outer.addWidget(callout)

        # Donut card.
        donut_card = QFrame()
        donut_card.setStyleSheet(
            "QFrame { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:12px; }"
        )
        dbox = QVBoxLayout(donut_card)
        dbox.setContentsMargins(14, 12, 14, 14)
        dbox.setSpacing(8)
        dtitle = QLabel("نسبة سداد الكسّارة")
        dtitle.setStyleSheet("font-size:13px; font-weight:800; color:#111827; background:transparent;")
        dtitle.setAlignment(Qt.AlignCenter)
        dbox.addWidget(dtitle)

        drow = QHBoxLayout()
        drow.setSpacing(12)
        self._donut = _DonutChart()
        drow.addWidget(self._donut, 0)
        legend = QVBoxLayout()
        legend.setSpacing(8)
        legend.addWidget(self._legend_row("paid", "المدفوع", AMBER))
        legend.addWidget(self._legend_row("remaining", "المتبقي", RED))
        legend.addWidget(self._legend_row("due", "إجمالي مستحق", "#334155", divider=True))
        legend.addStretch(1)
        legend_box = QWidget()
        legend_box.setLayout(legend)
        drow.addWidget(legend_box, 1)
        dbox.addLayout(drow)
        outer.addWidget(donut_card)

        # Three stat cards.
        stats = QHBoxLayout()
        stats.setSpacing(9)
        stats.addWidget(self._stat_card("prev", "رصيد سابق", "#FFFFFF", "#111827"))
        stats.addWidget(self._stat_card("this", "هذا السند", AMBER_TINT, AMBER_DARK))
        stats.addWidget(self._stat_card("after", "الرصيد بعده", "#FBE7E7", RED))
        outer.addLayout(stats)
        outer.addStretch(1)
        return holder

    def _legend_row(self, key: str, caption: str, color: str, divider: bool = False) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 8 if divider else 0, 0, 0)
        row.setSpacing(8)
        if divider:
            box.setStyleSheet("border-top:1px solid #E2E8F0;")
        sw = QLabel()
        sw.setFixedSize(12, 12)
        sw.setStyleSheet(f"background:{color}; border-radius:3px;")
        name = QLabel(caption)
        name.setStyleSheet(
            f"font-size:12px; font-weight:{'800' if divider else '600'}; color:#475569;"
        )
        value = QLabel("—")
        value.setStyleSheet(f"font-size:13px; font-weight:900; color:{color};")
        value.setLayoutDirection(Qt.LeftToRight)
        value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if not divider:
            row.addWidget(sw, 0)
        else:
            row.addSpacing(20)
        row.addWidget(name, 0)
        row.addStretch(1)
        row.addWidget(value, 0)
        self._legend[key] = value
        return box

    def _stat_card(self, key: str, caption: str, bg: str, fg: str) -> QFrame:
        card = QFrame()
        border = "#E2E8F0" if bg == "#FFFFFF" else "transparent"
        card.setStyleSheet(f"QFrame {{ background:{bg}; border:1px solid {border}; border-radius:11px; }}")
        col = QVBoxLayout(card)
        col.setContentsMargins(10, 9, 10, 9)
        col.setSpacing(2)
        value = QLabel("—")
        value.setStyleSheet(f"font-size:16px; font-weight:900; color:{fg}; background:transparent;")
        value.setAlignment(Qt.AlignCenter)
        value.setLayoutDirection(Qt.LeftToRight)
        label = QLabel(caption)
        label.setStyleSheet("font-size:10.5px; font-weight:700; color:#64748B; background:transparent;")
        label.setAlignment(Qt.AlignCenter)
        col.addWidget(value)
        col.addWidget(label)
        self._stat_values[key] = value
        return card

    # -- the crusher picker ----------------------------------------------

    def pick_supplier(self) -> None:
        try:
            rows = self._backend().supplier_picker_rows()
        except Exception as exc:
            self._show_error("تعذّر تحميل قائمة الكسّارات", exc)
            return
        if not rows:
            QMessageBox.information(self, "لا توجد كسّارات", "أضِف كسّارة من شاشة الكسّارات أولًا.")
            return
        dialog = TawridSupplierPickerDialog(rows, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected:
            return
        chosen = dialog.selected
        self._set_editor_value(self.inputs.get("supplier_id"), chosen.get("supplier_id"))
        if self._supplier_label is not None:
            self._supplier_label.setText(str(chosen.get("supplier_name") or ""))
        self._recompute()

    def _id(self, name: str) -> Any:
        editor = self.inputs.get(name)
        if editor is None:
            return None
        value = self._editor_value(editor)
        return value if value not in (None, "") else None

    def _val(self, name: str) -> Any:
        editor = self.inputs.get(name)
        return self._editor_value(editor) if editor is not None else ""

    # -- live analytics --------------------------------------------------

    def _recompute(self) -> None:
        """Refresh the callout, the donut and the three stat cards.

        Uses the account *excluding* the payment on screen (its own amount taken
        back out), so «قبل / بعد» reads correctly whether entering a new payment
        or viewing a saved one.
        """
        amount = _num(self._val("amount"))
        if self._words_label is not None:
            self._words_label.setText(_amount_in_words(amount) if amount else "—")

        supplier_id = self._id("supplier_id")
        if supplier_id is None:
            self._paint_analytics(None, amount)
            return
        exclude = self.current_id if self.mode != "new" else None
        try:
            account = self._backend().account_for(supplier_id, exclude)
        except Exception:
            account = PaymentAccount()
        self._paint_analytics(account, amount)

    def _paint_analytics(self, account: PaymentAccount | None, amount: Decimal) -> None:
        if account is None or not account.movements_available:
            self._callout_value.setText("—")
            self._callout_was.setText("")
            for label in self._stat_values.values():
                label.setText("—")
            for label in self._legend.values():
                label.setText("—")
            if self._donut is not None:
                self._donut.set_ratio(0.0, "—")
            return

        total_owed = account.total_owed
        prev_balance = total_owed - account.base_paid       # قبل هذا السند
        after_balance = prev_balance - amount               # بعده
        paid_after = account.base_paid + amount

        if total_owed > 0:
            ratio = float(paid_after / total_owed)
        else:
            ratio = 1.0 if paid_after > 0 else 0.0
        # The label shows the TRUE percentage (may exceed 100% when overpaid); the
        # donut clamps only the drawn ring, not this figure — «مكة ستون» is at ~105%.
        pct = ratio * 100

        self._callout_value.setText(_money(after_balance))
        self._callout_was.setText(f"كان {_money(prev_balance)}")
        self._stat_values["prev"].setText(_money(prev_balance))
        self._stat_values["this"].setText(_money(-amount))
        self._stat_values["after"].setText(_money(after_balance))
        self._legend["paid"].setText(_money(paid_after))
        self._legend["remaining"].setText(_money(after_balance))
        self._legend["due"].setText(_money(total_owed))
        if self._donut is not None:
            self._donut.set_ratio(ratio, f"{pct:.1f}%")

    # -- navigation + search ---------------------------------------------

    def open_lookup(self) -> None:
        """«بحث عن سند صرف»: live search dialog, then load the chosen payment."""
        if self.mode in {"new", "edit"}:
            QMessageBox.information(self, "جاري التعديل", "احفظ السند أو ألغِه قبل فتح سند تاني.")
            return
        dialog = TawridPaymentPickerDialog(self._backend().search_payments, self)
        if dialog.exec() != QDialog.Accepted or dialog.selected_id is None:
            return
        self._load_payment(dialog.selected_id)

    def _load_payment(self, payment_id: Any) -> None:
        try:
            record = self.service.get_record(self.spec, payment_id)
        except Exception as exc:
            self._show_error("فشل تحميل السند", exc)
            return
        if not record:
            return
        self.current_id = payment_id
        self._fill_form(record)
        self.set_mode("view")
        self._select_row_by_id(payment_id)

    def _navigate(self, where: str) -> None:
        if self.mode in {"new", "edit"}:
            return
        total = self.table.rowCount()
        if total == 0:
            return
        current = self.table.currentRow()
        if current < 0:
            current = 0
        target = {
            "first": 0,
            "last": total - 1,
            "prev": max(0, current - 1),
            "next": min(total - 1, current + 1),
        }[where]
        if target != current:
            # setCurrentCell, not selectRow: Qt makes selectRow a no-op on a view
            # whose parent is hidden, and this list is hidden by design.
            self.table.setCurrentCell(target, 0)
        self._update_nav_state()

    def _update_nav_state(self) -> None:
        if not hasattr(self, "nav_buttons") or not hasattr(self, "table"):
            return
        browsing = self.mode not in {"new", "edit"}
        total = self.table.rowCount()
        current = self.table.currentRow()
        self.nav_buttons["first"].setEnabled(browsing and current > 0)
        self.nav_buttons["prev"].setEnabled(browsing and current > 0)
        self.nav_buttons["next"].setEnabled(browsing and 0 <= current < total - 1)
        self.nav_buttons["last"].setEnabled(browsing and 0 <= current < total - 1)
        if hasattr(self, "find_button"):
            self.find_button.setEnabled(browsing)

    # -- hooks fired by BaseCrudScreen -----------------------------------

    def set_mode(self, mode: str) -> None:
        super().set_mode(mode)
        editing = mode in {"new", "edit"}
        if hasattr(self, "supplier_pick_button"):
            self.supplier_pick_button.setEnabled(editing)
        self._update_nav_state()

    def refresh_table(self) -> None:
        super().refresh_table()
        if self.current_id is None and self.table.rowCount():
            self.table.setCurrentCell(0, 0)
        self._update_nav_state()

    def _select_row_by_id(self, record_id: Any) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and str(item.data(Qt.UserRole)) == str(record_id):
                self.table.setCurrentCell(row, 0)
                return

    def _fill_form(self, record: dict[str, Any]) -> None:
        self._filling = True
        try:
            for name in ("payment_no", "payment_date", "supplier_id", "amount", "statement"):
                self._set_editor_value(self.inputs.get(name), record.get(name))

            display = None
            payment_id = record.get(self.spec.primary_key) or self.current_id
            if payment_id is not None:
                try:
                    display = self._backend().for_payment(payment_id)
                except Exception:
                    display = None
            display = display or record
            if self._supplier_label is not None:
                self._supplier_label.setText(str(display.get("supplier_name") or "— لم تُختَر —"))

            name = str(display.get("supplier_name") or "").strip()
            no = record.get("payment_no")
            self.summary_label.setText(
                f"سند صرف رقم {no}" + (f" — {name}" if name else "")
            )
        finally:
            self._filling = False
        self._recompute()

    def _clear_form(self) -> None:
        self._filling = True
        try:
            super()._clear_form()
            if self._supplier_label is not None:
                self._supplier_label.setText("— لم تُختَر —")
        finally:
            self._filling = False
        self._recompute()

    def new_record(self) -> None:
        super().new_record()
        try:
            self._set_editor_value(self.inputs.get("payment_no"), self._backend().next_payment_no())
        except Exception:
            pass
        self._set_editor_value(
            self.inputs.get("payment_date"), datetime.date.today().strftime("%Y-%m-%d")
        )
        self.summary_label.setText("سند جديد")

    def save_record(self) -> None:
        """Validate the crusher and the number, zero a blank amount, then save."""
        if self._id("supplier_id") is None:
            QMessageBox.warning(self, "ناقص", "اختر الكسّارة قبل حفظ السند.")
            return
        payment_no = str(self._val("payment_no") or "").strip()
        if not payment_no:
            QMessageBox.warning(self, "ناقص", "اكتب رقم السند.")
            return
        try:
            if self._backend().payment_no_exists(int(payment_no), self.current_id):
                QMessageBox.warning(self, "رقم مكرر", f"رقم السند {payment_no} مستخدم في سند تاني.")
                return
        except (ValueError, TypeError):
            QMessageBox.warning(self, "غير صحيح", "رقم السند لازم يكون رقمًا صحيحًا.")
            return
        # A blank amount box means zero (the column is NOT NULL DEFAULT 0).
        amount_editor = self.inputs.get("amount")
        if amount_editor is not None and not str(self._editor_value(amount_editor) or "").strip():
            self._set_editor_value(amount_editor, 0)
        super().save_record()
