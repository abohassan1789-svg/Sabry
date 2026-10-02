"""Business logic for the Loading Vouchers report (تقرير سندات التحميل).

The UI calls only this service; this service calls only the repository. No SQL
and no Qt widgets live here — just the row mapping, the Arabic labels, the three
summary cards and the filter-option loaders, plus the input validation.

The report is strictly **read-only**: opening or refreshing it performs SELECTs
only. It lists one row per loading voucher (the flat, single-item document) with
all ten fields, and derives three cards from those same rows in Python — a single
database round-trip for the whole screen.

Weights are free text
---------------------
``weight_before_loading`` / ``weight_after_loading`` are ``varchar`` free-text
columns (there is no scale integration): a user may type ``"12500"``, ``"12,500"``,
``"12.5 طن"`` or leave them blank. The detail table therefore shows the stored
text **verbatim** — never a reformatted value the user did not type. The two
weight cards, however, need a number, so :func:`_parse_weight` extracts the first
numeric value it can find (Arabic-Indic digits normalised to Latin, thousands
separators dropped) and the cards sum those with :class:`decimal.Decimal`. A cell
with no parseable number simply contributes zero — it is never an error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal, InvalidOperation
from typing import Any

from app.repositories.loading_voucher_report_repository import (
    LoadingVoucherReportFilters,
    LoadingVoucherReportRepository,
)

_ZERO = Decimal("0")

# Arabic-Indic (٠-٩) and Eastern-Arabic (۰-۹) digits -> Latin, so a weight typed
# with Arabic numerals still sums.
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
# First numeric token in a free-text weight: optional sign, digit groups with
# optional thousands commas, optional decimal part.
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

EMPTY_MESSAGE = "لا توجد سندات تحميل خلال الفترة/الفلاتر المحددة"


class LoadingVoucherReportValidationError(Exception):
    """Raised for invalid filters. ``message`` is a ready-to-show Arabic string."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class ReportColumn:
    """Lightweight column descriptor reused by the UI and later exporters."""

    key: str
    label: str


@dataclass(frozen=True)
class LoadingVoucherReportRequest:
    date_from: str | None = None
    date_to: str | None = None
    customer_id: Any = None
    product_id: Any = None
    vehicle_number: str | None = None


@dataclass(frozen=True)
class LoadingVoucherReportResult:
    columns: list[ReportColumn]
    rows: list[dict[str, Any]]           # display strings keyed by column.key
    summary: dict[str, Any]              # the three cards (count + two weight totals)
    is_empty: bool


# The ten required detail columns, in display order. RTL -> رقم السند on the right.
REPORT_COLUMNS: tuple[ReportColumn, ...] = (
    ReportColumn("voucher_number", "رقم السند"),
    ReportColumn("voucher_date", "التاريخ"),
    ReportColumn("voucher_time", "الوقت"),
    ReportColumn("customer_name", "اسم العميل"),
    ReportColumn("item_name", "اسم الصنف"),
    ReportColumn("driver_name", "اسم السائق"),
    ReportColumn("vehicle_number", "رقم السيارة"),
    ReportColumn("weight_before", "الوزن قبل التحميل"),
    ReportColumn("weight_after", "الوزن بعد التحميل"),
    ReportColumn("notes", "ملاحظات"),
)


