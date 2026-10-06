"""Tests for شاشة دفعات المقاولين — النموذجان 4 و7 كتبويبين (headless Qt, no database).

The user's rules:

* الحقول: التاريخ، اسم المقاول، اسم الشركة، اسم المشروع، رقم المستخلص، المبلغ، ملاحظات.
* رقم المستخلص قائمة منسدلة بناءً على المقاول + الشركة + المشروع مع بعض.
* رقم المستخلص اختياري: لو فاضي تبقى دفعة عامة على كل مستخلصات المشروع.
"""

from __future__ import annotations

import datetime
import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication

from app.services.contractor_extract_service import ContractorExtractService, ExtractError
from app.services.contractor_payment_service import (
    ContractorPaymentService,
    PaymentError,
    companies_of,
    contractor_summary,
    extracts_of,
    general_paid,
    payment_balance,
    project_balance,
    projects_of,
    with_net,
)
from app.ui.screens import contractor_payments_screen as screen_module
from app.ui.screens.contractor_payments_screen import (
    GENERAL,
    GENERAL_TEXT,
    TAB_BOARD,
    TAB_TREE,
    ContractorPaymentsScreen,
)

CONTRACTORS = [
    {"contractor_id": 1, "contractor_code": "A-H/CD-1001", "contractor_name": "أحمد للمقاولات", "contractor_type": "مقاول"},
    {"contractor_id": 2, "contractor_code": "A-H/CD-1002", "contractor_name": "البناء الحديث", "contractor_type": "مقاول"},
    {"contractor_id": 3, "contractor_code": "A-H/CD-1003", "contractor_name": "مورد بدون مستخلصات", "contractor_type": "مورد"},
]
_PLACES = {
    11: (10, "A-H/CO-1001", "شركة الأهرام", "A-H/CO-1001/PR-01", "كمبوند الياسمين"),
    12: (10, "A-H/CO-1001", "شركة الأهرام", "A-H/CO-1001/PR-02", "الياسمين 2"),
    21: (20, "A-H/CO-1002", "مجموعة النيل", "A-H/CO-1002/PR-01", "أبراج النيل"),
}


def _extract(extract_id, contractor_id, project_id, number, works, paid):
    company_id, company_code, company_name, project_code, project_name = _PLACES[project_id]
    contractor = CONTRACTORS[contractor_id - 1]
    # No deductions, so صافي المستخلص = إجمالي المستخلص.
    return {"extract_id": extract_id, "extract_no": number, "extract_date": datetime.date(2026, 9, 5),
            "works_value": Decimal(works), "vat_pct": Decimal("14"), "advance_payment_pct": 0,
            "withholding_tax_pct": 0, "works_insurance_pct": 0, "social_insurance_pct": 0, "other_deductions": 0,
            "contract_id": 100 + extract_id, "contract_no": number.rsplit("/", 1)[0],
            "contractor_id": contractor_id, "contractor_code": contractor["contractor_code"],
            "contractor_name": contractor["contractor_name"], "company_id": company_id,
            "company_code": company_code, "company_name": company_name, "project_id": project_id,
            "project_code": project_code, "project_name": project_name, "paid": Decimal(paid)}


RAW_CATALOG = [
    _extract(500, 1, 11, "A-H/CT-1001/EX-01", "100000", "100000"),  # مسدد
    _extract(501, 1, 11, "A-H/CT-1001/EX-02", "300000", "200000"),
    _extract(502, 1, 12, "A-H/CT-1003/EX-01", "50000", "0"),
    _extract(510, 2, 21, "A-H/CT-1002/EX-01", "400000", "0"),
]
# payment_id: (extract_id or None = دفعة عامة, contractor, project, date, amount, notes)
PAYMENTS = {
    900: (500, 1, 11, datetime.date(2026, 9, 8), "100000", "دفعة أولى"),
    901: (501, 1, 11, datetime.date(2026, 9, 18), "150000", "شيك"),
    902: (501, 1, 11, datetime.date(2026, 9, 22), "50000", "نقدي"),
    903: (None, 1, 11, datetime.date(2026, 9, 20), "20000", "تحت الحساب"),
}
GENERAL_TOTALS = {(1, 11): Decimal("20000")}


