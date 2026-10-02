"""داشبورد المقاولين — نموذج 9 «داكن تنفيذي» and نموذج 8 «لوحة الترتيب» as two tabs
(user, 2026-10-02), so the user picks one by using both.

The filter bar is the contracting reports' one: من/إلى، الشركة، المشروع، المقاول.
Every figure comes from ``contractors_dashboard_service``.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.contractors_dashboard_service import (
    PAYMENT_METHODS,
    ContractorsDashboardService,
    empty_dashboard,
)
from app.ui.common.theme import GREEN, TEXT
from app.ui.screens.contracting_report_base import MUTED, RED, ContractingReportBase
from app.ui.screens.contractor_contracts_screen import _money

PERMISSION_BASE = "contracting.contractors_dashboard"
TAB_DARK, TAB_LEADERS = 0, 1
RANK_ROWS = 5  # rows under each board's winner

# Tile looks: (background, border, caption, value, negative value)
LOOKS = {
    "hero": ("#16303A", "#234552", "#A9C3CA", "#FFFFFF", "#FCA5A5"),
    "dark": ("#183540", "#183540", "#93A6AD", "#FFFFFF", "#FCA5A5"),
    "teal": ("#0E5A66", "#0E5A66", "#CFE4E6", "#FFFFFF", "#FECACA"),
    "gold": ("#E2B65E", "#E2B65E", "#4A3509", "#1C1406", RED),
    "white": ("#FFFFFF", "#E5EAF0", MUTED, TEXT, RED),
    "green": (GREEN, GREEN, "#DCFCE7", "#FFFFFF", "#FECACA"),
}
DARK_BG, PANEL_BG, PANEL_BORDER = "#0F1C22", "#132830", "#21404B"
WIN_BG, WIN_BORDER, GOLD = "#FBF4E6", "#EBD9B4", "#C0862A"


def _count(value: int, one: str) -> str:
    return f"{value} {one}"


def _short(value: Any) -> str:
    return f"{float(value):,.0f}"


class Tile(QFrame):
    """A caption, a value and a hint, in one of ``LOOKS``."""

    def __init__(self, caption: str, look: str = "dark", value_size: int = 18) -> None:
        super().__init__()
        self.look = LOOKS[look]
        background, border, caption_color, value_color, _negative = self.look
        self.setObjectName("tile")
        self.setStyleSheet(
            f"QFrame#tile {{ background:{background}; border:1px solid {border}; border-radius:10px; }}"
            "QLabel { background:transparent; border:none; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(1)
        self.caption = QLabel(caption)
        self.caption.setStyleSheet(f"font-size:12px; font-weight:800; color:{caption_color};")
        self.value = QLabel("0")
        self._value_style = f"font-size:{value_size}px; font-weight:900; color:{value_color};"
        self.value.setStyleSheet(self._value_style)
        self.hint = QLabel("")
        self.hint.setStyleSheet(f"font-size:11px; font-weight:700; color:{caption_color};")
        for label in (self.caption, self.hint):
            # a long name is cut, never widens the grid
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.caption)
        layout.addWidget(self.value)
        layout.addWidget(self.hint)

    def set(self, value: str, hint: str = "", negative: bool = False) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(self._value_style + (f" color:{self.look[4]};" if negative else ""))
        self.hint.setText(hint)
        self.hint.setToolTip(hint)


def _panel(title: str, dark: bool) -> tuple[QFrame, QGridLayout]:
    frame = QFrame()
    frame.setObjectName("panel")
    background, border, color = (PANEL_BG, PANEL_BORDER, "#CFE0E4") if dark else ("#FFFFFF", "#E5EAF0", TEXT)
    frame.setStyleSheet(
        f"QFrame#panel {{ background:{background}; border:1px solid {border}; border-radius:12px; }}"
        "QLabel { background:transparent; border:none; }"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 10, 14, 12)
    layout.setSpacing(8)
    caption = QLabel(title)
    caption.setStyleSheet(f"font-size:14px; font-weight:900; color:{color};")
    layout.addWidget(caption)
    grid = QGridLayout()
    grid.setSpacing(8)
    layout.addLayout(grid, 1)
    return frame, grid


class RankRow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(2)
        self.rank = QLabel("")
        self.rank.setFixedWidth(22)
        self.rank.setAlignment(Qt.AlignCenter)
        self.rank.setStyleSheet(f"font-size:13px; font-weight:900; color:{MUTED};")
        self.name = QLabel("")
        self.name.setStyleSheet(f"font-size:13px; font-weight:800; color:{TEXT};")
        self.sub = QLabel("")
        self.sub.setStyleSheet(f"font-size:11px; font-weight:700; color:{MUTED};")
        for label in (self.name, self.sub):
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.amount = QLabel("")
        self.amount.setStyleSheet(f"font-size:13px; font-weight:900; color:{TEXT};")
        layout.addWidget(self.rank, 0, 0, 3, 1)
        layout.addWidget(self.name, 0, 1)
        layout.addWidget(self.sub, 1, 1)
        layout.addWidget(self.bar, 2, 1)
        layout.addWidget(self.amount, 0, 2, 3, 1, Qt.AlignVCenter)
        layout.setColumnStretch(1, 1)

    def set(self, rank: int, name: str, sub: str, amount: Any, top: Any) -> None:
        self.rank.setText(str(rank))
        self.name.setText(name)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))
        self.amount.setText(_money(amount))
        share = float(amount) / float(top) if top and float(top) > 0 else 0.0
        self.bar.setValue(int(max(0.0, min(share, 1.0)) * 1000))
        self.bar.setStyleSheet(
            "QProgressBar { background:#EEECE6; border:none; border-radius:3px; }"
            f"QProgressBar::chunk {{ background:{GOLD if rank == 1 else GREEN}; border-radius:3px; }}"
        )


class RankBoard(QFrame):
    """A board of نموذج 8: the winner in a gold box, then the next ``RANK_ROWS``."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("board")
        self.setStyleSheet(
            "QFrame#board { background:#FFFFFF; border:1px solid #E5EAF0; border-radius:12px; }"
            "QLabel { background:transparent; border:none; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)
        caption = QLabel(title)
        caption.setStyleSheet(f"font-size:14px; font-weight:900; color:{TEXT};")
        layout.addWidget(caption)
        winner = QFrame()
        winner.setObjectName("winner")
        winner.setStyleSheet(f"QFrame#winner {{ background:{WIN_BG}; border:1px solid {WIN_BORDER}; border-radius:10px; }}")
        row = QHBoxLayout(winner)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(12)
        crown = QLabel("👑")
        crown.setFixedSize(40, 40)
        crown.setAlignment(Qt.AlignCenter)
        crown.setStyleSheet(f"background:{GOLD}; border-radius:20px; font-size:18px;")
        names = QVBoxLayout()
        names.setSpacing(1)
        self.win_name = QLabel("")
        self.win_name.setStyleSheet(f"font-size:15px; font-weight:900; color:{TEXT};")
        self.win_sub = QLabel("")
        self.win_sub.setStyleSheet(f"font-size:11px; font-weight:700; color:{MUTED};")
        for label in (self.win_name, self.win_sub):
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        names.addWidget(self.win_name)
        names.addWidget(self.win_sub)
        self.win_amount = QLabel("")
        self.win_amount.setStyleSheet(f"font-size:19px; font-weight:900; color:{TEXT};")
        row.addWidget(crown)
        row.addLayout(names, 1)
        row.addWidget(self.win_amount)
        layout.addWidget(winner)
        self.rows = [RankRow() for _ in range(RANK_ROWS)]
        for rank_row in self.rows:
            layout.addWidget(rank_row)
        layout.addStretch(1)

    def set(self, entries: list[tuple[str, str, Any]], empty: str) -> None:
        """*entries*: (name, sub line, amount), biggest first."""
        if entries:
            name, sub, amount = entries[0]
            self.win_name.setText(name)
            self.win_sub.setText(sub)
            self.win_amount.setText(_money(amount))
        else:
            self.win_name.setText("—")
            self.win_sub.setText(empty)
            self.win_amount.setText("")
        top = entries[0][2] if entries else 0
        for index, rank_row in enumerate(self.rows):
            entry = entries[index + 1] if index + 1 < len(entries) else None
            rank_row.setVisible(entry is not None)
            if entry:
                rank_row.set(index + 2, *entry, top=top)


class ContractorsDashboardScreen(ContractingReportBase):
    TITLE = "داشبورد المقاولين"
    ICON = "📊"
    PERMISSION_BASE = PERMISSION_BASE

    def __init__(self, service: ContractorsDashboardService | None = None, parent: QWidget | None = None) -> None:
        self.dashboard: dict[str, Any] = empty_dashboard()
        super().__init__(service or ContractorsDashboardService(), parent)

    # -- layout ------------------------------------------------------------------------

    def _build_body(self, root: QVBoxLayout) -> None:
        self.show_button.setText("عرض")
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border:none; }"
            "QTabBar::tab { padding:7px 18px; font-size:13px; font-weight:800; color:#475569; background:#EEF2F6; "
            "border:1px solid #E5EAF0; border-bottom:none; border-top-left-radius:7px; border-top-right-radius:7px; "
            "margin-left:4px; }"
            f"QTabBar::tab:selected {{ background:{GREEN}; color:#FFFFFF; border-color:{GREEN}; }}"
        )
        self.tabs.addTab(self._build_dark_tab(), "نموذج 9 — داكن تنفيذي")
        self.tabs.addTab(self._build_leaders_tab(), "نموذج 8 — لوحة الترتيب")
        root.addWidget(self.tabs, 1)

    def _build_dark_tab(self) -> QFrame:
        page = QFrame()
        page.setObjectName("darkPage")
        page.setStyleSheet(f"QFrame#darkPage {{ background:{DARK_BG}; border-radius:10px; }}")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        hero = QHBoxLayout()
        hero.setSpacing(12)
        self.hero = {key: Tile(caption, "hero", 26) for key, caption in (
            ("contractors", "👷 المقاولين"), ("companies", "🏢 الشركات والمشاريع"), ("contracts", "🤝 العقود"),
            ("extracts", "🧾 المستخلصات"), ("payments", "💵 الدفعات"))}
        for tile in self.hero.values():
            hero.addWidget(tile, 1)
        layout.addLayout(hero)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.dark: dict[str, Tile] = {}
        panels = (
            ("👷 المقاولين — الضرائب والتأمينات والخصومات", 3, (
                ("c_balance", "إجمالي الرصيد الجاري", "teal"),
                ("c_withholding", "إجمالي ضرائب الخصم والإضافة", "dark"),
                ("c_social", "إجمالي التأمينات الاجتماعية", "dark"),
                ("c_works", "إجمالي تأمين الأعمال", "dark"),
                ("c_other", "إجمالي الخصومات الأخرى", "dark"),
                ("c_total", "الإجمالي", "dark"))),
            ("🤝 عقود المقاولين", 3, (
                ("k_biggest", "أكبر عقد", "gold"),
                ("k_advance", "إجمالي الدفعات المقدمة", "dark"),
                ("k_works", "إجمالي تأمين الأعمال", "dark"),
                ("k_value", "قيمة العقود", "teal"),
                ("k_tax", "إجمالي الضرائب والخصومات", "dark"),
                ("k_social", "إجمالي التأمينات المستقطعة", "dark"))),
            ("🧾 مستخلصات المقاولين", 4, (
                ("x_total", "إجمالي المستخلص", "teal"),
                ("x_before_tax", "إجمالي صافي الأعمال", "dark"),
                ("x_advance", "إجمالي الدفعة المقدمة", "dark"),
                ("x_withholding", "إجمالي ضرائب الخصم", "dark"),
                ("x_works", "إجمالي تأمين الأعمال", "dark"),
                ("x_social", "إجمالي التأمينات الاجتماعية", "dark"),
                ("x_other", "إجمالي الخصومات الأخرى", "dark"),
                ("x_net", "صافي المستخلصات", "dark"))),
            ("💵 دفعات المقاولين", 3, (
                ("p_total", "إجمالي الدفعات المدفوعة", "teal"),
                ("p_top", "أكبر مقاول أخد فلوس", "gold"),
                ("p_remaining", "المتبقي للمقاولين", "dark"),
                *((f"p_{method}", f"دفعات {method}", "dark") for method in PAYMENT_METHODS))),
        )
        for index, (title, columns, tiles) in enumerate(panels):
            frame, inner = _panel(title, dark=True)
            for position, (key, caption, look) in enumerate(tiles):
                tile = Tile(caption, look)
                self.dark[key] = tile
                inner.addWidget(tile, position // columns, position % columns)
            grid.addWidget(frame, index // 2, index % 2)
        layout.addLayout(grid, 1)
        return page

    def _build_leaders_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)
        strip = QHBoxLayout()
        strip.setSpacing(10)
        self.strip = {key: Tile(caption, "green" if key == "payments" else "white", 20) for key, caption in (
            ("contractors", "عدد المقاولين"), ("companies", "الشركات / المشاريع"), ("contracts", "عدد العقود"),
            ("extracts", "عدد المستخلصات"), ("payments", "إجمالي الدفعات"),
            ("balance", "الرصيد الجاري للمقاولين"))}
        for tile in self.strip.values():
            strip.addWidget(tile, 1)
        layout.addLayout(strip)

        boards = QHBoxLayout()
        boards.setSpacing(10)
        self.board_contracts = RankBoard("🤝 أكبر العقود")
        self.board_extracts = RankBoard("🧾 أعلى المقاولين في صافي المستخلصات")
        self.board_payments = RankBoard("💵 أكثر المقاولين قبضًا")
        for board in (self.board_contracts, self.board_extracts, self.board_payments):
            boards.addWidget(board, 1)
        layout.addLayout(boards, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.minis: dict[str, QLabel] = {}
        for title, columns, items in (
            ("👷 شاشة المقاولين", 4, (
                ("c_withholding", "ضرائب الخصم والإضافة"), ("c_social", "التأمينات الاجتماعية"),
                ("c_works", "تأمين الأعمال"), ("c_other", "الخصومات الأخرى"))),
            ("🤝 العقود", 4, (
                ("k_advance", "الدفعات المقدمة"), ("k_works", "تأمين الأعمال"),
                ("k_tax", "الضرائب والخصومات"), ("k_social", "التأمينات المستقطعة"))),
            ("🧾 المستخلصات", 3, (
                ("x_before_tax", "صافي الأعمال"), ("x_advance", "الدفعة المقدمة"), ("x_withholding", "ضرائب الخصم"),
                ("x_works", "تأمين الأعمال"), ("x_social", "التأمينات"), ("x_other", "خصومات أخرى"))),
        ):
            frame, inner = _panel(title, dark=False)
            inner.setVerticalSpacing(4)
            for position, (key, caption) in enumerate(items):
                cell = QVBoxLayout()
                cell.setSpacing(0)
                label = QLabel(caption)
                label.setStyleSheet(f"font-size:11px; font-weight:700; color:{MUTED};")
                value = QLabel("0.00")
                value.setStyleSheet(f"font-size:14px; font-weight:900; color:{TEXT};")
                for part in (label, value):  # both fill the cell and sit on its right, so they line up
                    part.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                    part.setAlignment(Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignVCenter)
                cell.addWidget(label)
                cell.addWidget(value)
                inner.addLayout(cell, position // columns, position % columns)
                self.minis[key] = value
            bottom.addWidget(frame, 1)
        layout.addLayout(bottom)
        return page

    # -- running -----------------------------------------------------------------------

    def run_report(self) -> None:
        self.dashboard = self.service.dashboard(**self.filters())
        self._fill_dark()
        self._fill_leaders()

    def _amounts(self) -> dict[str, Any]:
        """The amounts both tabs show, by tile key."""
        c, k, x = self.dashboard["contractors"], self.dashboard["contracts"], self.dashboard["extracts"]
        return {
            "c_withholding": c["withholding_tax"], "c_social": c["social_insurance"],
            "c_works": c["works_insurance"], "c_other": c["other_deductions"],
            "k_advance": k["advance"], "k_works": k["works_insurance"], "k_tax": k["tax"], "k_social": k["social"],
            "x_before_tax": x["before_tax"], "x_advance": x["advance_payment"], "x_withholding": x["withholding_tax"],
            "x_works": x["works_insurance"], "x_social": x["social_insurance"], "x_other": x["other_deductions"],
        }

    def _companies_text(self) -> tuple[str, str]:
        companies = self.dashboard["companies"]
        value = f"{companies['count']} شركات · {companies['projects']} مشاريع"
        hint = " · ".join(f"{name} {count}" for name, count in companies["per_company"])
        return value, hint

    def _fill_dark(self) -> None:
        d = self.dashboard
        c, k, x, p = d["contractors"], d["contracts"], d["extracts"], d["payments"]
        self.hero["contractors"].set(str(c["count"]), f"رصيد جاري {_money(c['balance'])}")
        self.hero["companies"].set(*self._companies_text())
        self.hero["contracts"].set(str(k["count"]), f"بقيمة {_money(k['value'])}")
        self.hero["extracts"].set(str(x["count"]), f"إجمالي {_money(x['works_value'])}")
        self.hero["payments"].set(str(p["count"]), f"مدفوع {_money(p['total'])}")

        for key, value in self._amounts().items():
            if key in self.dark:
                self.dark[key].set(_money(value), negative=value < 0)
        self.dark["c_balance"].set(_money(c["balance"]), "رصيد أول المدة", c["balance"] < 0)
        self.dark["c_total"].set(_money(c["deductions"]), "الضرائب والتأمينات والخصومات")
        biggest = k["biggest"]
        if biggest:
            self.dark["k_biggest"].set(_money(biggest["contract_value"]), biggest.get("contractor_name") or "")
        else:
            self.dark["k_biggest"].set("—", "لا توجد عقود")
        self.dark["k_value"].set(_money(k["value"]), _count(k["count"], "عقود"))
        self.dark["x_total"].set(_money(x["works_value"]), "بعد الضريبة")
        self.dark["x_net"].set(_money(x["net"]), _count(x["count"], "مستخلصات"), x["net"] < 0)
        self.dark["p_total"].set(_money(p["total"]), _count(p["count"], "دفعة"))
        top = p["top"]
        if top:
            self.dark["p_top"].set(_money(top[1]), f"{top[0]} · {_count(top[2], 'دفعات')}")
        else:
            self.dark["p_top"].set("—", "لا توجد دفعات")
        self.dark["p_remaining"].set(_money(p["remaining"]), "صافي المستخلصات − الدفعات", p["remaining"] < 0)
        for method in PAYMENT_METHODS:
            total, count = p["methods"].get(method, (0, 0))
            self.dark[f"p_{method}"].set(_money(total), _count(count, "دفعات"))

    def _fill_leaders(self) -> None:
        d = self.dashboard
        c, k, x, p = d["contractors"], d["contracts"], d["extracts"], d["payments"]
        companies = d["companies"]
        self.strip["contractors"].set(str(c["count"]), "مقاول مسجل")
        self.strip["companies"].set(f"{companies['count']} شركات · {companies['projects']} مشاريع",
                                    " · ".join(f"{name} {count}" for name, count in companies["per_company"]))
        self.strip["contracts"].set(str(k["count"]), f"بقيمة {_short(k['value'])}")
        self.strip["extracts"].set(str(x["count"]), f"إجمالي {_short(x['works_value'])}")
        self.strip["payments"].set(_money(p["total"]), _count(p["count"], "دفعة"))
        self.strip["balance"].set(_money(c["balance"]), "رصيد أول المدة", c["balance"] < 0)

        contracts = [(line.get("contractor_name") or "", f"{line.get('contract_no') or ''} · {line.get('project_name') or ''}",
                      line["contract_value"]) for line in k["ranking"]]
        if contracts:
            name, sub, value = contracts[0]
            contracts[0] = (name, f"أكبر عقد · {sub}", value)
        self.board_contracts.set(contracts, "لا توجد عقود")
        self.board_extracts.set([(name, "", net) for name, net in x["ranking"]], "لا توجد مستخلصات")
        payments = [(name, _count(count, "دفعات"), total) for name, total, count in p["ranking"]]
        if payments:
            name, sub, total = payments[0]
            payments[0] = (name, f"أكبر مقاول أخد فلوس · {sub}", total)
        self.board_payments.set(payments, "لا توجد دفعات")

        for key, value in self._amounts().items():
            label = self.minis[key]
            label.setText(_money(value))
            label.setStyleSheet(f"font-size:14px; font-weight:900; color:{RED if value < 0 else TEXT};")
