"""Tests for مرفقات عقود المقاولين (headless Qt, no database).

What the user asked for (2026-10-05):

* Pictures and PDF files attached to a contract, each kind on its own.
* Saved in the database (bytes), not as a path.
* Each one opens inside the program and can be downloaded to the PC.
"""

from __future__ import annotations

import datetime
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtWidgets import QApplication

from app.services import contract_attachment_service as service_module
from app.services.contract_attachment_service import (
    IMAGE,
    PDF,
    AttachmentError,
    ContractAttachmentService,
    read_attachment,
    size_text,
)
from app.ui.dialogs import contract_attachments_dialog as dialog_module
from app.ui.dialogs.contract_attachments_dialog import (
    ContractAttachmentsDialog,
    ImageViewerDialog,
    PdfViewerDialog,
    make_thumbnail,
)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _png(color: str = "#0E5A66", size: int = 400) -> bytes:
    image = QImage(size, size // 2, QImage.Format_RGB32)
    image.fill(QColor(color))
    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(raw)


def _pdf(tmp_path, pages: int = 2) -> bytes:
    path = tmp_path / "made.pdf"
    writer = QPdfWriter(str(path))
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF()))
    painter = QPainter(writer)
    for page in range(pages):
        if page:
            writer.newPage()
        painter.drawText(200, 200, f"page {page + 1}")
    painter.end()
    return path.read_bytes()


# --- the service, without a database -------------------------------------------------

def test_read_attachment_checks_kind_and_content(tmp_path, monkeypatch):
    picture = tmp_path / "صورة العقد.JPG"
    picture.write_bytes(b"\xff\xd8 bytes")
    assert read_attachment(picture, IMAGE) == ("صورة العقد.JPG", "image/jpeg", b"\xff\xd8 bytes")

    document = tmp_path / "contract.pdf"
    document.write_bytes(b"%PDF-1.7 rest")
    assert read_attachment(document, PDF) == ("contract.pdf", "application/pdf", b"%PDF-1.7 rest")

    with pytest.raises(AttachmentError):
        read_attachment(document, IMAGE)        # a PDF in the pictures tab
    with pytest.raises(AttachmentError):
        read_attachment(picture, PDF)           # a picture in the PDF tab
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"not a pdf")
    with pytest.raises(AttachmentError, match="سليم"):
        read_attachment(fake, PDF)
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    with pytest.raises(AttachmentError):
        read_attachment(empty, IMAGE)
    with pytest.raises(AttachmentError):
        read_attachment(tmp_path / "missing.png", IMAGE)
    monkeypatch.setattr(service_module, "MAX_BYTES", 4)
    with pytest.raises(AttachmentError):
        read_attachment(picture, IMAGE)


def test_size_text():
    assert size_text(300) == "1 ك.ب"
    assert size_text(850 * 1024) == "850 ك.ب"
    assert size_text(int(2.4 * 1024 * 1024)) == "2.4 ميجا"


class FakeDb:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries: list[tuple[str, list]] = []

    def fetch_all(self, query, params=None):
        self.queries.append((query, list(params or [])))
        return [dict(row) for row in self.rows]

    def fetch_one(self, query, params=None):
        self.queries.append((query, list(params or [])))
        if query.startswith("INSERT"):
            return {"attachment_id": 42}
        return dict(self.rows[0]) if self.rows else None

    def execute(self, query, params=None):
        self.queries.append((query, list(params or [])))


def test_service_add_stores_the_bytes_and_their_size():
    db = FakeDb()
    new_id = ContractAttachmentService(db).add(7, PDF, "عقد.pdf", "application/pdf", b"%PDF-data", None, 3)
    query, params = db.queries[-1]
    assert new_id == 42 and query.startswith("INSERT INTO contractor_contract_attachments")
    assert params == [7, "pdf", "عقد.pdf", "application/pdf", 9, b"%PDF-data", None, 3]
    with pytest.raises(ValueError):
        ContractAttachmentService(db).add(7, "doc", "x", "x", b"x")