def _payment(payment_id):
    extract_id, contractor_id, project_id, date, amount, notes = PAYMENTS[payment_id]
    company_id, _code, company_name, _pcode, project_name = _PLACES[project_id]
    x = next((r for r in RAW_CATALOG if r["extract_id"] == extract_id), None)
    return {"payment_id": payment_id, "payment_date": date, "extract_id": extract_id, "amount": Decimal(amount),
            "notes": notes, "extract_no": x["extract_no"] if x else "دفعة عامة",
            "contractor_id": contractor_id, "contractor_name": CONTRACTORS[contractor_id - 1]["contractor_name"],
            "company_id": company_id, "company_name": company_name, "project_id": project_id,
            "project_name": project_name, "status": "approved", "account_type": "رصيد جاري"}


class FakeService:
    def __init__(self):
        self.saved = []
        self.deleted = []
        self.approved = []
        self.unapproved = []

    def contractor_choices(self):
        return [dict(c) for c in CONTRACTORS]

    def extract_catalog(self):
        return with_net([dict(r) for r in RAW_CATALOG])

    def general_totals(self):
        return dict(GENERAL_TOTALS)

    def payments(self, contractor_id=None, extract_id=None, project_id=None):
        rows = [_payment(pid) for pid in PAYMENTS]
        if extract_id is not None:
            return [r for r in rows if r["extract_id"] == extract_id]
        if contractor_id is not None and project_id is not None:
            return [r for r in rows if r["extract_id"] is None and r["contractor_id"] == contractor_id
                    and r["project_id"] == project_id]
        if contractor_id is not None:
            return [r for r in rows if r["contractor_id"] == contractor_id]
        return rows

    def get_payment(self, payment_id):
        return _payment(payment_id) if payment_id in PAYMENTS else None

    def search_payments(self, keyword=""):
        return [r for r in self.payments()
                if keyword in " ".join(str(r[k]) for k in ("contractor_name", "company_name", "project_name",
                                                           "extract_no", "notes"))]

    def save_payment(self, data, payment_id=None, allow_approved=False):
        self.saved.append((dict(data), payment_id))
        return payment_id or 902

    def delete_payment(self, payment_id, allow_approved=False):
        self.deleted.append(payment_id)

    def approve(self, payment_id, user_id=None):
        self.approved.append(payment_id)

    def unapprove(self, payment_id):
        self.unapproved.append(payment_id)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app, monkeypatch):
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(screen_module.QMessageBox, name, lambda *a, **k: None)
    monkeypatch.setattr(screen_module.QMessageBox, "question", lambda *a, **k: screen_module.QMessageBox.Yes)
    return ContractorPaymentsScreen(FakeService())


@pytest.fixture
def admin_screen(screen):
    """Every payment in the fake is approved: only an admin may edit or delete one."""
    screen.approval.is_admin = True
    screen.set_mode("view")
    return screen


def _combo_ids(combo):
    return [combo.itemData(i) for i in range(combo.count())]


# --- the cascade and the arithmetic -----------------------------------------------------------

def test_extract_list_follows_contractor_company_and_project():
    catalog = with_net(RAW_CATALOG)
    assert [c["company_id"] for c in companies_of(catalog, 1)] == [10]
    assert [p["project_id"] for p in projects_of(catalog, 1, 10)] == [11, 12]
    assert [x["extract_id"] for x in extracts_of(catalog, 1, 10, 11)] == [500, 501]
    assert [x["extract_id"] for x in extracts_of(catalog, 1, 10, 12)] == [502]
    assert extracts_of(catalog, 2, 10, 11) == []  # another contractor's project: nothing
    assert companies_of(catalog, 3) == []


def test_net_and_remaining_come_from_the_extract():
    row = next(r for r in with_net(RAW_CATALOG) if r["extract_id"] == 501)
    assert row["net"] == Decimal("300000.00") and row["remaining"] == Decimal("100000.00")


def test_payment_balance_new_and_edited():
    new = payment_balance("300000", "200000", 0, "30,000")
    assert new == {"net": Decimal("300000"), "previous": Decimal("200000"), "this": Decimal("30000"),
                   "remaining": Decimal("70000")}
    edited = payment_balance("300000", "200000", "50000", "80000")  # its own 50,000 isn't counted twice
    assert edited["previous"] == Decimal("150000") and edited["remaining"] == Decimal("70000")
    assert payment_balance("100", "100", 0, "20")["remaining"] == Decimal("-20")


