"""Companies module screen (إدارة الشركات).

UI only: it reuses :class:`BaseCrudScreen` bound to the ``companies`` table spec,
so it inherits the exact same layout, colours, borders, toolbar and CRUD logic as
the products / customers screens (same design family). Business/database logic
stays in ``ReviewDataService`` + ``TABLE_SPECS['companies']``.

Two companies-specific touches are layered on top of the generic screen:

* ``السجل التجاري`` (commercial registration) and ``الرقم الضريبي`` (VAT number)
  are UNIQUE. Duplicates are rejected *before* the save with a clear Arabic
  message, instead of surfacing the raw database UNIQUE-index error. The database
  UNIQUE indexes remain the final guard for the (rare) concurrent race.

* Two image toolbar buttons — ``شعار الشركة`` (company logo) and ``ختم الشركة``
  (company stamp) — each open the same small dialog that stores the image
  **inside the database** (raw bytes, never a path) and previews it. Each printed
  document then renders the logo of the exact company it is printed for; the
  stamp is drawn in the invoice footer only when the «إظهار الختم» box on the
  sales-invoice screen is ticked. Both images are handled outside the generic
  spec-driven form on purpose, so the binary columns never flow through the Excel
  import/export or the text-only field editors.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.review_data_service import ReviewDataService, TABLE_SPECS
from app.ui.common.theme import _button_style
from app.ui.screens.base_crud_screen import BaseCrudScreen

# Accepted logo image types mapped to their MIME (stored alongside the bytes so
# the print layer can build a correct ``data:`` URI).
_LOGO_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}
_LOGO_MAX_BYTES = 5 * 1024 * 1024  # 5 MB — plenty for a print-quality logo.


@dataclass(frozen=True)
class CompanyImageAsset:
    """The captions + service calls that make :class:`CompanyImageDialog` manage
    one particular embedded image (the logo or the stamp).

    ``load``/``save`` are bound to the matching ``ReviewDataService`` pair, and
    ``data_key``/``mime_key`` name the columns the loader returns.
    """

    title: str            # window title + heading fallback, e.g. "شعار الشركة"
    noun: str             # bare noun for messages, e.g. "الشعار" / "الختم"
    choose_title: str     # file-picker title, e.g. "اختيار شعار الشركة"
    saved_message: str    # confirmation toast, e.g. "تم حفظ شعار الشركة."
    data_key: str         # "logo" / "stamp"
    mime_key: str         # "logo_mime" / "stamp_mime"
    load: Callable[[ReviewDataService, Any], dict | None]
    save: Callable[[ReviewDataService, Any, bytes | None, str | None], None]


class CompanyImageDialog(QDialog):
    """Preview / upload / remove one embedded company image (logo or stamp).

    Both images share this dialog: they differ only in their Arabic captions and
    in which ``ReviewDataService`` getter/setter they call — all carried by the
    ``asset`` (:class:`CompanyImageAsset`).
    """

    def __init__(
        self,
        service: ReviewDataService,
        company_id: Any,
        company_name: str,
        asset: CompanyImageAsset,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.company_id = company_id
        self.asset = asset
        self._data: bytes | None = None
        self._mime: str | None = None
        self._changed = False

        self.setWindowTitle(asset.title)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setModal(True)
        self.resize(360, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        heading = QLabel(company_name or asset.title)
        heading.setAlignment(Qt.AlignCenter)
        heading.setStyleSheet("font-size:15px; font-weight:900; color:#111827;")
        root.addWidget(heading)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedHeight(240)
        self.preview.setStyleSheet(
            "background:#F8FAFC; border:1px dashed #CBD5E1; border-radius:8px; "
            "color:#94A3B8; font-weight:700;"
        )
        root.addWidget(self.preview)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.choose_button = QPushButton("تحميل صورة")
        self.choose_button.setFixedHeight(38)
        self.choose_button.setStyleSheet(_button_style("#2563EB", "#1D4ED8"))
        self.choose_button.clicked.connect(self._choose)
        self.remove_button = QPushButton(f"إزالة {asset.noun}")
        self.remove_button.setFixedHeight(38)
        self.remove_button.setStyleSheet(_button_style("#DC2626", "#B91C1C"))
        self.remove_button.clicked.connect(self._remove)
        buttons.addWidget(self.choose_button)
        buttons.addWidget(self.remove_button)
        root.addLayout(buttons)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.save_button = QPushButton("حفظ")
        self.save_button.setFixedHeight(38)
        self.save_button.setStyleSheet(_button_style("#1A7A3C", "#166534"))
        self.save_button.clicked.connect(self._save)
        close_button = QPushButton("إغلاق")
        close_button.setFixedHeight(38)
        close_button.setStyleSheet(
            "QPushButton { background:#FFFFFF;color:#374151;border:1px solid #D1D5DB;"
            "border-radius:6px;font-weight:800;padding:7px 12px; }"
            "QPushButton:hover { background:#F3F4F6; }"
        )
        close_button.clicked.connect(self.reject)
        actions.addWidget(self.save_button, 1)
        actions.addWidget(close_button, 1)
        root.addLayout(actions)

        self._load_current()

    def _load_current(self) -> None:
        row = None
        try:
            row = self.asset.load(self.service, self.company_id)
        except Exception:  # noqa: BLE001 - never block the dialog on a read error
            row = None
        if row and row.get(self.asset.data_key):
            self._data = bytes(row[self.asset.data_key])
            self._mime = row.get(self.asset.mime_key) or "image/png"
        else:
            self._data = None
            self._mime = None
        self._changed = False
        self._render_preview()

    def _render_preview(self) -> None:
        if not self._data:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(f"لا يوجد {self.asset.noun}")
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(self._data):
            self.preview.setPixmap(QPixmap())
            self.preview.setText("تعذّر عرض الصورة")
            return
        self.preview.setText("")
        self.preview.setPixmap(
            pixmap.scaled(
                self.preview.width() - 12,
                self.preview.height() - 12,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

    def _choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.asset.choose_title,
            "",
            "الصور (*.png *.jpg *.jpeg *.gif *.bmp *.webp)",
        )
        if not path:
            return
        ext = Path(path).suffix.lower()
        mime = _LOGO_MIME_BY_EXT.get(ext)
        if mime is None:
            QMessageBox.warning(self, "نوع غير مدعوم", "الرجاء اختيار صورة PNG أو JPG.")
            return
        try:
            raw = Path(path).read_bytes()
        except OSError as exc:
            QMessageBox.warning(self, "تعذّر قراءة الملف", str(exc))
            return
        if not raw:
            QMessageBox.warning(self, "ملف فارغ", "الملف المختار فارغ.")
            return
        if len(raw) > _LOGO_MAX_BYTES:
            QMessageBox.warning(
                self, "حجم كبير", "حجم الصورة يتجاوز الحد المسموح (5 ميجابايت)."
            )
            return
        probe = QPixmap()
        if not probe.loadFromData(raw):
            QMessageBox.warning(self, "صورة غير صالحة", "تعذّر قراءة الصورة المختارة.")
            return
        self._data = raw
        self._mime = mime
        self._changed = True
        self._render_preview()

    def _remove(self) -> None:
        if not self._data:
            return
        self._data = None
        self._mime = None
        self._changed = True
        self._render_preview()

    def _save(self) -> None:
        if not self._changed:
            self.accept()
            return
        try:
            self.asset.save(self.service, self.company_id, self._data, self._mime)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "تعذّر الحفظ", str(exc))
            return
        QMessageBox.information(self, "تم", self.asset.saved_message)
        self.accept()


class CompaniesScreen(BaseCrudScreen):
    SPEC_KEY = "companies"

    # Companies are searched by name, commercial registration, or VAT number.
    SEARCH_PLACEHOLDER = "البحث باسم الشركة أو السجل التجاري أو الرقم الضريبي"

    # Each field on its own line (single-column form), per the requested layout.
    FORM_COLUMNS = 1

    # Unique fields, with their Arabic labels and duplicate messages.
    _UNIQUE_FIELDS = (
        ("commercial_registration", "رقم السجل التجاري مستخدم من قبل لشركة أخرى."),
        ("vat_number", "الرقم الضريبي مستخدم من قبل لشركة أخرى."),
    )

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        super().__init__(service, TABLE_SPECS[self.SPEC_KEY], parent)

    # --- logo / stamp toolbar buttons --------------------------------------
    # Each button manages one embedded image of the selected company through the
    # shared CompanyImageDialog; the asset carries its captions + service calls.
    _LOGO_ASSET = CompanyImageAsset(
        title="شعار الشركة",
        noun="الشعار",
        choose_title="اختيار شعار الشركة",
        saved_message="تم حفظ شعار الشركة.",
        data_key="logo",
        mime_key="logo_mime",
        load=lambda svc, cid: svc.get_company_logo(cid),
        save=lambda svc, cid, data, mime: svc.set_company_logo(cid, data, mime),
    )
    _STAMP_ASSET = CompanyImageAsset(
        title="ختم الشركة",
        noun="الختم",
        choose_title="اختيار ختم الشركة",
        saved_message="تم حفظ ختم الشركة.",
        data_key="stamp",
        mime_key="stamp_mime",
        load=lambda svc, cid: svc.get_company_stamp(cid),
        save=lambda svc, cid, data, mime: svc.set_company_stamp(cid, data, mime),
    )

    def _install_extra_toolbar_buttons(self, layout) -> None:
        """Add "شعار الشركة" + "ختم الشركة" buttons for the selected company."""
        self.logo_button = QPushButton("شعار الشركة")
        self.logo_button.setFixedHeight(38)
        self.logo_button.setStyleSheet(_button_style("#0E7490", "#155E75"))
        self.logo_button.clicked.connect(self.open_logo_dialog)
        layout.addWidget(self.logo_button)

        self.stamp_button = QPushButton("ختم الشركة")
        self.stamp_button.setFixedHeight(38)
        self.stamp_button.setStyleSheet(_button_style("#7C3AED", "#6D28D9"))
        self.stamp_button.clicked.connect(self.open_stamp_dialog)
        layout.addWidget(self.stamp_button)

    def open_logo_dialog(self) -> None:
        self._open_asset_dialog(self._LOGO_ASSET)

    def open_stamp_dialog(self) -> None:
        self._open_asset_dialog(self._STAMP_ASSET)

    def _open_asset_dialog(self, asset: CompanyImageAsset) -> None:
        if self.current_id is None:
            QMessageBox.information(
                self,
                asset.title,
                f"اختر شركة من القائمة (أو احفظ الشركة الجديدة أولاً) ثم أضف {asset.noun}.",
            )
            return
        name_editor = self.inputs.get("name_ar")
        company_name = name_editor.text().strip() if name_editor is not None else ""
        dialog = CompanyImageDialog(
            self.service, self.current_id, company_name, asset, self
        )
        dialog.exec()

    # --- validation before save --------------------------------------------
    def save_record(self) -> None:  # type: ignore[override]
        # Pre-check the UNIQUE columns so the user gets a clear Arabic message
        # instead of a raw database error. On edit, ignore this same row.
        exclude_id = None if self.mode == "new" else self.current_id
        for name, message in self._UNIQUE_FIELDS:
            editor = self.inputs.get(name)
            if editor is None:
                continue
            value = self._editor_value(editor)
            try:
                if self.service.value_exists(self.spec, name, value, exclude_id=exclude_id):
                    QMessageBox.warning(self, "قيمة مكررة", message)
                    return
            except Exception:
                # If the pre-check itself fails (e.g. transient DB issue), fall
                # through: the UNIQUE index is still the final guard on save.
                pass
        # Required/empty fields are enforced by the generic ReviewDataService
        # (with Arabic messages); everything else — IDENTITY id, audit columns —
        # flows through the base save.
        super().save_record()