def test_service_counts_both_kinds():
    db = FakeDb([{"kind": "image", "n": 3}])
    assert ContractAttachmentService(db).counts(7) == {"image": 3, "pdf": 0}


def test_service_returns_bytes_not_memoryviews():
    db = FakeDb([{"attachment_id": 1, "kind": "image", "file_name": "a.png", "mime_type": "image/png",
                  "file_size": 3, "thumbnail": memoryview(b"TMB"), "data": memoryview(b"IMG"),
                  "uploaded_at": None}])
    service = ContractAttachmentService(db)
    assert service.list(7, IMAGE)[0]["thumbnail"] == b"TMB"
    assert service.data(1)["data"] == b"IMG"
    selected = db.queries[0][0].split("FROM")[0]
    assert " data" not in selected  # the list leaves the file bytes in the database


# --- the window ----------------------------------------------------------------------

class FakeService:
    def __init__(self):
        self.files: dict[int, dict] = {}
        self.next_id = 1

    def list(self, contract_id, kind):
        return [{k: v for k, v in row.items() if k != "data"}
                for row in self.files.values() if row["contract_id"] == contract_id and row["kind"] == kind]

    def data(self, attachment_id):
        row = self.files.get(attachment_id)
        return dict(row) if row else None

    def add(self, contract_id, kind, file_name, mime_type, data, thumbnail=None, user_id=None):
        attachment_id, self.next_id = self.next_id, self.next_id + 1
        self.files[attachment_id] = {
            "attachment_id": attachment_id, "contract_id": contract_id, "kind": kind,
            "file_name": file_name, "mime_type": mime_type, "file_size": len(data), "data": data,
            "thumbnail": thumbnail, "uploaded_at": datetime.datetime(2026, 10, 5, tzinfo=datetime.timezone.utc)}
        return attachment_id

    def delete(self, attachment_id):
        self.files.pop(attachment_id)


@pytest.fixture
def messages(monkeypatch):
    shown: list[tuple[str, str]] = []
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(dialog_module.QMessageBox, name,
                            lambda _p, _t, text, *a, _n=name, **k: shown.append((_n, text)))
    monkeypatch.setattr(dialog_module.QMessageBox, "question", lambda *a, **k: dialog_module.QMessageBox.Yes)
    return shown


def _pick(monkeypatch, *paths):
    monkeypatch.setattr(dialog_module.QFileDialog, "getOpenFileNames",
                        lambda *a, **k: ([str(p) for p in paths], ""))


def _select_first(dialog):
    widget = dialog.lists[dialog.kind]
    widget.setCurrentRow(0)
    widget.item(0).setSelected(True)


def test_pictures_and_pdfs_are_attached_in_their_own_tabs(qt_app, messages, monkeypatch, tmp_path):
    service = FakeService()
    dialog = ContractAttachmentsDialog(service, 7, "A-H/CT-1001", True)
    assert dialog.tabs.tabText(0).endswith("(0)") and dialog.attach_button.text() == "إرفاق صور"

    first, second = tmp_path / "front.png", tmp_path / "back.png"
    first.write_bytes(_png())
    second.write_bytes(_png("#D9A54A"))
    _pick(monkeypatch, first, second)
    dialog.attach()
    assert [row["file_name"] for row in service.files.values()] == ["front.png", "back.png"]
    assert all(row["kind"] == IMAGE and row["thumbnail"] for row in service.files.values())
    assert dialog.tabs.tabText(0).endswith("(2)") and dialog.changed

    dialog.tabs.setCurrentIndex(1)
    assert dialog.attach_button.text() == "إرفاق ملفات PDF"
    document = tmp_path / "contract.pdf"
    document.write_bytes(_pdf(tmp_path))
    _pick(monkeypatch, document)
    dialog.attach()
    assert dialog.tabs.tabText(1).endswith("(1)")
    assert service.files[3]["kind"] == PDF and service.files[3]["data"] == document.read_bytes()


