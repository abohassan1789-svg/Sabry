"""Tests for شاشة بيانات الشركة — النموذج 8 (headless Qt, no database).

Covers what the user asked for:

* اسم الشركة، رقم السجل الضريبي، العنوان، اللوجو — and more than one company.
* The logo is saved in the database as bytes (+ mime), never as a path.
* «يظهر في الطباعة» beside the address only, saved as ``show_address_in_print``.
"""

from __future__ import annotations

import datetime
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialog

from app.services import company_info_service as service_module
from app.services.company_info_service import (
    CompanyInfoError,
    CompanyInfoService,
    clean,
    read_logo_file,
)
from app.ui.dialogs.company_info_list_dialog import filter_companies
from app.ui.screens import company_info_screen as screen_module
from app.ui.screens.company_info_screen import CompanyInfoScreen


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _png(color: str = "#0E5A66") -> bytes:
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(QColor(color))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


# --- the service, without a database -------------------------------------------------

def test_clean_trims_and_blanks_optional_texts():
    assert clean({"company_name": "  A-H  ", "tax_registration_no": " ", "address": "",
                  "show_address_in_print": False}) == {
        "company_name": "A-H", "tax_registration_no": None, "address": None,
        "show_address_in_print": False}


def test_clean_shows_the_address_by_default():
    assert clean({"company_name": "A-H"})["show_address_in_print"] is True


@pytest.mark.parametrize("data", [
    {"company_name": "   "},
    {"company_name": "x" * 201},
    {"company_name": "A-H", "tax_registration_no": "1" * 51},
    {"company_name": "A-H", "address": "ع" * 301},
])
def test_clean_refuses_bad_data(data):
    with pytest.raises(CompanyInfoError):
        clean(data)


def test_read_logo_file(tmp_path, monkeypatch):
    good = tmp_path / "logo.JPG"
    good.write_bytes(b"\xff\xd8 not checked here")
    assert read_logo_file(good) == (b"\xff\xd8 not checked here", "image/jpeg")

    with pytest.raises(CompanyInfoError):
        read_logo_file(tmp_path / "logo.txt")
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    with pytest.raises(CompanyInfoError):
        read_logo_file(empty)
    with pytest.raises(CompanyInfoError):
        read_logo_file(tmp_path / "missing.png")
    monkeypatch.setattr(service_module, "LOGO_MAX_BYTES", 4)
    with pytest.raises(CompanyInfoError):
        read_logo_file(good)


class FakeDb:
    """Answers the service's queries; ``taken`` makes the duplicate-name check hit."""

    def __init__(self, row=None, taken=False):
        self.row = row
        self.taken = taken
        self.queries: list[tuple[str, list]] = []

    def fetch_one(self, query, params=None):
        self.queries.append((query, list(params or [])))
        if "upper(btrim(company_name))" in query:
            return {"company_info_id": 9} if self.taken else None
        if query.startswith("INSERT"):
            return {"company_info_id": 5}
        return dict(self.row) if self.row else None

    def execute(self, query, params=None):
        self.queries.append((query, list(params or [])))


def test_service_get_returns_the_logo_as_bytes():
    db = FakeDb({"company_name": "A-H", "logo": memoryview(b"PNG"), "logo_mime": "image/png"})
    row = CompanyInfoService(db).get(1)
    assert row["logo"] == b"PNG" and isinstance(row["logo"], bytes)
    assert CompanyInfoService(FakeDb()).get(1) is None


def test_service_save_inserts_a_new_company_and_returns_its_id():
    db = FakeDb()
    new_id = CompanyInfoService(db).save(
        {"company_name": " A-H ", "tax_registration_no": "512-874-369", "address": "القاهرة",
         "show_address_in_print": False}, b"PNG", None, None, 7)
    query, params = db.queries[-1]
    assert new_id == 5
    assert query.startswith("INSERT INTO company_info") and "RETURNING company_info_id" in query
    assert params == ["A-H", "512-874-369", "القاهرة", False, b"PNG", "image/png", 7]