class LoadingVoucherReportService:
    """Build the read-only loading-vouchers report + its three summary cards."""

    def __init__(self, repository: LoadingVoucherReportRepository | None = None) -> None:
        self.repository = repository or LoadingVoucherReportRepository()
        self.columns = list(REPORT_COLUMNS)

    # --- public API ---------------------------------------------------------
    def fetch_report(
        self, request: LoadingVoucherReportRequest
    ) -> LoadingVoucherReportResult:
        date_from, date_to = self._validate_dates(request.date_from, request.date_to)

        filters = LoadingVoucherReportFilters(
            date_from=date_from,
            date_to=date_to,
            customer_id=self._as_int(request.customer_id),
            product_id=self._as_int(request.product_id),
            vehicle_number=self._clean(request.vehicle_number),
        )
        raw_rows = self.repository.fetch_rows(filters)

        rows: list[dict[str, Any]] = []
        total_before = _ZERO
        total_after = _ZERO
        for raw in raw_rows:
            before_text = self._text(raw.get("weight_before_loading"))
            after_text = self._text(raw.get("weight_after_loading"))
            total_before += self._parse_weight(before_text)
            total_after += self._parse_weight(after_text)
            rows.append(
                {
                    "voucher_number": self._text(raw.get("voucher_number")),
                    "voucher_date": self._format_date(raw.get("voucher_date")),
                    "voucher_time": self._format_time(raw.get("voucher_time")),
                    "customer_name": self._text(raw.get("customer_name_snapshot")),
                    "item_name": self._text(raw.get("item_name_snapshot")),
                    "driver_name": self._text(raw.get("driver_name")),
                    "vehicle_number": self._text(raw.get("vehicle_number")),
                    # Weights show verbatim — never a reformatted value.
                    "weight_before": before_text,
                    "weight_after": after_text,
                    "notes": self._text(raw.get("notes")),
                }
            )

        summary = {
            "voucher_count": len(rows),
            "voucher_count_label": f"{len(rows):,}",
            "total_weight_before": total_before,
            "total_weight_before_label": self._weight_text(total_before),
            "total_weight_after": total_after,
            "total_weight_after_label": self._weight_text(total_after),
        }
        return LoadingVoucherReportResult(
            columns=self.columns,
            rows=rows,
            summary=summary,
            is_empty=not rows,
        )

    # --- print letterhead (print/PDF only) ---------------------------------
    def company_letterhead(self) -> dict[str, Any] | None:
        """The first registered company, for the printable letterhead. Never raises."""
        try:
            return self.repository.fetch_company_letterhead()
        except Exception:  # noqa: BLE001
            return None

    # --- filter options (drop-downs) ---------------------------------------
    def load_customer_options(self) -> list[dict[str, Any]]:
        try:
            return [self._option(r) for r in self.repository.fetch_customer_options()]
        except Exception:  # noqa: BLE001 - a picker must never crash the screen
            return []

    def load_item_options(self) -> list[dict[str, Any]]:
        try:
            return [self._option(r) for r in self.repository.fetch_item_options()]
        except Exception:  # noqa: BLE001
            return []

    def load_vehicle_options(self) -> list[dict[str, Any]]:
        try:
            return [self._option(r) for r in self.repository.fetch_vehicle_options()]
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _option(row: dict[str, Any]) -> dict[str, Any]:
        label = row.get("label")
        return {
            "id": row.get("id"),
            "label": ("" if label is None else str(label)).strip() or "غير محدد",
        }

    # --- weight parsing / formatting ---------------------------------------
    @staticmethod
    def _parse_weight(text: str) -> Decimal:
        """Extract the first numeric value from a free-text weight, or ``0``.

        Arabic-Indic digits are normalised and thousands commas dropped, so
        ``"12,500 كجم"`` and ``"١٢٥٠٠"`` both yield ``12500``. Anything with no
        number contributes zero — a blank / descriptive weight is not an error.
        """
        if not text:
            return _ZERO
        normalised = text.translate(_ARABIC_DIGITS)
        match = _NUMBER_RE.search(normalised)
        if match is None:
            return _ZERO
        try:
            return Decimal(match.group(0).replace(",", ""))
        except InvalidOperation:
            return _ZERO

    @staticmethod
    def _weight_text(value: Decimal) -> str:
        """A weight total without noise: whole numbers show plain (12,500), a
        fractional total keeps its trimmed decimals (12,500.5)."""
        normalised = value.normalize()
        if normalised == normalised.to_integral_value():
            return f"{int(normalised):,}"
        text = format(normalised, "f")
        whole, _, frac = text.partition(".")
        return f"{int(whole):,}.{frac}" if frac else f"{int(whole):,}"

    # --- small formatters ---------------------------------------------------
    @staticmethod
    def _text(value: Any) -> str:
        return "" if value is None else str(value).strip()

    @staticmethod
    def _format_date(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")
        return str(value)[:10]

    @staticmethod
    def _format_time(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, time):
            return value.strftime("%H:%M")
        # A stored/ISO time string ("14:30:00") -> "14:30".
        return str(value)[:5]

    # --- validation ---------------------------------------------------------
    @staticmethod
    def _clean(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _validate_dates(
        date_from: str | None, date_to: str | None
    ) -> tuple[str | None, str | None]:
        start = (date_from or "").strip() or None
        end = (date_to or "").strip() or None
        if start and end and start > end:
            raise LoadingVoucherReportValidationError(
                "نطاق التاريخ غير صحيح: يجب أن يكون تاريخ (من) أقل من أو يساوي تاريخ (إلى)."
            )
        return start, end


__all__ = [
    "LoadingVoucherReportService",
    "LoadingVoucherReportRequest",
    "LoadingVoucherReportResult",
    "LoadingVoucherReportValidationError",
    "ReportColumn",
    "REPORT_COLUMNS",
    "EMPTY_MESSAGE",
]
