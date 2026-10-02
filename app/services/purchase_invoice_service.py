"""Business logic for the purchase-invoice screen.

Sits between the UI (``PurchaseInvoicePage``) and ``PurchaseInvoiceRepository``.
It owns:

* server-side supplier snapshot building, so the stored invoice never depends on
  values the UI *claims*;
* all count / weight / money maths in :class:`decimal.Decimal` (never ``float``),
  recomputed here and never trusted from the UI;
* validation with Arabic, user-facing messages;
* the draft-only edit rule and the delete rules;
* optimistic-concurrency handling and audit metadata;
* permission enforcement in the action layer (not only the UI).

Deliberately **not** done (unlike the sales invoice): no VAT of any kind, no
ZATCA / Phase-2 data, no print/QR generation. A purchase invoice is a plain
count/weight document.

Line maths
----------
For each line, from the typed ``item_count`` (العدد), ``unit_weight`` (الوزن)
and ``unit_price`` (السعر):

* ``total_weight``        = item_count × unit_weight            (إجمالي الوزن)
* ``count_price_total``   = item_count × unit_price             (إجمالي سعر العدد)
* ``weight_price_total``  = total_weight × unit_price           (إجمالي سعر الوزن)

And the two header totals:

* ``total_count_price``   = Σ count_price_total   (إجمالي الفاتورة)
* ``total_weight_price``  = Σ weight_price_total  (إجمالي الوزن)
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable

from app.models.purchase_invoice import (
    MAX_ITEM_NAME_LEN,
    MONEY_QUANT,
    PAYMENT_CASH,
    PAYMENT_CREDIT,
    QTY_QUANT,
    STATUS_APPROVED,
    STATUS_DRAFT,
)
from app.repositories.purchase_invoice_repository import (
    PurchaseInvoiceRepository,
    StalePurchaseInvoiceError,
)

# Permission codes (see permission_registry: module "purchases", target
# "purchase_invoices"). Enforced here in addition to the UI.
PERM_MODULE = "purchases"
PERM_TARGET = "purchase_invoices"


def _perm(action: str) -> str:
    return f"{PERM_MODULE}.{PERM_TARGET}.{action}"


class PurchaseInvoiceError(Exception):
    """Base for service errors; ``message`` is Arabic and safe to show as-is."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PurchaseInvoiceValidationError(PurchaseInvoiceError):
    """A validation / business-rule failure."""


class PurchaseInvoicePermissionError(PurchaseInvoiceError):
    """The current user lacks permission for the attempted action."""


class PurchaseInvoiceConcurrencyError(PurchaseInvoiceError):
    """The draft was changed by someone else (stale ``row_version``)."""


def _to_decimal(value: Any, field: str) -> Decimal:
    """Parse ``value`` into a finite Decimal or raise a validation error.

    Rejects ``None``/blank, thousands separators, and nan/inf.
    """
    if isinstance(value, Decimal):
        parsed = value
    else:
        if value is None:
            raise PurchaseInvoiceValidationError(f"{field} مطلوب.")
        text = str(value).strip().replace(",", "")
        if text == "":
            raise PurchaseInvoiceValidationError(f"{field} مطلوب.")
        try:
            parsed = Decimal(text)
        except InvalidOperation as exc:
            raise PurchaseInvoiceValidationError(f"{field}: قيمة رقمية غير صالحة.") from exc
    if not parsed.is_finite():
        raise PurchaseInvoiceValidationError(f"{field}: قيمة رقمية غير صالحة.")
    return parsed


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _qty(value: Decimal) -> Decimal:
    return value.quantize(QTY_QUANT, rounding=ROUND_HALF_UP)


