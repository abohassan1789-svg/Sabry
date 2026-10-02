"""شاشة البون — قسم التوريدات (Tawrid module, phase 4).

The heart of the module. Layout is "Model 3" from the mockup set the user picked:
**stacked full-width cards, one per party** — a shared header card, then the
customer / crusher / hauler cards, each in that party's colour — with **no ticket
list on the screen**. Finding an earlier bon is done through the «بحث عن بون»
dialog and the الأول/السابق/التالي/الأخير navigation, exactly like the crusher
screen. The full CRUD toolbar (جديد / تعديل / حفظ / حذف / إلغاء / خروج) is the
shared one from :class:`BaseCrudScreen`.

It replaces the Access screen ``Fboun`` over ``TBBOOn``. What is deliberately
different, and why — each tied to something measured in ``sisko.Accdb``:

* **Three price layers are shown as three cards, and computed live.** The five
  money totals (``total_cus``, ``amount_dis``, ``safi_cus``, ``total_res``,
  ``total_man``) are DB-GENERATED, so the labels only preview what the database
  will store — they can never drift from it.
* **Two volumes, never one.** ``cus_volume`` (Tak3ib) and ``res_volume``
  (Tak3ibres) are separate boxes on the customer and crusher cards; they differ
  on 4,015 of 4,072 legacy rows. The hauler's fee is on the customer's volume.
* **The item is a catalogue pick, not free text.** Choosing an item from
  ``tawrid_items`` is what maps the ticket to one of the ten fixed price columns
  — the deliberate replacement for ``Fboun``'s 10 hardcoded ``IF`` branches — and
  the three cards' prices auto-fill from that item on each card.
* **The three parties are pickers, not deletable-into combos.** A ticket cannot
  be saved without a customer and a crusher (both NOT NULL), so the raw
  constraint never surfaces.

The row's own INSERT/UPDATE/DELETE is the shared path (``ReviewDataService`` +
``TABLE_SPECS['tawrid_tickets']``); the pricing, the joined display record and the
pickers come from :class:`TawridTicketService`.
"""

from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.review_data_service import ReviewDataService, TABLE_SPECS
from app.services.tawrid_ticket_service import TawridTicketService
from app.ui.common.theme import GREEN, _button_style
from app.ui.dialogs.tawrid_customer_picker import TawridCustomerPickerDialog
from app.ui.dialogs.tawrid_supplier_picker import TawridSupplierPickerDialog
from app.ui.dialogs.tawrid_ticket_picker import TawridTicketPickerDialog
from app.ui.dialogs.tawrid_tractor_picker import TawridTractorPickerDialog
from app.ui.screens.base_crud_screen import BaseCrudScreen

# Party colours, matching the chosen mockup: customer green, crusher amber,
# hauler blue. Each is (accent, wash) for the card title strip and the computed
# total box.
CUS = ("#137A38", "#E7F3EC")
RES = ("#B45309", "#FBF0E2")
MAN = ("#1D4ED8", "#E8EEFC")

# Numeric boxes that are NOT NULL DEFAULT 0, so a blank one means zero.
_ZERO_IF_BLANK = (
    "cus_volume",
    "price_cus",
    "discount_percent",
    "res_volume",
    "price_res",
    "price_man",
)


def _money(value: Decimal | float | int | None) -> str:
    """Thousands-separated, two decimals. Negative shown as ``1,234.00-``."""
    amount = Decimal(str(value or 0))
    text = f"{abs(amount):,.2f}"
    return f"{text}-" if amount < 0 else text


def _num(text: Any) -> Decimal:
    """Read a numeric box. Blank/unparseable is zero (the boxes default to 0)."""
    cleaned = str(text or "").replace(",", "").strip()
    if cleaned == "":
        return Decimal("0")
    if cleaned.endswith("-"):
        cleaned = "-" + cleaned[:-1]
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal("0")