def test_contractor_summary_counts_general_payments():
    summary = contractor_summary(with_net(RAW_CATALOG), 1, GENERAL_TOTALS)
    assert summary["net"] == Decimal("450000.00")
    assert summary["paid"] == Decimal("320000")  # 300,000 on extracts + 20,000 general
    assert summary["remaining"] == Decimal("130000.00")


def test_project_balance_and_general_paid():
    catalog = with_net(RAW_CATALOG)
    assert general_paid(GENERAL_TOTALS, 1) == Decimal("20000")
    assert general_paid(GENERAL_TOTALS, 1, 12) == 0
    balance = project_balance(catalog, GENERAL_TOTALS, 1, 10, 11)
    assert balance == {"net": Decimal("400000.00"), "paid": Decimal("320000"), "remaining": Decimal("80000.00")}


class _NoDb:
    def fetch_one(self, *_a, **_k):
        return None


@pytest.mark.parametrize("change,message", [
    ({"contractor_id": None}, "المقاول"),
    ({"project_id": None}, "المشروع"),
    ({"payment_date": ""}, "تاريخ"),
    ({"amount": "0"}, "مبلغ"),
    ({"amount": "-5"}, "مبلغ"),
    ({"notes": "x" * 501}, "الملاحظات"),
    ({"account_type": None}, "نوع الحساب"),
    ({"account_type": "خزينة"}, "نوع الحساب"),
])
def test_save_refuses_bad_payments(change, message):
    data = {"contractor_id": 1, "project_id": 11, "extract_id": 501, "payment_date": "2026-09-26",
            "amount": "1,000", "notes": "", "account_type": "رصيد جاري"}
    data.update(change)
    with pytest.raises(PaymentError, match=message):
        ContractorPaymentService(_NoDb()).save_payment(data)


class _RecordingDb:
    """*owner* answers the extract's contractor/project; every record is *status*."""

    def __init__(self, owner, status="approved"):
        self.owner = owner
        self.status = status
        self.sql = []

    def fetch_one(self, sql, params=None):
        if sql.startswith("SELECT status FROM"):
            return {"status": self.status}
        self.sql.append((sql, params))
        return self.owner if "contractor_extracts" in sql else {"payment_id": 77}


def test_save_without_an_extract_is_a_general_payment():
    db = _RecordingDb(None)
    new_id = ContractorPaymentService(db).save_payment(
        {"contractor_id": 1, "project_id": 11, "extract_id": None, "payment_date": "2026-09-26", "amount": "5,000",
         "account_type": "رصيد جاري"})
    assert new_id == 77
    sql, params = db.sql[-1]
    assert sql.startswith("INSERT") and params[1:4] == [1, 11, None] and params[4] == Decimal("5000")


def test_save_refuses_a_draft_contractor_or_project():
    from app.services.contracting_approval import ApprovalError
    db = _RecordingDb(None, status="draft")
    with pytest.raises(ApprovalError, match="مسودة"):
        ContractorPaymentService(db).save_payment(
            {"contractor_id": 1, "project_id": 11, "extract_id": None, "payment_date": "2026-09-26", "amount": "1",
             "account_type": "رصيد جاري"})
    assert not any(sql.startswith("INSERT") for sql, _p in db.sql)


def test_save_refuses_an_extract_of_another_contractor_or_project():
    db = _RecordingDb({"contractor_id": 2, "project_id": 21})
    with pytest.raises(PaymentError, match="مش تبع"):
        ContractorPaymentService(db).save_payment(
            {"contractor_id": 1, "project_id": 11, "extract_id": 510, "payment_date": "2026-09-26", "amount": "1",
             "account_type": "رصيد جاري"})


def test_an_extract_with_payments_cannot_be_deleted():
    class Db:
        def fetch_one(self, *_a, **_k):
            return {"n": 2}

        def execute(self, *_a, **_k):
            raise AssertionError("must not delete")

    with pytest.raises(ExtractError, match="2 دفعة"):
        ContractorExtractService(Db()).delete_extract(501)


def _pick_account(fields, account_type="رصيد جاري"):
    """نوع الحساب is required and starts empty on a new payment."""
    fields.account.setCurrentIndex(fields.account.findData(account_type))


# --- the two tabs --------------------------------------------------------------------------------

def test_both_mockups_are_tabs(screen):
    assert "نموذج 4" in screen.tabs.tabText(TAB_TREE)
    assert "نموذج 7" in screen.tabs.tabText(TAB_BOARD)


