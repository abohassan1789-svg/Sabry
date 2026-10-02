"""شاشة الجرارات — قسم التوريدات (Tawrid module, phase 1).

Layout is "Model 8" from the mockup set the user picked: the standard
form + search-list of :class:`BaseCrudScreen`, with an **account summary**
above it. Standing on a driver, you can see what he is owed without opening a
statement — the question this screen exists to answer.

Everything below is presentation only. The CRUD path is the shared one
(``ReviewDataService`` + ``TABLE_SPECS['tawrid_tractors']``); the balance figures
come from :class:`TawridTractorService`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.services.review_data_service import ReviewDataService, TABLE_SPECS
from app.services.tawrid_tractor_service import TawridTractorService, TractorBalance
from app.ui.common.theme import GREEN, TEXT
from app.ui.screens.base_crud_screen import BaseCrudScreen

# Placeholder shown wherever a movement figure would go while the البون and
# سندات الصرف tables have not been built yet (phases 5 and 6).
_PENDING = "—"


def _money(value: Decimal | float | int) -> str:
    """Thousands-separated, two decimals. Negative shown as ``1,234.00-``."""
    amount = Decimal(str(value or 0))
    text = f"{abs(amount):,.2f}"
    return f"{text}-" if amount < 0 else text


class TawridTractorsScreen(BaseCrudScreen):
    SPEC_KEY = "tawrid_tractors"
    SEARCH_PLACEHOLDER = "ابحث باسم السائق أو رقم المقطورة أو الوش"

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        # Populated before super().__init__ because the base constructor builds
        # the UI, which calls back into the summary widgets built here.
        self._balance_service: TawridTractorService | None = None
        self._stat_values: dict[str, QLabel] = {}
        self._ledger_values: dict[str, QLabel] = {}
        super().__init__(service, TABLE_SPECS[self.SPEC_KEY], parent)
        self._show_balance(TractorBalance())

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

        The shared choices-combo starts with an empty item meaning "no
        selection". ``is_active`` is NOT NULL in the database, so an empty
        selection would surface as a raw NotNullViolation. The field is also not
        marked ``required`` — that check rejects any falsey value, which would
        wrongly reject "موقوف" (False).
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
        """Form + list (the shared lookup layout) with the summary strip on top."""
        content = QVBoxLayout()
        content.setSpacing(10)
        content.addWidget(self._build_summary_panel(), 0)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self._build_form_panel(), 1)
        row.addWidget(self._build_list_panel(), 0)
        content.addLayout(row, 1)
        return content

    def _build_summary_panel(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet(
            "QFrame { background:#FFFFFF; border:1px solid #E5EAF0; border-radius:7px; }"
        )
        outer = QHBoxLayout(panel)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(12)

        # Three headline tiles.
        for key, caption in (
            ("opening", "رصيد أول المدة"),
            ("trips", "عدد النقلات"),
            ("balance", "المستحق حالياً"),
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
            ("earned", "قيمة النقلات"),
            ("paid", "المصروف له"),
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

    # -- data ------------------------------------------------------------

    def _backend(self) -> TawridTractorService:
        if self._balance_service is None:
            self._balance_service = TawridTractorService()
        return self._balance_service

    def _refresh_balance(self, tractor_id: Any) -> None:
        """Recompute the summary. A failure here must never block the form."""
        try:
            balance = self._backend().for_tractor(tractor_id)
        except Exception:
            balance = TractorBalance()
        self._show_balance(balance)

    def _show_balance(self, balance: TractorBalance) -> None:
        pending = not balance.movements_available
        self._stat_values["opening"].setText(_money(balance.opening_balance))
        self._stat_values["trips"].setText(_PENDING if pending else f"{balance.trips_count:,}")
        self._stat_values["balance"].setText(_money(balance.balance))

        self._ledger_values["opening"].setText(_money(balance.opening_balance))
        self._ledger_values["earned"].setText(_PENDING if pending else f"+ {_money(balance.earned)}")
        self._ledger_values["paid"].setText(_PENDING if pending else f"- {_money(balance.paid)}")
        self._ledger_values["net"].setText(_money(balance.balance))

    # -- hooks fired by BaseCrudScreen ------------------------------------

    def _fill_form(self, record: dict[str, Any]) -> None:
        super()._fill_form(record)
        # ``get_record`` returns only the columns the spec declares, and
        # ``tractor_id`` is a surrogate key that is not one of them — so read the
        # id from ``current_id``, which load_selected() sets before calling here.
        self._refresh_balance(record.get(self.spec.primary_key) or self.current_id)
        # For the same reason the base class's "السجل الحالي" label comes out
        # blank; name the driver instead, which is what identifies a tractor here.
        driver = str(record.get("driver_name") or "").strip()
        code = record.get("tractor_code")
        if driver:
            self.summary_label.setText(
                f"السجل الحالي: {driver}" + (f" — مسلسل {code}" if code else "")
            )

    def _clear_form(self) -> None:
        super()._clear_form()
        # A cleared choices-combo lands on index 0; keep الحالة meaningful.
        self._set_editor_value(self.inputs.get("is_active"), "نشط")
        self._show_balance(TractorBalance())

    def new_record(self) -> None:
        """Start a new tractor with the next مسلسل already filled in."""
        super().new_record()
        try:
            self._set_editor_value(self.inputs["tractor_code"], self._backend().next_code())
        except Exception:
            # A suggestion only — never block creating a record over it.
            pass

    def save_record(self) -> None:
        """Treat a blank money box as zero before handing over to the base save.

        ``price_sen``/``price_raml``/``opening_balance`` are NOT NULL DEFAULT 0.
        A blank field otherwise reaches the database as NULL and surfaces as a
        raw NotNullViolation — but for a money box on this form, blank plainly
        means "nothing", not "unknown". Filling in the zero here keeps that from
        ever becoming an error the user has to decode.
        """
        for name in ("price_sen", "price_raml", "opening_balance"):
            editor = self.inputs.get(name)
            if editor is not None and not str(self._editor_value(editor) or "").strip():
                self._set_editor_value(editor, 0)
        super().save_record()
