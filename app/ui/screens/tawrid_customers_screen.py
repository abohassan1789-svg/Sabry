"""شاشة العملاء — قسم التوريدات (Tawrid module, phase 2).

Layout is "Model 2" from the mockup set the user picked: the same shape as
شاشة الجرارات (an account summary strip above the shared CRUD form + search
list), with the two price sets folded into a tab strip under the form —
«أسعار الأصناف» and «أسعار الجرارات».

It replaces the Access screen ``FEMP`` and its subform ``InvoiceCARCUS``.
What is deliberately different, and why:

* **The load/price grid rejects nothing.** Access offered every tractor in the
  combo, let you pick one already in the grid, then trapped error 3022 and
  asked you to try again. Here the picker only lists tractors not yet priced
  for this customer, so the unique (customer, tractor) rule cannot be hit.
* **A new grid row starts at the tractor's own rate** instead of blank. The
  tractor's default is also shown beside the customer's rate, because that
  comparison is the whole point of the grid: 208 of the 221 resolvable legacy
  rows differ from the default.
* **رقم المقطورة / رقم الوش are read-only,** read live from the tractor card.
  ``CarCus`` stored its own copy of the head number and three rows had already
  gone stale against the tractor.
* **A customer with movement cannot be deleted,** only stopped (موقوف). 911
  legacy tickets point at customers that were deleted outright.

Everything below is presentation and child-table wiring. The CRUD path for the
customer row itself is the shared one (``ReviewDataService`` +
``TABLE_SPECS['tawrid_customers']``); the balance figures and the grid come
from :class:`TawridCustomerService`.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.review_data_service import ReviewDataService, TABLE_SPECS
from app.services.tawrid_customer_service import (
    CustomerBalance,
    TawridCustomerService,
    TractorPrice,
)
from app.ui.common.theme import GREEN, TEXT
from app.ui.dialogs.tawrid_tractor_picker import TawridTractorPickerDialog
from app.ui.screens.base_crud_screen import BaseCrudScreen

# Shown wherever a movement figure would go while the البون and سندات القبض
# tables have not been built yet (later phases).
_PENDING = "—"

# The ten item-price fields, in the order FEMP laid them out. They are
# ``hidden_on_form`` in the TableSpec so the base form panel skips them; this
# screen builds them itself in the «أسعار الأصناف» tab.
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

# Grid columns. The editable ones are the three the user actually sets; the
# rest are read from the tractor card and must never be typed here.
GRID_COLUMNS = (
    ("driver_name", "اسم صاحب الجرار", False),
    ("trailer_no", "رقم المقطورة", False),
    ("head_no", "رقم الوش", False),
    ("load_volume", "التكعيب", True),
    ("price_sen", "سعر النقل - سن", True),
    ("price_raml", "سعر النقل - رمل", True),
    ("defaults", "الافتراضي للجرار", False),
)
EDITABLE_GRID_COLUMNS = {"load_volume", "price_sen", "price_raml"}


def _money(value: Decimal | float | int | None) -> str:
    """Thousands-separated, two decimals. Negative shown as ``1,234.00-``."""
    amount = Decimal(str(value or 0))
    text = f"{abs(amount):,.2f}"
    return f"{text}-" if amount < 0 else text


def _parse_money(text: str) -> Decimal | None:
    """Read a grid cell back. Blank means zero; anything unparseable is None."""
    cleaned = str(text or "").replace(",", "").strip()
    if cleaned == "":
        return Decimal("0")
    if cleaned.endswith("-"):
        cleaned = "-" + cleaned[:-1]
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


class TawridCustomersScreen(BaseCrudScreen):
    SPEC_KEY = "tawrid_customers"
    SEARCH_PLACEHOLDER = "ابحث باسم العميل أو المسلسل أو الموبايل"

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        # Populated before super().__init__ because the base constructor builds
        # the UI, which calls back into the widgets built here.
        self._backend_service: TawridCustomerService | None = None
        self._stat_values: dict[str, QLabel] = {}
        self._ledger_values: dict[str, QLabel] = {}
        self._grid_rows: list[TractorPrice] = []
        self._filling_grid = False
        super().__init__(service, TABLE_SPECS[self.SPEC_KEY], parent)
        self._show_balance(CustomerBalance())
        self._refresh_grid()

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

    # -- layout ----------------------------------------------------------

    def _build_content(self):
        """Summary strip on top; form + price tabs beside the search list."""
        content = QVBoxLayout()
        content.setSpacing(10)
        content.addWidget(self._build_summary_panel(), 0)

        row = QHBoxLayout()
        row.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(10)
        # The form takes exactly the height its fields need and the tabs absorb
        # the rest. Sharing the column equally instead crushed the form into a
        # scroll area three rows tall.
        left.addWidget(self._build_form_panel(), 0)
        left.addWidget(self._build_price_tabs(), 1)
        row.addLayout(left, 1)

        row.addWidget(self._build_list_panel(), 0)
        content.addLayout(row, 1)
        return content

    def _build_form_panel(self):
        """The shared form panel with its title and «السجل الحالي» line removed.

        The green header bar already names the screen, and the customer's name
        and مسلسل are the first two boxes on the form — so those two lines were
        repeating what is on screen anyway while costing the vertical space that
        pushed the eight fields into a scrollbar. Hidden rather than deleted:
        ``summary_label`` stays a live widget because the base class writes to
        it on every load, and a QVBoxLayout skips a hidden widget entirely.
        """
        scroll = super()._build_form_panel()
        container = scroll.widget()
        layout = container.layout()
        for index in range(min(2, layout.count())):
            widget = layout.itemAt(index).widget()
            if widget is not None:
                widget.hide()
        # Now that those two rows are gone the fields fit without scrolling;
        # the minimum keeps them fitting when the window is short.
        scroll.setMinimumHeight(max(container.sizeHint().height(), 240))
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
            ("balance", "المستحق عليه"),
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
            ("invoiced", "قيمة البونات"),
            ("collected", "المحصّل"),
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

    # -- the two price tabs ------------------------------------------------

    def _build_price_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setStyleSheet(
            "QTabWidget::pane { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:7px; }"
            "QTabBar::tab { background:#F1F5F9; color:#475569; border:1px solid #E2E8F0; "
            "border-bottom:none; border-top-left-radius:6px; border-top-right-radius:6px; "
            "padding:7px 16px; font-weight:800; }"
            f"QTabBar::tab:selected {{ background:#FFFFFF; color:{GREEN}; }}"
        )
        tabs.addTab(self._build_item_prices_tab(), "أسعار الأصناف")
        tabs.addTab(self._build_tractor_prices_tab(), "أسعار الجرارات")
        self._tabs = tabs
        return tabs

    def _build_item_prices_tab(self) -> QWidget:
        """The ten fixed item-price columns, laid out as FEMP had them.

        ``_build_field_group`` registers each editor in ``self.inputs``, so these
        save, clear and mode-switch on exactly the same path as the form fields
        even though the base form panel skipped them.
        """
        by_name = {field.name: field for field in self.spec.fields}
        fields = [by_name[name] for name in PRICE_FIELDS if name in by_name]

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 4, 10, 10)
        layout.setSpacing(6)
        # Three columns rather than the form's two: ten short money boxes in two
        # columns is five rows, which does not fit the tab beside a usable grid.
        columns, self.FORM_COLUMNS = self.FORM_COLUMNS, 3
        try:
            layout.addWidget(self._build_field_group("", fields))
        finally:
            self.FORM_COLUMNS = columns

        hint = QLabel(
            "سعر المتر المكعب للعميل لكل صنف. الحقل الفاضي معناه إن الصنف ده مش مسعّر له."
        )
        hint.setStyleSheet("font-size:11px; color:#94A3B8;")
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_tractor_prices_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.grid_add_button = QPushButton("إضافة جرار")
        self.grid_delete_button = QPushButton("حذف الصف")
        for button, primary in ((self.grid_add_button, True), (self.grid_delete_button, False)):
            button.setFixedHeight(32)
            if primary:
                button.setStyleSheet(
                    f"QPushButton {{ background:{GREEN}; color:#FFFFFF; border:none; "
                    "border-radius:6px; font-weight:800; padding:6px 14px; }"
                    "QPushButton:disabled { background:#CBD5E1; }"
                )
            else:
                button.setStyleSheet(
                    "QPushButton { background:#FFFFFF; color:#374151; border:1px solid #D1D5DB; "
                    "border-radius:6px; font-weight:800; padding:6px 14px; }"
                    "QPushButton:hover { background:#F3F4F6; }"
                    "QPushButton:disabled { color:#9CA3AF; }"
                )
        self.grid_add_button.clicked.connect(self.add_tractor_price)
        self.grid_delete_button.clicked.connect(self.delete_tractor_price)
        bar.addWidget(self.grid_add_button)
        bar.addWidget(self.grid_delete_button)
        bar.addStretch(1)

        self.grid_hint = QLabel("")
        self.grid_hint.setStyleSheet("font-size:11px; font-weight:700; color:#94A3B8;")
        bar.addWidget(self.grid_hint)
        layout.addLayout(bar)

        self.grid = QTableWidget()
        self.grid.setColumnCount(len(GRID_COLUMNS))
        self.grid.setHorizontalHeaderLabels([label for _name, label, _edit in GRID_COLUMNS])
        self.grid.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.grid.setSelectionMode(QAbstractItemView.SingleSelection)
        self.grid.setAlternatingRowColors(True)
        self.grid.verticalHeader().setVisible(False)
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.grid.setStyleSheet(
            "QTableWidget { background:#FFFFFF; alternate-background-color:#F8FAFC; "
            "border:1px solid #E2E8F0; gridline-color:#E5E7EB; font-size:13px; }"
            f"QHeaderView::section {{ background:{GREEN}; color:#FFFFFF; font-weight:900; "
            "border:none; padding:8px 6px; }"
            "QTableWidget::item:selected { background:#DDF3E6; color:#111827; }"
        )
        self.grid.itemChanged.connect(self._on_grid_item_changed)
        self.grid.setMinimumHeight(150)
        layout.addWidget(self.grid, 1)
        return page

    # -- data ------------------------------------------------------------

    def _backend(self) -> TawridCustomerService:
        if self._backend_service is None:
            self._backend_service = TawridCustomerService()
        return self._backend_service

    def _refresh_balance(self, customer_id: Any) -> None:
        """Recompute the summary. A failure here must never block the form."""
        try:
            balance = self._backend().for_customer(customer_id)
        except Exception:
            balance = CustomerBalance()
        self._show_balance(balance)

    def _show_balance(self, balance: CustomerBalance) -> None:
        pending = not balance.movements_available
        self._stat_values["opening"].setText(_money(balance.opening_balance))
        self._stat_values["tickets"].setText(
            _PENDING if pending else f"{balance.tickets_count:,}"
        )
        self._stat_values["balance"].setText(_money(balance.balance))

        self._ledger_values["opening"].setText(_money(balance.opening_balance))
        self._ledger_values["invoiced"].setText(
            _PENDING if pending else f"+ {_money(balance.invoiced)}"
        )
        self._ledger_values["collected"].setText(
            _PENDING if pending else f"- {_money(balance.collected)}"
        )
        self._ledger_values["net"].setText(_money(balance.balance))

    # -- the price grid ----------------------------------------------------

    def _refresh_grid(self) -> None:
        """Reload the customer × tractor rows and repaint the table."""
        rows: list[TractorPrice] = []
        if self.current_id is not None:
            try:
                rows = self._backend().tractor_prices(self.current_id)
            except Exception:
                rows = []
        self._grid_rows = rows

        # Signals are blocked while filling: every setItem would otherwise fire
        # itemChanged and be mistaken for a user edit, writing values back to
        # the database on every refresh.
        self._filling_grid = True
        self.grid.blockSignals(True)
        try:
            self.grid.clearContents()
            self.grid.setRowCount(len(rows))
            for row_index, price in enumerate(rows):
                for col_index, (name, _label, editable) in enumerate(GRID_COLUMNS):
                    item = QTableWidgetItem(self._grid_text(price, name))
                    item.setTextAlignment(Qt.AlignCenter)
                    if editable:
                        item.setFlags(item.flags() | Qt.ItemIsEditable)
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        item.setForeground(Qt.darkGray)
                    if col_index == 0:
                        item.setData(Qt.UserRole, price.price_id)
                    self.grid.setItem(row_index, col_index, item)
        finally:
            self.grid.blockSignals(False)
            self._filling_grid = False
        self._update_grid_state()

    def _grid_text(self, price: TractorPrice, column: str) -> str:
        if column == "driver_name":
            return price.driver_name
        if column == "trailer_no":
            return price.trailer_no
        if column == "head_no":
            return price.head_no
        if column == "load_volume":
            return _money(price.load_volume)
        if column == "price_sen":
            return _money(price.price_sen)
        if column == "price_raml":
            return _money(price.price_raml)
        if column == "defaults":
            # Both of the tractor's own rates, so the reason this row exists —
            # a rate that differs from the tractor's default — is visible.
            return f"سن {_money(price.default_sen)} / رمل {_money(price.default_raml)}"
        return ""

    def _update_grid_state(self) -> None:
        """Enable the grid only when there is a saved customer to attach to."""
        editing = self.mode in {"new", "edit"}
        has_customer = self.current_id is not None
        usable = editing and has_customer
        self.grid.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
            if usable
            else QAbstractItemView.NoEditTriggers
        )
        self.grid_add_button.setEnabled(usable and self._perm_save)
        self.grid_delete_button.setEnabled(usable and self._perm_delete)

        count = len(self._grid_rows)
        if not has_customer:
            self.grid_hint.setText("احفظ بيانات العميل أولاً، بعدها تقدر تضيف جرارات.")
        elif not editing:
            self.grid_hint.setText(f"{count} جرار — اضغط «تعديل» للتغيير")
        else:
            self.grid_hint.setText(f"{count} جرار")

        if hasattr(self, "_tabs"):
            self._tabs.setTabText(1, f"أسعار الجرارات ({count})")

    def _on_grid_item_changed(self, item: QTableWidgetItem) -> None:
        """Commit one edited cell. Anything unparseable is put back, not saved."""
        if self._filling_grid or item is None:
            return
        row = item.row()
        if row < 0 or row >= len(self._grid_rows):
            return
        name, label, editable = GRID_COLUMNS[item.column()]
        if not editable or name not in EDITABLE_GRID_COLUMNS:
            return
        price = self._grid_rows[row]
        value = _parse_money(item.text())
        if value is None or value < 0:
            QMessageBox.warning(
                self,
                "قيمة غير صحيحة",
                f"«{label}» لازم يكون رقم موجب أو صفر.",
            )
            self._refresh_grid()
            return

        values = {
            "load_volume": price.load_volume,
            "price_sen": price.price_sen,
            "price_raml": price.price_raml,
        }
        values[name] = value
        try:
            self._backend().update_tractor_price(
                price.price_id,
                values["load_volume"],
                values["price_sen"],
                values["price_raml"],
            )
        except Exception as exc:
            self._show_error("تعذّر حفظ سعر الجرار", exc)
        self._refresh_grid()

    def add_tractor_price(self) -> None:
        """Pick a tractor that is not already in this customer's grid."""
        if self.current_id is None:
            return
        try:
            options = self._backend().available_tractors(self.current_id)
        except Exception as exc:
            self._show_error("تعذّر تحميل قائمة الجرارات", exc)
            return
        if not options:
            QMessageBox.information(
                self,
                "لا توجد جرارات متاحة",
                "كل الجرارات النشطة مضافة بالفعل لهذا العميل.",
            )
            return

        dialog = TawridTractorPickerDialog(options, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected:
            return
        tractor = dialog.selected
        try:
            # Seeded with the tractor's own rates: a blank row would otherwise
            # be saved as zero and quietly price the haulage at nothing.
            self._backend().add_tractor_price(
                self.current_id,
                tractor["tractor_id"],
                0,
                tractor.get("price_sen") or 0,
                tractor.get("price_raml") or 0,
            )
        except Exception as exc:
            self._show_error("تعذّر إضافة الجرار", exc)
            return
        self._refresh_grid()

    def delete_tractor_price(self) -> None:
        row = self.grid.currentRow()
        if row < 0 or row >= len(self._grid_rows):
            return
        price = self._grid_rows[row]
        answer = QMessageBox.question(
            self,
            "تأكيد الحذف",
            f"حذف سعر الجرار «{price.driver_name}» لهذا العميل؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self._backend().delete_tractor_price(price.price_id)
        except Exception as exc:
            self._show_error("تعذّر حذف السعر", exc)
            return
        self._refresh_grid()

    # -- hooks fired by BaseCrudScreen ------------------------------------

    def set_mode(self, mode: str) -> None:
        super().set_mode(mode)
        # Built by _build_content, which the base constructor calls after
        # set_mode is first reachable — guard so early calls are harmless.
        if hasattr(self, "grid"):
            self._update_grid_state()

    def _fill_form(self, record: dict[str, Any]) -> None:
        super()._fill_form(record)
        # ``_fill_form`` in the base class skips hidden_on_form fields, and the
        # ten item prices are hidden so the base form panel would not render
        # them — fill them here instead.
        for name in PRICE_FIELDS:
            self._set_editor_value(self.inputs.get(name), record.get(name))

        # ``get_record`` returns only the columns the spec declares, and
        # ``customer_id`` is a surrogate key that is not one of them — so read
        # the id from ``current_id``, which load_selected() sets before this.
        customer_id = record.get(self.spec.primary_key) or self.current_id
        self._refresh_balance(customer_id)
        self._refresh_grid()

        # For the same reason the base class's "السجل الحالي" label comes out
        # blank; name the customer instead, which is what identifies him here.
        name = str(record.get("customer_name") or "").strip()
        code = record.get("customer_code")
        if name:
            self.summary_label.setText(
                f"السجل الحالي: {name}" + (f" — مسلسل {code}" if code else "")
            )

    def _clear_form(self) -> None:
        super()._clear_form()
        # A cleared choices-combo lands on index 0; keep الحالة meaningful.
        self._set_editor_value(self.inputs.get("is_active"), "نشط")
        self._show_balance(CustomerBalance())
        if hasattr(self, "grid"):
            self._refresh_grid()

    def new_record(self) -> None:
        """Start a new customer with the next مسلسل already filled in."""
        super().new_record()
        try:
            self._set_editor_value(
                self.inputs["customer_code"], self._backend().next_code()
            )
        except Exception:
            # A suggestion only — never block creating a record over it.
            pass

    def save_record(self) -> None:
        """Treat a blank money box as zero before handing over to the base save.

        Every price column plus ``opening_balance`` and ``discount_percent`` is
        NOT NULL DEFAULT 0. A blank field otherwise reaches the database as NULL
        and surfaces as a raw NotNullViolation — but for a money box on this
        form, blank plainly means "nothing", not "unknown".
        """
        for name in ("opening_balance", "discount_percent", *PRICE_FIELDS):
            editor = self.inputs.get(name)
            if editor is not None and not str(self._editor_value(editor) or "").strip():
                self._set_editor_value(editor, 0)
        super().save_record()
        # A brand-new customer only becomes a valid grid parent once saved.
        if hasattr(self, "grid"):
            self._refresh_grid()

    def _cascade_warning(self) -> str | None:
        """Name the grid rows that go with the customer, so the delete is informed."""
        base = super()._cascade_warning()
        try:
            rows = self._backend().price_row_count(self.current_id)
        except Exception:
            return base
        if not rows:
            return base
        line = f"تنبيه: سيتم أيضًا حذف {rows} صف من شبكة أسعار الجرارات لهذا العميل."
        return f"{base}\n{line}" if base else line

    def delete_record(self) -> None:
        """Refuse to delete a customer that has movement; offer stopping instead.

        This is the defect that made 911 legacy tickets unreadable: Access
        deleted the customer row outright and left the tickets pointing at
        nothing, so those statements can never be reproduced.
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
                    f"هذا العميل عليه {movement} حركة مسجّلة (بونات/سندات قبض)، "
                    "وحذفه هيخلي حركته من غير صاحب.\n"
                    "غيّر «الحالة» إلى «موقوف» بدل الحذف.",
                )
                return
        super().delete_record()