def test_opens_on_the_latest_payment_of_the_latest_extract(screen):
    assert (screen.contractor_id, screen.company_id, screen.project_id, screen.extract_id) == (1, 10, 11, 501)
    assert screen.current_id == 902
    for fields in screen.fields_pair:
        assert fields.amount.text() == "50,000.00"
        assert fields.notes.text() == "نقدي"
    assert screen.tree_contractor.text() == "أحمد للمقاولات"
    assert screen.tree_company.text() == "شركة الأهرام"
    assert screen.tree_project.text() == "كمبوند الياسمين"


def test_extract_lists_start_with_general_and_show_what_is_left(screen):
    for combo in (screen.tree_extract, screen.board_extract):
        assert _combo_ids(combo) == [GENERAL, 500, 501]
        assert combo.itemText(0) == GENERAL_TEXT
        assert combo.itemText(1) == "A-H/CT-1001/EX-01 — مسدد"
        assert combo.itemText(2) == "A-H/CT-1001/EX-02 — المتبقي 100,000.00"


def test_balance_strip_of_the_open_payment(screen):
    stats = {key: label.text() for key, label in screen.tree_stats.items()}
    assert stats == {"net": "300,000.00", "previous": "150,000.00", "this": "50,000.00", "remaining": "100,000.00"}
    assert screen.board_remaining.text() == "100,000.00"
    assert screen.tree_warning.isHidden()


def test_board_kpis_and_tables(screen):
    assert screen.board_kpis["net"].text() == "450,000.00"
    assert screen.board_kpis["paid"].text() == "320,000.00"
    assert screen.board_kpis["remaining"].text() == "130,000.00"
    assert screen.board_kpis["count"].text() == "4"
    assert screen.tree_table.rowCount() == 3   # EX-02's two payments + the totals row
    assert screen.board_table.rowCount() == 5  # the contractor's four + the totals row
    assert set(screen._cards) == {GENERAL, 500, 501}
    assert "المتبقي على المشروع 80,000.00" in screen.board_path.text()


def test_picking_a_project_lists_only_its_extracts(screen):
    screen.tabs.setCurrentIndex(TAB_BOARD)
    assert _combo_ids(screen.board_company) == [10]
    assert _combo_ids(screen.board_project) == [11, 12]
    screen.board_project.setCurrentIndex(screen.board_project.findData(12))
    assert screen.extract_id == 502
    assert _combo_ids(screen.board_extract) == [GENERAL, 502]
    assert screen.current_id is None and screen.board_fields.amount.text() == ""
    assert screen.tree_project.text() == "الياسمين 2"  # the other tab follows


def test_picking_a_contractor_walks_the_cascade(screen):
    screen.board_contractor.setCurrentIndex(screen.board_contractor.findData(2))
    assert (screen.company_id, screen.project_id, screen.extract_id) == (20, 21, 510)
    assert screen.tree.currentItem().data(0, Qt.UserRole) == ("x", 510)


def test_a_contractor_without_extracts(screen):
    screen.board_contractor.setCurrentIndex(screen.board_contractor.findData(3))
    assert screen.extract_id is None and screen.board_extract.count() == 0
    assert "لا توجد مستخلصات" in screen.board_path.text()
    assert screen.board_kpis["net"].text() == "0.00"


def test_clicking_an_extract_in_the_tree_opens_its_payment(screen):
    screen._on_tree_clicked(screen._tree_items[("x", 500)], 0)
    assert screen.extract_id == 500 and screen.current_id == 900
    assert screen.board_extract.currentData() == 500
    assert screen.tree_stats["remaining"].text() == "0.00"


def test_tree_search_keeps_matching_extracts(screen):
    screen.tree_search.setText("أبراج")
    assert ("x", 510) in screen._tree_items and ("x", 501) not in screen._tree_items


def test_clicking_a_card_selects_its_extract(screen):
    screen._cards[500].click()
    assert screen.extract_id == 500 and screen.current_id == 900


# --- new / save / edit / delete --------------------------------------------------------------------

