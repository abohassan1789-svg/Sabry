"""نافذة مرفقات العقد — «المرفقات» on شاشة عقود المقاولين (2026-10-05).

Two tabs, as the user asked: الصور and ملفات PDF. Each file is saved in the
database the moment it is attached. A file can be:

* opened inside the program (a picture viewer, a PDF viewer),
* downloaded to the PC («تنزيل»),
* deleted, by whoever may edit the contract.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, QStandardPaths, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.security.session_context import SESSION
from app.services.contract_attachment_service import (
    FILE_FILTERS,
    IMAGE,
    PDF,
    AttachmentError,
    ContractAttachmentService,
    read_attachment,
    size_text,
)
from app.ui.common.theme import GREEN, _button_style

THUMB = 150


def make_thumbnail(data: bytes, size: int = 240) -> bytes | None:
    """A small PNG of a picture for the list, or None if it doesn't decode."""
    image = QImage()
    if not image.loadFromData(data):
        return None
    image = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(raw)


def save_to_pc(parent: QWidget, file_name: str, data: bytes) -> str | None:
    """Ask where to save *data* (offering the Downloads folder) and write it; the path or None."""
    folder = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or str(Path.home())
    suffix = Path(file_name).suffix.lower()
    filter_ = FILE_FILTERS[PDF] if suffix == ".pdf" else "كل الملفات (*.*)"
    path, _ = QFileDialog.getSaveFileName(parent, "تنزيل الملف", str(Path(folder) / file_name), filter_)
    if not path:
        return None
    try:
        Path(path).write_bytes(data)
    except OSError as exc:
        QMessageBox.critical(parent, "تعذّر التنزيل", str(exc))
        return None
    QMessageBox.information(parent, "تم التنزيل", f"اتحفظ الملف في:\n{path}")
    return path


def _toolbar_button(text: str, bg: str, hover: str, icon: QStyle.StandardPixmap | None = None,
                    owner: QWidget | None = None) -> QPushButton:
    button = QPushButton(text)
    button.setFixedHeight(38)
    button.setStyleSheet(_button_style(bg, hover))
    if icon is not None and owner is not None:
        button.setIcon(owner.style().standardIcon(icon))
    return button


class _ViewerBase(QDialog):
    """A maximized viewer with zoom buttons and «تنزيل»."""

    def __init__(self, file_name: str, data: bytes, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.file_name = file_name
        self.data = data
        self.setWindowTitle(file_name)
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1200, 820)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(7)
        title = QLabel(file_name)
        title.setStyleSheet(f"font-size:16px; font-weight:900; color:{GREEN};")
        bar.addWidget(title, 1)
        self.zoom_in_button = _toolbar_button("تكبير +", "#475569", "#334155")
        self.zoom_out_button = _toolbar_button("تصغير -", "#475569", "#334155")
        self.fit_button = _toolbar_button("ملء الشاشة", "#0E7490", "#155E75")
        self.download_button = _toolbar_button("تنزيل على الجهاز", "#2563EB", "#1D4ED8",
                                               QStyle.SP_DialogSaveButton, self)
        close_button = _toolbar_button("إغلاق", "#374151", "#1F2937")
        for button in (self.zoom_in_button, self.zoom_out_button, self.fit_button,
                       self.download_button, close_button):
            bar.addWidget(button)
        root.addLayout(bar)
        self.zoom_in_button.clicked.connect(lambda: self.zoom(1.25))
        self.zoom_out_button.clicked.connect(lambda: self.zoom(0.8))
        self.fit_button.clicked.connect(self.fit)
        self.download_button.clicked.connect(lambda: save_to_pc(self, self.file_name, self.data))
        close_button.clicked.connect(self.accept)

    def zoom(self, factor: float) -> None:
        raise NotImplementedError

    def fit(self) -> None:
        raise NotImplementedError


