"""Crusher/supplier queries for the Tawrid module (قسم التوريدات), phase 3.

المورد = الكسّارة — one entity under two names, exactly as in Access, where the
menu button read «بيانات الكسارات» and the form caption «شاشة إدخال بيانات
الموردين», both bound to ``pruduct``.

Three jobs the generic ``ReviewDataService`` cannot do:

* the **account summary** shown on the screen,
* allocating the next مسلسل (``supplier_code``), and
* the **rows the picker dialog needs**, which include a balance so the crusher's
  standing is visible before its card is opened.

Account summary (ملخّص حساب الكسّارة)

    الرصيد = رصيد أول المدة + قيمة البونات − المدفوع

The sign is the mirror of the customer's: a positive balance is what *we owe the
crusher*, not what it owes us. That mirrors the Access report over ``TBBOOn``
(the supplier side, columns ``Priceres``/``Tak3ibres``/``totalres``) UNIONed with
``sanadsup`` (139 payment vouchers) and the opening balance out of ``pruduct``.
Overpayment is real and has to survive: «مكة ستون» sits at −11,125 in the legacy
data, which the Access screen had no way of showing at all.

The movement tables belong to later phases and do not exist yet, so this service
**probes for them** and reports "no movement yet" until they do — the same
approach as :mod:`app.services.tawrid_customer_service`. The screen then starts
showing real figures the moment those phases land, with no change here.

No presentation logic lives here: this returns values, and the screen decides
how to format them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.database.db import Database

# Tables this summary reads from once later phases create them. ``supplier_id``
# on the tickets table is the new home of the Access column ``TBBOOn.[res-id]``.
TICKETS_TABLE = "tawrid_tickets"
PAYMENTS_TABLE = "tawrid_supplier_payments"

# The ten fixed item-price columns, in the order ``Fproduct`` laid them out.
# Used to count how many items a crusher is actually priced for — 56 of the 230
# legacy cells are non-zero, so "9 من 10" is information, not decoration.
PRICE_COLUMNS = (
    "price_sen1",
    "price_sen2",
    "price_sen_ataqa",
    "price_sen6_safi",
    "price_sen6_bodra",
    "price_sen_adsa",
    "price_bodra",
    "price_raml",
    "price_sen_plus",
    "price_sen_modarag",
)


@dataclass(frozen=True)
class SupplierBalance:
    """One crusher's account, in currency units.

    ``purchased`` is what its tickets came to and ``paid`` what we handed over,
    so :attr:`balance` is the amount **owed to** the crusher. A negative balance
    means it was overpaid, which happens in the real data and must not be
    clamped away.
    """

    opening_balance: Decimal = Decimal("0")
    tickets_count: int = 0
    purchased: Decimal = Decimal("0")  # قيمة البونات المستحقة له
    paid: Decimal = Decimal("0")       # المدفوع له
    # True while the movement tables have not been created yet, so the screen can
    # show "—" instead of implying a real zero.
    movements_available: bool = False

    @property
    def balance(self) -> Decimal:
        """Net amount owed to the crusher (negative = overpaid)."""
        return self.opening_balance + self.purchased - self.paid


class TawridSupplierService:
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
        """The next free مسلسل — ``MAX(supplier_code) + 1``, starting at 1.

        A display-only suggestion for a new record; the UNIQUE index on
        ``supplier_code`` is what actually guarantees no two crushers share one.

        This is the fix for the worst defect on ``Fproduct``: its مسلسل box
        defaulted to ``DMax("[number1]","fanii")+1``, which counts the CUSTOMERS
        table. That produced 3 duplicate codes inside ``pruduct`` (26, 31, 46)
        and 5 codes shared with a customer. Counting from this table's own
        maximum — not from the row count, since the legacy numbering runs 1..84
        with gaps — is the whole correction.
        """
        row = self._db.fetch_one(
            "SELECT COALESCE(MAX(supplier_code), 0) + 1 AS next_code FROM tawrid_suppliers"
        )
        return int(row["next_code"]) if row else 1

    # -- account summary --------------------------------------------------

    def for_supplier(self, supplier_id: Any) -> SupplierBalance:
        """Return the account summary for *supplier_id*.

        An unknown/None id yields an all-zero summary rather than raising, so the
        screen can call this freely while the form is empty.
        """
        if supplier_id in (None, ""):
            return SupplierBalance()

        opening = self._scalar(
            "SELECT opening_balance FROM tawrid_suppliers WHERE supplier_id = %s",
            [supplier_id],
            "opening_balance",
            Decimal("0"),
        )

        has_tickets = self._table_exists(TICKETS_TABLE)
        has_payments = self._table_exists(PAYMENTS_TABLE)
        if not (has_tickets or has_payments):
            return SupplierBalance(opening_balance=Decimal(opening))

        tickets = 0
        purchased = Decimal("0")
        if has_tickets:
            # ``total_res`` is the crusher's line on the ticket — the Access
            # column ``totalres`` (= ``Priceres × Tak3ibres``). It is NOT the
            # customer's total: the two volumes differ on 4,015 of the 4,072
            # legacy tickets, which is the whole point of the three price layers.
            row = self._db.fetch_one(
                f"SELECT COUNT(*) AS n, COALESCE(SUM(total_res), 0) AS s "
                f"FROM {TICKETS_TABLE} WHERE supplier_id = %s",
                [supplier_id],
            )
            if row:
                tickets = int(row["n"] or 0)
                purchased = Decimal(row["s"] or 0)

        paid = Decimal("0")
        if has_payments:
            paid = Decimal(
                self._scalar(
                    f"SELECT COALESCE(SUM(amount), 0) AS s "
                    f"FROM {PAYMENTS_TABLE} WHERE supplier_id = %s",
                    [supplier_id],
                    "s",
                    Decimal("0"),
                )
            )

        return SupplierBalance(
            opening_balance=Decimal(opening),
            tickets_count=tickets,
            purchased=purchased,
            paid=paid,
            movements_available=True,
        )

    def has_movement(self, supplier_id: Any) -> int:
        """How many tickets/payments reference this crusher (0 when none).

        Used to refuse deletion. Returns 0 while the movement tables do not yet
        exist, which is correct: nothing can reference the crusher.
        """
        if supplier_id in (None, ""):
            return 0
        total = 0
        for table in (TICKETS_TABLE, PAYMENTS_TABLE):
            if not self._table_exists(table):
                continue
            total += int(
                self._scalar(
                    f"SELECT COUNT(*) AS c FROM {table} WHERE supplier_id = %s",
                    [supplier_id],
                    "c",
                    0,
                )
            )
        return total

    # -- the picker --------------------------------------------------------

    def picker_rows(self) -> list[dict[str, Any]]:
        """Every crusher, with its balance, for the search dialog.

        Active cards first, then by name — the stopped ones stay reachable (they
        are the only way to open a card that was stopped by mistake) but never
        sit above a crusher you can actually buy from. 7 of the 23 legacy cards
        have no movement of any kind.

        While the movement tables do not exist the balance is the opening
        balance, which is exactly what it is.
        """
        has_tickets = self._table_exists(TICKETS_TABLE)
        has_payments = self._table_exists(PAYMENTS_TABLE)

        purchased = (
            f"(SELECT COALESCE(SUM(t.total_res), 0) FROM {TICKETS_TABLE} t "
            f"  WHERE t.supplier_id = s.supplier_id)"
            if has_tickets
            else "0"
        )
        paid = (
            f"(SELECT COALESCE(SUM(p.amount), 0) FROM {PAYMENTS_TABLE} p "
            f"  WHERE p.supplier_id = s.supplier_id)"
            if has_payments
            else "0"
        )
        rows = self._db.fetch_all(
            f"""
            SELECT s.supplier_id, s.supplier_code, s.supplier_name, s.is_active,
                   s.opening_balance,
                   s.opening_balance + {purchased} - {paid} AS balance
              FROM tawrid_suppliers s
             ORDER BY s.is_active DESC, s.supplier_name
            """
        )
        return list(rows)

    def priced_item_count(self, supplier_id: Any) -> int:
        """How many of the ten item prices are non-zero for this crusher.

        The number behind the «أسعار الأصناف» panel heading. It is worth stating
        because the legacy grid is 76% empty: most crushers sell one or two
        items, and «الهدي» — 9 of 10 — is the exception, not the norm.
        """
        if supplier_id in (None, ""):
            return 0
        summed = " + ".join(f"(CASE WHEN {c} <> 0 THEN 1 ELSE 0 END)" for c in PRICE_COLUMNS)
        return int(
            self._scalar(
                f"SELECT ({summed}) AS c FROM tawrid_suppliers WHERE supplier_id = %s",
                [supplier_id],
                "c",
                0,
            )
        )