def test_new_payment_on_the_selected_extract(screen):
    screen.new_payment()
    assert screen.mode == "new" and not screen.tabs.tabBar().isEnabled()
    fields = screen.tree_fields
    fields.amount.setText("30000")
    fields.notes.setText("تحويل")
    assert screen.tree_stats["previous"].text() == "200,000.00"
    assert screen.tree_stats["this"].text() == "30,000.00"
    assert screen.tree_stats["remaining"].text() == "70,000.00"
    _pick_account(screen.fields)
    screen.save_record()
    data, record_id = screen.service.saved[-1]
    assert record_id is None
    assert data["extract_id"] == 501 and data["amount"] == "30000" and data["notes"] == "تحويل"
    assert screen.mode == "view"


def test_paying_more_than_is_left_warns_and_asks(screen, monkeypatch):
    screen.new_payment()
    screen.tree_fields.amount.setText("150000")
    assert not screen.tree_warning.isHidden()
    assert "50,000.00" in screen.tree_warning.text()
    monkeypatch.setattr(screen_module.QMessageBox, "question", lambda *a, **k: screen_module.QMessageBox.No)
    screen.save_record()
    assert screen.service.saved == [] and screen.mode == "new"


def test_edit_can_move_the_payment_to_another_extract(admin_screen):
    screen = admin_screen
    screen.edit_record()
    assert screen.mode == "edit"
    assert screen.tree_stats["previous"].text() == "150,000.00"  # its own 50,000 isn't counted twice
    screen._on_tree_clicked(screen._tree_items[("x", 502)], 0)
    assert screen.extract_id == 502 and screen.mode == "edit"
    screen.save_record()
    data, record_id = screen.service.saved[-1]
    assert record_id == 902 and data["extract_id"] == 502


def test_other_payments_cannot_open_while_editing(admin_screen):
    screen = admin_screen
    screen.edit_record()
    screen._on_table_clicked(screen.tree_table, 0)
    assert screen.current_id == 902
    assert not screen.search_button.isEnabled()


def test_cancel_goes_back_to_the_saved_payment(admin_screen):
    screen = admin_screen
    screen.edit_record()
    screen.tree_fields.amount.setText("1")
    screen.cancel_edit()
    assert screen.mode == "view" and screen.tree_fields.amount.text() == "50,000.00"


def test_delete(admin_screen):
    screen = admin_screen
    screen.delete_record()
    assert screen.service.deleted == [902]


# --- «بحث» (F1) -----------------------------------------------------------------------------------

def test_search_dialog_has_the_users_columns(qt_app):
    from app.ui.dialogs.contractor_payment_picker import ContractorPaymentPickerDialog
    dialog = ContractorPaymentPickerDialog(FakeService().search_payments)
    headers = [dialog.table.horizontalHeaderItem(i).text() for i in range(dialog.table.columnCount())]
    assert headers == ["التاريخ", "اسم المقاول", "اسم الشركة", "اسم المشروع", "رقم المستخلص", "المبلغ", "ملاحظات"]
    assert dialog.table.rowCount() == 4
    dialog.search_text.setText("شيك")
    dialog._accept_if_unambiguous()
    assert dialog.selected["payment_id"] == 901


def test_search_opens_the_chosen_payment(screen, monkeypatch):
    class Picked:
        Accepted = 1

        def __init__(self, search_fn, parent=None):
            self.selected = next(r for r in search_fn("") if r["payment_id"] == 900)

        def exec(self):
            return 1

    monkeypatch.setattr(screen_module, "ContractorPaymentPickerDialog", Picked)
    screen.open_search()
    assert screen.current_id == 900 and screen.extract_id == 500


# --- دفعة عامة (رقم المستخلص فاضي) -------------------------------------------------------------------

def test_choosing_general_opens_the_projects_general_payment(screen):
    screen.board_extract.setCurrentIndex(screen.board_extract.findData(GENERAL))
    assert screen.extract_id is None and screen.project_id == 11
    assert screen.current_id == 903 and screen.tree_fields.notes.text() == "تحت الحساب"
    assert screen.tree_extract.currentData() == GENERAL
    assert screen.tree.currentItem().data(0, Qt.UserRole) == ("g", 1, 10, 11)
    # the project's balance: 400,000 net − 300,000 on extracts − 20,000 general
    stats = {key: label.text() for key, label in screen.tree_stats.items()}
    assert stats == {"net": "400,000.00", "previous": "300,000.00", "this": "20,000.00", "remaining": "80,000.00"}
    assert screen._captions["tree_stat_net"].text() == "صافي مستخلصات المشروع"
    assert "المشروع" in screen.board_remaining_caption.text()
    assert "الدفعات العامة" in screen.tree_table_title.text()


