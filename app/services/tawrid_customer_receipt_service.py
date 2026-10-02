"""Customer receipt (سند قبض العميل) queries for the Tawrid module — phase 6.

The receipt voucher screen replaces the Access table ``sanadCus`` («مدفوعات
العملاء»): a flat log of one payment collected from one customer. The generic
``ReviewDataService`` handles the row's own INSERT / UPDATE / DELETE through
``TABLE_SPECS['tawrid_customer_receipts']``; everything this service adds is the
work around it:

* allocating the next receipt number (``receipt_no``) — Access had none, only a
  row id, so a visible unique number is assigned here;
* loading one receipt back **joined** to the customer so the screen can show the
  name without a second query;
* the **live account summary** for the chosen customer — opening balance, البونات
  المستحقة and المحصّل — reused from :class:`app.services.tawrid_customer_service.TawridCustomerService`
  so «المحصّل»/«الرصيد» here and on the customers screen never diverge; and
* the rows for the «بحث عن سند» dialog.

No presentation logic lives here: it returns values, and the screen formats them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.database.db import Database
from app.services.tawrid_customer_service import CustomerBalance, TawridCustomerService


@dataclass(frozen=True)
class ReceiptAccount:
    """A customer's account as it stands *excluding* one receipt being edited.

    ``base_collected`` is every receipt for the customer **except** the one on
    screen, so the screen can preview «قبل / بعد» consistently whether the user is
    entering a new receipt (nothing of theirs is collected yet) or viewing a saved
    one (its own amount is taken back out first).
    """

    opening_balance: Decimal = Decimal("0")
    invoiced: Decimal = Decimal("0")        # قيمة البونات المستحقة على العميل
    base_collected: Decimal = Decimal("0")  # المحصّل ما عدا السند الحالي
    tickets_count: int = 0
    movements_available: bool = False

    @property
    def total_due(self) -> Decimal:
        """Everything the customer owes before any collection — رصيد أول + البونات."""
        return self.opening_balance + self.invoiced


class TawridCustomerReceiptService:
    RECEIPTS_TABLE = "tawrid_customer_receipts"

    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()
        # Shares the same connection so the balance figures come from one place.
        self._customers = TawridCustomerService(self._db)

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

    def next_receipt_no(self) -> int:
        """The next free receipt number — ``MAX(receipt_no) + 1``, starting at 1.

        A display-only suggestion for a new voucher: the user may overwrite it,
        and the UNIQUE index on ``receipt_no`` is what actually guarantees no two
        receipts share one. Continuing from the maximum (not the count) is the
        only safe rule once numbers have gaps.
        """
        row = self._db.fetch_one(
            f"SELECT COALESCE(MAX(receipt_no), 0) + 1 AS n FROM {self.RECEIPTS_TABLE}"
        )
        return int(row["n"]) if row else 1

    def receipt_no_exists(self, receipt_no: Any, exclude_id: Any = None) -> bool:
        """Whether *receipt_no* is already taken (optionally ignoring one row).

        Lets the screen warn before the UNIQUE index raises a raw error on save.
        """
        if receipt_no in (None, ""):
            return False
        if exclude_id in (None, ""):
            row = self._db.fetch_one(
                f"SELECT 1 AS x FROM {self.RECEIPTS_TABLE} WHERE receipt_no = %s LIMIT 1",
                [receipt_no],
            )
        else:
            row = self._db.fetch_one(
                f"SELECT 1 AS x FROM {self.RECEIPTS_TABLE} "
                "WHERE receipt_no = %s AND receipt_id <> %s LIMIT 1",
                [receipt_no, exclude_id],
            )
        return bool(row)

    # -- picker rows ------------------------------------------------------

    def customer_picker_rows(self) -> list[dict[str, Any]]:
        """Active-first customer cards for the receipt customer picker."""
        return list(
            self._db.fetch_all(
                "SELECT customer_id, customer_code, customer_name, phone, is_active "
                "FROM tawrid_customers ORDER BY is_active DESC, customer_name"
            )
        )

    # -- the live account summary ----------------------------------------

    def account_for(self, customer_id: Any, exclude_receipt_id: Any = None) -> ReceiptAccount:
        """The customer's account, with one receipt optionally taken back out.

        Delegates the opening/invoiced/collected figures to
        :class:`TawridCustomerService` (one source of truth for «الرصيد»), then
        subtracts the amount of ``exclude_receipt_id`` from المحصّل so the screen
        can show the balance *before* and *after* the receipt on screen. For a
        brand-new receipt pass ``exclude_receipt_id=None`` — nothing is taken out.
        """
        if customer_id in (None, ""):
            return ReceiptAccount()
        balance: CustomerBalance = self._customers.for_customer(customer_id)
        base_collected = balance.collected
        if exclude_receipt_id not in (None, ""):
            own = self._dec(
                self._scalar(
                    f"SELECT amount FROM {self.RECEIPTS_TABLE} WHERE receipt_id = %s",
                    [exclude_receipt_id],
                    "amount",
                    Decimal("0"),
                )
            )
            base_collected = balance.collected - own
        return ReceiptAccount(
            opening_balance=balance.opening_balance,
            invoiced=balance.invoiced,
            base_collected=base_collected,
            tickets_count=balance.tickets_count,
            movements_available=balance.movements_available,
        )

    # -- one receipt, joined for display ---------------------------------

    def for_receipt(self, receipt_id: Any) -> dict[str, Any] | None:
        """Load one receipt joined to the customer card (name + مسلسل)."""
        if receipt_id in (None, ""):
            return None
        return self._db.fetch_one(
            f"""
            SELECT r.receipt_id, r.receipt_no, r.receipt_date, r.customer_id,
                   r.amount, r.statement,
                   c.customer_name, c.customer_code
              FROM {self.RECEIPTS_TABLE} r
              LEFT JOIN tawrid_customers c ON c.customer_id = r.customer_id
             WHERE r.receipt_id = %s
            """,
            [receipt_id],
        )

    # -- the search dialog ------------------------------------------------

    def search_receipts(self, keyword: str = "", limit: int = 300) -> list[dict[str, Any]]:
        """Rows for the «بحث عن سند» dialog: newest first, filtered by keyword.

        Matches the receipt number, the customer name or the بيان. An empty
        keyword returns the most recent *limit* receipts so the dialog opens on
        something useful rather than blank.
        """
        needle = str(keyword or "").strip()
        base = f"""
            SELECT r.receipt_id, r.receipt_no, r.receipt_date, r.amount, r.statement,
                   c.customer_name
              FROM {self.RECEIPTS_TABLE} r
              LEFT JOIN tawrid_customers c ON c.customer_id = r.customer_id
        """
        if needle:
            like = f"%{needle}%"
            rows = self._db.fetch_all(
                base
                + """
                 WHERE CAST(r.receipt_no AS TEXT) ILIKE %s
                    OR COALESCE(c.customer_name, '') ILIKE %s
                    OR COALESCE(r.statement, '') ILIKE %s
                 ORDER BY r.receipt_no DESC
                 LIMIT %s
                """,
                [like, like, like, limit],
            )
        else:
            rows = self._db.fetch_all(
                base + " ORDER BY r.receipt_no DESC LIMIT %s", [limit]
            )
        return list(rows)