def test_bad_files_are_reported_and_the_good_ones_kept(qt_app, messages, monkeypatch, tmp_path):
    service = FakeService()
    dialog = ContractAttachmentsDialog(service, 7, "A-H/CT-1001", True)
    good, broken, wrong = tmp_path / "ok.png", tmp_path / "broken.png", tmp_path / "doc.pdf"
    good.write_bytes(_png())
    broken.write_bytes(b"not a picture")
    wrong.write_bytes(b"%PDF-1.4")
    _pick(monkeypatch, good, broken, wrong)
    dialog.attach()
    assert [row["file_name"] for row in service.files.values()] == ["ok.png"]
    kind, text = messages[-1]
    assert kind == "warning" and "broken.png" in text and "doc.pdf" in text


def test_download_writes_the_stored_bytes_to_the_pc(qt_app, messages, monkeypatch, tmp_path):
    service = FakeService()
    service.add(7, PDF, "عقد.pdf", "application/pdf", b"%PDF-stored")
    dialog = ContractAttachmentsDialog(service, 7, "A-H/CT-1001", False)
    dialog.tabs.setCurrentIndex(1)
    _select_first(dialog)
    target = tmp_path / "out" / "saved.pdf"
    target.parent.mkdir()
    monkeypatch.setattr(dialog_module.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    dialog.download_selected()
    assert target.read_bytes() == b"%PDF-stored"
    assert messages[-1][0] == "information"


def test_without_edit_rights_files_open_but_cannot_change(qt_app, messages, tmp_path):
    service = FakeService()
    service.add(7, IMAGE, "a.png", "image/png", _png(), make_thumbnail(_png()))
    dialog = ContractAttachmentsDialog(service, 7, "A-H/CT-1001", False)
    _select_first(dialog)
    assert not dialog.attach_button.isEnabled() and not dialog.delete_button.isEnabled()
    assert dialog.open_button.isEnabled() and dialog.download_button.isEnabled()
    dialog.delete_selected()
    assert len(service.files) == 1


def test_delete_removes_the_attachment(qt_app, messages):
    service = FakeService()
    service.add(7, IMAGE, "a.png", "image/png", _png(), make_thumbnail(_png()))
    service.add(8, IMAGE, "other contract.png", "image/png", _png())
    dialog = ContractAttachmentsDialog(service, 7, "A-H/CT-1001", True)
    _select_first(dialog)
    dialog.delete_selected()
    assert list(service.files) == [2] and dialog.tabs.tabText(0).endswith("(0)")


def test_open_shows_the_file_inside_the_program(qt_app, messages, monkeypatch, tmp_path):
    service = FakeService()
    service.add(7, IMAGE, "a.png", "image/png", _png())
    service.add(7, PDF, "b.pdf", "application/pdf", _pdf(tmp_path, pages=3))
    shown = []
    monkeypatch.setattr(ImageViewerDialog, "exec", lambda self: shown.append(("image", self.pixmap.width())))
    monkeypatch.setattr(PdfViewerDialog, "exec", lambda self: shown.append(("pdf", self.document.pageCount())))
    dialog = ContractAttachmentsDialog(service, 7, "A-H/CT-1001", False)
    _select_first(dialog)
    dialog.open_selected()
    dialog.tabs.setCurrentIndex(1)
    _select_first(dialog)
    dialog.open_selected()
    assert shown == [("image", 400), ("pdf", 3)]


def test_a_broken_pdf_is_not_shown(qt_app, messages, monkeypatch):
    service = FakeService()
    service.add(7, PDF, "bad.pdf", "application/pdf", b"%PDF-garbage")
    monkeypatch.setattr(PdfViewerDialog, "exec", lambda self: pytest.fail("opened a broken PDF"))
    dialog = ContractAttachmentsDialog(service, 7, "A-H/CT-1001", False)
    dialog.tabs.setCurrentIndex(1)
    _select_first(dialog)
    dialog.open_selected()
    assert messages[-1][0] == "warning"


def test_image_viewer_zooms(qt_app):
    viewer = ImageViewerDialog("a.png", _png(size=800))
    viewer.resize(500, 400)
    viewer.fit()
    fitted = viewer.scale
    assert fitted < 1
    viewer.zoom(1.25)
    assert viewer.scale == pytest.approx(fitted * 1.25) and not viewer.fitting