def test_the_tree_has_a_general_branch_per_project(screen):
    assert ("g", 1, 10, 12) in screen._tree_items
    screen._on_tree_clicked(screen._tree_items[("g", 1, 10, 11)], 0)
    assert screen.extract_id is None and screen.current_id == 903


def test_saving_a_general_payment_sends_no_extract(screen):
    screen._cards[GENERAL].click()
    screen.new_payment()
    screen.tree_fields.amount.setText("10000")
    assert screen.tree_stats["previous"].text() == "320,000.00"
    assert screen.tree_stats["remaining"].text() == "70,000.00"
    _pick_account(screen.fields)
    screen.save_record()
    data, record_id = screen.service.saved[-1]
    assert record_id is None
    assert (data["contractor_id"], data["project_id"], data["extract_id"]) == (1, 11, None)


def test_a_new_payment_can_switch_to_general(screen):
    screen.new_payment()
    screen.tree_extract.setCurrentIndex(screen.tree_extract.findData(GENERAL))
    assert screen.mode == "new" and screen.extract_id is None
    screen.tree_fields.amount.setText("500")
    _pick_account(screen.fields)
    screen.save_record()
    assert screen.service.saved[-1][0]["extract_id"] is None


# --- طريقة الدفع: نقدي / شيك / تحويل (2026-09-26) ------------------------------------------------

from app.services.contractor_payment_service import CASH, CHEQUE, PAYMENT_METHODS, TRANSFER, method_text  # noqa: E402

_CHEQUE = {"contractor_id": 1, "project_id": 11, "extract_id": None, "payment_date": "2026-09-26",
           "amount": "5,000", "payment_method": CHEQUE, "reference_no": " 123456 ", "cheque_date": "2026-10-01",
           "account_type": "تأمين أعمال"}


def test_methods_are_the_users_list():
    assert PAYMENT_METHODS == ("نقدي", "شيك", "تحويل")


@pytest.mark.parametrize("change,message", [
    ({"payment_method": "آجل"}, "طريقة الدفع"),
    ({"reference_no": "  "}, "رقم الشيك"),
    ({"payment_method": TRANSFER, "reference_no": ""}, "رقم الشيك / الحوالة"),
    ({"reference_no": "9" * 51}, "أطول"),
    ({"cheque_date": ""}, "تاريخ الشيك"),
])
def test_cheque_or_transfer_needs_its_number_and_date(change, message):
    with pytest.raises(PaymentError, match=message):
        ContractorPaymentService(_NoDb()).save_payment(dict(_CHEQUE, **change))


def test_cheque_is_saved_with_its_number_and_date():
    db = _RecordingDb(None)
    ContractorPaymentService(db).save_payment(dict(_CHEQUE))
    sql, params = db.sql[-1]
    assert "payment_method, reference_no, cheque_date, account_type" in sql
    assert params[-4:] == [CHEQUE, "123456", "2026-10-01", "تأمين أعمال"]


def test_cash_stores_no_number_or_date():
    """Switching a cheque back to نقدي must not leave its number behind."""
    db = _RecordingDb(None)
    ContractorPaymentService(db).save_payment(dict(_CHEQUE, payment_method=CASH))
    assert db.sql[-1][1][-4:-1] == [CASH, None, None]
    ContractorPaymentService(db).save_payment({k: v for k, v in _CHEQUE.items() if k != "payment_method"})
    assert db.sql[-1][1][-4:-1] == [CASH, None, None]  # an old caller without a method = نقدي


def test_method_text_in_the_tables():
    assert method_text({}) == "نقدي"
    assert method_text({"payment_method": CHEQUE, "reference_no": "123456"}) == "شيك 123456"
    assert method_text({"payment_method": TRANSFER, "reference_no": ""}) == "تحويل"
    assert method_text({"payment_method": CASH, "reference_no": "stale"}) == "نقدي"


def _reference_shown(fields):
    return [not box.isHidden() for box in fields.reference_boxes]


