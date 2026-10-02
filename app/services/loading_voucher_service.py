"""Business logic for the Loading Voucher module (سند تحميل).

Sits between the (future) UI and :class:`LoadingVoucherRepository`. It owns:

* server-side customer / item snapshots, so the stored voucher never depends on
  values the UI *claims* (the customer name and the item code/name/unit are always
  rebuilt from the database at save time);
* all quantity maths in :class:`decimal.Decimal` (never ``float``);
* validation with Arabic, user-facing messages;
* permission enforcement in the action layer (not only the UI).

Scope: a simple, single-item logistics document — one header row per voucher
(voucher number + date + time + customer + driver + vehicle + item + quantity in
tons + notes). No detail-line table, no company link, no document-status /
approval workflow, no inventory posting. Deletes are hard deletes.

Field rules (v1)
----------------
* **Every business field is optional** (per the user's request): customer, driver
  name, vehicle number, item, quantity and notes may all be left blank. Only the
  auto voucher number and the date/time (defaulted) are always present.
* ``quantity_tons`` is optional; when a value IS entered it must be > 0
  (numeric(18,3)) — zero and negative are still rejected.
* ``driver_name`` and ``vehicle_number`` are optional free text (no drivers /
  vehicles master exists yet); they are trimmed and length-capped, blank -> NULL.
* ``weight_before_loading`` / ``weight_after_loading`` are optional FREE TEXT
  vehicle weighbridge readings; the user's typed value (including any unit, e.g.
  "500k" / "500 كجم") is stored literally. Blank -> NULL, trimmed + length-capped.
* ``voucher_date`` / ``voucher_time`` default to today / now when left blank.
* ``customer_id`` -> customers(customer_id); ``product_id`` -> products(id). Both are
  optional, but when supplied they are validated to exist and snapshotted;
  caller-supplied names are always ignored.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable

from app.models.loading_voucher import (
    MAX_CUSTOMER_NAME_LEN,
    MAX_DRIVER_NAME_LEN,
    MAX_ITEM_NAME_LEN,
    MAX_UNIT_LEN,
    MAX_VEHICLE_NUMBER_LEN,
    MAX_WEIGHT_LEN,
    QTY_QUANT,
)
from app.repositories.loading_voucher_repository import LoadingVoucherRepository

# Permission codes (module "logistics", target "loading_vouchers"). Enforced here
# in addition to the UI. Registration in permission_registry and the sidebar
# «الشحن/النقل» section is deferred to the UI stage (this backend stage adds no
# visible screen).
PERM_MODULE = "logistics"
PERM_TARGET = "loading_vouchers"


def _perm(action: str) -> str:
    return f"{PERM_MODULE}.{PERM_TARGET}.{action}"


class LoadingVoucherServiceError(Exception):
    """Base for voucher service errors; ``message`` is Arabic and safe to show as-is."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class LoadingVoucherValidationError(LoadingVoucherServiceError):
    """A validation / business-rule failure."""


class LoadingVoucherPermissionError(LoadingVoucherServiceError):
    """The current user lacks permission for the attempted action."""


# Arabic-Indic (٠-٩) and Persian (۰-۹) digits -> ASCII, so a value typed with an
# Arabic keyboard parses the same as one typed with a Latin keyboard.
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
# The numeric core of a string: an optional sign, digits and a single dot.
_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+")


def _normalize_number_text(raw: str) -> str:
    """Extract the numeric part of a user-typed value, tolerating units / digits.

    Data-entry users often append a unit ("500 ك", "12.5 طن") or type Arabic
    digits ("٥٠٠"). We normalise Arabic digits + decimal mark, drop thousands
    separators, and pull out the leading number, so those all parse. Returns "" if
    there is no number at all (e.g. only "ك") so the caller can reject it.
    """
    text = raw.strip().translate(_ARABIC_DIGITS)
    text = text.replace("٫", ".").replace("٬", "").replace("،", "").replace(",", "")
    match = _NUMBER_RE.search(text)
    return match.group(0) if match else ""


