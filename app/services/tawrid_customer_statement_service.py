"""كشف الحساب — قسم التوريدات (Tawrid account statements).

The **first** of the three statements (customer / crusher / tractor). It is a
read-only ledger, not a CRUD screen, and it re-creates the Access report
``ACCCus`` («كشف حساب عميل») — verified field-by-field against the running
``.accdb`` via COM. In Access ``ACCCus`` reads a view ``CustomerUnion`` that
``UNION ALL``s three sources:

* **رصيد أول المدة** — ``fanii.BalancFirst`` (a debit opening line);
* **بون عميل** — ``TBBOOn.SafiCus``, the customer's net-after-discount (debit);
* **سداد دفعات** — ``sanadCus.amount`` (credit).

and its summary box carries a **«حساب قديم»** = the balance carried forward from
*before* the «من تاريخ» filter. This module keeps all of that and adds the one
thing Access never showed: a **per-line running balance**.

Reusable for all three parties
------------------------------
Everything the ledger needs is described by a :class:`StatementConfig` — which
table is the party, which table/column is the debit (the ticket layer) and which
is the credit (the voucher). The customer wiring lives in
:class:`TawridCustomerStatementService`; the crusher and tractor statements are
the same class with ``total_res`` + ``tawrid_supplier_payments`` and ``total_man``
+ ``tawrid_tractor_payments`` respectively — no new query code.

The whole-account totals (opening / invoiced / collected / balance) are **not**
re-derived here: :meth:`TawridCustomerStatementService` delegates them to
:class:`app.services.tawrid_customer_service.TawridCustomerService.for_customer`,
the single source of truth for «الرصيد», so an unfiltered statement's closing
balance always equals the figure on the customers screen.

No presentation logic lives here: it returns values, and the screen formats them.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.database.db import Database


# -- column model (also drives the Excel export) --------------------------------


@dataclass(frozen=True)
class StatementColumn:
    """One ledger column: its ``key`` in an export row and its Arabic ``label``."""

    key: str
    label: str


# The customer ledger columns — Model 1 («الكلاسيكي», closest to ACCCus) plus the
# new running-balance column. The order is right-to-left as the screen shows it.
CUSTOMER_COLUMNS: tuple[StatementColumn, ...] = (
    StatementColumn("serial", "م"),
    StatementColumn("date", "التاريخ"),
    StatementColumn("kind", "نوع الإذن"),
    StatementColumn("description", "الخامة / البيان"),
    StatementColumn("price", "السعر"),
    StatementColumn("volume", "التكعيب"),
    StatementColumn("bon_no", "رقم البون"),
    StatementColumn("eissal", "رقم الإيصال"),
    StatementColumn("trailer", "رقم المقطورة"),
    StatementColumn("head", "رقم الوش"),
    StatementColumn("debit", "مدين"),
    StatementColumn("credit", "دائن"),
    StatementColumn("running", "رصيد جارٍ"),
)

# The «ملخص البونات» grouped table — the Access subreport ``Test`` / HelpSaSubreport2,
# grouped by (item, price, volume) with the count and value of each group.
BON_SUMMARY_COLUMNS: tuple[StatementColumn, ...] = (
    StatementColumn("serial", "م"),
    StatementColumn("item", "الصنف"),
    StatementColumn("count", "الكمية"),
    StatementColumn("price", "السعر"),
    StatementColumn("volume", "التكعيب"),
    StatementColumn("gross", "الإجمالى"),
    StatementColumn("meters", "إجمالى الأمتار"),
)


@dataclass(frozen=True)
class StatementConfig:
    """Describes one party's ledger sources — the only thing that differs across
    the customer / crusher / tractor statements."""

    party_table: str
    party_pk: str
    party_name_col: str
    party_code_col: str
    opening_col: str
    opening_date_col: str
    # debit source (the ticket layer)
    debit_table: str
    debit_fk: str
    debit_date_col: str
    debit_amount_col: str
    debit_desc_col: str
    debit_kind: str
    debit_bon_col: str        # رقم البون (Access number1 / ticket_no)
    debit_eissal_col: str     # رقم الإيصال (Access NumberEissal / receipt_no)
    debit_price_col: str | None = None
    debit_volume_col: str | None = None
    debit_gross_col: str | None = None   # جملة قيمة البون (Access totalCus) — for the bon summary
    # رقم المقطورة comes from the ticket's tractor card, joined in.
    debit_join_table: str | None = None
    debit_join_left: str | None = None   # column on the debit table (tractor_id)
    debit_join_right: str | None = None  # column on the joined table (tractor_id)
    debit_join_col: str | None = None    # the value shown (trailer_no)
    debit_join_col2: str | None = None   # a second joined value (head_no / رقم الوش)
    # credit source (the voucher)
    credit_table: str = ""
    credit_fk: str = ""
    credit_date_col: str = ""
    credit_amount_col: str = ""
    credit_eissal_col: str = ""   # رقم الإيصال for the voucher (Access sanad id / receipt_no)
    credit_desc_col: str = ""
    credit_kind: str = ""
    columns: tuple[StatementColumn, ...] = CUSTOMER_COLUMNS
    bon_summary_columns: tuple[StatementColumn, ...] = BON_SUMMARY_COLUMNS


# The «رصيد أول المدة» / «رصيد سابق» opening line uses these markers.
OPENING_KIND = "رصيد أول المدة"
CARRY_KIND = "رصيد سابق"


@dataclass(frozen=True)
class StatementRow:
    """One ledger line. ``debit``/``credit``/``running`` are signed Decimals; the
    rest is display text. ``is_opening`` marks the opening / carry-forward line so
    the screen can tint it and leave it out of the row serial numbering."""

    serial: int | None
    date: str
    kind: str
    bon_no: str       # رقم البون (blank for vouchers / opening)
    eissal: str       # رقم الإيصال
    trailer: str      # رقم المقطورة (blank for vouchers / opening)
    description: str
    price: Decimal | None
    volume: Decimal | None
    debit: Decimal
    credit: Decimal
    running: Decimal
    # رقم الوش — the trailer's tractor head plate. Optional (default blank): only
    # the customer statement joins it; the crusher/tractor statements leave it out.
    head: str = ""
    is_opening: bool = False


@dataclass(frozen=True)
class StatementResult:
    """A rendered statement: the header facts, the ledger rows and the totals.

    ``opening_balance`` is the running balance the ledger *starts* from — the
    plain opening balance with no date filter, or the carry-forward
    («رصيد سابق» / Access «حساب قديم») when a «من تاريخ» is set. ``period_debit``
    and ``period_credit`` sum only the movements shown; ``closing_balance`` =
    ``opening_balance + period_debit - period_credit``.
    """

    party_id: Any
    party_name: str
    party_code: Any
    date_from: str | None
    date_to: str | None
    opening_balance: Decimal
    opening_is_carry: bool
    rows: list[StatementRow] = field(default_factory=list)
    period_debit: Decimal = Decimal("0")
    period_credit: Decimal = Decimal("0")
    closing_balance: Decimal = Decimal("0")
    columns: tuple[StatementColumn, ...] = CUSTOMER_COLUMNS

    @property
    def is_empty(self) -> bool:
        """No movements in the period (the opening line alone doesn't count)."""
        return not any(not r.is_opening for r in self.rows)

    @property
    def movement_count(self) -> int:
        return sum(1 for r in self.rows if not r.is_opening)


@dataclass(frozen=True)
class BonSummaryRow:
    """One group of the «ملخص البونات» table: identical (item, price, volume)."""

    item: str
    count: int
    price: Decimal
    volume: Decimal
    gross: Decimal   # الإجمالى = price × volume × count (Access ``bal``)
    meters: Decimal  # إجمالى الأمتار = volume × count


@dataclass(frozen=True)
class BonSummary:
    """The Access subreport ``Test``: bon groups + the three footer totals."""

    rows: list[BonSummaryRow] = field(default_factory=list)
    total_value: Decimal = Decimal("0")   # إجمالي البونات
    total_count: int = 0                   # إجمالي النقلات
    total_meters: Decimal = Decimal("0")  # إجمالي الأمتار
    columns: tuple[StatementColumn, ...] = BON_SUMMARY_COLUMNS


def _dec(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


class TawridStatementService:
    """Builds a running-balance ledger for any party described by a config."""

    CONFIG: StatementConfig  # set by subclasses

    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()

    # -- helpers ---------------------------------------------------------

    def _scalar(self, query: str, params: list[Any], default: Any = Decimal("0")) -> Any:
        row = self._db.fetch_one(query, params)
        if not row:
            return default
        value = next(iter(row.values()))
        return default if value is None else value

    # -- picker rows -----------------------------------------------------

    def party_picker_rows(self) -> list[dict[str, Any]]:
        """Active-first party cards for the picker dialog."""
        cfg = self.CONFIG
        return list(
            self._db.fetch_all(
                f"SELECT {cfg.party_pk} AS party_id, {cfg.party_code_col} AS code, "
                f"{cfg.party_name_col} AS name, is_active "
                f"FROM {cfg.party_table} ORDER BY is_active DESC, {cfg.party_name_col}"
            )
        )

    def party_header(self, party_id: Any) -> dict[str, Any] | None:
        cfg = self.CONFIG
        if party_id in (None, ""):
            return None
        return self._db.fetch_one(
            f"SELECT {cfg.party_pk} AS party_id, {cfg.party_code_col} AS code, "
            f"{cfg.party_name_col} AS name, {cfg.opening_col} AS opening, "
            f"{cfg.opening_date_col} AS opening_date "
            f"FROM {cfg.party_table} WHERE {cfg.party_pk} = %s",
            [party_id],
        )

    # -- the ledger ------------------------------------------------------

    def build(
        self,
        party_id: Any,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> StatementResult:
        """Return the statement for *party_id* between *date_from* and *date_to*.

        Both dates are inclusive ``YYYY-MM-DD`` strings, or ``None`` for open.
        With a ``date_from`` the ledger opens on a **carry-forward** line so the
        running balance is right from the first movement shown.
        """
        cfg = self.CONFIG
        header = self.party_header(party_id)
        if header is None:
            return StatementResult(
                party_id=party_id, party_name="", party_code=None,
                date_from=date_from, date_to=date_to,
                opening_balance=Decimal("0"), opening_is_carry=bool(date_from),
                columns=cfg.columns,
            )

        opening = _dec(header.get("opening"))
        opening_date = header.get("opening_date")

        # Carry-forward: opening + all debits before the window - all credits before it.
        carry = opening
        if date_from:
            carry += _dec(
                self._scalar(
                    f"SELECT COALESCE(SUM({cfg.debit_amount_col}),0) FROM {cfg.debit_table} "
                    f"WHERE {cfg.debit_fk} = %s AND {cfg.debit_date_col} < %s",
                    [party_id, date_from],
                )
            )
            carry -= _dec(
                self._scalar(
                    f"SELECT COALESCE(SUM({cfg.credit_amount_col}),0) FROM {cfg.credit_table} "
                    f"WHERE {cfg.credit_fk} = %s AND {cfg.credit_date_col} < %s",
                    [party_id, date_from],
                )
            )

        movements = self._movements(party_id, date_from, date_to)

        rows: list[StatementRow] = []
        running = carry
        period_debit = Decimal("0")
        period_credit = Decimal("0")

        # The opening / carry-forward line.
        if date_from:
            open_date = self._minus_one_day(date_from)
            open_kind = CARRY_KIND
            open_desc = f"رصيد ما قبل {date_from}"
        else:
            open_date = str(opening_date) if opening_date else ""
            open_kind = OPENING_KIND
            open_desc = OPENING_KIND
        rows.append(
            StatementRow(
                serial=None, date=open_date, kind=open_kind,
                bon_no="", eissal="", trailer="", head="",
                description=open_desc, price=None, volume=None,
                debit=carry if carry >= 0 else Decimal("0"),
                credit=-carry if carry < 0 else Decimal("0"),
                running=carry, is_opening=True,
            )
        )

        serial = 0
        for mv in movements:
            debit = _dec(mv["debit"])
            credit = _dec(mv["credit"])
            running += debit - credit
            period_debit += debit
            period_credit += credit
            serial += 1
            rows.append(
                StatementRow(
                    serial=serial,
                    date=str(mv["d"]) if mv["d"] else "",
                    kind=mv["kind"],
                    bon_no="" if mv["bon"] in (None, "") else str(mv["bon"]),
                    eissal="" if mv["eissal"] in (None, "") else str(mv["eissal"]),
                    trailer="" if mv["trailer"] in (None, "") else str(mv["trailer"]),
                    # ``.get`` — only the customer config selects رقم الوش; other
                    # statements (and older mocks) have no ``head`` key at all.
                    head="" if mv.get("head") in (None, "") else str(mv.get("head")),
                    description=str(mv["descr"] or ""),
                    price=None if mv["price"] is None else _dec(mv["price"]),
                    volume=None if mv["volume"] is None else _dec(mv["volume"]),
                    debit=debit, credit=credit, running=running,
                )
            )

        return StatementResult(
            party_id=party_id,
            party_name=str(header.get("name") or ""),
            party_code=header.get("code"),
            date_from=date_from, date_to=date_to,
            opening_balance=carry, opening_is_carry=bool(date_from),
            rows=rows,
            period_debit=period_debit, period_credit=period_credit,
            closing_balance=running,
            columns=cfg.columns,
        )

    def _movements(
        self, party_id: Any, date_from: str | None, date_to: str | None
    ) -> list[dict[str, Any]]:
        """The debit and credit rows inside the window, ordered date → debit
        before credit → document number, so the running balance is stable."""
        cfg = self.CONFIG
        price = f"m.{cfg.debit_price_col}" if cfg.debit_price_col else "NULL"
        volume = f"m.{cfg.debit_volume_col}" if cfg.debit_volume_col else "NULL"
        # رقم المقطورة (and optionally رقم الوش) joined from the ticket's tractor
        # card, or NULL if no join / no second column configured.
        if cfg.debit_join_table and cfg.debit_join_col:
            trailer = f"j.{cfg.debit_join_col}"
            head = f"j.{cfg.debit_join_col2}" if cfg.debit_join_col2 else "NULL"
            join = (
                f"LEFT JOIN {cfg.debit_join_table} j "
                f"ON j.{cfg.debit_join_right} = m.{cfg.debit_join_left}"
            )
        else:
            trailer, head, join = "NULL", "NULL", ""
        debit_where = [f"m.{cfg.debit_fk} = %s"]
        credit_where = [f"{cfg.credit_fk} = %s"]
        debit_params: list[Any] = [party_id]
        credit_params: list[Any] = [party_id]
        if date_from:
            debit_where.append(f"m.{cfg.debit_date_col} >= %s")
            debit_params.append(date_from)
            credit_where.append(f"{cfg.credit_date_col} >= %s")
            credit_params.append(date_from)
        if date_to:
            debit_where.append(f"m.{cfg.debit_date_col} <= %s")
            debit_params.append(date_to)
            credit_where.append(f"{cfg.credit_date_col} <= %s")
            credit_params.append(date_to)

        query = f"""
            SELECT d, kind, bon, eissal, trailer, head, descr, price, volume, debit, credit, ord
              FROM (
                SELECT m.{cfg.debit_date_col} AS d, %s AS kind,
                       m.{cfg.debit_bon_col}::text AS bon,
                       m.{cfg.debit_eissal_col}::text AS eissal,
                       {trailer}::text AS trailer, {head}::text AS head,
                       m.{cfg.debit_desc_col} AS descr,
                       {price} AS price, {volume} AS volume,
                       m.{cfg.debit_amount_col} AS debit, 0::numeric AS credit, 0 AS ord
                  FROM {cfg.debit_table} m {join}
                 WHERE {' AND '.join(debit_where)}
                UNION ALL
                SELECT {cfg.credit_date_col} AS d, %s AS kind,
                       NULL::text AS bon, {cfg.credit_eissal_col}::text AS eissal,
                       NULL::text AS trailer, NULL::text AS head,
                       {cfg.credit_desc_col} AS descr,
                       NULL AS price, NULL AS volume,
                       0::numeric AS debit, {cfg.credit_amount_col} AS credit, 1 AS ord
                  FROM {cfg.credit_table}
                 WHERE {' AND '.join(credit_where)}
            ) u
            ORDER BY d, ord, eissal
        """
        params = [cfg.debit_kind, *debit_params, cfg.credit_kind, *credit_params]
        return list(self._db.fetch_all(query, params))

    # -- the «ملخص البونات» grouped table (Access subreport ``Test``) ------

    def bon_summary(
        self,
        party_id: Any,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> BonSummary:
        """Group the party's بونات by (item, price, volume) — the Access
        subreport ``Test``. Each group carries its count, its gross value
        (price × volume × count = Σ ``total_cus``) and its metres (volume ×
        count = Σ volume). Vouchers and the opening line are excluded (Access
        keyed the subreport on ``n1 <> ""``)."""
        cfg = self.CONFIG
        if party_id in (None, "") or not (
            cfg.debit_price_col and cfg.debit_volume_col and cfg.debit_gross_col
        ):
            return BonSummary(columns=cfg.bon_summary_columns)
        where = [f"{cfg.debit_fk} = %s", f"COALESCE({cfg.debit_desc_col}, '') <> ''"]
        params: list[Any] = [party_id]
        if date_from:
            where.append(f"{cfg.debit_date_col} >= %s")
            params.append(date_from)
        if date_to:
            where.append(f"{cfg.debit_date_col} <= %s")
            params.append(date_to)
        query = f"""
            SELECT {cfg.debit_desc_col} AS item,
                   {cfg.debit_price_col} AS price,
                   {cfg.debit_volume_col} AS volume,
                   COUNT(*) AS cnt,
                   COALESCE(SUM({cfg.debit_gross_col}), 0) AS gross,
                   COALESCE(SUM({cfg.debit_volume_col}), 0) AS meters
              FROM {cfg.debit_table}
             WHERE {' AND '.join(where)}
             GROUP BY {cfg.debit_desc_col}, {cfg.debit_price_col}, {cfg.debit_volume_col}
             ORDER BY {cfg.debit_desc_col}, {cfg.debit_price_col}, {cfg.debit_volume_col}
        """
        rows: list[BonSummaryRow] = []
        total_value = Decimal("0")
        total_count = 0
        total_meters = Decimal("0")
        for r in self._db.fetch_all(query, params):
            count = int(r["cnt"] or 0)
            gross = _dec(r["gross"])
            meters = _dec(r["meters"])
            rows.append(
                BonSummaryRow(
                    item=str(r["item"] or ""),
                    count=count,
                    price=_dec(r["price"]),
                    volume=_dec(r["volume"]),
                    gross=gross,
                    meters=meters,
                )
            )
            total_value += gross
            total_count += count
            total_meters += meters
        return BonSummary(
            rows=rows, total_value=total_value, total_count=total_count,
            total_meters=total_meters, columns=cfg.bon_summary_columns,
        )

    # -- export rows (for the shared ExcelExporter) ----------------------

    @staticmethod
    def _money(value: Decimal) -> str:
        text = f"{abs(value):,.2f}"
        return f"{text}-" if value < 0 else text

    @staticmethod
    def _vol(value: Decimal) -> str:
        """Trim trailing zeros: 62.000 → 62, 60.500 → 60.5."""
        return f"{value.normalize():f}"

    def export_rows(self, result: StatementResult) -> list[dict[str, Any]]:
        """The ledger as display dicts keyed by column key (money formatted)."""
        out: list[dict[str, Any]] = []
        for r in result.rows:
            out.append(
                {
                    "serial": "" if r.serial is None else str(r.serial),
                    "date": r.date,
                    "kind": r.kind,
                    "description": r.description,
                    "price": "" if r.price is None else f"{r.price:,.2f}",
                    "volume": "" if r.volume is None else self._vol(r.volume),
                    "bon_no": r.bon_no,
                    "eissal": r.eissal,
                    "trailer": r.trailer,
                    "head": r.head,
                    "debit": "" if r.debit == 0 else self._money(r.debit),
                    "credit": "" if r.credit == 0 else self._money(r.credit),
                    "running": self._money(r.running),
                }
            )
        return out

    @staticmethod
    def _minus_one_day(date_str: str) -> str:
        try:
            d = _dt.date.fromisoformat(date_str)
            return (d - _dt.timedelta(days=1)).isoformat()
        except (ValueError, TypeError):
            return date_str


# -- the customer statement ----------------------------------------------------

CUSTOMER_STATEMENT_CONFIG = StatementConfig(
    party_table="tawrid_customers",
    party_pk="customer_id",
    party_name_col="customer_name",
    party_code_col="customer_code",
    opening_col="opening_balance",
    opening_date_col="opening_date",
    debit_table="tawrid_tickets",
    debit_fk="customer_id",
    debit_date_col="ticket_date",
    debit_amount_col="safi_cus",
    debit_desc_col="item_name",
    debit_kind="بون عميل",
    debit_bon_col="ticket_no",       # رقم البون (Access number1)
    debit_eissal_col="receipt_no",   # رقم الإيصال (Access NumberEissal)
    debit_price_col="price_cus",
    debit_volume_col="cus_volume",
    debit_gross_col="total_cus",     # جملة قيمة البون (Access totalCus)
    debit_join_table="tawrid_tractors",   # رقم المقطورة via the ticket's tractor
    debit_join_left="tractor_id",
    debit_join_right="tractor_id",
    debit_join_col="trailer_no",
    debit_join_col2="head_no",            # رقم الوش via the same tractor card
    credit_table="tawrid_customer_receipts",
    credit_fk="customer_id",
    credit_date_col="receipt_date",
    credit_amount_col="amount",
    credit_eissal_col="receipt_no",  # رقم الإيصال (Access sanad id)
    credit_desc_col="statement",
    credit_kind="سداد دفعات",
    columns=CUSTOMER_COLUMNS,
)


class TawridCustomerStatementService(TawridStatementService):
    """كشف حساب عميل. Ledger from :class:`TawridStatementService`; the
    whole-account balance delegated to :class:`TawridCustomerService`."""

    CONFIG = CUSTOMER_STATEMENT_CONFIG

    def __init__(self, db: Database | None = None) -> None:
        super().__init__(db)
        # Imported lazily-friendly at module top; shares the one connection so the
        # unfiltered closing balance equals the customers screen exactly.
        from app.services.tawrid_customer_service import TawridCustomerService

        self._customers = TawridCustomerService(self._db)

    def whole_account(self, customer_id: Any):
        """The full-history summary (opening / invoiced / collected / balance)
        from the single source of truth, for cross-checking an unfiltered run."""
        return self._customers.for_customer(customer_id)
