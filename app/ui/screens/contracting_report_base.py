"""What every contracting report shares: the green header and the filter bar.

The filter bar is «كل الفترات», من/إلى، الشركة → المشروع (the project list
follows the company)، المقاول, then عرض التقرير / تحديث / خروج. A report that sets
``CONTRACT_FILTER`` adds a second row with «العقد» (user, 2026-10-13): its list
follows the company, project and contractor, and the report's service gets
``contract_id``. A report subclass sets ``TITLE``, ``ICON`` and
``PERMISSION_BASE``, builds the rest in ``_build_body`` and fills it in
``run_report``.
"""

from __future__ import annotations

import datetime
from typing import Any, Callable, Iterable

from PySide6.QtCore import QDate, QEvent, QObject, QSettings, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from app.security.session_context import SESSION
from app.ui.common.theme import GREEN, TEXT, _button_style
from app.ui.screens.contractor_contracts_screen import _COMBO_QSS, _EDITOR_QSS, _select_data

MUTED = "#475569"
RED = "#B91C1C"
TOTAL_BG = "#DCFCE7"
DEDUCTION_BG = "#FEF6F6"   # a «خصومات أخرى» line under its extract («إظهار تفاصيل الخصومات»)
DEDUCTION_COLOR = "#B91C1C"

TABLE_QSS = (
    "QTableWidget { border:1px solid #E5EAF0; font-size:13px; font-weight:700; gridline-color:#E5E7EB; "
    "background:#FFFFFF; }"
    f"QHeaderView::section {{ background:{GREEN}; color:#FFFFFF; font-weight:900; padding:6px; border:none; "
    "border-left:1px solid rgba(255,255,255,0.25); }"
    "QTableWidget::item:selected { background:#FEF3C7; color:#111827; }"
)


def deduction_text(deduction: dict[str, Any]) -> str:
    """«• غرامة تأخير — تأخير 5 أيام» (the reason only when there is one)."""
    reason = str(deduction.get("reason") or "").strip()
    return f"• {deduction.get('deduction_type') or ''}" + (f" — {reason}" if reason else "")


def deductions_toggle(checked: bool) -> QPushButton:
    """The «إظهار / إخفاء تفاصيل الخصومات» button (كشف حساب مقاول، تقرير المستخلصات)."""
    button = QPushButton()
    button.setCheckable(True)
    button.setChecked(checked)
    button.setCursor(Qt.PointingHandCursor)
    button.setMinimumHeight(34)
    button.setStyleSheet(
        f"QPushButton {{ background:#FFFFFF; color:{DEDUCTION_COLOR}; border:1.5px solid {DEDUCTION_COLOR}; "
        "border-radius:8px; padding:5px 14px; font-size:13px; font-weight:900; }"
        f"QPushButton:checked {{ background:{DEDUCTION_COLOR}; color:#FFFFFF; }}"
    )
    return button


def date_text(value: Any) -> str:
    return f"{value:%Y-%m-%d}" if isinstance(value, (datetime.date, datetime.datetime)) else str(value or "")


def table_item(text: str, negative: bool = False, bold: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignCenter)  # every report cell is centred (user, 2026-10-02)
    if negative:
        item.setForeground(QBrush(QColor(RED)))
    if bold:
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        item.setFont(font)
    return item


# -- column widths ------------------------------------------------------------------------


def share_widths(needs: list[int], available: int) -> list[int]:
    """Widths for columns that need *needs* px, sharing *available* px (user, 2026-10-02).

    Every column gets an equal share; one whose content needs more keeps what it
    needs and the rest share what is left. When even the needs do not fit, each
    column gets its need (the table scrolls).
    """
    if not needs:
        return []
    if sum(needs) >= available:
        return list(needs)
    widths: dict[int, float] = {}
    left, space = list(range(len(needs))), float(available)
    while left:
        share = space / len(left)
        wide = [i for i in left if needs[i] > share]
        if not wide:
            widths.update({i: share for i in left})
            break
        for i in wide:
            widths[i] = needs[i]
            space -= needs[i]
            left.remove(i)
    result = [int(widths[i]) for i in range(len(needs))]
    result[-1] += available - sum(result)  # the pixels lost to rounding
    return result