def _to_decimal(value: Any, field: str) -> Decimal:
    """Parse ``value`` into a finite Decimal or raise a validation error.

    Accepts a raw number, an Arabic-digit number, or a number with a trailing/
    leading unit label ("500 ك"). Rejects ``None``/blank and text with no number.
    """
    if isinstance(value, Decimal):
        parsed = value
    else:
        if value is None:
            raise LoadingVoucherValidationError(f"{field} مطلوب.")
        if str(value).strip() == "":
            raise LoadingVoucherValidationError(f"{field} مطلوب.")
        normalized = _normalize_number_text(str(value))
        if normalized == "":
            raise LoadingVoucherValidationError(
                f"{field}: قيمة رقمية غير صالحة."
            )
        try:
            parsed = Decimal(normalized)
        except InvalidOperation as exc:
            raise LoadingVoucherValidationError(
                f"{field}: قيمة رقمية غير صالحة."
            ) from exc
    if not parsed.is_finite():
        raise LoadingVoucherValidationError(f"{field}: قيمة رقمية غير صالحة.")
    return parsed


def _qty(value: Decimal) -> Decimal:
    return value.quantize(QTY_QUANT, rounding=ROUND_HALF_UP)


class LoadingVoucherService:
    def __init__(
        self,
        repository: LoadingVoucherRepository | None = None,
        permission_check: Callable[[str], bool] | None = None,
    ) -> None:
        self.repository = repository or LoadingVoucherRepository()
        # Permissive by default (unit tests / standalone launch); the screen wires
        # this to SESSION.can so the action layer enforces permissions too.
        self._can = permission_check or (lambda _code: True)

    # -- permissions ---------------------------------------------------------
    def _require(self, action: str) -> None:
        if not self._can(_perm(action)):
            raise LoadingVoucherPermissionError(
                "ليس لديك صلاحية لتنفيذ هذا الإجراء."
            )

    # ======================================================================
    # Master-data pass-throughs + numbering + load/search
    # ======================================================================
    def search_customers(self, keyword: str, limit: int = 100) -> list[dict[str, Any]]:
        """Customers for the customer lookup popup on the voucher screen."""
        return self.repository.search_customers(keyword, limit)

    def get_customer(self, customer_id: Any) -> dict[str, Any] | None:
        return self.repository.get_customer(int(customer_id))

    def search_products(self, keyword: str, limit: int = 100) -> list[dict[str, Any]]:
        """Products for the item lookup popup on the voucher screen."""
        return self.repository.search_products(keyword, limit)

    def get_product(self, product_id: Any) -> dict[str, Any] | None:
        return self.repository.get_product(int(product_id))

    def get_company_letterhead(self) -> dict[str, Any] | None:
        """First registered company's letterhead fields for the printout."""
        return self.repository.fetch_company_letterhead()

    def reserve_voucher_number(self) -> str:
        """Reserve the next global automatic voucher number ("LV-001", ...)."""
        return self.repository.reserve_voucher_number()

    def peek_next_number(self) -> str:
        """Advisory next automatic voucher number (for pre-filling a new form)."""
        return self.repository.peek_next_number()

    def load(self, voucher_id: Any) -> dict[str, Any] | None:
        """Load a full voucher for the screen."""
        return self.repository.load_voucher(int(voucher_id))

    def search_vouchers(
        self,
        keyword: str = "",
        limit: int = 300,
        *,
        customer_id: int | None = None,
        date_from: Any = None,
        date_to: Any = None,
    ) -> list[dict[str, Any]]:
        return self.repository.search_vouchers(
            keyword, limit, customer_id=customer_id,
            date_from=date_from, date_to=date_to,
        )

    # ======================================================================
    # Snapshots (from the database — never trusted from the UI)
    # ======================================================================
    def build_customer_snapshot(self, customer_id: Any) -> dict[str, Any]:
        """Snapshot the customer, or all-``None`` when no customer is chosen.

        The customer is optional; when an id IS supplied it must exist (a picked
        customer that no longer exists is a real error).
        """
        if customer_id in (None, ""):
            return {"customer_id": None, "customer_name_snapshot": None}
        customer = self.repository.get_customer(int(customer_id))
        if customer is None:
            raise LoadingVoucherValidationError("العميل غير موجود.")
        name = (customer.get("customer_name") or "").strip()
        return {
            "customer_id": int(customer["customer_id"]),
            "customer_name_snapshot": (name[:MAX_CUSTOMER_NAME_LEN] or None),
        }

    def build_item_snapshot(self, product_id: Any) -> dict[str, Any]:
        """Snapshot the item, or all-``None`` when no item is chosen.

        The item is optional; when an id IS supplied it must exist.
        """
        if product_id in (None, ""):
            return {
                "product_id": None,
                "item_code_snapshot": None,
                "item_name_snapshot": None,
                "unit_snapshot": "",
            }
        product = self.repository.get_product(int(product_id))
        if product is None:
            raise LoadingVoucherValidationError("الصنف غير موجود.")
        name = (product.get("item_name") or "").strip()
        return {
            "product_id": int(product["id"]),
            "item_code_snapshot": product.get("item_code"),
            "item_name_snapshot": (name[:MAX_ITEM_NAME_LEN] or None),
            "unit_snapshot": str(product.get("unit") or "").strip()[:MAX_UNIT_LEN],
        }

    # ======================================================================
    # Field cleaning / validation
    # ======================================================================
    @staticmethod
    def _clean_date(value: Any) -> date:
        """Blank -> today; a ``date``/``datetime`` -> its date; an ISO string -> parsed."""
        if value in (None, ""):
            return date.today()
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value).strip()[:10])
        except ValueError as exc:
            raise LoadingVoucherValidationError(
                "تاريخ السند غير صالح."
            ) from exc

    @staticmethod
    def _clean_time(value: Any) -> time:
        """Blank -> now (to the second); a ``time``/``datetime`` -> its time; string parsed."""
        if value in (None, ""):
            return datetime.now().time().replace(microsecond=0)
        if isinstance(value, datetime):
            return value.time().replace(microsecond=0)
        if isinstance(value, time):
            return value.replace(microsecond=0)
        text = str(value).strip()
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(text, fmt).time()
            except ValueError:
                continue
        raise LoadingVoucherValidationError("وقت السند غير صالح.")

    def _clean_quantity(self, value: Any) -> Decimal | None:
        """Optional quantity: blank -> ``None``; a supplied value must be > 0."""
        if value in (None, "") or (isinstance(value, str) and value.strip() == ""):
            return None
        qty = _qty(_to_decimal(value, "الكمية بالطن"))
        if qty <= 0:
            raise LoadingVoucherValidationError(
                "الكمية بالطن يجب أن تكون أكبر من صفر."
            )
        return qty

    @staticmethod
    def _clean_optional_text(value: Any, max_len: int) -> str | None:
        """Optional free text: blank -> ``None``; otherwise trimmed + length-capped."""
        text = ("" if value is None else str(value)).strip()
        return (text[:max_len] or None)

    @staticmethod
    def _clean_notes(value: Any) -> str | None:
        text = ("" if value is None else str(value)).strip()
        return text or None

    def _clean_voucher_number(self, value: Any, *, exclude_id: int | None) -> str:
        """Return a validated, unique voucher number.

        Blank -> reserve the next automatic number. A supplied value is validated
        for global uniqueness (the UNIQUE index is the final guard at save time).
        """
        number = ("" if value is None else str(value)).strip()
        if number == "":
            return self.repository.reserve_voucher_number()
        if self.repository.voucher_number_exists(number, exclude_id=exclude_id):
            raise LoadingVoucherValidationError("رقم السند مستخدم مسبقًا.")
        return number

    def _prepare(
        self, form: dict[str, Any], *, exclude_id: int | None
    ) -> dict[str, Any]:
        """Validate + rebuild a full header row from raw ``form`` input.

        The customer and item snapshots and the quantity are all derived
        server-side; caller-supplied snapshot names are ignored.
        """
        customer = self.build_customer_snapshot(form.get("customer_id"))
        item = self.build_item_snapshot(form.get("product_id"))
        header = {
            "voucher_number": self._clean_voucher_number(
                form.get("voucher_number"), exclude_id=exclude_id
            ),
            "voucher_date": self._clean_date(form.get("voucher_date")),
            "voucher_time": self._clean_time(form.get("voucher_time")),
            **customer,
            "driver_name": self._clean_optional_text(
                form.get("driver_name"), MAX_DRIVER_NAME_LEN
            ),
            "vehicle_number": self._clean_optional_text(
                form.get("vehicle_number"), MAX_VEHICLE_NUMBER_LEN
            ),
            "weight_before_loading": self._clean_optional_text(
                form.get("weight_before_loading"), MAX_WEIGHT_LEN
            ),
            "weight_after_loading": self._clean_optional_text(
                form.get("weight_after_loading"), MAX_WEIGHT_LEN
            ),
            **item,
            "quantity_tons": self._clean_quantity(form.get("quantity_tons")),
            "notes": self._clean_notes(form.get("notes")),
        }
        return header

    # ======================================================================
    # Create / update / delete
    # ======================================================================
    def create_voucher(
        self, form: dict[str, Any], *, user_id: int | None = None
    ) -> dict[str, Any]:
        """Validate + persist a new voucher in one transaction."""
        self._require("save")
        header = self._prepare(form, exclude_id=None)
        header["created_by"] = user_id
        header["updated_by"] = user_id
        return self.repository.insert_voucher(header)

    def update_voucher(
        self, voucher_id: int, form: dict[str, Any], *, user_id: int | None = None
    ) -> dict[str, Any]:
        """Validate + update an existing voucher."""
        self._require("edit")
        existing = self.repository.load_voucher(int(voucher_id))
        if existing is None:
            raise LoadingVoucherValidationError("السند غير موجود.")

        header = self._prepare(form, exclude_id=int(voucher_id))
        header_changes = {
            "voucher_number": header["voucher_number"],
            "voucher_date": header["voucher_date"],
            "voucher_time": header["voucher_time"],
            "customer_id": header["customer_id"],
            "customer_name_snapshot": header["customer_name_snapshot"],
            "driver_name": header["driver_name"],
            "vehicle_number": header["vehicle_number"],
            "weight_before_loading": header["weight_before_loading"],
            "weight_after_loading": header["weight_after_loading"],
            "product_id": header["product_id"],
            "item_code_snapshot": header["item_code_snapshot"],
            "item_name_snapshot": header["item_name_snapshot"],
            "unit_snapshot": header["unit_snapshot"],
            "quantity_tons": header["quantity_tons"],
            "notes": header["notes"],
            "updated_by": user_id,
        }
        updated = self.repository.update_voucher(int(voucher_id), header_changes)
        if updated is None:
            raise LoadingVoucherValidationError("السند غير موجود.")
        return updated

    def delete_voucher(self, voucher_id: int, *, user_id: int | None = None) -> bool:
        """Hard-delete a voucher. Raises if it does not exist."""
        self._require("delete")
        existing = self.repository.load_voucher(int(voucher_id))
        if existing is None:
            raise LoadingVoucherValidationError("السند غير موجود.")
        return self.repository.delete_voucher(int(voucher_id))


__all__ = [
    "LoadingVoucherService",
    "LoadingVoucherServiceError",
    "LoadingVoucherValidationError",
    "LoadingVoucherPermissionError",
    "Decimal",
]
