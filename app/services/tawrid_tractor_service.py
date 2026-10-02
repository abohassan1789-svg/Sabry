"""Tractor-specific queries for the Tawrid module (قسم التوريدات).

Two jobs the generic ``ReviewDataService`` cannot do, because both are specific
to how a tractor account works:

* the account summary shown on the screen, and
* allocating the next مسلسل (``tractor_code``), which is the staff-facing number
  and is independent of the surrogate ``tractor_id`` primary key.

Account summary (ملخّص حساب الجرار)

Answers the question the tractors screen exists to answer at a glance: *how much
do we owe this driver right now?*

    الرصيد = رصيد أول المدة + قيمة النقلات − المدفوع

The movement side of that sum lives in tables built by later phases of the
Tawrid module — ``tawrid_tickets`` (البونات) and ``tawrid_tractor_payments``
(سندات صرف الجرارات). Neither exists yet, so this service **probes for them** and
reports zero movement until they do. That keeps phase 1 shippable on its own and
means the panel starts showing real figures the moment those phases land, with
no change here.

No presentation logic lives in this module: it returns numbers, and the screen
decides how to format them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.database.db import Database

# Tables this summary reads from once later phases create them.
TICKETS_TABLE = "tawrid_tickets"
PAYMENTS_TABLE = "tawrid_tractor_payments"


@dataclass(frozen=True)
class TractorBalance:
    """One tractor's account, in currency units."""

    opening_balance: Decimal = Decimal("0")
    trips_count: int = 0
    earned: Decimal = Decimal("0")   # قيمة النقلات المستحقة له
    paid: Decimal = Decimal("0")     # المصروف له
    # True while the movement tables have not been created yet, so the screen
    # can say "لم تُفعّل بعد" instead of implying a real zero.
    movements_available: bool = False

    @property
    def balance(self) -> Decimal:
        """Net amount owed to the driver."""
        return self.opening_balance + self.earned - self.paid


class TawridTractorService:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()

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

    def next_code(self) -> int:
        """The next free مسلسل — ``MAX(tractor_code) + 1``, starting at 1.

        Display-only suggestion for a new record: the user may overwrite it, and
        the UNIQUE index on ``tractor_code`` is what actually guarantees no two
        tractors share one.
        """
        row = self._db.fetch_one(
            "SELECT COALESCE(MAX(tractor_code), 0) + 1 AS next_code FROM tawrid_tractors"
        )
        return int(row["next_code"]) if row else 1

    def for_tractor(self, tractor_id: Any) -> TractorBalance:
        """Return the account summary for *tractor_id*.

        An unknown/None id yields an all-zero summary rather than raising, so the
        screen can call this freely while the form is empty.
        """
        if tractor_id in (None, ""):
            return TractorBalance()

        opening = self._scalar(
            "SELECT opening_balance FROM tawrid_tractors WHERE tractor_id = %s",
            [tractor_id],
            "opening_balance",
            Decimal("0"),
        )

        has_tickets = self._table_exists(TICKETS_TABLE)
        has_payments = self._table_exists(PAYMENTS_TABLE)
        if not (has_tickets or has_payments):
            return TractorBalance(opening_balance=Decimal(opening))

        trips = 0
        earned = Decimal("0")
        if has_tickets:
            row = self._db.fetch_one(
                f"SELECT COUNT(*) AS n, COALESCE(SUM(total_man), 0) AS s "
                f"FROM {TICKETS_TABLE} WHERE tractor_id = %s",
                [tractor_id],
            )
            if row:
                trips = int(row["n"] or 0)
                earned = Decimal(row["s"] or 0)

        paid = Decimal("0")
        if has_payments:
            paid = Decimal(
                self._scalar(
                    f"SELECT COALESCE(SUM(amount), 0) AS s "
                    f"FROM {PAYMENTS_TABLE} WHERE tractor_id = %s",
                    [tractor_id],
                    "s",
                    Decimal("0"),
                )
            )

        return TractorBalance(
            opening_balance=Decimal(opening),
            trips_count=trips,
            earned=earned,
            paid=paid,
            movements_available=True,
        )