def test_service_save_updates_an_existing_company():
    db = FakeDb()
    assert CompanyInfoService(db).save({"company_name": "A-H"}, None, "image/png", 3) == 3
    query, params = db.queries[-1]
    assert query.startswith("UPDATE company_info SET") and query.endswith("WHERE company_info_id = %s")
    assert params[4:6] == [None, None]  # no logo -> no mime either
    assert params[-1] == 3


def test_service_save_refuses_a_name_another_company_has():
    db = FakeDb(taken=True)
    with pytest.raises(CompanyInfoError, match="في شركة تانية"):
        CompanyInfoService(db).save({"company_name": "A-H"}, None, None, 3)
    assert not any(q.startswith(("INSERT", "UPDATE")) for q, _p in db.queries)
    # the open company itself is left out of the check
    assert db.queries[-1][1] == ["A-H", 3, 3]


def test_service_save_checks_before_writing():
    db = FakeDb()
    with pytest.raises(CompanyInfoError):
        CompanyInfoService(db).save({"company_name": ""}, None, None)
    assert db.queries == []


def test_filter_companies_searches_name_tax_and_address():
    rows = [{"company_name": "A-H", "tax_registration_no": "512", "address": "القاهرة"},
            {"company_name": "النيل", "tax_registration_no": "777", "address": "الجيزة"}]
    assert filter_companies(rows, "") == rows
    assert filter_companies(rows, "a-h") == rows[:1]
    assert filter_companies(rows, "777") == rows[1:]
    assert filter_companies(rows, "الجيزة") == rows[1:]


# --- the screen ----------------------------------------------------------------------

class FakeService:
    def __init__(self, *rows):
        self.companies = {i: {**row, "company_info_id": i} for i, row in enumerate(rows, start=1)}
        self.saved: list[tuple[dict, bytes | None, str | None, object]] = []
        self.deleted: list[int] = []

    def list_rows(self):
        return [{"company_info_id": i, "company_name": r["company_name"],
                 "tax_registration_no": r.get("tax_registration_no"), "address": r.get("address")}
                for i, r in sorted(self.companies.items())]

    def get(self, company_id):
        row = self.companies.get(company_id)
        return dict(row) if row else None

    def save(self, data, logo, logo_mime, company_id=None, user_id=None):
        values = clean(data)
        for other_id, other in self.companies.items():
            if other_id != company_id and other["company_name"].upper() == values["company_name"].upper():
                raise CompanyInfoError(f"في شركة تانية اسمها «{values['company_name']}».")
        self.saved.append((values, logo, logo_mime, company_id))
        company_id = company_id or max(self.companies, default=0) + 1
        self.companies[company_id] = {
            **values, "company_info_id": company_id, "logo": logo, "logo_mime": logo_mime if logo else None,
            "updated_at": datetime.datetime(2026, 10, 5, 10, 30, tzinfo=datetime.timezone.utc)}
        return company_id

    def delete(self, company_id):
        self.deleted.append(company_id)
        self.companies.pop(company_id)


@pytest.fixture
def messages(monkeypatch):
    shown: list[tuple[str, str]] = []
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(screen_module.QMessageBox, name,
                            lambda _p, title, text, *a, _n=name, **k: shown.append((_n, text)))
    monkeypatch.setattr(screen_module.QMessageBox, "question",
                        lambda *a, **k: screen_module.QMessageBox.Yes)
    return shown


@pytest.fixture
def row():
    return {"company_name": "A-H للمقاولات العامة", "tax_registration_no": "512-874-369",
            "address": "التجمع الخامس، القاهرة الجديدة", "show_address_in_print": True,
            "logo": _png(), "logo_mime": "image/png", "updated_at": None}


@pytest.fixture
def second():
    return {"company_name": "شركة النيل", "tax_registration_no": "777-111-222", "address": None,
            "show_address_in_print": False, "logo": None, "logo_mime": None, "updated_at": None}


