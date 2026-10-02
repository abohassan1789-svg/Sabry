"""Business logic for the Production Order module (أمر الإنتاج).

Sits between the (future) UI and :class:`ProductionOrderRepository`. It owns:

* server-side finished-product / BOM snapshots, so the stored order never depends
  on values the UI *claims*;
* all quantity maths in :class:`decimal.Decimal` (never ``float``), recomputed here
  and never trusted from the caller (expected quantity and deviation supplied by a
  caller are ignored and recomputed);
* BOM resolution against the existing BOM module (no BOM logic is duplicated):
  no BOM -> reject; one BOM -> use it; many BOMs -> require an explicit ``bom_id``;
* validation with Arabic, user-facing messages;
* permission enforcement in the action layer (not only the UI).

Scope: a simple manufacturing document — a header (finished product + BOM used +
date + quantity to produce) and its material lines (component + expected issue
quantity + editable actual issue quantity + deviation). **No** warehouse, no real
inventory posting, no labour / machine / routing / production-stage / overhead /
approval workflow, and no cost totals in this version.

Core maths
----------
For each component line, from the BOM's per-unit quantity and the order's
production quantity:

* ``expected_quantity`` = production_quantity × bom_quantity_per_unit  (الكمية المتوقعة)
* ``actual_quantity``   = editable; defaults to ``expected_quantity``   (الكمية الفعلية)
* ``deviation``         = actual_quantity − expected_quantity           (الانحراف)

``deviation`` is a STORED generated column in the database; the service computes it
only for returned in-memory payloads and never trusts a caller-supplied value.

Two distinct behaviours (see the UI gate for «صرف المواد الخام»)
---------------------------------------------------------------
* :meth:`load_materials` — explicit (re)load from the selected BOM: rebuilds the
  lines, refreshes every snapshot from the BOM, recomputes ``expected_quantity``
  and **resets** ``actual_quantity`` to it.
* :meth:`recalculate_for_quantity` — a plain production-quantity change on already
  loaded lines: recomputes ``expected_quantity`` from each line's stored
  ``bom_quantity_per_unit`` and **preserves** the user's ``actual_quantity``.

Item type (نوع الصنف)
--------------------
``products.item_type`` (مادة خام / منتج تام) is intentionally **not** enforced with
a hard rule — legacy rows can be NULL (same stance as the BOM module). Any
finished/component typing is left to the UI.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable

from app.models.production_order import (
    MAX_ITEM_NAME_LEN,
    MONEY_QUANT,
    QTY_QUANT,
)
from app.repositories.production_order_repository import ProductionOrderRepository

# Permission codes (module "manufacturing", target "production_orders"). Enforced
# here in addition to the UI. Registration in permission_registry is deferred to
# the UI stage (this backend stage adds no visible screen).
PERM_MODULE = "manufacturing"
PERM_TARGET = "production_orders"


def _perm(action: str) -> str:
    return f"{PERM_MODULE}.{PERM_TARGET}.{action}"


class ProductionOrderServiceError(Exception):
    """Base for order service errors; ``message`` is Arabic and safe to show as-is."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ProductionOrderValidationError(ProductionOrderServiceError):
    """A validation / business-rule failure."""


class ProductionOrderPermissionError(ProductionOrderServiceError):
    """The current user lacks permission for the attempted action."""


def _to_decimal(value: Any, field: str) -> Decimal:
    """Parse ``value`` into a finite Decimal or raise a validation error.

    Rejects ``None``/blank, thousands separators, and nan/inf.
    """
    if isinstance(value, Decimal):
        parsed = value
    else:
        if value is None:
            raise ProductionOrderValidationError(f"{field} مطلوب.")
        text = str(value).strip().replace(",", "")
        if text == "":
            raise ProductionOrderValidationError(f"{field} مطلوب.")
        try:
            parsed = Decimal(text)
        except InvalidOperation as exc:
            raise ProductionOrderValidationError(
                f"{field}: قيمة رقمية غير صالحة."
            ) from exc
    if not parsed.is_finite():
        raise ProductionOrderValidationError(f"{field}: قيمة رقمية غير صالحة.")
    return parsed


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _qty(value: Decimal) -> Decimal:
    return value.quantize(QTY_QUANT, rounding=ROUND_HALF_UP)


