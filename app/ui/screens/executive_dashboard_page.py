"""Executive Dashboard (الداشبورد التنفيذية) — the new multi-design dashboard.

A single screen that renders the whole business at a glance for one date range:

* KPI cards — عدد العملاء · عدد الموردين · عدد الأصناف · إجمالي سندات القبض
* المبيعات والمشتريات — a grouped monthly bar chart
* أعلى ٥ عملاء / أعلى ٥ موردين — horizontal bar lists
* أوامر الإنتاج — الكميات المنتجة · أعلى صنف · تكاليف المواد الخام
* سندات التحميل — أكبر سيارة وزناً بعد التحميل · أكثر سيارة سندات
* a letterhead-style header **pinned to the bottom** (per the design brief), so the
  charts get the top of the page.

Design system
-------------
The layout is built once from a :class:`Theme` (colors, chart palette, radii,
shadows). Ten designs are planned; a top switcher lets the user flip between the
implemented ones. New designs are added by registering another :class:`Theme` in
:data:`THEMES` — the same data and the same builder render every one, so each is a
complete, working dashboard.

All data comes from :class:`ExecutiveDashboardService` (read-only). This module is
presentation only — no SQL, no business logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import QDate, QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QBoxLayout,
    QDateEdit,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.services.executive_dashboard_service import ExecutiveDashboardService

logger = logging.getLogger(__name__)

CURRENCY = "ر.س"
NO_DATA = "لا توجد بيانات خلال الفترة المحددة"


# ==========================================================================
#  Theme model — one dashboard design.
# ==========================================================================
@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    # surfaces
    bg: str
    card: str
    text: str
    muted: str
    line: str
    soft: str
    accent: str
    accent_text: str = "#FFFFFF"
    # bottom header band
    header_bg: str = ""
    header_text: str = "#FFFFFF"
    header_logo_bg: str = "rgba(255,255,255,0.18)"
    # chart palette
    sales: str = "#137A38"
    purchase: str = "#F59E0B"
    cust: str = "#137A38"
    supp: str = "#0EA5E9"
    grid: str = "#E5EAF0"
    axis: str = "#64748B"
    # kpi trims
    kpi_icon_bg: str = "#EEF7F0"
    kpi_icon_fg: str = "#137A38"
    trend: str = "#16A34A"
    # style flags
    radius: int = 16
    shadow: bool = True
    kpi_top_accent: bool = True
    display_font: str = "Cairo"
    body_font: str = "Cairo"
    # extended design hooks (all optional — a plain color theme leaves them default)
    page_bg: str = ""                       # scroll/content bg (default: bg); may be a gradient
    card_border: str = ""                   # card border color (default: line); "" -> line
    kpi_gradients: tuple[str, ...] = ()     # per-KPI-card background (up to 4)
    kpi_icon_bgs: tuple[str, ...] = ()      # per-KPI-card icon background (up to 4)
    kpi_text: str = ""                      # KPI value/label color override (for colored cards)
    hide_kpi_icon: bool = False             # editorial / minimal designs drop the icon
    kpi_value_accent: bool = False          # KPI value rendered in the accent color
    dense: bool = False                     # compact paddings / smaller type
    card_accent: bool = False               # accent stripe on the leading edge of each card
    title_rule: bool = False                # hairline rule under each card title


# The ten planned designs (key, Arabic name), in switcher order.
MODELS: tuple[tuple[str, str], ...] = (
    ("m1", "الأخضر الكلاسيكي"),
    ("m2", "الداكن الاحترافي"),
    ("m3", "البطاقات الملوّنة"),
    ("m4", "الأبيض المينيمال"),
    ("m5", "بينتو جريد"),
    ("m6", "الزجاجي"),
    ("m7", "المحلّل الكثيف"),
    ("m8", "الأنيق الكلاسيكي"),
    ("m9", "نيومورفيزم"),
    ("m10", "الصناعي"),
)

# Registered (implemented) designs. Each stage adds one more here.
THEMES: dict[str, Theme] = {
    "m1": Theme(
        key="m1",
        name="الأخضر الكلاسيكي",
        bg="#EEF2F6",
        card="#FFFFFF",
        text="#0F172A",
        muted="#64748B",
        line="#E2E8F0",
        soft="#EEF7F0",
        accent="#137A38",
        accent_text="#FFFFFF",
        header_bg="qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0F6B30,stop:1 #1A9247)",
        header_text="#EAFFF1",
        sales="#137A38",
        purchase="#F59E0B",
        cust="#137A38",
        supp="#0EA5E9",
        grid="#E5EAF0",
        axis="#64748B",
        kpi_icon_bg="#EEF7F0",
        kpi_icon_fg="#137A38",
        trend="#16A34A",
        radius=16,
        shadow=True,
        kpi_top_accent=True,
    ),
    "m2": Theme(
        key="m2",
        name="الداكن الاحترافي",
        bg="#0B1220",
        card="#131E33",
        text="#E8EEF9",
        muted="#8CA0BD",
        line="#24344F",
        soft="#0F1A2E",
        accent="#22D3A0",
        accent_text="#04121C",
        header_bg="qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0B2A22,stop:1 #132B3F)",
        header_text="#EAFFF6",
        header_logo_bg="rgba(34,211,160,0.18)",
        sales="#22D3A0",
        purchase="#38BDF8",
        cust="#22D3A0",
        supp="#818CF8",
        grid="#22304A",
        axis="#94A3B8",
        kpi_icon_bg="#0F1A2E",
        kpi_icon_fg="#22D3A0",
        trend="#34D399",
        radius=16,
        shadow=False,
        kpi_top_accent=True,
    ),
    "m3": Theme(
        key="m3",
        name="البطاقات الملوّنة",
        bg="#F5F6FB",
        card="#FFFFFF",
        text="#1E1B2E",
        muted="#6B7280",
        line="#ECEBF3",
        soft="#F6F4FC",
        accent="#7C3AED",
        accent_text="#FFFFFF",
        header_bg="qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #7C3AED,stop:1 #EC4899)",
        header_text="#FFFFFF",
        header_logo_bg="rgba(255,255,255,0.24)",
        sales="#7C3AED",
        purchase="#EC4899",
        cust="#F97316",
        supp="#06B6D4",
        grid="#ECE9F5",
        axis="#8B8698",
        trend="#16A34A",
        radius=16,
        shadow=True,
        kpi_top_accent=False,
        kpi_text="#FFFFFF",
        kpi_gradients=(
            "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #7C3AED,stop:1 #A855F7)",
            "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #EC4899,stop:1 #F472B6)",
            "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #F97316,stop:1 #FB923C)",
            "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #0891B2,stop:1 #22D3EE)",
        ),
        kpi_icon_bgs=("rgba(255,255,255,0.24)",) * 4,
    ),
    "m4": Theme(
        key="m4",
        name="الأبيض المينيمال",
        bg="#FFFFFF",
        card="#FFFFFF",
        text="#0A0A0A",
        muted="#9CA3AF",
        line="#ECECEC",
        soft="#FAFAFA",
        accent="#16A34A",
        accent_text="#FFFFFF",
        header_bg="#0A0A0A",
        header_text="#FAFAFA",
        header_logo_bg="rgba(255,255,255,0.14)",
        sales="#111827",
        purchase="#16A34A",
        cust="#111827",
        supp="#16A34A",
        grid="#EFEFEF",
        axis="#9CA3AF",
        trend="#16A34A",
        radius=8,
        shadow=False,
        kpi_top_accent=False,
        hide_kpi_icon=True,
        display_font="Cairo",
    ),
    "m5": Theme(
        key="m5",
        name="بينتو جريد",
        bg="#ECEEF3",
        card="#FFFFFF",
        text="#111827",
        muted="#6B7280",
        line="#E4E7EE",
        soft="#F3F4F8",
        accent="#4F46E5",
        accent_text="#FFFFFF",
        header_bg="qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #1E1B4B,stop:1 #4F46E5)",
        header_text="#FFFFFF",
        header_logo_bg="rgba(255,255,255,0.20)",
        sales="#4F46E5",
        purchase="#F59E0B",
        cust="#4F46E5",
        supp="#10B981",
        grid="#E4E7EE",
        axis="#6B7280",
        trend="#16A34A",
        radius=22,
        shadow=True,
        kpi_top_accent=False,
        kpi_gradients=(
            "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #EEF0FF,stop:1 #FFFFFF)",
            "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #E9FBF3,stop:1 #FFFFFF)",
            "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #FFF4E8,stop:1 #FFFFFF)",
            "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #FDEAF4,stop:1 #FFFFFF)",
        ),
        kpi_icon_bgs=("#4F46E5", "#10B981", "#F59E0B", "#EC4899"),
    ),
    "m6": Theme(
        key="m6",
        name="الزجاجي",
        bg="#0E7490",
        page_bg="qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #0EA5E9,stop:0.5 #0D9488,stop:1 #065F46)",
        card="rgba(255,255,255,0.14)",
        card_border="rgba(255,255,255,0.30)",
        text="#F0FDFA",
        muted="rgba(240,253,250,0.82)",
        line="rgba(255,255,255,0.28)",
        soft="rgba(255,255,255,0.12)",
        accent="#FFFFFF",
        accent_text="#065F46",
        header_bg="rgba(255,255,255,0.16)",
        header_text="#FFFFFF",
        header_logo_bg="rgba(255,255,255,0.22)",
        sales="#FFFFFF",
        purchase="#BFF7E6",
        cust="#FFFFFF",
        supp="#BDF0FF",
        grid="rgba(255,255,255,0.28)",
        axis="#E6FFFA",
        kpi_icon_bg="rgba(255,255,255,0.22)",
        kpi_icon_fg="#FFFFFF",
        trend="#A7F3D0",
        radius=18,
        shadow=False,
        kpi_top_accent=False,
    ),
    "m7": Theme(
        key="m7",
        name="المحلّل الكثيف",
        bg="#EEF2F6",
        card="#FFFFFF",
        text="#0F172A",
        muted="#64748B",
        line="#E2E8F0",
        soft="#F1F5F9",
        accent="#0EA5E9",
        accent_text="#FFFFFF",
        header_bg="#0F172A",
        header_text="#E2E8F0",
        header_logo_bg="rgba(255,255,255,0.14)",
        sales="#0EA5E9",
        purchase="#F43F5E",
        cust="#0EA5E9",
        supp="#8B5CF6",
        grid="#E2E8F0",
        axis="#64748B",
        kpi_icon_bg="#E0F2FE",
        kpi_icon_fg="#0284C7",
        trend="#16A34A",
        radius=10,
        shadow=True,
        kpi_top_accent=False,
        dense=True,
        card_accent=True,
    ),
    "m8": Theme(
        key="m8",
        name="الأنيق الكلاسيكي",
        bg="#F5F1E9",
        card="#FFFDF9",
        text="#26211A",
        muted="#8A7F6D",
        line="#E7E0D2",
        soft="#F2ECE0",
        accent="#0F5132",
        accent_text="#FFFFFF",
        header_bg="#26211A",
        header_text="#F5F1E9",
        header_logo_bg="rgba(245,241,233,0.14)",
        sales="#0F5132",
        purchase="#B45309",
        cust="#0F5132",
        supp="#B45309",
        grid="#E7E0D2",
        axis="#8A7F6D",
        trend="#0F5132",
        radius=5,
        shadow=True,
        kpi_top_accent=False,
        hide_kpi_icon=True,
        title_rule=True,
        display_font="Amiri",
        body_font="Tajawal",
    ),
    "m9": Theme(
        key="m9",
        name="نيومورفيزم",
        bg="#E7EBF1",
        card="#E7EBF1",
        card_border="#E7EBF1",
        text="#33415C",
        muted="#7A879B",
        line="#D7DDE7",
        soft="#EDF0F5",
        accent="#3B82F6",
        accent_text="#FFFFFF",
        header_bg="qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #3B82F6,stop:1 #60A5FA)",
        header_text="#FFFFFF",
        header_logo_bg="rgba(255,255,255,0.22)",
        sales="#3B82F6",
        purchase="#F59E0B",
        cust="#3B82F6",
        supp="#EF4444",
        grid="#D7DDE7",
        axis="#7A879B",
        kpi_icon_bg="#EDF0F5",
        kpi_icon_fg="#3B82F6",
        trend="#16A34A",
        radius=20,
        shadow=True,
        kpi_top_accent=False,
    ),
    "m10": Theme(
        key="m10",
        name="الصناعي",
        bg="#0F1620",
        card="#18222F",
        text="#E6EDF5",
        muted="#8EA0B5",
        line="#26374B",
        soft="#111A26",
        accent="#F59E0B",
        accent_text="#1A1206",
        header_bg="qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #1A2534,stop:1 #0F1620)",
        header_text="#F59E0B",
        header_logo_bg="rgba(245,158,11,0.16)",
        sales="#F59E0B",
        purchase="#38BDF8",
        cust="#F59E0B",
        supp="#34D399",
        grid="#243244",
        axis="#8EA0B5",
        kpi_icon_bg="#111A26",
        kpi_icon_fg="#F59E0B",
        trend="#34D399",
        radius=10,
        shadow=False,
        kpi_top_accent=True,
        kpi_value_accent=True,
        card_accent=True,
        display_font="Cairo",
    ),
}

DEFAULT_THEME = "m1"


# ==========================================================================
#  Formatting helpers.
# ==========================================================================
def money(value: Any) -> str:
    try:
        return f"{float(value):,.0f} {CURRENCY}"
    except (TypeError, ValueError):
        return f"0 {CURRENCY}"


def qty(value: Any) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "0"
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:,.1f}"


def _kfmt(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{round(value / 1_000)}K"
    return f"{int(value)}"


# ==========================================================================
#  Grouped monthly bar chart (sales vs purchases) — QPainter.
# ==========================================================================
class GroupedBarChart(QWidget):
    """Two bars per month (sales, purchases) with a light value grid. RTL: the
    value axis sits on the right, months read left-to-right chronologically."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: list[dict[str, Any]] = []
        self._sales = "#137A38"
        self._purch = "#F59E0B"
        self._grid = "#E5EAF0"
        self._axis = "#64748B"
        self.setMinimumHeight(130)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, data: list[dict[str, Any]], theme: Theme) -> None:
        self._data = data or []
        self._sales, self._purch = theme.sales, theme.purchase
        self._grid, self._axis = theme.grid, theme.axis
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: ANN001 - Qt paint event
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = float(self.width()), float(self.height())

        if not self._data:
            p.setPen(QColor(self._axis))
            p.setFont(QFont("Cairo", 11, QFont.DemiBold))
            p.drawText(self.rect(), Qt.AlignCenter, NO_DATA)
            return

        m_left, m_right, m_top, m_bottom = 18.0, 56.0, 16.0, 40.0
        x0, x1 = m_left, w - m_right
        y0, y1 = m_top, h - m_bottom
        plot_w, plot_h = max(1.0, x1 - x0), max(1.0, y1 - y0)

        peak = max((max(d["sales"], d["purchases"]) for d in self._data), default=0.0)
        nice = peak * 1.15 if peak > 0 else 1.0

        # grid + value labels (right side)
        grid_pen = QPen(QColor(self._grid))
        grid_pen.setWidth(1)
        p.setFont(QFont("Cairo", 9))
        for i in range(5):
            y = y0 + plot_h * i / 4
            p.setPen(grid_pen)
            p.drawLine(QRectF(x0, y, plot_w, 0).topLeft(), QRectF(x1, y, 0, 0).topLeft())
            p.setPen(QColor(self._axis))
            p.drawText(
                QRectF(x1 + 4, y - 8, m_right - 6, 16),
                Qt.AlignLeft | Qt.AlignVCenter,
                _kfmt(nice * (1 - i / 4)),
            )

        n = len(self._data)
        gw = plot_w / n
        bw = min(26.0, gw * 0.30)
        sales_brush, purch_brush = QColor(self._sales), QColor(self._purch)
        p.setFont(QFont("Cairo", 10, QFont.DemiBold))
        for i, d in enumerate(self._data):
            cx = x0 + gw * (i + 0.5)
            hs = plot_h * (d["sales"] / nice)
            hp = plot_h * (d["purchases"] / nice)
            p.setPen(Qt.NoPen)
            p.setBrush(sales_brush)
            p.drawRoundedRect(QRectF(cx - bw - 3, y1 - hs, bw, hs), 4, 4)
            p.setBrush(purch_brush)
            p.drawRoundedRect(QRectF(cx + 3, y1 - hp, bw, hp), 4, 4)
            p.setPen(QColor(self._axis))
            p.drawText(
                QRectF(cx - gw / 2, y1 + 6, gw, 18),
                Qt.AlignHCenter | Qt.AlignVCenter,
                str(d["label"]),
            )
        p.end()