class TawridTicketsScreen(BaseCrudScreen):
    SPEC_KEY = "tawrid_tickets"
    SEARCH_PLACEHOLDER = "ابحث برقم البون أو اسم العميل"

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        # Populated before super().__init__ because the base constructor builds
        # the UI, which calls back into the widgets built here.
        self._backend_service: TawridTicketService | None = None
        self._calc: dict[str, QLabel] = {}
        self._party_labels: dict[str, QLabel] = {}
        self._item_combo: QComboBox | None = None
        self._filling = False
        super().__init__(service, TABLE_SPECS[self.SPEC_KEY], parent)
        self._recompute()

    # -- backend ---------------------------------------------------------

    def _backend(self) -> TawridTicketService:
        if self._backend_service is None:
            self._backend_service = TawridTicketService()
        return self._backend_service

    # -- toolbar ---------------------------------------------------------

    def _install_extra_toolbar_buttons(self, layout: QHBoxLayout) -> None:
        """«بحث عن بون» + the record navigation that stands in for the list."""
        self.find_button = QPushButton("بحث عن بون")
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
        """Four stacked cards; the base list is built and hidden for navigation."""
        content = QVBoxLayout()
        content.setSpacing(10)

        # The base class writes to ``summary_label`` on every load/new/clear, but
        # only builds it inside its form panel — which this screen replaces. Build
        # it here so those writes land, and show it as a thin caption line.
        self.summary_label = QLabel("سجل جديد")
        self.summary_label.setStyleSheet("font-size:13px; font-weight:800; color:#64748B;")
        content.addWidget(self.summary_label, 0)

        content.addWidget(self._build_header_card(), 0)
        content.addWidget(self._build_customer_card(), 0)
        content.addWidget(self._build_supplier_card(), 0)
        content.addWidget(self._build_hauler_card(), 0)
        content.addStretch(1)

        # The list panel stays built (the base class drives selection and the
        # record count through ``self.table``) but hidden — the user asked for no
        # ticket list on the screen; navigation and «بحث عن بون» use it instead.
        self.list_panel = self._build_list_panel()
        self.list_panel.hide()
        content.addWidget(self.list_panel, 0)
        return content

    def _editor(self, name: str) -> QLineEdit:
        """Build a spec-styled editor for *name* and register it in self.inputs."""
        by_name = {field.name: field for field in self.spec.fields}
        editor = self._make_editor(by_name[name])
        self.inputs[name] = editor
        return editor

    def _hidden_id(self, name: str) -> QLineEdit:
        """A never-shown line edit that carries a party id into the save payload."""
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

    def _card(self, title: str, role: str, accent: tuple[str, str]) -> tuple[QFrame, QGridLayout]:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame#card {{ background:#FFFFFF; border:1px solid #E2E8F0; border-radius:9px; }}"
        )
        frame.setObjectName("card")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        strip = QFrame()
        strip.setStyleSheet(
            f"background:{accent[0]}; border-top-left-radius:8px; border-top-right-radius:8px;"
        )
        srow = QHBoxLayout(strip)
        srow.setContentsMargins(13, 7, 13, 7)
        head = QLabel(title)
        head.setStyleSheet("color:#FFFFFF; font-size:14px; font-weight:900; background:transparent;")
        role_lab = QLabel(role)
        role_lab.setStyleSheet("color:rgba(255,255,255,0.9); font-size:11px; font-weight:700; background:transparent;")
        srow.addWidget(head)
        srow.addStretch(1)
        srow.addWidget(role_lab)
        outer.addWidget(strip)

        body = QGridLayout()
        body.setContentsMargins(13, 11, 13, 12)
        body.setHorizontalSpacing(12)
        body.setVerticalSpacing(8)
        holder = QWidget()
        holder.setLayout(body)
        outer.addWidget(holder)
        return frame, body

    def _calc_label(self, key: str, accent: tuple[str, str]) -> QWidget:
        box = QFrame()
        box.setStyleSheet(
            f"QFrame {{ background:{accent[1]}; border:1px solid {accent[0]}33; border-radius:7px; }}"
        )
        col = QVBoxLayout(box)
        col.setContentsMargins(10, 6, 10, 6)
        col.setSpacing(1)
        value = QLabel("0.00")
        value.setStyleSheet(
            f"font-size:18px; font-weight:900; color:{accent[0]}; background:transparent; border:none;"
        )
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value.setLayoutDirection(Qt.LeftToRight)
        self._calc[key] = value
        col.addWidget(value)
        return box

    def _pick_row(self, party: str, caption: str, on_click) -> QWidget:
        """A party display line: the chosen name + a «اختيار» button."""
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        value = QLabel("— لم يُختَر —")
        value.setStyleSheet(
            "font-size:14px; font-weight:900; color:#111827; background:#F8FAFC; "
            "border:1px solid #E2E8F0; border-radius:7px; padding:7px 10px;"
        )
        value.setMinimumHeight(38)
        self._party_labels[party] = value
        button = QPushButton(caption)
        button.setFixedHeight(38)
        button.setStyleSheet(_button_style(GREEN, "#0F6B30"))
        button.clicked.connect(on_click)
        setattr(self, f"{party}_pick_button", button)
        row.addWidget(value, 1)
        row.addWidget(button, 0)
        return box

    def _build_header_card(self) -> QFrame:
        frame, grid = self._card("بيانات البون", "مشترك", (GREEN, "#E7F3EC"))
        grid.addWidget(self._labelled("رقم البون", self._editor("ticket_no")), 0, 0)
        grid.addWidget(self._labelled("التاريخ", self._editor("ticket_date")), 0, 1)
        grid.addWidget(self._labelled("رقم الإيصال", self._editor("receipt_no")), 0, 2)

        # The item combo drives the price mapping; item_name/item_family ride
        # along in hidden editors so they are stored on the ticket.
        self._item_combo = QComboBox()
        self._item_combo.setMinimumHeight(38)
        self._item_combo.setLayoutDirection(Qt.RightToLeft)
        self._item_combo.setStyleSheet(
            f"QComboBox {{ background:#FFFFFF; border:1px solid {GREEN}; border-radius:7px; "
            "padding:6px 10px; font-size:14px; font-weight:900; color:#111827; }"
            "QComboBox:disabled { background:#F8FAFC; color:#64748B; }"
        )
        self._reload_items()
        self._item_combo.currentIndexChanged.connect(self._on_item_changed)
        self.inputs["item_id"] = self._item_combo
        self._hidden_id("item_name")
        self._hidden_id("item_family")
        self._family_label = QLabel("—")
        self._family_label.setStyleSheet(
            "font-size:13px; font-weight:800; color:#475569; background:#F8FAFC; "
            "border:1px solid #E2E8F0; border-radius:7px; padding:7px 10px;"
        )
        self._family_label.setMinimumHeight(38)
        grid.addWidget(self._labelled("الصنف", self._item_combo), 1, 0, 1, 2)
        grid.addWidget(self._labelled("نوع الصنف", self._family_label), 1, 2)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        return frame

    def _build_customer_card(self) -> QFrame:
        frame, grid = self._card("العميل", "يستلم ويُحاسَب", CUS)
        self._hidden_id("customer_id")
        grid.addWidget(self._pick_row("customer", "اختيار عميل", self.pick_customer), 0, 0, 1, 4)
        grid.addWidget(self._labelled("التكعيب (تكعيب العميل)", self._num_editor("cus_volume")), 1, 0)
        grid.addWidget(self._labelled("سعر المتر", self._num_editor("price_cus")), 1, 1)
        grid.addWidget(self._labelled("نسبة الخصم %", self._num_editor("discount_percent")), 1, 2)
        grid.addWidget(self._labelled("الصافي المستحق", self._calc_label("safi_cus", CUS)), 1, 3)
        for col in range(4):
            grid.setColumnStretch(col, 1)
        return frame

    def _build_supplier_card(self) -> QFrame:
        frame, grid = self._card("الكسّارة", "تورّد المنتج", RES)
        self._hidden_id("supplier_id")
        grid.addWidget(self._pick_row("supplier", "اختيار كسّارة", self.pick_supplier), 0, 0, 1, 4)
        grid.addWidget(self._labelled("التكعيب (تكعيب الكسّارة)", self._num_editor("res_volume")), 1, 0)
        grid.addWidget(self._labelled("سعر المتر", self._num_editor("price_res")), 1, 1)
        grid.addWidget(QWidget(), 1, 2)
        grid.addWidget(self._labelled("إجمالي التوريد", self._calc_label("total_res", RES)), 1, 3)
        for col in range(4):
            grid.setColumnStretch(col, 1)
        return frame

    def _build_hauler_card(self) -> QFrame:
        frame, grid = self._card("الجرار", "ينقل الحمولة", MAN)
        self._hidden_id("tractor_id")
        grid.addWidget(self._pick_row("tractor", "اختيار جرار", self.pick_tractor), 0, 0, 1, 4)
        grid.addWidget(self._labelled("سعر النقل", self._num_editor("price_man")), 1, 0)
        hint = QLabel("الأجرة تُحسب على تكعيب العميل")
        hint.setStyleSheet(
            "font-size:12px; font-weight:800; color:#475569; background:#F8FAFC; "
            "border:1px solid #E2E8F0; border-radius:7px; padding:7px 10px;"
        )
        hint.setMinimumHeight(38)
        grid.addWidget(self._labelled("محسوب على", hint), 1, 1, 1, 2)
        grid.addWidget(self._labelled("أجرة الجرار", self._calc_label("total_man", MAN)), 1, 3)
        for col in range(4):
            grid.setColumnStretch(col, 1)
        return frame

    def _num_editor(self, name: str) -> QLineEdit:
        editor = self._editor(name)
        editor.textChanged.connect(lambda _t=None: self._recompute())
        return editor

    # -- item combo ------------------------------------------------------

    def _reload_items(self) -> None:
        if self._item_combo is None:
            return
        self._item_combo.blockSignals(True)
        self._item_combo.clear()
        self._item_combo.addItem("— اختر الصنف —", None)
        try:
            for item in self._backend().items():
                self._item_combo.addItem(item.item_name, item.item_id)
        except Exception:
            pass
        self._item_combo.setCurrentIndex(0)
        self._item_combo.blockSignals(False)

    def _on_item_changed(self, *_args) -> None:
        item_id = self._item_combo.currentData() if self._item_combo else None
        item = self._backend().item(item_id) if item_id else None
        self._set_editor_value(self.inputs.get("item_name"), item.item_name if item else "")
        self._set_editor_value(self.inputs.get("item_family"), item.item_family if item else "")
        self._family_label.setText(item.item_family if item else "—")
        if not self._filling:
            self._autofill_prices()

    # -- pickers ---------------------------------------------------------

    def pick_customer(self) -> None:
        try:
            rows = self._backend().customer_picker_rows()
        except Exception as exc:
            self._show_error("تعذّر تحميل قائمة العملاء", exc)
            return
        if not rows:
            QMessageBox.information(self, "لا يوجد عملاء", "أضِف عميلًا من شاشة العملاء أولًا.")
            return
        dialog = TawridCustomerPickerDialog(rows, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected:
            return
        chosen = dialog.selected
        self._set_editor_value(self.inputs.get("customer_id"), chosen.get("customer_id"))
        self._party_labels["customer"].setText(str(chosen.get("customer_name") or ""))
        self._autofill_prices()
        self._autofill_volume()

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
        self._party_labels["supplier"].setText(str(chosen.get("supplier_name") or ""))
        self._autofill_prices()
        self._autofill_res_volume()

    def pick_tractor(self) -> None:
        try:
            rows = self._backend().tractor_picker_rows()
        except Exception as exc:
            self._show_error("تعذّر تحميل قائمة الجرارات", exc)
            return
        if not rows:
            QMessageBox.information(self, "لا توجد جرارات", "أضِف جرارًا من شاشة الجرارات أولًا.")
            return
        # When a customer is chosen, offer to narrow the list to that customer's
        # own tractors (the price-grid pairs); when a crusher is chosen, to that
        # crusher's own tractors (from the تكعيب الكسّارات sheets). Default stays
        # «كل الجرارات».
        customer_id = self._id("customer_id")
        customer_rows = None
        customer_name = None
        if customer_id is not None:
            try:
                customer_rows = self._backend().customer_tractor_picker_rows(customer_id)
            except Exception:
                customer_rows = None
            customer_name = self._party_labels["customer"].text()

        supplier_id = self._id("supplier_id")
        crusher_rows = None
        crusher_name = None
        if supplier_id is not None:
            try:
                crusher_rows = self._backend().crusher_tractor_picker_rows(supplier_id)
            except Exception:
                crusher_rows = None
            crusher_name = self._party_labels["supplier"].text()

        dialog = TawridTractorPickerDialog(
            rows, self, customer_rows=customer_rows, customer_name=customer_name,
            crusher_rows=crusher_rows, crusher_name=crusher_name,
        )
        if dialog.exec() != QDialog.Accepted or not dialog.selected:
            return
        chosen = dialog.selected
        self._set_editor_value(self.inputs.get("tractor_id"), chosen.get("tractor_id"))
        name = str(chosen.get("driver_name") or "")
        plate = chosen.get("head_no") or chosen.get("trailer_no")
        self._party_labels["tractor"].setText(f"{name} — وش {plate}" if plate else name)
        self._autofill_prices()
        self._autofill_volume()
        self._autofill_res_volume()

    def _autofill_prices(self) -> None:
        """Fill the three prices (and default discount) from the chosen cards.

        Only in edit/new mode — viewing a saved ticket must show its own stored
        prices, never re-derive them from today's cards.
        """
        if self.mode not in {"new", "edit"} or self._filling:
            return
        prices = self._backend().prices_for(
            self._id("customer_id"),
            self._id("supplier_id"),
            self._id("tractor_id"),
            self._id("item_id"),
        )
        self._set_editor_value(self.inputs.get("price_cus"), _money(prices.price_cus))
        self._set_editor_value(self.inputs.get("price_res"), _money(prices.price_res))
        self._set_editor_value(self.inputs.get("price_man"), _money(prices.price_man))
        # Default the discount from the customer only when the box is still empty,
        # so re-picking a tractor never wipes a discount the user typed.
        if _num(self._editor_value(self.inputs.get("discount_percent"))) == 0:
            self._set_editor_value(self.inputs.get("discount_percent"), _money(prices.discount_percent))
        self._recompute()

    def _autofill_volume(self) -> None:
        """Set ``cus_volume`` from the customer×tractor grid for the chosen pair.

        The load is set up per (customer, tractor) on the customers screen
        (``load_volume`` = ``CarCus.tak3ib``), so once both are picked the
        customer's volume is known and should not be re-typed. Fired only from
        the customer/tractor picks — never on an item change — so a hand-typed
        volume survives switching the صنف.

        A pick is an explicit choice of the pair, so it always reflects the NEW
        pair: the new tractor's grid load, or — when that pair has no grid row —
        a cleared box. Leaving the previous tractor's number would be the bug the
        user hit: changing the tractor kept the first volume.
        """
        if self.mode not in {"new", "edit"} or self._filling:
            return
        if self._id("tractor_id") is None:
            return
        try:
            volume = self._backend().grid_volume(self._id("customer_id"), self._id("tractor_id"))
        except Exception:
            volume = None
        self._set_editor_value(
            self.inputs.get("cus_volume"), _money(volume) if volume is not None else ""
        )
        self._recompute()

    def _autofill_res_volume(self) -> None:
        """Set ``res_volume`` (تكعيب الكسّارة) from the crusher×tractor cubing sheets.

        When a crusher and a tractor are both chosen, the crusher's own volume for
        that tractor is known from the تكعيب الكسّارات sheets — so it should not be
        re-typed. Fired from the crusher/tractor picks (not the customer pick, and
        not an item change), so a hand-typed crusher volume survives those.

        Unlike ``cus_volume`` this only **fills when a cubing row exists** and never
        clears otherwise: the crusher volume has a meaningful manual default and
        the cubing sheets are a supplementary source, not the authoritative per-pair
        config the customer grid is.
        """
        if self.mode not in {"new", "edit"} or self._filling:
            return
        tractor_id = self._id("tractor_id")
        supplier_id = self._id("supplier_id")
        if tractor_id is None or supplier_id is None:
            return
        try:
            volume = self._backend().crusher_volume(supplier_id, tractor_id)
        except Exception:
            volume = None
        if volume is not None:
            self._set_editor_value(self.inputs.get("res_volume"), _money(volume))
            self._recompute()

    def _id(self, name: str) -> Any:
        editor = self.inputs.get(name)
        if editor is None:
            return None
        value = self._editor_value(editor)
        return value if value not in (None, "") else None

    # -- live totals -----------------------------------------------------

    def _recompute(self) -> None:
        """Preview the five generated totals with the exact DB formulas."""
        cus_vol = _num(self._val("cus_volume"))
        price_cus = _num(self._val("price_cus"))
        disc = _num(self._val("discount_percent"))
        res_vol = _num(self._val("res_volume"))
        price_res = _num(self._val("price_res"))
        price_man = _num(self._val("price_man"))

        total_cus = (price_cus * cus_vol).quantize(Decimal("0.01"))
        amount_dis = (total_cus * disc / Decimal("100")).quantize(Decimal("0.01"))
        safi_cus = total_cus - amount_dis
        total_res = (price_res * res_vol).quantize(Decimal("0.01"))
        total_man = (price_man * cus_vol).quantize(Decimal("0.01"))

        self._calc["safi_cus"].setText(_money(safi_cus))
        self._calc["total_res"].setText(_money(total_res))
        self._calc["total_man"].setText(_money(total_man))

    def _val(self, name: str) -> Any:
        editor = self.inputs.get(name)
        return self._editor_value(editor) if editor is not None else ""

    # -- navigation + search ---------------------------------------------

    def open_lookup(self) -> None:
        """«بحث عن بون»: live search dialog, then load the chosen ticket."""
        if self.mode in {"new", "edit"}:
            QMessageBox.information(
                self, "جاري التعديل", "احفظ البون أو ألغِه قبل فتح بون تاني."
            )
            return
        dialog = TawridTicketPickerDialog(self._backend().search_tickets, self)
        if dialog.exec() != QDialog.Accepted or dialog.selected_id is None:
            return
        self._load_ticket(dialog.selected_id)

    def _load_ticket(self, ticket_id: Any) -> None:
        try:
            record = self.service.get_record(self.spec, ticket_id)
        except Exception as exc:
            self._show_error("فشل تحميل البون", exc)
            return
        if not record:
            return
        self.current_id = ticket_id
        self._fill_form(record)
        self.set_mode("view")
        self._select_row_by_id(ticket_id)

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
        # The item combo and the pick buttons follow the same lock as the fields.
        editing = mode in {"new", "edit"}
        for party in ("customer", "supplier", "tractor"):
            button = getattr(self, f"{party}_pick_button", None)
            if button is not None:
                button.setEnabled(editing)
        self._update_nav_state()

    def refresh_table(self) -> None:
        super().refresh_table()
        # The base opens on the first record with selectRow(0), a no-op on a view
        # inside a hidden parent — this list is hidden by design.
        if self.current_id is None and self.table.rowCount():
            self.table.setCurrentCell(0, 0)
        self._update_nav_state()

    def refresh_screen(self) -> None:
        super().refresh_screen()
        self._reload_items()

    def _select_row_by_id(self, record_id: Any) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and str(item.data(Qt.UserRole)) == str(record_id):
                self.table.setCurrentCell(row, 0)
                return

    def _fill_form(self, record: dict[str, Any]) -> None:
        """Populate the cards from a stored ticket + its joined display record."""
        self._filling = True
        try:
            for name in (
                "ticket_no", "ticket_date", "receipt_no",
                "customer_id", "supplier_id", "tractor_id", "item_id",
                "item_name", "item_family",
                "cus_volume", "price_cus", "discount_percent",
                "res_volume", "price_res", "price_man",
            ):
                self._set_editor_value(self.inputs.get(name), record.get(name))

            display = None
            ticket_id = record.get(self.spec.primary_key) or self.current_id
            if ticket_id is not None:
                try:
                    display = self._backend().for_ticket(ticket_id)
                except Exception:
                    display = None
            display = display or record
            self._party_labels["customer"].setText(str(display.get("customer_name") or "— لم يُختَر —"))
            self._party_labels["supplier"].setText(str(display.get("supplier_name") or "— لم يُختَر —"))
            driver = display.get("driver_name")
            if driver:
                plate = display.get("head_no") or display.get("trailer_no")
                self._party_labels["tractor"].setText(f"{driver} — وش {plate}" if plate else str(driver))
            else:
                self._party_labels["tractor"].setText("— لم يُختَر —")
            self._family_label.setText(str(display.get("item_family") or "—"))

            name = str(display.get("customer_name") or "").strip()
            no = record.get("ticket_no")
            self.summary_label.setText(
                f"البون رقم {no}" + (f" — {name}" if name else "")
            )
        finally:
            self._filling = False
        self._recompute()

    def _clear_form(self) -> None:
        self._filling = True
        try:
            super()._clear_form()
            if self._item_combo is not None:
                self._item_combo.setCurrentIndex(0)
            for party in ("customer", "supplier", "tractor"):
                self._party_labels[party].setText("— لم يُختَر —")
            self._family_label.setText("—")
        finally:
            self._filling = False
        self._recompute()

    def new_record(self) -> None:
        super().new_record()
        # Suggest the next البون number and default to today; the parties stay
        # blank until picked.
        try:
            self._set_editor_value(self.inputs.get("ticket_no"), self._backend().next_ticket_no())
        except Exception:
            pass
        self._set_editor_value(
            self.inputs.get("ticket_date"), datetime.date.today().strftime("%Y-%m-%d")
        )
        self.summary_label.setText("بون جديد")

    def save_record(self) -> None:
        """Validate the parties and the number, zero blank money boxes, then save."""
        if self._id("customer_id") is None:
            QMessageBox.warning(self, "ناقص", "اختر العميل قبل حفظ البون.")
            return
        if self._id("supplier_id") is None:
            QMessageBox.warning(self, "ناقص", "اختر الكسّارة قبل حفظ البون.")
            return
        ticket_no = str(self._val("ticket_no") or "").strip()
        if not ticket_no:
            QMessageBox.warning(self, "ناقص", "اكتب رقم البون.")
            return
        try:
            if self._backend().ticket_no_exists(int(ticket_no), self.current_id):
                QMessageBox.warning(
                    self, "رقم مكرر", f"رقم البون {ticket_no} مستخدم في بون تاني."
                )
                return
        except (ValueError, TypeError):
            QMessageBox.warning(self, "غير صحيح", "رقم البون لازم يكون رقمًا صحيحًا.")
            return

        for name in _ZERO_IF_BLANK:
            editor = self.inputs.get(name)
            if editor is not None and not str(self._editor_value(editor) or "").strip():
                self._set_editor_value(editor, 0)
        super().save_record()

    def delete_record(self) -> None:
        # A ticket has no children; the plain confirm from the base is enough.
        super().delete_record()
