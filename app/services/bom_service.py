"""Business logic for the Bill of Materials module (قائمة المواد).

Sits between the (future) UI and :class:`BomRepository`. It owns:

* server-side finished-product / component snapshots, so the stored BOM never
  depends on values the UI *claims*;
* all quantity / price / money maths in :class:`decimal.Decimal` (never
  ``float``), recomputed here and never trusted from the caller;
* validation with Arabic, user-facing messages (finished-product self-reference,
  duplicate components, quantity > 0, price >= 0, existence of every product);
* permission enforcement in the action layer (not only the UI).

Scope: material cost only — a BOM header (finished product + automatic number +
date + total material cost) and its component lines (item + quantity + price +
line total). No labour, machine, routing, production order, overhead or
multi-level BOM.

Line maths
----------
For each component line, from the component's ``quantity`` (الكمية) and ``price``
(السعر):

* ``line_total``          = quantity × price                    (إجمالي السطر)

And the single header total:

* ``total_material_cost`` = Σ line_total                        (إجمالي تكلفة الخامات)

Price behaviour
---------------
A component's initial price comes from ``products.price`` (the only price column
on the item master — there is no separate cost column). A caller may override it
(the UI will make it editable); the value actually used is stored as a snapshot
on the line so an old BOM never changes when the item master is later edited.

Item type (نوع الصنف)
--------------------
``products.item_type`` (مادة خام / منتج تام) is intentionally **not** enforced
here: Prompt-1 found it can be NULL on legacy rows and is only constrained by the
UI dropdown, so a hard rule would reject valid existing data. Strict
finished=منتج تام / component=مادة خام filtering is left to the UI layer.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable

from app.models.bom import (
    MAX_ITEM_NAME_LEN,
    MONEY_QUANT,
    QTY_QUANT,
)
from app.repositories.bom_repository import BomRepository

# Permission codes (module "manufacturing", target "boms"). Enforced here in
# addition to the UI. Registration in permission_registry is deferred to the UI
# stage (this backend stage adds no visible screen).
PERM_MODULE = "manufacturing"
PERM_TARGET = "boms"


def _perm(action: str) -> str:
    return f"{PERM_MODULE}.{PERM_TARGET}.{action}"


class BomServiceError(Exception):
    """Base for BOM service errors; ``message`` is Arabic and safe to show as-is."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BomServiceValidationError(BomServiceError):
    """A validation / business-rule failure."""


class BomServicePermissionError(BomServiceError):
    """The current user lacks permission for the attempted action."""


def _to_decimal(value: Any, field: str) -> Decimal:
    """Parse ``value`` into a finite Decimal or raise a validation error.

    Rejects ``None``/blank, thousands separators, and nan/inf.
    """
    if isinstance(value, Decimal):
        parsed = value
    else:
        if value is None:
            raise BomServiceValidationError(f"{field} مطلوب.")
        text = str(value).strip().replace(",", "")
        if text == "":
            raise BomServiceValidationError(f"{field} مطلوب.")
        try:
            parsed = Decimal(text)
        except InvalidOperation as exc:
            raise BomServiceValidationError(f"{field}: قيمة رقمية غير صالحة.") from exc
    if not parsed.is_finite():
        raise BomServiceValidationError(f"{field}: قيمة رقمية غير صالحة.")
    return parsed


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _qty(value: Decimal) -> Decimal:
    return value.quantize(QTY_QUANT, rounding=ROUND_HALF_UP)


