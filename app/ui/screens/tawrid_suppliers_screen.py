"""شاشة الكسّارات — قسم التوريدات (Tawrid module, phase 3).

المورد = الكسّارة: one entity under two names, as in Access. It replaces the
screen ``Fproduct`` over the table ``pruduct`` (23 rows), and is independent of
the older ``suppliers`` table and its screen.

Layout is "Model 2-ب" from the mockup set the user picked: the account summary
strip above the shared CRUD form, the ten item prices in a panel beside the
form, and **no list panel** — the record list moved into a search dialog behind
a button. The price panel is the wide half: بيانات المورد is seven short boxes,
while the prices are ten money fields that have to show their digits.

What is deliberately different from Access, and why. Each is tied to something
measured in ``sisko.Accdb``, not to taste:

* **The مسلسل comes from this table's own maximum.** ``Fproduct.t1`` defaulted
  to ``DMax("[number1]","fanii")+1`` — it counted the *customers* table. The
  measured result: 3 duplicate codes inside ``pruduct`` (26, 31, 46) and 5 codes
  shared with a customer. ``supplier_code`` is UNIQUE here, so the defect cannot
  recur.
* **ملاحظات and تاريخ الرصيد are on the form.** Both columns exist in
  ``pruduct`` and neither had a control on ``Fproduct``, which is why the notes
  are empty in 23 rows out of 23 and no opening balance carries its date.
* **Everything locks together.** On ``Fproduct`` three boxes — سن + , سن مدرج
  and رصيد أول المدة — were left ``Locked = False`` while every other control
  was locked, so they could be typed into without pressing «تعديل». Here the
  base class drives all of them from one mode.
* **A crusher with movement cannot be deleted,** only stopped (موقوف). Crusher
  id 22 was deleted outright while 4 tickets still reference it — and unlike the
  tractors, ``TBBOOn`` records no crusher name, only ``res-id``, so that name is
  gone for good.
* **The search dialog shows الحالة and الرصيد.** The Access combo listed every
  card, active or dead, in creation order with nothing to tell them apart; 7 of
  the 23 have no movement at all.

Everything below is presentation. The CRUD path is the shared one
(``ReviewDataService`` + ``TABLE_SPECS['tawrid_suppliers']``); the balance
figures and the picker rows come from :class:`TawridSupplierService`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.review_data_service import ReviewDataService, TABLE_SPECS
from app.services.tawrid_supplier_service import (
    SupplierBalance,
    TawridSupplierService,
)
from app.ui.common.theme import GREEN, TEXT, _button_style
from app.ui.dialogs.tawrid_supplier_picker import TawridSupplierPickerDialog
from app.ui.screens.base_crud_screen import BaseCrudScreen

# Shown wherever a movement figure would go while the البون and سندات الصرف
# tables have not been built yet (later phases).
_PENDING = "—"

# The ten item-price fields, in the order Fproduct laid them out. They are
# ``hidden_on_form`` in the TableSpec so the base form panel skips them; this
# screen builds them itself in the «أسعار الأصناف» panel.
PRICE_FIELDS = (
    "price_sen1",
    "price_sen2",
    "price_sen_ataqa",
    "price_sen6_safi",
    "price_sen6_bodra",
    "price_sen_adsa",
    "price_bodra",
    "price_raml",
    "price_sen_plus",
    "price_sen_modarag",
)

# Money boxes that are NOT NULL DEFAULT 0, so a blank one means zero.
_ZERO_IF_BLANK = ("opening_balance", *PRICE_FIELDS)


def _money(value: Decimal | float | int | None) -> str:
    """Thousands-separated, two decimals. Negative shown as ``1,234.00-``.

    Trailing sign: the figure sits in an RTL layout, where a leading minus
    renders on the wrong end of the number.
    """
    amount = Decimal(str(value or 0))
    text = f"{abs(amount):,.2f}"
    return f"{text}-" if amount < 0 else text


class TawridSuppliersScreen(BaseCrudScreen):
    SPEC_KEY = "tawrid_suppliers"
    SEARCH_PLACEHOLDER = "ابحث باسم المورد أو المسلسل أو الموبايل"

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        # Populated before super().__init__ because the base constructor builds
        # the UI, which calls back into the widgets built here.
        self._backend_service: TawridSupplierService | None = None
        self._stat_values: dict[str, QLabel] = {}
        self._ledger_values: dict[str, QLabel] = {}
        self._price_heading: QLabel | None = None
        super().__init__(service, TABLE_SPECS[self.SPEC_KEY], parent)
        self._show_balance(SupplierBalance())
        self._update_price_heading()

    # -- display ---------------------------------------------------------

    def _display_value(self, field_name: str, value: Any) -> Any:
        """Render the stored boolean as the Arabic label the combo offers."""
        if field_name == "is_active":
            if value is None:
                return "نشط"
            return "نشط" if bool(value) else "موقوف"
        return value

    def _make_editor(self, field: Any):
        """Drop the blank option from الحالة so it can never be saved empty.

        ``is_active`` is NOT NULL, so an empty selection would surface as a raw
        NotNullViolation. The field is also not marked ``required`` — that check
        rejects any falsey value, which would wrongly reject "موقوف" (False).
        """
        editor = super()._make_editor(field)
        if field.name == "is_active":
            blank = editor.findText("")
            if blank >= 0:
                editor.removeItem(blank)
            editor.setCurrentIndex(max(0, editor.findText("نشط")))
        return editor

    # -- toolbar -----------------------------------------------------------

    def _install_extra_toolbar_buttons(self, layout: QHBoxLayout) -> None:
        """The search button and the record navigation that replaced the list.

        ``الاول / السابق / التالي / الاخير`` are not an invention: they are on
        ``Fproduct`` already. They were redundant on the customers screen, whose
        list sits beside the form — here, with the list behind a dialog, they are
        the only way to walk the cards without reopening it each time.
        """
        self.find_button = QPushButton("بحث عن كسّارة")
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
            button.clicked.connect(lambda _checked=False, k=key: self._navigate(k))
            self.nav_buttons[key] = button
            layout.addWidget(button)

    # -- layout ----------------------------------------------------------

    def _build_content(self):
        """Summary strip on top; form beside the item prices. No list panel.

        The list panel is still **built** and then hidden. The base class drives
        selection, navigation and the record count through ``self.table`` and
        ``self.search_text``; keeping the widgets alive and merely invisible
        means none of that has to be reimplemented, and a hidden widget takes no
        space in a layout.
        """
        content = QVBoxLayout()
        content.setSpacing(10)
        content.addWidget(self._build_summary_panel(), 0)

        row = QHBoxLayout()
        row.setSpacing(12)
        # The prices are the wide half, not the form. بيانات المورد is seven
        # short boxes — a مسلسل, a name, a phone, a status, a balance, a date
        # and a note — and giving them the stretch left them swimming in empty
        # space while the ten money boxes were squeezed until their digits were
        # cut off. So the form is capped and the price panel takes the rest.
        row.addWidget(self._build_form_panel(), 0)
        row.addWidget(self._build_prices_panel(), 1)
        content.addLayout(row, 1)

        self.list_panel = self._build_list_panel()
        self.list_panel.hide()
        content.addWidget(self.list_panel, 0)
        return content

    def _build_form_panel(self):
        """The shared form panel with its title and «السجل الحالي» line removed.

        The green header bar already names the screen, and the crusher's name and
        مسلسل are the first two boxes on the form — so those two lines repeat
        what is on screen anyway while costing the vertical space that pushes the
        seven fields into a scrollbar. Hidden rather than deleted:
        ``summary_label`` stays a live widget because the base class writes to it
        on every load, and a QVBoxLayout skips a hidden widget entirely.
        """
        scroll = super()._build_form_panel()
        container = scroll.widget()
        layout = container.layout()
        for index in range(min(2, layout.count())):
            widget = layout.itemAt(index).widget()
            if widget is not None:
                widget.hide()
        scroll.setMinimumHeight(max(container.sizeHint().height(), 240))
        # Pinned to a narrow band: wide enough that two fields per row never
        # clip (a QScrollArea given only a maximum shrinks to its size hint and
        # grows a horizontal scrollbar instead), and capped so the seven boxes
        # stop stealing the width the ten price boxes need.
        scroll.setMinimumWidth(570)
        scroll.setMaximumWidth(620)
        return scroll

    def _build_summary_panel(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet(
            "QFrame { background:#FFFFFF; border:1px solid #E5EAF0; border-radius:7px; }"
        )
        outer = QHBoxLayout(panel)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(12)

        for key, caption in (
            ("opening", "رصيد أول المدة"),
            ("tickets", "عدد البونات"),
            # The customer owes us; the crusher is owed by us. Same arithmetic,
            # opposite direction, so the caption has to say which.
            ("balance", "المستحق له"),
        ):
            outer.addWidget(self._build_stat_tile(key, caption), 1)

        outer.addWidget(self._vertical_rule())
        outer.addWidget(self._build_ledger_block(), 0)
        return panel

    def _build_stat_tile(self, key: str, caption: str) -> QWidget:
        tile = QFrame()
        tile.setStyleSheet(
            "QFrame { background:#F8FAFC; border:1px solid #E2E8F0; border-radius:7px; }"
        )
        box = QVBoxLayout(tile)
        box.setContentsMargins(12, 8, 12, 8)
        box.setSpacing(0)

        value = QLabel(_PENDING)
        value.setStyleSheet(
            f"font-size:22px; font-weight:900; color:{GREEN}; background:transparent; border:none;"
        )
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value.setLayoutDirection(Qt.LeftToRight)

        label = QLabel(caption)
        label.setStyleSheet(
            "font-size:12px; font-weight:700; color:#64748B; background:transparent; border:none;"
        )
        box.addWidget(value)
        box.addWidget(label)
        self._stat_values[key] = value
        return tile

    def _vertical_rule(self) -> QFrame:
        rule = QFrame()
        rule.setFrameShape(QFrame.VLine)
        rule.setStyleSheet("color:#E2E8F0;")
        return rule

    def _build_ledger_block(self) -> QWidget:
        block = QWidget()
        grid = QGridLayout(block)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(2)

        title = QLabel("الحساب")
        title.setStyleSheet(f"font-size:12px; font-weight:900; color:{GREEN};")
        grid.addWidget(title, 0, 0, 1, 2)

        rows = (
            ("opening", "أول المدة"),
            ("purchased", "قيمة البونات"),
            ("paid", "المدفوع"),
            ("net", "الرصيد"),
        )
        for index, (key, caption) in enumerate(rows, start=1):
            name = QLabel(caption)
            emphasis = "900" if key == "net" else "700"
            colour = GREEN if key == "net" else "#64748B"
            name.setStyleSheet(f"font-size:12px; font-weight:{emphasis}; color:{colour};")

            value = QLabel(_PENDING)
            value.setStyleSheet(
                f"font-size:12px; font-weight:900; color:{TEXT if key != 'net' else GREEN};"
            )
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value.setLayoutDirection(Qt.LeftToRight)
            value.setMinimumWidth(96)

            grid.addWidget(name, index, 0)
            grid.addWidget(value, index, 1)
            self._ledger_values[key] = value
        return block

    # -- the item prices panel ---------------------------------------------

    def _build_prices_panel(self) -> QWidget:
        """The ten fixed item-price columns, beside the form.

        ``_build_field_group`` registers each editor in ``self.inputs``, so these
        save, clear and mode-switch on exactly the same path as the form fields
        even though the base form panel skipped them.
        """
        by_name = {field.name: field for field in self.spec.fields}
        fields = [by_name[name] for name in PRICE_FIELDS if name in by_name]

        panel = QFrame()
        # Minimum, not fixed. A fixed 340px was narrower than the ten label +
        # money-box pairs actually need, so the boxes were clipped and «180.00»
        # read as «.00» — the panel now grows with the window instead.
        panel.setMinimumWidth(560)
        panel.setStyleSheet(
            "QFrame { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:7px; }"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        heading = QLabel("أسعار الأصناف")
        heading.setStyleSheet(
            f"font-size:13px; font-weight:900; color:{GREEN}; background:transparent; border:none;"
        )
        layout.addWidget(heading)
        self._price_heading = heading

        # Three columns, the same as the customers screen uses for these ten
        # fields: two would leave five tall rows of very wide boxes, and one
        # would force the scrollbar the Access screen also had
        # (``Fproduct.ScrollBars = 3``).
        columns, self.FORM_COLUMNS = self.FORM_COLUMNS, 3
        try:
            group = self._build_field_group("", fields)
        finally:
            self.FORM_COLUMNS = columns
        # The frame around it is already the card; without this the group box
        # draws a second border inside the first.
        group.setStyleSheet(
            "QGroupBox { background:transparent; border:none; margin-top:0; }"
        )
        layout.addWidget(group)

        hint = QLabel(
            "سعر شراء المتر المكعب من الكسّارة. الخانة الفاضية أو الصفر معناها "
            "إن الصنف ده مش مسعّر عندها."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "font-size:11px; color:#94A3B8; background:transparent; border:none;"
        )
        layout.addWidget(hint)
        layout.addStretch(1)
        return panel

    def _update_price_heading(self) -> None:
        """Name how many of the ten items this crusher is actually priced for.

        Worth stating because the legacy grid is 76% empty — 56 of 230 cells.
        Most crushers sell one or two items, so «1 من 10» is the normal case and
        «9 من 10» (الهدي) is the exception.
        """
        if self._price_heading is None:
            return
        priced = 0
        for name in PRICE_FIELDS:
            editor = self.inputs.get(name)
            if editor is None:
                continue
            text = str(self._editor_value(editor) or "").replace(",", "").strip()
            try:
                if text and Decimal(text) != 0:
                    priced += 1
            except Exception:  # noqa: BLE001 - a half-typed number is not a count
                continue
        self._price_heading.setText(f"أسعار الأصناف — {priced} من {len(PRICE_FIELDS)}")

    # -- data ------------------------------------------------------------

    def _backend(self) -> TawridSupplierService:
        if self._backend_service is None:
            self._backend_service = TawridSupplierService()
        return self._backend_service

    def _refresh_balance(self, supplier_id: Any) -> None:
        """Recompute the summary. A failure here must never block the form."""
        try:
            balance = self._backend().for_supplier(supplier_id)
        except Exception:
            balance = SupplierBalance()
        self._show_balance(balance)

    def _show_balance(self, balance: SupplierBalance) -> None:
        pending = not balance.movements_available
        self._stat_values["opening"].setText(_money(balance.opening_balance))
        self._stat_values["tickets"].setText(
            _PENDING if pending else f"{balance.tickets_count:,}"
        )
        self._stat_values["balance"].setText(_money(balance.balance))

        self._ledger_values["opening"].setText(_money(balance.opening_balance))
        self._ledger_values["purchased"].setText(
            _PENDING if pending else f"+ {_money(balance.purchased)}"
        )
        self._ledger_values["paid"].setText(
            _PENDING if pending else f"- {_money(balance.paid)}"
        )
        self._ledger_values["net"].setText(_money(balance.balance))

    # -- the search dialog and record navigation ---------------------------

    def open_lookup(self) -> None:
        """Open the crusher picker and load whatever it returns.

        This overrides the base class's generic ``RecordLookupDialog`` so the F1
        shortcut and the «بحث عن كسّارة» button lead to the same place — the
        dialog that also shows الحالة and الرصيد.
        """
        if self.mode in {"new", "edit"}:
            QMessageBox.information(
                self,
                "جاري التعديل",
                "احفظ التعديلات أو ألغِها قبل الانتقال إلى كسّارة تانية.",
            )
            return
        try:
            rows = self._backend().picker_rows()
        except Exception as exc:
            self._show_error("تعذّر تحميل قائمة الكسّارات", exc)
            return
        if not rows:
            QMessageBox.information(
                self, "لا توجد كسّارات", "مفيش كسّارات مسجّلة. اضغط «جديد» لإضافة واحدة."
            )
            return

        dialog = TawridSupplierPickerDialog(rows, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected:
            return
        self._load_supplier(dialog.selected.get("supplier_id"))

    def _load_supplier(self, supplier_id: Any) -> None:
        """Show one crusher's card, keeping the hidden list row in step.

        Selecting the row rather than only filling the form is what makes the
        الاول/السابق/التالي/الاخير buttons continue from where the search left
        off: they walk the same hidden table.
        """
        if supplier_id is None:
            return
        try:
            record = self.service.get_record(self.spec, supplier_id)
        except Exception as exc:
            self._show_error("فشل تحميل السجل", exc)
            return
        if not record:
            return
        self.current_id = supplier_id
        self._fill_form(record)
        self.set_mode("view")
        self._select_row_by_id(supplier_id)

    def _navigate(self, where: str) -> None:
        """Move to the first/previous/next/last card in the hidden list."""
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
            # whose parent is hidden, and this list is hidden by design. It fires
            # itemSelectionChanged either way, which the base class has wired to
            # load_selected — so the form follows on its own.
            self.table.setCurrentCell(target, 0)
        self._update_nav_state()

    def _update_nav_state(self) -> None:
        """Grey the navigation while editing or at the ends of the list."""
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

    # -- hooks fired by BaseCrudScreen ------------------------------------

    def set_mode(self, mode: str) -> None:
        super().set_mode(mode)
        # Built by _build_content, which the base constructor calls after
        # set_mode is first reachable — guard so early calls are harmless.
        self._update_nav_state()

    def refresh_table(self) -> None:
        super().refresh_table()
        # The base class opens on the first record with ``selectRow(0)``, which
        # Qt silently ignores for a view inside a hidden parent — and this list
        # is hidden by design. Without this the screen would open on a blank
        # form with no way to tell why.
        if self.current_id is None and self.table.rowCount():
            self.table.setCurrentCell(0, 0)
        self._update_nav_state()

    def _select_row_by_id(self, record_id: Any) -> None:
        """Same as the base version, but with a selection call that works here.

        See :meth:`refresh_table` — ``selectRow`` does nothing on a hidden view.
        """
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and str(item.data(Qt.UserRole)) == str(record_id):
                self.table.setCurrentCell(row, 0)
                return

    def _fill_form(self, record: dict[str, Any]) -> None:
        super()._fill_form(record)
        # ``_fill_form`` in the base class skips hidden_on_form fields, and the
        # ten item prices are hidden so the base form panel would not render
        # them — fill them here instead.
        for name in PRICE_FIELDS:
            self._set_editor_value(self.inputs.get(name), record.get(name))

        # ``get_record`` returns only the columns the spec declares, and
        # ``supplier_id`` is a surrogate key that is not one of them — so read
        # the id from ``current_id``, which load_selected() sets before this.
        supplier_id = record.get(self.spec.primary_key) or self.current_id
        self._refresh_balance(supplier_id)
        self._update_price_heading()

        # For the same reason the base class's "السجل الحالي" label comes out
        # blank; name the crusher instead, which is what identifies it here.
        name = str(record.get("supplier_name") or "").strip()
        code = record.get("supplier_code")
        if name:
            self.summary_label.setText(
                f"السجل الحالي: {name}" + (f" — مسلسل {code}" if code else "")
            )

    def _clear_form(self) -> None:
        super()._clear_form()
        # A cleared choices-combo lands on index 0; keep الحالة meaningful.
        self._set_editor_value(self.inputs.get("is_active"), "نشط")
        self._show_balance(SupplierBalance())
        self._update_price_heading()

    def new_record(self) -> None:
        """Start a new crusher with the next مسلسل already filled in."""
        super().new_record()
        try:
            self._set_editor_value(
                self.inputs["supplier_code"], self._backend().next_code()
            )
        except Exception:
            # A suggestion only — never block creating a record over it.
            pass

    def save_record(self) -> None:
        """Treat a blank money box as zero before handing over to the base save.

        Every price column plus ``opening_balance`` is NOT NULL DEFAULT 0. A
        blank field otherwise reaches the database as NULL and surfaces as a raw
        NotNullViolation — but for a money box on this form, blank plainly means
        "nothing", not "unknown".
        """
        for name in _ZERO_IF_BLANK:
            editor = self.inputs.get(name)
            if editor is not None and not str(self._editor_value(editor) or "").strip():
                self._set_editor_value(editor, 0)
        super().save_record()
        self._update_price_heading()

    def delete_record(self) -> None:
        """Refuse to delete a crusher that has movement; offer stopping instead.

        This is the defect that orphaned 4 tickets against crusher id 22 — and
        those are worse than the customer case, because ``TBBOOn`` stores no
        crusher name at all, only ``res-id``, so nothing survives to say which
        crusher supplied them.
        """
        if self.current_id is not None:
            try:
                movement = self._backend().has_movement(self.current_id)
            except Exception:
                movement = 0
            if movement:
                QMessageBox.warning(
                    self,
                    "لا يمكن الحذف",
                    f"الكسّارة دي عليها {movement} حركة مسجّلة (بونات/سندات صرف)، "
                    "وحذفها هيخلي حركتها من غير صاحب.\n"
                    "غيّر «الحالة» إلى «موقوف» بدل الحذف.",
                )
                return
        super().delete_record()