class ImageViewerDialog(_ViewerBase):
    def __init__(self, file_name: str, data: bytes, parent: QWidget | None = None) -> None:
        super().__init__(file_name, data, parent)
        self.pixmap = QPixmap()
        self.pixmap.loadFromData(data)
        self.scale = 1.0
        self.fitting = True
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.scroll = QScrollArea()
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.setStyleSheet("QScrollArea { background:#1F2937; border:none; border-radius:8px; }")
        self.label.setStyleSheet("background:transparent;")
        self.scroll.setWidget(self.label)
        self.layout().addWidget(self.scroll, 1)
        if self.pixmap.isNull():
            self.label.setText("تعذّر عرض الصورة")
            self.label.setStyleSheet("color:#FFFFFF; font-size:16px; font-weight:800;")

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        if self.fitting:
            self.fit()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        if self.fitting:
            self.fit()

    def _render(self) -> None:
        if self.pixmap.isNull():
            return
        size = self.pixmap.size() * self.scale
        self.label.setPixmap(self.pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.label.resize(self.label.pixmap().size())

    def fit(self) -> None:
        if self.pixmap.isNull():
            return
        self.fitting = True
        area = self.scroll.viewport().size()
        self.scale = min(1.0, (area.width() - 4) / self.pixmap.width(), (area.height() - 4) / self.pixmap.height())
        self.scale = max(self.scale, 0.05)
        self._render()

    def zoom(self, factor: float) -> None:
        self.fitting = False
        self.scale = max(0.05, min(8.0, self.scale * factor))
        self._render()


class PdfViewerDialog(_ViewerBase):
    def __init__(self, file_name: str, data: bytes, parent: QWidget | None = None) -> None:
        super().__init__(file_name, data, parent)
        # The buffer must outlive the document reading from it.
        self._bytes = QByteArray(data)
        self._buffer = QBuffer(self._bytes, self)
        self._buffer.open(QIODevice.ReadOnly)
        self.document = QPdfDocument(self)
        self.document.load(self._buffer)
        self.view = QPdfView(self)
        self.view.setLayoutDirection(Qt.LeftToRight)
        self.view.setDocument(self.document)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.view.setStyleSheet("background:#4B5563;")
        self.pages_label = QLabel(f"{self.document.pageCount()} صفحة")
        self.pages_label.setStyleSheet("color:#475569; font-weight:800;")
        self.layout().itemAt(0).layout().insertWidget(1, self.pages_label)
        self.layout().addWidget(self.view, 1)

    @property
    def loaded(self) -> bool:
        return self.document.status() == QPdfDocument.Status.Ready

    def fit(self) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    def zoom(self, factor: float) -> None:
        current = self.view.zoomFactor()
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(max(0.1, min(8.0, current * factor)))


class ContractAttachmentsDialog(QDialog):
    """The contract's pictures and PDF files, each kind in its own tab."""

    def __init__(self, service: ContractAttachmentService, contract_id: Any, contract_no: str,
                 can_modify: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.contract_id = contract_id
        self.can_modify = can_modify
        self.changed = False
        self.rows: dict[str, list[dict[str, Any]]] = {IMAGE: [], PDF: []}

        self.setWindowTitle(f"مرفقات العقد {contract_no}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(980, 640)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        heading = QLabel(f"مرفقات العقد «{contract_no}»")
        heading.setStyleSheet(f"font-size:19px; font-weight:900; color:{GREEN};")
        note = QLabel("الملفات بتتحفظ جوه قاعدة البيانات أول ما ترفقها.")
        note.setStyleSheet("color:#64748B; font-weight:700;")
        root.addWidget(heading)
        root.addWidget(note)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border:1px solid #E2E8F0; border-radius:8px; background:#FFFFFF; }"
            "QTabBar::tab { background:#FFFFFF; color:#334155; border:1px solid #D9E2EC; border-bottom:none; "
            "border-top-left-radius:8px; border-top-right-radius:8px; padding:9px 22px; margin-left:4px; "
            "font-size:14px; font-weight:900; }"
            f"QTabBar::tab:selected {{ background:{GREEN}; color:#FFFFFF; border-color:{GREEN}; }}"
        )
        self.lists = {IMAGE: self._build_image_list(), PDF: self._build_pdf_list()}
        self.tabs.addTab(self.lists[IMAGE], self.style().standardIcon(QStyle.SP_DesktopIcon), "")
        self.tabs.addTab(self.lists[PDF], self.style().standardIcon(QStyle.SP_FileIcon), "")
        root.addWidget(self.tabs, 1)

        bar = QHBoxLayout()
        bar.setSpacing(7)
        self.attach_button = _toolbar_button("", "#1A7A3C", "#166534", QStyle.SP_FileDialogNewFolder, self)
        self.open_button = _toolbar_button("فتح", "#0E7490", "#155E75", QStyle.SP_FileDialogContentsView, self)
        self.download_button = _toolbar_button("تنزيل على الجهاز", "#2563EB", "#1D4ED8",
                                               QStyle.SP_DialogSaveButton, self)
        self.delete_button = _toolbar_button("حذف", "#DC2626", "#B91C1C", QStyle.SP_TrashIcon, self)
        close_button = _toolbar_button("إغلاق", "#374151", "#1F2937")
        for button in (self.attach_button, self.open_button, self.download_button, self.delete_button):
            bar.addWidget(button)
        bar.addStretch(1)
        bar.addWidget(close_button)
        root.addLayout(bar)

        self.attach_button.clicked.connect(self.attach)
        self.open_button.clicked.connect(self.open_selected)
        self.download_button.clicked.connect(self.download_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        close_button.clicked.connect(self.accept)
        self.tabs.currentChanged.connect(lambda _i: self._update_buttons())
        for widget in self.lists.values():
            widget.itemSelectionChanged.connect(self._update_buttons)
            widget.itemDoubleClicked.connect(lambda _item: self.open_selected())
        self.refresh()

    # -- lists -------------------------------------------------------------

    @staticmethod
    def _list_style() -> str:
        return (
            "QListWidget { background:#FFFFFF; border:none; font-size:13px; font-weight:700; color:#1F2937; }"
            "QListWidget::item { border:1px solid #E5EAF0; border-radius:8px; padding:6px; margin:4px; }"
            "QListWidget::item:selected { background:#ECFDF3; border:2px solid #1A7A3C; color:#1F2937; }"
        )

    def _build_image_list(self) -> QListWidget:
        widget = QListWidget()
        widget.setViewMode(QListWidget.IconMode)
        widget.setIconSize(QSize(THUMB, THUMB))
        widget.setGridSize(QSize(THUMB + 40, THUMB + 56))
        widget.setResizeMode(QListWidget.Adjust)
        widget.setMovement(QListWidget.Static)
        widget.setWordWrap(True)
        widget.setSelectionMode(QAbstractItemView.SingleSelection)
        widget.setStyleSheet(self._list_style())
        return widget

    def _build_pdf_list(self) -> QListWidget:
        widget = QListWidget()
        widget.setIconSize(QSize(34, 34))
        widget.setSelectionMode(QAbstractItemView.SingleSelection)
        widget.setStyleSheet(self._list_style())
        return widget

    @property
    def kind(self) -> str:
        return IMAGE if self.tabs.currentIndex() == 0 else PDF

    def refresh(self) -> None:
        for kind in (IMAGE, PDF):
            try:
                self.rows[kind] = self.service.list(self.contract_id, kind)
            except Exception as exc:
                self.rows[kind] = []
                QMessageBox.critical(self, "تعذّر تحميل المرفقات", str(exc))
            self._fill(kind)
        self.tabs.setTabText(0, f"الصور ({len(self.rows[IMAGE])})")
        self.tabs.setTabText(1, f"ملفات PDF ({len(self.rows[PDF])})")
        self._update_buttons()

    def _fill(self, kind: str) -> None:
        widget = self.lists[kind]
        widget.clear()
        pdf_icon = self.style().standardIcon(QStyle.SP_FileIcon)
        for row in self.rows[kind]:
            when = row.get("uploaded_at")
            when_text = f"{when.astimezone():%Y-%m-%d}" if isinstance(when, datetime.datetime) else ""
            if kind == IMAGE:
                icon, pixmap = QIcon(), QPixmap()
                if row.get("thumbnail") and pixmap.loadFromData(row["thumbnail"]):
                    icon = QIcon(pixmap)
                item = QListWidgetItem(icon, f"{row['file_name']}\n{size_text(row['file_size'])}")
                item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            else:
                details = " · ".join(part for part in (size_text(row["file_size"]), when_text) if part)
                item = QListWidgetItem(pdf_icon, f"{row['file_name']}\n{details}")
            item.setToolTip(row["file_name"])
            item.setData(Qt.UserRole, row["attachment_id"])
            widget.addItem(item)
        if widget.count() == 0:
            empty = QListWidgetItem("لسه مفيش صور مرفقة." if kind == IMAGE else "لسه مفيش ملفات PDF مرفقة.")
            empty.setFlags(Qt.NoItemFlags)
            widget.addItem(empty)

    def _selected(self) -> dict[str, Any] | None:
        item = self.lists[self.kind].currentItem()
        if item is None or not item.isSelected() or item.data(Qt.UserRole) is None:
            return None
        wanted = item.data(Qt.UserRole)
        return next((row for row in self.rows[self.kind] if row["attachment_id"] == wanted), None)

    def _update_buttons(self) -> None:
        picked = self._selected() is not None
        self.attach_button.setText("إرفاق صور" if self.kind == IMAGE else "إرفاق ملفات PDF")
        self.attach_button.setEnabled(self.can_modify)
        self.open_button.setEnabled(picked)
        self.download_button.setEnabled(picked)
        self.delete_button.setEnabled(picked and self.can_modify)

    # -- actions -----------------------------------------------------------

    def attach(self) -> None:
        if not self.can_modify:
            return
        kind = self.kind
        title = "اختيار صور للعقد" if kind == IMAGE else "اختيار ملفات PDF للعقد"
        paths, _ = QFileDialog.getOpenFileNames(self, title, "", FILE_FILTERS[kind])
        if not paths:
            return
        problems: list[str] = []
        added = 0
        for path in paths:
            try:
                name, mime, data = read_attachment(path, kind)
            except AttachmentError as exc:
                problems.append(str(exc))
                continue
            thumbnail = None
            if kind == IMAGE:
                thumbnail = make_thumbnail(data)
                if thumbnail is None:
                    problems.append(f"تعذّر قراءة الصورة «{name}».")
                    continue
            try:
                self.service.add(self.contract_id, kind, name, mime, data, thumbnail,
                                 (SESSION.user or {}).get("id"))
            except Exception as exc:
                problems.append(f"«{name}»: {exc}")
                continue
            added += 1
        if added:
            self.changed = True
            self.refresh()
            self.tabs.setCurrentIndex(0 if kind == IMAGE else 1)
        if problems:
            QMessageBox.warning(self, "ملفات ما اترفقتش", "\n".join(problems))

    def _load(self) -> dict[str, Any] | None:
        row = self._selected()
        if row is None:
            return None
        try:
            full = self.service.data(row["attachment_id"])
        except Exception as exc:
            QMessageBox.critical(self, "تعذّر تحميل الملف", str(exc))
            return None
        if not full or not full.get("data"):
            QMessageBox.warning(self, "الملف مش موجود", "الملف ده اتمسح. اضغط إغلاق وافتح المرفقات تاني.")
            return None
        return full

    def open_selected(self) -> None:
        full = self._load()
        if full is None:
            return
        viewer_cls: Callable[..., QDialog] = ImageViewerDialog if full["kind"] == IMAGE else PdfViewerDialog
        viewer = viewer_cls(full["file_name"], full["data"], self)
        if isinstance(viewer, PdfViewerDialog) and not viewer.loaded:
            QMessageBox.warning(self, "تعذّر فتح الملف", "البرنامج مش قادر يعرض ملف الـ PDF ده. نزّله وافتحه من الجهاز.")
            return
        viewer.showMaximized()
        viewer.exec()

    def download_selected(self) -> None:
        full = self._load()
        if full is not None:
            save_to_pc(self, full["file_name"], full["data"])

    def delete_selected(self) -> None:
        row = self._selected()
        if row is None or not self.can_modify:
            return
        answer = QMessageBox.question(
            self, "تأكيد الحذف", f"هل تريد حذف المرفق «{row['file_name']}»؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.delete(row["attachment_id"])
        except Exception as exc:
            QMessageBox.critical(self, "تعذّر الحذف", str(exc))
            return
        self.changed = True
        self.refresh()
