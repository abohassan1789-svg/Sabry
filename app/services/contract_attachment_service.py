"""مرفقات عقود المقاولين: pictures and PDF files kept inside the database.

The user asked (2026-10-05) for attachments on a contract, pictures apart from
PDF files, saved in the database rather than as paths, and for each one to be
opened inside the program or downloaded to the PC.

A file is saved the moment it is attached; there is no «حفظ» step for it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.database.db import Database

IMAGE = "image"
PDF = "pdf"
KINDS = (IMAGE, PDF)

IMAGE_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}
PDF_MIME = "application/pdf"
MAX_BYTES = 25 * 1024 * 1024  # 25 MB a file — room for a scanned contract.
NAME_MAX = 255

FILE_FILTERS = {
    IMAGE: "الصور (*.png *.jpg *.jpeg *.gif *.bmp *.webp)",
    PDF: "ملفات PDF (*.pdf)",
}


class AttachmentError(ValueError):
    """A message for the user: the file cannot be attached as it is."""


def read_attachment(path: str | Path, kind: str) -> tuple[str, str, bytes]:
    """(file name, mime type, bytes) of a file the user picked as *kind*.

    Checks the extension, that the file is readable and not empty, the size,
    and that a PDF starts like one. Whether a picture really decodes is for
    the screen to check (it needs Qt).
    """
    file = Path(path)
    ext = file.suffix.lower()
    if kind == IMAGE:
        mime = IMAGE_MIME_BY_EXT.get(ext)
        if mime is None:
            raise AttachmentError(f"«{file.name}» مش صورة. اختار PNG أو JPG.")
    elif kind == PDF:
        if ext != ".pdf":
            raise AttachmentError(f"«{file.name}» مش ملف PDF.")
        mime = PDF_MIME
    else:
        raise ValueError(f"unknown attachment kind: {kind!r}")
    try:
        data = file.read_bytes()
    except OSError as exc:
        raise AttachmentError(f"تعذّر قراءة «{file.name}»: {exc}") from exc
    if not data:
        raise AttachmentError(f"الملف «{file.name}» فاضي.")
    if len(data) > MAX_BYTES:
        raise AttachmentError(f"«{file.name}» أكبر من {MAX_BYTES // (1024 * 1024)} ميجا.")
    if kind == PDF and not data.lstrip()[:5].startswith(b"%PDF"):
        raise AttachmentError(f"«{file.name}» مش ملف PDF سليم.")
    return file.name[:NAME_MAX], mime, data


def size_text(size: Any) -> str:
    """«850 ك.ب» / «2.4 ميجا» for a size in bytes."""
    size = int(size or 0)
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} ميجا"
    return f"{max(1, round(size / 1024))} ك.ب"


class ContractAttachmentService:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()

    def list(self, contract_id: Any, kind: str) -> list[dict[str, Any]]:
        """The contract's attachments of *kind*, oldest first, without the file bytes.

        ``thumbnail`` (a picture's small PNG) comes back as ``bytes`` or ``None``.
        """
        rows = self._db.fetch_all(
            "SELECT attachment_id, kind, file_name, mime_type, file_size, thumbnail, uploaded_at "
            "FROM contractor_contract_attachments WHERE contract_id = %s AND kind = %s "
            "ORDER BY attachment_id",
            [contract_id, kind],
        )
        for row in rows:
            if row.get("thumbnail") is not None:
                row["thumbnail"] = bytes(row["thumbnail"])
        return rows

    def counts(self, contract_id: Any) -> dict[str, int]:
        """How many pictures and PDF files the contract has: ``{"image": n, "pdf": n}``."""
        rows = self._db.fetch_all(
            "SELECT kind, count(*) AS n FROM contractor_contract_attachments "
            "WHERE contract_id = %s GROUP BY kind",
            [contract_id],
        )
        counts = dict.fromkeys(KINDS, 0)
        for row in rows:
            counts[row["kind"]] = int(row["n"])
        return counts

    def data(self, attachment_id: Any) -> dict[str, Any] | None:
        """One attachment with its bytes: file_name, mime_type, data."""
        row = self._db.fetch_one(
            "SELECT attachment_id, kind, file_name, mime_type, data "
            "FROM contractor_contract_attachments WHERE attachment_id = %s",
            [attachment_id],
        )
        if row and row.get("data") is not None:
            row["data"] = bytes(row["data"])
        return row

    def add(self, contract_id: Any, kind: str, file_name: str, mime_type: str, data: bytes,
            thumbnail: bytes | None = None, user_id: Any = None) -> Any:
        """Save one file on the contract; returns its id."""
        if kind not in KINDS:
            raise ValueError(f"unknown attachment kind: {kind!r}")
        if not data:
            raise AttachmentError("الملف فاضي.")
        row = self._db.fetch_one(
            "INSERT INTO contractor_contract_attachments "
            "(contract_id, kind, file_name, mime_type, file_size, data, thumbnail, uploaded_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING attachment_id",
            [contract_id, kind, file_name[:NAME_MAX], mime_type, len(data), data, thumbnail, user_id],
        )
        return row["attachment_id"]

    def delete(self, attachment_id: Any) -> None:
        self._db.execute(
            "DELETE FROM contractor_contract_attachments WHERE attachment_id = %s", [attachment_id]
        )