def test_opens_on_the_first_company_read_only(qt_app, messages, row, second):
    screen = CompanyInfoScreen(FakeService(row, second))
    assert screen.current_id == 1
    assert screen.name_edit.text() == "A-H للمقاولات العامة"
    assert screen.tax_edit.text() == "512-874-369"
    assert screen.address_edit.toPlainText() == "التجمع الخامس، القاهرة الجديدة"
    assert screen.show_address_check.isChecked()
    assert screen.hero_name.text() == "A-H للمقاولات العامة"
    assert not screen.hero_logo.pixmap().isNull()
    assert screen.position_label.text() == "شركة 1 من 2"
    assert screen.mode == "view" and screen.name_edit.isReadOnly()
    assert not screen.show_address_check.isEnabled()
    assert not screen.choose_logo_button.isEnabled() and not screen.save_button.isEnabled()
    assert screen.edit_button.isEnabled() and screen.delete_button.isEnabled()


def test_no_companies_yet(qt_app, messages):
    screen = CompanyInfoScreen(FakeService())
    assert screen.current_id is None
    assert "اضغط «جديد»" in screen.hero_name.text()
    assert screen.hero_logo.text() == "بدون لوجو"
    assert screen.new_button.isEnabled()
    assert not screen.edit_button.isEnabled() and not screen.delete_button.isEnabled()
    assert not screen.find_button.isEnabled()


def test_add_a_second_company(qt_app, messages, row):
    service = FakeService(row)
    screen = CompanyInfoScreen(service)
    screen.new_record()
    assert screen.mode == "new" and screen.name_edit.text() == "" and screen._logo is None
    assert screen.show_address_check.isChecked()  # the address prints unless unticked
    assert screen.hero_name.text() == "شركة جديدة"
    screen.name_edit.setText("شركة النيل")
    screen.show_address_check.setChecked(False)
    assert "مش هيظهر في الطباعة" in screen.hero_address_caption.text()
    screen.save_record()
    values, logo, _mime, company_id = service.saved[-1]
    assert company_id is None and values["company_name"] == "شركة النيل"
    assert values["show_address_in_print"] is False and logo is None
    assert screen.current_id == 2 and screen.position_label.text() == "شركة 2 من 2"
    assert screen.mode == "view"


def test_a_name_another_company_has_is_refused(qt_app, messages, row, second):
    service = FakeService(row, second)
    screen = CompanyInfoScreen(service)
    screen.new_record()
    screen.name_edit.setText("شركة النيل")
    screen.save_record()
    assert service.saved == [] and screen.mode == "new"
    assert messages[-1][0] == "warning"


def test_cancel_a_new_company_goes_back_to_the_open_one(qt_app, messages, row, second):
    screen = CompanyInfoScreen(FakeService(row, second))
    screen.navigate("next")
    screen.new_record()
    screen.cancel_edit()
    assert screen.current_id == 2 and screen.name_edit.text() == "شركة النيل"


def test_edit_and_save_sends_the_fields_the_flag_and_the_logo(qt_app, messages, row):
    service = FakeService(row)
    screen = CompanyInfoScreen(service)
    screen.edit_record()
    assert screen.mode == "edit" and not screen.name_edit.isReadOnly()
    screen.name_edit.setText("  اسم جديد  ")
    assert screen.hero_name.text() == "اسم جديد"  # the strip follows the typing
    screen.save_record()
    values, logo, mime, company_id = service.saved[-1]
    assert company_id == 1 and values["company_name"] == "اسم جديد"
    assert logo == row["logo"] and mime == "image/png"
    assert screen.updated_label.text().startswith("آخر تعديل:")


def test_navigation_and_lookup(qt_app, messages, row, second, monkeypatch):
    screen = CompanyInfoScreen(FakeService(row, second, {**second, "company_name": "شركة الدلتا"}))
    assert not screen.nav_buttons["prev"].isEnabled() and screen.nav_buttons["next"].isEnabled()
    screen.navigate("last")
    assert screen.name_edit.text() == "شركة الدلتا" and not screen.nav_buttons["next"].isEnabled()
    screen.navigate("prev")
    assert screen.current_id == 2
    screen.navigate("first")
    assert screen.current_id == 1

    class PickSecond:
        def __init__(self, rows, parent=None):
            self.selected = rows[1]

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(screen_module, "CompanyInfoListDialog", PickSecond)
    screen.open_lookup()
    assert screen.current_id == 2
    screen.edit_record()
    screen.open_lookup()  # refused while editing
    assert screen.current_id == 2 and messages[-1][0] == "information"


