"""Small PostgreSQL CRUD service for CRM review screens."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.sql import SQL, Identifier

from app.config.database import build_database_url, runtime_connect_kwargs
from app.config.settings import get_settings

# Accepted spellings for a ``bool`` FieldSpec. The Arabic labels are what the
# form's combo shows; the rest let an Excel import or a legacy value round-trip.
_TRUE_TEXTS = frozenset({"نشط", "true", "True", "1", "yes", "Yes", "نعم"})
_FALSE_TEXTS = frozenset({"موقوف", "false", "False", "0", "no", "No", "لا"})

# نوع المقاول — the four values the ``ck_contractors_type`` CHECK accepts.
CONTRACTOR_TYPES = ("مقاول", "مورد", "استشاري", "دعاية وإعلان")


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    data_type: str = "text"
    required: bool = False
    readonly: bool = False
    hidden_on_form: bool = False
    # Virtual fields are shown on the form/list for convenience (e.g. the linked
    # customer's name/phone) but are NOT columns on the screen's own table, so
    # they are skipped on SELECT/INSERT/UPDATE.
    virtual: bool = False
    # Optional group box label; fields sharing a group render together.
    group: str = ""
    # Combo data source: "employees" | "case_statuses" | "customers_phone" | "customers_name".
    combo_source: str = ""
    # Fixed dropdown choices. When set the field renders as a read-only-edit
    # combo offering exactly these values (the stored value is the text itself),
    # e.g. نوع الحساب -> ("عدد", "وزن"). Independent of combo_source (which is for
    # database-backed lookups).
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableSpec:
    key: str
    table_name: str
    title: str
    icon_text: str
    primary_key: str
    search_columns: tuple[str, ...]
    list_columns: tuple[str, ...]
    fields: tuple[FieldSpec, ...]
    # Optional explicit column set for the F1 lookup dialog. When empty the
    # dialog falls back to all visible form fields.
    lookup_columns: tuple[str, ...] = ()


TABLE_SPECS: dict[str, TableSpec] = {
    "customers": TableSpec(
        key="customers",
        table_name="customers",
        title="إدارة العملاء",
        icon_text="C",
        primary_key="customer_id",
        search_columns=("customer_name", "phone_number", "address"),
        # The search grid shows only name + phone; the row still carries its
        # customer_id (fetched by list_records) for selection/loading.
        list_columns=("customer_name", "phone_number"),
        fields=(
            # The customer screen shows only five fields: an auto code (displayed
            # as CUS-<id>), name, phone, address, and opening balance. The legacy
            # location/tax columns are kept in the table but hidden from the form
            # (hidden_on_form=True) so no stored data is lost — they can be
            # un-hidden later without a schema change.
            FieldSpec("customer_id", "كود العميل", "int", readonly=True),
            FieldSpec("customer_name", "اسم العميل"),
            FieldSpec("phone_number", "الهاتف"),
            FieldSpec("address", "العنوان"),
            FieldSpec("opening_balance", "رصيد أول المدة", "float"),
            FieldSpec("place_area_feddan", "كود المنطقة", "int", hidden_on_form=True),
            FieldSpec("area_number", "رقم المنطقة", hidden_on_form=True),
            FieldSpec("building", "المبنى", hidden_on_form=True),
            FieldSpec("unit_number", "الوحدة", hidden_on_form=True),
            FieldSpec("floor_number", "الدور", hidden_on_form=True),
            FieldSpec("vat_number", "الرقم الضريبي", hidden_on_form=True),
            FieldSpec("cr", "السجل التجاري", hidden_on_form=True),
            FieldSpec("installment_duration_years", "مدة الأقساط", "int", hidden_on_form=True),
            FieldSpec("remaining_installments", "الأقساط المتبقية", "int", hidden_on_form=True),
            FieldSpec("installment_amount", "قيمة القسط", "int", hidden_on_form=True),
            FieldSpec("legacy_area_number_2", "رقم منطقة إضافي", hidden_on_form=True),
        ),
    ),
    "suppliers": TableSpec(
        key="suppliers",
        table_name="suppliers",
        title="إدارة الموردين",
        icon_text="S",
        primary_key="supplier_id",
        search_columns=("supplier_name", "mobile"),
        # The list under the form shows only name + mobile; supplier_id is still
        # fetched (list_records prepends the primary key) for row selection.
        list_columns=("supplier_name", "mobile"),
        fields=(
            # Auto code from the suppliers sequence (starts 1001) — shown
            # read-only, never written by the app (like customer_id / item_code).
            FieldSpec("supplier_id", "كود المورد", "int", readonly=True),
            FieldSpec("supplier_name", "اسم المورد"),
            FieldSpec("mobile", "الموبايل"),
            # نوع الحساب: hidden from the form at the user's request (2026-08-21).
            # Kept as a hidden field (not dropped) so stored values survive and it
            # can be un-hidden later without a schema change. Fixed dropdown —
            # عدد أو وزن, stored as the Arabic text — preserved for that case.
            FieldSpec("account_type", "نوع الحساب", choices=("عدد", "وزن"),
                      hidden_on_form=True),
            FieldSpec("opening_balance", "رصيد أول المدة", "float"),
        ),
    ),
    # --- قسم التوريدات ----------------------------------------------------
    # Phase 1. Mirrors the legacy Access screen ``Fgararat`` field for field, so
    # staff moving off the Access program see the same form. ``tractor_code`` is
    # the مسلسل they already use (unique), and the plate numbers are text — see
    # the note on the table in schema/full_schema.sql.
    "tawrid_tractors": TableSpec(
        key="tawrid_tractors",
        table_name="tawrid_tractors",
        title="إدارة الجرارات",
        icon_text="🚜",
        primary_key="tractor_id",
        search_columns=("driver_name", "trailer_no", "head_no", "phone"),
        list_columns=("driver_name", "trailer_no"),
        fields=(
            FieldSpec("tractor_code", "مسلسل", "int", required=True, group="بيانات الجرار"),
            FieldSpec("driver_name", "إسم السائق", required=True, group="بيانات الجرار"),
            FieldSpec("trailer_no", "رقم المقطورة", group="بيانات الجرار"),
            FieldSpec("head_no", "رقم الوش", group="بيانات الجرار"),
            FieldSpec("phone", "الموبايل", group="بيانات الجرار"),
            FieldSpec("is_active", "الحالة", "bool", choices=("نشط", "موقوف"),
                      group="بيانات الجرار"),
            FieldSpec("price_sen", "سعر السن", "float", group="الأسعار والرصيد"),
            FieldSpec("price_raml", "سعر الرمل", "float", group="الأسعار والرصيد"),
            FieldSpec("opening_balance", "رصيد أول المدة", "float", group="الأسعار والرصيد"),
            FieldSpec("opening_date", "تاريخ الرصيد", "date", group="الأسعار والرصيد"),
            FieldSpec("notes", "ملاحظات", group="الأسعار والرصيد"),
        ),
        lookup_columns=("tractor_code", "driver_name", "trailer_no", "head_no"),
    ),
    "tawrid_customers": TableSpec(
        key="tawrid_customers",
        table_name="tawrid_customers",
        title="إدارة العملاء - التوريدات",
        icon_text="👥",
        primary_key="customer_id",
        search_columns=("customer_name", "phone", "customer_code"),
        list_columns=("customer_code", "customer_name"),
        fields=(
            FieldSpec("customer_code", "مسلسل", "int", required=True, group="بيانات العميل"),
            FieldSpec("customer_name", "اسم العميل", required=True, group="بيانات العميل"),
            FieldSpec("phone", "الموبايل", group="بيانات العميل"),
            FieldSpec("is_active", "الحالة", "bool", choices=("نشط", "موقوف"),
                      group="بيانات العميل"),
            FieldSpec("opening_balance", "رصيد أول المدة", "float", group="بيانات العميل"),
            # FEMP never showed fanii.date123, so opening balances were entered
            # undated even though the statement query reads the column.
            FieldSpec("opening_date", "تاريخ الرصيد", "date", group="بيانات العميل"),
            FieldSpec("discount_percent", "نسبة الخصم %", "float", group="بيانات العميل"),
            FieldSpec("notes", "ملاحظات", group="بيانات العميل"),
            # The ten item prices. hidden_on_form keeps them out of the base
            # form panel: the screen builds them itself inside the «أسعار
            # الأصناف» tab (Model 2), registering the same editors in
            # ``self.inputs`` so saving/validation stay on the shared path.
            # Order and labels are FEMP's, including «سن عتاقة» on the column
            # Access called sen3.
            FieldSpec("price_sen1", "سن 1", "float", hidden_on_form=True),
            FieldSpec("price_sen2", "سن 2", "float", hidden_on_form=True),
            FieldSpec("price_sen_ataqa", "سن عتاقة", "float", hidden_on_form=True),
            FieldSpec("price_sen6_safi", "سن 6 صافي", "float", hidden_on_form=True),
            FieldSpec("price_sen6_bodra", "سن 6 بالبودرة", "float", hidden_on_form=True),
            FieldSpec("price_sen_adsa", "سن عدسة", "float", hidden_on_form=True),
            FieldSpec("price_bodra", "بودرة", "float", hidden_on_form=True),
            FieldSpec("price_raml", "رملة", "float", hidden_on_form=True),
            FieldSpec("price_sen_plus", "سن+", "float", hidden_on_form=True),
            FieldSpec("price_sen_modarag", "سن مدرج", "float", hidden_on_form=True),
        ),
        lookup_columns=("customer_code", "customer_name", "phone", "opening_balance"),
    ),
    # Phase 3. Replaces the Access screen ``Fproduct`` over ``pruduct``. In this
    # business المورد = الكسّارة, one entity under two names — the menu says
    # «الكسارات», the screen's own caption said «الموردين» — so the labels here
    # use المورد exactly as ``Fproduct`` did. Independent of the older
    # ``suppliers`` table, which belongs to a different module.
    "tawrid_suppliers": TableSpec(
        key="tawrid_suppliers",
        table_name="tawrid_suppliers",
        title="إدارة الكسارات - التوريدات",
        icon_text="🏗",
        primary_key="supplier_id",
        search_columns=("supplier_name", "phone", "supplier_code"),
        list_columns=("supplier_code", "supplier_name"),
        fields=(
            FieldSpec("supplier_code", "مسلسل", "int", required=True, group="بيانات المورد"),
            FieldSpec("supplier_name", "اسم المورد", required=True, group="بيانات المورد"),
            FieldSpec("phone", "الموبايل", group="بيانات المورد"),
            FieldSpec("is_active", "الحالة", "bool", choices=("نشط", "موقوف"),
                      group="بيانات المورد"),
            FieldSpec("opening_balance", "رصيد أول المدة", "float", group="بيانات المورد"),
            # ``pruduct.date123`` has a value on all 23 rows, but Fproduct never
            # showed it — so no opening balance was ever entered with its date.
            FieldSpec("opening_date", "تاريخ الرصيد", "date", group="بيانات المورد"),
            # ``pruduct.notees`` exists and has no control on Fproduct at all,
            # which is why it is empty in 23 rows out of 23.
            FieldSpec("notes", "ملاحظات", group="بيانات المورد"),
            # The ten item prices. hidden_on_form keeps them out of the base form
            # panel: the screen builds them itself in the «أسعار الأصناف» panel
            # beside the form, registering the same editors in ``self.inputs`` so
            # saving and mode switching stay on the shared path. Order and labels
            # are Fproduct's, including «سن عتاقة» on the column Access called
            # sen3.
            FieldSpec("price_sen1", "سن 1", "float", hidden_on_form=True),
            FieldSpec("price_sen2", "سن 2", "float", hidden_on_form=True),
            FieldSpec("price_sen_ataqa", "سن عتاقة", "float", hidden_on_form=True),
            FieldSpec("price_sen6_safi", "سن 6 صافي", "float", hidden_on_form=True),
            FieldSpec("price_sen6_bodra", "سن 6 بالبودرة", "float", hidden_on_form=True),
            FieldSpec("price_sen_adsa", "سن عدسة", "float", hidden_on_form=True),
            FieldSpec("price_bodra", "بودرة", "float", hidden_on_form=True),
            FieldSpec("price_raml", "رملة", "float", hidden_on_form=True),
            FieldSpec("price_sen_plus", "سن+", "float", hidden_on_form=True),
            FieldSpec("price_sen_modarag", "سن مدرج", "float", hidden_on_form=True),
        ),
        lookup_columns=("supplier_code", "supplier_name", "phone", "opening_balance"),
    ),
    # قسم التوريدات — المرحلة الرابعة: البون (التذكرة). A transaction/document
    # screen, not a master card: the three party ids are set through pickers (not
    # typed), and the five money totals are DB-GENERATED so they are not fields
    # here at all — the screen reads them back through ``TawridTicketService``.
    # Only the writable columns are declared, so the shared save path writes
    # exactly them and never tries to assign a generated column.
    "tawrid_tickets": TableSpec(
        key="tawrid_tickets",
        table_name="tawrid_tickets",
        title="إدارة البون - التوريدات",
        icon_text="🧾",
        primary_key="ticket_id",
        search_columns=("ticket_no", "receipt_no", "item_name"),
        list_columns=("ticket_no", "ticket_date", "item_name"),
        fields=(
            FieldSpec("ticket_id", "كود البون", "int", readonly=True, hidden_on_form=True),
            FieldSpec("ticket_no", "رقم البون", "int", required=True),
            FieldSpec("ticket_date", "التاريخ", "date", required=True),
            FieldSpec("receipt_no", "رقم الإيصال"),
            # The three party ids + the item id. Filled by the pickers/combo, so
            # they are readonly (never typed) but still written on save — the base
            # save excludes only a readonly PRIMARY KEY, not a readonly FK.
            FieldSpec("customer_id", "العميل", "int", readonly=True),
            FieldSpec("supplier_id", "الكسّارة", "int", readonly=True),
            FieldSpec("tractor_id", "الجرار", "int", readonly=True),
            # NOT readonly: the item combo must enable in edit/new mode.
            FieldSpec("item_id", "الصنف", "int"),
            FieldSpec("item_name", "اسم الصنف"),
            FieldSpec("item_family", "نوع الصنف"),
            # العميل layer.
            FieldSpec("cus_volume", "تكعيب العميل", "float"),
            FieldSpec("price_cus", "سعر العميل", "float"),
            FieldSpec("discount_percent", "نسبة الخصم %", "float"),
            # الكسّارة layer.
            FieldSpec("res_volume", "تكعيب الكسّارة", "float"),
            FieldSpec("price_res", "سعر الكسّارة", "float"),
            # الجرار layer.
            FieldSpec("price_man", "سعر النقل", "float"),
            FieldSpec("notes", "ملاحظات"),
        ),
    ),
    # قسم التوريدات — المرحلة الخامسة: تكعيب الكسّارات (كشف رأس + سطور). A
    # master→detail DOCUMENT, not a master card: the header carries only the
    # crusher (set through a picker, never typed), the date and the sheet number;
    # the tractor lines live in ``tawrid_crusher_cubing_lines`` and are handled by
    # ``TawridCubingService``, not by this spec. There is NO price column anywhere
    # (the Access ``sallesHead``/``Sallesdata`` recorded volume only).
    "tawrid_crusher_cubing": TableSpec(
        key="tawrid_crusher_cubing",
        table_name="tawrid_crusher_cubing",
        title="تكعيب الكسّارات",
        icon_text="🏗️",
        primary_key="cubing_id",
        search_columns=("sheet_no",),
        list_columns=("sheet_no", "sheet_date"),
        fields=(
            FieldSpec("cubing_id", "كود الكشف", "int", readonly=True, hidden_on_form=True),
            FieldSpec("sheet_no", "رقم الكشف", "int", required=True),
            FieldSpec("sheet_date", "التاريخ", "date", required=True),
            # Filled by the crusher picker, so readonly (never typed) but still
            # written on save — the base save excludes only a readonly PRIMARY KEY.
            FieldSpec("crusher_id", "الكسّارة", "int", readonly=True),
            FieldSpec("notes", "ملاحظات"),
        ),
    ),
    # قسم التوريدات — المرحلة السادسة: سند قبض العميل. Replaces the Access table
    # ``sanadCus`` (مدفوعات العملاء) — a flat log: التاريخ · العميل · المبلغ ·
    # البيان. The customer id is set through a picker (never typed), so it is
    # readonly but still written on save (the base save excludes only a readonly
    # PRIMARY KEY). ``amount`` may be negative (a legacy reversal), so no CHECK on
    # it. The «الرصيد» analytics come from ``TawridCustomerReceiptService``.
    "tawrid_customer_receipts": TableSpec(
        key="tawrid_customer_receipts",
        table_name="tawrid_customer_receipts",
        title="سندات قبض العملاء",
        icon_text="🧾",
        primary_key="receipt_id",
        search_columns=("receipt_no", "statement"),
        list_columns=("receipt_no", "receipt_date", "amount"),
        fields=(
            FieldSpec("receipt_id", "كود السند", "int", readonly=True, hidden_on_form=True),
            FieldSpec("receipt_no", "رقم السند", "int", required=True),
            FieldSpec("receipt_date", "التاريخ", "date", required=True),
            # Filled by the customer picker, so readonly (never typed) but still
            # written on save.
            FieldSpec("customer_id", "العميل", "int", readonly=True),
            FieldSpec("amount", "المبلغ", "float", required=True),
            FieldSpec("statement", "البيان"),
        ),
    ),
    # قسم التوريدات — المرحلة السابعة: سندات صرف الكسّارات (← Access sanadsup, the
    # form «مدفوعات الموردين»). The mirror of tawrid_customer_receipts: رقم السند
    # (auto MAX+1, unique — Access had none), التاريخ, الكسّارة, المبلغ and the
    # البيان. The crusher id is set through a picker (never typed), so it is
    # readonly but still written on save (the base save excludes only a readonly
    # PRIMARY KEY). ``amount`` may be negative (a reversal), so no CHECK on it. The
    # «الرصيد» analytics come from ``TawridSupplierPaymentService``.
    "tawrid_supplier_payments": TableSpec(
        key="tawrid_supplier_payments",
        table_name="tawrid_supplier_payments",
        title="سندات صرف الكسّارات",
        icon_text="🧾",
        primary_key="payment_id",
        search_columns=("payment_no", "statement"),
        list_columns=("payment_no", "payment_date", "amount"),
        fields=(
            FieldSpec("payment_id", "كود السند", "int", readonly=True, hidden_on_form=True),
            FieldSpec("payment_no", "رقم السند", "int", required=True),
            FieldSpec("payment_date", "التاريخ", "date", required=True),
            # Filled by the crusher picker, so readonly (never typed) but still
            # written on save.
            FieldSpec("supplier_id", "الكسّارة", "int", readonly=True),
            FieldSpec("amount", "المبلغ", "float", required=True),
            FieldSpec("statement", "البيان"),
        ),
    ),
    # قسم التوريدات — سندات صرف الجرارات (SanadCAR). The tractor-side mirror of
    # tawrid_supplier_payments: same flat voucher (رقم/تاريخ/المبلغ/البيان). The
    # tractor id is set through a picker (never typed), so it is readonly but still
    # written on save (the base save excludes only a readonly PRIMARY KEY).
    # ``amount`` may be negative (a reversal), so no CHECK on it. The «الرصيد»
    # analytics come from ``TawridTractorPaymentService``.
    "tawrid_tractor_payments": TableSpec(
        key="tawrid_tractor_payments",
        table_name="tawrid_tractor_payments",
        title="سندات صرف الجرارات",
        icon_text="🧾",
        primary_key="payment_id",
        search_columns=("payment_no", "statement"),
        list_columns=("payment_no", "payment_date", "amount"),
        fields=(
            FieldSpec("payment_id", "كود السند", "int", readonly=True, hidden_on_form=True),
            FieldSpec("payment_no", "رقم السند", "int", required=True),
            FieldSpec("payment_date", "التاريخ", "date", required=True),
            # Filled by the tractor picker, so readonly (never typed) but still
            # written on save.
            FieldSpec("tractor_id", "الجرار", "int", readonly=True),
            FieldSpec("amount", "المبلغ", "float", required=True),
            FieldSpec("statement", "البيان"),
        ),
    ),
    "expenses": TableSpec(
        key="expenses",
        table_name="expenses",
        title="إدارة المصروفات",
        icon_text="M",
        primary_key="id",
        search_columns=("expense_type", "statement"),
        # The list shows date + type + amount; the id is fetched (list_records
        # prepends the primary key) for row selection.
        list_columns=("expense_date", "expense_type", "amount"),
        fields=(
            # id is auto-assigned by the sequence — kept off the form (there is
            # no user-facing code field), but still fetched for selection.
            FieldSpec("id", "الكود", "int", readonly=True, hidden_on_form=True),
            FieldSpec("expense_date", "التاريخ", "date", required=True),
            FieldSpec("amount", "المبلغ", "float", required=True),
            # نوع المصروف: free text that also behaves as an editable dropdown —
            # the screen fills the list from list_expense_types() (DISTINCT of the
            # stored values), so a newly typed type is offered next time.
            FieldSpec("expense_type", "نوع المصروف"),
            FieldSpec("statement", "البيان"),
        ),
    ),
    "treasury_deposits": TableSpec(
        key="treasury_deposits",
        table_name="treasury_deposits",
        title="إضافة أموال للخزينة",
        icon_text="خ",
        primary_key="id",
        # Searchable by the البيان text or the date — partial (ILIKE) match.
        search_columns=("statement", "movement_date"),
        # The list shows movement no. + date + amount; the id is prepended by the
        # list query for row selection.
        list_columns=("id", "movement_date", "amount"),
        fields=(
            # رقم الحركة: auto id from the sequence (starts at 3001) — shown
            # read-only on the form, with a preview on a new record.
            FieldSpec("id", "رقم الحركة", "int", readonly=True),
            FieldSpec("movement_date", "التاريخ", "date", required=True),
            FieldSpec("amount", "المبلغ", "float", required=True),
            FieldSpec("statement", "البيان"),
        ),
    ),
    "workers": TableSpec(
        key="workers",
        table_name="workers",
        title="إدارة العمال",
        icon_text="W",
        primary_key="worker_id",
        search_columns=("worker_name", "mobile"),
        # The list under the form shows only name + mobile; worker_id is still
        # fetched (list_records prepends the primary key) for row selection.
        list_columns=("worker_name", "mobile"),
        fields=(
            # Auto code from the workers sequence (starts 1) — shown read-only,
            # zero-padded to four digits in the UI (0001, 0002, ...).
            FieldSpec("worker_id", "كود العامل", "int", readonly=True),
            FieldSpec("worker_name", "اسم العامل"),
            FieldSpec("mobile", "الموبايل"),
            FieldSpec("opening_balance", "رصيد أول المدة", "float"),
        ),
    ),
    "products": TableSpec(
        key="products",
        table_name="products",
        title="إدارة الأصناف",
        icon_text="ص",
        primary_key="item_code",
        search_columns=("item_name", "item_code"),
        list_columns=("item_code", "item_name", "item_type", "unit", "price", "opening_balance"),
        fields=(
            # كود الصنف is auto-assigned from the products sequence (starts 1001),
            # exactly like customer_id — shown read-only, never written by the app.
            FieldSpec("item_code", "كود الصنف", "int", readonly=True),
            FieldSpec("item_name", "اسم الصنف", required=True),
            # نوع الصنف: fixed dropdown — مادة خام أو منتج تام. Stored as the Arabic
            # text (blank = unset).
            FieldSpec("item_type", "نوع الصنف", choices=("مادة خام", "منتج تام")),
            # الوحدة (unit of measure): optional free text, e.g. قطعة / كرتون / كيلو.
            FieldSpec("unit", "الوحدة"),
            FieldSpec("price", "سعر الوحدة", "float"),
            FieldSpec("opening_balance", "رصيد أول المدة", "float"),
            # الكمية والإجمالي مخفيان من الشاشة (بناءً على طلب المستخدم) لكن العمودين
            # يبقيان في قاعدة البيانات: quantity افتراضيًا 0، و total عمود مُولَّد.
            FieldSpec("quantity", "الكمية", "float", hidden_on_form=True),
            FieldSpec("total", "الإجمالي", "float", readonly=True, virtual=True, hidden_on_form=True),
        ),
    ),
    "companies": TableSpec(
        key="companies",
        table_name="companies",
        title="إدارة الشركات",
        icon_text="ش",
        primary_key="id",
        # Searchable by company name (Arabic/English), commercial registration, or
        # VAT number — a partial (ILIKE) match on any of these.
        search_columns=("name_ar", "name_en", "commercial_registration", "vat_number"),
        # The search grid shows only these three columns (in this order). The row's
        # primary key (id) is still fetched and attached for selection even though
        # it is not a visible column.
        list_columns=("name_ar", "vat_number", "commercial_registration"),
        fields=(
            # id is auto-assigned by PostgreSQL IDENTITY — shown read-only, never
            # written by the app (exactly like item_code / customer_id).
            FieldSpec("id", "كود الشركة", "int", readonly=True),
            FieldSpec("name_ar", "اسم الشركة (عربي)", required=True),
            FieldSpec("name_en", "اسم الشركة (إنجليزي)"),
            # Registration / VAT numbers are STRINGS (never numeric) so leading
            # zeros are preserved; each is UNIQUE at the database level.
            FieldSpec("commercial_registration", "السجل التجاري", required=True),
            FieldSpec("vat_number", "الرقم الضريبي", required=True),
            # Free-text phone/mobile (may hold more than one number). Shown on the
            # printed letterhead (Arabic block, under the address).
            FieldSpec("phone", "رقم الهاتف"),
            FieldSpec("address_ar", "العنوان (عربي)"),
            FieldSpec("address_en", "العنوان (إنجليزي)"),
        ),
    ),
    "employees": TableSpec(
        key="employees",
        table_name="employees",
        title="إدارة الموظفين",
        icon_text="E",
        primary_key="employee_id",
        search_columns=("employee_name", "phone_number", "governorate", "district_center", "village"),
        list_columns=("employee_id", "employee_name", "phone_number", "governorate"),
        fields=(
            FieldSpec("employee_id", "كود الموظف", "int", readonly=True),
            FieldSpec("employee_name", "اسم الموظف"),
            FieldSpec("phone_number", "الهاتف", required=True),
            FieldSpec("governorate", "المحافظة"),
            FieldSpec("district_center", "المركز"),
            FieldSpec("village", "القرية"),
        ),
    ),
    "daily_followups": TableSpec(
        key="daily_followups",
        table_name="daily_followups",
        title="إدارة المتابعة اليومية",
        icon_text="D",
        primary_key="daily_followup_id",
        search_columns=("customer_name", "customer_phone", "notes"),
        list_columns=(
            "daily_followup_id",
            "customer_name",
            "customer_phone",
            "follow_up_date",
            "case_status_name",
            "notes",
        ),
        lookup_columns=(
            "daily_followup_id",
            "follow_up_date",
            "customer_id",
            "customer_name",
            "customer_phone",
            "place_area_feddan",
            "area_number",
            "building",
            "unit_number",
            "floor_number",
            "employee_name",
            "case_status_name",
            "installment_duration_years",
            "remaining_installments",
            "installment_amount",
            "installment_type",
            "unit_sale_amount",
            "seller_commission_amount",
            "buyer_commission_amount",
            "buyer_name",
            "buyer_phone_number",
            "notes",
        ),
        fields=(
            # --- بيانات العميل (تُجلب من العميل المختار) ---
            FieldSpec("customer_phone", "رقم التليفون", virtual=True,
                      group="بيانات العميل", combo_source="customers_phone"),
            FieldSpec("customer_name", "إسم العميل", virtual=True,
                      group="بيانات العميل", combo_source="customers_name"),
            FieldSpec("customer_id", "كود العميل", "int", readonly=True, group="بيانات العميل"),
            FieldSpec("place_area_feddan", "المنطقة بالفدان", "int", readonly=True,
                      virtual=True, group="بيانات العميل"),
            FieldSpec("area_number", "رقم المنطقة", readonly=True, virtual=True, group="بيانات العميل"),
            FieldSpec("building", "عمارة", readonly=True, virtual=True, group="بيانات العميل"),
            FieldSpec("unit_number", "وحدة", readonly=True, virtual=True, group="بيانات العميل"),
            FieldSpec("floor_number", "الطابق", readonly=True, virtual=True, group="بيانات العميل"),
            # --- بيانات المتابعة والحالة والمتبقي ---
            FieldSpec("daily_followup_id", "كود المتابعة", "int", readonly=True,
                      group="بيانات المتابعة والحالة"),
            FieldSpec("follow_up_date", "تاريخ المتابعة", "date", group="بيانات المتابعة والحالة"),
            FieldSpec("employee_id", "اسم الموظف", "int",
                      group="بيانات المتابعة والحالة", combo_source="employees"),
            FieldSpec("case_status_id", "الحالة", "int",
                      group="بيانات المتابعة والحالة", combo_source="case_statuses"),
            FieldSpec("installment_duration_years", "مدة الأقساط بالسنين", "float",
                      group="بيانات المتابعة والحالة"),
            FieldSpec("remaining_installments", "متبقي الأقساط", "float",
                      group="بيانات المتابعة والحالة"),
            FieldSpec("installment_amount", "قيمة القسط", "float", group="بيانات المتابعة والحالة"),
            FieldSpec("installment_type", "نوع القسط", group="بيانات المتابعة والحالة"),
            FieldSpec("unit_sale_amount", "قيمة بيع الوحدة", "float", group="بيانات المتابعة والحالة"),
            FieldSpec("seller_commission_amount", "عمولة البائع", "float",
                      group="بيانات المتابعة والحالة"),
            FieldSpec("buyer_commission_amount", "عمولة المشتري", "float",
                      group="بيانات المتابعة والحالة"),
            FieldSpec("buyer_name", "اسم المشتري", group="بيانات المتابعة والحالة"),
            FieldSpec("buyer_phone_number", "تليفون المشتري", group="بيانات المتابعة والحالة"),
            FieldSpec("notes", "ملاحظات", group="بيانات المتابعة والحالة"),
            FieldSpec("contact_count", "عدد مرات الاتصال", "int", hidden_on_form=True),
        ),
    ),
    "places": TableSpec(
        key="places",
        table_name="places",
        title="إدارة المناطق",
        icon_text="P",
        primary_key="place_id",
        search_columns=("place_number",),
        list_columns=("place_id", "place_number"),
        fields=(
            FieldSpec("place_id", "كود المنطقة", "int", readonly=True),
            FieldSpec("place_number", "رقم / اسم المنطقة", required=True),
        ),
    ),
    "case_statuses": TableSpec(
        key="case_statuses",
        table_name="case_statuses",
        title="إدارة الحالات",
        icon_text="S",
        primary_key="case_status_id",
        search_columns=("case_status_name",),
        list_columns=("case_status_id", "case_status_name"),
        fields=(
            FieldSpec("case_status_id", "كود الحالة", "int", readonly=True),
            FieldSpec("case_status_name", "اسم الحالة", required=True),
        ),
    ),
    "receipt_vouchers": TableSpec(
        key="receipt_vouchers",
        table_name="receipt_vouchers",
        title="سندات قبض العملاء",
        icon_text="س",
        primary_key="id",
        # Searchable by voucher number, customer name (via the customers JOIN in
        # _list_receipt_vouchers), or voucher date — partial (ILIKE) match.
        search_columns=("voucher_number", "customer_name", "voucher_date"),
        # The grid shows number + date + customer name + amount; the id is still
        # fetched (prepended by the list query) for row selection. Same shape and
        # order as the supplier payment vouchers.
        list_columns=("voucher_number", "voucher_date", "customer_name", "amount"),
        fields=(
            # id is auto-assigned by PostgreSQL IDENTITY — hidden from the form,
            # still fetched for selection.
            FieldSpec("id", "الكود", "int", readonly=True, hidden_on_form=True),
            # رقم السند is fully automatic: the DB DEFAULT assigns the next PA-<n>
            # atomically. Shown read-only, never typed (like the supplier voucher).
            FieldSpec("voucher_number", "رقم السند", readonly=True),
            FieldSpec("voucher_date", "التاريخ", "date", required=True),
            # اسم العميل: chosen from a dropdown of registered customers; the stored
            # value is the customer_id foreign key, never the name.
            FieldSpec("customer_id", "اسم العميل", "int", required=True),
            FieldSpec("amount", "المبلغ", "float", required=True),
            FieldSpec("description", "البيان"),
            # الشركة / نوع الدفع stay as (now-optional) columns in the table so no
            # existing data is lost and the printout can still read a stored value,
            # but they are no longer part of the form/spec.
            # Grid-only column from the customers JOIN (label for the list header);
            # never an editor and never written to the table.
            FieldSpec("customer_name", "اسم العميل", virtual=True, hidden_on_form=True),
        ),
    ),
    "supplier_payment_vouchers": TableSpec(
        key="supplier_payment_vouchers",
        table_name="supplier_payment_vouchers",
        title="سندات صرف الموردين",
        icon_text="ص",
        primary_key="id",
        # Searchable by voucher number, supplier name (via the suppliers JOIN in
        # _list_supplier_payment_vouchers), or voucher date — partial ILIKE match.
        search_columns=("voucher_number", "supplier_name", "voucher_date"),
        # The grid shows number + date + supplier name + amount; the id is still
        # fetched (prepended by the list query) for row selection.
        list_columns=("voucher_number", "voucher_date", "supplier_name", "amount"),
        fields=(
            # id is auto-assigned by the sequence — hidden from the form (there is
            # no user-facing numeric code), but still fetched for selection.
            FieldSpec("id", "الكود", "int", readonly=True, hidden_on_form=True),
            # رقم السند is fully automatic: the DB DEFAULT assigns the next
            # ``Paid - Sub-<n>`` atomically. Shown read-only, never typed.
            FieldSpec("voucher_number", "رقم السند", readonly=True),
            FieldSpec("voucher_date", "التاريخ", "date", required=True),
            # اسم المورد: chosen from a dropdown of registered suppliers; the
            # stored value is the supplier_id foreign key, never the name.
            FieldSpec("supplier_id", "اسم المورد", "int", required=True),
            FieldSpec("amount", "المبلغ", "float", required=True),
            FieldSpec("description", "البيان"),
            # Grid-only column from the suppliers JOIN (label for the list header);
            # never an editor and never written to the table.
            FieldSpec("supplier_name", "اسم المورد", virtual=True, hidden_on_form=True),
        ),
    ),
    "worker_payment_vouchers": TableSpec(
        key="worker_payment_vouchers",
        table_name="worker_payment_vouchers",
        title="سندات صرف العمال",
        icon_text="ع",
        primary_key="id",
        # Searchable by voucher number, worker name (via the workers JOIN in
        # _list_worker_payment_vouchers), or voucher date — partial ILIKE match.
        search_columns=("voucher_number", "worker_name", "voucher_date"),
        # The grid shows number + date + worker name + amount; the id is still
        # fetched (prepended by the list query) for row selection.
        list_columns=("voucher_number", "voucher_date", "worker_name", "amount"),
        fields=(
            # id is auto-assigned by the sequence — hidden from the form (there is
            # no user-facing numeric code), but still fetched for selection.
            FieldSpec("id", "الكود", "int", readonly=True, hidden_on_form=True),
            # رقم السند is fully automatic: the DB DEFAULT assigns the next
            # ``Paid - Wrk-<n>`` atomically. Shown read-only, never typed.
            FieldSpec("voucher_number", "رقم السند", readonly=True),
            FieldSpec("voucher_date", "التاريخ", "date", required=True),
            # اسم العامل: chosen from a dropdown of registered workers; the stored
            # value is the worker_id foreign key, never the name.
            FieldSpec("worker_id", "اسم العامل", "int", required=True),
            FieldSpec("amount", "المبلغ", "float", required=True),
            FieldSpec("description", "البيان"),
            # Grid-only column from the workers JOIN (label for the list header);
            # never an editor and never written to the table.
            FieldSpec("worker_name", "اسم العامل", virtual=True, hidden_on_form=True),
        ),
    ),
    "worker_daily": TableSpec(
        key="worker_daily",
        table_name="worker_daily",
        title="يومية العمال",
        icon_text="ع",
        primary_key="id",
        # Searchable by worker name (via the workers JOIN in _list_worker_daily),
        # statement, or date — partial (ILIKE) match.
        search_columns=("worker_name", "statement", "movement_date"),
        # The grid shows movement no. + date + worker + salary + cash + balance;
        # the id is prepended by the list query for row selection.
        list_columns=("id", "movement_date", "worker_name", "daily_salary", "cash", "balance"),
        fields=(
            # رقم الحركة: auto id from the sequence — shown read-only (visible on
            # the form, unlike the vouchers where the code is hidden).
            FieldSpec("id", "رقم الحركة", "int", readonly=True),
            FieldSpec("movement_date", "التاريخ", "date", required=True),
            # اسم العامل: dropdown of registered workers; the stored value is the
            # worker_id foreign key, never the name.
            FieldSpec("worker_id", "اسم العامل", "int", required=True),
            FieldSpec("statement", "البيان"),
            # Entered by hand.
            FieldSpec("number_of_days", "عدد الأيام", "float"),
            FieldSpec("daily_wage", "أجر اليوم", "float"),
            # الراتب اليومي = عدد الأيام × أجر اليوم — a DB generated column. Virtual
            # so it is never sent on INSERT/UPDATE; the screen shows a live preview
            # and the grid shows the stored value.
            FieldSpec("daily_salary", "الراتب اليومي", "float", readonly=True, virtual=True),
            FieldSpec("cash", "نقديات", "float"),
            # الرصيد = الراتب اليومي − النقديات — also a DB generated column (virtual,
            # live preview + stored grid value).
            FieldSpec("balance", "الرصيد", "float", readonly=True, virtual=True),
            # Grid-only column from the workers JOIN (label for the list header);
            # never an editor and never written to the table.
            FieldSpec("worker_name", "اسم العامل", virtual=True, hidden_on_form=True),
        ),
    ),
    # شاشة المقاولين — النموذج 4 «بطاقة هوية المقاول» (2026-09-24). The code is
    # text like «A-H/CD-1001»: the screen suggests the next one, the user may
    # change it. الضرائب والتأمينات والخصومات are amounts, not percentages. The
    # screen lays every field out itself in three cards; ``group`` names the card.
    "contractors": TableSpec(
        key="contractors",
        table_name="contractors",
        title="إدارة المقاولين",
        icon_text="👷",
        primary_key="contractor_id",
        search_columns=("contractor_code", "contractor_name", "registration_no", "phone",
                        "contractor_type"),
        list_columns=("contractor_code", "contractor_name"),
        fields=(
            FieldSpec("contractor_code", "كود المقاول", required=True, group="البيانات الأساسية"),
            FieldSpec("contractor_name", "اسم المقاول", required=True, group="البيانات الأساسية"),
            FieldSpec("contractor_type", "نوع المقاول", required=True,
                      choices=CONTRACTOR_TYPES, group="البيانات الأساسية"),
            FieldSpec("registration_no", "رقم التسجيل", group="البيانات الأساسية"),
            FieldSpec("phone", "رقم التلفون", group="الاتصال والحساب"),
            FieldSpec("address", "العنوان", group="الاتصال والحساب"),
            FieldSpec("current_balance", "الرصيد الجاري", "float", group="الاتصال والحساب"),
            FieldSpec("vat_amount", "ضرائب القيمة المضافة", "float",
                      group="الضرائب والتأمينات والخصومات"),
            FieldSpec("withholding_tax_amount", "ضرائب الخصم والإضافة", "float",
                      group="الضرائب والتأمينات والخصومات"),
            FieldSpec("social_insurance_amount", "التأمينات الاجتماعية", "float",
                      group="الضرائب والتأمينات والخصومات"),
            FieldSpec("works_insurance_amount", "تأمين الأعمال", "float",
                      group="الضرائب والتأمينات والخصومات"),
            FieldSpec("other_deductions_amount", "الخصومات الأخرى", "float",
                      group="الضرائب والتأمينات والخصومات"),
        ),
        lookup_columns=("contractor_code", "contractor_name", "contractor_type",
                        "registration_no", "phone", "current_balance"),
    ),
}


class ReviewDataService:
    """CRUD operations for the review UI."""

    CUSTOMER_LOOKUP_LIMIT = 100

    def __init__(self) -> None:
        self.settings = get_settings()
        self.database_url = build_database_url(self.settings).replace("postgresql+psycopg://", "postgresql://")
        # A single long-lived connection is reused for every query. Opening a
        # fresh PostgreSQL connection per query (TCP + auth handshake) was the
        # main cause of the lag when a screen was built for the first time.
        self._connection: psycopg.Connection | None = None

    def _ensure_connection(self) -> psycopg.Connection:
        if self._connection is None or self._connection.closed:
            self._connection = psycopg.connect(
                self.database_url,
                row_factory=dict_row,
                autocommit=True,
                **runtime_connect_kwargs(),
            )
        return self._connection

    @contextmanager
    def connect(self):
        """Yield the shared connection.

        Kept as a context manager so existing ``with self.connect() as conn:``
        call sites are unchanged, but it reuses one persistent (autocommit)
        connection instead of opening/closing one per call. Exiting the block
        does NOT close the connection. If the connection has gone stale it is
        transparently reopened on the next call.
        """
        try:
            yield self._ensure_connection()
        except psycopg.OperationalError:
            # Drop the dead connection so the next call reconnects.
            self._connection = None
            raise

    def list_records(self, spec: TableSpec, keyword: str = "", limit: int = 500) -> list[dict[str, Any]]:
        columns = [spec.primary_key, *[c for c in spec.list_columns if c != spec.primary_key]]
        return self.list_records_with_columns(spec, columns, keyword, limit)

    def list_records_with_columns(
        self,
        spec: TableSpec,
        columns: list[str] | tuple[str, ...],
        keyword: str = "",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if spec.key == "daily_followups":
            return self._list_daily_followups(columns, keyword, limit)
        if spec.key == "receipt_vouchers":
            return self._list_receipt_vouchers(columns, keyword, limit)
        if spec.key == "supplier_payment_vouchers":
            return self._list_supplier_payment_vouchers(columns, keyword, limit)
        if spec.key == "worker_payment_vouchers":
            return self._list_worker_payment_vouchers(columns, keyword, limit)
        if spec.key == "worker_daily":
            return self._list_worker_daily(columns, keyword, limit)
        columns = list(dict.fromkeys([spec.primary_key, *[c for c in columns if c != spec.primary_key]]))
        query = SQL("SELECT {cols} FROM {table}").format(
            cols=SQL(", ").join(Identifier(c) for c in columns),
            table=Identifier(spec.table_name),
        )
        params: list[Any] = []
        if keyword.strip():
            like_parts = []
            for column in spec.search_columns:
                like_parts.append(SQL("CAST({col} AS text) ILIKE %s").format(col=Identifier(column)))
                params.append(f"%{keyword.strip()}%")
            query += SQL(" WHERE ") + SQL(" OR ").join(like_parts)
        query += SQL(" ORDER BY {pk} ASC LIMIT %s").format(pk=Identifier(spec.primary_key))
        params.append(limit)
        with self.connect() as conn:
            return list(conn.execute(query, params))

    def list_places_for_selection(self) -> list[dict[str, Any]]:
        query = SQL(
            "SELECT place_id, place_number FROM {table} ORDER BY place_id ASC"
        ).format(table=Identifier("places"))
        with self.connect() as conn:
            return list(conn.execute(query))

    # Every selectable column on the daily-followup screen, mapped to its SQL
    # expression. Used both for the SELECT list and for the all-columns search.
    _DAILY_FOLLOWUP_SELECT = (
        ("daily_followup_id", "d.daily_followup_id"),
        ("follow_up_date", "d.follow_up_date"),
        ("customer_id", "d.customer_id"),
        ("customer_name", "c.customer_name"),
        ("customer_phone", "c.phone_number"),
        ("place_area_feddan", "c.place_area_feddan"),
        ("area_number", "c.area_number"),
        ("building", "c.building"),
        ("unit_number", "c.unit_number"),
        ("floor_number", "c.floor_number"),
        ("employee_name", "e.employee_name"),
        ("case_status_name", "cs.case_status_name"),
        ("installment_duration_years", "d.installment_duration_years"),
        ("remaining_installments", "d.remaining_installments"),
        ("installment_amount", "d.installment_amount"),
        ("installment_type", "d.installment_type"),
        ("unit_sale_amount", "d.unit_sale_amount"),
        ("seller_commission_amount", "d.seller_commission_amount"),
        ("buyer_commission_amount", "d.buyer_commission_amount"),
        ("buyer_name", "d.buyer_name"),
        ("buyer_phone_number", "d.buyer_phone_number"),
        ("notes", "d.notes"),
    )

    _DAILY_FOLLOWUP_SEARCH = (
        ("daily_followup_id", "d.daily_followup_id"),
        ("customer_id", "d.customer_id"),
        ("customer_name", "c.customer_name"),
        ("customer_phone", "c.phone_number"),
        ("follow_up_date", "d.follow_up_date"),
        ("case_status_name", "cs.case_status_name"),
        ("notes", "d.notes"),
    )

    def _list_daily_followups(
        self,
        columns: list[str] | tuple[str, ...],
        keyword: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        select_map = dict(self._DAILY_FOLLOWUP_SELECT)
        requested = list(dict.fromkeys(columns))
        selected = [(alias, select_map[alias]) for alias in requested if alias in select_map]
        if not selected:
            selected = [("daily_followup_id", select_map["daily_followup_id"])]
        select_list = SQL(", ").join(
            SQL("{expr} AS {alias}").format(expr=SQL(expr), alias=Identifier(alias))
            for alias, expr in selected
        )
        query = (
            SQL("SELECT ")
            + select_list
            + SQL(
                " FROM daily_followups d "
                "LEFT JOIN customers c ON c.customer_id = d.customer_id "
                "LEFT JOIN case_statuses cs ON cs.case_status_id = d.case_status_id "
                "LEFT JOIN employees e ON e.employee_id = d.employee_id"
            )
        )
        params: list[Any] = []
        if keyword.strip():
            like = f"%{keyword.strip()}%"
            conditions = SQL(" OR ").join(
                SQL("CAST({expr} AS text) ILIKE %s").format(expr=SQL(expr))
                for _alias, expr in self._DAILY_FOLLOWUP_SEARCH
            )
            query += SQL(" WHERE ") + conditions
            params.extend([like] * len(self._DAILY_FOLLOWUP_SEARCH))
        query += SQL(" ORDER BY d.daily_followup_id ASC LIMIT %s")
        params.append(limit)
        with self.connect() as conn:
            return list(conn.execute(query, params))

    # Every selectable column on the receipt-vouchers screen, mapped to its SQL
    # expression (customer_name comes from the customers JOIN). Used both for
    # the SELECT list and for the search below — same pattern as daily_followups.
    _RECEIPT_VOUCHER_SELECT = (
        ("id", "rv.id"),
        ("voucher_number", "rv.voucher_number"),
        ("voucher_date", "rv.voucher_date"),
        ("customer_id", "rv.customer_id"),
        ("customer_name", "c.customer_name"),
        ("company_id", "rv.company_id"),
        ("payment_type", "rv.payment_type"),
        ("amount", "rv.amount"),
        ("description", "rv.description"),
    )

    # The requested search entries: voucher number, customer name, or date.
    _RECEIPT_VOUCHER_SEARCH = (
        ("voucher_number", "rv.voucher_number"),
        ("customer_name", "c.customer_name"),
        ("voucher_date", "rv.voucher_date"),
    )

    def _list_receipt_vouchers(
        self,
        columns: list[str] | tuple[str, ...],
        keyword: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        select_map = dict(self._RECEIPT_VOUCHER_SELECT)
        requested = list(dict.fromkeys(columns))
        selected = [(alias, select_map[alias]) for alias in requested if alias in select_map]
        if not selected:
            selected = [("id", select_map["id"])]
        select_list = SQL(", ").join(
            SQL("{expr} AS {alias}").format(expr=SQL(expr), alias=Identifier(alias))
            for alias, expr in selected
        )
        query = (
            SQL("SELECT ")
            + select_list
            + SQL(
                " FROM receipt_vouchers rv "
                "LEFT JOIN customers c ON c.customer_id = rv.customer_id"
            )
        )
        params: list[Any] = []
        if keyword.strip():
            like = f"%{keyword.strip()}%"
            conditions = SQL(" OR ").join(
                SQL("CAST({expr} AS text) ILIKE %s").format(expr=SQL(expr))
                for _alias, expr in self._RECEIPT_VOUCHER_SEARCH
            )
            query += SQL(" WHERE ") + conditions
            params.extend([like] * len(self._RECEIPT_VOUCHER_SEARCH))
        query += SQL(" ORDER BY rv.id ASC LIMIT %s")
        params.append(limit)
        with self.connect() as conn:
            return list(conn.execute(query, params))

    # Every selectable column on the supplier-payment-voucher screen, mapped to
    # its SQL expression (supplier_name comes from the suppliers JOIN). Same
    # pattern as _RECEIPT_VOUCHER_SELECT.
    _SUPPLIER_VOUCHER_SELECT = (
        ("id", "spv.id"),
        ("voucher_number", "spv.voucher_number"),
        ("voucher_date", "spv.voucher_date"),
        ("supplier_id", "spv.supplier_id"),
        ("supplier_name", "s.supplier_name"),
        ("amount", "spv.amount"),
        ("description", "spv.description"),
    )

    # Search entries: voucher number, supplier name, or date.
    _SUPPLIER_VOUCHER_SEARCH = (
        ("voucher_number", "spv.voucher_number"),
        ("supplier_name", "s.supplier_name"),
        ("voucher_date", "spv.voucher_date"),
    )

    def _list_supplier_payment_vouchers(
        self,
        columns: list[str] | tuple[str, ...],
        keyword: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        select_map = dict(self._SUPPLIER_VOUCHER_SELECT)
        requested = list(dict.fromkeys(columns))
        selected = [(alias, select_map[alias]) for alias in requested if alias in select_map]
        if not selected:
            selected = [("id", select_map["id"])]
        select_list = SQL(", ").join(
            SQL("{expr} AS {alias}").format(expr=SQL(expr), alias=Identifier(alias))
            for alias, expr in selected
        )
        query = (
            SQL("SELECT ")
            + select_list
            + SQL(
                " FROM supplier_payment_vouchers spv "
                "LEFT JOIN suppliers s ON s.supplier_id = spv.supplier_id"
            )
        )
        params: list[Any] = []
        if keyword.strip():
            like = f"%{keyword.strip()}%"
            conditions = SQL(" OR ").join(
                SQL("CAST({expr} AS text) ILIKE %s").format(expr=SQL(expr))
                for _alias, expr in self._SUPPLIER_VOUCHER_SEARCH
            )
            query += SQL(" WHERE ") + conditions
            params.extend([like] * len(self._SUPPLIER_VOUCHER_SEARCH))
        query += SQL(" ORDER BY spv.id ASC LIMIT %s")
        params.append(limit)
        with self.connect() as conn:
            return list(conn.execute(query, params))

    def list_suppliers_for_selection(self) -> list[dict[str, Any]]:
        """Suppliers for the payment-voucher dropdown (id + name), by name."""
        query = SQL(
            "SELECT supplier_id, supplier_name FROM suppliers "
            "ORDER BY supplier_name NULLS LAST, supplier_id ASC"
        )
        with self.connect() as conn:
            return list(conn.execute(query))

    # Every selectable column on the worker-payment-voucher screen, mapped to its
    # SQL expression (worker_name comes from the workers JOIN). Same pattern as
    # _SUPPLIER_VOUCHER_SELECT.
    _WORKER_VOUCHER_SELECT = (
        ("id", "wpv.id"),
        ("voucher_number", "wpv.voucher_number"),
        ("voucher_date", "wpv.voucher_date"),
        ("worker_id", "wpv.worker_id"),
        ("worker_name", "w.worker_name"),
        ("amount", "wpv.amount"),
        ("description", "wpv.description"),
    )

    # Search entries: voucher number, worker name, or date.
    _WORKER_VOUCHER_SEARCH = (
        ("voucher_number", "wpv.voucher_number"),
        ("worker_name", "w.worker_name"),
        ("voucher_date", "wpv.voucher_date"),
    )

    def _list_worker_payment_vouchers(
        self,
        columns: list[str] | tuple[str, ...],
        keyword: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        select_map = dict(self._WORKER_VOUCHER_SELECT)
        requested = list(dict.fromkeys(columns))
        selected = [(alias, select_map[alias]) for alias in requested if alias in select_map]
        if not selected:
            selected = [("id", select_map["id"])]
        select_list = SQL(", ").join(
            SQL("{expr} AS {alias}").format(expr=SQL(expr), alias=Identifier(alias))
            for alias, expr in selected
        )
        query = (
            SQL("SELECT ")
            + select_list
            + SQL(
                " FROM worker_payment_vouchers wpv "
                "LEFT JOIN workers w ON w.worker_id = wpv.worker_id"
            )
        )
        params: list[Any] = []
        if keyword.strip():
            like = f"%{keyword.strip()}%"
            conditions = SQL(" OR ").join(
                SQL("CAST({expr} AS text) ILIKE %s").format(expr=SQL(expr))
                for _alias, expr in self._WORKER_VOUCHER_SEARCH
            )
            query += SQL(" WHERE ") + conditions
            params.extend([like] * len(self._WORKER_VOUCHER_SEARCH))
        query += SQL(" ORDER BY wpv.id ASC LIMIT %s")
        params.append(limit)
        with self.connect() as conn:
            return list(conn.execute(query, params))

    # Every selectable column on the worker-daily screen, mapped to its SQL
    # expression (worker_name comes from the workers JOIN). Same pattern as the
    # voucher list queries.
    _WORKER_DAILY_SELECT = (
        ("id", "wd.id"),
        ("movement_date", "wd.movement_date"),
        ("worker_id", "wd.worker_id"),
        ("worker_name", "w.worker_name"),
        ("statement", "wd.statement"),
        ("number_of_days", "wd.number_of_days"),
        ("daily_wage", "wd.daily_wage"),
        ("daily_salary", "wd.daily_salary"),
        ("cash", "wd.cash"),
        ("balance", "wd.balance"),
    )

    # Search entries: worker name, statement, or date.
    _WORKER_DAILY_SEARCH = (
        ("worker_name", "w.worker_name"),
        ("statement", "wd.statement"),
        ("movement_date", "wd.movement_date"),
    )

    def _list_worker_daily(
        self,
        columns: list[str] | tuple[str, ...],
        keyword: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        select_map = dict(self._WORKER_DAILY_SELECT)
        requested = list(dict.fromkeys(columns))
        selected = [(alias, select_map[alias]) for alias in requested if alias in select_map]
        if not selected:
            selected = [("id", select_map["id"])]
        select_list = SQL(", ").join(
            SQL("{expr} AS {alias}").format(expr=SQL(expr), alias=Identifier(alias))
            for alias, expr in selected
        )
        query = (
            SQL("SELECT ")
            + select_list
            + SQL(
                " FROM worker_daily wd "
                "LEFT JOIN workers w ON w.worker_id = wd.worker_id"
            )
        )
        params: list[Any] = []
        if keyword.strip():
            like = f"%{keyword.strip()}%"
            conditions = SQL(" OR ").join(
                SQL("CAST({expr} AS text) ILIKE %s").format(expr=SQL(expr))
                for _alias, expr in self._WORKER_DAILY_SEARCH
            )
            query += SQL(" WHERE ") + conditions
            params.extend([like] * len(self._WORKER_DAILY_SEARCH))
        query += SQL(" ORDER BY wd.id ASC LIMIT %s")
        params.append(limit)
        with self.connect() as conn:
            return list(conn.execute(query, params))

    def list_workers_for_selection(self) -> list[dict[str, Any]]:
        """Workers for the worker-daily dropdown (id + name), by name."""
        query = SQL(
            "SELECT worker_id, worker_name FROM workers "
            "ORDER BY worker_name NULLS LAST, worker_id ASC"
        )
        with self.connect() as conn:
            return list(conn.execute(query))

    def list_companies_for_selection(self) -> list[dict[str, Any]]:
        query = SQL("SELECT id, name_ar FROM companies ORDER BY name_ar ASC")
        with self.connect() as conn:
            return list(conn.execute(query))

    def get_company_details(self, company_id: Any) -> dict[str, Any] | None:
        """Full seller-header fields for a company (name / CR / VAT / address).

        Used by the receipt-voucher printout so the ``سند قبض`` header carries
        the same company identity (name, commercial registration, VAT number,
        address, and embedded logo) as the Saudi tax invoice.
        """
        if company_id in (None, ""):
            return None
        query = SQL(
            "SELECT id, name_ar, name_en, commercial_registration, vat_number, "
            "address_ar, address_en, logo, logo_mime FROM companies WHERE id = %s"
        )
        with self.connect() as conn:
            return conn.execute(query, [company_id]).fetchone()

    def get_company_logo(self, company_id: Any) -> dict[str, Any] | None:
        """Return ``{"logo": bytes, "logo_mime": str}`` for a company, or None.

        Fetched on its own (not via :meth:`get_record`) so the potentially large
        image blob is only ever loaded when a document is actually printed or the
        companies screen shows the logo preview.
        """
        if company_id in (None, ""):
            return None
        query = SQL("SELECT logo, logo_mime FROM companies WHERE id = %s")
        with self.connect() as conn:
            return conn.execute(query, [company_id]).fetchone()

    def set_company_logo(
        self, company_id: Any, data: bytes | None, mime: str | None
    ) -> None:
        """Store (or clear, when ``data`` is None) a company's embedded logo."""
        if company_id in (None, ""):
            return
        query = SQL("UPDATE companies SET logo = %s, logo_mime = %s WHERE id = %s")
        with self.connect() as conn:
            conn.execute(query, [data, (mime if data else None), company_id])

    def get_company_stamp(self, company_id: Any) -> dict[str, Any] | None:
        """Return ``{"stamp": bytes, "stamp_mime": str}`` for a company, or None.

        The twin of :meth:`get_company_logo`: the stamp (ختم الشركة) is fetched on
        its own so the image blob is only loaded when the companies screen shows
        the stamp preview or a document is printed with the stamp enabled.
        """
        if company_id in (None, ""):
            return None
        query = SQL("SELECT stamp, stamp_mime FROM companies WHERE id = %s")
        with self.connect() as conn:
            return conn.execute(query, [company_id]).fetchone()

    def set_company_stamp(
        self, company_id: Any, data: bytes | None, mime: str | None
    ) -> None:
        """Store (or clear, when ``data`` is None) a company's embedded stamp."""
        if company_id in (None, ""):
            return
        query = SQL("UPDATE companies SET stamp = %s, stamp_mime = %s WHERE id = %s")
        with self.connect() as conn:
            conn.execute(query, [data, (mime if data else None), company_id])

    def find_customer_by_phone(self, phone: Any) -> dict[str, Any] | None:
        text = str(phone).strip()
        if not text:
            return None
        query = SQL(
            "SELECT customer_id, customer_name, phone_number FROM customers "
            "WHERE CAST(phone_number AS text) = %s ORDER BY customer_id ASC LIMIT 1"
        )
        with self.connect() as conn:
            return conn.execute(query, [text]).fetchone()

    def find_customer_by_name(self, name: Any) -> dict[str, Any] | None:
        text = str(name).strip()
        if not text:
            return None
        query = SQL(
            "SELECT customer_id, customer_name, phone_number FROM customers "
            "WHERE customer_name ILIKE %s ORDER BY customer_id ASC LIMIT 1"
        )
        with self.connect() as conn:
            return conn.execute(query, [text]).fetchone()

    def list_employees_for_selection(self) -> list[dict[str, Any]]:
        query = SQL(
            "SELECT employee_id, employee_name FROM employees ORDER BY employee_name ASC"
        )
        with self.connect() as conn:
            return list(conn.execute(query))

    def list_case_statuses_for_selection(self) -> list[dict[str, Any]]:
        query = SQL(
            "SELECT case_status_id, case_status_name FROM case_statuses ORDER BY case_status_name ASC"
        )
        with self.connect() as conn:
            return list(conn.execute(query))

    def find_case_status_by_name(self, name: Any) -> dict[str, Any] | None:
        """Resolve a case-status row by its (case-insensitive) name.

        Used by the Excel importer to turn the visible ``الحالة`` text back into
        a ``case_status_id`` foreign key.
        """
        text = str(name).strip()
        if not text:
            return None
        query = SQL(
            "SELECT case_status_id, case_status_name FROM case_statuses "
            "WHERE case_status_name ILIKE %s ORDER BY case_status_id ASC LIMIT 1"
        )
        with self.connect() as conn:
            return conn.execute(query, [text]).fetchone()

    def fetch_column_values(
        self, table_name: str, columns: list[str] | tuple[str, ...]
    ) -> list[dict[str, Any]]:
        """Return every row of ``table_name`` projected to ``columns``.

        Used by the Excel importer to load the existing values that make up a
        screen's duplicate signature (e.g. all customer phone numbers), so it can
        reject rows that would clash with data already in the database.
        """
        cols = list(dict.fromkeys(columns))
        query = SQL("SELECT {cols} FROM {table}").format(
            cols=SQL(", ").join(Identifier(c) for c in cols),
            table=Identifier(table_name),
        )
        with self.connect() as conn:
            return list(conn.execute(query))

    def list_customers_for_selection(self) -> list[dict[str, Any]]:
        query = SQL(
            "SELECT customer_id, customer_name, phone_number FROM customers ORDER BY customer_id ASC"
        )
        with self.connect() as conn:
            return list(conn.execute(query))

    # -- expenses dashboard -------------------------------------------------

    def list_expense_types(self) -> list[str]:
        """Distinct non-blank expense types already stored, for the dropdown.

        This is what makes نوع المصروف "learn": every saved type shows up here on
        the next load, with no separate lookup table.
        """
        query = SQL(
            "SELECT DISTINCT btrim(expense_type) AS expense_type FROM expenses "
            "WHERE expense_type IS NOT NULL AND btrim(expense_type) <> '' "
            "ORDER BY expense_type ASC"
        )
        with self.connect() as conn:
            return [row["expense_type"] for row in conn.execute(query)]

    def expenses_total(self) -> Any:
        """Sum of every expense amount — the ``إجمالي المصروفات`` card."""
        with self.connect() as conn:
            row = conn.execute(
                SQL("SELECT COALESCE(SUM(amount), 0) AS total FROM expenses")
            ).fetchone()
            return (row["total"] if row else 0) or 0

    def expenses_by_type(self) -> list[dict[str, Any]]:
        """Total amount per expense type, biggest first — feeds the charts."""
        query = SQL(
            "SELECT COALESCE(NULLIF(btrim(expense_type), ''), 'غير محدد') AS expense_type, "
            "SUM(amount) AS total FROM expenses GROUP BY 1 ORDER BY total DESC, expense_type ASC"
        )
        with self.connect() as conn:
            return list(conn.execute(query))

    def top_expense_type(self) -> dict[str, Any] | None:
        """The single expense type with the highest total — ``أكبر نوع``."""
        rows = self.expenses_by_type()
        return rows[0] if rows else None

    def search_expenses(
        self,
        date_from: Any = None,
        date_to: Any = None,
        expense_type: Any = None,
        limit: int | None = 500,
    ) -> list[dict[str, Any]]:
        """Rows for the expenses search popup, newest first.

        With no date filter the caller passes ``limit=500`` to show only the
        latest 500. When a date range is given the caller passes ``limit=None``
        so every matching (possibly old) row shows. An ``expense_type`` narrows
        to one exact type. All filters are optional.
        """
        query = SQL(
            "SELECT id, expense_date, expense_type, amount, statement FROM expenses"
        )
        conditions: list[Any] = []
        params: list[Any] = []
        if date_from:
            conditions.append(SQL("expense_date >= %s"))
            params.append(date_from)
        if date_to:
            conditions.append(SQL("expense_date <= %s"))
            params.append(date_to)
        if expense_type is not None and str(expense_type).strip():
            conditions.append(SQL("btrim(expense_type) = %s"))
            params.append(str(expense_type).strip())
        if conditions:
            query = query + SQL(" WHERE ") + SQL(" AND ").join(conditions)
        query = query + SQL(" ORDER BY expense_date DESC, id DESC")
        if limit is not None:
            query = query + SQL(" LIMIT %s")
            params.append(int(limit))
        with self.connect() as conn:
            return list(conn.execute(query, params))

    # -- treasury deposits dashboard (money-in to the cashbox) --------------

    def treasury_total(self) -> Any:
        """Sum of every treasury deposit — the ``إجمالي المبلغ`` card."""
        with self.connect() as conn:
            row = conn.execute(
                SQL("SELECT COALESCE(SUM(amount), 0) AS total FROM treasury_deposits")
            ).fetchone()
            return (row["total"] if row else 0) or 0

    def treasury_top_date(self) -> dict[str, Any] | None:
        """The single date whose deposits sum highest — ``أعلى تاريخ دخل فيه مبلغ``.

        Returns keys ``movement_date`` and ``total`` (or ``None`` when empty).
        """
        query = SQL(
            "SELECT movement_date, SUM(amount) AS total "
            "FROM treasury_deposits "
            "GROUP BY movement_date "
            "ORDER BY total DESC, movement_date DESC "
            "LIMIT 1"
        )
        with self.connect() as conn:
            return conn.execute(query).fetchone()

    def treasury_by_month(self) -> list[dict[str, Any]]:
        """Total deposited per calendar month, biggest first — feeds the charts
        (أعلى الشهور). ``month`` is a ``YYYY-MM`` label; ``total`` is the sum."""
        query = SQL(
            "SELECT to_char(movement_date, 'YYYY-MM') AS month, "
            "SUM(amount) AS total "
            "FROM treasury_deposits "
            "GROUP BY 1 ORDER BY total DESC, month DESC"
        )
        with self.connect() as conn:
            return list(conn.execute(query))

    def search_treasury(
        self,
        date_from: Any = None,
        date_to: Any = None,
        limit: int | None = 500,
    ) -> list[dict[str, Any]]:
        """Rows for the treasury-deposit search popup, newest first.

        Mirrors :meth:`search_expenses`: with no date filter the caller passes
        ``limit=500`` (latest 500 only); a date range passes ``limit=None`` to
        show every match. All filters optional.
        """
        query = SQL(
            "SELECT id, movement_date, amount, statement FROM treasury_deposits"
        )
        conditions: list[Any] = []
        params: list[Any] = []
        if date_from:
            conditions.append(SQL("movement_date >= %s"))
            params.append(date_from)
        if date_to:
            conditions.append(SQL("movement_date <= %s"))
            params.append(date_to)
        if conditions:
            query = query + SQL(" WHERE ") + SQL(" AND ").join(conditions)
        query = query + SQL(" ORDER BY movement_date DESC, id DESC")
        if limit is not None:
            query = query + SQL(" LIMIT %s")
            params.append(int(limit))
        with self.connect() as conn:
            return list(conn.execute(query, params))

    # -- receipt vouchers dashboard (customer money-in) ---------------------

    def receipt_vouchers_total(self) -> Any:
        """Sum of every receipt-voucher amount — the ``إجمالي السندات`` card."""
        with self.connect() as conn:
            row = conn.execute(
                SQL("SELECT COALESCE(SUM(amount), 0) AS total FROM receipt_vouchers")
            ).fetchone()
            return (row["total"] if row else 0) or 0

    def receipt_vouchers_by_customer(self) -> list[dict[str, Any]]:
        """Total amount received per customer, biggest first — feeds the charts
        and the ``أعلى عميل قبضت منه`` card. The customer name comes from the
        customers JOIN (an unknown customer shows as ``غير محدد``)."""
        query = SQL(
            "SELECT COALESCE(NULLIF(btrim(c.customer_name), ''), 'غير محدد') AS customer_name, "
            "SUM(rv.amount) AS total "
            "FROM receipt_vouchers rv "
            "LEFT JOIN customers c ON c.customer_id = rv.customer_id "
            "GROUP BY 1 ORDER BY total DESC, customer_name ASC"
        )
        with self.connect() as conn:
            return list(conn.execute(query))

    def top_receipt_voucher_customer(self) -> dict[str, Any] | None:
        """The single customer with the highest received total — ``أعلى عميل``."""
        rows = self.receipt_vouchers_by_customer()
        return rows[0] if rows else None

    def search_receipt_vouchers(
        self,
        date_from: Any = None,
        date_to: Any = None,
        customer_id: Any = None,
        limit: int | None = 500,
    ) -> list[dict[str, Any]]:
        """Rows for the receipt-voucher search popup, newest first.

        Mirrors :meth:`search_supplier_vouchers`: no date filter -> latest 500;
        a date range -> every match (limit=None). ``customer_id`` narrows to one
        customer. All filters optional.
        """
        query = SQL(
            "SELECT rv.id, rv.voucher_number, rv.voucher_date, "
            "rv.customer_id, c.customer_name, rv.amount, rv.description "
            "FROM receipt_vouchers rv "
            "LEFT JOIN customers c ON c.customer_id = rv.customer_id"
        )
        conditions: list[Any] = []
        params: list[Any] = []
        if date_from:
            conditions.append(SQL("rv.voucher_date >= %s"))
            params.append(date_from)
        if date_to:
            conditions.append(SQL("rv.voucher_date <= %s"))
            params.append(date_to)
        if customer_id not in (None, ""):
            conditions.append(SQL("rv.customer_id = %s"))
            params.append(customer_id)
        if conditions:
            query = query + SQL(" WHERE ") + SQL(" AND ").join(conditions)
        query = query + SQL(" ORDER BY rv.voucher_date DESC, rv.id DESC")
        if limit is not None:
            query = query + SQL(" LIMIT %s")
            params.append(int(limit))
        with self.connect() as conn:
            return list(conn.execute(query, params))

    # -- supplier payment vouchers dashboard --------------------------------

    def supplier_vouchers_total(self) -> Any:
        """Sum of every voucher amount — the ``إجمالي السندات`` card."""
        with self.connect() as conn:
            row = conn.execute(
                SQL("SELECT COALESCE(SUM(amount), 0) AS total FROM supplier_payment_vouchers")
            ).fetchone()
            return (row["total"] if row else 0) or 0

    def supplier_vouchers_by_supplier(self) -> list[dict[str, Any]]:
        """Total amount paid per supplier, biggest first — feeds the charts and
        the ``أعلى مورد صرفت عليه`` card. The supplier name comes from the
        suppliers JOIN (a deleted/unknown supplier shows as ``غير محدد``)."""
        query = SQL(
            "SELECT COALESCE(NULLIF(btrim(s.supplier_name), ''), 'غير محدد') AS supplier_name, "
            "SUM(spv.amount) AS total "
            "FROM supplier_payment_vouchers spv "
            "LEFT JOIN suppliers s ON s.supplier_id = spv.supplier_id "
            "GROUP BY 1 ORDER BY total DESC, supplier_name ASC"
        )
        with self.connect() as conn:
            return list(conn.execute(query))

    def top_supplier_voucher(self) -> dict[str, Any] | None:
        """The single supplier with the highest paid total — ``أعلى مورد``."""
        rows = self.supplier_vouchers_by_supplier()
        return rows[0] if rows else None

    def peek_next_supplier_voucher_number(self) -> str:
        """Advisory next automatic ``Paid - Sub-<n>`` for pre-filling the form.

        Reads the sequence state without consuming it, so it never allocates a
        number; the real value is still assigned atomically by the DB DEFAULT on
        INSERT. Falls back to ``Paid - Sub-01`` if the sequence is unreadable.
        """
        try:
            with self.connect() as conn:
                row = conn.execute(
                    SQL("SELECT last_value, is_called FROM supplier_payment_voucher_number_seq")
                ).fetchone()
            nxt = (row["last_value"] + 1) if row and row["is_called"] else (row["last_value"] if row else 1)
        except Exception:
            nxt = 1
        return f"Paid - Sub-{int(nxt):02d}"

    def search_supplier_vouchers(
        self,
        date_from: Any = None,
        date_to: Any = None,
        supplier_id: Any = None,
        limit: int | None = 500,
    ) -> list[dict[str, Any]]:
        """Rows for the supplier-voucher search popup, newest first.

        Mirrors :meth:`search_expenses`: with no date filter the caller passes
        ``limit=500`` (latest 500 only); a date range passes ``limit=None`` to
        show every match. ``supplier_id`` narrows to one supplier. All optional.
        """
        query = SQL(
            "SELECT spv.id, spv.voucher_number, spv.voucher_date, "
            "spv.supplier_id, s.supplier_name, spv.amount, spv.description "
            "FROM supplier_payment_vouchers spv "
            "LEFT JOIN suppliers s ON s.supplier_id = spv.supplier_id"
        )
        conditions: list[Any] = []
        params: list[Any] = []
        if date_from:
            conditions.append(SQL("spv.voucher_date >= %s"))
            params.append(date_from)
        if date_to:
            conditions.append(SQL("spv.voucher_date <= %s"))
            params.append(date_to)
        if supplier_id not in (None, ""):
            conditions.append(SQL("spv.supplier_id = %s"))
            params.append(supplier_id)
        if conditions:
            query = query + SQL(" WHERE ") + SQL(" AND ").join(conditions)
        query = query + SQL(" ORDER BY spv.voucher_date DESC, spv.id DESC")
        if limit is not None:
            query = query + SQL(" LIMIT %s")
            params.append(int(limit))
        with self.connect() as conn:
            return list(conn.execute(query, params))

    # -- worker payment vouchers dashboard ----------------------------------

    def worker_vouchers_total(self) -> Any:
        """Sum of every voucher amount — the ``إجمالي السندات`` card."""
        with self.connect() as conn:
            row = conn.execute(
                SQL("SELECT COALESCE(SUM(amount), 0) AS total FROM worker_payment_vouchers")
            ).fetchone()
            return (row["total"] if row else 0) or 0

    def worker_vouchers_by_worker(self) -> list[dict[str, Any]]:
        """Total amount paid per worker, biggest first — feeds the charts and the
        ``أعلى عامل صرفت عليه`` card. The worker name comes from the workers JOIN
        (a deleted/unknown worker shows as ``غير محدد``)."""
        query = SQL(
            "SELECT COALESCE(NULLIF(btrim(w.worker_name), ''), 'غير محدد') AS worker_name, "
            "SUM(wpv.amount) AS total "
            "FROM worker_payment_vouchers wpv "
            "LEFT JOIN workers w ON w.worker_id = wpv.worker_id "
            "GROUP BY 1 ORDER BY total DESC, worker_name ASC"
        )
        with self.connect() as conn:
            return list(conn.execute(query))

    def top_worker_voucher(self) -> dict[str, Any] | None:
        """The single worker with the highest paid total — ``أعلى عامل``."""
        rows = self.worker_vouchers_by_worker()
        return rows[0] if rows else None

    def peek_next_worker_voucher_number(self) -> str:
        """Advisory next automatic ``Paid - Wrk-<n>`` for pre-filling the form.

        Reads the sequence state without consuming it, so it never allocates a
        number; the real value is still assigned atomically by the DB DEFAULT on
        INSERT. Falls back to ``Paid - Wrk-01`` if the sequence is unreadable.
        """
        try:
            with self.connect() as conn:
                row = conn.execute(
                    SQL("SELECT last_value, is_called FROM worker_payment_voucher_number_seq")
                ).fetchone()
            nxt = (row["last_value"] + 1) if row and row["is_called"] else (row["last_value"] if row else 1)
        except Exception:
            nxt = 1
        return f"Paid - Wrk-{int(nxt):02d}"

    def search_worker_vouchers(
        self,
        date_from: Any = None,
        date_to: Any = None,
        worker_id: Any = None,
        limit: int | None = 500,
    ) -> list[dict[str, Any]]:
        """Rows for the worker-voucher search popup, newest first.

        Mirrors :meth:`search_supplier_vouchers`: with no date filter the caller
        passes ``limit=500`` (latest 500 only); a date range passes ``limit=None``
        to show every match. ``worker_id`` narrows to one worker. All optional.
        """
        query = SQL(
            "SELECT wpv.id, wpv.voucher_number, wpv.voucher_date, "
            "wpv.worker_id, w.worker_name, wpv.amount, wpv.description "
            "FROM worker_payment_vouchers wpv "
            "LEFT JOIN workers w ON w.worker_id = wpv.worker_id"
        )
        conditions: list[Any] = []
        params: list[Any] = []
        if date_from:
            conditions.append(SQL("wpv.voucher_date >= %s"))
            params.append(date_from)
        if date_to:
            conditions.append(SQL("wpv.voucher_date <= %s"))
            params.append(date_to)
        if worker_id not in (None, ""):
            conditions.append(SQL("wpv.worker_id = %s"))
            params.append(worker_id)
        if conditions:
            query = query + SQL(" WHERE ") + SQL(" AND ").join(conditions)
        query = query + SQL(" ORDER BY wpv.voucher_date DESC, wpv.id DESC")
        if limit is not None:
            query = query + SQL(" LIMIT %s")
            params.append(int(limit))
        with self.connect() as conn:
            return list(conn.execute(query, params))

    # -- worker daily dashboard ---------------------------------------------

    def worker_daily_total_salary(self) -> Any:
        """Sum of every daily_salary — the ``إجمالي الراتب اليومي`` card."""
        with self.connect() as conn:
            row = conn.execute(
                SQL("SELECT COALESCE(SUM(daily_salary), 0) AS total FROM worker_daily")
            ).fetchone()
            return (row["total"] if row else 0) or 0

    def worker_daily_total_cash(self) -> Any:
        """Sum of every cash amount — the ``إجمالي النقديات`` card."""
        with self.connect() as conn:
            row = conn.execute(
                SQL("SELECT COALESCE(SUM(cash), 0) AS total FROM worker_daily")
            ).fetchone()
            return (row["total"] if row else 0) or 0

    def worker_daily_total_balance(self) -> Any:
        """Sum of every balance — the ``إجمالي الرصيد`` card."""
        with self.connect() as conn:
            row = conn.execute(
                SQL("SELECT COALESCE(SUM(balance), 0) AS total FROM worker_daily")
            ).fetchone()
            return (row["total"] if row else 0) or 0

    def worker_daily_by_worker(self) -> list[dict[str, Any]]:
        """Total daily_salary per worker, biggest first — feeds the top-workers
        chart. The worker name comes from the workers JOIN (an unknown worker
        shows as ``غير محدد``)."""
        query = SQL(
            "SELECT COALESCE(NULLIF(btrim(w.worker_name), ''), 'غير محدد') AS worker_name, "
            "SUM(wd.daily_salary) AS total "
            "FROM worker_daily wd "
            "LEFT JOIN workers w ON w.worker_id = wd.worker_id "
            "GROUP BY 1 ORDER BY total DESC, worker_name ASC"
        )
        with self.connect() as conn:
            return list(conn.execute(query))

    def search_worker_daily(
        self,
        date_from: Any = None,
        date_to: Any = None,
        worker_id: Any = None,
        limit: int | None = 500,
    ) -> list[dict[str, Any]]:
        """Rows for the worker-daily search popup, newest first.

        Mirrors :meth:`search_supplier_vouchers`: no date filter -> latest 500;
        a date range -> every match (limit=None). ``worker_id`` narrows to one
        worker. All filters optional.
        """
        query = SQL(
            "SELECT wd.id, wd.movement_date, wd.worker_id, w.worker_name, "
            "wd.statement, wd.number_of_days, wd.daily_wage, wd.daily_salary, "
            "wd.cash, wd.balance "
            "FROM worker_daily wd "
            "LEFT JOIN workers w ON w.worker_id = wd.worker_id"
        )
        conditions: list[Any] = []
        params: list[Any] = []
        if date_from:
            conditions.append(SQL("wd.movement_date >= %s"))
            params.append(date_from)
        if date_to:
            conditions.append(SQL("wd.movement_date <= %s"))
            params.append(date_to)
        if worker_id not in (None, ""):
            conditions.append(SQL("wd.worker_id = %s"))
            params.append(worker_id)
        if conditions:
            query = query + SQL(" WHERE ") + SQL(" AND ").join(conditions)
        query = query + SQL(" ORDER BY wd.movement_date DESC, wd.id DESC")
        if limit is not None:
            query = query + SQL(" LIMIT %s")
            params.append(int(limit))
        with self.connect() as conn:
            return list(conn.execute(query, params))

    def count_customers(self) -> int:
        """Total number of customers — the ``عدد العملاء`` KPI card."""
        with self.connect() as conn:
            row = conn.execute(SQL("SELECT COUNT(*) AS c FROM customers")).fetchone()
            return int(row["c"]) if row else 0

    def top_customer_by_sales(self) -> dict[str, Any] | None:
        """The customer with the highest approved sales — ``أعلى عميل مبيعات``.

        Sales are summed from ``sales_invoices`` (the main sales invoices),
        counting only ``approved`` documents and their ``total_including_vat``.
        The current customer name is preferred over the invoice snapshot, so a
        later rename is reflected. Returns ``None`` when there are no approved
        sales yet. Returns keys: ``customer_id``, ``customer_name``, ``total_sales``.
        """
        query = SQL(
            "SELECT si.customer_id AS customer_id, "
            "COALESCE(c.customer_name, MAX(si.customer_name_snapshot)) AS customer_name, "
            "SUM(si.total_including_vat) AS total_sales "
            "FROM sales_invoices si "
            "LEFT JOIN customers c ON c.customer_id = si.customer_id "
            "WHERE si.document_status = 'approved' "
            "GROUP BY si.customer_id, c.customer_name "
            "ORDER BY total_sales DESC NULLS LAST "
            "LIMIT 1"
        )
        with self.connect() as conn:
            return conn.execute(query).fetchone()

    def search_customers(self, keyword: Any, limit: int | None = 100) -> list[dict[str, Any]]:
        """Search customers by code (customer_id), name, or phone.

        Partial (ILIKE) search, case-insensitive; Arabic and English both work.
        Results are ordered with an exact customer_id (code) match first, then
        by customer_id ascending. Limited to ``limit`` rows for performance.

        Notes on the current schema (001_create_core_schema.sql):
        * The customers table has no separate "mobile" column; only
          ``phone_number``. A future mobile column would be added here.
        * There is no active/inactive flag, so all customers are returned.
          If such a flag is added later, an ``is_active`` filter should be
          added to the WHERE clause here.
        """
        text = "" if keyword is None else str(keyword).strip()
        columns = ["customer_id", "phone_number", "customer_name"]
        base_query = SQL("SELECT {cols} FROM customers").format(
            cols=SQL(", ").join(Identifier(column) for column in columns)
        )
        if not text:
            query = base_query + SQL(" ORDER BY customer_id ASC")
            params: list[Any] = []
            if limit is not None:
                query += SQL(" LIMIT %s")
                params.append(limit)
            with self.connect() as conn:
                return list(conn.execute(query, params))
        like = f"%{text}%"
        query = (
            base_query
            + SQL(
                " WHERE CAST(customer_id AS text) ILIKE %s "
                "OR COALESCE(customer_name, '') ILIKE %s "
                "OR COALESCE(CAST(phone_number AS text), '') ILIKE %s "
                "ORDER BY (CAST(customer_id AS text) = %s) DESC, customer_id ASC"
            )
        )
        params = [like, like, like, text]
        if limit is not None:
            query += SQL(" LIMIT %s")
            params.append(limit)
        with self.connect() as conn:
            return list(conn.execute(query, params))

    def lookup_customers(self, keyword: Any, limit: int | None = 100) -> list[dict[str, Any]]:
        """Lightweight customer lookup for remote dropdown searches.

        Returns only the fields needed by dropdowns and caps the result size at
        100 so callers cannot accidentally hydrate the full customers table.
        """
        text = "" if keyword is None else str(keyword).strip()
        capped_limit = self._customer_lookup_limit(limit)
        columns = ["customer_id", "customer_name", "phone_number"]
        base_query = SQL("SELECT {cols} FROM customers").format(
            cols=SQL(", ").join(Identifier(column) for column in columns)
        )
        params: list[Any] = []
        if text:
            like = f"%{text}%"
            query = (
                base_query
                + SQL(
                    " WHERE CAST(customer_id AS text) ILIKE %s "
                    "OR COALESCE(customer_name, '') ILIKE %s "
                    "OR COALESCE(CAST(phone_number AS text), '') ILIKE %s "
                    "ORDER BY (CAST(customer_id AS text) = %s) DESC, "
                    "(COALESCE(customer_name, '') ILIKE %s) DESC, "
                    "(COALESCE(customer_name, '') ILIKE %s) DESC, "
                    "customer_name NULLS LAST, customer_id ASC LIMIT %s"
                )
            )
            params = [like, like, like, text, text, f"{text}%", capped_limit]
        else:
            query = base_query + SQL(
                " ORDER BY customer_name NULLS LAST, customer_id ASC LIMIT %s"
            )
            params = [capped_limit]
        with self.connect() as conn:
            return list(conn.execute(query, params))

    @classmethod
    def _customer_lookup_limit(cls, limit: int | None) -> int:
        try:
            requested = int(limit) if limit is not None else cls.CUSTOMER_LOOKUP_LIMIT
        except (TypeError, ValueError):
            requested = cls.CUSTOMER_LOOKUP_LIMIT
        return max(1, min(cls.CUSTOMER_LOOKUP_LIMIT, requested))

    def value_exists(
        self,
        spec: TableSpec,
        column: str,
        value: Any,
        exclude_id: Any | None = None,
    ) -> bool:
        """True if ``value`` already exists in ``column`` (optionally ignoring one row).

        Used by screens with user-entered UNIQUE columns (e.g. a company's
        commercial registration / VAT number) to show a clear Arabic message
        before hitting the database's UNIQUE index, which remains the final guard.
        Comparison is whitespace-insensitive to match the stored, trimmed value.
        """
        text = "" if value is None else str(value).strip()
        if text == "":
            return False
        query = SQL(
            "SELECT 1 FROM {table} WHERE btrim(CAST({col} AS text)) = %s"
        ).format(table=Identifier(spec.table_name), col=Identifier(column))
        params: list[Any] = [text]
        if exclude_id is not None:
            query += SQL(" AND {pk} <> %s").format(pk=Identifier(spec.primary_key))
            params.append(exclude_id)
        query += SQL(" LIMIT 1")
        with self.connect() as conn:
            return conn.execute(query, params).fetchone() is not None

    def next_id(self, spec: TableSpec) -> int:
        with self.connect() as conn:
            return self._next_id(conn, spec)

    def get_record(self, spec: TableSpec, record_id: Any) -> dict[str, Any] | None:
        columns = [field.name for field in spec.fields if not field.virtual]
        query = SQL("SELECT {cols} FROM {table} WHERE {pk} = %s").format(
            cols=SQL(", ").join(Identifier(c) for c in columns),
            table=Identifier(spec.table_name),
            pk=Identifier(spec.primary_key),
        )
        with self.connect() as conn:
            record = conn.execute(query, [record_id]).fetchone()
            if record and spec.key == "daily_followups" and record.get("customer_id"):
                customer = conn.execute(
                    SQL(
                        "SELECT customer_name, phone_number FROM customers WHERE customer_id = %s"
                    ),
                    [record["customer_id"]],
                ).fetchone()
                if customer:
                    record["customer_name"] = customer.get("customer_name")
                    record["customer_phone"] = customer.get("phone_number")
            return record

    def save_record(self, spec: TableSpec, payload: dict[str, Any], record_id: Any | None) -> Any:
        clean_payload = {
            field.name: self._coerce_value(field, payload.get(field.name))
            for field in spec.fields
            if field.name in payload
            and not field.virtual
            and not (field.readonly and field.name == spec.primary_key)
        }
        for field in spec.fields:
            if field.required and not clean_payload.get(field.name):
                raise ValueError(f"الحقل مطلوب: {field.label}")

        if spec.key == "daily_followups":
            follow_up_date = clean_payload.get("follow_up_date")
            if follow_up_date is not None:
                clean_payload["follow_up_month"] = follow_up_date.month
                clean_payload["follow_up_year"] = follow_up_date.year

        if spec.key in {"customers", "suppliers", "workers", "products"} and "opening_balance" in clean_payload and clean_payload.get("opening_balance") is None:
            # رصيد أول المدة is NOT NULL DEFAULT 0: an empty field means zero,
            # not NULL, so it never trips the column's NOT NULL constraint.
            clean_payload["opening_balance"] = 0

        if spec.key in {"receipt_vouchers", "supplier_payment_vouchers", "worker_payment_vouchers"}:
            # رقم السند is always automatic (never user-typed): drop the column so
            # the database DEFAULT assigns the next number atomically on INSERT
            # (receipt_vouchers -> PA-<n>, supplier_payment_vouchers ->
            # Paid - Sub-<n>, worker_payment_vouchers -> Paid - Wrk-<n>).
            # Concurrency-safe; never MAX+1. On UPDATE this leaves
            # the stored number unchanged. Any display preview carried by the
            # readonly field is ignored here.
            clean_payload.pop("voucher_number", None)

        with self.connect() as conn:
            if record_id is None:
                # Concurrency-safe id allocation: do NOT set the primary key from
                # MAX(pk)+1. Let PostgreSQL assign it atomically from the table's
                # sequence (migration 008 wires a DEFAULT nextval on every core
                # table) and read the assigned value back with RETURNING. Two
                # devices clicking "New/Save" at the same instant therefore each
                # receive their own unique number with no locking and no
                # duplicate-key failures. NEVER reintroduce MAX(pk)+1 here.
                columns = list(clean_payload.keys())  # never contains the PK
                if columns:
                    query = SQL(
                        "INSERT INTO {table} ({cols}) VALUES ({values}) RETURNING {pk}"
                    ).format(
                        table=Identifier(spec.table_name),
                        cols=SQL(", ").join(Identifier(c) for c in columns),
                        values=SQL(", ").join(SQL("%s") for _ in columns),
                        pk=Identifier(spec.primary_key),
                    )
                    params = [clean_payload[c] for c in columns]
                else:
                    query = SQL(
                        "INSERT INTO {table} DEFAULT VALUES RETURNING {pk}"
                    ).format(
                        table=Identifier(spec.table_name),
                        pk=Identifier(spec.primary_key),
                    )
                    params = []
                return conn.execute(query, params).fetchone()[spec.primary_key]

            columns = list(clean_payload.keys())
            assignments = SQL(", ").join(
                SQL("{col} = %s").format(col=Identifier(column)) for column in columns
            )
            query = SQL("UPDATE {table} SET {assignments} WHERE {pk} = %s").format(
                table=Identifier(spec.table_name),
                assignments=assignments,
                pk=Identifier(spec.primary_key),
            )
            conn.execute(query, [clean_payload[c] for c in columns] + [record_id])
            return record_id

    # Child tables that reference each master table through an ON DELETE RESTRICT
    # foreign key (see migration 001_create_core_schema.sql). This is the single
    # source of truth for relationship safety, shared by single-record delete and
    # bulk "delete all" so both refuse to orphan linked rows.
    _CHILD_RELATIONSHIPS: dict[str, tuple[tuple[str, str, str], ...]] = {
        "customers": (("daily_followups", "customer_id", "يوجد تعاملات يومية مرتبطة بالعميل"),),
        "employees": (("daily_followups", "employee_id", "يوجد تعاملات يومية مرتبطة بالموظف"),),
        "case_statuses": (("daily_followups", "case_status_id", "يوجد تعاملات يومية مرتبطة بالحالة"),),
        # A tractor priced for some customer must not vanish out from under him.
        # The FK is ON DELETE RESTRICT, so the delete would fail anyway — this
        # entry turns that raw ForeignKeyViolation into a sentence naming how
        # many customers still price the tractor.
        "tawrid_tractors": (
            (
                "tawrid_customer_tractor_prices",
                "tractor_id",
                "الجرار مستخدم في شبكة أسعار عملاء",
            ),
        ),
        # عقود ودفعات المقاولين keep the contractor (ON DELETE RESTRICT).
        "contractors": (("contractor_contracts", "contractor_id", "يوجد عقود مسجلة على المقاول"),
                        ("contractor_payments", "contractor_id", "يوجد دفعات مسجلة على المقاول")),
    }

    # Entities whose delete / delete-all CASCADES: deleting the master also deletes
    # every linked child row (per the user's request), so a supplier/customer with
    # invoices or vouchers can be removed. Each entry lists (child_table, fk_column)
    # in a safe order (children first). The invoice detail tables (lines, ZATCA data)
    # are ON DELETE CASCADE from their invoice, so deleting the invoice row is enough.
    _CASCADE_CHILDREN: dict[str, tuple[tuple[str, str], ...]] = {
        "suppliers": (
            ("purchase_invoices", "supplier_id"),
            ("supplier_payment_vouchers", "supplier_id"),
        ),
        "customers": (
            ("sales_invoices", "customer_id"),
            ("receipt_vouchers", "customer_id"),
            ("cashier_invoices", "customer_id"),
            ("loading_vouchers", "customer_id"),
            ("daily_followups", "customer_id"),
        ),
    }

    # A human warning shown before a cascading delete, so the user knows what else goes.
    _CASCADE_LABELS: dict[str, str] = {
        "suppliers": (
            "تنبيه: سيتم أيضًا حذف كل السجلات المرتبطة بالمورد نهائيًا "
            "(فواتير المشتريات وسندات صرف الموردين)."
        ),
        "customers": (
            "تنبيه: سيتم أيضًا حذف كل السجلات المرتبطة بالعميل نهائيًا "
            "(فواتير المبيعات، سندات القبض، فواتير الكاشير، سندات التحميل، المتابعة اليومية)."
        ),
    }

    def cascade_warning(self, spec: TableSpec) -> str | None:
        """Extra confirmation line for entities whose delete cascades, else None."""
        return self._CASCADE_LABELS.get(spec.key)

    def delete_record(self, spec: TableSpec, record_id: Any) -> None:
        cascade = self._CASCADE_CHILDREN.get(spec.key)
        if cascade:
            self._cascade_delete_one(spec, record_id, cascade)
            return
        blockers = self.delete_blockers(spec, record_id)
        if blockers:
            raise ValueError("\n".join(blockers))
        query = SQL("DELETE FROM {table} WHERE {pk} = %s").format(
            table=Identifier(spec.table_name),
            pk=Identifier(spec.primary_key),
        )
        with self.connect() as conn:
            conn.execute(query, [record_id])

    def _cascade_delete_one(
        self, spec: TableSpec, record_id: Any, cascade: tuple[tuple[str, str], ...]
    ) -> None:
        """Delete one master row and all its linked children, atomically."""
        with self.connect() as conn:
            with conn.transaction():
                for child_table, child_column in cascade:
                    conn.execute(
                        SQL("DELETE FROM {table} WHERE {column} = %s").format(
                            table=Identifier(child_table),
                            column=Identifier(child_column),
                        ),
                        [record_id],
                    )
                conn.execute(
                    SQL("DELETE FROM {table} WHERE {pk} = %s").format(
                        table=Identifier(spec.table_name),
                        pk=Identifier(spec.primary_key),
                    ),
                    [record_id],
                )

    def delete_blockers(self, spec: TableSpec, record_id: Any) -> list[str]:
        blockers: list[str] = []
        with self.connect() as conn:
            for table_name, column_name, message in self._CHILD_RELATIONSHIPS.get(spec.key, ()):
                count = conn.execute(
                    SQL("SELECT COUNT(*) AS c FROM {table} WHERE {column} = %s").format(
                        table=Identifier(table_name),
                        column=Identifier(column_name),
                    ),
                    [record_id],
                ).fetchone()["c"]
                if count:
                    blockers.append(f"{message}: {count}")
        return blockers

    def delete_all_records(self, spec: TableSpec) -> int:
        """Delete every row of this screen's own table only.

        For a cascading entity (suppliers / customers) it also deletes every
        linked child row first, so a full wipe succeeds even with invoices/vouchers
        present. For every other entity it still refuses (raising ``ValueError``)
        when linked child rows would be orphaned, so an unrelated table can never
        violate its ON DELETE RESTRICT relationships. Returns the rows deleted.
        """
        cascade = self._CASCADE_CHILDREN.get(spec.key)
        if cascade:
            return self._cascade_delete_all(spec, cascade)
        blockers = self.delete_all_blockers(spec)
        if blockers:
            raise ValueError("\n".join(blockers))
        query = SQL("DELETE FROM {table}").format(table=Identifier(spec.table_name))
        with self.connect() as conn:
            cursor = conn.execute(query)
            deleted = getattr(cursor, "rowcount", 0)
            return deleted if isinstance(deleted, int) and deleted >= 0 else 0

    def _cascade_delete_all(
        self, spec: TableSpec, cascade: tuple[tuple[str, str], ...]
    ) -> int:
        """Wipe a whole master table and every linked child row, atomically.

        Only child rows that actually reference this table (FK ``IS NOT NULL``) are
        removed, so unrelated rows (e.g. a cash cashier invoice with no customer)
        survive. Returns the number of master rows deleted.
        """
        deleted = 0
        with self.connect() as conn:
            with conn.transaction():
                for child_table, child_column in cascade:
                    conn.execute(
                        SQL("DELETE FROM {table} WHERE {column} IS NOT NULL").format(
                            table=Identifier(child_table),
                            column=Identifier(child_column),
                        )
                    )
                cursor = conn.execute(
                    SQL("DELETE FROM {table}").format(table=Identifier(spec.table_name))
                )
                rowcount = getattr(cursor, "rowcount", 0)
                deleted = rowcount if isinstance(rowcount, int) and rowcount >= 0 else 0
        return deleted

    def delete_all_blockers(self, spec: TableSpec) -> list[str]:
        """Reasons a full-table delete is blocked, mirroring :meth:`delete_blockers`.

        A bulk delete is blocked whenever *any* child row still references this
        table (an ``IS NOT NULL`` foreign-key value), since removing all parents
        would break those links.
        """
        blockers: list[str] = []
        with self.connect() as conn:
            for table_name, column_name, message in self._CHILD_RELATIONSHIPS.get(spec.key, ()):
                count = conn.execute(
                    SQL("SELECT COUNT(*) AS c FROM {table} WHERE {column} IS NOT NULL").format(
                        table=Identifier(table_name),
                        column=Identifier(column_name),
                    ),
                ).fetchone()["c"]
                if count:
                    blockers.append(f"{message}: {count}")
        return blockers

    def _next_id(self, conn, spec: TableSpec) -> int:
        """Preview-only hint for the id a new record will *likely* get.

        Shown in the read-only code field when the user clicks "New". It is NOT
        used to allocate the real primary key — allocation happens atomically in
        :meth:`save_record` via the table's PostgreSQL sequence (RETURNING). This
        MAX(pk)+1 value is display-only and safe because it never becomes the
        stored id; under concurrency the sequence, not this number, decides.
        """
        query = SQL("SELECT COALESCE(MAX({pk}), 0) + 1 AS next_id FROM {table}").format(
            pk=Identifier(spec.primary_key),
            table=Identifier(spec.table_name),
        )
        next_id = int(conn.execute(query).fetchone()["next_id"])
        # customers, products and suppliers all start their code at 1001.
        if spec.key in {"customers", "products", "suppliers"}:
            return max(1001, next_id)
        # treasury deposits' رقم الحركة starts at 3001 (matches the DB sequence).
        if spec.key == "treasury_deposits":
            return max(3001, next_id)
        return next_id

    def _coerce_value(self, field: FieldSpec, value: Any) -> Any:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            return None
        if field.data_type == "int":
            try:
                return int(text)
            except ValueError as exc:
                raise ValueError(f"قيمة رقمية غير صحيحة في {field.label}: {text}") from exc
        if field.data_type == "float":
            try:
                return float(text)
            except ValueError as exc:
                raise ValueError(f"قيمة رقمية غير صحيحة في {field.label}: {text}") from exc
        if field.data_type == "bool":
            # Rendered as a two-choice combo (نشط / موقوف), stored as a real
            # boolean. Accepts the Arabic labels and the usual literals so a
            # value round-trips whether it came from the form or an import.
            if text in _TRUE_TEXTS:
                return True
            if text in _FALSE_TEXTS:
                return False
            raise ValueError(f"قيمة غير صحيحة في {field.label}: {text}")
        if field.data_type == "date":
            from datetime import datetime

            try:
                return datetime.strptime(text[:10], "%Y-%m-%d").date()
            except ValueError as exc:
                raise ValueError(
                    f"تاريخ غير صحيح في {field.label} (الصيغة YYYY-MM-DD): {text}"
                ) from exc
        return text
