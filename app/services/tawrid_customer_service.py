"""Customer-specific queries for the Tawrid module (قسم التوريدات), phase 2.

Three jobs the generic ``ReviewDataService`` cannot do:

* the **account summary** shown on the screen,
* allocating the next مسلسل (``customer_code``), and
* the **customer × tractor price grid** — a child table with its own CRUD, the
  replacement for the Access subform ``InvoiceCARCUS subform`` over ``CarCus``.

Account summary (ملخّص حساب العميل)

    الرصيد = رصيد أول المدة + قيمة البونات − المحصّل

That mirrors the Access report ``ACCCus``, which UNIONs ``TBBOOn`` (the customer
side, column ``SafiCus``), ``sanadCus`` (receipts) and the opening balance out of
``fanii``. The movement tables belong to later phases and do not exist yet, so
this service **probes for them** and reports "no movement yet" until they do —
the same approach as :mod:`app.services.tawrid_tractor_service`. The screen then
starts showing real figures the moment those phases land, with no change here.

The price grid

One row per (customer, tractor). It is read back joined to ``tawrid_tractors``
so the screen can show the driver's name, the trailer number and the head
number without storing copies of them: ``CarCus`` stored the head number and
three of its 236 rows had already drifted away from the tractor card.

No presentation logic lives here: this returns values, and the screen decides
how to format them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.database.db import Database

# Tables this summary reads from once later phases create them.
TICKETS_TABLE = "tawrid_tickets"
RECEIPTS_TABLE = "tawrid_customer_receipts"

PRICES_TABLE = "tawrid_customer_tractor_prices"


@dataclass(frozen=True)
class CustomerBalance:
    """One customer's account, in currency units."""

    opening_balance: Decimal = Decimal("0")
    tickets_count: int = 0
    invoiced: Decimal = Decimal("0")   # قيمة البونات المستحقة عليه
    collected: Decimal = Decimal("0")  # المحصّل منه
    # True while the movement tables have not been created yet, so the screen can
    # show "—" instead of implying a real zero.
    movements_available: bool = False

    @property
    def balance(self) -> Decimal:
        """Net amount the customer owes."""
        return self.opening_balance + self.invoiced - self.collected


@dataclass(frozen=True)
class TractorPrice:
    """One row of the customer × tractor grid, joined to the tractor card."""

    price_id: Any = None
    tractor_id: Any = None
    tractor_code: Any = None
    driver_name: str = ""
    trailer_no: str = ""
    head_no: str = ""
    load_volume: Decimal = Decimal("0")
    price_sen: Decimal = Decimal("0")
    price_raml: Decimal = Decimal("0")
    # The tractor's own default rates, for comparison. In the legacy data 208 of
    # 221 grid rows differ from these, which is why the grid exists at all.
    default_sen: Decimal = Decimal("0")
    default_raml: Decimal = Decimal("0")


