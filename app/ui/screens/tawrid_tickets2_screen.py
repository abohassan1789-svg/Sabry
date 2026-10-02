"""شاشة «بون 2» — شكل بديل لإدخال البون (قسم التوريدات).

The client wanted a **second look** for entering the البون without giving up the
first: same table, same math, same pickers — a different arrangement to type on.
So this screen edits exactly the same ``tawrid_tickets`` row as
:class:`~app.ui.screens.tawrid_tickets_screen.TawridTicketsScreen`, but presents
it through an **internal tab** the user switches between:

* **الأعمدة الثلاثة** — a header card, then the جرار / العميل / الكسّارة cards
  side by side, and a dark strip with the margin and the three totals.
* **شاشة بقسمين** — an Access-style two-panel form: البيانات والأطراف on the right,
  الحسابات on the left.

Both tabs carry a *complete, independent* set of editors; only the visible tab is
ever interacted with, and switching tabs copies the current values across, so the
two are always showing the same ticket. The active tab's editors are what
``BaseCrudScreen`` sees as ``self.inputs`` (repointed on every switch), so the
shared save / load / delete / navigation path is unchanged.

**Tractor-first filtering** (the difference the user asked for): the جرار is
chosen first, and it narrows the two other pickers — the customer picker opens on
that tractor's customers (the عميل×جرار price grid) and the crusher picker on that
tractor's crushers (the تكعيب الكسّارات sheets), each with «كل …» one click away.
That is the reverse of the old screen, which narrows the *tractor* list instead.

All queries and the price/volume auto-fill come from the shared
:class:`TawridTicketService`; no new table, no new column.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
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
    QTabWidget,
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

# The party colours (accent, wash) shared with the first البون screen: customer
# green, crusher amber, hauler blue.
from app.ui.screens.tawrid_tickets_screen import (
    CUS,
    MAN,
    RES,
    _ZERO_IF_BLANK,
    _money,
    _num,
)

# Every field editor a tab must carry, so a switch copies a complete record.
_FIELDS = (
    "ticket_no", "ticket_date", "receipt_no",
    "item_id", "item_name", "item_family",
    "customer_id", "supplier_id", "tractor_id",
    "cus_volume", "price_cus", "discount_percent",
    "res_volume", "price_res", "price_man",
)


class _Tab:
    """The per-tab widget registry. Repointed onto the screen when it goes live."""

    def __init__(self) -> None:
        self.inputs: dict[str, Any] = {}
        self.calc: dict[str, QLabel] = {}
        self.party_labels: dict[str, QLabel] = {}
        self.pick_buttons: dict[str, QPushButton] = {}
        self.item_combo: QComboBox | None = None
        self.family_label: QLabel | None = None


class TawridTickets2Screen(BaseCrudScreen):
    SPEC_KEY = "tawrid_tickets"
    SEARCH_PLACEHOLDER = "ابحث برقم البون أو اسم العميل"

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        self._backend_service: TawridTicketService | None = None
        self._tabs: list[_Tab] = [_Tab(), _Tab()]
        self._active = 0
        self._filling = False
        # Live aliases the inherited/overridden methods read; repointed by
        # _use_tab to the active tab's registry.
        self.inputs = {}
        self._calc: dict[str, QLabel] = {}
        self._party_labels: dict[str, QLabel] = {}
        self._pick_buttons: dict[str, QPushButton] = {}
        self._item_combo: QComboBox | None = None
        self._family_label: QLabel | None = None
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
        content = QVBoxLayout()
        content.setSpacing(10)

        # The base writes to ``summary_label`` on every load/new/clear; it lives
        # in the form panel this screen replaces, so build it here as a caption.
        self.summary_label = QLabel("سجل جديد")
        self.summary_label.setStyleSheet("font-size:13px; font-weight:800; color:#64748B;")
        content.addWidget(self.summary_label, 0)

        self.tabs = QTabWidget()
        self.tabs.setLayoutDirection(Qt.RightToLeft)
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border:1px solid #E2E8F0; border-radius:10px; top:-1px; }"
            "QTabBar::tab { background:#F1F5F9; color:#475569; font-weight:900; font-size:13.5px; "
            "padding:9px 20px; margin-left:4px; border-top-left-radius:8px; border-top-right-radius:8px; }"
            f"QTabBar::tab:selected {{ background:{GREEN}; color:#FFFFFF; }}"
        )
        self.tabs.addTab(self._build_tab_columns(self._tabs[0]), "الأعمدة الثلاثة")
        self.tabs.addTab(self._build_tab_split(self._tabs[1]), "شاشة بقسمين")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        content.addWidget(self.tabs, 1)

        # Make tab 0 the live registry before the base finishes constructing.
        self._use_tab(0)
        self._reload_items()

        # The base drives selection and the record count through ``self.table``;
        # keep the list panel built but hidden (no ticket list on this screen).
        self.list_panel = self._build_list_panel()
        self.list_panel.hide()
        content.addWidget(self.list_panel, 0)
        return content

    # -- shared editor builders (register into a tab's registry) ---------

    def _spec_field(self, name: str):
        by_name = {field.name: field for field in self.spec.fields}
        return by_name[name]

    def _mk(self, tab: _Tab, name: str) -> QWidget:
        editor = self._make_editor(self._spec_field(name))
        tab.inputs[name] = editor
        return editor

    def _mk_num(self, tab: _Tab, name: str) -> QLineEdit:
        editor = self._mk(tab, name)
        editor.textChanged.connect(lambda _t=None: self._recompute())
        return editor

    def _hidden(self, tab: _Tab, name: str) -> None:
        editor = QLineEdit()
        editor.setReadOnly(True)
        editor.hide()
        tab.inputs[name] = editor

    def _build_item_combo(self, tab: _Tab) -> QComboBox:  # type: ignore[override]
        combo = QComboBox()
        combo.setMinimumHeight(38)
        combo.setLayoutDirection(Qt.RightToLeft)
        combo.setStyleSheet(
            f"QComboBox {{ background:#FFFFFF; border:1px solid {GREEN}; border-radius:7px; "
            "padding:6px 10px; font-size:14px; font-weight:900; color:#111827; }"
            "QComboBox:disabled { background:#F8FAFC; color:#64748B; }"
        )
        combo.currentIndexChanged.connect(lambda _i=0, t=tab: self._on_item_changed(t))
        tab.inputs["item_id"] = combo
        tab.item_combo = combo
        self._hidden(tab, "item_name")
        self._hidden(tab, "item_family")
        return combo

    def _family_box(self, tab: _Tab) -> QLabel:
        label = QLabel("—")
        label.setStyleSheet(
            "font-size:13px; font-weight:800; color:#475569; background:#F8FAFC; "
            "border:1px solid #E2E8F0; border-radius:7px; padding:7px 10px;"
        )
        label.setMinimumHeight(38)
        tab.family_label = label
        return label

    def _calc_box(self, tab: _Tab, key: str, accent: tuple[str, str], big: bool = True) -> QFrame:
        box = QFrame()
        box.setStyleSheet(
            f"QFrame {{ background:{accent[1]}; border:1px solid {accent[0]}33; border-radius:7px; }}"
        )
        col = QVBoxLayout(box)
        col.setContentsMargins(10, 6, 10, 6)
        col.setSpacing(1)
        value = QLabel("0.00")
        value.setStyleSheet(
            f"font-size:{18 if big else 15}px; font-weight:900; color:{accent[0]}; "
            "background:transparent; border:none;"
        )
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value.setLayoutDirection(Qt.LeftToRight)
        tab.calc[key] = value
        col.addWidget(value)
        return box

    def _pick_row(self, tab: _Tab, party: str, caption: str, accent: str, on_click) -> QWidget:
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
        tab.party_labels[party] = value
        button = QPushButton(caption)
        button.setFixedHeight(38)
        button.setStyleSheet(_button_style(accent, "#0F6B30" if accent == GREEN else accent))
        button.clicked.connect(on_click)
        tab.pick_buttons[party] = button
        row.addWidget(value, 1)
        row.addWidget(button, 0)
        return box

    @staticmethod
    def _labelled(caption: str, widget: QWidget) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        lab = QLabel(caption)
        lab.setStyleSheet("font-size:11.5px; font-weight:700; color:#64748B;")
        col.addWidget(lab)
        col.addWidget(widget)
        return box

    @staticmethod
    def _card(title: str, role: str, accent: tuple[str, str] | str) -> tuple[QFrame, QGridLayout]:
        strip_colour = accent[0] if isinstance(accent, tuple) else accent
        frame = QFrame()
        frame.setObjectName("card")
        frame.setStyleSheet(
            "QFrame#card { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:9px; }"
        )
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        strip = QFrame()
        strip.setStyleSheet(
            f"background:{strip_colour}; border-top-left-radius:8px; border-top-right-radius:8px;"
        )
        srow = QHBoxLayout(strip)
        srow.setContentsMargins(13, 7, 13, 7)
        head = QLabel(title)
        head.setStyleSheet("color:#FFFFFF; font-size:14px; font-weight:900; background:transparent;")
        role_lab = QLabel(role)
        role_lab.setStyleSheet(
            "color:rgba(255,255,255,0.9); font-size:11px; font-weight:700; background:transparent;"
        )
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

    # -- tab 1: three columns --------------------------------------------

    def _build_tab_columns(self, tab: _Tab) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(12, 12, 12, 12)
        col.setSpacing(10)

        header, grid = self._card("بيانات البون", "مشترك", GREEN)
        grid.addWidget(self._labelled("رقم البون", self._mk(tab, "ticket_no")), 0, 0)
        grid.addWidget(self._labelled("التاريخ", self._mk(tab, "ticket_date")), 0, 1)
        grid.addWidget(self._labelled("رقم الإيصال", self._mk(tab, "receipt_no")), 0, 2)
        grid.addWidget(self._labelled("الصنف", self._build_item_combo(tab)), 1, 0, 1, 2)
        grid.addWidget(self._labelled("نوع الصنف", self._family_box(tab)), 1, 2)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        col.addWidget(header, 0)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        cards.addWidget(self._col_hauler(tab), 1)
        cards.addWidget(self._col_customer(tab), 1)
        cards.addWidget(self._col_supplier(tab), 1)
        col.addLayout(cards, 1)

        col.addWidget(self._summary_strip(tab), 0)
        return page

    def _col_hauler(self, tab: _Tab) -> QFrame:
        frame, grid = self._card("الجرار", "يُختار أولًا", MAN)
        self._hidden(tab, "tractor_id")
        grid.addWidget(self._pick_row(tab, "tractor", "اختيار جرار", MAN[0], self.pick_tractor), 0, 0, 1, 2)
        grid.addWidget(self._labelled("سعر النقل للمتر", self._mk_num(tab, "price_man")), 1, 0, 1, 2)
        hint = QLabel("الأجرة تُحسب على تكعيب العميل")
        hint.setStyleSheet(
            "font-size:12px; font-weight:800; color:#475569; background:#F8FAFC; "
            "border:1px solid #E2E8F0; border-radius:7px; padding:7px 10px;"
        )
        hint.setMinimumHeight(38)
        grid.addWidget(self._labelled("محسوب على", hint), 2, 0, 1, 2)
        grid.addWidget(self._labelled("أجرة الجرار", self._calc_box(tab, "total_man", MAN)), 3, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(4, 1)
        return frame

    def _col_customer(self, tab: _Tab) -> QFrame:
        frame, grid = self._card("العميل", "يستلم ويُحاسَب", CUS)
        self._hidden(tab, "customer_id")
        grid.addWidget(self._pick_row(tab, "customer", "اختيار عميل", GREEN, self.pick_customer), 0, 0, 1, 2)
        grid.addWidget(self._labelled("التكعيب (م³)", self._mk_num(tab, "cus_volume")), 1, 0)
        grid.addWidget(self._labelled("سعر المتر", self._mk_num(tab, "price_cus")), 1, 1)
        grid.addWidget(self._labelled("نسبة الخصم %", self._mk_num(tab, "discount_percent")), 2, 0)
        grid.addWidget(self._labelled("قيمة الخصم", self._calc_box(tab, "amount_dis", CUS, big=False)), 2, 1)
        grid.addWidget(self._labelled("الصافي المستحق", self._calc_box(tab, "safi_cus", CUS)), 3, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(4, 1)
        return frame

    def _col_supplier(self, tab: _Tab) -> QFrame:
        frame, grid = self._card("الكسّارة", "تورّد المنتج", RES)
        self._hidden(tab, "supplier_id")
        grid.addWidget(self._pick_row(tab, "supplier", "اختيار كسّارة", RES[0], self.pick_supplier), 0, 0, 1, 2)
        grid.addWidget(self._labelled("التكعيب (م³)", self._mk_num(tab, "res_volume")), 1, 0)
        grid.addWidget(self._labelled("سعر المتر", self._mk_num(tab, "price_res")), 1, 1)
        grid.addWidget(self._labelled("إجمالي التوريد", self._calc_box(tab, "total_res", RES)), 2, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(3, 1)
        return frame

    def _summary_strip(self, tab: _Tab) -> QFrame:
        strip = QFrame()
        strip.setStyleSheet("QFrame { background:#0F172A; border-radius:11px; }")
        row = QHBoxLayout(strip)
        row.setContentsMargins(18, 12, 18, 12)
        row.setSpacing(24)

        def block(caption: str, key: str, colour: str, size: int) -> None:
            box = QWidget()
            c = QVBoxLayout(box)
            c.setContentsMargins(0, 0, 0, 0)
            c.setSpacing(2)
            cap = QLabel(caption)
            cap.setStyleSheet("font-size:11.5px; font-weight:700; color:#94A3B8; background:transparent;")
            val = QLabel("0.00")
            val.setStyleSheet(
                f"font-family:'Cairo'; font-size:{size}px; font-weight:900; color:{colour}; "
                "background:transparent;"
            )
            val.setLayoutDirection(Qt.LeftToRight)
            tab.calc[key] = val
            c.addWidget(cap)
            c.addWidget(val)
            row.addWidget(box, 0)

        block("هامش البون", "margin", "#4ADE80", 26)
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background:#1E293B;")
        row.addWidget(sep)
        block("مستحق من العميل", "safi_cus2", "#E2E8F0", 18)
        block("مستحق للكسّارة", "total_res2", "#E2E8F0", 18)
        block("مستحق للجرار", "total_man2", "#E2E8F0", 18)
        row.addStretch(1)
        return strip

    # -- tab 2: Access-style two panels ----------------------------------

    def _build_tab_split(self, tab: _Tab) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(14)
        outer.addWidget(self._split_right(tab), 1)
        outer.addWidget(self._split_left(tab), 1)
        return page

    def _panel(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background:#FFFFFF; border:1px solid #C7D5E5; border-radius:12px; }"
        )
        box = QVBoxLayout(frame)
        box.setContentsMargins(20, 16, 20, 18)
        box.setSpacing(9)
        head = QLabel(title)
        head.setAlignment(Qt.AlignCenter)
        head.setStyleSheet(
            "font-size:15px; font-weight:900; color:#B45309; background:transparent; border:none;"
        )
        box.addWidget(head)
        return frame, box

    def _arow(self, box: QVBoxLayout, caption: str, widget: QWidget, dark: bool = False) -> None:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(10)
        lab = QLabel(caption)
        lab.setFixedWidth(120)
        lab.setMinimumHeight(36)
        lab.setAlignment(Qt.AlignCenter)
        lab.setStyleSheet(
            f"background:{'#2C6B92' if dark else '#4A90C2'}; color:#FFFFFF; border-radius:5px; "
            "font-weight:700; font-size:12.5px;"
        )
        line.addWidget(lab, 0)
        line.addWidget(widget, 1)
        box.addWidget(row)

    def _divider(self, box: QVBoxLayout, text: str) -> None:
        lab = QLabel(text)
        lab.setStyleSheet(
            "font-size:12.5px; font-weight:700; color:#64748B; border-bottom:1px dashed #CBD5E1; "
            "padding-bottom:4px; margin-top:6px;"
        )
        box.addWidget(lab)

    def _split_right(self, tab: _Tab) -> QFrame:
        frame, box = self._panel("بيانات البون والأطراف")
        self._arow(box, "رقم البون", self._mk(tab, "ticket_no"))
        self._arow(box, "التاريخ", self._mk(tab, "ticket_date"))
        self._arow(box, "رقم الإيصال", self._mk(tab, "receipt_no"))
        self._arow(box, "نوع الصنف", self._family_box(tab))
        self._arow(box, "الصنف", self._build_item_combo(tab))

        self._divider(box, "الجرار — يُختار أولًا فيُصفّي العميل والكسّارة")
        self._hidden(tab, "tractor_id")
        self._arow(box, "اسم صاحب الجرار",
                   self._pick_row(tab, "tractor", "اختيار", MAN[0], self.pick_tractor), dark=True)

        self._divider(box, "العميل والكسّارة")
        self._hidden(tab, "customer_id")
        self._hidden(tab, "supplier_id")
        self._arow(box, "اسم العميل",
                   self._pick_row(tab, "customer", "اختيار", GREEN, self.pick_customer), dark=True)
        self._arow(box, "اسم الكسّارة",
                   self._pick_row(tab, "supplier", "اختيار", RES[0], self.pick_supplier), dark=True)
        box.addStretch(1)
        return frame

    def _split_left(self, tab: _Tab) -> QFrame:
        frame, box = self._panel("الحسابات والقيم")

        self._divider(box, "حساب العميل")
        self._arow(box, "التكعيب", self._mk_num(tab, "cus_volume"))
        self._arow(box, "سعر المتر", self._mk_num(tab, "price_cus"))
        self._arow(box, "نسبة الخصم %", self._mk_num(tab, "discount_percent"))
        self._arow(box, "قيمة الخصم", self._calc_box(tab, "amount_dis", CUS, big=False))
        self._arow(box, "الصافي", self._calc_box(tab, "safi_cus", CUS), dark=True)

        self._divider(box, "حساب الكسّارة (المورد)")
        self._arow(box, "تكعيب المورد", self._mk_num(tab, "res_volume"))
        self._arow(box, "سعر المورد", self._mk_num(tab, "price_res"))
        self._arow(box, "إجمالي المورد", self._calc_box(tab, "total_res", RES), dark=True)

        self._divider(box, "حساب الجرار (النقل)")
        self._arow(box, "سعر النقل", self._mk_num(tab, "price_man"))
        self._arow(box, "أجرة الجرار", self._calc_box(tab, "total_man", MAN), dark=True)
        box.addStretch(1)
        return frame

    # -- tab switching ---------------------------------------------------

    def _use_tab(self, index: int) -> None:
        tab = self._tabs[index]
        self.inputs = tab.inputs
        self._calc = tab.calc
        self._party_labels = tab.party_labels
        self._pick_buttons = tab.pick_buttons
        self._item_combo = tab.item_combo
        self._family_label = tab.family_label
        self._active = index

    def _on_tab_changed(self, index: int) -> None:
        if index == self._active:
            return
        src = self._tabs[self._active]
        dst = self._tabs[index]
        self._filling = True
        try:
            for name in _FIELDS:
                self._set_editor_value(dst.inputs.get(name), self._editor_value(src.inputs.get(name)))
            for party, label in dst.party_labels.items():
                label.setText(src.party_labels[party].text())
            if dst.family_label is not None and src.family_label is not None:
                dst.family_label.setText(src.family_label.text())
        finally:
            self._filling = False
        self._use_tab(index)
        # Re-apply the current mode's read-only state to the now-live editors.
        self.set_mode(self.mode)
        self._recompute()

    # -- item combo ------------------------------------------------------

    def _reload_items(self) -> None:
        for tab in self._tabs:
            combo = tab.item_combo
            if combo is None:
                continue
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("— اختر الصنف —", None)
            try:
                for item in self._backend().items():
                    combo.addItem(item.item_name, item.item_id)
            except Exception:  # noqa: BLE001
                pass
            combo.setCurrentIndex(0)
            combo.blockSignals(False)

    def _on_item_changed(self, tab: _Tab) -> None:
        combo = tab.item_combo
        item_id = combo.currentData() if combo else None
        item = self._backend().item(item_id) if item_id else None
        self._set_editor_value(tab.inputs.get("item_name"), item.item_name if item else "")
        self._set_editor_value(tab.inputs.get("item_family"), item.item_family if item else "")
        if tab.family_label is not None:
            tab.family_label.setText(item.item_family if item else "—")
        if not self._filling and tab is self._tabs[self._active]:
            self._autofill_prices()

    # -- pickers ---------------------------------------------------------

    def pick_tractor(self) -> None:
        """The جرار is chosen first; it filters the other two pickers."""
        try:
            rows = self._backend().tractor_picker_rows()
        except Exception as exc:
            self._show_error("تعذّر تحميل قائمة الجرارات", exc)
            return
        if not rows:
            QMessageBox.information(self, "لا توجد جرارات", "أضِف جرارًا من شاشة الجرارات أولًا.")
            return
        dialog = TawridTractorPickerDialog(rows, self)
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

    def pick_customer(self) -> None:
        try:
            rows = self._backend().customer_picker_rows()
        except Exception as exc:
            self._show_error("تعذّر تحميل قائمة العملاء", exc)
            return
        if not rows:
            QMessageBox.information(self, "لا يوجد عملاء", "أضِف عميلًا من شاشة العملاء أولًا.")
            return
        tractor_id = self._id("tractor_id")
        tractor_rows = None
        tractor_name = None
        if tractor_id is not None:
            try:
                tractor_rows = self._backend().customers_for_tractor(tractor_id)
            except Exception:
                tractor_rows = None
            tractor_name = self._party_labels["tractor"].text()
        dialog = TawridCustomerPickerDialog(
            rows, self, tractor_rows=tractor_rows, tractor_name=tractor_name
        )
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
        tractor_id = self._id("tractor_id")
        tractor_rows = None
        tractor_name = None
        if tractor_id is not None:
            try:
                tractor_rows = self._backend().crushers_for_tractor(tractor_id)
            except Exception:
                tractor_rows = None
            tractor_name = self._party_labels["tractor"].text()
        dialog = TawridSupplierPickerDialog(
            rows, self, tractor_rows=tractor_rows, tractor_name=tractor_name
        )
        if dialog.exec() != QDialog.Accepted or not dialog.selected:
            return
        chosen = dialog.selected
        self._set_editor_value(self.inputs.get("supplier_id"), chosen.get("supplier_id"))
        self._party_labels["supplier"].setText(str(chosen.get("supplier_name") or ""))
        self._autofill_prices()
        self._autofill_res_volume()

    # -- auto-fill (act on the active tab) -------------------------------

    def _autofill_prices(self) -> None:
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
        if _num(self._val("discount_percent")) == 0:
            self._set_editor_value(self.inputs.get("discount_percent"), _money(prices.discount_percent))
        self._recompute()

    def _autofill_volume(self) -> None:
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

    def _val(self, name: str) -> Any:
        editor = self.inputs.get(name)
        return self._editor_value(editor) if editor is not None else ""

    # -- live totals -----------------------------------------------------

    def _recompute(self) -> None:
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
        margin = safi_cus - total_res - total_man

        values = {
            "total_cus": total_cus,
            "amount_dis": amount_dis,
            "safi_cus": safi_cus,
            "safi_cus2": safi_cus,
            "total_res": total_res,
            "total_res2": total_res,
            "total_man": total_man,
            "total_man2": total_man,
            "margin": margin,
        }
        for key, value in values.items():
            label = self._calc.get(key)
            if label is not None:
                label.setText(_money(value))

    # -- navigation + search ---------------------------------------------

    def open_lookup(self) -> None:
        if self.mode in {"new", "edit"}:
            QMessageBox.information(self, "جاري التعديل", "احفظ البون أو ألغِه قبل فتح بون تاني.")
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
        for button in getattr(self, "_pick_buttons", {}).values():
            button.setEnabled(editing)
        self._update_nav_state()

    def refresh_table(self) -> None:
        super().refresh_table()
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
        """Populate the active tab from a stored ticket + its joined display record."""
        self._filling = True
        try:
            for name in _FIELDS:
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
            if self._family_label is not None:
                self._family_label.setText(str(display.get("item_family") or "—"))

            name = str(display.get("customer_name") or "").strip()
            no = record.get("ticket_no")
            self.summary_label.setText(f"البون رقم {no}" + (f" — {name}" if name else ""))
        finally:
            self._filling = False
        self._recompute()

    def _clear_form(self) -> None:
        self._filling = True
        try:
            for editor in self.inputs.values():
                self._set_editor_value(editor, None)
            if self._item_combo is not None:
                self._item_combo.setCurrentIndex(0)
            for label in self._party_labels.values():
                label.setText("— لم يُختَر —")
            if self._family_label is not None:
                self._family_label.setText("—")
        finally:
            self._filling = False
        self._recompute()

    def new_record(self) -> None:
        super().new_record()
        try:
            self._set_editor_value(self.inputs.get("ticket_no"), self._backend().next_ticket_no())
        except Exception:
            pass
        self._set_editor_value(
            self.inputs.get("ticket_date"), datetime.date.today().strftime("%Y-%m-%d")
        )
        self.summary_label.setText("بون جديد")

    def save_record(self) -> None:
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
                QMessageBox.warning(self, "رقم مكرر", f"رقم البون {ticket_no} مستخدم في بون تاني.")
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
        super().delete_record()