def test_delete_opens_the_next_company(qt_app, messages, row, second):
    service = FakeService(row, second)
    screen = CompanyInfoScreen(service)
    screen.delete_record()
    assert service.deleted == [1]
    assert screen.current_id == 2 and screen.position_label.text() == "شركة 1 من 1"
    screen.delete_record()
    assert screen.current_id is None and "اضغط «جديد»" in screen.hero_name.text()


def test_logo_is_picked_from_a_file_and_saved_as_bytes(qt_app, messages, row, tmp_path, monkeypatch):
    service = FakeService(row)
    screen = CompanyInfoScreen(service)
    new_logo = _png("#D9A54A")
    path = tmp_path / "new.png"
    path.write_bytes(new_logo)
    monkeypatch.setattr(screen_module.QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    screen.choose_logo()  # ignored outside «تعديل»
    assert screen._logo == row["logo"]
    screen.edit_record()
    screen.choose_logo()
    screen.save_record()
    assert service.saved[-1][1:3] == (new_logo, "image/png")


def test_a_file_that_is_not_an_image_is_refused(qt_app, messages, row, tmp_path, monkeypatch):
    screen = CompanyInfoScreen(FakeService(row))
    path = tmp_path / "fake.png"
    path.write_bytes(b"not an image")
    monkeypatch.setattr(screen_module.QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    screen.edit_record()
    screen.choose_logo()
    assert screen._logo == row["logo"]
    assert messages[-1][0] == "warning"


def test_remove_then_cancel_puts_the_logo_back(qt_app, messages, row):
    service = FakeService(row)
    screen = CompanyInfoScreen(service)
    screen.edit_record()
    screen.name_edit.setText("اسم مؤقت")
    screen.remove_logo()
    assert screen._logo is None and screen.logo_preview.text() == "لا يوجد لوجو"
    screen.cancel_edit()
    assert screen._logo == row["logo"] and screen.name_edit.text() == row["company_name"]
    assert service.saved == []


def test_remove_then_save_clears_the_logo(qt_app, messages, row):
    service = FakeService(row)
    screen = CompanyInfoScreen(service)
    screen.edit_record()
    screen.remove_logo()
    screen.save_record()
    assert service.saved[-1][1:3] == (None, None)


def test_a_blank_name_is_refused_and_the_edit_stays_open(qt_app, messages, row):
    service = FakeService(row)
    screen = CompanyInfoScreen(service)
    screen.edit_record()
    screen.name_edit.setText("   ")
    screen.save_record()
    assert service.saved == [] and screen.mode == "edit"
    assert messages[-1] == ("warning", "اكتب اسم الشركة.")


def test_reload_waits_for_the_edit_to_end(qt_app, messages, row):
    service = FakeService(row)
    screen = CompanyInfoScreen(service)
    service.companies[1]["company_name"] = "اتغيّر من جهاز تاني"
    screen.edit_record()
    screen.reload_lists()
    assert screen.name_edit.text() == row["company_name"]
    screen.cancel_edit()
    screen.reload_lists()
    assert screen.name_edit.text() == "اتغيّر من جهاز تاني"


def test_permissions_turn_the_buttons_off(qt_app, messages, row, monkeypatch):
    monkeypatch.setattr(screen_module.SESSION, "can", lambda code: code.endswith(".view"))
    screen = CompanyInfoScreen(FakeService(row))
    for button in (screen.new_button, screen.edit_button, screen.delete_button):
        assert not button.isEnabled()
    screen.edit_record()
    screen.new_record()
    assert screen.mode == "view"


def test_every_field_fits_without_vertical_scrolling(qt_app, messages, row):
    """The user's screen is about 1700×900; the window opens maximized."""
    screen = CompanyInfoScreen(FakeService(row))
    assert screen.minimumSizeHint().height() <= 830