class TawridCustomerService:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()

    # -- helpers ---------------------------------------------------------

    def _table_exists(self, table_name: str) -> bool:
        row = self._db.fetch_one(
            "SELECT to_regclass(%s) AS oid", [f"public.{table_name}"]
        )
        return bool(row and row["oid"] is not None)

    def _scalar(self, query: str, params: list[Any], key: str, default: Any) -> Any:
        row = self._db.fetch_one(query, params)
        if not row or row.get(key) is None:
            return default
        return row[key]

    # -- codes -----------------------------------------------------------

    def next_code(self) -> int:
        """The next free مسلسل — ``MAX(customer_code) + 1``, starting at 1.

        A display-only suggestion for a new record: the user may overwrite it,
        and the UNIQUE index on ``customer_code`` is what actually guarantees no
        two customers share one. The legacy numbering runs 5..101 with 52 gaps,
        so continuing from the maximum (not the count) is the only safe rule.
        """
        row = self._db.fetch_one(
            "SELECT COALESCE(MAX(customer_code), 0) + 1 AS next_code FROM tawrid_customers"
        )
        return int(row["next_code"]) if row else 1

    # -- account summary --------------------------------------------------

    def for_customer(self, customer_id: Any) -> CustomerBalance:
        """Return the account summary for *customer_id*.

        An unknown/None id yields an all-zero summary rather than raising, so the
        screen can call this freely while the form is empty.
        """
        if customer_id in (None, ""):
            return CustomerBalance()

        opening = self._scalar(
            "SELECT opening_balance FROM tawrid_customers WHERE customer_id = %s",
            [customer_id],
            "opening_balance",
            Decimal("0"),
        )

        has_tickets = self._table_exists(TICKETS_TABLE)
        has_receipts = self._table_exists(RECEIPTS_TABLE)
        if not (has_tickets or has_receipts):
            return CustomerBalance(opening_balance=Decimal(opening))

        tickets = 0
        invoiced = Decimal("0")
        if has_tickets:
            # ``safi_cus`` is the customer's net after discount — the Access
            # column ``SafiCus``, which is what ACCCus posts to the statement.
            row = self._db.fetch_one(
                f"SELECT COUNT(*) AS n, COALESCE(SUM(safi_cus), 0) AS s "
                f"FROM {TICKETS_TABLE} WHERE customer_id = %s",
                [customer_id],
            )
            if row:
                tickets = int(row["n"] or 0)
                invoiced = Decimal(row["s"] or 0)

        collected = Decimal("0")
        if has_receipts:
            collected = Decimal(
                self._scalar(
                    f"SELECT COALESCE(SUM(amount), 0) AS s "
                    f"FROM {RECEIPTS_TABLE} WHERE customer_id = %s",
                    [customer_id],
                    "s",
                    Decimal("0"),
                )
            )

        return CustomerBalance(
            opening_balance=Decimal(opening),
            tickets_count=tickets,
            invoiced=invoiced,
            collected=collected,
            movements_available=True,
        )

    def has_movement(self, customer_id: Any) -> int:
        """How many tickets/receipts reference this customer (0 when none).

        Used to refuse deletion. Returns 0 while the movement tables do not yet
        exist, which is correct: nothing can reference the customer.
        """
        if customer_id in (None, ""):
            return 0
        total = 0
        for table, column in ((TICKETS_TABLE, "customer_id"), (RECEIPTS_TABLE, "customer_id")):
            if not self._table_exists(table):
                continue
            total += int(
                self._scalar(
                    f"SELECT COUNT(*) AS c FROM {table} WHERE {column} = %s",
                    [customer_id],
                    "c",
                    0,
                )
            )
        return total

    # -- the customer × tractor price grid --------------------------------

    def tractor_prices(self, customer_id: Any) -> list[TractorPrice]:
        """This customer's grid, joined to the tractor cards, by driver name."""
        if customer_id in (None, ""):
            return []
        rows = self._db.fetch_all(
            f"""
            SELECT p.price_id, p.tractor_id, p.load_volume, p.price_sen, p.price_raml,
                   t.tractor_code, t.driver_name, t.trailer_no, t.head_no,
                   t.price_sen AS default_sen, t.price_raml AS default_raml
              FROM {PRICES_TABLE} p
              JOIN tawrid_tractors t ON t.tractor_id = p.tractor_id
             WHERE p.customer_id = %s
             ORDER BY t.driver_name
            """,
            [customer_id],
        )
        return [
            TractorPrice(
                price_id=row["price_id"],
                tractor_id=row["tractor_id"],
                tractor_code=row["tractor_code"],
                driver_name=row["driver_name"] or "",
                trailer_no=row["trailer_no"] or "",
                head_no=row["head_no"] or "",
                load_volume=Decimal(row["load_volume"] or 0),
                price_sen=Decimal(row["price_sen"] or 0),
                price_raml=Decimal(row["price_raml"] or 0),
                default_sen=Decimal(row["default_sen"] or 0),
                default_raml=Decimal(row["default_raml"] or 0),
            )
            for row in rows
        ]

    def available_tractors(self, customer_id: Any) -> list[dict[str, Any]]:
        """Active tractors not already priced for this customer.

        Filtering them out here is what keeps the unique (customer, tractor)
        constraint from ever surfacing as an error: the combo simply cannot
        offer a duplicate. Access instead trapped the resulting error 3022 and
        asked the user to try again.
        """
        rows = self._db.fetch_all(
            f"""
            SELECT t.tractor_id, t.tractor_code, t.driver_name, t.trailer_no, t.head_no,
                   t.price_sen, t.price_raml
              FROM tawrid_tractors t
             WHERE t.is_active
               AND NOT EXISTS (
                   SELECT 1 FROM {PRICES_TABLE} p
                    WHERE p.tractor_id = t.tractor_id AND p.customer_id = %s
               )
             ORDER BY t.driver_name
            """,
            [customer_id if customer_id not in (None, "") else -1],
        )
        return list(rows)

    def add_tractor_price(
        self,
        customer_id: Any,
        tractor_id: Any,
        load_volume: Any = 0,
        price_sen: Any = 0,
        price_raml: Any = 0,
    ) -> Any:
        """Insert one grid row and return its ``price_id``."""
        row = self._db.fetch_one(
            f"""
            INSERT INTO {PRICES_TABLE}
                   (customer_id, tractor_id, load_volume, price_sen, price_raml)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING price_id
            """,
            [
                customer_id,
                tractor_id,
                _money(load_volume),
                _money(price_sen),
                _money(price_raml),
            ],
        )
        return row["price_id"] if row else None

    def update_tractor_price(
        self, price_id: Any, load_volume: Any, price_sen: Any, price_raml: Any
    ) -> None:
        self._db.execute(
            f"""
            UPDATE {PRICES_TABLE}
               SET load_volume = %s, price_sen = %s, price_raml = %s
             WHERE price_id = %s
            """,
            [_money(load_volume), _money(price_sen), _money(price_raml), price_id],
        )

    def delete_tractor_price(self, price_id: Any) -> None:
        self._db.execute(f"DELETE FROM {PRICES_TABLE} WHERE price_id = %s", [price_id])

    def price_row_count(self, customer_id: Any) -> int:
        """Grid rows for this customer — the number named in the delete warning."""
        if customer_id in (None, ""):
            return 0
        return int(
            self._scalar(
                f"SELECT COUNT(*) AS c FROM {PRICES_TABLE} WHERE customer_id = %s",
                [customer_id],
                "c",
                0,
            )
        )


def _money(value: Any) -> Decimal:
    """Blank means zero, not NULL: every price column is NOT NULL DEFAULT 0.

    The grid is edited in a table where an emptied cell plainly means "nothing",
    so turning it into a NotNullViolation the user has to decode would be wrong.
    """
    if value is None:
        return Decimal("0")
    text = str(value).strip()
    if text == "":
        return Decimal("0")
    try:
        return Decimal(text)
    except Exception as exc:  # noqa: BLE001 - re-raised with a readable message
        raise ValueError(f"قيمة رقمية غير صحيحة: {value}") from exc