class BomService:
    def __init__(
        self,
        repository: BomRepository | None = None,
        permission_check: Callable[[str], bool] | None = None,
    ) -> None:
        self.repository = repository or BomRepository()
        # Permissive by default (unit tests / standalone launch); the screen
        # wires this to SESSION.can so the action layer enforces permissions too.
        self._can = permission_check or (lambda _code: True)

    # -- permissions ---------------------------------------------------------
    def _require(self, action: str) -> None:
        if not self._can(_perm(action)):
            raise BomServicePermissionError("ليس لديك صلاحية لتنفيذ هذا الإجراء.")

    # ======================================================================
    # Master-data pass-throughs (products) + numbering
    # ======================================================================
    def search_products(self, keyword: str, limit: int = 100) -> list[dict[str, Any]]:
        """Products for the أصناف lookup popup on the BOM screen."""
        return self.repository.search_products(keyword, limit)

    def get_product(self, product_id: Any) -> dict[str, Any] | None:
        return self.repository.get_product(int(product_id))

    def reserve_bom_number(self) -> str:
        """Reserve the next global automatic BOM number ("BOM-0001", ...)."""
        return self.repository.reserve_bom_number()

    def peek_next_number(self) -> str:
        """Advisory next automatic BOM number (for pre-filling a new form)."""
        return self.repository.peek_next_number()

    def load(self, bom_id: Any) -> dict[str, Any] | None:
        """Load a full BOM (``{"header", "lines"}``) for the screen."""
        return self.repository.load_bom(int(bom_id))

    def search_boms(
        self,
        keyword: str = "",
        limit: int = 300,
        *,
        product_id: int | None = None,
        date_from: Any = None,
        date_to: Any = None,
    ) -> list[dict[str, Any]]:
        return self.repository.search_boms(
            keyword, limit, product_id=product_id, date_from=date_from, date_to=date_to
        )

    # ======================================================================
    # Finished-product snapshot (from the database — never trusted from the UI)
    # ======================================================================
    def build_product_snapshot(self, product_id: Any) -> dict[str, Any]:
        if product_id in (None, ""):
            raise BomServiceValidationError("يجب اختيار المنتج التام.")
        product = self.repository.get_product(int(product_id))
        if product is None:
            raise BomServiceValidationError("المنتج التام غير موجود.")
        name = (product.get("item_name") or "").strip()
        if name == "":
            raise BomServiceValidationError("المنتج التام المحدد بدون اسم.")
        return {
            "product_id": int(product["id"]),
            "product_name_snapshot": name[:MAX_ITEM_NAME_LEN],
        }

    # ======================================================================
    # Line + total calculations (Decimal only)
    # ======================================================================
    def compute_line_total(self, quantity: Decimal, price: Decimal) -> Decimal:
        """``line_total = quantity × price`` as money (2 dp)."""
        return _money(quantity * price)

    def _build_line(
        self, raw: dict[str, Any], index: int, *, finished_product_id: int
    ) -> dict[str, Any]:
        label = f"السطر {index}"

        component_id = raw.get("component_product_id")
        if component_id in (None, ""):
            raise BomServiceValidationError(f"{label}: يجب اختيار الصنف المكوّن.")
        try:
            component_id = int(component_id)
        except (TypeError, ValueError) as exc:
            raise BomServiceValidationError(
                f"{label}: معرّف الصنف المكوّن غير صالح."
            ) from exc

        # Rule: the finished product cannot be one of its own components.
        if component_id == int(finished_product_id):
            raise BomServiceValidationError(
                f"{label}: لا يمكن إضافة المنتج التام نفسه كأحد مكوّناته."
            )

        product = self.repository.get_product(component_id)
        if product is None:
            raise BomServiceValidationError(f"{label}: الصنف المكوّن غير موجود.")

        item_name = (product.get("item_name") or "").strip()
        if item_name == "":
            raise BomServiceValidationError(f"{label}: الصنف المكوّن بدون اسم.")

        quantity = _qty(_to_decimal(raw.get("quantity"), f"{label} - الكمية"))
        if quantity <= 0:
            raise BomServiceValidationError(
                f"{label}: الكمية يجب أن تكون أكبر من صفر."
            )

        # Price: caller-supplied value wins (the UI makes it editable); otherwise
        # default to the item master's price. The used value is stored as a snapshot.
        raw_price = raw.get("price")
        if raw_price in (None, ""):
            raw_price = product.get("price")
        price = _money(_to_decimal(raw_price, f"{label} - السعر"))
        if price < 0:
            raise BomServiceValidationError(f"{label}: السعر لا يمكن أن يكون سالبًا.")

        return {
            "component_product_id": component_id,
            "item_code_snapshot": product.get("item_code"),
            "item_name_snapshot": item_name[:MAX_ITEM_NAME_LEN],
            "unit_snapshot": str(product.get("unit") or "").strip()[:50],
            "quantity": quantity,
            "price": price,
            "line_total": self.compute_line_total(quantity, price),
        }

    def build_lines(
        self, raw_lines: list[dict[str, Any]], *, finished_product_id: int
    ) -> list[dict[str, Any]]:
        if not raw_lines:
            raise BomServiceValidationError(
                "يجب إضافة صنف مكوّن واحد على الأقل إلى قائمة المواد."
            )
        lines: list[dict[str, Any]] = []
        seen: set[int] = set()
        for i, raw in enumerate(raw_lines, start=1):
            line = self._build_line(raw, i, finished_product_id=finished_product_id)
            component_id = line["component_product_id"]
            # Rule: a component must not appear twice in the same BOM.
            if component_id in seen:
                raise BomServiceValidationError(
                    f"السطر {i}: الصنف المكوّن مكرّر في نفس قائمة المواد."
                )
            seen.add(component_id)
            lines.append(line)
        return lines

    def compute_total_material_cost(self, lines: list[dict[str, Any]]) -> Decimal:
        total = sum((line["line_total"] for line in lines), start=Decimal("0"))
        return _money(total)

    # ======================================================================
    # Header validation / assembly
    # ======================================================================
    @staticmethod
    def _clean_bom_date(value: Any) -> Any:
        if value in (None, ""):
            raise BomServiceValidationError("تاريخ قائمة المواد مطلوب.")
        return value

    def _clean_bom_number(self, value: Any, *, exclude_id: int | None) -> str:
        """Return a validated, unique BOM number.

        Blank -> reserve the next automatic number. A supplied value is validated
        for global uniqueness (the UNIQUE index is the final guard at save time).
        """
        number = ("" if value is None else str(value)).strip()
        if number == "":
            return self.repository.reserve_bom_number()
        if self.repository.bom_number_exists(number, exclude_id=exclude_id):
            raise BomServiceValidationError("رقم قائمة المواد مستخدم مسبقًا.")
        return number

    def _prepare(
        self, form: dict[str, Any], *, exclude_id: int | None
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Validate + rebuild a header + lines from raw ``form`` input.

        The product snapshot and the total are derived server-side; any total the
        caller supplies is ignored and recomputed.
        """
        bom_date = self._clean_bom_date(form.get("bom_date"))
        product = self.build_product_snapshot(form.get("product_id"))
        lines = self.build_lines(
            form.get("lines") or [], finished_product_id=product["product_id"]
        )
        total = self.compute_total_material_cost(lines)
        bom_number = self._clean_bom_number(form.get("bom_number"), exclude_id=exclude_id)

        header = {
            "bom_number": bom_number,
            "bom_date": bom_date,
            **product,
            "total_material_cost": total,
        }
        return header, lines

    # ======================================================================
    # Create / update / delete
    # ======================================================================
    def create_bom(
        self, form: dict[str, Any], *, user_id: int | None = None
    ) -> dict[str, Any]:
        """Validate + persist a new BOM (header + lines) in one transaction."""
        self._require("save")
        header, lines = self._prepare(form, exclude_id=None)
        header["created_by"] = user_id
        header["updated_by"] = user_id
        return self.repository.insert_bom(header, lines)

    def update_bom(
        self, bom_id: int, form: dict[str, Any], *, user_id: int | None = None
    ) -> dict[str, Any]:
        """Validate + update an existing BOM (header + replace lines)."""
        self._require("edit")
        existing = self.repository.load_bom(int(bom_id))
        if existing is None:
            raise BomServiceValidationError("قائمة المواد غير موجودة.")

        header, lines = self._prepare(form, exclude_id=int(bom_id))
        header_changes = {
            "bom_number": header["bom_number"],
            "bom_date": header["bom_date"],
            "product_id": header["product_id"],
            "product_name_snapshot": header["product_name_snapshot"],
            "total_material_cost": header["total_material_cost"],
            "updated_by": user_id,
        }
        updated = self.repository.update_bom(int(bom_id), header_changes, lines)
        if updated is None:
            raise BomServiceValidationError("قائمة المواد غير موجودة.")
        return updated

    def delete_bom(self, bom_id: int, *, user_id: int | None = None) -> bool:
        """Delete a BOM (its lines cascade). Raises if it does not exist."""
        self._require("delete")
        existing = self.repository.load_bom(int(bom_id))
        if existing is None:
            raise BomServiceValidationError("قائمة المواد غير موجودة.")
        return self.repository.delete_bom(int(bom_id))


__all__ = [
    "BomService",
    "BomServiceError",
    "BomServiceValidationError",
    "BomServicePermissionError",
    "Decimal",
]
