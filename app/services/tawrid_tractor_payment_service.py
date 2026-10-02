"""Tractor payment (سند صرف الجرار) queries for the Tawrid module — phase 8.

The payment voucher screen replaces the Access table ``SanadCAR`` («مدفوعات
الجرارات»): a flat log of one payment handed to one tractor/driver. The generic
``ReviewDataService`` handles the row's own INSERT / UPDATE / DELETE through
``TABLE_SPECS['tawrid_tractor_payments']``; everything this service adds is the
work around it:

* allocating the next payment number (``payment_no``) — Access had none, only a
  row id, so a visible unique number is assigned here;
* loading one payment back **joined** to the tractor so the screen can show the
  driver's name without a second query;
* the **live account summary** for the chosen tractor — opening balance, قيمة
  النقلات المستحقة له (``SUM(total_man)``) and المصروف — reused from
  :class:`app.services.tawrid_tractor_service.TawridTractorService` so
  «المصروف»/«الرصيد» here and on the tractors screen never diverge; and
* the rows for the «بحث عن سند صرف جرار» dialog.

The tractor's balance is the **mirror** of the crusher's: a positive balance is
what *we owe the driver*, and overpayment is real — so the balance goes negative
cleanly and is never clamped.

No presentation logic lives here: it returns values, and the screen formats them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.database.db import Database
from app.services.tawrid_tractor_service import TawridTractorService, TractorBalance


@dataclass(frozen=True)
class PaymentAccount:
    """A tractor's account as it stands *excluding* one payment being edited.

    ``base_paid`` is every payment for the tractor **except** the one on screen,
    so the screen can preview «قبل / بعد» consistently whether the user is
    entering a new payment (nothing of theirs is paid yet) or viewing a saved one
    (its own amount is taken back out first).
    """

    opening_balance: Decimal = Decimal("0")
    earned: Decimal = Decimal("0")      # قيمة النقلات المستحقة له (SUM(total_man))
    base_paid: Decimal = Decimal("0")   # المصروف ما عدا السند الحالي
    trips_count: int = 0
    movements_available: bool = False

    @property
    def total_owed(self) -> Decimal:
        """Everything owed to the driver before any payment — رصيد أول + النقلات."""
        return self.opening_balance + self.earned


class TawridTractorPaymentService:
    PAYMENTS_TABLE = "tawrid_tractor_payments"

    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()
        # Shares the same connection so the balance figures come from one place.
        self._tractors = TawridTractorService(self._db)

    # -- helpers ---------------------------------------------------------

    def _scalar(self, query: str, params: list[Any], key: str, default: Any) -> Any:
        row = self._db.fetch_one(query, params)
        if not row or row.get(key) is None:
            return default
        return row[key]

    @staticmethod
    def _dec(value: Any) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        return Decimal(str(value))

    # -- numbering -------------------------------------------------------

    def next_payment_no(self) -> int:
        """The next free payment number — ``MAX(payment_no) + 1``, starting at 1.

        A display-only suggestion for a new voucher: the user may overwrite it,
        and the UNIQUE index on ``payment_no`` is what actually guarantees no two
        payments share one. Continuing from the maximum (not the count) is the
        only safe rule once numbers have gaps.
        """
        row = self._db.fetch_one(
            f"SELECT COALESCE(MAX(payment_no), 0) + 1 AS n FROM {self.PAYMENTS_TABLE}"
        )
        return int(row["n"]) if row else 1

    def payment_no_exists(self, payment_no: Any, exclude_id: Any = None) -> bool:
        """Whether *payment_no* is already taken (optionally ignoring one row).

        Lets the screen warn before the UNIQUE index raises a raw error on save.
        """
        if payment_no in (None, ""):
            return False
        if exclude_id in (None, ""):
            row = self._db.fetch_one(
                f"SELECT 1 AS x FROM {self.PAYMENTS_TABLE} WHERE payment_no = %s LIMIT 1",
                [payment_no],
            )
        else:
            row = self._db.fetch_one(
                f"SELECT 1 AS x FROM {self.PAYMENTS_TABLE} "
                "WHERE payment_no = %s AND payment_id <> %s LIMIT 1",
                [payment_no, exclude_id],
            )
        return bool(row)

    # -- picker rows ------------------------------------------------------

    def tractor_picker_rows(self) -> list[dict[str, Any]]:
        """Tractor cards for the payment tractor picker, active-first.

        Same identity columns the الجرارات picker shows (name / رقم الوش / رقم
        المقطورة). The stopped (موقوف) cards stay reachable — they are the only way
        to open a payment on a recovered/deleted tractor — but never sit above an
        active card, mirroring the crusher-side ``picker_rows``.
        """
        return list(
            self._db.fetch_all(
                "SELECT tractor_id, tractor_code, driver_name, trailer_no, head_no, "
                "is_active "
                "FROM tawrid_tractors ORDER BY is_active DESC, driver_name"
            )
        )

    # -- the live account summary ----------------------------------------

    def account_for(self, tractor_id: Any, exclude_payment_id: Any = None) -> PaymentAccount:
        """The tractor's account, with one payment optionally taken back out.

        Delegates the opening/earned/paid figures to
        :class:`TawridTractorService` (one source of truth for «الرصيد»), then
        subtracts the amount of ``exclude_payment_id`` from المصروف so the screen
        can show the balance *before* and *after* the payment on screen. For a
        brand-new payment pass ``exclude_payment_id=None`` — nothing is taken out.
        """
        if tractor_id in (None, ""):
            return PaymentAccount()
        balance: TractorBalance = self._tractors.for_tractor(tractor_id)
        base_paid = balance.paid
        if exclude_payment_id not in (None, ""):
            own = self._dec(
                self._scalar(
                    f"SELECT amount FROM {self.PAYMENTS_TABLE} WHERE payment_id = %s",
                    [exclude_payment_id],
                    "amount",
                    Decimal("0"),
                )
            )
            base_paid = balance.paid - own
        return PaymentAccount(
            opening_balance=balance.opening_balance,
            earned=balance.earned,
            base_paid=base_paid,
            trips_count=balance.trips_count,
            movements_available=balance.movements_available,
        )

    # -- one payment, joined for display ---------------------------------

    def for_payment(self, payment_id: Any) -> dict[str, Any] | None:
        """Load one payment joined to the tractor card (driver name + مسلسل)."""
        if payment_id in (None, ""):
            return None
        return self._db.fetch_one(
            f"""
            SELECT p.payment_id, p.payment_no, p.payment_date, p.tractor_id,
                   p.amount, p.statement,
                   t.driver_name, t.tractor_code
              FROM {self.PAYMENTS_TABLE} p
              LEFT JOIN tawrid_tractors t ON t.tractor_id = p.tractor_id
             WHERE p.payment_id = %s
            """,
            [payment_id],
        )

    # -- the search dialog ------------------------------------------------

    def search_payments(self, keyword: str = "", limit: int = 300) -> list[dict[str, Any]]:
        """Rows for the «بحث عن سند صرف جرار» dialog: newest first, filtered.

        Matches the payment number, the driver name or the بيان. An empty keyword
        returns the most recent *limit* payments so the dialog opens on something
        useful rather than blank.
        """
        needle = str(keyword or "").strip()
        base = f"""
            SELECT p.payment_id, p.payment_no, p.payment_date, p.amount, p.statement,
                   t.driver_name
              FROM {self.PAYMENTS_TABLE} p
              LEFT JOIN tawrid_tractors t ON t.tractor_id = p.tractor_id
        """
        if needle:
            like = f"%{needle}%"
            rows = self._db.fetch_all(
                base
                + """
                 WHERE CAST(p.payment_no AS TEXT) ILIKE %s
                    OR COALESCE(t.driver_name, '') ILIKE %s
                    OR COALESCE(p.statement, '') ILIKE %s
                 ORDER BY p.payment_no DESC
                 LIMIT %s
                """,
                [like, like, like, limit],
            )
        else:
            rows = self._db.fetch_all(
                base + " ORDER BY p.payment_no DESC LIMIT %s", [limit]
            )
        return list(rows)
