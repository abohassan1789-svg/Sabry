"""كشف حساب الخزينة — قسم التوريدات (Tawrid treasury / cash-book statement).

Re-creates the Access report **``A-khazina``** («كشف حساب الخزينه»), whose
RecordSource is the saved query ``q-kazina12`` → ``kazina12`` — a **UNION ALL of
the three voucher tables only** (the tickets/البونات are *not* part of the
treasury; a cash book tracks actual money movement, not the work):

* ``sanadCus``  (سندات قبض العملاء)   → **مقبوضات** (``amount AS dr``),
* ``SanadCAR``  (سندات صرف الجرارات)  → **مدفوعات** (``amount AS cr``),
* ``sanadsup``  (سندات صرف الكسّارات) → **مدفوعات** (``amount AS cr``).

The Access report shows ``date123 / dr / cr / bian`` per row, is filtered by a
**date range only** (``[Forms]![Reports]![d1]`` / ``d2`` — no party filters), and
its footer carries three totals: ``d3 = Sum([dr])`` (إجمالي المقبوضات),
``d4 = Sum([cr])`` (إجمالي المدفوعات) and ``Text80 = [d3]-[d4]`` (الرصيد الحالي).

Our sources (all on SiskoDB, reconciled 1:1 with the current ``.accdb``):
``tawrid_customer_receipts``, ``tawrid_supplier_payments`` and
``tawrid_tractor_payments`` — each ``amount`` + ``*_date`` + ``statement``
(=``bian``). At the user's request this build **enriches** the faithful Access
columns with a **النوع** (voucher source) column, a **الطرف** (party name) column
and a per-row **رصيد تراكمي** (running balance); the raw Access shape is a strict
subset of these.

No presentation logic lives here: it returns values, the screen formats them. The
column model + ``export_rows`` follow
:mod:`app.services.tawrid_comprehensive_report_service` so the shared Excel export
and the parallel print module consume it unchanged.
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

    ``money`` marks a two-decimal currency column; the rest are plain text.
    ``align`` is the on-screen / print alignment.
    """

    key: str
    label: str
    money: bool = False
    align: str = "center"


# Detail columns, right-to-left as the screen shows them. النوع + الطرف + رصيد
# تراكمي are the enrichment over Access; التاريخ/مقبوضات/مدفوعات/البيان are the
# faithful ``A-khazina`` detail band.
REPORT_COLUMNS: tuple[ReportColumn, ...] = (
    ReportColumn("serial", "م"),
    ReportColumn("date", "التاريخ"),
    ReportColumn("source", "النوع"),
    ReportColumn("party", "الطرف", align="right"),
    ReportColumn("dr", "مقبوضات", money=True),
    ReportColumn("cr", "مدفوعات", money=True),
    ReportColumn("balance", "رصيد تراكمي", money=True),
    ReportColumn("statement", "البيان", align="right"),
)


# The three voucher sources — the Access ``kazina12`` UNION legs, in its order.
SOURCE_RECEIPT = "قبض عميل"
SOURCE_SUPPLIER = "صرف كسّارة"
SOURCE_TRACTOR = "صرف جرار"


@dataclass(frozen=True)
class ReportFilters:
    """The Access date range (``d1``/``d2``). Either bound left ``None`` is open."""

    date_from: str | None = None
    date_to: str | None = None

    @property
    def is_empty(self) -> bool:
        return not any(v not in (None, "") for v in (self.date_from, self.date_to))


@dataclass(frozen=True)
class ReportRow:
    """One voucher line: date, source, party, the two money legs, the running
    balance up to and including this row, and the البيان text."""

    serial: int
    date: str
    source: str
    party: str
    dr: Decimal
    cr: Decimal
    balance: Decimal
    statement: str


@dataclass(frozen=True)
class ReportTotals:
    """The three Access footer totals (``d3``/``d4``/``Text80``) plus row count."""

    total_dr: Decimal = Decimal("0")   # d3     — إجمالي المقبوضات
    total_cr: Decimal = Decimal("0")   # d4     — إجمالي المدفوعات
    balance: Decimal = Decimal("0")    # Text80 — الرصيد الحالي = d3 - d4
    count: int = 0


@dataclass(frozen=True)
class ReportResult:
    """A rendered treasury statement: rows, totals and the filters used."""

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


