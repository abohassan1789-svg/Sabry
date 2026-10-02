"""Read-only database layer for the Loading Vouchers report (تقرير سندات التحميل).

This is the ONLY place SQL for this report lives. It returns plain, read-only row
dicts; the service (``app/services/loading_voucher_report_service.py``) does all
Arabic labels, weight parsing / formatting, the three summary cards and the
validation, and the UI never sees SQL.

The report reads the ``loading_vouchers`` table directly (a flat, single-item
document — see ``app/models/loading_voucher.py``). It never writes. The filter
drop-downs are populated from the DISTINCT values actually present in that table,
so a filter only ever offers customers / items / vehicles that have vouchers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.db import Database
from app.models.loading_voucher import TBL_LOADING_VOUCHERS

# Picker/list guard — the drop-downs are DISTINCT over a single small table, but
# keep an upper bound so an unexpectedly huge table never floods a combo.
DEFAULT_OPTION_LIMIT = 1000


@dataclass(frozen=True)
class LoadingVoucherReportFilters:
    """Normalised query input. Every field is optional (``None`` = no restriction
    on that dimension); dates are ``YYYY-MM-DD`` strings or ``None`` (open-ended)."""

    date_from: str | None = None
    date_to: str | None = None
    customer_id: int | None = None
    product_id: int | None = None
    vehicle_number: str | None = None


# The detail columns read for the report, in the required display order. The UI
# renders RTL, so the first column (رقم السند) shows on the right.
_DETAIL_COLUMNS = (
    "voucher_number",
    "voucher_date",
    "voucher_time",
    "customer_name_snapshot",
    "item_name_snapshot",
    "driver_name",
    "vehicle_number",
    "weight_before_loading",
    "weight_after_loading",
    "notes",
)
_DETAIL_SELECT = ", ".join(_DETAIL_COLUMNS)


class LoadingVoucherReportRepository:
    """Read-only SQL for the loading-vouchers report detail rows + filter options."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    # -- detail rows ---------------------------------------------------------
    def fetch_rows(self, filters: LoadingVoucherReportFilters) -> list[dict[str, Any]]:
        """Return every loading voucher matching the filters, oldest first.

        Ordered deterministically on ``voucher_date`` then ``voucher_time`` then
        ``id`` so the on-screen order is stable and reproducible.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if filters.date_from:
            conditions.append("voucher_date >= %s::date")
            params.append(filters.date_from)
        if filters.date_to:
            conditions.append("voucher_date <= %s::date")
            params.append(filters.date_to)
        if filters.customer_id is not None:
            conditions.append("customer_id = %s")
            params.append(int(filters.customer_id))
        if filters.product_id is not None:
            conditions.append("product_id = %s")
            params.append(int(filters.product_id))
        if filters.vehicle_number:
            conditions.append("vehicle_number = %s")
            params.append(filters.vehicle_number)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = (
            f"SELECT {_DETAIL_SELECT} FROM {TBL_LOADING_VOUCHERS}"
            f"{where} ORDER BY voucher_date, voucher_time, id"
        )
        return self.db.fetch_all(sql, params)

    # -- filter drop-down options (DISTINCT over the vouchers) ---------------
    def fetch_customer_options(self, limit: int = DEFAULT_OPTION_LIMIT) -> list[dict[str, Any]]:
        """Distinct (customer_id, name) pairs used by any voucher, name-ordered."""
        return self.db.fetch_all(
            "SELECT customer_id AS id, "
            "MAX(customer_name_snapshot) AS label "
            f"FROM {TBL_LOADING_VOUCHERS} WHERE customer_id IS NOT NULL "
            "GROUP BY customer_id ORDER BY label NULLS LAST LIMIT %s",
            [int(limit)],
        )

    def fetch_item_options(self, limit: int = DEFAULT_OPTION_LIMIT) -> list[dict[str, Any]]:
        """Distinct (product_id, name) pairs used by any voucher, name-ordered."""
        return self.db.fetch_all(
            "SELECT product_id AS id, "
            "MAX(item_name_snapshot) AS label "
            f"FROM {TBL_LOADING_VOUCHERS} WHERE product_id IS NOT NULL "
            "GROUP BY product_id ORDER BY label NULLS LAST LIMIT %s",
            [int(limit)],
        )

    def fetch_vehicle_options(self, limit: int = DEFAULT_OPTION_LIMIT) -> list[dict[str, Any]]:
        """Distinct non-blank vehicle numbers (free text) used by any voucher.

        The value doubles as the id and the label — there is no vehicles master."""
        return self.db.fetch_all(
            "SELECT vehicle_number AS id, vehicle_number AS label "
            f"FROM {TBL_LOADING_VOUCHERS} "
            "WHERE vehicle_number IS NOT NULL AND btrim(vehicle_number) <> '' "
            "GROUP BY vehicle_number ORDER BY vehicle_number LIMIT %s",
            [int(limit)],
        )

    # -- company letterhead (read-only; the first registered company) -------
    def fetch_company_letterhead(self) -> dict[str, Any] | None:
        """Return the first registered company for the printable letterhead.

        Mirrors ``PurchaseReportRepository.fetch_company_letterhead`` — the same
        establishment header the other reports print. Print/PDF only; the
        on-screen report never renders it. ``None`` if no company is registered,
        and any read error yields ``None`` so printing never breaks.
        """
        try:
            return self.db.fetch_one(
                "SELECT id, name_ar, name_en, commercial_registration, vat_number, "
                "phone, address_ar, address_en, logo, logo_mime "
                "FROM companies ORDER BY id LIMIT 1"
            )
        except Exception:  # noqa: BLE001 - letterhead is optional; never block print
            return None


__all__ = [
    "LoadingVoucherReportRepository",
    "LoadingVoucherReportFilters",
    "DEFAULT_OPTION_LIMIT",
]