def test_number_and_date_only_open_for_cheque_or_transfer(screen):
    for fields in screen.fields_pair:
        assert fields.method.currentData() == CASH
        assert fields.reference_boxes and not any(_reference_shown(fields))
    screen.new_payment()
    fields = screen.fields
    for method, shown in ((CHEQUE, True), (TRANSFER, True), (CASH, False)):
        fields.method.setCurrentIndex(fields.method.findData(method))
        assert all(_reference_shown(fields)) is shown and any(_reference_shown(fields)) is shown


def test_saving_a_cheque_from_the_screen(screen):
    screen.new_payment()
    fields = screen.fields
    fields.amount.setText("30000")
    fields.date.setDate(QDate(2026, 9, 20))
    fields.method.setCurrentIndex(fields.method.findData(CHEQUE))
    assert fields.cheque_date.date() == QDate(2026, 9, 20)  # starts on the payment's date
    fields.reference.setText("778899")
    fields.cheque_date.setDate(QDate(2026, 10, 5))
    _pick_account(screen.fields)
    screen.save_record()
    data, _pid = screen.service.saved[-1]
    assert (data["payment_method"], data["reference_no"], data["cheque_date"]) == (CHEQUE, "778899", "2026-10-05")


def test_a_saved_cheque_opens_with_its_number_in_both_tabs(admin_screen):
    screen = admin_screen
    record = dict(_payment(902), payment_method=TRANSFER, reference_no="TR-55",
                  cheque_date=datetime.date(2026, 9, 30))
    screen.service.get_payment = lambda _pid: dict(record)
    screen.load_payment(902)
    for fields in screen.fields_pair:
        assert fields.method.currentData() == TRANSFER and all(_reference_shown(fields))
        assert fields.reference.text() == "TR-55" and fields.cheque_date.date() == QDate(2026, 9, 30)
        assert not fields.method.isEnabled() and fields.reference.isReadOnly()  # view mode
    screen.edit_record()
    assert screen.fields.method.isEnabled() and not screen.fields.reference.isReadOnly()


def test_payment_tables_show_the_method(screen):
    headers = [screen.tree_table.horizontalHeaderItem(i).text() for i in range(screen.tree_table.columnCount())]
    assert headers == ["التاريخ", "رقم المستخلص", "المبلغ", "نوع الحساب", "طريقة الدفع", "ملاحظات"]
    assert screen.tree_table.item(0, 3).text() == "رصيد جاري"
    assert screen.tree_table.item(0, 4).text() == "نقدي"
    board = [screen.board_table.horizontalHeaderItem(i).text() for i in range(screen.board_table.columnCount())]
    assert board[3:] == ["المبلغ", "نوع الحساب", "طريقة الدفع", "ملاحظات"]


# --- مسودة / معتمد --------------------------------------------------------------------------

def _with_draft(screen, payment_id=902):
    """Make *payment_id* a draft: listed, but not inside the extract's paid total."""
    original = screen.service.payments

    def payments(**kw):
        return [dict(r, status="draft") if r["payment_id"] == payment_id else r for r in original(**kw)]
    screen.service.payments = payments
    screen.service.get_payment = lambda pid: dict(_payment(pid), status="draft" if pid == payment_id else "approved")
    catalog = screen.service.extract_catalog
    screen.service.extract_catalog = lambda: [dict(r, paid=r["paid"] - 50000, remaining=r["remaining"] + 50000)
                                              if r["extract_id"] == 501 else r for r in catalog()]
    screen.refresh_all()
    screen.load_payment(payment_id)


def test_an_approved_payment_is_locked(screen):
    assert screen.current_id == 902 and screen.approval.badge.text() == "معتمد"
    assert not screen.edit_button.isEnabled() and not screen.delete_button.isEnabled()
    screen.edit_record()
    assert screen.mode == "view"
    screen.delete_record()
    assert screen.service.deleted == []
    screen.unapprove_record()
    assert screen.service.unapproved == [902]


def test_a_draft_payment_is_listed_but_not_totalled(screen):
    _with_draft(screen)
    assert screen.approval.badge.text() == "مسودة"
    assert screen.edit_button.isEnabled() and screen.approval.approve_button.isEnabled()
    rows = [screen.tree_table.item(r, 0).text() for r in range(screen.tree_table.rowCount())]
    assert any("مسودة" in text for text in rows)
    total_row = screen.tree_table.rowCount() - 1
    assert screen.tree_table.item(total_row, 1).text() == "1 دفعة"
    assert screen.tree_table.item(total_row, 2).text() == "150,000.00"  # 901 only