class ColumnFitter(QObject):
    """Spreads a table's width over its visible columns, so with a few columns
    shown no single one takes all the room. Call ``fit()`` after a fill or a
    change of columns; it refits by itself when the table is resized.
    *fixed* columns (a ＋/－ column) keep their width.
    """

    PADDING = 18

    def __init__(self, table: QTableWidget, fixed: Iterable[int] = ()) -> None:
        super().__init__(table)
        self.table = table
        self.fixed = set(fixed)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        for column in range(table.columnCount()):
            if column not in self.fixed:
                header.setSectionResizeMode(column, QHeaderView.Interactive)
        table.viewport().installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt)
        if event.type() == QEvent.Resize:
            self.fit()
        return False

    def fit(self) -> None:
        table, header = self.table, self.table.horizontalHeader()
        columns = [c for c in range(table.columnCount()) if not table.isColumnHidden(c) and c not in self.fixed]
        available = table.viewport().width() - sum(
            header.sectionSize(c) for c in self.fixed if not table.isColumnHidden(c))
        needs = [max(table.sizeHintForColumn(c), header.sectionSizeHint(c)) + self.PADDING for c in columns]
        for column, width in zip(columns, share_widths(needs, available)):
            header.resizeSection(column, width)


# -- «تحديد أعمدة الجدول» ---------------------------------------------------------------


def report_settings() -> QSettings:
    """Where a report keeps its per-user choices (the columns shown)."""
    return QSettings("A-H CONTRACTOR", "CRM")


def _columns_key(prefix: str) -> str:
    username = (SESSION.user or {}).get("username") if SESSION.user else None
    return f"{prefix}/{(username or '_').lower()}"


def load_columns(settings: QSettings, prefix: str, all_keys: Iterable[str],
                 defaults: tuple[str, ...], added: Iterable[str] = ()) -> tuple[str, ...]:
    """The current user's saved column choice, in table order; *defaults* if never saved.

    *added* are columns that came after the user may have saved a choice: each one is
    switched on once (and the choice saved), so it shows; hiding it later sticks. A user
    with no saved choice yet already sees them, so they are marked as shown then."""
    all_keys = tuple(all_keys)
    saved = settings.value(_columns_key(prefix))

    def marker(key: str) -> str:
        return f"{prefix}_added/{key}/{_columns_key(prefix).rsplit('/', 1)[-1]}"

    if saved is None:
        for key in added:
            settings.setValue(marker(key), "1")
        return defaults
    chosen = set(str(saved).split(","))
    changed = False
    for key in added:
        if settings.value(marker(key)) is None:
            settings.setValue(marker(key), "1")
            if key not in chosen:
                chosen.add(key)
                changed = True
    result = tuple(key for key in all_keys if key in chosen)
    if changed:
        save_columns(settings, prefix, result)
    return result


def save_columns(settings: QSettings, prefix: str, keys: Iterable[str]) -> None:
    settings.setValue(_columns_key(prefix), ",".join(keys))
    settings.sync()


def load_flag(settings: QSettings, prefix: str, default: bool = False) -> bool:
    """The current user's saved on/off choice (e.g. «التفاف النص»); *default* if never saved."""
    saved = settings.value(_columns_key(prefix))
    return default if saved is None else str(saved).lower() in ("1", "true")


def save_flag(settings: QSettings, prefix: str, value: bool) -> None:
    settings.setValue(_columns_key(prefix), "1" if value else "0")
    settings.sync()


