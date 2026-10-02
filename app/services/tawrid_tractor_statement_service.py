"""كشف حساب الجرارات — قسم التوريدات (statement 3/3, the LAST).

The **third and last** of the three account statements (customer / crusher /
tractor), the read-only re-creation of the Access report ``Acccgarar``
(«كشف حساب الجرارات»). Read field-by-field from the running ``.accdb`` via COM:
``Acccgarar`` binds the query ``HissapGarar`` which filters the view
``Gararunion`` by ``maatora_id = Forms!Reports!Shop`` and ``date123 BETWEEN d1
AND d2``. ``Gararunion`` is a ``UNION ALL`` of three sources:

* **رصيد أول المدة** — ``tbgrarat.BalancFirst`` (a debit opening line);
* **بون مندوب** — ``TBBOOn.totalman`` (= ``Pricemand × Tak3ib``, the *customer's*
  volume), the tractor/hauler's layer of the ticket (debit);
* **مدفوعات الجرارات** — ``SanadCAR.amount`` (credit).

and its «حساب قديم» (``v1 = z1 − z2``) is the balance carried forward from
*before* the «من تاريخ» filter — exactly the customer statement's carry-forward.

Almost everything is inherited from :class:`TawridStatementService`, the
config-driven base built for the customer statement: only the
:class:`StatementConfig` differs. The **one tractor-specific difference** is the
«ملخص البونات»: like the customer statement the tractor HAS one, but the Access
subreport ``HelpSaSubreport`` (RecordSource ``HisspCountcus``) groups it by the
**customer** (``GROUP BY cus_id, Pricemand, Tak3ib``), not by the item — so the
«الصنف» column becomes the customer name. :meth:`bon_summary` is overridden here
to do that join; everything else (the ledger, the carry-forward, the running
balance, the export) is the shared base.

The whole-account balance is **not** re-derived here: it is delegated to
:class:`app.services.tawrid_tractor_service.TawridTractorService.for_tractor`,
the single source of truth for «الرصيد» (opening + Σ``total_man`` − Σ``amount``,
negative = overpaid — the recovered legacy tractor 27 sits at −13,139.50), so an
unfiltered statement's closing balance always equals the figure on the tractors
screen and the tractor-payment screen.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.database.db import Database
from app.services.tawrid_customer_statement_service import (
    CUSTOMER_COLUMNS,
    BonSummary,
    BonSummaryRow,
    StatementColumn,
    StatementConfig,
    StatementResult,  # re-exported for the screen's type hints
    TawridStatementService,
    _dec,
)

__all__ = [
    "TRACTOR_STATEMENT_CONFIG",
    "TRACTOR_BON_SUMMARY_COLUMNS",
    "StatementResult",
    "TawridTractorStatementService",
]

# The tractor «ملخص البونات» columns — identical to the customer's except the
# grouping key is the **customer name** (Access ``HelpSaSubreport``: «اسم العميل»),
# not the item. The count/price/volume/gross/meters columns are the same shape.
TRACTOR_BON_SUMMARY_COLUMNS: tuple[StatementColumn, ...] = (
    StatementColumn("serial", "م"),
    StatementColumn("item", "اسم العميل"),
    StatementColumn("count", "عدد النقلات"),
    StatementColumn("price", "السعر"),
    StatementColumn("volume", "التكعيب"),
    StatementColumn("gross", "الإجمالى"),
    StatementColumn("meters", "إجمالى الأمتار"),
)

# The tractor wiring. Same party-neutral ledger columns as the customer/crusher
# (م / التاريخ / نوع الإذن / الخامة / السعر / التكعيب / رقم البون / رقم الإيصال /
# رقم المقطورة / مدين / دائن / رصيد جارٍ). The debit layer is the tractor's
# (``total_man`` = ``price_man × cus_volume`` — the hauler is paid on the
# CUSTOMER's volume, Access ``totalman``), and the credit is a سند صرف جرار.
#
# ``debit_gross_col`` is set to ``total_man`` so :meth:`bon_summary` is enabled;
# the base grouping is overridden below to group by customer. The kind strings are
# the real Access ``type22`` values: «بون مندوب» / «مدفوعات الجرارات».
TRACTOR_STATEMENT_CONFIG = StatementConfig(
    party_table="tawrid_tractors",
    party_pk="tractor_id",
    party_name_col="driver_name",       # NB: not supplier_name — the config parameterises this
    party_code_col="tractor_code",
    opening_col="opening_balance",
    opening_date_col="opening_date",
    debit_table="tawrid_tickets",
    debit_fk="tractor_id",
    debit_date_col="ticket_date",
    debit_amount_col="total_man",        # الجرار: Access totalman (Pricemand × Tak3ib)
    debit_desc_col="item_name",
    debit_kind="بون مندوب",             # Access type22 for the ticket layer
    debit_bon_col="ticket_no",           # رقم البون (Access number1)
    debit_eissal_col="receipt_no",       # رقم الإيصال (Access NumberEissal)
    debit_price_col="price_man",         # السعر (Access Pricemand)
    debit_volume_col="cus_volume",       # التكعيب (Access Tak3ib — the customer's volume)
    debit_gross_col="total_man",         # جملة قيمة البون — enables «ملخص البونات»
    debit_join_table="tawrid_tractors",  # رقم المقطورة via the ticket's tractor (constant here)
    debit_join_left="tractor_id",
    debit_join_right="tractor_id",
    debit_join_col="trailer_no",
    debit_join_col2="head_no",           # رقم الوش via the same tractor card
    credit_table="tawrid_tractor_payments",
    credit_fk="tractor_id",
    credit_date_col="payment_date",
    credit_amount_col="amount",
    credit_eissal_col="payment_no",      # رقم الإيصال (Access SanadCAR id)
    credit_desc_col="statement",
    credit_kind="مدفوعات الجرارات",      # Access type22 for the voucher layer
    columns=CUSTOMER_COLUMNS,
    bon_summary_columns=TRACTOR_BON_SUMMARY_COLUMNS,
)


class TawridTractorStatementService(TawridStatementService):
    """كشف حساب الجرارات. Ledger from :class:`TawridStatementService`; the
    whole-account balance delegated to :class:`TawridTractorService`, and the
    «ملخص البونات» grouped by the customer (the Access ``HisspCountcus``)."""

    CONFIG = TRACTOR_STATEMENT_CONFIG

    def __init__(self, db: Database | None = None) -> None:
        super().__init__(db)
        # Shares the one connection so the unfiltered closing balance equals the
        # tractors screen exactly (opening + Σtotal_man − Σamount).
        from app.services.tawrid_tractor_service import TawridTractorService

        self._tractors = TawridTractorService(self._db)

    def whole_account(self, tractor_id: Any):
        """The full-history summary (opening / earned / paid / balance) from the
        single source of truth, for cross-checking an unfiltered run."""
        return self._tractors.for_tractor(tractor_id)

    def party_picker_rows(self) -> list[dict[str, Any]]:
        """Active-first tractor cards for the picker dialog.

        Overridden to add the plate columns (``head_no`` / ``trailer_no``) the
        :class:`TawridTractorPickerDialog` shows, on top of the party
        id/code/name the base query returns — the staff pick a tractor by its
        plate, not its driver name alone.
        """
        return list(
            self._db.fetch_all(
                "SELECT tractor_id AS party_id, tractor_code AS code, "
                "driver_name AS name, head_no, trailer_no, is_active "
                "FROM tawrid_tractors ORDER BY is_active DESC, driver_name"
            )
        )

    def bon_summary(
        self,
        party_id: Any,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> BonSummary:
        """Group the tractor's بونات by (**customer**, price, volume) — the Access
        subreport ``HelpSaSubreport`` / query ``HisspCountcus``.

        This is the one place the tractor statement diverges from the shared base,
        whose :meth:`TawridStatementService.bon_summary` groups by the item name.
        Here the «الصنف» column is the **customer name** (a join to
        ``tawrid_customers``): each group carries its trip count, its gross value
        (Σ``total_man`` = Access ``bal`` = Pricemand × Σnumber × Tak3ib) and its
        metres (Σ``cus_volume``). All بونات are included — the orphan tickets that
        migrated onto the «عميل محذوف» placeholder show as their own group (the
        user's decision), so the summary total reconciles with «إجمالي مدين».
        """
        cfg = self.CONFIG
        if party_id in (None, ""):
            return BonSummary(columns=cfg.bon_summary_columns)
        where = [f"m.{cfg.debit_fk} = %s"]
        params: list[Any] = [party_id]
        if date_from:
            where.append(f"m.{cfg.debit_date_col} >= %s")
            params.append(date_from)
        if date_to:
            where.append(f"m.{cfg.debit_date_col} <= %s")
            params.append(date_to)
        query = f"""
            SELECT c.customer_name AS item,
                   m.{cfg.debit_price_col} AS price,
                   m.{cfg.debit_volume_col} AS volume,
                   COUNT(*) AS cnt,
                   COALESCE(SUM(m.{cfg.debit_gross_col}), 0) AS gross,
                   COALESCE(SUM(m.{cfg.debit_volume_col}), 0) AS meters
              FROM {cfg.debit_table} m
              JOIN tawrid_customers c ON c.customer_id = m.customer_id
             WHERE {' AND '.join(where)}
             GROUP BY c.customer_name, m.{cfg.debit_price_col}, m.{cfg.debit_volume_col}
             ORDER BY c.customer_name, m.{cfg.debit_price_col}, m.{cfg.debit_volume_col}
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
