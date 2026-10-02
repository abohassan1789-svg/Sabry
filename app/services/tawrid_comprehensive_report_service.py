"""التقرير الشامل — قسم التوريدات (Tawrid comprehensive report).

Not an account statement. It re-creates the Access report **``ReportAll``**
(«تقرير شامل»), whose RecordSource is the saved query ``ReportAll`` over
**``TBBOOn`` only** — a flat **detail listing over the tickets (البونات)**, with
no vouchers, no opening balance, no carry-forward, no running balance and no
donut. Verified via Access COM against the running ``.accdb``: the query filters
``TBBOOn`` by **five optional criteria**, each ``= param OR param IS NULL`` so a
blank filter matches everything:

* التاريخ ``date123 BETWEEN d1 AND d2``,
* المورد/الكسّارة ``[res-id] = st1``,
* العميل ``cus_id = a1``,
* الجرار/المقطورة ``maatora_id = x2``,
* الصنف ``productName = a2``.

Every row carries all **three price layers** side by side (customer / hauler /
crusher), and the report footer carries **five totals** — the Access controls
``r1 = Sum(totalCus)``, ``s1 = Sum(totalman)``, ``Text165 = Sum(totalres)``,
``v1 = Sum(Tak3ib)`` and ``Text131 = Sum(Tak3ibres)``.

Our sources (all migrated on SiskoDB): ``tawrid_tickets`` LEFT-joined to
``tawrid_suppliers`` (المورد), ``tawrid_customers`` (العميل) and
``tawrid_tractors`` (المقطورة/السائق). The item filter is on the free-text
``item_name`` directly (Access ``productName``).

No presentation logic lives here: it returns values, and the screen formats them.
The service and data shape are new (unlike the three statements, this is not
config-driven), but the column model + ``export_rows`` follow the same style as
:mod:`app.services.tawrid_customer_statement_service` so the shared Excel export
and the print module can consume it unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.database.db import Database


# -- column model (also drives the Excel export + the print column chooser) ------


@dataclass(frozen=True)
class ReportColumn:
    """One detail column: its ``key`` in an export row and its Arabic ``label``.

    ``money`` marks a two-decimal currency column, ``volume`` a trimmed-zeros
    cubing column; the rest are plain text. ``align`` is the on-screen /print
    alignment.
    """

    key: str
    label: str
    money: bool = False
    volume: bool = False
    align: str = "center"


# The detail columns, right-to-left as the screen shows them — the three price
# layers (customer / hauler / crusher) between the identity columns, matching the
# Access ``ReportAll`` detail band.
REPORT_COLUMNS: tuple[ReportColumn, ...] = (
    ReportColumn("serial", "م"),
    ReportColumn("date", "التاريخ"),
    ReportColumn("item", "اسم الصنف", align="right"),
    ReportColumn("price_cus", "سعر العميل", money=True),
    ReportColumn("cus_volume", "تكعيب العميل", volume=True),
    ReportColumn("total_cus", "تكلفة العميل", money=True),
    ReportColumn("price_man", "سعر السائق", money=True),
    ReportColumn("total_man", "تكلفة السائق", money=True),
    ReportColumn("price_res", "سعر المورد", money=True),
    ReportColumn("res_volume", "تكعيب المورد", volume=True),
    ReportColumn("total_res", "تكلفة المورد", money=True),
    ReportColumn("receipt_no", "رقم الإيصال"),
    ReportColumn("supplier", "اسم المورد", align="right"),
    ReportColumn("customer", "اسم العميل", align="right"),
    ReportColumn("trailer", "رقم المقطورة"),
)


@dataclass(frozen=True)
class ReportFilters:
    """The five optional filters. Any left ``None``/empty matches everything."""

    date_from: str | None = None
    date_to: str | None = None
    supplier_id: Any | None = None
    customer_id: Any | None = None
    tractor_id: Any | None = None
    item_name: str | None = None

    @property
    def is_empty(self) -> bool:
        return not any(
            v not in (None, "")
            for v in (
                self.date_from, self.date_to, self.supplier_id,
                self.customer_id, self.tractor_id, self.item_name,
            )
        )


@dataclass(frozen=True)
class ReportRow:
    """One ticket line — the three price layers plus the identity columns."""

    serial: int
    date: str
    item: str
    price_cus: Decimal
    cus_volume: Decimal
    total_cus: Decimal
    price_man: Decimal
    total_man: Decimal
    price_res: Decimal
    res_volume: Decimal
    total_res: Decimal
    receipt_no: str
    supplier: str
    customer: str
    trailer: str


@dataclass(frozen=True)
class ReportTotals:
    """The five footer totals (the Access ``r1``/``s1``/``Text165``/``v1``/
    ``Text131``) plus the row count."""

    total_cus: Decimal = Decimal("0")   # r1     — إجمالي تكلفة العميل
    total_man: Decimal = Decimal("0")   # s1     — إجمالي تكلفة السائق
    total_res: Decimal = Decimal("0")   # Text165 — إجمالي تكلفة المورد
    cus_volume: Decimal = Decimal("0")  # v1     — إجمالي تكعيب العميل
    res_volume: Decimal = Decimal("0")  # Text131 — إجمالي تكعيب المورد
    count: int = 0


@dataclass(frozen=True)
class ReportResult:
    """A rendered comprehensive report: the rows, the five totals and the filters
    that produced them."""

    rows: list[ReportRow] = field(default_factory=list)
    totals: ReportTotals = field(default_factory=ReportTotals)
    filters: ReportFilters = field(default_factory=ReportFilters)
    columns: tuple[ReportColumn, ...] = REPORT_COLUMNS

    @property
    def is_empty(self) -> bool:
        return not self.rows


def _dec(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


class TawridComprehensiveReportService:
    """Builds the flat tickets detail listing with the five optional filters."""

    columns: tuple[ReportColumn, ...] = REPORT_COLUMNS

    # «عميل محذوف» / «كسّارة محذوفة» placeholders and free-text names all come
    # through the joins, so a filtered run always reconciles with an unfiltered one.
    _DELETED_LABEL = "— محذوف —"

    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()

    # -- picker rows (feed the reused party pickers) ---------------------

    def supplier_picker_rows(self) -> list[dict[str, Any]]:
        """Active-first crusher cards for :class:`TawridSupplierPickerDialog`."""
        return list(
            self._db.fetch_all(
                "SELECT supplier_id, supplier_code, supplier_name, is_active "
                "FROM tawrid_suppliers ORDER BY is_active DESC, supplier_name"
            )
        )

    def customer_picker_rows(self) -> list[dict[str, Any]]:
        """Active-first customer cards for :class:`TawridCustomerPickerDialog`."""
        return list(
            self._db.fetch_all(
                "SELECT customer_id, customer_code, customer_name, is_active "
                "FROM tawrid_customers ORDER BY is_active DESC, customer_name"
            )
        )

    def tractor_picker_rows(self) -> list[dict[str, Any]]:
        """Active-first tractor cards for :class:`TawridTractorPickerDialog`."""
        return list(
            self._db.fetch_all(
                "SELECT tractor_id, driver_name, head_no, trailer_no, is_active "
                "FROM tawrid_tractors ORDER BY is_active DESC, driver_name"
            )
        )

    def distinct_items(self) -> list[str]:
        """The distinct non-empty ``item_name`` values, for the item combo.

        Access used a value-list combo on ``productName``; here the list is the
        items actually present on the tickets, so a typo can still be found.
        """
        rows = self._db.fetch_all(
            "SELECT DISTINCT item_name FROM tawrid_tickets "
            "WHERE COALESCE(item_name, '') <> '' ORDER BY item_name"
        )
        return [str(r["item_name"]) for r in rows]

    # -- the report -----------------------------------------------------

    def build(self, filters: ReportFilters | None = None) -> ReportResult:
        """Return the tickets detail listing under the (optional) *filters*.

        Each filter is applied only when set — the Access ``= param OR param IS
        NULL`` pattern — so an all-blank ``filters`` returns every ticket.
        """
        filters = filters or ReportFilters()
        where: list[str] = []
        params: list[Any] = []
        if filters.date_from:
            where.append("t.ticket_date >= %s")
            params.append(filters.date_from)
        if filters.date_to:
            where.append("t.ticket_date <= %s")
            params.append(filters.date_to)
        if filters.supplier_id not in (None, ""):
            where.append("t.supplier_id = %s")
            params.append(filters.supplier_id)
        if filters.customer_id not in (None, ""):
            where.append("t.customer_id = %s")
            params.append(filters.customer_id)
        if filters.tractor_id not in (None, ""):
            where.append("t.tractor_id = %s")
            params.append(filters.tractor_id)
        if filters.item_name not in (None, ""):
            where.append("t.item_name = %s")
            params.append(filters.item_name)
        clause = f"WHERE {' AND '.join(where)}" if where else ""

        query = f"""
            SELECT t.ticket_date AS d,
                   t.item_name AS item,
                   t.price_cus, t.cus_volume, t.total_cus,
                   t.price_man, t.total_man,
                   t.price_res, t.res_volume, t.total_res,
                   t.receipt_no,
                   s.supplier_name AS supplier,
                   c.customer_name AS customer,
                   g.trailer_no AS trailer,
                   t.ticket_no
              FROM tawrid_tickets t
              LEFT JOIN tawrid_suppliers s ON s.supplier_id = t.supplier_id
              LEFT JOIN tawrid_customers c ON c.customer_id = t.customer_id
              LEFT JOIN tawrid_tractors g ON g.tractor_id = t.tractor_id
              {clause}
             ORDER BY t.ticket_date, t.ticket_no
        """

        rows: list[ReportRow] = []
        totals = {
            "total_cus": Decimal("0"), "total_man": Decimal("0"),
            "total_res": Decimal("0"), "cus_volume": Decimal("0"),
            "res_volume": Decimal("0"),
        }
        for serial, r in enumerate(self._db.fetch_all(query, params), start=1):
            row = ReportRow(
                serial=serial,
                date=str(r["d"]) if r["d"] else "",
                item=str(r["item"] or ""),
                price_cus=_dec(r["price_cus"]),
                cus_volume=_dec(r["cus_volume"]),
                total_cus=_dec(r["total_cus"]),
                price_man=_dec(r["price_man"]),
                total_man=_dec(r["total_man"]),
                price_res=_dec(r["price_res"]),
                res_volume=_dec(r["res_volume"]),
                total_res=_dec(r["total_res"]),
                receipt_no="" if r["receipt_no"] in (None, "") else str(r["receipt_no"]),
                supplier=str(r["supplier"] or self._DELETED_LABEL),
                customer=str(r["customer"] or self._DELETED_LABEL),
                trailer="" if r["trailer"] in (None, "") else str(r["trailer"]),
            )
            rows.append(row)
            totals["total_cus"] += row.total_cus
            totals["total_man"] += row.total_man
            totals["total_res"] += row.total_res
            totals["cus_volume"] += row.cus_volume
            totals["res_volume"] += row.res_volume

        return ReportResult(
            rows=rows,
            totals=ReportTotals(count=len(rows), **totals),
            filters=filters,
            columns=self.columns,
        )

    # -- export rows (for the shared ExcelExporter + the print module) ---

    @staticmethod
    def _money(value: Decimal) -> str:
        text = f"{abs(value):,.2f}"
        return f"{text}-" if value < 0 else text

    @staticmethod
    def _vol(value: Decimal) -> str:
        """Trim trailing zeros: 62.000 → 62, 60.500 → 60.5."""
        return f"{value.normalize():f}" if value else "0"

    def export_rows(self, result: ReportResult) -> list[dict[str, Any]]:
        """The detail rows as display dicts keyed by column key (formatted)."""
        out: list[dict[str, Any]] = []
        for r in result.rows:
            out.append(
                {
                    "serial": str(r.serial),
                    "date": r.date,
                    "item": r.item,
                    "price_cus": self._money(r.price_cus),
                    "cus_volume": self._vol(r.cus_volume),
                    "total_cus": self._money(r.total_cus),
                    "price_man": self._money(r.price_man),
                    "total_man": self._money(r.total_man),
                    "price_res": self._money(r.price_res),
                    "res_volume": self._vol(r.res_volume),
                    "total_res": self._money(r.total_res),
                    "receipt_no": r.receipt_no,
                    "supplier": r.supplier,
                    "customer": r.customer,
                    "trailer": r.trailer,
                }
            )
        return out