class ColumnChooser(QWidget):
    """The checkbox list behind «تحديد أعمدة الجدول»: one column of boxes per group.

    Every change calls *apply* with the ticked keys, in table order.
    """

    def __init__(self, groups: tuple[tuple[str, tuple[str, ...]], ...], headers: dict[str, str],
                 defaults: tuple[str, ...], apply: Callable[[tuple[str, ...]], None]) -> None:
        super().__init__()
        self.apply = apply
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet(
            f"QWidget {{ background:#FFFFFF; color:{TEXT}; }}"
            "QCheckBox { font-size:13px; font-weight:700; padding:3px 0; spacing:8px; }"
            # An explicit box, so an unticked column still shows where to click.
            "QCheckBox::indicator { width:15px; height:15px; border:2px solid #94A3B8; border-radius:4px; "
            "background:#FFFFFF; }"
            f"QCheckBox::indicator:checked {{ background:{GREEN}; border-color:{GREEN}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        title = QLabel("تحديد أعمدة الجدول")
        title.setStyleSheet("font-size:15px; font-weight:900;")
        layout.addWidget(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(26)
        grid.setVerticalSpacing(2)
        self.boxes: dict[str, QCheckBox] = {}
        for column, (name, keys) in enumerate(groups):
            caption = QLabel(name)
            caption.setStyleSheet(f"font-size:12px; font-weight:900; color:{GREEN}; "
                                  "border-bottom:1px solid #E5EAF0; padding-bottom:4px;")
            grid.addWidget(caption, 0, column)
            for line, key in enumerate(keys, start=1):
                box = QCheckBox(headers[key])
                box.toggled.connect(lambda _checked: self.apply(self.checked_keys()))
                grid.addWidget(box, line, column, Qt.AlignTop)
                self.boxes[key] = box
        grid.setRowStretch(max(len(keys) for _name, keys in groups) + 1, 1)
        layout.addLayout(grid)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.all_button = QPushButton("تحديد الكل")
        self.none_button = QPushButton("إلغاء الكل")
        self.default_button = QPushButton("استعادة الافتراضي")
        every = tuple(self.boxes)
        for button, keys in ((self.all_button, every), (self.none_button, ()), (self.default_button, defaults)):
            button.setFixedHeight(32)
            button.setStyleSheet(_button_style("#64748B", "#475569"))
            button.clicked.connect(lambda _=False, k=keys: self.apply(k))
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def checked_keys(self) -> tuple[str, ...]:
        return tuple(key for key, box in self.boxes.items() if box.isChecked())

    def sync(self, visible: Iterable[str]) -> None:
        shown = set(visible)
        for key, box in self.boxes.items():
            box.blockSignals(True)
            box.setChecked(key in shown)
            box.blockSignals(False)


def column_button(chooser: ColumnChooser) -> tuple[QToolButton, QMenu]:
    """The «تحديد أعمدة الجدول» button; its menu holds *chooser* and stays open while ticking."""
    button = QToolButton()
    button.setText("  تحديد أعمدة الجدول  ▾")
    button.setPopupMode(QToolButton.InstantPopup)
    button.setFixedHeight(36)
    button.setStyleSheet(
        f"QToolButton {{ background:#FFFFFF; color:{GREEN}; border:1px solid {GREEN}; border-radius:7px; "
        "padding:0 12px; font-size:13px; font-weight:900; }"
        "QToolButton::menu-indicator { image:none; width:0; }"
        "QToolButton:hover { background:#F0FDF4; }"
    )
    menu = QMenu(button)
    menu.setLayoutDirection(Qt.RightToLeft)
    action = QWidgetAction(menu)
    action.setDefaultWidget(chooser)
    menu.addAction(action)
    button.setMenu(menu)
    return button, menu


class ContractingReportBase(QWidget):
    TITLE = ""
    ICON = "📈"
    PERMISSION_BASE = ""
    CONTRACT_FILTER = False  # «العقد» on a second filter row; the service takes ``contract_id``

    def __init__(self, service: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self._perm_filter = SESSION.can(f"{self.PERMISSION_BASE}.filter")

        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet("QWidget { font-family: 'Segoe UI', 'Tahoma', 'Arial'; }")
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        root.addWidget(self._build_header())
        root.addWidget(self._build_filters())
        self._build_body(root)
        self.load_choices()
        self.run_report()

    # -- for the subclass ------------------------------------------------------------

    def _build_body(self, root: QVBoxLayout) -> None:
        raise NotImplementedError

    def run_report(self) -> None:
        raise NotImplementedError

    # -- header ------------------------------------------------------------------------

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setStyleSheet(
            f"QFrame {{ background:{GREEN}; border-radius:6px; }}"
            "QLabel { background:transparent; color:#FFFFFF; }"
        )
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(14)
        icon = QLabel(self.ICON)
        icon.setFixedSize(50, 50)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            "background:rgba(255,255,255,0.16); border:1px solid rgba(255,255,255,0.28); "
            "border-radius:7px; font-size:22px; font-weight:900;"
        )
        title = QLabel(self.TITLE)
        title.setStyleSheet("font-size:26px; font-weight:900;")
        username = (SESSION.user or {}).get("username") if SESSION.user else None
        self.header_user = QLabel(f"المستخدم: {username or '—'}")
        self.header_date = QLabel("")
        for label in (self.header_user, self.header_date):
            label.setStyleSheet(
                "background:rgba(255,255,255,0.14); border:1px solid rgba(255,255,255,0.24); "
                "border-radius:6px; padding:8px 14px; font-weight:800;"
            )
        layout.addWidget(icon)
        layout.addWidget(title, 1)
        layout.addWidget(self.header_user)
        layout.addWidget(self.header_date)
        self.header_timer = QTimer(self)
        self.header_timer.timeout.connect(self._update_datetime)
        self.header_timer.start(1000)
        self._update_datetime()
        return header

    def _update_datetime(self) -> None:
        now = datetime.datetime.now()
        self.header_date.setText(f"التاريخ: {now:%Y-%m-%d} | الوقت: {now:%H:%M:%S}")

    # -- filter bar ----------------------------------------------------------------------

    def _caption(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"font-size:13px; font-weight:900; color:{MUTED}; background:transparent; border:none;")
        return label

    def _combo(self, width: int) -> QComboBox:
        combo = QComboBox()
        combo.setMinimumHeight(38)
        combo.setMinimumWidth(width)
        combo.setStyleSheet(_COMBO_QSS)
        return combo

    def _date(self, value: QDate) -> QDateEdit:
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd")
        edit.setDate(value)
        edit.setMinimumHeight(38)
        edit.setLayoutDirection(Qt.LeftToRight)
        edit.setStyleSheet(_EDITOR_QSS + "QDateEdit:disabled { background:#F1F5F9; color:#94A3B8; border-color:#CBD5E1; }")
        return edit

    def _build_filters(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet("QFrame { background:#FFFFFF; border:1px solid #E5EAF0; border-radius:7px; }")
        rows = QVBoxLayout(bar)
        rows.setContentsMargins(10, 8, 10, 8)
        rows.setSpacing(8)
        layout = QHBoxLayout()
        layout.setSpacing(8)
        rows.addLayout(layout)
        today = QDate.currentDate()
        self.all_dates = QCheckBox("كل الفترات")
        self.all_dates.setChecked(True)
        self.all_dates.setStyleSheet(f"font-size:13px; font-weight:900; color:{TEXT}; border:none;")
        self.date_from = self._date(QDate(today.year(), 1, 1))
        self.date_to = self._date(today)
        self.company_combo = self._combo(190)
        self.project_combo = self._combo(190)
        self.contractor_combo = self._combo(210)
        self.show_button = QPushButton("عرض التقرير")
        self.refresh_button = QPushButton("تحديث")
        self.exit_button = QPushButton("خروج")
        for text, widget in (("", self.all_dates), ("من", self.date_from), ("إلى", self.date_to),
                             ("الشركة", self.company_combo), ("المشروع", self.project_combo),
                             ("المقاول", self.contractor_combo)):
            if text:
                layout.addWidget(self._caption(text))
            layout.addWidget(widget)
        layout.addStretch(1)
        for button, icon, bg, hover in (
            (self.show_button, QStyle.SP_FileDialogContentsView, "#1A7A3C", "#166534"),
            (self.refresh_button, QStyle.SP_BrowserReload, "#64748B", "#475569"),
            (self.exit_button, QStyle.SP_ArrowBack, "#374151", "#1F2937"),
        ):
            button.setFixedHeight(38)
            button.setIcon(self.style().standardIcon(icon))
            button.setStyleSheet(_button_style(bg, hover))
            layout.addWidget(button)
        self.contract_combo: QComboBox | None = None
        if self.CONTRACT_FILTER:
            second = QHBoxLayout()
            second.setSpacing(8)
            self.contract_combo = self._combo(460)
            second.addWidget(self._caption("العقد"))
            second.addWidget(self.contract_combo)
            second.addStretch(1)
            rows.addLayout(second)

        self.all_dates.toggled.connect(self._sync_dates)
        self.company_combo.currentIndexChanged.connect(self._company_changed)
        if self.contract_combo is not None:
            self.project_combo.currentIndexChanged.connect(self._load_contracts)
            self.contractor_combo.currentIndexChanged.connect(self._load_contracts)
        self.show_button.clicked.connect(self.run_report)
        # Same path as the automatic reload: a database error is shown, never raised.
        self.refresh_button.clicked.connect(self.reload_lists)
        self.exit_button.clicked.connect(self.window().close)
        for widget in (self.all_dates, self.date_from, self.date_to, self.company_combo,
                       self.project_combo, self.contractor_combo, self.contract_combo):
            if widget is not None:
                widget.setEnabled(self._perm_filter)
        self._sync_dates()
        return bar

    def _sync_dates(self) -> None:
        for edit in (self.date_from, self.date_to):
            edit.setEnabled(self._perm_filter and not self.all_dates.isChecked())

    @staticmethod
    def _fill(combo: QComboBox, rows: list[dict[str, Any]], key: str, label: Callable[[dict[str, Any]], str]) -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("الكل", None)
        for row in rows:
            combo.addItem(label(row), row[key])
        _select_data(combo, current)
        combo.blockSignals(False)

    def load_choices(self) -> None:
        self._fill(self.company_combo, self.service.company_choices(), "company_id", lambda r: r["company_name"])
        self._fill(self.contractor_combo, self.service.contractor_choices(), "contractor_id",
                   lambda r: r["contractor_name"])
        self._load_projects()
        self._load_contracts()

    def _load_projects(self) -> None:
        self._fill(self.project_combo, self.service.project_choices(self.company_combo.currentData()),
                   "project_id", lambda r: r["project_name"])

    def _load_contracts(self) -> None:
        """«العقد»: the contracts under the chosen company / project / contractor (the pick is
        kept while it still fits, else «الكل»)."""
        if self.contract_combo is None:
            return
        rows = self.service.contract_choices(self.company_combo.currentData(), self.project_combo.currentData(),
                                             self.contractor_combo.currentData())
        self._fill(self.contract_combo, rows, "contract_id", lambda r: r["contract_label"])

    def _company_changed(self) -> None:
        self._load_projects()
        self._load_contracts()

    def filters(self) -> dict[str, Any]:
        dated = not self.all_dates.isChecked()
        return {
            "date_from": self.date_from.date().toPython() if dated else None,
            "date_to": self.date_to.date().toPython() if dated else None,
            "company_id": self.company_combo.currentData(),
            "project_id": self.project_combo.currentData(),
            "contractor_id": self.contractor_combo.currentData(),
            **({"contract_id": self.contract_combo.currentData()} if self.contract_combo is not None else {}),
        }

    def refresh_all(self) -> None:
        self.load_choices()
        self.run_report()

    def reload_lists(self) -> None:
        """Data changed in another screen: refill the filters (keeping the picks) and rerun.

        A database error is shown, never raised: on a sidebar open it would leave
        the button looking dead.
        """
        try:
            self.refresh_all()
        except Exception as exc:  # noqa: BLE001 - shown to the user, never raised into Qt
            QMessageBox.critical(self, "تعذّر تحديث التقرير", str(exc))
