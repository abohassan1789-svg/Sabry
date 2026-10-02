"""Domain constants and column maps for the purchase-invoice tables.

Scope note
----------
Like :mod:`app.models.sales_invoice`, this module contains **no DDL and never
runs any schema statement**. The three tables it describes are created (once,
idempotently) by ``app/database/schema/full_schema.sql``:

* ``purchase_invoices``            — invoice header (one row per invoice)
* ``purchase_invoice_lines``       — invoice detail lines
* ``purchase_invoice_audit_logs``  — append-only audit trail

This layer therefore holds only *structure metadata* (table + column names) and
*reusable domain constants* (statuses, payment types, numbering, precisions).

A purchase invoice is a count/weight document with **no VAT, no ZATCA/Phase-2
data and no print pipeline** — the deliberate differences from the sales
invoice. Its counterparty is a supplier (name snapshot from ``suppliers``) and
its line items are free text (no products link).

All monetary / quantity / weight values are handled with :class:`decimal.Decimal`;
Python ``float`` is never used for invoice figures.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

# --- table names ------------------------------------------------------------

TBL_INVOICES = "purchase_invoices"
TBL_LINES = "purchase_invoice_lines"
TBL_AUDIT_LOGS = "purchase_invoice_audit_logs"

# --- document status (mirrors purchase_invoices.document_status) -------------

STATUS_DRAFT = "draft"
STATUS_APPROVED = "approved"

STATUS_LABELS_AR = {
    STATUS_DRAFT: "مسودة",
    STATUS_APPROVED: "معتمدة",
}

# --- payment type (stored codes; UI shows the Arabic labels) -----------------

PAYMENT_CASH = "cash"
PAYMENT_CREDIT = "credit"

PAYMENT_LABELS_AR = {
    PAYMENT_CASH: "نقدي",
    PAYMENT_CREDIT: "آجل",
}

# --- automatic numbering ("Pur-1001", "Pur-1002", ...) -----------------------
# The purchase invoice number is a single global editable-but-automatic series:
# a "Pur-" prefix followed by a sequence value that starts at 1001. The sequence
# lives in the database (``purchase_invoice_number_seq``); this module only owns
# how a sequence value is rendered to / parsed from the displayed number.
PURCHASE_NUMBER_PREFIX = "Pur-"
PURCHASE_NUMBER_START = 1001  # mirrors the sequence MINVALUE / START WITH


def format_invoice_number(sequence_value: Any) -> str:
    """Render a sequence value as the displayed number, e.g. ``1001 → 'Pur-1001'``."""
    return f"{PURCHASE_NUMBER_PREFIX}{int(sequence_value)}"


def parse_sequence_value(invoice_number: Any) -> int | None:
    """Extract the numeric sequence from a displayed number, or ``None``.

    Accepts the canonical ``"Pur-1001"`` form (case-insensitive prefix) and a
    bare numeric string ``"1001"``; anything else returns ``None`` so a manual,
    non-standard number never moves the automatic sequence. Only the trailing
    run of digits after an optional prefix is treated as the sequence.
    """
    text = str(invoice_number or "").strip()
    if text == "":
        return None
    match = re.fullmatch(
        rf"(?:{re.escape(PURCHASE_NUMBER_PREFIX)})?(\d+)", text, flags=re.IGNORECASE
    )
    if match is None:
        return None
    return int(match.group(1))

# --- numeric precision (must not exceed the physical column definitions) -----

MONEY_QUANT = Decimal("0.01")          # numeric(18,2) amounts round to 2 dp
QTY_QUANT = Decimal("0.000001")        # numeric(18,6) count / weight / unit_price

# --- line item identity limit (mirrors the physical varchar length) ----------
MAX_ITEM_NAME_LEN = 255                # item_name_snapshot varchar(255)

# --- header columns the application is allowed to write ----------------------
# ``id`` (IDENTITY), ``created_at``/``updated_at`` (DB defaults), ``row_version``
# (DB-managed) and the approval columns are intentionally excluded here.
INVOICE_INSERT_COLUMNS: tuple[str, ...] = (
    "invoice_number",
    "issue_datetime",
    "supplier_id",
    "supplier_name_snapshot",
    "payment_type",
    "notes",
    "total_count_price",
    "total_weight_price",
    "document_status",
    "created_by",
    "updated_by",
)

# Header columns read back / shown on the screen.
INVOICE_SELECT_COLUMNS: tuple[str, ...] = (
    "id",
    "invoice_number",
    "issue_datetime",
    "supplier_id",
    "supplier_name_snapshot",
    "payment_type",
    "notes",
    "total_count_price",
    "total_weight_price",
    "document_status",
    "approved_at",
    "approved_by",
    "created_by",
    "updated_by",
    "created_at",
    "updated_at",
    "row_version",
)

# Detail-line columns the application writes (``id`` is IDENTITY; timestamps
# default in the database).
LINE_INSERT_COLUMNS: tuple[str, ...] = (
    "invoice_id",
    "line_number",
    "item_code_snapshot",
    "item_name_snapshot",
    "unit_snapshot",
    "item_count",
    "unit_weight",
    "total_weight",
    "unit_price",
    "count_price_total",
    "weight_price_total",
)

LINE_SELECT_COLUMNS: tuple[str, ...] = ("id",) + LINE_INSERT_COLUMNS


__all__ = [name for name in dir() if not name.startswith("_")]
