"""Every template-picker choice must reach *its own* builder.

This mapping broke silently once already: ``on_preview`` and ``on_export_pdf``
each open-coded ``build_invoice_html if choice == 1 else build_invoice_html_v2``,
so picking النموذج الثالث quietly printed النموذج الثاني. The picker looked fine
and nothing failed — the wrong layout simply came out. The dispatch now lives in
one place (:meth:`SaudiSalesInvoicePage._choose_invoice_builder`); this pins it.

The picker dialog is patched out, so no window opens and the tests stay headless.
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication

from app.services.saudi_sales_invoice_service import SaudiSalesInvoiceService
from app.ui.screens import saudi_invoice_print
from app.ui.screens.saudi_invoice_print import (
    _DEFAULT_TEMPLATE_OPTIONS,
    build_invoice_html,
)
from app.ui.screens.saudi_invoice_print_v2 import build_invoice_html_v2
from app.ui.screens.saudi_invoice_print_v3 import build_invoice_html_v3
from app.ui.screens.saudi_invoice_print_v4 import build_invoice_html_v4
from app.ui.screens.saudi_invoice_print_v5 import build_invoice_html_v5
from app.ui.screens.saudi_invoice_print_v6 import build_invoice_html_v6
from app.ui.screens.saudi_invoice_print_v7 import build_invoice_html_v7
from app.ui.screens.saudi_invoice_print_v8 import build_invoice_html_v8
from app.ui.screens.saudi_sales_invoice_page import SaudiSalesInvoicePage

from tests.unit.test_saudi_sales_invoice_page import FakeRepo

_EXPECTED = {
    1: build_invoice_html,
    2: build_invoice_html_v2,
    3: build_invoice_html_v3,
    4: build_invoice_html_v4,
    5: build_invoice_html_v5,
    6: build_invoice_html_v6,
    7: build_invoice_html_v7,
    8: build_invoice_html_v8,
}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    return SaudiSalesInvoicePage(service=SaudiSalesInvoiceService(repository=FakeRepo()))


def test_every_option_has_a_builder():
    """A new option in the picker without a builder falls back to النموذج الأول."""
    assert len(_DEFAULT_TEMPLATE_OPTIONS) == len(_EXPECTED)


@pytest.mark.parametrize("choice", sorted(_EXPECTED))
def test_choice_reaches_its_own_builder(page, monkeypatch, choice):
    monkeypatch.setattr(
        "app.ui.screens.saudi_invoice_print.choose_invoice_template",
        lambda *a, **k: choice,
    )
    assert page._choose_invoice_builder("المعاينة") is _EXPECTED[choice]


def test_cancelling_the_picker_builds_nothing(page, monkeypatch):
    monkeypatch.setattr(
        "app.ui.screens.saudi_invoice_print.choose_invoice_template",
        lambda *a, **k: None,
    )
    assert page._choose_invoice_builder("المعاينة") is None


# ======================================================================
# Receipt voucher (سند قبض) — printed from two different screens
# ======================================================================
from app.ui.screens.saudi_receipt_voucher_print import (  # noqa: E402
    VOUCHER_TEMPLATE_OPTIONS,
    build_receipt_voucher_html,
    build_receipt_voucher_html_v2,
    build_receipt_voucher_html_v3,
    build_receipt_voucher_html_v4,
    build_receipt_voucher_html_v5,
    build_receipt_voucher_html_v6,
    build_receipt_voucher_html_v7,
    build_receipt_voucher_html_v8,
    build_receipt_voucher_html_v9,
    choose_voucher_builder,
)
from app.ui.screens.saudi_voucher_print_phase1 import (  # noqa: E402
    build_phase1_voucher_html,
    build_phase1_voucher_html_v2,
    build_phase1_voucher_html_v4,
)

_VOUCHER_EXPECTED = {
    1: build_receipt_voucher_html,
    2: build_receipt_voucher_html_v2,
    3: build_receipt_voucher_html_v3,
    4: build_receipt_voucher_html_v4,
    5: build_receipt_voucher_html_v5,
    6: build_receipt_voucher_html_v6,
    7: build_receipt_voucher_html_v7,
    8: build_receipt_voucher_html_v8,
    9: build_receipt_voucher_html_v9,
    # النماذج العاشر/الحادي عشر/الثاني عشر = Phase-1 layouts reused in Phase-2.
    10: build_phase1_voucher_html,
    11: build_phase1_voucher_html_v2,
    12: build_phase1_voucher_html_v4,
}


def test_every_voucher_option_has_a_builder():
    assert len(VOUCHER_TEMPLATE_OPTIONS) == len(_VOUCHER_EXPECTED)


@pytest.mark.parametrize("choice", sorted(_VOUCHER_EXPECTED))
def test_voucher_choice_reaches_its_own_builder(qapp, monkeypatch, choice):
    monkeypatch.setattr(
        "app.ui.screens.saudi_invoice_print.choose_invoice_template",
        lambda *a, **k: choice,
    )
    assert choose_voucher_builder(None) is _VOUCHER_EXPECTED[choice]


def test_cancelling_the_voucher_picker_builds_nothing(qapp, monkeypatch):
    monkeypatch.setattr(
        "app.ui.screens.saudi_invoice_print.choose_invoice_template",
        lambda *a, **k: None,
    )
    assert choose_voucher_builder(None) is None


# ======================================================================
# Phase-1 «مرحلة أولى» rosters (فواتير + سندات) — النموذج الأول → السادس
# ======================================================================
from app.ui.screens.saudi_invoice_print_phase1 import (  # noqa: E402
    PHASE1_TEMPLATE_OPTIONS,
    _PHASE1_BUILDERS,
    build_phase1_invoice_html_v6,
    phase1_builder_for,
)
from app.ui.screens.saudi_voucher_print_phase1 import (  # noqa: E402
    PHASE1_VOUCHER_TEMPLATE_OPTIONS,
    _PHASE1_VOUCHER_BUILDERS,
    build_phase1_voucher_html_v6,
    phase1_voucher_builder_for,
)


def test_phase1_rosters_are_complete():
    """Every «مرحلة أولى» picker label (invoice + voucher) must have a builder, so a
    new option can never silently fall through to «قيد الإنشاء»."""
    assert len(PHASE1_TEMPLATE_OPTIONS) == len(_PHASE1_BUILDERS) == 6
    assert len(PHASE1_VOUCHER_TEMPLATE_OPTIONS) == len(_PHASE1_VOUCHER_BUILDERS) == 6


def test_phase1_sixth_templates_dispatch():
    """النموذج السادس (the azure «فاتورة ضريبية» + turquoise «سند قبض») reaches its
    own builder from either picker."""
    assert PHASE1_TEMPLATE_OPTIONS[5] == "النموذج السادس"
    assert phase1_builder_for(6) is build_phase1_invoice_html_v6
    assert PHASE1_VOUCHER_TEMPLATE_OPTIONS[5] == "النموذج السادس"
    assert phase1_voucher_builder_for(6) is build_phase1_voucher_html_v6


def test_both_voucher_screens_share_one_dispatch():
    """Neither screen may re-open-code the option list or the builder map.

    They each used to carry their own copy, so a template added to one screen was
    silently missing from the other. Both must go through choose_voucher_builder.
    """
    import inspect

    from app.ui.screens import receipt_vouchers_screen, saudi_sales_invoice_page

    for module in (receipt_vouchers_screen, saudi_sales_invoice_page):
        src = inspect.getsource(module)
        assert "choose_voucher_builder" in src, f"{module.__name__} bypasses the shared dispatch"
        assert "build_receipt_voucher_html_v2" not in src, (
            f"{module.__name__} open-codes a voucher builder map again"
        )