class PurchaseInvoiceService:
    def __init__(
        self,
        repository: PurchaseInvoiceRepository | None = None,
        permission_check: Callable[[str], bool] | None = None,
    ) -> None:
        self.repository = repository or PurchaseInvoiceRepository()
        # Permissive by default (unit tests / standalone launch); the screen
        # wires this to SESSION.can so the action layer enforces permissions too.
        self._can = permission_check or (lambda _code: True)

    # -- permissions ---------------------------------------------------------
    def _require(self, action: str) -> None:
        if not self._can(_perm(action)):
            raise PurchaseInvoicePermissionError(
                "ليس لديك صلاحية لتنفيذ هذا الإجراء."
            )

    # ======================================================================
    # Master data pass-throughs (suppliers)
    # ======================================================================
    def list_suppliers(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.repository.list_suppliers(limit)

    def search_suppliers(self, keyword: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.repository.search_suppliers(keyword, limit)

    def get_supplier(self, supplier_id: Any) -> dict[str, Any] | None:
        return self.repository.get_supplier(int(supplier_id))

    def search_products(self, keyword: str, limit: int = 100) -> list[dict[str, Any]]:
        """Products for the أصناف lookup popup on the purchase screen."""
        return self.repository.search_products(keyword, limit)

    def reserve_invoice_number(self) -> str:
        """Reserve the next global automatic purchase-invoice number ("Pur-...")."""
        return self.repository.reserve_invoice_number()

    def load(self, invoice_id: Any) -> dict[str, Any] | None:
        """Load a full invoice (``{"header", "lines"}``) for the screen."""
        return self.repository.load_invoice(int(invoice_id))

    def search_invoices(
        self,
        keyword: str = "",
        status: str | None = None,
        limit: int = 300,
        *,
        supplier_id: int | None = None,
        date_from: Any = None,
        date_to: Any = None,
    ) -> list[dict[str, Any]]:
        return self.repository.search_invoices(
            keyword,
            status,
            limit,
            supplier_id=supplier_id,
            date_from=date_from,
            date_to=date_to,
        )

    # ======================================================================
    # Supplier snapshot (rebuilt from the database — never trusted from the UI)
    # ======================================================================
    def build_supplier_snapshot(self, supplier_id: Any) -> dict[str, Any]:
        if supplier_id in (None, ""):
            raise PurchaseInvoiceValidationError("يجب اختيار المورد.")
        supplier = self.repository.get_supplier(int(supplier_id))
        if supplier is None:
            raise PurchaseInvoiceValidationError("المورد غير موجود.")
        name = (supplier.get("supplier_name") or "").strip()
        if name == "":
            raise PurchaseInvoiceValidationError("المورد المحدد بدون اسم.")
        return {
            "supplier_id": int(supplier["supplier_id"]),
            "supplier_name_snapshot": name,
        }

    # ======================================================================
    # Line + total calculations (Decimal only)
    # ======================================================================
    def compute_line_amounts(
        self, item_count: Decimal, unit_weight: Decimal, unit_price: Decimal
    ) -> dict[str, Decimal]:
        """Derive the three computed line columns from the typed inputs."""
        total_weight = _qty(item_count * unit_weight)
        count_price_total = _money(item_count * unit_price)
        weight_price_total = _money(total_weight * unit_price)
        return {
            "total_weight": total_weight,
            "count_price_total": count_price_total,
            "weight_price_total": weight_price_total,
        }

    @staticmethod
    def _clean_item_name(raw: dict[str, Any], label: str) -> str:
        """Validate the free-text item name (the only thing that identifies a line)."""
        name = str(raw.get("item_name") or "").strip()
        if not name:
            raise PurchaseInvoiceValidationError(f"{label}: أدخل اسم الصنف.")
        if len(name) > MAX_ITEM_NAME_LEN:
            raise PurchaseInvoiceValidationError(
                f"{label}: اسم الصنف يجب ألا يزيد عن {MAX_ITEM_NAME_LEN} حرفًا."
            )
        return name

    @staticmethod
    def _clean_item_code(raw: dict[str, Any]) -> int | None:
        """Normalise the optional line item code (كود الصنف) to a positive int or None.

        A free-typed line need not carry a product code, so a blank / missing /
        non-numeric value is stored as NULL rather than rejected.
        """
        value = raw.get("item_code")
        if value in (None, ""):
            return None
        try:
            code = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return code if code > 0 else None

    @staticmethod
    def _clean_unit(raw: dict[str, Any]) -> str:
        """Normalise the optional line unit (الوحدة); blank when unset, capped at 50."""
        return str(raw.get("unit") or "").strip()[:50]

    def _build_line(self, raw: dict[str, Any], index: int) -> dict[str, Any]:
        label = f"السطر {index}"
        name = self._clean_item_name(raw, label)
        item_code = self._clean_item_code(raw)
        unit = self._clean_unit(raw)

        item_count = _qty(_to_decimal(raw.get("item_count"), f"{label} - الكمية"))
        if item_count <= 0:
            raise PurchaseInvoiceValidationError(
                f"{label}: الكمية يجب أن تكون أكبر من صفر."
            )

        # الوزن removed from the purchase screen; lines default to zero weight. The
        # weight columns remain in the database (and reports) for compatibility.
        raw_weight = raw.get("unit_weight")
        unit_weight = _qty(_to_decimal(raw_weight, f"{label} - الوزن")) if raw_weight not in (None, "") else _qty(Decimal("0"))
        if unit_weight < 0:
            raise PurchaseInvoiceValidationError(
                f"{label}: الوزن لا يمكن أن يكون سالبًا."
            )

        unit_price = _qty(_to_decimal(raw.get("unit_price"), f"{label} - السعر"))
        if unit_price < 0:
            raise PurchaseInvoiceValidationError(
                f"{label}: السعر لا يمكن أن يكون سالبًا."
            )

        amounts = self.compute_line_amounts(item_count, unit_weight, unit_price)
        return {
            "item_code_snapshot": item_code,
            "item_name_snapshot": name,
            "unit_snapshot": unit,
            "item_count": item_count,
            "unit_weight": unit_weight,
            "unit_price": unit_price,
            **amounts,
        }

    def build_lines(self, raw_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not raw_lines:
            raise PurchaseInvoiceValidationError(
                "يجب إضافة صنف واحد على الأقل إلى الفاتورة."
            )
        return [self._build_line(raw, i) for i, raw in enumerate(raw_lines, start=1)]

    def compute_totals(self, lines: list[dict[str, Any]]) -> dict[str, Decimal]:
        total_count_price = sum(
            (line["count_price_total"] for line in lines), start=Decimal("0")
        )
        total_weight_price = sum(
            (line["weight_price_total"] for line in lines), start=Decimal("0")
        )
        return {
            "total_count_price": _money(total_count_price),
            "total_weight_price": _money(total_weight_price),
        }

    # ======================================================================
    # Header validation
    # ======================================================================
    @staticmethod
    def _clean_invoice_number(value: Any) -> str:
        number = ("" if value is None else str(value)).strip()
        if number == "":
            raise PurchaseInvoiceValidationError("رقم الفاتورة مطلوب.")
        return number

    @staticmethod
    def _clean_payment_type(value: Any) -> str:
        if value not in (PAYMENT_CASH, PAYMENT_CREDIT):
            raise PurchaseInvoiceValidationError("نوع الدفع غير صالح.")
        return value

    def _prepare_header(
        self, form: dict[str, Any], *, exclude_id: int | None
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Decimal]]:
        """Validate + rebuild a header from raw UI ``form`` input.

        Returns ``(header_persistable, lines, totals)``. The supplier snapshot and
        totals are derived server-side; nothing numeric is taken from the UI
        verbatim.
        """
        invoice_number = self._clean_invoice_number(form.get("invoice_number"))
        payment_type = self._clean_payment_type(form.get("payment_type"))

        issue_datetime = form.get("issue_datetime")
        if issue_datetime in (None, ""):
            raise PurchaseInvoiceValidationError("تاريخ ووقت الإصدار مطلوب.")

        supplier = self.build_supplier_snapshot(form.get("supplier_id"))

        if self.repository.invoice_number_exists(invoice_number, exclude_id=exclude_id):
            raise PurchaseInvoiceValidationError("رقم الفاتورة مستخدم مسبقًا.")

        lines = self.build_lines(form.get("lines") or [])
        totals = self.compute_totals(lines)

        notes = form.get("notes")
        notes = notes.strip() if isinstance(notes, str) else notes

        header = {
            "invoice_number": invoice_number,
            "issue_datetime": issue_datetime,
            **supplier,
            "payment_type": payment_type,
            "notes": notes or None,
            **{key: value for key, value in totals.items()},
            "document_status": STATUS_DRAFT,
        }
        return header, lines, totals

    # ======================================================================
    # Create / update / delete
    # ======================================================================
    def create_draft(
        self, form: dict[str, Any], *, user_id: int | None = None
    ) -> dict[str, Any]:
        """Validate + persist a new draft (header + lines) in one transaction."""
        self._require("save")
        header, lines, _totals = self._prepare_header(form, exclude_id=None)
        header["created_by"] = user_id
        header["updated_by"] = user_id
        audit = {
            "action": "save",
            "old_status": None,
            "new_status": STATUS_DRAFT,
            "performed_by": user_id,
            "invoice_number_snapshot": header["invoice_number"],
            "supplier_id_snapshot": header["supplier_id"],
            "details": {"lines": len(lines)},
        }
        return self.repository.insert_invoice(header, lines, audit)

    def update_draft(
        self,
        invoice_id: int,
        expected_row_version: int,
        form: dict[str, Any],
        *,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Validate + update an existing draft (header + replace lines)."""
        self._require("edit")
        existing = self.repository.load_invoice(invoice_id)
        if existing is None:
            raise PurchaseInvoiceValidationError("الفاتورة غير موجودة.")
        if existing["header"]["document_status"] != STATUS_DRAFT:
            raise PurchaseInvoiceValidationError("لا يمكن تعديل فاتورة معتمدة.")

        header, lines, _totals = self._prepare_header(form, exclude_id=int(invoice_id))
        # Only header columns that may legitimately change on a draft update.
        header_changes = {
            key: header[key]
            for key in (
                "invoice_number",
                "issue_datetime",
                "supplier_id",
                "supplier_name_snapshot",
                "payment_type",
                "notes",
                "total_count_price",
                "total_weight_price",
            )
        }
        header_changes["updated_by"] = user_id
        audit = {
            "action": "update",
            "old_status": STATUS_DRAFT,
            "new_status": STATUS_DRAFT,
            "performed_by": user_id,
            "invoice_number_snapshot": header["invoice_number"],
            "supplier_id_snapshot": header["supplier_id"],
            "details": {"lines": len(lines)},
        }
        try:
            return self.repository.update_invoice(
                int(invoice_id), int(expected_row_version), header_changes, lines, audit
            )
        except StalePurchaseInvoiceError as exc:
            raise PurchaseInvoiceConcurrencyError(str(exc)) from exc

    def can_delete(self, invoice: dict[str, Any]) -> tuple[bool, str]:
        """Return ``(deletable, reason)`` for a loaded invoice dict.

        Both drafts and approved invoices are deletable — nothing blocks a
        purchase invoice from being removed.
        """
        return True, ""

    def delete_draft(self, invoice_id: int, *, user_id: int | None = None) -> bool:
        """Delete a single eligible draft. Raises on approved."""
        self._require("delete")
        existing = self.repository.load_invoice(invoice_id)
        if existing is None:
            raise PurchaseInvoiceValidationError("الفاتورة غير موجودة.")
        deletable, reason = self.can_delete(existing)
        if not deletable:
            raise PurchaseInvoiceValidationError(reason)
        return self.repository.delete_draft(int(invoice_id), performed_by=user_id)

    def delete_all_drafts(
        self, *, supplier_id: int | None = None, user_id: int | None = None
    ) -> dict[str, int]:
        """Delete every eligible draft; returns counts of deleted vs protected."""
        self._require("delete")
        return self.repository.delete_all_eligible_drafts(
            supplier_id=supplier_id, performed_by=user_id
        )

    # ======================================================================
    # Approval — LOCAL only
    # ======================================================================
    def is_approval_available(self) -> bool:
        """Local approval is available: a draft can be marked ``approved``."""
        return True

    def approve(
        self,
        invoice_id: int,
        expected_row_version: int,
        *,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Approve a draft locally (draft → approved)."""
        self._require("approve")
        existing = self.repository.load_invoice(invoice_id)
        if existing is None:
            raise PurchaseInvoiceValidationError("الفاتورة غير موجودة.")
        header = existing["header"]
        if header["document_status"] != STATUS_DRAFT:
            raise PurchaseInvoiceValidationError("الفاتورة معتمدة بالفعل.")
        audit = {
            "action": "approve",
            "old_status": STATUS_DRAFT,
            "new_status": STATUS_APPROVED,
            "performed_by": user_id,
            "invoice_number_snapshot": header["invoice_number"],
            "supplier_id_snapshot": header["supplier_id"],
            "details": {},
        }
        try:
            return self.repository.approve_invoice(
                int(invoice_id),
                int(expected_row_version),
                approved_by=user_id,
                audit=audit,
            )
        except StalePurchaseInvoiceError as exc:
            raise PurchaseInvoiceConcurrencyError(str(exc)) from exc


__all__ = [
    "PurchaseInvoiceService",
    "PurchaseInvoiceError",
    "PurchaseInvoiceValidationError",
    "PurchaseInvoicePermissionError",
    "PurchaseInvoiceConcurrencyError",
    "Decimal",
]