class TawridTreasuryStatementService:
    """Builds the unified treasury cash book with an optional date filter."""

    columns: tuple[ReportColumn, ...] = REPORT_COLUMNS

    # Deleted parties come through the LEFT JOIN as NULL, so a run always
    # reconciles with the raw voucher tables regardless of party existence.
    _DELETED_LABEL = "— محذوف —"

    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()

    # -- the report -----------------------------------------------------

    def build(self, filters: ReportFilters | None = None) -> ReportResult:
        """Return the treasury cash book under the (optional) date *filters*.

        The three voucher tables are UNION-ed (receipts as **مقبوضات/dr**, both
        payment tables as **مدفوعات/cr**), ordered by date then a stable
        source/number tiebreaker, and a running balance (``Σdr − Σcr`` up to each
        row) is carried down the ordered rows.
        """
        filters = filters or ReportFilters()

        def _leg(date_col: str) -> tuple[str, list[Any]]:
            """A per-leg date WHERE clause + its params, mirroring Access d1/d2."""
            clauses: list[str] = []
            params: list[Any] = []
            if filters.date_from:
                clauses.append(f"{date_col} >= %s")
                params.append(filters.date_from)
            if filters.date_to:
                clauses.append(f"{date_col} <= %s")
                params.append(filters.date_to)
            return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), params

        w_cus, p_cus = _leg("r.receipt_date")
        w_sup, p_sup = _leg("p.payment_date")
        w_car, p_car = _leg("g.payment_date")

        query = f"""
            SELECT d, source, party, dr, cr, statement
              FROM (
                SELECT r.receipt_date            AS d,
                       %s                         AS source,
                       COALESCE(c.customer_name, %s) AS party,
                       r.amount                   AS dr,
                       CAST(0 AS numeric)         AS cr,
                       r.statement                AS statement,
                       1                          AS ord,
                       r.receipt_no               AS vno
                  FROM tawrid_customer_receipts r
                  LEFT JOIN tawrid_customers c ON c.customer_id = r.customer_id
                  {w_cus}
                UNION ALL
                SELECT p.payment_date,
                       %s,
                       COALESCE(s.supplier_name, %s),
                       CAST(0 AS numeric),
                       p.amount,
                       p.statement,
                       2,
                       p.payment_no
                  FROM tawrid_supplier_payments p
                  LEFT JOIN tawrid_suppliers s ON s.supplier_id = p.supplier_id
                  {w_sup}
                UNION ALL
                SELECT g.payment_date,
                       %s,
                       COALESCE(t.driver_name, %s),
                       CAST(0 AS numeric),
                       g.amount,
                       g.statement,
                       3,
                       g.payment_no
                  FROM tawrid_tractor_payments g
                  LEFT JOIN tawrid_tractors t ON t.tractor_id = g.tractor_id
                  {w_car}
              ) u
             ORDER BY d, ord, vno
        """

        params: list[Any] = [
            SOURCE_RECEIPT, self._DELETED_LABEL, *p_cus,
            SOURCE_SUPPLIER, self._DELETED_LABEL, *p_sup,
            SOURCE_TRACTOR, self._DELETED_LABEL, *p_car,
        ]

        rows: list[ReportRow] = []
        total_dr = Decimal("0")
        total_cr = Decimal("0")
        running = Decimal("0")
        for serial, r in enumerate(self._db.fetch_all(query, params), start=1):
            dr = _dec(r["dr"])
            cr = _dec(r["cr"])
            running += dr - cr
            total_dr += dr
            total_cr += cr
            rows.append(
                ReportRow(
                    serial=serial,
                    date=str(r["d"]) if r["d"] else "",
                    source=str(r["source"] or ""),
                    party=str(r["party"] or self._DELETED_LABEL),
                    dr=dr,
                    cr=cr,
                    balance=running,
                    statement="" if r["statement"] in (None, "") else str(r["statement"]),
                )
            )

        return ReportResult(
            rows=rows,
            totals=ReportTotals(
                total_dr=total_dr,
                total_cr=total_cr,
                balance=total_dr - total_cr,
                count=len(rows),
            ),
            filters=filters,
            columns=self.columns,
        )

    # -- export rows (for the shared ExcelExporter + the print module) ---

    @staticmethod
    def _money(value: Decimal) -> str:
        text = f"{abs(value):,.2f}"
        return f"{text}-" if value < 0 else text

    def export_rows(self, result: ReportResult) -> list[dict[str, Any]]:
        """The detail rows as display dicts keyed by column key (formatted)."""
        out: list[dict[str, Any]] = []
        for r in result.rows:
            out.append(
                {
                    "serial": str(r.serial),
                    "date": r.date,
                    "source": r.source,
                    "party": r.party,
                    "dr": self._money(r.dr),
                    "cr": self._money(r.cr),
                    "balance": self._money(r.balance),
                    "statement": r.statement,
                }
            )
        return out
