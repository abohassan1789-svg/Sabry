"""Data for شاشة بيانات الشركة: the ``company_info`` table.

The companies the app prints for: name, tax registration number, address (with
«يظهر في الطباعة») and logo. More than one company is allowed; which one a
printout uses is decided later. The logo is kept inside the database as bytes
plus its mime type, never as a file path, so every PC prints the same logo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.database.db import Database

NAME_MAX = 200
TAX_MAX = 50
ADDRESS_MAX = 300

# The image types the logo accepts, by file extension.
LOGO_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}
LOGO_MAX_BYTES = 5 * 1024 * 1024  # 5 MB — plenty for a print-quality logo.
LOGO_FILE_FILTER = "الصور (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"

_COLUMNS = ("company_name", "tax_registration_no", "address", "show_address_in_print",
            "logo", "logo_mime", "updated_by")


class CompanyInfoError(ValueError):
    """A message for the user: the data cannot be saved as it is."""


def clean(data: dict[str, Any]) -> dict[str, Any]:
    """Trim the texts and check them; blank optional texts become ``None``."""
    name = str(data.get("company_name") or "").strip()
    tax = str(data.get("tax_registration_no") or "").strip()
    address = str(data.get("address") or "").strip()
    if not name:
        raise CompanyInfoError("اكتب اسم الشركة.")
    if len(name) > NAME_MAX:
        raise CompanyInfoError(f"اسم الشركة أطول من {NAME_MAX} حرف.")
    if len(tax) > TAX_MAX:
        raise CompanyInfoError(f"رقم السجل الضريبي أطول من {TAX_MAX} حرف.")
    if len(address) > ADDRESS_MAX:
        raise CompanyInfoError(f"العنوان أطول من {ADDRESS_MAX} حرف.")
    return {
        "company_name": name,
        "tax_registration_no": tax or None,
        "address": address or None,
        "show_address_in_print": bool(data.get("show_address_in_print", True)),
    }


def read_logo_file(path: str | Path) -> tuple[bytes, str]:
    """The bytes and mime type of an image file the user picked for the logo.

    Checks the extension, that the file is readable and not empty, and the
    size. Whether the bytes really are an image is for the screen to check (it
    needs Qt to decode them).
    """
    file = Path(path)
    mime = LOGO_MIME_BY_EXT.get(file.suffix.lower())
    if mime is None:
        raise CompanyInfoError("اختار صورة PNG أو JPG.")
    try:
        raw = file.read_bytes()
    except OSError as exc:
        raise CompanyInfoError(f"تعذّر قراءة الملف: {exc}") from exc
    if not raw:
        raise CompanyInfoError("الملف المختار فاضي.")
    if len(raw) > LOGO_MAX_BYTES:
        raise CompanyInfoError("حجم الصورة أكبر من 5 ميجابايت.")
    return raw, mime


class CompanyInfoService:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()

    def list_rows(self) -> list[dict[str, Any]]:
        """Every company, without the logo bytes, in the order they were added."""
        return self._db.fetch_all(
            "SELECT company_info_id, company_name, tax_registration_no, address "
            "FROM company_info ORDER BY company_info_id"
        )

    def get(self, company_id: Any) -> dict[str, Any] | None:
        """One company, ``logo`` as ``bytes`` (or ``None``)."""
        row = self._db.fetch_one(
            "SELECT company_info_id, company_name, tax_registration_no, address, "
            "show_address_in_print, logo, logo_mime, updated_at "
            "FROM company_info WHERE company_info_id = %s",
            [company_id],
        )
        if row and row.get("logo") is not None:
            row["logo"] = bytes(row["logo"])
        return row

    def name_taken(self, name: str, except_id: Any = None) -> bool:
        """True if another company already has *name* (trimmed, any case)."""
        row = self._db.fetch_one(
            "SELECT company_info_id FROM company_info "
            "WHERE upper(btrim(company_name)) = upper(btrim(%s)) "
            "AND (%s::integer IS NULL OR company_info_id <> %s::integer) LIMIT 1",
            [name, except_id, except_id],
        )
        return row is not None

    def save(self, data: dict[str, Any], logo: bytes | None, logo_mime: str | None,
             company_id: Any = None, user_id: Any = None) -> Any:
        """Insert (``company_id`` None) or update one company; returns its id.

        *logo* ``None`` means the company has no logo; an old one is removed.
        """
        values = clean(data)
        if self.name_taken(values["company_name"], company_id):
            raise CompanyInfoError(f"في شركة تانية اسمها «{values['company_name']}».")
        values["logo"] = logo or None
        values["logo_mime"] = (logo_mime or "image/png") if logo else None
        values["updated_by"] = user_id
        params = [values[name] for name in _COLUMNS]
        if company_id is None:
            row = self._db.fetch_one(
                f"INSERT INTO company_info ({', '.join(_COLUMNS)}) "
                f"VALUES ({', '.join(['%s'] * len(_COLUMNS))}) RETURNING company_info_id",
                params,
            )
            return row["company_info_id"]
        self._db.execute(
            f"UPDATE company_info SET {', '.join(f'{name} = %s' for name in _COLUMNS)} "
            "WHERE company_info_id = %s",
            [*params, company_id],
        )
        return company_id

    def delete(self, company_id: Any) -> None:
        self._db.execute("DELETE FROM company_info WHERE company_info_id = %s", [company_id])
