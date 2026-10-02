"""كشف حساب الكسّارات — قسم التوريدات (statement 2/3).

The **second** of the three account statements (customer / crusher / tractor),
the read-only re-creation of the Access report ``ACCSUP`` («كشف حساب الكسارات»).
Read field-by-field from the running ``.accdb`` via COM: ``ACCSUP`` binds the
query ``HissBalaSUP`` which filters the view ``supplierunion`` by
``[res-id] = Forms!Reports!st1`` and ``date123 BETWEEN d1 AND d2``.
``supplierunion`` is a ``UNION ALL`` of three sources:

* **رصيد اول المدة** — ``pruduct.BalancFirst`` (a debit opening line);
* **بون مورد** — ``TBBOOn.totalres`` (= ``Priceres × Tak3ibres``), the crusher's
  layer of the ticket (debit);
* **مدفوعات للمورد** — ``sanadsup.amount`` (credit).

and its «حساب قديم» (``v1 = z1 − z2``) is the balance carried forward from
*before* the «من تاريخ» filter — exactly the customer statement's carry-forward.

Everything is inherited from :class:`TawridStatementService`, the config-driven
base built for the customer statement: only the :class:`StatementConfig` differs.
The **one crusher-specific difference from the customer statement is that there is
no «ملخص البونات»** — ``ACCSUP`` carries no subreport (verified: no ``acSubreport``
control on the report). That is expressed here by leaving ``debit_gross_col`` unset,
which makes :meth:`TawridStatementService.bon_summary` return an empty summary; the
screen drops the button and the print drops the checkbox as well.

The whole-account balance is **not** re-derived here: it is delegated to
:class:`app.services.tawrid_supplier_service.TawridSupplierService.for_supplier`,
the single source of truth for «الرصيد» (opening + Σ``total_res`` − Σ``amount``,
negative = overpaid), so an unfiltered statement's closing balance always equals
the figure on the crushers screen.
"""

from __future__ import annotations

from typing import Any

from app.database.db import Database
from app.services.tawrid_customer_statement_service import (
    CUSTOMER_COLUMNS,
    StatementConfig,
    StatementResult,  # re-exported for the screen's type hints
    TawridStatementService,
)

__all__ = [
    "SUPPLIER_STATEMENT_CONFIG",
    "StatementResult",
    "TawridSupplierStatementService",
]

# The crusher wiring. Same ledger columns as the customer (they are party-neutral
# — م / التاريخ / نوع الإذن / الخامة / السعر / التكعيب / رقم البون / رقم الإيصال /
# رقم المقطورة / مدين / دائن / رصيد جارٍ). The debit layer is the crusher's
# (``total_res`` = ``price_res × res_volume``, the Access ``totalres``), NOT the
# customer's — the two ticket volumes differ on 4,015 of the 4,072 legacy rows.
#
# ``debit_gross_col`` is deliberately left ``None``: the crusher statement has no
# «ملخص البونات» (``ACCSUP`` has no subreport), and an unset gross column makes
# ``bon_summary()`` return empty.
SUPPLIER_STATEMENT_CONFIG = StatementConfig(
    party_table="tawrid_suppliers",
    party_pk="supplier_id",
    party_name_col="supplier_name",
    party_code_col="supplier_code",
    opening_col="opening_balance",
    opening_date_col="opening_date",
    debit_table="tawrid_tickets",
    debit_fk="supplier_id",
    debit_date_col="ticket_date",
    debit_amount_col="total_res",       # الكسّارة: Access totalres (Priceres × Tak3ibres)
    debit_desc_col="item_name",
    debit_kind="بون مورد",
    debit_bon_col="ticket_no",          # رقم البون (Access number1)
    debit_eissal_col="receipt_no",      # رقم الإيصال (Access NumberEissal)
    debit_price_col="price_res",        # السعر (Access Priceres)
    debit_volume_col="res_volume",      # التكعيب (Access Tak3ibres)
    debit_gross_col=None,               # NO «ملخص البونات» for the crusher
    debit_join_table="tawrid_tractors",  # رقم المقطورة via the ticket's tractor
    debit_join_left="tractor_id",
    debit_join_right="tractor_id",
    debit_join_col="trailer_no",
    debit_join_col2="head_no",           # رقم الوش via the same tractor card
    credit_table="tawrid_supplier_payments",
    credit_fk="supplier_id",
    credit_date_col="payment_date",
    credit_amount_col="amount",
    credit_eissal_col="payment_no",     # رقم الإيصال (Access sanadsup id)
    credit_desc_col="statement",
    credit_kind="مدفوعات للمورد",
    columns=CUSTOMER_COLUMNS,
)


class TawridSupplierStatementService(TawridStatementService):
    """كشف حساب الكسّارات. Ledger from :class:`TawridStatementService`; the
    whole-account balance delegated to :class:`TawridSupplierService`."""

    CONFIG = SUPPLIER_STATEMENT_CONFIG

    def __init__(self, db: Database | None = None) -> None:
        super().__init__(db)
        # Shares the one connection so the unfiltered closing balance equals the
        # crushers screen exactly (opening + Σtotal_res − Σamount).
        from app.services.tawrid_supplier_service import TawridSupplierService

        self._suppliers = TawridSupplierService(self._db)

    def whole_account(self, supplier_id: Any):
        """The full-history summary (opening / purchased / paid / balance) from
        the single source of truth, for cross-checking an unfiltered run."""
        return self._suppliers.for_supplier(supplier_id)