class ProductionOrderService:
    def __init__(
        self,
        repository: ProductionOrderRepository | None = None,
        permission_check: Callable[[str], bool] | None = None,
    ) -> None:
        self.repository = repository or ProductionOrderRepository()
        # Permissive by default (unit tests / standalone launch); the screen wires
        # this to SESSION.can so the action layer enforces permissions too.
        self._can = permission_check or (lambda _code: True)

    # -- permissions ---------------------------------------------------------
    def _require(self, action: str) -> None:
        if not self._can(_perm(action)):
            raise ProductionOrderPermissionError(
                "ليس لديك صلاحية لتنفيذ هذا الإجراء."
            )

    # ======================================================================
    # Master-data pass-throughs (products) + numbering + load/search
    # ======================================================================
    def search_products(self, keyword: str, limit: int = 100) -> list[dict[str, Any]]:
        """Products for the finished-product lookup popup on the order screen."""
        return self.repository.search_products(keyword, limit)

    def get_product(self, product_id: Any) -> dict[str, Any] | None:
        return self.repository.get_product(int(product_id))

    def reserve_order_number(self) -> str:
        """Reserve the next global automatic order number ("PRO-001", ...)."""
        return self.repository.reserve_order_number()

    def peek_next_number(self) -> str:
        """Advisory next automatic order number (for pre-filling a new form)."""
        return self.repository.peek_next_number()

    def load(self, order_id: Any) -> dict[str, Any] | None:
        """Load a full order (``{"header", "lines"}``) for the screen."""
        return self.repository.load_order(int(order_id))

    def search_orders(
        self,
        keyword: str = "",
        limit: int = 300,
        *,
        product_id: int | None = None,
        date_from: Any = None,
        date_to: Any = None,
    ) -> list[dict[str, Any]]:
        return self.repository.search_orders(
            keyword, limit, product_id=product_id, date_from=date_from, date_to=date_to
        )

    # ======================================================================
    # Finished-product snapshot (from the database — never trusted from the UI)
    # ======================================================================
    def build_product_snapshot(self, product_id: Any) -> dict[str, Any]:
        if product_id in (None, ""):
            raise ProductionOrderValidationError("يجب اختيار المنتج التام.")
        product = self.repository.get_product(int(product_id))
        if product is None:
            raise ProductionOrderValidationError("المنتج التام غير موجود.")
        name = (product.get("item_name") or "").strip()
        if name == "":
            raise ProductionOrderValidationError("المنتج التام المحدد بدون اسم.")
        return {
            "product_id": int(product["id"]),
            "product_name_snapshot": name[:MAX_ITEM_NAME_LEN],
        }

    # ======================================================================
    # BOM resolution (consumes the existing BOM module; no BOM logic duplicated)
    # ======================================================================
    def list_boms_for_product(self, product_id: Any) -> list[dict[str, Any]]:
        """All BOMs for a finished product (most recent first) — for the UI picker."""
        if product_id in (None, ""):
            raise ProductionOrderValidationError("يجب اختيار المنتج التام.")
        return self.repository.find_boms_for_product(int(product_id))

    def resolve_bom(
        self, product_id: Any, bom_id: Any = None
    ) -> tuple[int, dict[str, Any]]:
        """Resolve which BOM to consume and load it.

        Rules:
        * no BOM        -> reject (clear Arabic message);
        * one BOM       -> use it automatically;
        * many BOMs and no ``bom_id`` -> reject asking for explicit selection (never
          silently guess);
        * ``bom_id`` given -> it must belong to the selected finished product;
        * the resolved BOM must contain at least one component.

        Returns ``(bom_id, {"header", "lines"})``.
        """
        if product_id in (None, ""):
            raise ProductionOrderValidationError("يجب اختيار المنتج التام.")
        product_id = int(product_id)
        boms = self.repository.find_boms_for_product(product_id)
        if not boms:
            raise ProductionOrderValidationError(
                "المنتج التام المحدد ليس له قائمة مواد (BOM). أنشئ قائمة مواد أولًا."
            )

        if bom_id in (None, ""):
            if len(boms) > 1:
                raise ProductionOrderValidationError(
                    "يوجد أكثر من قائمة مواد لهذا المنتج. يجب اختيار قائمة المواد المطلوبة."
                )
            resolved_id = int(boms[0]["id"])
        else:
            resolved_id = int(bom_id)
            if not any(int(b["id"]) == resolved_id for b in boms):
                raise ProductionOrderValidationError(
                    "قائمة المواد المحددة لا تخص المنتج التام المختار."
                )

        bom = self.repository.load_bom(resolved_id)
        if bom is None:
            raise ProductionOrderValidationError("قائمة المواد المحددة غير موجودة.")
        if not bom.get("lines"):
            raise ProductionOrderValidationError(
                "قائمة المواد المحددة لا تحتوي على أي مكوّنات."
            )
        return resolved_id, bom

    # ======================================================================
    # Quantity maths (Decimal only)
    # ======================================================================
    def compute_expected(
        self, production_quantity: Decimal, bom_quantity_per_unit: Decimal
    ) -> Decimal:
        """``expected = production_quantity × bom_quantity_per_unit`` (3 dp)."""
        return _qty(production_quantity * bom_quantity_per_unit)

    def compute_deviation(
        self, actual_quantity: Decimal, expected_quantity: Decimal
    ) -> Decimal:
        """``deviation = actual − expected`` (3 dp; may be negative/zero/positive)."""
        return _qty(actual_quantity - expected_quantity)

    @staticmethod
    def _clean_production_quantity(value: Any) -> Decimal:
        qty = _qty(_to_decimal(value, "الكمية المطلوب إنتاجها"))
        if qty <= 0:
            raise ProductionOrderValidationError(
                "الكمية المطلوب إنتاجها يجب أن تكون أكبر من صفر."
            )
        return qty

    def _bom_line_snapshot(self, bom_line: dict[str, Any]) -> dict[str, Any]:
        """The stable snapshot fields copied from a BOM line onto an order line."""
        name = (str(bom_line.get("item_name_snapshot") or "")).strip()
        return {
            "component_product_id": int(bom_line["component_product_id"]),
            "item_code_snapshot": bom_line.get("item_code_snapshot"),
            "item_name_snapshot": name[:MAX_ITEM_NAME_LEN],
            "unit_snapshot": str(bom_line.get("unit_snapshot") or "").strip()[:50],
            "bom_quantity_per_unit": _qty(_to_decimal(
                bom_line.get("quantity"), "كمية المكوّن في قائمة المواد"
            )),
            "bom_price_snapshot": _money(_to_decimal(
                bom_line.get("price"), "سعر المكوّن في قائمة المواد"
            )),
        }

    def _build_line(
        self,
        bom_line: dict[str, Any],
        production_quantity: Decimal,
        *,
        finished_product_id: int,
        actual_override: Any = None,
    ) -> dict[str, Any]:
        """Build one order line from a BOM line.

        ``expected`` is always recomputed here; ``actual`` defaults to ``expected``
        unless a valid non-blank override is supplied (>= 0 enforced). Any
        caller-supplied expected/deviation is ignored.
        """
        snap = self._bom_line_snapshot(bom_line)

        # Defensive: the finished product must never appear as its own material
        # (the BOM already forbids this, but we never trust stored data blindly).
        if snap["component_product_id"] == int(finished_product_id):
            raise ProductionOrderValidationError(
                "لا يمكن أن يظهر المنتج التام نفسه كأحد مواد أمر الإنتاج."
            )

        expected = self.compute_expected(production_quantity, snap["bom_quantity_per_unit"])
        if actual_override in (None, ""):
            actual = expected
        else:
            actual = _qty(_to_decimal(actual_override, "الكمية الفعلية"))
            if actual < 0:
                raise ProductionOrderValidationError(
                    "الكمية الفعلية لا يمكن أن تكون سالبة."
                )

        return {
            **snap,
            "expected_quantity": expected,
            "actual_quantity": actual,
            # deviation is a generated column server-side; provided for payloads only.
            "deviation": self.compute_deviation(actual, expected),
        }

    def _build_lines(
        self,
        bom: dict[str, Any],
        production_quantity: Decimal,
        *,
        finished_product_id: int,
        actual_by_component: dict[int, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Build all order lines from a resolved BOM, de-duplicating components."""
        actual_by_component = actual_by_component or {}
        lines: list[dict[str, Any]] = []
        seen: set[int] = set()
        for bom_line in bom["lines"]:
            component_id = int(bom_line["component_product_id"])
            # A component must not appear twice in the same order (BOM already
            # guarantees this; enforced here for defence in depth).
            if component_id in seen:
                raise ProductionOrderValidationError(
                    "لا يُسمح بتكرار نفس المكوّن في أمر الإنتاج."
                )
            seen.add(component_id)
            lines.append(self._build_line(
                bom_line,
                production_quantity,
                finished_product_id=finished_product_id,
                actual_override=actual_by_component.get(component_id),
            ))
        if not lines:
            raise ProductionOrderValidationError(
                "قائمة المواد المحددة لا تحتوي على أي مكوّنات."
            )
        return lines

    # ======================================================================
    # Explicit reload («صرف المواد الخام») — resets actual to expected
    # ======================================================================
    def load_materials(
        self, product_id: Any, production_quantity: Any, *, bom_id: Any = None
    ) -> dict[str, Any]:
        """(Re)load material requirement lines from the selected BOM (no persistence).

        Backs the UI action «صرف المواد الخام». Rebuilds every line, refreshes all
        snapshots from the BOM, recomputes ``expected_quantity`` and RESETS
        ``actual_quantity`` to it. Does NOT create any stock movement.

        Returns ``{"bom_id", "production_quantity", "lines"}``.
        """
        product = self.build_product_snapshot(product_id)
        qty = self._clean_production_quantity(production_quantity)
        resolved_bom_id, bom = self.resolve_bom(product["product_id"], bom_id)
        lines = self._build_lines(
            bom, qty, finished_product_id=product["product_id"]
        )
        return {
            "bom_id": resolved_bom_id,
            "production_quantity": qty,
            "lines": lines,
        }

    # ======================================================================
    # Production-quantity change on already loaded lines — preserves actual
    # ======================================================================
    def recalculate_for_quantity(
        self, lines: list[dict[str, Any]], new_production_quantity: Any
    ) -> list[dict[str, Any]]:
        """Recompute ``expected`` (and ``deviation``) for a new production quantity.

        The user's ``actual_quantity`` on each line is PRESERVED (a quantity change
        alone must not reset it — that only happens on an explicit BOM reload). Each
        line's stored ``bom_quantity_per_unit`` drives the new expected quantity.
        """
        qty = self._clean_production_quantity(new_production_quantity)
        result: list[dict[str, Any]] = []
        for line in lines:
            per_unit = _qty(_to_decimal(
                line.get("bom_quantity_per_unit"), "كمية المكوّن في قائمة المواد"
            ))
            expected = self.compute_expected(qty, per_unit)
            actual = _qty(_to_decimal(line.get("actual_quantity"), "الكمية الفعلية"))
            if actual < 0:
                raise ProductionOrderValidationError(
                    "الكمية الفعلية لا يمكن أن تكون سالبة."
                )
            updated = dict(line)
            updated["bom_quantity_per_unit"] = per_unit
            updated["expected_quantity"] = expected
            updated["actual_quantity"] = actual
            updated["deviation"] = self.compute_deviation(actual, expected)
            result.append(updated)
        return result

    # ======================================================================
    # Header validation / assembly
    # ======================================================================
    @staticmethod
    def _clean_order_date(value: Any) -> Any:
        if value in (None, ""):
            raise ProductionOrderValidationError("تاريخ أمر الإنتاج مطلوب.")
        return value

    def _clean_order_number(self, value: Any, *, exclude_id: int | None) -> str:
        """Return a validated, unique order number.

        Blank -> reserve the next automatic number. A supplied value is validated
        for global uniqueness (the UNIQUE index is the final guard at save time).
        """
        number = ("" if value is None else str(value)).strip()
        if number == "":
            return self.repository.reserve_order_number()
        if self.repository.order_number_exists(number, exclude_id=exclude_id):
            raise ProductionOrderValidationError("رقم أمر الإنتاج مستخدم مسبقًا.")
        return number

    @staticmethod
    def _actual_by_component(raw_lines: Any) -> dict[int, Any]:
        """Map component_product_id -> submitted actual quantity (expected/deviation ignored)."""
        mapping: dict[int, Any] = {}
        for raw in raw_lines or []:
            component_id = raw.get("component_product_id")
            if component_id in (None, ""):
                continue
            try:
                mapping[int(component_id)] = raw.get("actual_quantity")
            except (TypeError, ValueError):
                continue
        return mapping

    def _prepare(
        self, form: dict[str, Any], *, exclude_id: int | None
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Validate + rebuild a header + lines from raw ``form`` input.

        Everything numeric is derived server-side: the finished-product snapshot,
        the resolved BOM, ``expected_quantity`` and ``deviation`` are all recomputed
        here; only the per-line ``actual_quantity`` is taken from the caller (and
        validated). Any caller-supplied expected/deviation is ignored.
        """
        order_date = self._clean_order_date(form.get("order_date"))
        product = self.build_product_snapshot(form.get("product_id"))
        production_quantity = self._clean_production_quantity(
            form.get("production_quantity")
        )
        resolved_bom_id, bom = self.resolve_bom(
            product["product_id"], form.get("bom_id")
        )
        lines = self._build_lines(
            bom,
            production_quantity,
            finished_product_id=product["product_id"],
            actual_by_component=self._actual_by_component(form.get("lines")),
        )
        order_number = self._clean_order_number(
            form.get("order_number"), exclude_id=exclude_id
        )

        header = {
            "order_number": order_number,
            "order_date": order_date,
            **product,
            "bom_id": resolved_bom_id,
            "production_quantity": production_quantity,
        }
        return header, lines

    # ======================================================================
    # Create / update / delete
    # ======================================================================
    def create_order(
        self, form: dict[str, Any], *, user_id: int | None = None
    ) -> dict[str, Any]:
        """Validate + persist a new order (header + lines) in one transaction."""
        self._require("save")
        header, lines = self._prepare(form, exclude_id=None)
        header["created_by"] = user_id
        header["updated_by"] = user_id
        return self.repository.insert_order(header, lines)

    def update_order(
        self, order_id: int, form: dict[str, Any], *, user_id: int | None = None
    ) -> dict[str, Any]:
        """Validate + update an existing order (header + replace lines)."""
        self._require("edit")
        existing = self.repository.load_order(int(order_id))
        if existing is None:
            raise ProductionOrderValidationError("أمر الإنتاج غير موجود.")

        header, lines = self._prepare(form, exclude_id=int(order_id))
        header_changes = {
            "order_number": header["order_number"],
            "order_date": header["order_date"],
            "product_id": header["product_id"],
            "product_name_snapshot": header["product_name_snapshot"],
            "bom_id": header["bom_id"],
            "production_quantity": header["production_quantity"],
            "updated_by": user_id,
        }
        updated = self.repository.update_order(int(order_id), header_changes, lines)
        if updated is None:
            raise ProductionOrderValidationError("أمر الإنتاج غير موجود.")
        return updated

    def delete_order(self, order_id: int, *, user_id: int | None = None) -> bool:
        """Delete an order (its lines cascade). Raises if it does not exist."""
        self._require("delete")
        existing = self.repository.load_order(int(order_id))
        if existing is None:
            raise ProductionOrderValidationError("أمر الإنتاج غير موجود.")
        return self.repository.delete_order(int(order_id))


__all__ = [
    "ProductionOrderService",
    "ProductionOrderServiceError",
    "ProductionOrderValidationError",
    "ProductionOrderPermissionError",
    "Decimal",
]