def test_a_draft_payment_is_counted_once_in_its_balance(screen):
    _with_draft(screen)  # EX-02: net 300,000, approved payments 150,000, this draft 50,000
    stats = {key: label.text() for key, label in screen.tree_stats.items()}
    assert stats == {"net": "300,000.00", "previous": "150,000.00", "this": "50,000.00", "remaining": "100,000.00"}
    screen.edit_record()
    assert screen.tree_stats["previous"].text() == "150,000.00"


def test_approving_a_draft_payment(screen):
    _with_draft(screen)
    screen.approve_record()
    assert screen.service.approved == [902]


# --- القوايم في باقي الشاشات (user request 2026-10-02) ----------------------------------------

def test_saving_and_deleting_announce_a_change(admin_screen, data_changes):
    screen = admin_screen
    screen.edit_record()
    screen.save_record()
    screen.delete_record()
    assert data_changes == [screen, screen]


def test_reload_lists_refreshes_the_contractor_list(screen, monkeypatch):
    extra = {"contractor_id": 9, "contractor_code": "A-H/CD-1009", "contractor_name": "مقاول جديد"}
    choices = screen.service.contractor_choices
    monkeypatch.setattr(screen.service, "contractor_choices", lambda: [*choices(), extra])
    screen.reload_lists()
    assert screen.board_contractor.findData(9) >= 0


def test_reload_lists_keeps_the_tree_scroll_position(screen):
    """Review fix: a reload must not jump the tree back to the top."""
    screen.show()
    screen.tree.setFixedHeight(70)
    QApplication.processEvents()
    bar = screen.tree.verticalScrollBar()
    assert bar.maximum() > 0, "the fake tree must be taller than the box"
    bar.setValue(bar.maximum())
    kept = bar.value()
    screen.reload_lists()
    QApplication.processEvents()
    assert bar.value() == kept
    screen.hide()


def test_clearing_the_cards_survives_an_unreferenced_widget(screen):
    """Review fix: the loop crashed on a widget only the grid held (e.g. an empty-state caption)."""
    from PySide6.QtWidgets import QLabel

    screen.cards_grid.addWidget(QLabel("—"), 0, 0)
    screen._fill_cards([])


# --- نوع الحساب: رصيد جاري / تأمين أعمال / تأمينات اجتماعية — required (2026-10-07) ---------------

from app.services.contractor_payment_service import ACCOUNT_TYPES  # noqa: E402
from app.ui.screens.contractor_payments_screen import ACCOUNT_PROMPT  # noqa: E402


def test_account_types_are_the_users_list():
    assert ACCOUNT_TYPES == ("رصيد جاري", "تأمين أعمال", "تأمينات اجتماعية")


def test_a_new_payment_starts_without_an_account_type(screen):
    for fields in screen.fields_pair:
        assert [fields.account.itemText(i) for i in range(fields.account.count())] == [ACCOUNT_PROMPT, *ACCOUNT_TYPES]
    for tab in (TAB_TREE, TAB_BOARD):  # the open tab's form is the one cleared
        screen.tabs.setCurrentIndex(tab)
        screen.new_payment()
        assert screen.fields.account.currentData() is None and screen.fields.account.isEnabled()
        screen.cancel_edit()


def test_saving_without_an_account_type_is_refused(screen, monkeypatch):
    warnings = []
    monkeypatch.setattr(screen_module.QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    screen.new_payment()
    screen.fields.amount.setText("30000")
    screen.save_record()
    assert screen.service.saved == [] and screen.mode == "new"
    assert warnings == ["اختار نوع الحساب."]
    _pick_account(screen.fields, "تأمين أعمال")
    screen.save_record()
    assert screen.service.saved[-1][0]["account_type"] == "تأمين أعمال" and screen.mode == "view"


def test_a_saved_payment_opens_with_its_account_type_in_both_tabs(admin_screen):
    screen = admin_screen
    record = dict(_payment(902), account_type="تأمينات اجتماعية")
    screen.service.get_payment = lambda _pid: dict(record)
    screen.load_payment(902)
    for fields in screen.fields_pair:
        assert fields.account.currentData() == "تأمينات اجتماعية" and not fields.account.isEnabled()
    screen.edit_record()
    assert screen.fields.account.isEnabled()
    screen.save_record()
    assert screen.service.saved[-1][0]["account_type"] == "تأمينات اجتماعية"