# ==========================================================================
#  The dashboard page.
# ==========================================================================
class ExecutiveDashboardPage(QWidget):
    def __init__(
        self,
        service: ExecutiveDashboardService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service or ExecutiveDashboardService()
        self.setLayoutDirection(Qt.RightToLeft)
        self._theme_key = DEFAULT_THEME
        self._data: dict[str, Any] | None = None
        self._model_buttons: dict[str, QPushButton] = {}
        self._build_ui()
        self.refresh_dashboard()

    # --- shell hooks --------------------------------------------------------
    def event(self, event: QEvent) -> bool:
        result = super().event(event)
        if event.type() == QEvent.WindowActivate:
            self.refresh_dashboard()
        return result

    @property
    def theme(self) -> Theme:
        return THEMES.get(self._theme_key, THEMES[DEFAULT_THEME])

    # --- layout scaffold ----------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_switcher())

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self._scroll, 1)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(22, 12, 22, 14)
        self._content_layout.setSpacing(12)
        self._scroll.setWidget(self._content)

        self._filter_bar = self._build_filter_bar()
        self._content_layout.addWidget(self._filter_bar)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(12)
        self._content_layout.addWidget(self._body, 1)

        self._apply_chrome()

    def _build_switcher(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("switcher")
        bar.setStyleSheet(
            "QFrame#switcher{background:#0F6B30;}"
            "QLabel#swTitle{color:#EAFFF1;font-family:'Cairo';font-size:15px;font-weight:900;}"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(8)

        title = QLabel("🎨  اختر تصميم الداشبورد")
        title.setObjectName("swTitle")
        row.addWidget(title)
        row.addSpacing(6)

        for index, (key, name) in enumerate(MODELS, start=1):
            btn = QPushButton(f"{index}")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(30)
            btn.setMinimumWidth(34)
            implemented = key in THEMES
            btn.setEnabled(implemented)
            btn.setToolTip(name if implemented else f"{name} — قريباً")
            btn.clicked.connect(lambda _c=False, k=key: self._select_theme(k))
            self._model_buttons[key] = btn
            row.addWidget(btn)

        row.addStretch(1)
        self._style_switcher_buttons()
        return bar

    def _style_switcher_buttons(self) -> None:
        active = (
            "QPushButton{background:#FFFFFF;color:#0F6B30;border:none;border-radius:8px;"
            "font-family:'Cairo';font-weight:900;font-size:13px;padding:4px 10px;}"
        )
        idle = (
            "QPushButton{background:rgba(255,255,255,0.14);color:#EAFFF1;border:none;"
            "border-radius:8px;font-family:'Cairo';font-weight:800;font-size:13px;padding:4px 10px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.28);}"
            "QPushButton:disabled{background:rgba(255,255,255,0.06);color:rgba(234,255,241,0.4);}"
        )
        for key, btn in self._model_buttons.items():
            btn.setStyleSheet(active if key == self._theme_key else idle)

    def _build_filter_bar(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("filterBar")
        row = QHBoxLayout(panel)
        row.setDirection(QBoxLayout.RightToLeft)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(10)

        heading = QLabel("📊 داشبورد الإدارة")
        heading.setObjectName("filterHeading")

        self.date_from = self._date_edit()
        self.date_to = self._date_edit()
        self._reset_dates()

        apply_btn = QPushButton("تطبيق الفلتر")
        apply_btn.setObjectName("applyBtn")
        apply_btn.setCursor(Qt.PointingHandCursor)
        apply_btn.setFixedHeight(36)
        apply_btn.clicked.connect(self.refresh_dashboard)

        reset_btn = QPushButton("آخر ٦ شهور")
        reset_btn.setObjectName("resetBtn")
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.setFixedHeight(36)
        reset_btn.clicked.connect(self._reset_and_refresh)

        row.addWidget(heading)
        row.addStretch(1)
        row.addWidget(self._field("من تاريخ", self.date_from))
        row.addWidget(self._field("إلى تاريخ", self.date_to))
        row.addWidget(apply_btn)
        row.addWidget(reset_btn)
        return panel

    def _field(self, label: str, widget: QWidget) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        text = QLabel(label)
        text.setObjectName("fieldLabel")
        text.setAlignment(Qt.AlignRight)
        lay.addWidget(text)
        lay.addWidget(widget)
        return box

    def _date_edit(self) -> QDateEdit:
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd")
        edit.setMinimumDate(QDate(2000, 1, 1))
        edit.setFixedWidth(130)
        edit.setFixedHeight(36)
        return edit

    def _reset_dates(self) -> None:
        today = QDate.currentDate()
        start = today.addMonths(-5)
        self.date_from.setDate(QDate(start.year(), start.month(), 1))
        self.date_to.setDate(today)

    def _reset_and_refresh(self) -> None:
        self._reset_dates()
        self.refresh_dashboard()

    # --- theme switching ----------------------------------------------------
    def _select_theme(self, key: str) -> None:
        if key not in THEMES:
            return
        self._theme_key = key
        self._style_switcher_buttons()
        self._apply_chrome()
        self._render_body()

    def _apply_chrome(self) -> None:
        t = self.theme
        page_bg = t.page_bg or t.bg
        self._content.setObjectName("dashContent")
        self._scroll.setStyleSheet(f"QScrollArea{{background:{t.bg};border:none;}}")
        self._content.setStyleSheet(f"QWidget#dashContent{{background:{page_bg};}}")
        self._filter_bar.setStyleSheet(
            f"QFrame#filterBar{{background:{t.card};border:1px solid {t.line};border-radius:{t.radius}px;}}"
            f"QLabel#filterHeading{{color:{t.text};font-family:'{t.display_font}';font-size:18px;font-weight:900;}}"
            f"QLabel#fieldLabel{{color:{t.muted};font-family:'{t.body_font}';font-size:11px;font-weight:800;}}"
            f"QDateEdit{{background:{t.soft};color:{t.text};border:1px solid {t.line};border-radius:9px;"
            "padding:5px 8px;font-family:'Cairo';font-size:13px;font-weight:700;}"
            f"QPushButton#applyBtn{{background:{t.accent};color:{t.accent_text};border:none;border-radius:9px;"
            "padding:8px 18px;font-family:'Cairo';font-weight:900;font-size:13px;}"
            f"QPushButton#resetBtn{{background:{t.soft};color:{t.text};border:1px solid {t.line};border-radius:9px;"
            "padding:8px 16px;font-family:'Cairo';font-weight:800;font-size:13px;}"
        )

    # --- data ---------------------------------------------------------------
    def _selected_range(self) -> tuple[str, str]:
        return (
            self.date_from.date().toString("yyyy-MM-dd"),
            self.date_to.date().toString("yyyy-MM-dd"),
        )

    def refresh_dashboard(self) -> None:
        date_from, date_to = self._selected_range()
        try:
            self._data = self.service.load(date_from, date_to)
        except Exception:  # noqa: BLE001 - never crash the shell
            logger.exception("Executive dashboard: load failed")
            self._data = None
            QMessageBox.warning(
                self, "تعذر تحميل الداشبورد", "حدث خطأ أثناء تحميل بيانات الداشبورد."
            )
            return
        self._render_body()

    # --- body render (theme-driven) ----------------------------------------
    def _render_body(self) -> None:
        self._clear(self._body_layout)
        if self._data is None:
            return
        t = self.theme
        self._body_layout.addWidget(self._build_kpis(t))
        # The chart row is the only elastic band — it absorbs all spare height so
        # the whole dashboard fits one screen with no vertical scroll.
        self._body_layout.addWidget(self._build_main_row(t), 1)
        self._body_layout.addWidget(self._build_sub_row(t))
        self._body_layout.addWidget(self._build_bottom_header(t))

    # ----- KPI row ----------------------------------------------------------
    def _build_kpis(self, t: Theme) -> QWidget:
        counts = self._data["counts"]
        cards = [
            ("👥", "عدد العملاء", f"{counts['customers']:,}", "▲ 6%"),
            ("🚚", "عدد الموردين", f"{counts['suppliers']:,}", "▲ 3%"),
            ("📦", "عدد الأصناف", f"{counts['products']:,}", "▲ 9%"),
            ("💵", "إجمالي سندات القبض", money(self._data["receipt_total"]), "▲ 14%"),
        ]
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(15 if not t.dense else 11)
        for idx, (icon, label, value, trend) in enumerate(cards):
            row.addWidget(self._kpi_card(t, idx, icon, label, value, trend), 1)
        return wrap

    def _kpi_card(self, t: Theme, idx: int, icon: str, label: str, value: str, trend: str) -> QFrame:
        card = QFrame()
        bg = t.kpi_gradients[idx] if idx < len(t.kpi_gradients) else t.card
        colored = idx < len(t.kpi_gradients) and bool(t.kpi_text)
        border = "none" if colored else f"1px solid {t.card_border or t.line}"
        top_accent = f"border-top:3px solid {t.accent};" if t.kpi_top_accent else ""
        card.setStyleSheet(
            f"QFrame{{background:{bg};border:{border};{top_accent}border-radius:{t.radius}px;}}"
        )
        self._shadow(card, t)
        box = QVBoxLayout(card)
        pad = 11 if t.dense else 13
        box.setContentsMargins(16, pad, 16, pad)
        box.setSpacing(5 if t.dense else 7)

        text_color = t.kpi_text or t.text
        muted_color = t.kpi_text or t.muted
        value_color = t.accent if (t.kpi_value_accent and not colored) else text_color

        head = QHBoxLayout()
        head.setDirection(QBoxLayout.RightToLeft)
        if not t.hide_kpi_icon:
            icon_bg = t.kpi_icon_bgs[idx] if idx < len(t.kpi_icon_bgs) else t.kpi_icon_bg
            icon_fg = "#FFFFFF" if (idx < len(t.kpi_icon_bgs) and t.kpi_icon_bgs) else t.kpi_icon_fg
            badge = QLabel(icon)
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(34, 34)
            badge.setStyleSheet(
                f"background:{icon_bg};color:{icon_fg};border:none;border-radius:11px;font-size:18px;"
            )
            head.addWidget(badge)
        head.addStretch(1)
        trend_label = QLabel(trend)
        trend_label.setStyleSheet(
            f"color:{muted_color if colored else t.trend};font-family:'Cairo';"
            "font-size:12px;font-weight:800;border:none;background:transparent;"
        )
        head.addWidget(trend_label)

        value_label = QLabel(value)
        value_label.setAlignment(Qt.AlignRight)
        value_label.setStyleSheet(
            f"color:{value_color};font-family:'{t.display_font}';"
            f"font-size:{20 if t.dense else 22}px;font-weight:900;border:none;background:transparent;"
        )
        name_label = QLabel(label)
        name_label.setAlignment(Qt.AlignRight)
        name_label.setStyleSheet(
            f"color:{muted_color};font-family:'{t.body_font}';font-size:13px;font-weight:700;"
            "border:none;background:transparent;"
        )
        box.addLayout(head)
        box.addWidget(value_label)
        box.addWidget(name_label)
        return card

    # ----- main row: chart + top customers + top suppliers ------------------
    def _build_main_row(self, t: Theme) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(15)

        # sales/purchases chart card
        chart_card, chart_box = self._card(t, min_height=220)
        header = QHBoxLayout()
        header.setDirection(QBoxLayout.RightToLeft)
        header.addWidget(self._card_title(t, "المبيعات والمشتريات — آخر الشهور"))
        header.addStretch(1)
        header.addWidget(self._legend_dot(t.sales, "مبيعات", t))
        header.addWidget(self._legend_dot(t.purchase, "مشتريات", t))
        chart_box.addLayout(header)
        chart = GroupedBarChart()
        chart.set_data(self._data["monthly"], t)
        chart_box.addWidget(chart, 1)
        row.addWidget(chart_card, 2)

        row.addWidget(self._hbar_panel(t, "أعلى ٥ عملاء (مبيعات)", self._data["top_customers"], t.cust), 1)
        row.addWidget(self._hbar_panel(t, "أعلى ٥ موردين", self._data["top_suppliers"], t.supp), 1)
        return wrap

    def _hbar_panel(self, t: Theme, title: str, items: list[dict[str, Any]], color: str) -> QFrame:
        card, box = self._card(t, min_height=196)
        box.addWidget(self._card_title(t, title))
        if not items:
            box.addWidget(self._empty_label(t), 1)
            return card
        peak = max((it["value"] for it in items), default=1.0) or 1.0
        for it in items:
            box.addWidget(self._hbar_row(t, it["name"], it["value"], peak, color))
        box.addStretch(1)
        return card

    def _hbar_row(self, t: Theme, name: str, value: float, peak: float, color: str) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 1, 0, 1)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.setDirection(QBoxLayout.RightToLeft)
        name_label = QLabel(name)
        name_label.setStyleSheet(
            f"color:{t.text};font-family:'{t.body_font}';font-size:12px;font-weight:700;border:none;"
        )
        value_label = QLabel(money(value))
        value_label.setStyleSheet(
            f"color:{t.muted};font-family:'Cairo';font-size:12px;font-weight:800;border:none;"
        )
        top.addWidget(name_label)
        top.addStretch(1)
        top.addWidget(value_label)

        track = QFrame()
        track.setFixedHeight(8)
        track.setStyleSheet(f"background:{t.line};border:none;border-radius:4px;")
        track_lay = QHBoxLayout(track)
        track_lay.setContentsMargins(0, 0, 0, 0)
        track_lay.setSpacing(0)
        track_lay.setDirection(QBoxLayout.RightToLeft)
        fill = QFrame()
        fill.setStyleSheet(f"background:{color};border:none;border-radius:5px;")
        units = max(0, min(1000, int(round(value / peak * 1000))))
        track_lay.addWidget(fill, units)
        track_lay.addStretch(1000 - units)

        lay.addLayout(top)
        lay.addWidget(track)
        return wrap

    # ----- sub row: production + loading ------------------------------------
    def _build_sub_row(self, t: Theme) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(15)

        prod = self._data["production"]
        prod_card, prod_box = self._card(t)
        prod_box.addWidget(self._card_title(t, "🏭 أوامر الإنتاج والكميات"))
        stats = QHBoxLayout()
        stats.setDirection(QBoxLayout.RightToLeft)
        stats.setSpacing(12)
        stats.addWidget(self._stat(t, qty(prod["produced_qty"]), "عدد الكميات المنتجة (وحدة)"))
        stats.addWidget(self._stat(t, qty(prod["top_item_qty"]), f"أعلى صنف: {prod['top_item_name']}"))
        stats.addWidget(self._stat(t, money(prod["raw_cost"]), "إجمالي تكاليف المواد الخام"))
        prod_box.addLayout(stats)
        row.addWidget(prod_card, 3)

        load = self._data["loading"]
        kind = "بعد التحميل" if load["weight_kind"] == "after" else "قبل التحميل"
        load_card, load_box = self._card(t)
        load_box.addWidget(self._card_title(t, "🚛 سندات التحميل"))
        lstats = QHBoxLayout()
        lstats.setDirection(QBoxLayout.RightToLeft)
        lstats.setSpacing(12)
        weight_txt = f"أكبر وزن {kind} · {qty(load['weight_value'])} كجم"
        lstats.addWidget(self._stat(t, f"سيارة {load['weight_vehicle']}", weight_txt))
        lstats.addWidget(
            self._stat(t, f"سيارة {load['count_vehicle']}", f"أكثر سيارة سندات · {load['count_value']} سند")
        )
        load_box.addLayout(lstats)
        row.addWidget(load_card, 2)
        return wrap

    def _stat(self, t: Theme, value: str, label: str) -> QFrame:
        block = QFrame()
        block.setStyleSheet(f"background:{t.soft};border:none;border-radius:11px;")
        box = QVBoxLayout(block)
        box.setContentsMargins(14, 11, 14, 11)
        box.setSpacing(4)
        value_label = QLabel(value)
        value_label.setAlignment(Qt.AlignRight)
        value_label.setWordWrap(True)
        value_label.setStyleSheet(
            f"color:{t.text};font-family:'{t.display_font}';font-size:18px;font-weight:900;border:none;"
        )
        label_label = QLabel(label)
        label_label.setAlignment(Qt.AlignRight)
        label_label.setWordWrap(True)
        label_label.setStyleSheet(
            f"color:{t.muted};font-family:'{t.body_font}';font-size:12px;font-weight:700;border:none;"
        )
        box.addWidget(value_label)
        box.addWidget(label_label)
        return block

    # ----- bottom header (pinned last) --------------------------------------
    def _build_bottom_header(self, t: Theme) -> QFrame:
        rng = self._data["range"]
        totals = self._data["totals"]
        period = self._period_text(rng)

        header = QFrame()
        header.setMaximumHeight(74)
        header.setStyleSheet(
            f"QFrame{{background:{t.header_bg or t.accent};border:none;border-radius:14px;}}"
        )
        self._shadow(header, t)
        row = QHBoxLayout(header)
        row.setDirection(QBoxLayout.RightToLeft)
        row.setContentsMargins(20, 12, 20, 12)
        row.setSpacing(16)

        logo = QLabel("A-H")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(44, 44)
        logo.setStyleSheet(
            f"background:{t.header_logo_bg};color:{t.header_text};border:none;"
            "border-radius:12px;font-family:'Cairo';font-size:15px;font-weight:900;"
        )
        brand_box = QVBoxLayout()
        brand_box.setSpacing(2)
        name = QLabel("A-H CODE للحلول البرمجية")
        name.setStyleSheet(
            f"color:{t.header_text};font-family:'{t.display_font}';font-size:16px;font-weight:900;border:none;"
        )
        sub = QLabel(f"لوحة المعلومات التنفيذية · {period}")
        sub.setStyleSheet(
            f"color:{t.header_text};font-family:'{t.body_font}';font-size:11px;font-weight:600;border:none;"
        )
        brand_box.addWidget(name)
        brand_box.addWidget(sub)

        brand_wrap = QHBoxLayout()
        brand_wrap.setDirection(QBoxLayout.RightToLeft)
        brand_wrap.setSpacing(12)
        brand_wrap.addWidget(logo)
        brand_wrap.addLayout(brand_box)

        row.addLayout(brand_wrap)
        row.addStretch(1)
        row.addWidget(self._header_total(t, "إجمالي المبيعات", money(totals["sales"])))
        row.addWidget(self._header_total(t, "إجمالي المشتريات", money(totals["purchases"])))
        return header

    def _header_total(self, t: Theme, label: str, value: str) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        label_label = QLabel(label)
        label_label.setAlignment(Qt.AlignRight)
        label_label.setStyleSheet(
            f"color:{t.header_text};font-family:'{t.body_font}';font-size:11px;font-weight:600;border:none;"
        )
        value_label = QLabel(value)
        value_label.setAlignment(Qt.AlignRight)
        value_label.setStyleSheet(
            f"color:{t.header_text};font-family:'Cairo';font-size:17px;font-weight:900;border:none;"
        )
        lay.addWidget(label_label)
        lay.addWidget(value_label)
        return box

    # --- small shared builders ---------------------------------------------
    def _card(self, t: Theme, min_height: int | None = None) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        # RTL: the leading (right) edge carries the accent stripe when requested.
        accent_edge = f"border-right:3px solid {t.accent};" if t.card_accent else ""
        card.setStyleSheet(
            f"QFrame{{background:{t.card};border:1px solid {t.card_border or t.line};"
            f"{accent_edge}border-radius:{t.radius}px;}}"
        )
        if min_height:
            card.setMinimumHeight(int(min_height * (0.85 if t.dense else 1)))
        self._shadow(card, t)
        box = QVBoxLayout(card)
        pad = 12 if t.dense else 15
        box.setContentsMargins(18, pad, 18, pad)
        box.setSpacing(8 if t.dense else 9)
        return card, box

    def _card_title(self, t: Theme, text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignRight)
        rule = f"border-bottom:1px solid {t.line};padding-bottom:8px;" if t.title_rule else "border:none;"
        label.setStyleSheet(
            f"color:{t.text};font-family:'{t.display_font}';font-size:{17 if t.title_rule else 15}px;"
            f"font-weight:900;background:transparent;{rule}"
        )
        return label

    def _legend_dot(self, color: str, text: str, t: Theme) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.setDirection(QBoxLayout.RightToLeft)
        dot = QLabel()
        dot.setFixedSize(11, 11)
        dot.setStyleSheet(f"background:{color};border:none;border-radius:5px;")
        label = QLabel(text)
        label.setStyleSheet(
            f"color:{t.muted};font-family:'{t.body_font}';font-size:12px;font-weight:700;border:none;"
        )
        lay.addWidget(dot)
        lay.addWidget(label)
        return box

    def _empty_label(self, t: Theme) -> QLabel:
        label = QLabel(NO_DATA)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            f"color:{t.muted};font-family:'{t.body_font}';font-size:13px;font-weight:700;border:none;"
        )
        return label

    def _shadow(self, widget: QWidget, t: Theme) -> None:
        if not t.shadow:
            return
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(18)
        effect.setXOffset(0)
        effect.setYOffset(3)
        effect.setColor(QColor(15, 23, 42, 30))
        widget.setGraphicsEffect(effect)

    @staticmethod
    def _period_text(rng: dict[str, Any]) -> str:
        date_from = rng.get("date_from") or "—"
        date_to = rng.get("date_to") or "—"
        return f"الفترة من {date_from} إلى {date_to}"

    @staticmethod
    def _clear(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()


__all__ = ["ExecutiveDashboardPage", "Theme", "THEMES", "MODELS"]
