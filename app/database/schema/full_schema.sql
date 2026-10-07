-- full_schema.sql — AUTO-GENERATED idempotent schema bootstrap.
-- Source: pg_dump --schema-only of the reference InvPhase2 database, made
-- safe to run repeatedly. Runs on app startup and installer provisioning so
-- a fresh database self-builds and an existing one gains only what it lacks.
-- To add a table/column later: add an idempotent statement (CREATE TABLE IF
-- NOT EXISTS / ALTER TABLE ... ADD COLUMN IF NOT EXISTS) — no migration files.

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';

CREATE OR REPLACE FUNCTION public.cashier_invoice_lines_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.cashier_invoices_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.companies_normalize() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.name_ar := btrim(NEW.name_ar);
    NEW.commercial_registration := btrim(NEW.commercial_registration);
    NEW.vat_number := btrim(NEW.vat_number);
    NEW.name_en := NULLIF(btrim(NEW.name_en), '');
    NEW.address_ar := NULLIF(btrim(NEW.address_ar), '');
    NEW.address_en := NULLIF(btrim(NEW.address_en), '');
    NEW.phone := NULLIF(btrim(NEW.phone), '');
    IF TG_OP = 'UPDATE' THEN
        NEW.updated_at := now();
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.products_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.receipt_vouchers_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.sales_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS public.app_users (
    id integer NOT NULL,
    username character varying(60) CONSTRAINT app_users_username_not_null1 NOT NULL,
    password_hash character varying(255) NOT NULL,
    full_name character varying(120),
    email character varying(120),
    phone character varying(40),
    role_id integer,
    language character varying(10) DEFAULT 'ar'::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    is_admin boolean DEFAULT false NOT NULL,
    full_access boolean DEFAULT false NOT NULL,
    notes text,
    last_login_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS public.app_users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.app_users_id_seq OWNED BY public.app_users.id;

CREATE TABLE IF NOT EXISTS public.backup_logs (
    id integer NOT NULL,
    backup_type character varying(20) NOT NULL,
    file_name character varying(255),
    file_path text,
    status character varying(20) NOT NULL,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer
);

CREATE SEQUENCE IF NOT EXISTS public.backup_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.backup_logs_id_seq OWNED BY public.backup_logs.id;

CREATE TABLE IF NOT EXISTS public.case_statuses (
    case_status_id integer NOT NULL,
    case_status_name character varying(90)
);

CREATE SEQUENCE IF NOT EXISTS public.case_statuses_case_status_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.case_statuses_case_status_id_seq OWNED BY public.case_statuses.case_status_id;

CREATE TABLE IF NOT EXISTS public.cashier_invoice_lines (
    id integer NOT NULL,
    cashier_invoice_id integer NOT NULL,
    line_number integer NOT NULL,
    product_id integer NOT NULL,
    product_code_snapshot character varying(100),
    product_name_snapshot character varying(255),
    quantity numeric(18,6) DEFAULT 1 NOT NULL,
    unit_price numeric(18,6) DEFAULT 0 NOT NULL,
    line_subtotal numeric(18,2) DEFAULT 0 NOT NULL,
    vat_rate numeric(5,2) DEFAULT 15.00 NOT NULL,
    vat_amount numeric(18,2) DEFAULT 0 NOT NULL,
    line_total numeric(18,2) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_cashier_invoice_lines_line_number_positive CHECK ((line_number > 0)),
    CONSTRAINT ck_cashier_invoice_lines_line_subtotal_non_negative CHECK ((line_subtotal >= (0)::numeric)),
    CONSTRAINT ck_cashier_invoice_lines_line_total_non_negative CHECK ((line_total >= (0)::numeric)),
    CONSTRAINT ck_cashier_invoice_lines_quantity_positive CHECK ((quantity > (0)::numeric)),
    CONSTRAINT ck_cashier_invoice_lines_unit_price_non_negative CHECK ((unit_price >= (0)::numeric)),
    CONSTRAINT ck_cashier_invoice_lines_vat_amount_non_negative CHECK ((vat_amount >= (0)::numeric)),
    CONSTRAINT ck_cashier_invoice_lines_vat_rate_range CHECK (((vat_rate >= (0)::numeric) AND (vat_rate <= (100)::numeric)))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'public.cashier_invoice_lines'::regclass AND attname = 'id' AND attidentity <> '') THEN
    ALTER TABLE public.cashier_invoice_lines ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.cashier_invoice_lines_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.cashier_invoices (
    id integer NOT NULL,
    invoice_number character varying(100) NOT NULL,
    invoice_uuid uuid,
    invoice_date date DEFAULT CURRENT_DATE NOT NULL,
    invoice_time time without time zone DEFAULT LOCALTIME NOT NULL,
    invoice_datetime timestamp with time zone DEFAULT now() NOT NULL,
    customer_id integer,
    company_id integer NOT NULL,
    branch_id integer,
    created_by_user_id integer,
    invoice_status character varying(20) DEFAULT 'DRAFT'::character varying NOT NULL,
    invoice_type character varying(20) DEFAULT 'SIMPLIFIED'::character varying NOT NULL,
    currency_code character(3) DEFAULT 'SAR'::bpchar NOT NULL,
    subtotal numeric(18,2) DEFAULT 0 NOT NULL,
    vat_amount numeric(18,2) DEFAULT 0 NOT NULL,
    grand_total numeric(18,2) DEFAULT 0 NOT NULL,
    notes text,
    seller_name_snapshot character varying(255),
    seller_vat_number_snapshot character varying(15),
    seller_commercial_registration_snapshot character varying(50),
    seller_address_snapshot text,
    buyer_name_snapshot character varying(255),
    buyer_vat_number_snapshot character varying(15),
    zatca_icv bigint,
    zatca_previous_invoice_hash text,
    zatca_invoice_hash text,
    zatca_qr_base64 text,
    zatca_xml text,
    zatca_signed_xml text,
    zatca_cryptographic_stamp text,
    zatca_public_key text,
    zatca_signature text,
    zatca_status character varying(30) DEFAULT 'NOT_GENERATED'::character varying NOT NULL,
    zatca_response text,
    zatca_reported_at timestamp with time zone,
    print_count integer DEFAULT 0 NOT NULL,
    last_printed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_cashier_invoices_grand_total_non_negative CHECK ((grand_total >= (0)::numeric)),
    CONSTRAINT ck_cashier_invoices_invoice_number_not_blank CHECK ((char_length(btrim((invoice_number)::text)) > 0)),
    CONSTRAINT ck_cashier_invoices_invoice_status CHECK (((invoice_status)::text = ANY ((ARRAY['DRAFT'::character varying, 'ISSUED'::character varying, 'CANCELLED'::character varying])::text[]))),
    CONSTRAINT ck_cashier_invoices_invoice_type CHECK (((invoice_type)::text = 'SIMPLIFIED'::text)),
    CONSTRAINT ck_cashier_invoices_print_count_non_negative CHECK ((print_count >= 0)),
    CONSTRAINT ck_cashier_invoices_subtotal_non_negative CHECK ((subtotal >= (0)::numeric)),
    CONSTRAINT ck_cashier_invoices_vat_amount_non_negative CHECK ((vat_amount >= (0)::numeric)),
    CONSTRAINT ck_cashier_invoices_zatca_status CHECK (((zatca_status)::text = ANY ((ARRAY['NOT_GENERATED'::character varying, 'READY'::character varying, 'PENDING'::character varying, 'REPORTED'::character varying, 'ACCEPTED'::character varying, 'ACCEPTED_WITH_WARNINGS'::character varying, 'REJECTED'::character varying, 'FAILED'::character varying])::text[])))
);

CREATE SEQUENCE IF NOT EXISTS public.cashier_invoice_number_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.cashier_invoice_number_seq OWNED BY public.cashier_invoices.invoice_number;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'public.cashier_invoices'::regclass AND attname = 'id' AND attidentity <> '') THEN
    ALTER TABLE public.cashier_invoices ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.cashier_invoices_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.companies (
    id integer NOT NULL,
    name_ar character varying(255) NOT NULL,
    name_en character varying(255),
    commercial_registration character varying(50) NOT NULL,
    vat_number character varying(50) NOT NULL,
    phone character varying(50),
    address_ar text,
    address_en text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    logo bytea,
    logo_mime character varying(64),
    stamp bytea,
    stamp_mime character varying(64),
    CONSTRAINT ck_companies_commercial_registration_not_blank CHECK ((char_length(btrim((commercial_registration)::text)) > 0)),
    CONSTRAINT ck_companies_name_ar_not_blank CHECK ((char_length(btrim((name_ar)::text)) > 0)),
    CONSTRAINT ck_companies_vat_number_not_blank CHECK ((char_length(btrim((vat_number)::text)) > 0))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'public.companies'::regclass AND attname = 'id' AND attidentity <> '') THEN
    ALTER TABLE public.companies ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.companies_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
  END IF;
END $$;

-- Additive: provision the phone column on databases whose companies table was
-- created before it existed (a fresh CREATE above already includes it).
ALTER TABLE public.companies ADD COLUMN IF NOT EXISTS phone character varying(50);

CREATE TABLE IF NOT EXISTS public.company_settings (
    company_name_ar character varying(80),
    general_manager_name character varying(80),
    email_address character varying(25),
    mobile_number character varying(25),
    website_url character varying(60),
    address character varying(80),
    commercial_registry_number character varying(25),
    tax_number character varying(25),
    image_path character varying(255),
    company_name_en character varying(80),
    civil_defense_license_number character varying(50),
    civil_defense_license_start_date timestamp without time zone,
    civil_defense_license_end_date timestamp without time zone,
    municipality_license_number character varying(50),
    municipality_license_start_date timestamp without time zone,
    municipality_license_end_date timestamp without time zone
);

CREATE SEQUENCE IF NOT EXISTS public.crm_attachment_code_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS public.crm_attachments (
    id integer NOT NULL,
    attachment_code character varying(40) NOT NULL,
    entity_type character varying(60) DEFAULT 'Other'::character varying NOT NULL,
    entity_id integer,
    title character varying(200) NOT NULL,
    category character varying(60),
    original_file_name character varying(255) NOT NULL,
    file_extension character varying(20),
    mime_type character varying(120),
    file_size bigint DEFAULT 0 NOT NULL,
    file_hash character varying(64),
    file_data bytea NOT NULL,
    notes text,
    tags text,
    is_favorite boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer,
    updated_by integer
);

CREATE SEQUENCE IF NOT EXISTS public.crm_attachments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.crm_attachments_id_seq OWNED BY public.crm_attachments.id;

CREATE TABLE IF NOT EXISTS public.customers (
    customer_id integer NOT NULL,
    phone_number character varying(40),
    customer_name character varying(100),
    place_area_feddan integer,
    area_number character varying(30),
    building character varying(30),
    unit_number character varying(30),
    floor_number character varying(60),
    installment_duration_years integer,
    remaining_installments integer,
    installment_amount integer,
    legacy_area_number_2 character varying(30),
    vat_number character varying(50),
    cr character varying(50),
    address text
);

-- Added post-dump (migration 019): customer opening balance (رصيد أول المدة).
-- CREATE TABLE IF NOT EXISTS above never alters an existing table, so this
-- idempotent ALTER self-applies the new column on every device at launch.
ALTER TABLE public.customers
    ADD COLUMN IF NOT EXISTS opening_balance numeric(18, 2) DEFAULT 0 NOT NULL;

CREATE SEQUENCE IF NOT EXISTS public.customers_customer_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.customers_customer_id_seq OWNED BY public.customers.customer_id;

-- Added post-dump (migration 020): suppliers master table (الموردين). The code
-- sequence starts at 1001 so the first supplier is 1001, then 1002, 1003, ...
CREATE SEQUENCE IF NOT EXISTS public.suppliers_supplier_id_seq
    START WITH 1001
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS public.suppliers (
    supplier_id integer DEFAULT nextval('public.suppliers_supplier_id_seq'::regclass) NOT NULL,
    supplier_name character varying(150),
    mobile character varying(40),
    opening_balance numeric(18,2) DEFAULT 0 NOT NULL
);

ALTER SEQUENCE public.suppliers_supplier_id_seq OWNED BY public.suppliers.supplier_id;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'suppliers_pkey' AND conrelid = 'public.suppliers'::regclass) THEN
    ALTER TABLE ONLY public.suppliers ADD CONSTRAINT suppliers_pkey PRIMARY KEY (supplier_id);
  END IF;
END $$;

-- Added post-dump (migration 028): نوع الحساب — a supplier's account type, stored
-- as the Arabic text 'عدد' or 'وزن'. Optional (NULL for suppliers entered before
-- this column existed). ADD COLUMN IF NOT EXISTS keeps this idempotent.
ALTER TABLE public.suppliers
    ADD COLUMN IF NOT EXISTS account_type character varying(10);

-- Added post-dump (migration 021): workers master table (العمال). The code
-- sequence starts at 1; the UI shows it zero-padded (0001, 0002, 0003, ...).
CREATE SEQUENCE IF NOT EXISTS public.workers_worker_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS public.workers (
    worker_id integer DEFAULT nextval('public.workers_worker_id_seq'::regclass) NOT NULL,
    worker_name character varying(150),
    mobile character varying(40),
    opening_balance numeric(18,2) DEFAULT 0 NOT NULL
);

ALTER SEQUENCE public.workers_worker_id_seq OWNED BY public.workers.worker_id;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'workers_pkey' AND conrelid = 'public.workers'::regclass) THEN
    ALTER TABLE ONLY public.workers ADD CONSTRAINT workers_pkey PRIMARY KEY (worker_id);
  END IF;
END $$;

-- Added post-dump (migration 022): expenses table (المصروفات). The expense_type
-- dropdown is built from the DISTINCT values already stored (no separate table).
CREATE SEQUENCE IF NOT EXISTS public.expenses_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS public.expenses (
    id integer DEFAULT nextval('public.expenses_id_seq'::regclass) NOT NULL,
    expense_date date DEFAULT CURRENT_DATE NOT NULL,
    amount numeric(18,2) DEFAULT 0 NOT NULL,
    expense_type character varying(150),
    statement text
);

ALTER SEQUENCE public.expenses_id_seq OWNED BY public.expenses.id;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'expenses_pkey' AND conrelid = 'public.expenses'::regclass) THEN
    ALTER TABLE ONLY public.expenses ADD CONSTRAINT expenses_pkey PRIMARY KEY (id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_expenses_type ON public.expenses USING btree (expense_type);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON public.expenses USING btree (expense_date);

CREATE TABLE IF NOT EXISTS public.daily_followups (
    daily_followup_id integer NOT NULL,
    sequence_number integer DEFAULT 0,
    follow_up_date timestamp without time zone,
    customer_id integer,
    employee_id integer,
    case_status_id integer,
    notes character varying(150),
    follow_up_month smallint,
    follow_up_year smallint,
    legacy_month_year_code character varying(243),
    contact_count integer DEFAULT 1,
    installment_duration_years double precision,
    remaining_installments double precision,
    installment_amount double precision,
    installment_type character varying(50),
    buyer_name character varying(90),
    buyer_phone_number character varying(90),
    unit_sale_amount double precision,
    seller_commission_amount double precision,
    buyer_commission_amount double precision
);

CREATE SEQUENCE IF NOT EXISTS public.daily_followups_daily_followup_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.daily_followups_daily_followup_id_seq OWNED BY public.daily_followups.daily_followup_id;

CREATE TABLE IF NOT EXISTS public.employees (
    employee_id integer NOT NULL,
    phone_number character varying(40) NOT NULL,
    employee_name character varying(100),
    governorate character varying(100),
    district_center character varying(100),
    village character varying(100)
);

CREATE SEQUENCE IF NOT EXISTS public.employees_employee_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.employees_employee_id_seq OWNED BY public.employees.employee_id;

CREATE TABLE IF NOT EXISTS public.permissions (
    id integer NOT NULL,
    permission_code character varying(150) NOT NULL,
    permission_type character varying(20) NOT NULL,
    module_code character varying(50),
    module_name_ar character varying(120),
    module_name_en character varying(120),
    category_ar character varying(120),
    category_en character varying(120),
    target_code character varying(80),
    target_name_ar character varying(150),
    target_name_en character varying(150),
    action_code character varying(40),
    action_name_ar character varying(80),
    action_name_en character varying(80),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS public.permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.permissions_id_seq OWNED BY public.permissions.id;

CREATE TABLE IF NOT EXISTS public.places (
    place_id integer NOT NULL,
    place_number character varying(50)
);

CREATE SEQUENCE IF NOT EXISTS public.places_place_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.places_place_id_seq OWNED BY public.places.place_id;

CREATE TABLE IF NOT EXISTS public.products (
    id integer NOT NULL,
    item_code integer NOT NULL,
    item_name character varying(200) NOT NULL,
    unit character varying(50) DEFAULT ''::character varying NOT NULL,
    item_type character varying(20),
    quantity numeric(18,3) DEFAULT 0 NOT NULL,
    price numeric(18,2) DEFAULT 0 NOT NULL,
    opening_balance numeric(18,2) DEFAULT 0 NOT NULL,
    total numeric(23,5) GENERATED ALWAYS AS ((quantity * price)) STORED,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_products_item_name_not_blank CHECK ((char_length(btrim((item_name)::text)) > 0)),
    CONSTRAINT ck_products_price_non_negative CHECK ((price >= (0)::numeric)),
    CONSTRAINT ck_products_quantity_non_negative CHECK ((quantity >= (0)::numeric))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'public.products'::regclass AND attname = 'id' AND attidentity <> '') THEN
    ALTER TABLE public.products ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.products_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
  END IF;
END $$;

CREATE SEQUENCE IF NOT EXISTS public.products_item_code_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.products_item_code_seq OWNED BY public.products.item_code;

-- الوحدة (unit of measure) — added to existing databases. Text, defaults to ''
-- so pre-existing rows carry a blank unit until edited on the أصناف screen.
ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS unit character varying(50) DEFAULT ''::character varying NOT NULL;

-- نوع الصنف (item type) — added to existing databases. A fixed choice of
-- 'مادة خام' or 'منتج تام'; nullable (unset) until chosen on the أصناف screen. The
-- choice is enforced by the UI dropdown, not the database, so a future third
-- value never needs a schema change.
ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS item_type character varying(20);

-- رصيد أول المدة (opening balance) — added to existing databases. Mirrors the
-- customers / suppliers / workers column: DEFAULT 0 NOT NULL, so old rows get 0.
ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS opening_balance numeric(18,2) DEFAULT 0 NOT NULL;

CREATE TABLE IF NOT EXISTS public.receipt_vouchers (
    id integer NOT NULL,
    voucher_number character varying(30) NOT NULL,
    voucher_date date DEFAULT CURRENT_DATE NOT NULL,
    customer_id integer NOT NULL,
    company_id integer,
    payment_type character varying(20),
    amount numeric(18,2) NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer,
    updated_by integer,
    CONSTRAINT ck_receipt_vouchers_amount_positive CHECK ((amount > (0)::numeric)),
    CONSTRAINT ck_receipt_vouchers_payment_type CHECK (((payment_type)::text = ANY ((ARRAY['cash'::character varying, 'bank_transfer'::character varying])::text[]))),
    CONSTRAINT ck_receipt_vouchers_voucher_number_not_blank CHECK ((char_length(btrim((voucher_number)::text)) > 0))
);

CREATE SEQUENCE IF NOT EXISTS public.receipt_voucher_number_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.receipt_voucher_number_seq OWNED BY public.receipt_vouchers.voucher_number;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'public.receipt_vouchers'::regclass AND attname = 'id' AND attidentity <> '') THEN
    ALTER TABLE public.receipt_vouchers ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.receipt_vouchers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.role_permissions (
    id integer NOT NULL,
    role_id integer NOT NULL,
    permission_id integer NOT NULL,
    allowed boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS public.role_permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.role_permissions_id_seq OWNED BY public.role_permissions.id;

CREATE TABLE IF NOT EXISTS public.roles (
    id integer NOT NULL,
    role_code character varying(50) NOT NULL,
    role_name_ar character varying(120),
    role_name_en character varying(120),
    description text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS public.roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;

CREATE TABLE IF NOT EXISTS public.sales_invoice_audit_logs (
    id bigint NOT NULL,
    invoice_id bigint,
    invoice_number_snapshot character varying(100),
    seller_company_id_snapshot bigint,
    action character varying(50) NOT NULL,
    old_status character varying(30),
    new_status character varying(30),
    performed_by integer,
    batch_id uuid,
    details jsonb,
    previous_log_hash text,
    log_hash text,
    performed_at timestamp with time zone DEFAULT now() NOT NULL
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'public.sales_invoice_audit_logs'::regclass AND attname = 'id' AND attidentity <> '') THEN
    ALTER TABLE public.sales_invoice_audit_logs ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.sales_invoice_audit_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.sales_invoice_lines (
    id bigint NOT NULL,
    invoice_id bigint NOT NULL,
    line_number integer NOT NULL,
    product_id integer,
    product_code_snapshot character varying(100) NOT NULL,
    product_name_snapshot character varying(255) NOT NULL,
    unit_code character varying(20) DEFAULT 'PCE'::character varying NOT NULL,
    quantity numeric(18,6) NOT NULL,
    unit_price numeric(18,6) NOT NULL,
    line_amount_before_vat numeric(18,2) NOT NULL,
    vat_category_code character varying(10) DEFAULT 'S'::character varying NOT NULL,
    vat_rate numeric(5,2) DEFAULT 15.00 NOT NULL,
    vat_amount numeric(18,2) NOT NULL,
    line_total_including_vat numeric(18,2) NOT NULL,
    tax_exemption_reason_code character varying(100),
    tax_exemption_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_sales_invoice_lines_line_amount_before_vat_nonnegative CHECK ((line_amount_before_vat >= (0)::numeric)),
    CONSTRAINT ck_sales_invoice_lines_line_number_positive CHECK ((line_number > 0)),
    CONSTRAINT ck_sales_invoice_lines_line_total_including_vat_nonnegative CHECK ((line_total_including_vat >= (0)::numeric)),
    CONSTRAINT ck_sales_invoice_lines_line_total_matches_components CHECK ((line_total_including_vat = (line_amount_before_vat + vat_amount))),
    CONSTRAINT ck_sales_invoice_lines_quantity_positive CHECK ((quantity > (0)::numeric)),
    CONSTRAINT ck_sales_invoice_lines_unit_price_nonnegative CHECK ((unit_price >= (0)::numeric)),
    CONSTRAINT ck_sales_invoice_lines_vat_amount_nonnegative CHECK ((vat_amount >= (0)::numeric)),
    CONSTRAINT ck_sales_invoice_lines_vat_rate_nonnegative CHECK ((vat_rate >= (0)::numeric))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'public.sales_invoice_lines'::regclass AND attname = 'id' AND attidentity <> '') THEN
    ALTER TABLE public.sales_invoice_lines ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.sales_invoice_lines_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
  END IF;
END $$;

CREATE SEQUENCE IF NOT EXISTS public.sales_invoice_number_seq
    START WITH 50001
    INCREMENT BY 1
    MINVALUE 50001
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS public.sales_invoice_zatca_data (
    invoice_id bigint NOT NULL,
    device_id bigint,
    uuid uuid,
    invoice_counter_value bigint,
    previous_invoice_hash text,
    invoice_hash text,
    cryptographic_stamp text,
    public_key_snapshot text,
    digital_signature text,
    qr_code_base64 text,
    generated_xml bytea,
    cleared_xml bytea,
    xml_file_name character varying(500),
    xml_file_path text,
    schema_version character varying(30),
    integration_operation character varying(20),
    integration_status character varying(30) DEFAULT 'not_generated'::character varying NOT NULL,
    zatca_request_id character varying(255),
    zatca_response jsonb,
    validation_warnings jsonb,
    validation_errors jsonb,
    xml_generated_at timestamp with time zone,
    submitted_at timestamp with time zone,
    accepted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_sales_invoice_zatca_data_integration_operation_valid CHECK (((integration_operation IS NULL) OR ((integration_operation)::text = ANY ((ARRAY['clearance'::character varying, 'reporting'::character varying])::text[])))),
    CONSTRAINT ck_sales_invoice_zatca_data_integration_status_valid CHECK (((integration_status)::text = ANY ((ARRAY['not_generated'::character varying, 'generated'::character varying, 'pending'::character varying, 'cleared'::character varying, 'reported'::character varying, 'warning'::character varying, 'rejected'::character varying, 'failed'::character varying])::text[])))
);

CREATE TABLE IF NOT EXISTS public.sales_invoice_zatca_submissions (
    id bigint NOT NULL,
    invoice_id bigint NOT NULL,
    operation character varying(20) NOT NULL,
    attempt_number integer NOT NULL,
    request_id character varying(255),
    request_payload_hash text,
    http_status_code integer,
    request_metadata jsonb,
    response_payload jsonb,
    warnings jsonb,
    errors jsonb,
    is_success boolean DEFAULT false NOT NULL,
    requested_at timestamp with time zone NOT NULL,
    responded_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_sales_invoice_zatca_submissions_attempt_number_positive CHECK ((attempt_number > 0)),
    CONSTRAINT ck_sales_invoice_zatca_submissions_operation_valid CHECK (((operation)::text = ANY ((ARRAY['clearance'::character varying, 'reporting'::character varying, 'compliance'::character varying])::text[])))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'public.sales_invoice_zatca_submissions'::regclass AND attname = 'id' AND attidentity <> '') THEN
    ALTER TABLE public.sales_invoice_zatca_submissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.sales_invoice_zatca_submissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.sales_invoices (
    id bigint NOT NULL,
    invoice_number character varying(100) NOT NULL,
    issue_datetime timestamp with time zone DEFAULT now() NOT NULL,
    seller_company_id integer NOT NULL,
    seller_name_ar_snapshot character varying(255) NOT NULL,
    seller_name_en_snapshot character varying(255),
    seller_vat_number_snapshot character varying(15) NOT NULL,
    customer_id integer NOT NULL,
    customer_name_snapshot character varying(255) NOT NULL,
    customer_vat_number_snapshot character varying(15),
    customer_address_snapshot text,
    payment_type character varying(20) NOT NULL,
    notes text,
    invoice_currency_code character(3) DEFAULT 'SAR'::bpchar NOT NULL,
    tax_currency_code character(3) DEFAULT 'SAR'::bpchar NOT NULL,
    subtotal_before_vat numeric(18,2) DEFAULT 0 NOT NULL,
    vat_total numeric(18,2) DEFAULT 0 NOT NULL,
    total_including_vat numeric(18,2) DEFAULT 0 NOT NULL,
    document_status character varying(30) DEFAULT 'draft'::character varying NOT NULL,
    approved_at timestamp with time zone,
    approved_by integer,
    created_by integer,
    updated_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    row_version integer DEFAULT 1 NOT NULL,
    CONSTRAINT ck_sales_invoices_document_status_valid CHECK (((document_status)::text = ANY ((ARRAY['draft'::character varying, 'approved'::character varying])::text[]))),
    CONSTRAINT ck_sales_invoices_invoice_number_not_blank CHECK ((char_length(btrim((invoice_number)::text)) > 0)),
    CONSTRAINT ck_sales_invoices_payment_type_valid CHECK (((payment_type)::text = ANY ((ARRAY['cash'::character varying, 'credit'::character varying])::text[]))),
    CONSTRAINT ck_sales_invoices_subtotal_before_vat_nonnegative CHECK ((subtotal_before_vat >= (0)::numeric)),
    CONSTRAINT ck_sales_invoices_total_including_vat_nonnegative CHECK ((total_including_vat >= (0)::numeric)),
    CONSTRAINT ck_sales_invoices_total_matches_components CHECK ((total_including_vat = (subtotal_before_vat + vat_total))),
    CONSTRAINT ck_sales_invoices_vat_total_nonnegative CHECK ((vat_total >= (0)::numeric))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'public.sales_invoices'::regclass AND attname = 'id' AND attidentity <> '') THEN
    ALTER TABLE public.sales_invoices ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.sales_invoices_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.user_login_logs (
    id integer NOT NULL,
    user_id integer,
    username character varying(60),
    login_time timestamp with time zone DEFAULT now() NOT NULL,
    logout_time timestamp with time zone,
    status character varying(20),
    ip_address character varying(60),
    device_name character varying(120),
    notes text
);

CREATE SEQUENCE IF NOT EXISTS public.user_login_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.user_login_logs_id_seq OWNED BY public.user_login_logs.id;

CREATE TABLE IF NOT EXISTS public.user_permissions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    permission_id integer NOT NULL,
    allowed boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS public.user_permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.user_permissions_id_seq OWNED BY public.user_permissions.id;

ALTER TABLE ONLY public.app_users ALTER COLUMN id SET DEFAULT nextval('public.app_users_id_seq'::regclass);

ALTER TABLE ONLY public.backup_logs ALTER COLUMN id SET DEFAULT nextval('public.backup_logs_id_seq'::regclass);

ALTER TABLE ONLY public.case_statuses ALTER COLUMN case_status_id SET DEFAULT nextval('public.case_statuses_case_status_id_seq'::regclass);

ALTER TABLE ONLY public.cashier_invoices ALTER COLUMN invoice_number SET DEFAULT ('CINV-'::text || to_char(nextval('public.cashier_invoice_number_seq'::regclass), 'FM000000'::text));

ALTER TABLE ONLY public.crm_attachments ALTER COLUMN id SET DEFAULT nextval('public.crm_attachments_id_seq'::regclass);

ALTER TABLE ONLY public.customers ALTER COLUMN customer_id SET DEFAULT nextval('public.customers_customer_id_seq'::regclass);

ALTER TABLE ONLY public.daily_followups ALTER COLUMN daily_followup_id SET DEFAULT nextval('public.daily_followups_daily_followup_id_seq'::regclass);

ALTER TABLE ONLY public.employees ALTER COLUMN employee_id SET DEFAULT nextval('public.employees_employee_id_seq'::regclass);

ALTER TABLE ONLY public.permissions ALTER COLUMN id SET DEFAULT nextval('public.permissions_id_seq'::regclass);

ALTER TABLE ONLY public.places ALTER COLUMN place_id SET DEFAULT nextval('public.places_place_id_seq'::regclass);

ALTER TABLE ONLY public.products ALTER COLUMN item_code SET DEFAULT nextval('public.products_item_code_seq'::regclass);

ALTER TABLE ONLY public.receipt_vouchers ALTER COLUMN voucher_number SET DEFAULT ('PA-'::text || to_char(nextval('public.receipt_voucher_number_seq'::regclass), 'FM000'::text));

-- Migration 024: company_id / payment_type are optional (the simplified customer
-- receipt-voucher screen no longer collects them). Idempotent — DROP NOT NULL on
-- an already-nullable column is a no-op.
ALTER TABLE public.receipt_vouchers ALTER COLUMN company_id DROP NOT NULL;
ALTER TABLE public.receipt_vouchers ALTER COLUMN payment_type DROP NOT NULL;

ALTER TABLE ONLY public.role_permissions ALTER COLUMN id SET DEFAULT nextval('public.role_permissions_id_seq'::regclass);

ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);

ALTER TABLE ONLY public.user_login_logs ALTER COLUMN id SET DEFAULT nextval('public.user_login_logs_id_seq'::regclass);

ALTER TABLE ONLY public.user_permissions ALTER COLUMN id SET DEFAULT nextval('public.user_permissions_id_seq'::regclass);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'app_users_pkey1' AND conrelid = 'public.app_users'::regclass) THEN
    ALTER TABLE ONLY public.app_users ADD CONSTRAINT app_users_pkey1 PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'app_users_username_key' AND conrelid = 'public.app_users'::regclass) THEN
    ALTER TABLE ONLY public.app_users ADD CONSTRAINT app_users_username_key UNIQUE (username);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'backup_logs_pkey' AND conrelid = 'public.backup_logs'::regclass) THEN
    ALTER TABLE ONLY public.backup_logs ADD CONSTRAINT backup_logs_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'case_statuses_pkey' AND conrelid = 'public.case_statuses'::regclass) THEN
    ALTER TABLE ONLY public.case_statuses ADD CONSTRAINT case_statuses_pkey PRIMARY KEY (case_status_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cashier_invoice_lines_pkey' AND conrelid = 'public.cashier_invoice_lines'::regclass) THEN
    ALTER TABLE ONLY public.cashier_invoice_lines ADD CONSTRAINT cashier_invoice_lines_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cashier_invoices_pkey' AND conrelid = 'public.cashier_invoices'::regclass) THEN
    ALTER TABLE ONLY public.cashier_invoices ADD CONSTRAINT cashier_invoices_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'companies_pkey' AND conrelid = 'public.companies'::regclass) THEN
    ALTER TABLE ONLY public.companies ADD CONSTRAINT companies_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'crm_attachments_pkey' AND conrelid = 'public.crm_attachments'::regclass) THEN
    ALTER TABLE ONLY public.crm_attachments ADD CONSTRAINT crm_attachments_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'customers_pkey' AND conrelid = 'public.customers'::regclass) THEN
    ALTER TABLE ONLY public.customers ADD CONSTRAINT customers_pkey PRIMARY KEY (customer_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'daily_followups_pkey' AND conrelid = 'public.daily_followups'::regclass) THEN
    ALTER TABLE ONLY public.daily_followups ADD CONSTRAINT daily_followups_pkey PRIMARY KEY (daily_followup_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'employees_pkey' AND conrelid = 'public.employees'::regclass) THEN
    ALTER TABLE ONLY public.employees ADD CONSTRAINT employees_pkey PRIMARY KEY (employee_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'permissions_permission_code_key' AND conrelid = 'public.permissions'::regclass) THEN
    ALTER TABLE ONLY public.permissions ADD CONSTRAINT permissions_permission_code_key UNIQUE (permission_code);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'permissions_pkey' AND conrelid = 'public.permissions'::regclass) THEN
    ALTER TABLE ONLY public.permissions ADD CONSTRAINT permissions_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_sales_invoice_audit_logs' AND conrelid = 'public.sales_invoice_audit_logs'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoice_audit_logs ADD CONSTRAINT pk_sales_invoice_audit_logs PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_sales_invoice_lines' AND conrelid = 'public.sales_invoice_lines'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoice_lines ADD CONSTRAINT pk_sales_invoice_lines PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_sales_invoice_zatca_data' AND conrelid = 'public.sales_invoice_zatca_data'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoice_zatca_data ADD CONSTRAINT pk_sales_invoice_zatca_data PRIMARY KEY (invoice_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_sales_invoice_zatca_submissions' AND conrelid = 'public.sales_invoice_zatca_submissions'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoice_zatca_submissions ADD CONSTRAINT pk_sales_invoice_zatca_submissions PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_sales_invoices' AND conrelid = 'public.sales_invoices'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoices ADD CONSTRAINT pk_sales_invoices PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'places_pkey' AND conrelid = 'public.places'::regclass) THEN
    ALTER TABLE ONLY public.places ADD CONSTRAINT places_pkey PRIMARY KEY (place_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'products_pkey' AND conrelid = 'public.products'::regclass) THEN
    ALTER TABLE ONLY public.products ADD CONSTRAINT products_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'receipt_vouchers_pkey' AND conrelid = 'public.receipt_vouchers'::regclass) THEN
    ALTER TABLE ONLY public.receipt_vouchers ADD CONSTRAINT receipt_vouchers_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'role_permissions_pkey' AND conrelid = 'public.role_permissions'::regclass) THEN
    ALTER TABLE ONLY public.role_permissions ADD CONSTRAINT role_permissions_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'role_permissions_role_id_permission_id_key' AND conrelid = 'public.role_permissions'::regclass) THEN
    ALTER TABLE ONLY public.role_permissions ADD CONSTRAINT role_permissions_role_id_permission_id_key UNIQUE (role_id, permission_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roles_pkey' AND conrelid = 'public.roles'::regclass) THEN
    ALTER TABLE ONLY public.roles ADD CONSTRAINT roles_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roles_role_code_key' AND conrelid = 'public.roles'::regclass) THEN
    ALTER TABLE ONLY public.roles ADD CONSTRAINT roles_role_code_key UNIQUE (role_code);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_cashier_invoice_lines_invoice_line' AND conrelid = 'public.cashier_invoice_lines'::regclass) THEN
    ALTER TABLE ONLY public.cashier_invoice_lines ADD CONSTRAINT uq_cashier_invoice_lines_invoice_line UNIQUE (cashier_invoice_id, line_number);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_sales_invoice_lines_invoice_line' AND conrelid = 'public.sales_invoice_lines'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoice_lines ADD CONSTRAINT uq_sales_invoice_lines_invoice_line UNIQUE (invoice_id, line_number);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_sales_invoice_zatca_data_uuid' AND conrelid = 'public.sales_invoice_zatca_data'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoice_zatca_data ADD CONSTRAINT uq_sales_invoice_zatca_data_uuid UNIQUE (uuid);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_sales_invoice_zatca_submissions_attempt' AND conrelid = 'public.sales_invoice_zatca_submissions'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoice_zatca_submissions ADD CONSTRAINT uq_sales_invoice_zatca_submissions_attempt UNIQUE (invoice_id, operation, attempt_number);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_login_logs_pkey' AND conrelid = 'public.user_login_logs'::regclass) THEN
    ALTER TABLE ONLY public.user_login_logs ADD CONSTRAINT user_login_logs_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_permissions_pkey' AND conrelid = 'public.user_permissions'::regclass) THEN
    ALTER TABLE ONLY public.user_permissions ADD CONSTRAINT user_permissions_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_permissions_user_id_permission_id_key' AND conrelid = 'public.user_permissions'::regclass) THEN
    ALTER TABLE ONLY public.user_permissions ADD CONSTRAINT user_permissions_user_id_permission_id_key UNIQUE (user_id, permission_id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_backup_logs_backup_type ON public.backup_logs USING btree (backup_type);

CREATE INDEX IF NOT EXISTS idx_backup_logs_created_at ON public.backup_logs USING btree (created_at);

CREATE INDEX IF NOT EXISTS idx_backup_logs_status ON public.backup_logs USING btree (status);

CREATE INDEX IF NOT EXISTS idx_case_statuses_name ON public.case_statuses USING btree (case_status_name);

CREATE INDEX IF NOT EXISTS idx_cashier_invoice_lines_cashier_invoice_id ON public.cashier_invoice_lines USING btree (cashier_invoice_id);

CREATE INDEX IF NOT EXISTS idx_cashier_invoice_lines_product_id ON public.cashier_invoice_lines USING btree (product_id);

CREATE INDEX IF NOT EXISTS idx_cashier_invoices_branch_id ON public.cashier_invoices USING btree (branch_id);

CREATE INDEX IF NOT EXISTS idx_cashier_invoices_company_id ON public.cashier_invoices USING btree (company_id);

CREATE INDEX IF NOT EXISTS idx_cashier_invoices_created_by_user_id ON public.cashier_invoices USING btree (created_by_user_id);

CREATE INDEX IF NOT EXISTS idx_cashier_invoices_customer_id ON public.cashier_invoices USING btree (customer_id);

CREATE INDEX IF NOT EXISTS idx_cashier_invoices_invoice_date ON public.cashier_invoices USING btree (invoice_date);

CREATE INDEX IF NOT EXISTS idx_cashier_invoices_invoice_status ON public.cashier_invoices USING btree (invoice_status);

CREATE INDEX IF NOT EXISTS idx_cashier_invoices_zatca_status ON public.cashier_invoices USING btree (zatca_status);

CREATE INDEX IF NOT EXISTS idx_companies_name_ar ON public.companies USING btree (name_ar);

CREATE INDEX IF NOT EXISTS idx_companies_name_ar_trgm ON public.companies USING gin (name_ar public.gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_crm_attachments_category ON public.crm_attachments USING btree (category);

CREATE UNIQUE INDEX IF NOT EXISTS idx_crm_attachments_code ON public.crm_attachments USING btree (attachment_code);

CREATE INDEX IF NOT EXISTS idx_crm_attachments_created_at ON public.crm_attachments USING btree (created_at);

CREATE INDEX IF NOT EXISTS idx_crm_attachments_entity_id ON public.crm_attachments USING btree (entity_id);

CREATE INDEX IF NOT EXISTS idx_crm_attachments_entity_type ON public.crm_attachments USING btree (entity_type);

CREATE INDEX IF NOT EXISTS idx_crm_attachments_file_hash ON public.crm_attachments USING btree (file_hash);

CREATE INDEX IF NOT EXISTS idx_customers_area_number ON public.customers USING btree (area_number);

CREATE INDEX IF NOT EXISTS idx_customers_name ON public.customers USING btree (customer_name);

CREATE INDEX IF NOT EXISTS idx_customers_name_trgm ON public.customers USING gin (customer_name public.gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_customers_phone_number ON public.customers USING btree (phone_number);

CREATE INDEX IF NOT EXISTS idx_customers_phone_trgm ON public.customers USING gin (phone_number public.gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_customers_vat_number ON public.customers USING btree (vat_number);

CREATE INDEX IF NOT EXISTS idx_daily_followups_buyer_name ON public.daily_followups USING btree (buyer_name);

CREATE INDEX IF NOT EXISTS idx_daily_followups_case_status_id ON public.daily_followups USING btree (case_status_id);

CREATE INDEX IF NOT EXISTS idx_daily_followups_customer_id ON public.daily_followups USING btree (customer_id);

CREATE INDEX IF NOT EXISTS idx_daily_followups_customer_name ON public.daily_followups USING btree (buyer_name);

CREATE INDEX IF NOT EXISTS idx_daily_followups_employee_id ON public.daily_followups USING btree (employee_id);

CREATE INDEX IF NOT EXISTS idx_daily_followups_follow_up_date ON public.daily_followups USING btree (follow_up_date);

CREATE INDEX IF NOT EXISTS idx_daily_followups_notes_trgm ON public.daily_followups USING gin (notes public.gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_daily_followups_year_month ON public.daily_followups USING btree (follow_up_year, follow_up_month);

CREATE INDEX IF NOT EXISTS idx_employees_name ON public.employees USING btree (employee_name);

CREATE INDEX IF NOT EXISTS idx_employees_name_trgm ON public.employees USING gin (employee_name public.gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_employees_phone ON public.employees USING btree (phone_number);

CREATE INDEX IF NOT EXISTS idx_login_logs_user ON public.user_login_logs USING btree (user_id);

CREATE INDEX IF NOT EXISTS idx_permissions_active ON public.permissions USING btree (is_active);

CREATE INDEX IF NOT EXISTS idx_places_number ON public.places USING btree (place_number);

CREATE INDEX IF NOT EXISTS idx_products_item_name ON public.products USING btree (item_name);

CREATE INDEX IF NOT EXISTS idx_products_item_name_trgm ON public.products USING gin (item_name public.gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_receipt_vouchers_company_id ON public.receipt_vouchers USING btree (company_id);

CREATE INDEX IF NOT EXISTS idx_receipt_vouchers_customer_id ON public.receipt_vouchers USING btree (customer_id);

CREATE INDEX IF NOT EXISTS idx_receipt_vouchers_payment_type ON public.receipt_vouchers USING btree (payment_type);

CREATE INDEX IF NOT EXISTS idx_receipt_vouchers_voucher_date ON public.receipt_vouchers USING btree (voucher_date);

CREATE INDEX IF NOT EXISTS idx_role_permissions_role ON public.role_permissions USING btree (role_id);

CREATE INDEX IF NOT EXISTS idx_user_permissions_user ON public.user_permissions USING btree (user_id);

CREATE INDEX IF NOT EXISTS ix_sales_invoice_audit_logs_action ON public.sales_invoice_audit_logs USING btree (action);

CREATE INDEX IF NOT EXISTS ix_sales_invoice_audit_logs_batch_id ON public.sales_invoice_audit_logs USING btree (batch_id);

CREATE INDEX IF NOT EXISTS ix_sales_invoice_audit_logs_invoice_id ON public.sales_invoice_audit_logs USING btree (invoice_id);

CREATE INDEX IF NOT EXISTS ix_sales_invoice_audit_logs_performed_at ON public.sales_invoice_audit_logs USING btree (performed_at);

CREATE INDEX IF NOT EXISTS ix_sales_invoice_audit_logs_performed_by ON public.sales_invoice_audit_logs USING btree (performed_by);

CREATE INDEX IF NOT EXISTS ix_sales_invoice_lines_invoice_id ON public.sales_invoice_lines USING btree (invoice_id);

CREATE INDEX IF NOT EXISTS ix_sales_invoice_lines_product_id ON public.sales_invoice_lines USING btree (product_id);

CREATE INDEX IF NOT EXISTS ix_sales_invoice_zatca_data_device_counter ON public.sales_invoice_zatca_data USING btree (device_id, invoice_counter_value);

CREATE INDEX IF NOT EXISTS ix_sales_invoice_zatca_data_integration_status ON public.sales_invoice_zatca_data USING btree (integration_status);

CREATE INDEX IF NOT EXISTS ix_sales_invoice_zatca_data_invoice_hash ON public.sales_invoice_zatca_data USING btree (invoice_hash);

CREATE INDEX IF NOT EXISTS ix_sales_invoice_zatca_data_submitted_at ON public.sales_invoice_zatca_data USING btree (submitted_at);

CREATE INDEX IF NOT EXISTS ix_sales_invoice_zatca_submissions_invoice_id ON public.sales_invoice_zatca_submissions USING btree (invoice_id);

CREATE INDEX IF NOT EXISTS ix_sales_invoice_zatca_submissions_is_success ON public.sales_invoice_zatca_submissions USING btree (is_success);

CREATE INDEX IF NOT EXISTS ix_sales_invoice_zatca_submissions_operation ON public.sales_invoice_zatca_submissions USING btree (operation);

CREATE INDEX IF NOT EXISTS ix_sales_invoice_zatca_submissions_requested_at ON public.sales_invoice_zatca_submissions USING btree (requested_at);

CREATE INDEX IF NOT EXISTS ix_sales_invoices_company_status_issued ON public.sales_invoices USING btree (seller_company_id, document_status, issue_datetime);

CREATE INDEX IF NOT EXISTS ix_sales_invoices_customer_id ON public.sales_invoices USING btree (customer_id);

CREATE INDEX IF NOT EXISTS ix_sales_invoices_document_status ON public.sales_invoices USING btree (document_status);

CREATE INDEX IF NOT EXISTS ix_sales_invoices_issue_datetime ON public.sales_invoices USING btree (issue_datetime);

CREATE INDEX IF NOT EXISTS ix_sales_invoices_seller_company_id ON public.sales_invoices USING btree (seller_company_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_cashier_invoices_invoice_number ON public.cashier_invoices USING btree (invoice_number);

CREATE UNIQUE INDEX IF NOT EXISTS uq_cashier_invoices_invoice_uuid ON public.cashier_invoices USING btree (invoice_uuid);

CREATE UNIQUE INDEX IF NOT EXISTS uq_companies_commercial_registration ON public.companies USING btree (commercial_registration);

CREATE UNIQUE INDEX IF NOT EXISTS uq_companies_vat_number ON public.companies USING btree (vat_number);

CREATE UNIQUE INDEX IF NOT EXISTS uq_products_item_code ON public.products USING btree (item_code);

CREATE UNIQUE INDEX IF NOT EXISTS uq_receipt_vouchers_voucher_number ON public.receipt_vouchers USING btree (voucher_number);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_invoice_audit_logs_log_hash ON public.sales_invoice_audit_logs USING btree (log_hash) WHERE (log_hash IS NOT NULL);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_invoice_zatca_device_counter ON public.sales_invoice_zatca_data USING btree (device_id, invoice_counter_value) WHERE ((device_id IS NOT NULL) AND (invoice_counter_value IS NOT NULL));

CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_invoices_invoice_number ON public.sales_invoices USING btree (invoice_number);

DROP TRIGGER IF EXISTS trg_cashier_invoice_lines_set_updated_at ON public.cashier_invoice_lines;
CREATE TRIGGER trg_cashier_invoice_lines_set_updated_at BEFORE UPDATE ON public.cashier_invoice_lines FOR EACH ROW EXECUTE FUNCTION public.cashier_invoice_lines_set_updated_at();

DROP TRIGGER IF EXISTS trg_cashier_invoices_set_updated_at ON public.cashier_invoices;
CREATE TRIGGER trg_cashier_invoices_set_updated_at BEFORE UPDATE ON public.cashier_invoices FOR EACH ROW EXECUTE FUNCTION public.cashier_invoices_set_updated_at();

DROP TRIGGER IF EXISTS trg_companies_normalize ON public.companies;
CREATE TRIGGER trg_companies_normalize BEFORE INSERT OR UPDATE ON public.companies FOR EACH ROW EXECUTE FUNCTION public.companies_normalize();

DROP TRIGGER IF EXISTS trg_products_set_updated_at ON public.products;
CREATE TRIGGER trg_products_set_updated_at BEFORE UPDATE ON public.products FOR EACH ROW EXECUTE FUNCTION public.products_set_updated_at();

DROP TRIGGER IF EXISTS trg_receipt_vouchers_set_updated_at ON public.receipt_vouchers;
CREATE TRIGGER trg_receipt_vouchers_set_updated_at BEFORE UPDATE ON public.receipt_vouchers FOR EACH ROW EXECUTE FUNCTION public.receipt_vouchers_set_updated_at();

DROP TRIGGER IF EXISTS trg_sales_invoice_lines_updated_at ON public.sales_invoice_lines;
CREATE TRIGGER trg_sales_invoice_lines_updated_at BEFORE UPDATE ON public.sales_invoice_lines FOR EACH ROW EXECUTE FUNCTION public.sales_set_updated_at();

DROP TRIGGER IF EXISTS trg_sales_invoice_zatca_data_updated_at ON public.sales_invoice_zatca_data;
CREATE TRIGGER trg_sales_invoice_zatca_data_updated_at BEFORE UPDATE ON public.sales_invoice_zatca_data FOR EACH ROW EXECUTE FUNCTION public.sales_set_updated_at();

DROP TRIGGER IF EXISTS trg_sales_invoices_updated_at ON public.sales_invoices;
CREATE TRIGGER trg_sales_invoices_updated_at BEFORE UPDATE ON public.sales_invoices FOR EACH ROW EXECUTE FUNCTION public.sales_set_updated_at();

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'app_users_role_id_fkey' AND conrelid = 'public.app_users'::regclass) THEN
    ALTER TABLE ONLY public.app_users ADD CONSTRAINT app_users_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_cashier_invoice_lines_invoice' AND conrelid = 'public.cashier_invoice_lines'::regclass) THEN
    ALTER TABLE ONLY public.cashier_invoice_lines ADD CONSTRAINT fk_cashier_invoice_lines_invoice FOREIGN KEY (cashier_invoice_id) REFERENCES public.cashier_invoices(id) ON UPDATE CASCADE ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_cashier_invoice_lines_product' AND conrelid = 'public.cashier_invoice_lines'::regclass) THEN
    ALTER TABLE ONLY public.cashier_invoice_lines ADD CONSTRAINT fk_cashier_invoice_lines_product FOREIGN KEY (product_id) REFERENCES public.products(id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_cashier_invoices_company' AND conrelid = 'public.cashier_invoices'::regclass) THEN
    ALTER TABLE ONLY public.cashier_invoices ADD CONSTRAINT fk_cashier_invoices_company FOREIGN KEY (company_id) REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_cashier_invoices_created_by_user' AND conrelid = 'public.cashier_invoices'::regclass) THEN
    ALTER TABLE ONLY public.cashier_invoices ADD CONSTRAINT fk_cashier_invoices_created_by_user FOREIGN KEY (created_by_user_id) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_cashier_invoices_customer' AND conrelid = 'public.cashier_invoices'::regclass) THEN
    ALTER TABLE ONLY public.cashier_invoices ADD CONSTRAINT fk_cashier_invoices_customer FOREIGN KEY (customer_id) REFERENCES public.customers(customer_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_daily_followups_case_status' AND conrelid = 'public.daily_followups'::regclass) THEN
    ALTER TABLE ONLY public.daily_followups ADD CONSTRAINT fk_daily_followups_case_status FOREIGN KEY (case_status_id) REFERENCES public.case_statuses(case_status_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_daily_followups_customer' AND conrelid = 'public.daily_followups'::regclass) THEN
    ALTER TABLE ONLY public.daily_followups ADD CONSTRAINT fk_daily_followups_customer FOREIGN KEY (customer_id) REFERENCES public.customers(customer_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_daily_followups_employee' AND conrelid = 'public.daily_followups'::regclass) THEN
    ALTER TABLE ONLY public.daily_followups ADD CONSTRAINT fk_daily_followups_employee FOREIGN KEY (employee_id) REFERENCES public.employees(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_receipt_vouchers_company' AND conrelid = 'public.receipt_vouchers'::regclass) THEN
    ALTER TABLE ONLY public.receipt_vouchers ADD CONSTRAINT fk_receipt_vouchers_company FOREIGN KEY (company_id) REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_receipt_vouchers_created_by' AND conrelid = 'public.receipt_vouchers'::regclass) THEN
    ALTER TABLE ONLY public.receipt_vouchers ADD CONSTRAINT fk_receipt_vouchers_created_by FOREIGN KEY (created_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_receipt_vouchers_customer' AND conrelid = 'public.receipt_vouchers'::regclass) THEN
    ALTER TABLE ONLY public.receipt_vouchers ADD CONSTRAINT fk_receipt_vouchers_customer FOREIGN KEY (customer_id) REFERENCES public.customers(customer_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_receipt_vouchers_updated_by' AND conrelid = 'public.receipt_vouchers'::regclass) THEN
    ALTER TABLE ONLY public.receipt_vouchers ADD CONSTRAINT fk_receipt_vouchers_updated_by FOREIGN KEY (updated_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sales_invoice_audit_logs_invoice_id_sales_invoices' AND conrelid = 'public.sales_invoice_audit_logs'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoice_audit_logs ADD CONSTRAINT fk_sales_invoice_audit_logs_invoice_id_sales_invoices FOREIGN KEY (invoice_id) REFERENCES public.sales_invoices(id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sales_invoice_audit_logs_performed_by_app_users' AND conrelid = 'public.sales_invoice_audit_logs'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoice_audit_logs ADD CONSTRAINT fk_sales_invoice_audit_logs_performed_by_app_users FOREIGN KEY (performed_by) REFERENCES public.app_users(id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sales_invoice_lines_invoice_id_sales_invoices' AND conrelid = 'public.sales_invoice_lines'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoice_lines ADD CONSTRAINT fk_sales_invoice_lines_invoice_id_sales_invoices FOREIGN KEY (invoice_id) REFERENCES public.sales_invoices(id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sales_invoice_lines_product_id_products' AND conrelid = 'public.sales_invoice_lines'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoice_lines ADD CONSTRAINT fk_sales_invoice_lines_product_id_products FOREIGN KEY (product_id) REFERENCES public.products(id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sales_invoice_zatca_data_invoice_id_sales_invoices' AND conrelid = 'public.sales_invoice_zatca_data'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoice_zatca_data ADD CONSTRAINT fk_sales_invoice_zatca_data_invoice_id_sales_invoices FOREIGN KEY (invoice_id) REFERENCES public.sales_invoices(id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sales_invoice_zatca_submissions_invoice_id_sales_invoices' AND conrelid = 'public.sales_invoice_zatca_submissions'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoice_zatca_submissions ADD CONSTRAINT fk_sales_invoice_zatca_submissions_invoice_id_sales_invoices FOREIGN KEY (invoice_id) REFERENCES public.sales_invoices(id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sales_invoices_approved_by_app_users' AND conrelid = 'public.sales_invoices'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoices ADD CONSTRAINT fk_sales_invoices_approved_by_app_users FOREIGN KEY (approved_by) REFERENCES public.app_users(id) ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sales_invoices_created_by_app_users' AND conrelid = 'public.sales_invoices'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoices ADD CONSTRAINT fk_sales_invoices_created_by_app_users FOREIGN KEY (created_by) REFERENCES public.app_users(id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sales_invoices_customer_id_customers' AND conrelid = 'public.sales_invoices'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoices ADD CONSTRAINT fk_sales_invoices_customer_id_customers FOREIGN KEY (customer_id) REFERENCES public.customers(customer_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sales_invoices_seller_company_id_companies' AND conrelid = 'public.sales_invoices'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoices ADD CONSTRAINT fk_sales_invoices_seller_company_id_companies FOREIGN KEY (seller_company_id) REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sales_invoices_updated_by_app_users' AND conrelid = 'public.sales_invoices'::regclass) THEN
    ALTER TABLE ONLY public.sales_invoices ADD CONSTRAINT fk_sales_invoices_updated_by_app_users FOREIGN KEY (updated_by) REFERENCES public.app_users(id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'role_permissions_permission_id_fkey' AND conrelid = 'public.role_permissions'::regclass) THEN
    ALTER TABLE ONLY public.role_permissions ADD CONSTRAINT role_permissions_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'role_permissions_role_id_fkey' AND conrelid = 'public.role_permissions'::regclass) THEN
    ALTER TABLE ONLY public.role_permissions ADD CONSTRAINT role_permissions_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_login_logs_user_id_fkey' AND conrelid = 'public.user_login_logs'::regclass) THEN
    ALTER TABLE ONLY public.user_login_logs ADD CONSTRAINT user_login_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_users(id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_permissions_permission_id_fkey' AND conrelid = 'public.user_permissions'::regclass) THEN
    ALTER TABLE ONLY public.user_permissions ADD CONSTRAINT user_permissions_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_permissions_user_id_fkey' AND conrelid = 'public.user_permissions'::regclass) THEN
    ALTER TABLE ONLY public.user_permissions ADD CONSTRAINT user_permissions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_users(id) ON DELETE CASCADE;
  END IF;
END $$;

-- Added post-dump (migration 023): supplier payment vouchers (سندات صرف الموردين).
-- Money PAID to a supplier. voucher_number is auto-numbered by the DB DEFAULT as
-- ``Paid - Sub-01``, ``Paid - Sub-02``, ... (never MAX+1); supplier_id is a
-- RESTRICT FK to suppliers. This whole block is idempotent and self-contained.
CREATE SEQUENCE IF NOT EXISTS public.supplier_payment_voucher_number_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.supplier_payment_vouchers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS public.supplier_payment_vouchers (
    id integer DEFAULT nextval('public.supplier_payment_vouchers_id_seq'::regclass) NOT NULL,
    voucher_number character varying(40) NOT NULL,
    voucher_date date DEFAULT CURRENT_DATE NOT NULL,
    supplier_id integer NOT NULL,
    amount numeric(18,2) DEFAULT 0 NOT NULL,
    description text,
    CONSTRAINT ck_supplier_payment_vouchers_amount_positive CHECK ((amount > (0)::numeric)),
    CONSTRAINT ck_supplier_payment_vouchers_voucher_number_not_blank CHECK ((char_length(btrim((voucher_number)::text)) > 0))
);

ALTER SEQUENCE public.supplier_payment_vouchers_id_seq OWNED BY public.supplier_payment_vouchers.id;
ALTER SEQUENCE public.supplier_payment_voucher_number_seq OWNED BY public.supplier_payment_vouchers.voucher_number;

ALTER TABLE ONLY public.supplier_payment_vouchers
    ALTER COLUMN voucher_number SET DEFAULT ('Paid - Sub-'::text || to_char(nextval('public.supplier_payment_voucher_number_seq'::regclass), 'FM00'::text));

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'supplier_payment_vouchers_pkey' AND conrelid = 'public.supplier_payment_vouchers'::regclass) THEN
    ALTER TABLE ONLY public.supplier_payment_vouchers ADD CONSTRAINT supplier_payment_vouchers_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_supplier_payment_vouchers_supplier' AND conrelid = 'public.supplier_payment_vouchers'::regclass) THEN
    ALTER TABLE ONLY public.supplier_payment_vouchers ADD CONSTRAINT fk_supplier_payment_vouchers_supplier FOREIGN KEY (supplier_id) REFERENCES public.suppliers(supplier_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_supplier_payment_vouchers_voucher_number ON public.supplier_payment_vouchers USING btree (voucher_number);
CREATE INDEX IF NOT EXISTS idx_supplier_payment_vouchers_supplier ON public.supplier_payment_vouchers USING btree (supplier_id);
CREATE INDEX IF NOT EXISTS idx_supplier_payment_vouchers_date ON public.supplier_payment_vouchers USING btree (voucher_date);

-- Added post-dump (migration 025): worker daily wage-sheet (يومية العمال). The
-- daily_salary (days × wage) and balance (salary − cash) columns are STORED
-- generated columns — never written by the app. worker_id is a RESTRICT FK to
-- workers. This whole block is idempotent and self-contained.
CREATE SEQUENCE IF NOT EXISTS public.worker_daily_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS public.worker_daily (
    id integer DEFAULT nextval('public.worker_daily_id_seq'::regclass) NOT NULL,
    movement_date date DEFAULT CURRENT_DATE NOT NULL,
    worker_id integer NOT NULL,
    statement text,
    number_of_days numeric(18,2) DEFAULT 0 NOT NULL,
    daily_wage numeric(18,2) DEFAULT 0 NOT NULL,
    daily_salary numeric(20,4) GENERATED ALWAYS AS ((number_of_days * daily_wage)) STORED,
    cash numeric(18,2) DEFAULT 0 NOT NULL,
    balance numeric(20,4) GENERATED ALWAYS AS (((number_of_days * daily_wage) - cash)) STORED,
    CONSTRAINT ck_worker_daily_days_non_negative CHECK ((number_of_days >= (0)::numeric)),
    CONSTRAINT ck_worker_daily_wage_non_negative CHECK ((daily_wage >= (0)::numeric))
);

ALTER SEQUENCE public.worker_daily_id_seq OWNED BY public.worker_daily.id;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'worker_daily_pkey' AND conrelid = 'public.worker_daily'::regclass) THEN
    ALTER TABLE ONLY public.worker_daily ADD CONSTRAINT worker_daily_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_worker_daily_worker' AND conrelid = 'public.worker_daily'::regclass) THEN
    ALTER TABLE ONLY public.worker_daily ADD CONSTRAINT fk_worker_daily_worker FOREIGN KEY (worker_id) REFERENCES public.workers(worker_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_worker_daily_worker ON public.worker_daily USING btree (worker_id);
CREATE INDEX IF NOT EXISTS idx_worker_daily_date ON public.worker_daily USING btree (movement_date);

-- Added post-dump (migration 026): worker payment vouchers (سندات صرف العمال).
-- Money PAID to a worker. voucher_number is auto-numbered by the DB DEFAULT as
-- ``Paid - Wrk-01``, ``Paid - Wrk-02``, ... (never MAX+1); worker_id is a
-- RESTRICT FK to workers. Mirrors supplier_payment_vouchers exactly. This whole
-- block is idempotent and self-contained.
CREATE SEQUENCE IF NOT EXISTS public.worker_payment_voucher_number_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.worker_payment_vouchers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS public.worker_payment_vouchers (
    id integer DEFAULT nextval('public.worker_payment_vouchers_id_seq'::regclass) NOT NULL,
    voucher_number character varying(40) NOT NULL,
    voucher_date date DEFAULT CURRENT_DATE NOT NULL,
    worker_id integer NOT NULL,
    amount numeric(18,2) DEFAULT 0 NOT NULL,
    description text,
    CONSTRAINT ck_worker_payment_vouchers_amount_positive CHECK ((amount > (0)::numeric)),
    CONSTRAINT ck_worker_payment_vouchers_voucher_number_not_blank CHECK ((char_length(btrim((voucher_number)::text)) > 0))
);

ALTER SEQUENCE public.worker_payment_vouchers_id_seq OWNED BY public.worker_payment_vouchers.id;
ALTER SEQUENCE public.worker_payment_voucher_number_seq OWNED BY public.worker_payment_vouchers.voucher_number;

ALTER TABLE ONLY public.worker_payment_vouchers
    ALTER COLUMN voucher_number SET DEFAULT ('Paid - Wrk-'::text || to_char(nextval('public.worker_payment_voucher_number_seq'::regclass), 'FM00'::text));

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'worker_payment_vouchers_pkey' AND conrelid = 'public.worker_payment_vouchers'::regclass) THEN
    ALTER TABLE ONLY public.worker_payment_vouchers ADD CONSTRAINT worker_payment_vouchers_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_worker_payment_vouchers_worker' AND conrelid = 'public.worker_payment_vouchers'::regclass) THEN
    ALTER TABLE ONLY public.worker_payment_vouchers ADD CONSTRAINT fk_worker_payment_vouchers_worker FOREIGN KEY (worker_id) REFERENCES public.workers(worker_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_worker_payment_vouchers_voucher_number ON public.worker_payment_vouchers USING btree (voucher_number);
CREATE INDEX IF NOT EXISTS idx_worker_payment_vouchers_worker ON public.worker_payment_vouchers USING btree (worker_id);
CREATE INDEX IF NOT EXISTS idx_worker_payment_vouchers_date ON public.worker_payment_vouchers USING btree (voucher_date);

-- Added post-dump (migration 027): treasury deposits (إضافة أموال للخزينة).
-- Money added INTO the treasury/cashbox. The id doubles as the user-facing
-- رقم الحركة and its sequence starts at 3001 (first movement 3001, then 3002...).
-- This whole block is idempotent and self-contained.
CREATE SEQUENCE IF NOT EXISTS public.treasury_deposits_id_seq
    START WITH 3001
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS public.treasury_deposits (
    id integer DEFAULT nextval('public.treasury_deposits_id_seq'::regclass) NOT NULL,
    movement_date date DEFAULT CURRENT_DATE NOT NULL,
    amount numeric(18,2) DEFAULT 0 NOT NULL,
    statement text,
    CONSTRAINT ck_treasury_deposits_amount_positive CHECK ((amount > (0)::numeric))
);

ALTER SEQUENCE public.treasury_deposits_id_seq OWNED BY public.treasury_deposits.id;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'treasury_deposits_pkey' AND conrelid = 'public.treasury_deposits'::regclass) THEN
    ALTER TABLE ONLY public.treasury_deposits ADD CONSTRAINT treasury_deposits_pkey PRIMARY KEY (id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_treasury_deposits_date ON public.treasury_deposits USING btree (movement_date);

-- ==========================================================================
-- Purchase invoices (فاتورة المشتريات) — added 2026-08-14
--
-- A count/weight-based purchase document. Mirrors the sales-invoice shape but
-- carries NO VAT, NO ZATCA/Phase-2 data and NO print pipeline. The counterparty
-- is a supplier (name snapshot from public.suppliers); line items are free text
-- (no products link). Per line the app stores the three computed money/weight
-- columns; the header carries the two invoice totals. Numbers are the global
-- "Pur-<seq>" series starting at Pur-1001. This whole block is idempotent and
-- self-contained; it reuses public.sales_set_updated_at() for the updated_at
-- triggers (that function only sets NEW.updated_at = now(), nothing sales-specific).
-- ==========================================================================

CREATE SEQUENCE IF NOT EXISTS public.purchase_invoice_number_seq
    START WITH 1001
    INCREMENT BY 1
    MINVALUE 1001
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS public.purchase_invoices (
    id bigint NOT NULL,
    invoice_number character varying(100) NOT NULL,
    issue_datetime timestamp with time zone DEFAULT now() NOT NULL,
    supplier_id integer NOT NULL,
    supplier_name_snapshot character varying(255) NOT NULL,
    payment_type character varying(20) NOT NULL,
    notes text,
    total_count_price numeric(18,2) DEFAULT 0 NOT NULL,
    total_weight_price numeric(18,2) DEFAULT 0 NOT NULL,
    document_status character varying(30) DEFAULT 'draft'::character varying NOT NULL,
    approved_at timestamp with time zone,
    approved_by integer,
    created_by integer,
    updated_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    row_version integer DEFAULT 1 NOT NULL,
    CONSTRAINT ck_purchase_invoices_document_status_valid CHECK (((document_status)::text = ANY ((ARRAY['draft'::character varying, 'approved'::character varying])::text[]))),
    CONSTRAINT ck_purchase_invoices_invoice_number_not_blank CHECK ((char_length(btrim((invoice_number)::text)) > 0)),
    CONSTRAINT ck_purchase_invoices_payment_type_valid CHECK (((payment_type)::text = ANY ((ARRAY['cash'::character varying, 'credit'::character varying])::text[]))),
    CONSTRAINT ck_purchase_invoices_total_count_price_nonnegative CHECK ((total_count_price >= (0)::numeric)),
    CONSTRAINT ck_purchase_invoices_total_weight_price_nonnegative CHECK ((total_weight_price >= (0)::numeric))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'public.purchase_invoices'::regclass AND attname = 'id' AND attidentity <> '') THEN
    ALTER TABLE public.purchase_invoices ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.purchase_invoices_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.purchase_invoice_lines (
    id bigint NOT NULL,
    invoice_id bigint NOT NULL,
    line_number integer NOT NULL,
    item_code_snapshot integer,
    item_name_snapshot character varying(255) NOT NULL,
    unit_snapshot character varying(50) DEFAULT ''::character varying NOT NULL,
    item_count numeric(18,6) NOT NULL,
    unit_weight numeric(18,6) DEFAULT 0 NOT NULL,
    total_weight numeric(18,6) DEFAULT 0 NOT NULL,
    unit_price numeric(18,6) DEFAULT 0 NOT NULL,
    count_price_total numeric(18,2) DEFAULT 0 NOT NULL,
    weight_price_total numeric(18,2) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_purchase_invoice_lines_line_number_positive CHECK ((line_number > 0)),
    CONSTRAINT ck_purchase_invoice_lines_item_count_positive CHECK ((item_count > (0)::numeric)),
    CONSTRAINT ck_purchase_invoice_lines_unit_weight_nonnegative CHECK ((unit_weight >= (0)::numeric)),
    CONSTRAINT ck_purchase_invoice_lines_total_weight_nonnegative CHECK ((total_weight >= (0)::numeric)),
    CONSTRAINT ck_purchase_invoice_lines_unit_price_nonnegative CHECK ((unit_price >= (0)::numeric)),
    CONSTRAINT ck_purchase_invoice_lines_count_price_total_nonnegative CHECK ((count_price_total >= (0)::numeric)),
    CONSTRAINT ck_purchase_invoice_lines_weight_price_total_nonnegative CHECK ((weight_price_total >= (0)::numeric))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'public.purchase_invoice_lines'::regclass AND attname = 'id' AND attidentity <> '') THEN
    ALTER TABLE public.purchase_invoice_lines ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.purchase_invoice_lines_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
  END IF;
END $$;

-- كود الصنف والوحدة على سطر الفاتورة — added to existing databases. Both are
-- snapshots captured at save time (like item_name_snapshot). item_code_snapshot
-- is nullable because a free-typed line need not carry a product code.
ALTER TABLE public.purchase_invoice_lines
    ADD COLUMN IF NOT EXISTS item_code_snapshot integer;
ALTER TABLE public.purchase_invoice_lines
    ADD COLUMN IF NOT EXISTS unit_snapshot character varying(50) DEFAULT ''::character varying NOT NULL;

CREATE TABLE IF NOT EXISTS public.purchase_invoice_audit_logs (
    id bigint NOT NULL,
    invoice_id bigint,
    invoice_number_snapshot character varying(100),
    supplier_id_snapshot bigint,
    action character varying(50) NOT NULL,
    old_status character varying(30),
    new_status character varying(30),
    performed_by integer,
    details jsonb,
    performed_at timestamp with time zone DEFAULT now() NOT NULL
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'public.purchase_invoice_audit_logs'::regclass AND attname = 'id' AND attidentity <> '') THEN
    ALTER TABLE public.purchase_invoice_audit_logs ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.purchase_invoice_audit_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
  END IF;
END $$;

-- Primary keys
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_purchase_invoices' AND conrelid = 'public.purchase_invoices'::regclass) THEN
    ALTER TABLE ONLY public.purchase_invoices ADD CONSTRAINT pk_purchase_invoices PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_purchase_invoice_lines' AND conrelid = 'public.purchase_invoice_lines'::regclass) THEN
    ALTER TABLE ONLY public.purchase_invoice_lines ADD CONSTRAINT pk_purchase_invoice_lines PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_purchase_invoice_audit_logs' AND conrelid = 'public.purchase_invoice_audit_logs'::regclass) THEN
    ALTER TABLE ONLY public.purchase_invoice_audit_logs ADD CONSTRAINT pk_purchase_invoice_audit_logs PRIMARY KEY (id);
  END IF;
END $$;

-- Unique constraints / indexes
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_purchase_invoice_lines_invoice_line' AND conrelid = 'public.purchase_invoice_lines'::regclass) THEN
    ALTER TABLE ONLY public.purchase_invoice_lines ADD CONSTRAINT uq_purchase_invoice_lines_invoice_line UNIQUE (invoice_id, line_number);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_purchase_invoices_invoice_number ON public.purchase_invoices USING btree (invoice_number);

-- Secondary indexes
CREATE INDEX IF NOT EXISTS ix_purchase_invoices_supplier_id ON public.purchase_invoices USING btree (supplier_id);
CREATE INDEX IF NOT EXISTS ix_purchase_invoices_document_status ON public.purchase_invoices USING btree (document_status);
CREATE INDEX IF NOT EXISTS ix_purchase_invoices_issue_datetime ON public.purchase_invoices USING btree (issue_datetime);
CREATE INDEX IF NOT EXISTS ix_purchase_invoice_lines_invoice_id ON public.purchase_invoice_lines USING btree (invoice_id);
CREATE INDEX IF NOT EXISTS ix_purchase_invoice_audit_logs_invoice_id ON public.purchase_invoice_audit_logs USING btree (invoice_id);
CREATE INDEX IF NOT EXISTS ix_purchase_invoice_audit_logs_performed_at ON public.purchase_invoice_audit_logs USING btree (performed_at);

-- Foreign keys
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_purchase_invoices_supplier_id_suppliers' AND conrelid = 'public.purchase_invoices'::regclass) THEN
    ALTER TABLE ONLY public.purchase_invoices ADD CONSTRAINT fk_purchase_invoices_supplier_id_suppliers FOREIGN KEY (supplier_id) REFERENCES public.suppliers(supplier_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_purchase_invoices_created_by_app_users' AND conrelid = 'public.purchase_invoices'::regclass) THEN
    ALTER TABLE ONLY public.purchase_invoices ADD CONSTRAINT fk_purchase_invoices_created_by_app_users FOREIGN KEY (created_by) REFERENCES public.app_users(id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_purchase_invoices_updated_by_app_users' AND conrelid = 'public.purchase_invoices'::regclass) THEN
    ALTER TABLE ONLY public.purchase_invoices ADD CONSTRAINT fk_purchase_invoices_updated_by_app_users FOREIGN KEY (updated_by) REFERENCES public.app_users(id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_purchase_invoices_approved_by_app_users' AND conrelid = 'public.purchase_invoices'::regclass) THEN
    ALTER TABLE ONLY public.purchase_invoices ADD CONSTRAINT fk_purchase_invoices_approved_by_app_users FOREIGN KEY (approved_by) REFERENCES public.app_users(id) ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_purchase_invoice_lines_invoice_id_purchase_invoices' AND conrelid = 'public.purchase_invoice_lines'::regclass) THEN
    ALTER TABLE ONLY public.purchase_invoice_lines ADD CONSTRAINT fk_purchase_invoice_lines_invoice_id_purchase_invoices FOREIGN KEY (invoice_id) REFERENCES public.purchase_invoices(id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_purchase_invoice_audit_logs_invoice_id_purchase_invoices' AND conrelid = 'public.purchase_invoice_audit_logs'::regclass) THEN
    ALTER TABLE ONLY public.purchase_invoice_audit_logs ADD CONSTRAINT fk_purchase_invoice_audit_logs_invoice_id_purchase_invoices FOREIGN KEY (invoice_id) REFERENCES public.purchase_invoices(id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_purchase_invoice_audit_logs_performed_by_app_users' AND conrelid = 'public.purchase_invoice_audit_logs'::regclass) THEN
    ALTER TABLE ONLY public.purchase_invoice_audit_logs ADD CONSTRAINT fk_purchase_invoice_audit_logs_performed_by_app_users FOREIGN KEY (performed_by) REFERENCES public.app_users(id) ON DELETE SET NULL;
  END IF;
END $$;

-- updated_at triggers (reuse the shared setter)
DROP TRIGGER IF EXISTS trg_purchase_invoices_updated_at ON public.purchase_invoices;
CREATE TRIGGER trg_purchase_invoices_updated_at BEFORE UPDATE ON public.purchase_invoices FOR EACH ROW EXECUTE FUNCTION public.sales_set_updated_at();

DROP TRIGGER IF EXISTS trg_purchase_invoice_lines_updated_at ON public.purchase_invoice_lines;
CREATE TRIGGER trg_purchase_invoice_lines_updated_at BEFORE UPDATE ON public.purchase_invoice_lines FOR EACH ROW EXECUTE FUNCTION public.sales_set_updated_at();


-- ==========================================================================
-- Bill of Materials (قائمة المواد) — added 2026-08-17
--
-- A simple material-cost document: a header (boms) naming the finished product
-- with an automatic "BOM-<seq>" number starting at BOM-0001, and its component
-- lines (bom_lines: item + quantity + price + a STORED generated line_total).
-- The header total_material_cost is the sum of the line totals, recomputed
-- server-side and stored. Both tables reference the existing public.products
-- table (finished product + component); no duplicate item master is created.
-- No labour / machine / routing / production-order / overhead / multi-level data.
-- This whole block is idempotent and self-contained; it defines its own
-- bom_set_updated_at() trigger function (shared with no other module).
-- ==========================================================================

CREATE SEQUENCE IF NOT EXISTS public.bom_number_seq
    AS bigint
    START WITH 1
    INCREMENT BY 1
    MINVALUE 1
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS public.boms (
    id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    bom_number character varying(30) DEFAULT ('BOM-'::text || to_char(nextval('public.bom_number_seq'::regclass), 'FM0000'::text)) NOT NULL,
    bom_date date DEFAULT CURRENT_DATE NOT NULL,
    product_id integer NOT NULL,
    product_name_snapshot character varying(200) NOT NULL,
    total_material_cost numeric(18,2) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer,
    updated_by integer,
    CONSTRAINT ck_boms_total_material_cost_nonnegative CHECK ((total_material_cost >= (0)::numeric)),
    CONSTRAINT ck_boms_bom_number_not_blank CHECK ((char_length(btrim((bom_number)::text)) > 0)),
    CONSTRAINT ck_boms_product_name_not_blank CHECK ((char_length(btrim((product_name_snapshot)::text)) > 0))
);

ALTER SEQUENCE public.bom_number_seq OWNED BY public.boms.bom_number;

CREATE TABLE IF NOT EXISTS public.bom_lines (
    id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    bom_id integer NOT NULL,
    line_number integer NOT NULL,
    component_product_id integer NOT NULL,
    item_code_snapshot integer,
    item_name_snapshot character varying(200) NOT NULL,
    unit_snapshot character varying(50) DEFAULT ''::character varying NOT NULL,
    quantity numeric(18,3) NOT NULL,
    price numeric(18,2) DEFAULT 0 NOT NULL,
    line_total numeric(23,5) GENERATED ALWAYS AS ((quantity * price)) STORED,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_bom_lines_line_number_positive CHECK ((line_number > 0)),
    CONSTRAINT ck_bom_lines_quantity_positive CHECK ((quantity > (0)::numeric)),
    CONSTRAINT ck_bom_lines_price_nonnegative CHECK ((price >= (0)::numeric)),
    CONSTRAINT ck_bom_lines_item_name_not_blank CHECK ((char_length(btrim((item_name_snapshot)::text)) > 0))
);

-- Primary keys
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_boms' AND conrelid = 'public.boms'::regclass) THEN
    ALTER TABLE ONLY public.boms ADD CONSTRAINT pk_boms PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_bom_lines' AND conrelid = 'public.bom_lines'::regclass) THEN
    ALTER TABLE ONLY public.bom_lines ADD CONSTRAINT pk_bom_lines PRIMARY KEY (id);
  END IF;
END $$;

-- Unique constraints / indexes
CREATE UNIQUE INDEX IF NOT EXISTS uq_boms_bom_number ON public.boms USING btree (bom_number);
CREATE UNIQUE INDEX IF NOT EXISTS uq_bom_lines_bom_line ON public.bom_lines USING btree (bom_id, line_number);
CREATE UNIQUE INDEX IF NOT EXISTS uq_bom_lines_bom_component ON public.bom_lines USING btree (bom_id, component_product_id);

-- Secondary indexes
CREATE INDEX IF NOT EXISTS idx_boms_bom_date ON public.boms USING btree (bom_date);
CREATE INDEX IF NOT EXISTS idx_boms_product_id ON public.boms USING btree (product_id);
CREATE INDEX IF NOT EXISTS idx_bom_lines_bom_id ON public.bom_lines USING btree (bom_id);
CREATE INDEX IF NOT EXISTS idx_bom_lines_component_product_id ON public.bom_lines USING btree (component_product_id);

-- Foreign keys
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_boms_product' AND conrelid = 'public.boms'::regclass) THEN
    ALTER TABLE ONLY public.boms ADD CONSTRAINT fk_boms_product FOREIGN KEY (product_id) REFERENCES public.products(id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_boms_created_by' AND conrelid = 'public.boms'::regclass) THEN
    ALTER TABLE ONLY public.boms ADD CONSTRAINT fk_boms_created_by FOREIGN KEY (created_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_boms_updated_by' AND conrelid = 'public.boms'::regclass) THEN
    ALTER TABLE ONLY public.boms ADD CONSTRAINT fk_boms_updated_by FOREIGN KEY (updated_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_bom_lines_bom' AND conrelid = 'public.bom_lines'::regclass) THEN
    ALTER TABLE ONLY public.bom_lines ADD CONSTRAINT fk_bom_lines_bom FOREIGN KEY (bom_id) REFERENCES public.boms(id) ON UPDATE CASCADE ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_bom_lines_component_product' AND conrelid = 'public.bom_lines'::regclass) THEN
    ALTER TABLE ONLY public.bom_lines ADD CONSTRAINT fk_bom_lines_component_product FOREIGN KEY (component_product_id) REFERENCES public.products(id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

-- updated_at trigger (BOM-specific setter; shared by both BOM tables)
CREATE OR REPLACE FUNCTION public.bom_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_boms_set_updated_at ON public.boms;
CREATE TRIGGER trg_boms_set_updated_at BEFORE UPDATE ON public.boms FOR EACH ROW EXECUTE FUNCTION public.bom_set_updated_at();

DROP TRIGGER IF EXISTS trg_bom_lines_set_updated_at ON public.bom_lines;
CREATE TRIGGER trg_bom_lines_set_updated_at BEFORE UPDATE ON public.bom_lines FOR EACH ROW EXECUTE FUNCTION public.bom_set_updated_at();


-- ==========================================================================
-- Production Order (أمر الإنتاج) — added 2026-08-17
--
-- A simple manufacturing document that consumes an existing BOM (قائمة المواد) to
-- work out the raw-material issue requirement for a finished product: a header
-- (production_orders) naming the finished product, the BOM actually used, the
-- date and the quantity to produce, with an automatic "PRO-<seq>" number starting
-- at PRO-001 (3-digit minimum padding -> grows past 999 to PRO-1000); and its
-- material lines (production_order_lines: component + bom_quantity_per_unit +
-- expected_quantity + editable actual_quantity + a STORED generated deviation =
-- actual - expected). No warehouse, no inventory posting, no cost total, no
-- labour / machine / routing / production-stage / overhead / approval workflow in
-- this version. The tables reference the existing public.products (finished
-- product + component) and public.boms (BOM consumed) tables; no duplicate
-- item / BOM master is created. This whole block is idempotent and
-- self-contained; it defines its own production_order_set_updated_at() trigger
-- function (shared with no other module).
-- ==========================================================================

CREATE SEQUENCE IF NOT EXISTS public.production_order_number_seq
    AS bigint
    START WITH 1
    INCREMENT BY 1
    MINVALUE 1
    NO MAXVALUE
    CACHE 1;

-- Order-number formatter: 'PRO-' + zero-padded sequence value, MINIMUM 3 digits,
-- unbounded growth (PRO-001 ... PRO-999, PRO-1000, ...). Identical to Python
-- format_number(). A fixed to_char mask (FM000) overflows to '###' past 3 digits,
-- so it was deliberately avoided.
CREATE OR REPLACE FUNCTION public.production_order_format_number(seq_value bigint)
    RETURNS text LANGUAGE sql IMMUTABLE AS
$$ SELECT 'PRO-' || lpad(seq_value::text, GREATEST(3, length(seq_value::text)), '0') $$;

CREATE TABLE IF NOT EXISTS public.production_orders (
    id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    order_number character varying(30) DEFAULT public.production_order_format_number(nextval('public.production_order_number_seq'::regclass)) NOT NULL,
    order_date date DEFAULT CURRENT_DATE NOT NULL,
    product_id integer NOT NULL,
    product_name_snapshot character varying(200) NOT NULL,
    bom_id integer NOT NULL,
    production_quantity numeric(18,3) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer,
    updated_by integer,
    CONSTRAINT ck_production_orders_quantity_positive CHECK ((production_quantity > (0)::numeric)),
    CONSTRAINT ck_production_orders_order_number_not_blank CHECK ((char_length(btrim((order_number)::text)) > 0)),
    CONSTRAINT ck_production_orders_product_name_not_blank CHECK ((char_length(btrim((product_name_snapshot)::text)) > 0))
);

ALTER SEQUENCE public.production_order_number_seq OWNED BY public.production_orders.order_number;

CREATE TABLE IF NOT EXISTS public.production_order_lines (
    id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    production_order_id integer NOT NULL,
    line_number integer NOT NULL,
    component_product_id integer NOT NULL,
    item_code_snapshot integer,
    item_name_snapshot character varying(200) NOT NULL,
    unit_snapshot character varying(50) DEFAULT ''::character varying NOT NULL,
    bom_quantity_per_unit numeric(18,3) NOT NULL,
    expected_quantity numeric(18,3) NOT NULL,
    actual_quantity numeric(18,3) NOT NULL,
    deviation numeric(19,3) GENERATED ALWAYS AS ((actual_quantity - expected_quantity)) STORED,
    bom_price_snapshot numeric(18,2) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_po_lines_line_number_positive CHECK ((line_number > 0)),
    CONSTRAINT ck_po_lines_bom_qty_per_unit_positive CHECK ((bom_quantity_per_unit > (0)::numeric)),
    CONSTRAINT ck_po_lines_expected_nonnegative CHECK ((expected_quantity >= (0)::numeric)),
    CONSTRAINT ck_po_lines_actual_nonnegative CHECK ((actual_quantity >= (0)::numeric)),
    CONSTRAINT ck_po_lines_bom_price_nonnegative CHECK ((bom_price_snapshot >= (0)::numeric)),
    CONSTRAINT ck_po_lines_item_name_not_blank CHECK ((char_length(btrim((item_name_snapshot)::text)) > 0))
);

-- Primary keys
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_production_orders' AND conrelid = 'public.production_orders'::regclass) THEN
    ALTER TABLE ONLY public.production_orders ADD CONSTRAINT pk_production_orders PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_production_order_lines' AND conrelid = 'public.production_order_lines'::regclass) THEN
    ALTER TABLE ONLY public.production_order_lines ADD CONSTRAINT pk_production_order_lines PRIMARY KEY (id);
  END IF;
END $$;

-- Unique constraints / indexes
CREATE UNIQUE INDEX IF NOT EXISTS uq_production_orders_order_number ON public.production_orders USING btree (order_number);
CREATE UNIQUE INDEX IF NOT EXISTS uq_po_lines_order_line ON public.production_order_lines USING btree (production_order_id, line_number);
CREATE UNIQUE INDEX IF NOT EXISTS uq_po_lines_order_component ON public.production_order_lines USING btree (production_order_id, component_product_id);

-- Secondary indexes
CREATE INDEX IF NOT EXISTS idx_production_orders_order_date ON public.production_orders USING btree (order_date);
CREATE INDEX IF NOT EXISTS idx_production_orders_product_id ON public.production_orders USING btree (product_id);
CREATE INDEX IF NOT EXISTS idx_production_orders_bom_id ON public.production_orders USING btree (bom_id);
CREATE INDEX IF NOT EXISTS idx_po_lines_order_id ON public.production_order_lines USING btree (production_order_id);
CREATE INDEX IF NOT EXISTS idx_po_lines_component_product_id ON public.production_order_lines USING btree (component_product_id);

-- Foreign keys
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_production_orders_product' AND conrelid = 'public.production_orders'::regclass) THEN
    ALTER TABLE ONLY public.production_orders ADD CONSTRAINT fk_production_orders_product FOREIGN KEY (product_id) REFERENCES public.products(id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_production_orders_bom' AND conrelid = 'public.production_orders'::regclass) THEN
    ALTER TABLE ONLY public.production_orders ADD CONSTRAINT fk_production_orders_bom FOREIGN KEY (bom_id) REFERENCES public.boms(id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_production_orders_created_by' AND conrelid = 'public.production_orders'::regclass) THEN
    ALTER TABLE ONLY public.production_orders ADD CONSTRAINT fk_production_orders_created_by FOREIGN KEY (created_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_production_orders_updated_by' AND conrelid = 'public.production_orders'::regclass) THEN
    ALTER TABLE ONLY public.production_orders ADD CONSTRAINT fk_production_orders_updated_by FOREIGN KEY (updated_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_po_lines_order' AND conrelid = 'public.production_order_lines'::regclass) THEN
    ALTER TABLE ONLY public.production_order_lines ADD CONSTRAINT fk_po_lines_order FOREIGN KEY (production_order_id) REFERENCES public.production_orders(id) ON UPDATE CASCADE ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_po_lines_component_product' AND conrelid = 'public.production_order_lines'::regclass) THEN
    ALTER TABLE ONLY public.production_order_lines ADD CONSTRAINT fk_po_lines_component_product FOREIGN KEY (component_product_id) REFERENCES public.products(id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

-- updated_at trigger (Production-Order-specific setter; shared by both PO tables)
CREATE OR REPLACE FUNCTION public.production_order_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_production_orders_set_updated_at ON public.production_orders;
CREATE TRIGGER trg_production_orders_set_updated_at BEFORE UPDATE ON public.production_orders FOR EACH ROW EXECUTE FUNCTION public.production_order_set_updated_at();

DROP TRIGGER IF EXISTS trg_po_lines_set_updated_at ON public.production_order_lines;
CREATE TRIGGER trg_po_lines_set_updated_at BEFORE UPDATE ON public.production_order_lines FOR EACH ROW EXECUTE FUNCTION public.production_order_set_updated_at();


-- ==========================================================================
-- Loading Voucher (سند تحميل) — added 2026-08-18
--
-- A simple single-item logistics document: one header row per voucher recording
-- that a quantity (in tons) of one item was loaded for a customer onto a vehicle
-- driven by a named driver at a given date/time, with an automatic "LV-<seq>"
-- number starting at LV-001 (3-digit minimum padding -> grows past 999 to
-- LV-1000). There is NO detail-line table (single item), no company link, no
-- document-status / approval workflow and no inventory posting in this version;
-- deletes are hard deletes. Driver name and vehicle number are free text (no
-- drivers / vehicles master exists yet). The table references the existing
-- public.customers (by customer_id) and public.products (by id) master tables;
-- no duplicate customer / item master is created, and *_snapshot columns freeze
-- the customer name and item code/name/unit at save time. This whole block is
-- idempotent and self-contained; it defines its own loading_voucher_set_updated_at()
-- trigger function (shared with no other module).
-- ==========================================================================

CREATE SEQUENCE IF NOT EXISTS public.loading_voucher_number_seq
    AS bigint
    START WITH 1
    INCREMENT BY 1
    MINVALUE 1
    NO MAXVALUE
    CACHE 1;

-- Voucher-number formatter: 'LV-' + zero-padded sequence value, MINIMUM 3 digits,
-- unbounded growth (LV-001 ... LV-999, LV-1000, ...). Identical to Python
-- format_number(). A fixed to_char mask (FM000) overflows to '###' past 3 digits,
-- so it was deliberately avoided.
CREATE OR REPLACE FUNCTION public.loading_voucher_format_number(seq_value bigint)
    RETURNS text LANGUAGE sql IMMUTABLE AS
$$ SELECT 'LV-' || lpad(seq_value::text, GREATEST(3, length(seq_value::text)), '0') $$;

CREATE TABLE IF NOT EXISTS public.loading_vouchers (
    id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    voucher_number character varying(30) DEFAULT public.loading_voucher_format_number(nextval('public.loading_voucher_number_seq'::regclass)) NOT NULL,
    voucher_date date DEFAULT CURRENT_DATE NOT NULL,
    voucher_time time without time zone DEFAULT localtime NOT NULL,
    customer_id integer,
    customer_name_snapshot character varying(150),
    driver_name character varying(150),
    vehicle_number character varying(50),
    weight_before_loading character varying(50),
    weight_after_loading character varying(50),
    product_id integer,
    item_code_snapshot integer,
    item_name_snapshot character varying(200),
    unit_snapshot character varying(50) DEFAULT ''::character varying NOT NULL,
    quantity_tons numeric(18,3),
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer,
    updated_by integer,
    CONSTRAINT ck_loading_vouchers_quantity_positive CHECK (((quantity_tons IS NULL) OR (quantity_tons > (0)::numeric))),
    CONSTRAINT ck_loading_vouchers_voucher_number_not_blank CHECK ((char_length(btrim((voucher_number)::text)) > 0))
);

ALTER SEQUENCE public.loading_voucher_number_seq OWNED BY public.loading_vouchers.voucher_number;

-- Additive columns for already-provisioned installs (idempotent; no-op on a fresh
-- table that already has them from the CREATE above). Vehicle weighbridge readings
-- before / after loading — FREE TEXT (varchar), so values like "500k" / "500 كجم"
-- are stored literally.
ALTER TABLE public.loading_vouchers ADD COLUMN IF NOT EXISTS weight_before_loading character varying(50);
ALTER TABLE public.loading_vouchers ADD COLUMN IF NOT EXISTS weight_after_loading character varying(50);

-- If an earlier build created these as numeric, convert them to free text so the
-- user's typed unit is preserved. Idempotent: the guard only fires while the
-- column is still numeric; existing numeric values become their text form.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'loading_vouchers'
               AND column_name = 'weight_before_loading' AND data_type = 'numeric') THEN
    ALTER TABLE public.loading_vouchers
      ALTER COLUMN weight_before_loading TYPE character varying(50)
      USING weight_before_loading::text;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'loading_vouchers'
               AND column_name = 'weight_after_loading' AND data_type = 'numeric') THEN
    ALTER TABLE public.loading_vouchers
      ALTER COLUMN weight_after_loading TYPE character varying(50)
      USING weight_after_loading::text;
  END IF;
END $$;

-- Primary key
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_loading_vouchers' AND conrelid = 'public.loading_vouchers'::regclass) THEN
    ALTER TABLE ONLY public.loading_vouchers ADD CONSTRAINT pk_loading_vouchers PRIMARY KEY (id);
  END IF;
END $$;

-- Unique constraints / indexes
CREATE UNIQUE INDEX IF NOT EXISTS uq_loading_vouchers_voucher_number ON public.loading_vouchers USING btree (voucher_number);

-- Secondary indexes
CREATE INDEX IF NOT EXISTS idx_loading_vouchers_voucher_date ON public.loading_vouchers USING btree (voucher_date);
CREATE INDEX IF NOT EXISTS idx_loading_vouchers_customer_id ON public.loading_vouchers USING btree (customer_id);
CREATE INDEX IF NOT EXISTS idx_loading_vouchers_product_id ON public.loading_vouchers USING btree (product_id);

-- Foreign keys
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_loading_vouchers_customer' AND conrelid = 'public.loading_vouchers'::regclass) THEN
    ALTER TABLE ONLY public.loading_vouchers ADD CONSTRAINT fk_loading_vouchers_customer FOREIGN KEY (customer_id) REFERENCES public.customers(customer_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_loading_vouchers_product' AND conrelid = 'public.loading_vouchers'::regclass) THEN
    ALTER TABLE ONLY public.loading_vouchers ADD CONSTRAINT fk_loading_vouchers_product FOREIGN KEY (product_id) REFERENCES public.products(id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_loading_vouchers_created_by' AND conrelid = 'public.loading_vouchers'::regclass) THEN
    ALTER TABLE ONLY public.loading_vouchers ADD CONSTRAINT fk_loading_vouchers_created_by FOREIGN KEY (created_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_loading_vouchers_updated_by' AND conrelid = 'public.loading_vouchers'::regclass) THEN
    ALTER TABLE ONLY public.loading_vouchers ADD CONSTRAINT fk_loading_vouchers_updated_by FOREIGN KEY (updated_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

-- updated_at trigger (Loading-Voucher-specific setter)
CREATE OR REPLACE FUNCTION public.loading_voucher_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_loading_vouchers_set_updated_at ON public.loading_vouchers;
CREATE TRIGGER trg_loading_vouchers_set_updated_at BEFORE UPDATE ON public.loading_vouchers FOR EACH ROW EXECUTE FUNCTION public.loading_voucher_set_updated_at();


-- ==========================================================================
-- قسم التوريدات — الجرارات  (Tawrid module: tractors / hauliers)
-- ==========================================================================
-- Phase 1 of the Tawrid (توريدات) module. Modelled on the legacy Access screen
-- ``Fgararat`` / table ``tbgrarat``, with the defects found while auditing that
-- file corrected:
--
--   * ``is_active`` replaces deletion. In the Access file 305 tickets and 56
--     payment vouchers pointed at tractors that had been deleted outright, so
--     their statements could never be reproduced. Hiding beats deleting.
--   * ``trailer_no`` / ``head_no`` are text, not integers. They are plate-style
--     identifiers (leading zeros and Arabic letters are both plausible), never
--     quantities — storing them as numbers silently mangles such values.
--   * ``tractor_code`` and ``driver_name`` are UNIQUE. Both are already unique
--     across all 25 legacy rows, and the staff clearly rely on it (they
--     disambiguate by hand: "ربيع بصل 1/2/3", "ماهر الشرقاوي 2").
--
-- Every table in this module is prefixed ``tawrid_`` and is independent of the
-- existing suppliers/purchases tables, so nothing here touches the older data.
CREATE TABLE IF NOT EXISTS public.tawrid_tractors (
    tractor_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    tractor_code integer NOT NULL,
    driver_name character varying(150) NOT NULL,
    trailer_no character varying(30),
    head_no character varying(30),
    phone character varying(30),
    price_sen numeric(18,2) DEFAULT 0 NOT NULL,
    price_raml numeric(18,2) DEFAULT 0 NOT NULL,
    opening_balance numeric(18,2) DEFAULT 0 NOT NULL,
    opening_date date,
    notes text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer,
    updated_by integer,
    CONSTRAINT ck_tawrid_tractors_driver_name_not_blank CHECK ((char_length(btrim((driver_name)::text)) > 0)),
    CONSTRAINT ck_tawrid_tractors_code_positive CHECK ((tractor_code > 0)),
    CONSTRAINT ck_tawrid_tractors_price_sen_non_negative CHECK ((price_sen >= (0)::numeric)),
    CONSTRAINT ck_tawrid_tractors_price_raml_non_negative CHECK ((price_raml >= (0)::numeric))
);

-- Primary key
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_tawrid_tractors' AND conrelid = 'public.tawrid_tractors'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_tractors ADD CONSTRAINT pk_tawrid_tractors PRIMARY KEY (tractor_id);
  END IF;
END $$;

-- Unique constraints / indexes
CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_tractors_code ON public.tawrid_tractors USING btree (tractor_code);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_tractors_driver_name ON public.tawrid_tractors USING btree (btrim((driver_name)::text));

-- Secondary indexes (the البون screen looks tractors up by plate).
CREATE INDEX IF NOT EXISTS idx_tawrid_tractors_trailer_no ON public.tawrid_tractors USING btree (trailer_no);
CREATE INDEX IF NOT EXISTS idx_tawrid_tractors_head_no ON public.tawrid_tractors USING btree (head_no);
CREATE INDEX IF NOT EXISTS idx_tawrid_tractors_is_active ON public.tawrid_tractors USING btree (is_active);

-- Foreign keys (audit columns only)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_tractors_created_by' AND conrelid = 'public.tawrid_tractors'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_tractors ADD CONSTRAINT fk_tawrid_tractors_created_by FOREIGN KEY (created_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_tractors_updated_by' AND conrelid = 'public.tawrid_tractors'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_tractors ADD CONSTRAINT fk_tawrid_tractors_updated_by FOREIGN KEY (updated_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

-- updated_at trigger
CREATE OR REPLACE FUNCTION public.tawrid_tractor_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_tawrid_tractors_set_updated_at ON public.tawrid_tractors;
CREATE TRIGGER trg_tawrid_tractors_set_updated_at BEFORE UPDATE ON public.tawrid_tractors FOR EACH ROW EXECUTE FUNCTION public.tawrid_tractor_set_updated_at();

-- Provenance for rows imported from the legacy Access file (``tbgrarat.id``).
-- Later phases migrate البونات and سندات الصرف, which reference tractors by that
-- id, so it has to survive the import to join against. NULL for rows created in
-- the app; unique among imported rows so re-running the import updates in place
-- instead of duplicating.
ALTER TABLE public.tawrid_tractors ADD COLUMN IF NOT EXISTS legacy_id integer;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_tractors_legacy_id
    ON public.tawrid_tractors USING btree (legacy_id) WHERE legacy_id IS NOT NULL;


-- =============================================================================
-- قسم التوريدات — المرحلة الثانية: العملاء
-- =============================================================================
-- Replaces the legacy Access screen ``FEMP`` (table ``fanii``, 45 rows) and its
-- subform ``InvoiceCARCUS subform`` (table ``CarCus``, 236 rows). Brand-new
-- tables: nothing here touches the existing ``customers`` table or its screen,
-- which belong to a different, older module.
--
-- The item prices stay as FIXED COLUMNS, one per item, exactly as in ``fanii``.
-- That is the user's decision (2026-09-03), taken with the trade-off stated:
-- adding a new item later means altering this table and the screen, and the
-- Access data already shows the cost of it — «سن 3» and «سن عتاقة» are the same
-- item under two names, and «س1» / «س 2» are typos recorded in real tickets,
-- because ``productName`` is free text with no items table behind it. A future
-- items table is therefore still expected; these columns are the interim shape.
--
-- Deviations from Access, each tied to something measured in the source data:
--
--   * ``opening_date`` is ON THE FORM. ``fanii.date123`` exists and the customer
--     statement query reads it, but FEMP never showed it — so every opening
--     balance was entered without its date.
--   * ``phone`` / ``notes`` / ``is_active`` are new. ``fanii`` has none of them.
--     ``is_active`` is the replacement for deletion: 911 tickets in ``TBBOOn``
--     point at customers that were deleted outright, and their statements can
--     never be reproduced. Hiding beats deleting.
--   * ``customer_name`` is UNIQUE and NOT NULL. One legacy row has no name at
--     all and two begin with a stray space; no two of the 45 collide, and the
--     staff already disambiguate by hand («عفيفي 2», «حسن 3»).
--   * ``price_sen_ataqa`` carries the label «سن عتاقة» that FEMP put on the
--     column named ``sen3`` — the column keeps the name the users read, not the
--     one the old developer typed.
CREATE TABLE IF NOT EXISTS public.tawrid_customers (
    customer_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    customer_code integer NOT NULL,
    customer_name character varying(150) NOT NULL,
    phone character varying(30),
    -- Item prices — one column per item, mirroring ``fanii``. The comment on
    -- each names the Access column it replaces and the label FEMP showed.
    price_sen1 numeric(18,2) DEFAULT 0 NOT NULL,         -- fanii.sen1        «سن 1»
    price_sen2 numeric(18,2) DEFAULT 0 NOT NULL,         -- fanii.sen2        «سن 2»
    price_sen_ataqa numeric(18,2) DEFAULT 0 NOT NULL,    -- fanii.sen3        «سن عتاقة»
    price_sen6_safi numeric(18,2) DEFAULT 0 NOT NULL,    -- fanii.sen6safi    «سن 6 صافي»
    price_sen6_bodra numeric(18,2) DEFAULT 0 NOT NULL,   -- fanii.sen6bodra   «سن 6 بالبودرة»
    price_sen_adsa numeric(18,2) DEFAULT 0 NOT NULL,     -- fanii.sen3adsa    «سن عدسة»
    price_bodra numeric(18,2) DEFAULT 0 NOT NULL,        -- fanii.bodra       «بودرة»
    price_raml numeric(18,2) DEFAULT 0 NOT NULL,         -- fanii.raml        «رملة»
    price_sen_plus numeric(18,2) DEFAULT 0 NOT NULL,     -- fanii.[sen++]     «سن+»
    price_sen_modarag numeric(18,2) DEFAULT 0 NOT NULL,  -- fanii.SeenModarg  «سن مدرج»
    -- fanii.Des — a percentage. Only one of the 45 rows is non-zero (0.01), so
    -- the range check below is what finally pins down what the column means.
    discount_percent numeric(9,4) DEFAULT 0 NOT NULL,
    opening_balance numeric(18,2) DEFAULT 0 NOT NULL,
    opening_date date,
    notes text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer,
    updated_by integer,
    CONSTRAINT ck_tawrid_customers_name_not_blank CHECK ((char_length(btrim((customer_name)::text)) > 0)),
    CONSTRAINT ck_tawrid_customers_code_positive CHECK ((customer_code > 0)),
    CONSTRAINT ck_tawrid_customers_discount_range CHECK ((discount_percent >= (0)::numeric AND discount_percent <= (100)::numeric)),
    CONSTRAINT ck_tawrid_customers_prices_non_negative CHECK ((
        price_sen1 >= (0)::numeric AND price_sen2 >= (0)::numeric
        AND price_sen_ataqa >= (0)::numeric AND price_sen6_safi >= (0)::numeric
        AND price_sen6_bodra >= (0)::numeric AND price_sen_adsa >= (0)::numeric
        AND price_bodra >= (0)::numeric AND price_raml >= (0)::numeric
        AND price_sen_plus >= (0)::numeric AND price_sen_modarag >= (0)::numeric
    ))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_tawrid_customers' AND conrelid = 'public.tawrid_customers'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_customers ADD CONSTRAINT pk_tawrid_customers PRIMARY KEY (customer_id);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_customers_code ON public.tawrid_customers USING btree (customer_code);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_customers_name ON public.tawrid_customers USING btree (btrim((customer_name)::text));
CREATE INDEX IF NOT EXISTS idx_tawrid_customers_is_active ON public.tawrid_customers USING btree (is_active);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_customers_created_by' AND conrelid = 'public.tawrid_customers'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_customers ADD CONSTRAINT fk_tawrid_customers_created_by FOREIGN KEY (created_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_customers_updated_by' AND conrelid = 'public.tawrid_customers'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_customers ADD CONSTRAINT fk_tawrid_customers_updated_by FOREIGN KEY (updated_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.tawrid_customer_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_tawrid_customers_set_updated_at ON public.tawrid_customers;
CREATE TRIGGER trg_tawrid_customers_set_updated_at BEFORE UPDATE ON public.tawrid_customers FOR EACH ROW EXECUTE FUNCTION public.tawrid_customer_set_updated_at();

-- Provenance for rows imported from ``fanii.id``. The tickets (``TBBOOn.cus_id``)
-- and the receipts (``sanadCus.empid``) both reference a customer by that id, so
-- it has to survive the import for the later phases to join against.
ALTER TABLE public.tawrid_customers ADD COLUMN IF NOT EXISTS legacy_id integer;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_customers_legacy_id
    ON public.tawrid_customers USING btree (legacy_id) WHERE legacy_id IS NOT NULL;


-- -----------------------------------------------------------------------------
-- شبكة أسعار العميل × الجرار — replaces ``CarCus``
-- -----------------------------------------------------------------------------
-- One row per (customer, tractor): the load size and the haulage rate to use
-- when a بون is written for that pair. This grid is real, not decoration —
-- 208 of the 221 resolvable legacy rows carry a rate that DIFFERS from the
-- tractor's own default, which is exactly why the البون screen looks it up here
-- first (query ``PriceSeNRamal``) and falls back to the tractor only if missing.
--
-- Two things in ``CarCus`` are deliberately not carried over:
--
--   * ``numberwesh`` — a copy of the tractor's own ``numbwesh``. Three of the
--     236 rows already disagree with the tractor card, i.e. the copy went stale.
--     The screen JOINs ``tawrid_tractors`` for it instead.
--   * the absent foreign keys — Access enforced none, so 12 rows point at
--     tractors (ids 27, 34, 46, 47) that no longer exist. Real FKs below.
CREATE TABLE IF NOT EXISTS public.tawrid_customer_tractor_prices (
    price_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    customer_id integer NOT NULL,
    tractor_id integer NOT NULL,
    -- CarCus.tak3ib — the load in cubic metres for this customer/tractor pair.
    load_volume numeric(12,2) DEFAULT 0 NOT NULL,
    price_sen numeric(18,2) DEFAULT 0 NOT NULL,   -- CarCus.PriceSen
    price_raml numeric(18,2) DEFAULT 0 NOT NULL,  -- CarCus.PriceRaml
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer,
    updated_by integer,
    legacy_id integer,
    CONSTRAINT ck_tawrid_ctp_load_non_negative CHECK ((load_volume >= (0)::numeric)),
    CONSTRAINT ck_tawrid_ctp_price_sen_non_negative CHECK ((price_sen >= (0)::numeric)),
    CONSTRAINT ck_tawrid_ctp_price_raml_non_negative CHECK ((price_raml >= (0)::numeric))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_tawrid_customer_tractor_prices' AND conrelid = 'public.tawrid_customer_tractor_prices'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_customer_tractor_prices ADD CONSTRAINT pk_tawrid_customer_tractor_prices PRIMARY KEY (price_id);
  END IF;
END $$;

-- One rate per pair. Access enforced this too, but only as a trapped runtime
-- error (3022) in the subform's Form_Error handler — here it is a constraint.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_ctp_customer_tractor
    ON public.tawrid_customer_tractor_prices USING btree (customer_id, tractor_id);
CREATE INDEX IF NOT EXISTS idx_tawrid_ctp_tractor ON public.tawrid_customer_tractor_prices USING btree (tractor_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_ctp_legacy_id
    ON public.tawrid_customer_tractor_prices USING btree (legacy_id) WHERE legacy_id IS NOT NULL;

-- The grid belongs to the customer: deleting the customer takes it with him.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_ctp_customer' AND conrelid = 'public.tawrid_customer_tractor_prices'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_customer_tractor_prices ADD CONSTRAINT fk_tawrid_ctp_customer FOREIGN KEY (customer_id) REFERENCES public.tawrid_customers(customer_id) ON UPDATE CASCADE ON DELETE CASCADE;
  END IF;
END $$;

-- The tractor does not: a tractor still priced for some customer must not be
-- deletable out from under him. This is the rule Access lacked.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_ctp_tractor' AND conrelid = 'public.tawrid_customer_tractor_prices'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_customer_tractor_prices ADD CONSTRAINT fk_tawrid_ctp_tractor FOREIGN KEY (tractor_id) REFERENCES public.tawrid_tractors(tractor_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_ctp_created_by' AND conrelid = 'public.tawrid_customer_tractor_prices'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_customer_tractor_prices ADD CONSTRAINT fk_tawrid_ctp_created_by FOREIGN KEY (created_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_ctp_updated_by' AND conrelid = 'public.tawrid_customer_tractor_prices'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_customer_tractor_prices ADD CONSTRAINT fk_tawrid_ctp_updated_by FOREIGN KEY (updated_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DROP TRIGGER IF EXISTS trg_tawrid_ctp_set_updated_at ON public.tawrid_customer_tractor_prices;
CREATE TRIGGER trg_tawrid_ctp_set_updated_at BEFORE UPDATE ON public.tawrid_customer_tractor_prices FOR EACH ROW EXECUTE FUNCTION public.tawrid_customer_set_updated_at();


-- =============================================================================
-- قسم التوريدات — المرحلة الثالثة: الكسّارات (= الموردين)
-- =============================================================================
-- Replaces the Access table ``pruduct`` (23 rows) and its screen ``Fproduct``.
-- In this business المورد = الكسّارة — one entity under two names: the menu
-- button reads «بيانات الكسارات» while the Access form caption reads «شاشة
-- إدخال بيانات الموردين». Both were bound to ``pruduct``, and both names are
-- kept here for the same reason.
--
-- Brand-new table: nothing here touches the existing ``suppliers`` table or its
-- screen, which belong to a different, older purchase module.
--
-- The shape is almost exactly ``tawrid_customers`` minus the discount and the
-- tractor price grid: ``pruduct`` has no ``Des`` column and no subform. The ten
-- item prices stay FIXED COLUMNS, by the same standing decision — see the note
-- on ``tawrid_customers`` above.
--
-- Deviations from Access, each tied to something measured in ``sisko.Accdb``:
--
--   * ``supplier_code`` is UNIQUE. In Access it is not: the default value on
--     ``Fproduct.t1`` is ``DMax("[number1]","fanii")+1`` — it counts the
--     CUSTOMERS table, not this one. The measured result is 3 duplicate codes
--     inside ``pruduct`` (26, 31, 46) and 5 codes shared with a customer
--     (5, 7, 39, 43, 82). The importer renumbers the duplicates and reports
--     them; the code is a creation counter, not an identifier anyone quotes.
--   * ``notes`` and ``opening_date`` are ON THE FORM. Both columns exist in
--     ``pruduct`` (``notees`` / ``date123``) and NEITHER has a control on
--     ``Fproduct`` — which is why all 23 rows have empty notes and every
--     opening balance was entered with no date.
--   * ``is_active`` is new and is the replacement for deletion. Crusher id 22
--     was deleted outright while 4 tickets still reference it, and unlike the
--     tractors ``TBBOOn`` records no crusher name — only ``res-id`` — so that
--     name is gone for good. 7 of the 23 cards have no ticket, no voucher and
--     no opening balance at all, and still fill the search list.
--   * ``supplier_name`` is NOT NULL, UNIQUE and trimmed. One legacy row
--     (id 23) has no name whatsoever.
--   * ``phone`` is new; ``pruduct`` has no contact column of any kind.
--   * ``price_sen_ataqa`` carries the label «سن عتاقة» that ``Fproduct`` put on
--     the column Access named ``sen3`` — the column keeps the name the users
--     read, not the one the old developer typed. Same as ``tawrid_customers``.
CREATE TABLE IF NOT EXISTS public.tawrid_suppliers (
    supplier_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    supplier_code integer NOT NULL,
    supplier_name character varying(150) NOT NULL,
    phone character varying(30),
    -- Item prices — the crusher's SELLING price per cubic metre, i.e. what we
    -- pay it. Same ten columns and same order as ``pruduct`` / ``fanii``.
    price_sen1 numeric(18,2) DEFAULT 0 NOT NULL,         -- pruduct.sen1        «سن 1»
    price_sen2 numeric(18,2) DEFAULT 0 NOT NULL,         -- pruduct.sen2        «سن 2»
    price_sen_ataqa numeric(18,2) DEFAULT 0 NOT NULL,    -- pruduct.sen3        «سن عتاقة»
    price_sen6_safi numeric(18,2) DEFAULT 0 NOT NULL,    -- pruduct.sen6safi    «سن 6 صافي»
    price_sen6_bodra numeric(18,2) DEFAULT 0 NOT NULL,   -- pruduct.sen6bodra   «سن 6 بالبودرة»
    price_sen_adsa numeric(18,2) DEFAULT 0 NOT NULL,     -- pruduct.sen3adsa    «سن عدسة»
    price_bodra numeric(18,2) DEFAULT 0 NOT NULL,        -- pruduct.bodra       «بودرة»
    price_raml numeric(18,2) DEFAULT 0 NOT NULL,         -- pruduct.raml        «رملة»
    price_sen_plus numeric(18,2) DEFAULT 0 NOT NULL,     -- pruduct.[Sen++]     «سن +»
    price_sen_modarag numeric(18,2) DEFAULT 0 NOT NULL,  -- pruduct.SeenModarg  «سن مدرج»
    opening_balance numeric(18,2) DEFAULT 0 NOT NULL,    -- pruduct.BalancFirst
    opening_date date,                                   -- pruduct.date123
    notes text,                                          -- pruduct.notees
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer,
    updated_by integer,
    CONSTRAINT ck_tawrid_suppliers_name_not_blank CHECK ((char_length(btrim((supplier_name)::text)) > 0)),
    CONSTRAINT ck_tawrid_suppliers_code_positive CHECK ((supplier_code > 0)),
    CONSTRAINT ck_tawrid_suppliers_prices_non_negative CHECK ((
        price_sen1 >= (0)::numeric AND price_sen2 >= (0)::numeric
        AND price_sen_ataqa >= (0)::numeric AND price_sen6_safi >= (0)::numeric
        AND price_sen6_bodra >= (0)::numeric AND price_sen_adsa >= (0)::numeric
        AND price_bodra >= (0)::numeric AND price_raml >= (0)::numeric
        AND price_sen_plus >= (0)::numeric AND price_sen_modarag >= (0)::numeric
    ))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_tawrid_suppliers' AND conrelid = 'public.tawrid_suppliers'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_suppliers ADD CONSTRAINT pk_tawrid_suppliers PRIMARY KEY (supplier_id);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_suppliers_code ON public.tawrid_suppliers USING btree (supplier_code);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_suppliers_name ON public.tawrid_suppliers USING btree (btrim((supplier_name)::text));
CREATE INDEX IF NOT EXISTS idx_tawrid_suppliers_is_active ON public.tawrid_suppliers USING btree (is_active);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_suppliers_created_by' AND conrelid = 'public.tawrid_suppliers'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_suppliers ADD CONSTRAINT fk_tawrid_suppliers_created_by FOREIGN KEY (created_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_suppliers_updated_by' AND conrelid = 'public.tawrid_suppliers'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_suppliers ADD CONSTRAINT fk_tawrid_suppliers_updated_by FOREIGN KEY (updated_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.tawrid_supplier_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_tawrid_suppliers_set_updated_at ON public.tawrid_suppliers;
CREATE TRIGGER trg_tawrid_suppliers_set_updated_at BEFORE UPDATE ON public.tawrid_suppliers FOR EACH ROW EXECUTE FUNCTION public.tawrid_supplier_set_updated_at();

-- Provenance for rows imported from ``pruduct.id``. Load-bearing for the phases
-- after this one: ``TBBOOn.[res-id]`` and ``sanadsup.supid`` both reference a
-- crusher by that id, so it has to survive the import to be joined against.
ALTER TABLE public.tawrid_suppliers ADD COLUMN IF NOT EXISTS legacy_id integer;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_suppliers_legacy_id
    ON public.tawrid_suppliers USING btree (legacy_id) WHERE legacy_id IS NOT NULL;


-- =============================================================================
-- قسم التوريدات — المرحلة الرابعة: الأصناف (كتالوج + خريطة عمود السعر)
-- =============================================================================
-- The single deliberate home for the mapping that ``TBBOOn`` did with 10
-- hardcoded ``IF`` branches on ``Fboun``: a typed Arabic string (``productName``
-- / ``typeharka``) was turned into ONE of the ten fixed price columns. The
-- standing decision keeps the prices as fixed columns on the three cards, so the
-- string→column mapping has to live SOMEWHERE deliberate — here — instead of
-- being re-typed as branches on the ticket screen.
--
--   * ``price_column`` names which of the ten fixed columns on
--     ``tawrid_customers`` / ``tawrid_suppliers`` this item is priced by; the
--     CHECK pins it to exactly those ten so a typo can never point at a column
--     that does not exist.
--   * ``item_family`` is the ``typeharka`` value (سن / رمل) — it selects the
--     hauler's rate (``price_sen`` vs ``price_raml``) on the customer×tractor
--     grid, which is the only place haulage splits sand from stone.
--   * The legacy free text had 14 spellings for a handful of items, incl. the
--     typos ``س1`` / ``س 2`` and ``سن 3`` vs ``سن عتاقة`` for one item. A
--     catalogue with a UNIQUE name is what collapses those onto one row.
CREATE TABLE IF NOT EXISTS public.tawrid_items (
    item_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    item_name character varying(60) NOT NULL,
    item_family character varying(20) DEFAULT 'سن' NOT NULL,   -- typeharka: سن / رمل
    price_column character varying(30) NOT NULL,               -- which fixed price column
    sort_order integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_tawrid_items_name_not_blank CHECK ((char_length(btrim((item_name)::text)) > 0)),
    CONSTRAINT ck_tawrid_items_price_column CHECK ((price_column IN (
        'price_sen1','price_sen2','price_sen_ataqa','price_sen6_safi','price_sen6_bodra',
        'price_sen_adsa','price_bodra','price_raml','price_sen_plus','price_sen_modarag'
    )))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_tawrid_items' AND conrelid = 'public.tawrid_items'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_items ADD CONSTRAINT pk_tawrid_items PRIMARY KEY (item_id);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_items_name ON public.tawrid_items USING btree (item_name);
CREATE INDEX IF NOT EXISTS idx_tawrid_items_is_active ON public.tawrid_items USING btree (is_active);

DROP TRIGGER IF EXISTS trg_tawrid_items_set_updated_at ON public.tawrid_items;
CREATE OR REPLACE FUNCTION public.tawrid_item_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_tawrid_items_set_updated_at BEFORE UPDATE ON public.tawrid_items FOR EACH ROW EXECUTE FUNCTION public.tawrid_item_set_updated_at();

-- The ten standard items, one per fixed price column, in the order the cards lay
-- them out. Idempotent: a card the user renamed on a future items screen keeps
-- its name because the seed only inserts a name that is not already present.
INSERT INTO public.tawrid_items (item_name, item_family, price_column, sort_order) VALUES
    ('سن 1',        'سن',  'price_sen1',         1),
    ('سن 2',        'سن',  'price_sen2',         2),
    ('سن عتاقة',    'سن',  'price_sen_ataqa',    3),
    ('سن 6 صافي',   'سن',  'price_sen6_safi',    4),
    ('سن 6 بالبودرة','سن', 'price_sen6_bodra',   5),
    ('سن عدسة',     'سن',  'price_sen_adsa',     6),
    ('بودرة',       'سن',  'price_bodra',        7),
    ('رملة',        'رمل', 'price_raml',         8),
    ('سن +',        'سن',  'price_sen_plus',     9),
    ('سن مدرج',     'سن',  'price_sen_modarag', 10)
ON CONFLICT (item_name) DO NOTHING;


-- =============================================================================
-- قسم التوريدات — المرحلة الرابعة: البون (= التذكرة)
-- =============================================================================
-- Replaces the Access table ``TBBOOn`` (4,072 tickets) and its screen ``Fboun``
-- — the heart of the module. Every ticket carries THREE independent price layers
-- at once, and all three account statements read from it:
--
--     العميل   total_cus = price_cus × cus_volume   safi_cus = total_cus − amount_dis
--     الكسّارة  total_res = price_res × res_volume
--     الجرار   total_man = price_man × cus_volume   ← the CUSTOMER's volume
--
-- Every formula above was audited on ALL 4,072 legacy rows and holds on every
-- one, so they are enforced here as GENERATED columns rather than trusted to the
-- UI. Deviations from Access, each tied to something measured in ``sisko.Accdb``:
--
--   * **Two volumes are kept, not collapsed.** ``cus_volume`` (Tak3ib) and
--     ``res_volume`` (Tak3ibres) differ on 4,015 of 4,072 rows (e.g. 60.5 vs
--     59.0). Folding them into one number would silently rewrite the crusher's
--     account. The hauler is paid on ``cus_volume``: ``total_man`` against
--     ``res_volume`` held on only 214 rows.
--   * **``discount_percent`` is a REAL percentage (0..100), not the fraction the
--     legacy stored.** ``TBBOOn.disc`` was ``0.01`` meaning 1%
--     (``amount_dis = total_cus × disc`` held on all 177 discounted rows). Here
--     the value is the percent itself and the generated column divides by 100,
--     so ``tawrid_customers.discount_percent`` (also rescaled to a real percent
--     at import) and the ticket agree instead of being off by ×100.
--   * **Real foreign keys.** Access enforced none: 911 tickets pointed at deleted
--     customers, 305 at deleted tractors, 4 at deleted crusher id 22. The import
--     lands the unrecoverable ones on موقوف «محذوف» placeholder cards so no
--     ticket is dropped and every FK resolves; the columns are therefore NOT
--     NULL where a placeholder can always be provided.
--   * **``ticket_no`` (``number1``) is UNIQUE.** 4,072 distinct values, zero
--     duplicates in the legacy data — a sound key. ``receipt_no``
--     (``NumberEissal``) is NOT unique: it has 107 duplicated values and junk
--     like ``888888880``, so it is a plain column.
--   * **``item_id`` replaces the free-text product string.** The typed name is
--     kept in ``item_name`` for the printed bon, but the price mapping goes
--     through the ``tawrid_items`` catalogue, not 10 IF branches.
CREATE TABLE IF NOT EXISTS public.tawrid_tickets (
    ticket_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    ticket_no integer NOT NULL,                          -- TBBOOn.number1  (البون رقم)
    receipt_no character varying(30),                    -- TBBOOn.NumberEissal (not unique)
    ticket_date date NOT NULL,                           -- TBBOOn.date123
    customer_id integer NOT NULL,                        -- TBBOOn.cus_id  → tawrid_customers
    supplier_id integer NOT NULL,                        -- TBBOOn.[res-id] → tawrid_suppliers
    tractor_id integer,                                  -- TBBOOn.maatora_id → tawrid_tractors
    item_id integer,                                     -- → tawrid_items (the price mapping)
    item_name character varying(60) DEFAULT '' NOT NULL, -- TBBOOn.productName (printed name)
    item_family character varying(20) DEFAULT '' NOT NULL,-- TBBOOn.typeharka (سن / رمل)
    -- العميل: what the customer is billed.
    cus_volume numeric(18,3) DEFAULT 0 NOT NULL,         -- TBBOOn.Tak3ib
    price_cus numeric(18,2) DEFAULT 0 NOT NULL,          -- TBBOOn.PriceCus
    discount_percent numeric(9,4) DEFAULT 0 NOT NULL,    -- TBBOOn.disc, rescaled to a percent
    -- الكسّارة: what the crusher is owed.
    res_volume numeric(18,3) DEFAULT 0 NOT NULL,         -- TBBOOn.Tak3ibres
    price_res numeric(18,2) DEFAULT 0 NOT NULL,          -- TBBOOn.Priceres
    -- الجرار: what the hauler is paid — on the CUSTOMER's volume.
    price_man numeric(18,2) DEFAULT 0 NOT NULL,          -- TBBOOn.Pricemand
    -- Generated layers. Each expression is in base columns only (a generated
    -- column may not reference another generated column), and ``safi_cus`` inlines
    -- the same rounded total/discount so it equals total_cus − amount_dis exactly.
    total_cus numeric(18,2) GENERATED ALWAYS AS (round(price_cus * cus_volume, 2)) STORED,
    amount_dis numeric(18,2) GENERATED ALWAYS AS (round(round(price_cus * cus_volume, 2) * discount_percent / 100, 2)) STORED,
    safi_cus numeric(18,2) GENERATED ALWAYS AS (round(price_cus * cus_volume, 2) - round(round(price_cus * cus_volume, 2) * discount_percent / 100, 2)) STORED,
    total_res numeric(18,2) GENERATED ALWAYS AS (round(price_res * res_volume, 2)) STORED,
    total_man numeric(18,2) GENERATED ALWAYS AS (round(price_man * cus_volume, 2)) STORED,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer,
    updated_by integer,
    CONSTRAINT ck_tawrid_tickets_no_positive CHECK ((ticket_no > 0)),
    CONSTRAINT ck_tawrid_tickets_volumes_non_negative CHECK ((cus_volume >= (0)::numeric AND res_volume >= (0)::numeric)),
    CONSTRAINT ck_tawrid_tickets_prices_non_negative CHECK ((price_cus >= (0)::numeric AND price_res >= (0)::numeric AND price_man >= (0)::numeric)),
    CONSTRAINT ck_tawrid_tickets_discount_range CHECK ((discount_percent >= (0)::numeric AND discount_percent <= (100)::numeric))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_tawrid_tickets' AND conrelid = 'public.tawrid_tickets'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_tickets ADD CONSTRAINT pk_tawrid_tickets PRIMARY KEY (ticket_id);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_tickets_no ON public.tawrid_tickets USING btree (ticket_no);
CREATE INDEX IF NOT EXISTS idx_tawrid_tickets_customer ON public.tawrid_tickets USING btree (customer_id);
CREATE INDEX IF NOT EXISTS idx_tawrid_tickets_supplier ON public.tawrid_tickets USING btree (supplier_id);
CREATE INDEX IF NOT EXISTS idx_tawrid_tickets_tractor ON public.tawrid_tickets USING btree (tractor_id);
CREATE INDEX IF NOT EXISTS idx_tawrid_tickets_item ON public.tawrid_tickets USING btree (item_id);
CREATE INDEX IF NOT EXISTS idx_tawrid_tickets_date ON public.tawrid_tickets USING btree (ticket_date);

-- Movement must never be orphaned: ON DELETE RESTRICT on all three party FKs, so
-- a card that a ticket references cannot be deleted (the master screens already
-- offer «موقوف» instead). ON UPDATE CASCADE so a surrogate key change follows.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_tickets_customer' AND conrelid = 'public.tawrid_tickets'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_tickets ADD CONSTRAINT fk_tawrid_tickets_customer FOREIGN KEY (customer_id) REFERENCES public.tawrid_customers(customer_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_tickets_supplier' AND conrelid = 'public.tawrid_tickets'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_tickets ADD CONSTRAINT fk_tawrid_tickets_supplier FOREIGN KEY (supplier_id) REFERENCES public.tawrid_suppliers(supplier_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_tickets_tractor' AND conrelid = 'public.tawrid_tickets'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_tickets ADD CONSTRAINT fk_tawrid_tickets_tractor FOREIGN KEY (tractor_id) REFERENCES public.tawrid_tractors(tractor_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_tickets_item' AND conrelid = 'public.tawrid_tickets'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_tickets ADD CONSTRAINT fk_tawrid_tickets_item FOREIGN KEY (item_id) REFERENCES public.tawrid_items(item_id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_tickets_created_by' AND conrelid = 'public.tawrid_tickets'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_tickets ADD CONSTRAINT fk_tawrid_tickets_created_by FOREIGN KEY (created_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_tickets_updated_by' AND conrelid = 'public.tawrid_tickets'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_tickets ADD CONSTRAINT fk_tawrid_tickets_updated_by FOREIGN KEY (updated_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DROP TRIGGER IF EXISTS trg_tawrid_tickets_set_updated_at ON public.tawrid_tickets;
CREATE OR REPLACE FUNCTION public.tawrid_ticket_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_tawrid_tickets_set_updated_at BEFORE UPDATE ON public.tawrid_tickets FOR EACH ROW EXECUTE FUNCTION public.tawrid_ticket_set_updated_at();

-- Provenance for rows imported from ``TBBOOn.id``. The receipt/payment vouchers
-- of later phases reference a ticket by its البون number, but the surrogate key
-- has to survive the import so a re-run updates in place.
ALTER TABLE public.tawrid_tickets ADD COLUMN IF NOT EXISTS legacy_id integer;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_tickets_legacy_id
    ON public.tawrid_tickets USING btree (legacy_id) WHERE legacy_id IS NOT NULL;


-- =============================================================================
-- قسم التوريدات — المرحلة الخامسة: تكعيب الكسّارات (كشف رأس + سطور)
-- =============================================================================
-- Replaces the Access objects ``sallesHead`` (21 rows) / ``Sallesdata`` (125
-- rows) and the form ``SallesInvoice``. The Access names read as a *sales
-- invoice*, but the objects were repurposed to record VOLUME only — audited
-- 2026-09-04, there is NO price column anywhere in either table. Each header is
-- one crusher's cubing sheet for a date; each line is a tractor and the تكعيب
-- (cubic volume) it hauled. This is a master→detail document (one header ↔ many
-- lines), not a flat grid. Deviations from Access, each tied to a measured fact:
--
--   * **Real foreign keys.** Access enforced none: 45 of 125 lines pointed at
--     deleted tractors, 3 headers had no crusher and 1 pointed at deleted
--     crusher id 22. ``crusher_id`` is NOT NULL (the import lands the one
--     unrecoverable header on a موقوف «كسّارة محذوفة» placeholder); ``tractor_id``
--     is nullable with a name/plate snapshot so a deleted tractor's line reads.
--   * **ON DELETE CASCADE from line → header.** Deleting a sheet in Access left
--     its lines orphaned — there was no key between the two tables at all.
--   * **``sheet_no`` (``number1``) is UNIQUE** — 1..21, zero duplicates.
--   * **The dead Access columns are dropped:** ``inv_id`` (text: "0"×19, "ال",
--     "3") and ``t1`` (bool, all True) carried no information.
--   * **رقم الوش / اسم السائق are read live from the tractor card;** the snapshot
--     columns hold a value only for a deleted tractor, so a card edit never
--     leaves the sheet stale (``Sallesdata`` stored its own drifting copy).
CREATE TABLE IF NOT EXISTS public.tawrid_crusher_cubing (
    cubing_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    sheet_no integer NOT NULL,                           -- sallesHead.number1
    sheet_date date NOT NULL,                            -- sallesHead.inv_date
    crusher_id integer NOT NULL,                         -- sallesHead.productNam → tawrid_suppliers
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer,
    updated_by integer,
    CONSTRAINT ck_tawrid_crusher_cubing_no_positive CHECK ((sheet_no > 0))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_tawrid_crusher_cubing' AND conrelid = 'public.tawrid_crusher_cubing'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_crusher_cubing ADD CONSTRAINT pk_tawrid_crusher_cubing PRIMARY KEY (cubing_id);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_crusher_cubing_no ON public.tawrid_crusher_cubing USING btree (sheet_no);
CREATE INDEX IF NOT EXISTS idx_tawrid_crusher_cubing_crusher ON public.tawrid_crusher_cubing USING btree (crusher_id);
CREATE INDEX IF NOT EXISTS idx_tawrid_crusher_cubing_date ON public.tawrid_crusher_cubing USING btree (sheet_date);

-- The crusher a sheet belongs to must not be deleted out from under it
-- (ON DELETE RESTRICT); the master screen offers «موقوف» instead.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_crusher_cubing_crusher' AND conrelid = 'public.tawrid_crusher_cubing'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_crusher_cubing ADD CONSTRAINT fk_tawrid_crusher_cubing_crusher FOREIGN KEY (crusher_id) REFERENCES public.tawrid_suppliers(supplier_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_crusher_cubing_created_by' AND conrelid = 'public.tawrid_crusher_cubing'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_crusher_cubing ADD CONSTRAINT fk_tawrid_crusher_cubing_created_by FOREIGN KEY (created_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_crusher_cubing_updated_by' AND conrelid = 'public.tawrid_crusher_cubing'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_crusher_cubing ADD CONSTRAINT fk_tawrid_crusher_cubing_updated_by FOREIGN KEY (updated_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.tawrid_crusher_cubing_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_tawrid_crusher_cubing_set_updated_at ON public.tawrid_crusher_cubing;
CREATE TRIGGER trg_tawrid_crusher_cubing_set_updated_at BEFORE UPDATE ON public.tawrid_crusher_cubing FOR EACH ROW EXECUTE FUNCTION public.tawrid_crusher_cubing_set_updated_at();

-- Provenance for rows imported from ``sallesHead.id``.
ALTER TABLE public.tawrid_crusher_cubing ADD COLUMN IF NOT EXISTS legacy_id integer;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_crusher_cubing_legacy_id
    ON public.tawrid_crusher_cubing USING btree (legacy_id) WHERE legacy_id IS NOT NULL;


-- The lines: one tractor + its cubic volume, belonging to one header sheet.
CREATE TABLE IF NOT EXISTS public.tawrid_crusher_cubing_lines (
    line_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    cubing_id integer NOT NULL,                          -- → tawrid_crusher_cubing (Sallesdata.inv_id)
    line_seq integer DEFAULT 0 NOT NULL,                 -- display order within the sheet
    tractor_id integer,                                  -- Sallesdata.maatora_id → tawrid_tractors
    driver_name_snapshot character varying(100) DEFAULT '' NOT NULL, -- Sallesdata.namemand (deleted tractor only)
    trailer_no_snapshot character varying(30) DEFAULT '' NOT NULL,   -- Sallesdata.numberwesh snapshot
    volume numeric(18,3) DEFAULT 0 NOT NULL,             -- Sallesdata.tak3ib
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_tawrid_cubing_lines_volume_non_negative CHECK ((volume >= (0)::numeric))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_tawrid_crusher_cubing_lines' AND conrelid = 'public.tawrid_crusher_cubing_lines'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_crusher_cubing_lines ADD CONSTRAINT pk_tawrid_crusher_cubing_lines PRIMARY KEY (line_id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_tawrid_cubing_lines_cubing ON public.tawrid_crusher_cubing_lines USING btree (cubing_id);
CREATE INDEX IF NOT EXISTS idx_tawrid_cubing_lines_tractor ON public.tawrid_crusher_cubing_lines USING btree (tractor_id);

-- Deleting the sheet deletes its lines (ON DELETE CASCADE); Access left them
-- orphaned. The tractor a line names must not be deleted (ON DELETE RESTRICT);
-- the tractors screen offers «موقوف», and the snapshot covers already-deleted ones.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_cubing_lines_cubing' AND conrelid = 'public.tawrid_crusher_cubing_lines'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_crusher_cubing_lines ADD CONSTRAINT fk_tawrid_cubing_lines_cubing FOREIGN KEY (cubing_id) REFERENCES public.tawrid_crusher_cubing(cubing_id) ON UPDATE CASCADE ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_cubing_lines_tractor' AND conrelid = 'public.tawrid_crusher_cubing_lines'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_crusher_cubing_lines ADD CONSTRAINT fk_tawrid_cubing_lines_tractor FOREIGN KEY (tractor_id) REFERENCES public.tawrid_tractors(tractor_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.tawrid_cubing_line_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_tawrid_cubing_lines_set_updated_at ON public.tawrid_crusher_cubing_lines;
CREATE TRIGGER trg_tawrid_cubing_lines_set_updated_at BEFORE UPDATE ON public.tawrid_crusher_cubing_lines FOR EACH ROW EXECUTE FUNCTION public.tawrid_cubing_line_set_updated_at();

-- Provenance for rows imported from ``Sallesdata.id``.
ALTER TABLE public.tawrid_crusher_cubing_lines ADD COLUMN IF NOT EXISTS legacy_id integer;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_cubing_lines_legacy_id
    ON public.tawrid_crusher_cubing_lines USING btree (legacy_id) WHERE legacy_id IS NOT NULL;


-- =============================================================================
-- قسم التوريدات — المرحلة السادسة: سندات قبض العملاء (مدفوعات العملاء)
-- =============================================================================
-- Replaces the Access table ``sanadCus`` (1,164 rows) and the form «مدفوعات
-- العملاء». Audited 2026-09-04, it is a dead-simple flat log of five columns —
-- ``id``, ``date123``, ``empid`` (the customer link, an employee-template
-- leftover name), ``amount`` and ``bian`` (statement). Each receipt reduces the
-- customer's balance, so ``TawridCustomerService`` reads SUM(amount) here as
-- «المحصّل». Deviations from Access, each tied to a measured fact:
--
--   * **A real foreign key to the customer.** Access enforced none: 308 receipts
--     point at a customer it deleted. ``customer_id`` is NOT NULL ON DELETE
--     RESTRICT; the import lands the 308 orphans on the same موقوف «عميل محذوف»
--     placeholder (legacy_id = -1) the البون import already creates.
--   * **A visible receipt number.** ``sanadCus`` had no receipt/voucher number at
--     all — only its row ``id``. ``receipt_no`` is a UNIQUE auto MAX+1 so every
--     voucher can be found and printed by a number.
--   * **``amount`` allows negatives.** Three legacy rows are genuine reversals
--     (min −4,093,165); SUM(amount) nets them, so no ``> 0`` check — only the
--     three null amounts import as 0 and are flagged.
CREATE TABLE IF NOT EXISTS public.tawrid_customer_receipts (
    receipt_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    receipt_no integer NOT NULL,                          -- auto MAX+1 (Access had none)
    receipt_date date NOT NULL,                           -- sanadCus.date123
    customer_id integer NOT NULL,                         -- sanadCus.empid → tawrid_customers
    amount numeric(18,2) DEFAULT 0 NOT NULL,              -- sanadCus.amount (may be negative)
    statement text,                                       -- sanadCus.bian
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer,
    updated_by integer,
    CONSTRAINT ck_tawrid_customer_receipts_no_positive CHECK ((receipt_no > 0))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_tawrid_customer_receipts' AND conrelid = 'public.tawrid_customer_receipts'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_customer_receipts ADD CONSTRAINT pk_tawrid_customer_receipts PRIMARY KEY (receipt_id);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_customer_receipts_no ON public.tawrid_customer_receipts USING btree (receipt_no);
CREATE INDEX IF NOT EXISTS idx_tawrid_customer_receipts_customer ON public.tawrid_customer_receipts USING btree (customer_id);
CREATE INDEX IF NOT EXISTS idx_tawrid_customer_receipts_date ON public.tawrid_customer_receipts USING btree (receipt_date);

-- A receipt must never be orphaned: ON DELETE RESTRICT, so a customer with a
-- receipt cannot be deleted (the customers screen offers «موقوف» instead).
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_customer_receipts_customer' AND conrelid = 'public.tawrid_customer_receipts'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_customer_receipts ADD CONSTRAINT fk_tawrid_customer_receipts_customer FOREIGN KEY (customer_id) REFERENCES public.tawrid_customers(customer_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_customer_receipts_created_by' AND conrelid = 'public.tawrid_customer_receipts'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_customer_receipts ADD CONSTRAINT fk_tawrid_customer_receipts_created_by FOREIGN KEY (created_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_customer_receipts_updated_by' AND conrelid = 'public.tawrid_customer_receipts'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_customer_receipts ADD CONSTRAINT fk_tawrid_customer_receipts_updated_by FOREIGN KEY (updated_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.tawrid_customer_receipt_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_tawrid_customer_receipts_set_updated_at ON public.tawrid_customer_receipts;
CREATE TRIGGER trg_tawrid_customer_receipts_set_updated_at BEFORE UPDATE ON public.tawrid_customer_receipts FOR EACH ROW EXECUTE FUNCTION public.tawrid_customer_receipt_set_updated_at();

-- Provenance for rows imported from ``sanadCus.id``.
ALTER TABLE public.tawrid_customer_receipts ADD COLUMN IF NOT EXISTS legacy_id integer;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_customer_receipts_legacy_id
    ON public.tawrid_customer_receipts USING btree (legacy_id) WHERE legacy_id IS NOT NULL;


-- =============================================================================
-- قسم التوريدات — المرحلة السابعة: سندات صرف الكسّارات (مدفوعات الموردين)
-- =============================================================================
-- Replaces the Access table ``sanadsup`` (139 rows) and the form «مدفوعات
-- الموردين» / «مدفوعات الكسارات». Audited 2026-09-04, it is the mirror of
-- ``sanadCus`` — a dead-simple flat log of five columns: ``id``, ``date123``,
-- ``supid`` (the crusher link → ``pruduct.id``), ``amount`` and ``bian``
-- (statement). Each payment reduces what we owe the crusher, so
-- ``TawridSupplierService`` reads SUM(amount) here as «المدفوع له». The audit
-- found it far cleaner than the customer side — 0 orphans, 0 null/negative/zero
-- amounts, SUM(amount) = 31,040,082.00 — so the deviations below are the pattern
-- kept in step with phase 6, and none of them fire on this data:
--
--   * **A real foreign key to the crusher.** Access enforced none, though here it
--     happens to have 0 orphans. ``supplier_id`` is NOT NULL ON DELETE RESTRICT;
--     the import lands any orphan on the same موقوف «كسّارة محذوفة» placeholder
--     (legacy_id = -1) the البون/التكعيب imports already create.
--   * **A visible payment number.** ``sanadsup`` had no voucher number at all —
--     only its row ``id``. ``payment_no`` is a UNIQUE auto MAX+1 so every voucher
--     can be found and printed by a number.
--   * **``amount`` allows negatives.** No legacy row is negative, but a reversal
--     could be, and SUM(amount) must net it — so no ``> 0`` check; a null amount
--     would import as 0 and be flagged.
CREATE TABLE IF NOT EXISTS public.tawrid_supplier_payments (
    payment_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    payment_no integer NOT NULL,                          -- auto MAX+1 (Access had none)
    payment_date date NOT NULL,                           -- sanadsup.date123
    supplier_id integer NOT NULL,                         -- sanadsup.supid → tawrid_suppliers
    amount numeric(18,2) DEFAULT 0 NOT NULL,              -- sanadsup.amount (may be negative)
    statement text,                                       -- sanadsup.bian
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer,
    updated_by integer,
    CONSTRAINT ck_tawrid_supplier_payments_no_positive CHECK ((payment_no > 0))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_tawrid_supplier_payments' AND conrelid = 'public.tawrid_supplier_payments'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_supplier_payments ADD CONSTRAINT pk_tawrid_supplier_payments PRIMARY KEY (payment_id);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_supplier_payments_no ON public.tawrid_supplier_payments USING btree (payment_no);
CREATE INDEX IF NOT EXISTS idx_tawrid_supplier_payments_supplier ON public.tawrid_supplier_payments USING btree (supplier_id);
CREATE INDEX IF NOT EXISTS idx_tawrid_supplier_payments_date ON public.tawrid_supplier_payments USING btree (payment_date);

-- A payment must never be orphaned: ON DELETE RESTRICT, so a crusher with a
-- payment cannot be deleted (the crushers screen offers «موقوف» instead).
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_supplier_payments_supplier' AND conrelid = 'public.tawrid_supplier_payments'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_supplier_payments ADD CONSTRAINT fk_tawrid_supplier_payments_supplier FOREIGN KEY (supplier_id) REFERENCES public.tawrid_suppliers(supplier_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_supplier_payments_created_by' AND conrelid = 'public.tawrid_supplier_payments'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_supplier_payments ADD CONSTRAINT fk_tawrid_supplier_payments_created_by FOREIGN KEY (created_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_supplier_payments_updated_by' AND conrelid = 'public.tawrid_supplier_payments'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_supplier_payments ADD CONSTRAINT fk_tawrid_supplier_payments_updated_by FOREIGN KEY (updated_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.tawrid_supplier_payment_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_tawrid_supplier_payments_set_updated_at ON public.tawrid_supplier_payments;
CREATE TRIGGER trg_tawrid_supplier_payments_set_updated_at BEFORE UPDATE ON public.tawrid_supplier_payments FOR EACH ROW EXECUTE FUNCTION public.tawrid_supplier_payment_set_updated_at();

-- Provenance for rows imported from ``sanadsup.id``.
ALTER TABLE public.tawrid_supplier_payments ADD COLUMN IF NOT EXISTS legacy_id integer;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_supplier_payments_legacy_id
    ON public.tawrid_supplier_payments USING btree (legacy_id) WHERE legacy_id IS NOT NULL;


-- =============================================================================
-- قسم التوريدات — المرحلة الثامنة: سندات صرف الجرارات (مدفوعات الجرارات)
-- =============================================================================
-- Replaces the Access table ``SanadCAR`` (709 rows) and the form «مدفوعات
-- الجرارات». Audited 2026-09-04, it is the tractor-side mirror of ``sanadsup``
-- — a dead-simple flat log of five columns: ``id``, ``date123``, ``Gararid``
-- (the tractor link → ``tbgrarat.id``, capital G), ``amount`` and ``bian``
-- (statement). Each payment reduces what we owe the driver, so
-- ``TawridTractorService`` reads SUM(amount) here as «المصروف له». Unlike the
-- crusher side the audit found real defects, and the deviations below fire:
--
--   * **A real foreign key to the tractor.** Access enforced none: 54 vouchers
--     point at 3 deleted tractors (Gararid 27/42/19). ``tractor_id`` is NOT NULL
--     ON DELETE RESTRICT; 53 resolve to the موقوف cards phase 1 recovered, and the
--     1 truly-gone tractor (Gararid 19) lands on a موقوف «جرار محذوف» placeholder
--     (legacy_id = -1) the import creates.
--   * **A visible payment number.** ``SanadCAR`` had no voucher number at all —
--     only its row ``id``. ``payment_no`` is a UNIQUE auto MAX+1 so every voucher
--     can be found and printed by a number.
--   * **``amount`` allows negatives.** No legacy row is negative, but a reversal
--     could be, and SUM(amount) must net it — so no ``> 0`` check; the one null
--     amount (Access id 453) imports as 0 and is flagged.
CREATE TABLE IF NOT EXISTS public.tawrid_tractor_payments (
    payment_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    payment_no integer NOT NULL,                          -- auto MAX+1 (Access had none)
    payment_date date NOT NULL,                           -- SanadCAR.date123
    tractor_id integer NOT NULL,                          -- SanadCAR.Gararid → tawrid_tractors
    amount numeric(18,2) DEFAULT 0 NOT NULL,              -- SanadCAR.amount (may be negative)
    statement text,                                       -- SanadCAR.bian
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer,
    updated_by integer,
    CONSTRAINT ck_tawrid_tractor_payments_no_positive CHECK ((payment_no > 0))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_tawrid_tractor_payments' AND conrelid = 'public.tawrid_tractor_payments'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_tractor_payments ADD CONSTRAINT pk_tawrid_tractor_payments PRIMARY KEY (payment_id);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_tractor_payments_no ON public.tawrid_tractor_payments USING btree (payment_no);
CREATE INDEX IF NOT EXISTS idx_tawrid_tractor_payments_tractor ON public.tawrid_tractor_payments USING btree (tractor_id);
CREATE INDEX IF NOT EXISTS idx_tawrid_tractor_payments_date ON public.tawrid_tractor_payments USING btree (payment_date);

-- A payment must never be orphaned: ON DELETE RESTRICT, so a tractor with a
-- payment cannot be deleted (the tractors screen offers «موقوف» instead).
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_tractor_payments_tractor' AND conrelid = 'public.tawrid_tractor_payments'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_tractor_payments ADD CONSTRAINT fk_tawrid_tractor_payments_tractor FOREIGN KEY (tractor_id) REFERENCES public.tawrid_tractors(tractor_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_tractor_payments_created_by' AND conrelid = 'public.tawrid_tractor_payments'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_tractor_payments ADD CONSTRAINT fk_tawrid_tractor_payments_created_by FOREIGN KEY (created_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tawrid_tractor_payments_updated_by' AND conrelid = 'public.tawrid_tractor_payments'::regclass) THEN
    ALTER TABLE ONLY public.tawrid_tractor_payments ADD CONSTRAINT fk_tawrid_tractor_payments_updated_by FOREIGN KEY (updated_by) REFERENCES public.app_users(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.tawrid_tractor_payment_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_tawrid_tractor_payments_set_updated_at ON public.tawrid_tractor_payments;
CREATE TRIGGER trg_tawrid_tractor_payments_set_updated_at BEFORE UPDATE ON public.tawrid_tractor_payments FOR EACH ROW EXECUTE FUNCTION public.tawrid_tractor_payment_set_updated_at();

-- Provenance for rows imported from ``SanadCAR.id``.
ALTER TABLE public.tawrid_tractor_payments ADD COLUMN IF NOT EXISTS legacy_id integer;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tawrid_tractor_payments_legacy_id
    ON public.tawrid_tractor_payments USING btree (legacy_id) WHERE legacy_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- المقاولين (contractors) — شاشة المقاولين، النموذج 4 «بطاقة هوية المقاول».
--   * ``contractor_code`` is TEXT like «A-H/CD-1001». The screen suggests the
--     next one (highest numeric suffix + 1, starting at 1001), but the user may
--     type any code, so it is only kept unique (trimmed, case-insensitive),
--     never generated by the database.
--   * ``contractor_type`` is one of five fixed words, stored as the Arabic text
--     the screen's dropdown shows.
--   * الضرائب والتأمينات والخصومات are AMOUNTS, not percentages (user request,
--     2026-09-24): money columns, never negative, blank = 0.
--   * ``current_balance`` (الرصيد الجاري) is typed by the user for now; it may
--     be negative.
CREATE TABLE IF NOT EXISTS public.contractors (
    contractor_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    contractor_code character varying(30) NOT NULL,
    contractor_name character varying(200) NOT NULL,
    contractor_type character varying(30) DEFAULT 'مقاول' NOT NULL,
    registration_no character varying(50),
    address character varying(300),
    phone character varying(50),
    current_balance numeric(18,2) DEFAULT 0 NOT NULL,
    vat_amount numeric(18,2) DEFAULT 0 NOT NULL,                 -- ضرائب القيمة المضافة
    withholding_tax_amount numeric(18,2) DEFAULT 0 NOT NULL,     -- ضرائب الخصم والإضافة
    social_insurance_amount numeric(18,2) DEFAULT 0 NOT NULL,    -- التأمينات الاجتماعية
    works_insurance_amount numeric(18,2) DEFAULT 0 NOT NULL,     -- تأمين الأعمال
    other_deductions_amount numeric(18,2) DEFAULT 0 NOT NULL,    -- الخصومات الأخرى
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_contractors_code_not_blank CHECK ((char_length(btrim((contractor_code)::text)) > 0)),
    CONSTRAINT ck_contractors_name_not_blank CHECK ((char_length(btrim((contractor_name)::text)) > 0)),
    CONSTRAINT ck_contractors_type CHECK (((contractor_type)::text = ANY ((ARRAY['مقاول'::character varying, 'مورد'::character varying, 'استشاري'::character varying, 'دعاية وإعلان'::character varying, 'سمسار'::character varying])::text[]))),
    CONSTRAINT ck_contractors_deductions_non_negative CHECK ((
        vat_amount >= (0)::numeric AND withholding_tax_amount >= (0)::numeric
        AND social_insurance_amount >= (0)::numeric AND works_insurance_amount >= (0)::numeric
        AND other_deductions_amount >= (0)::numeric
    ))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_contractors' AND conrelid = 'public.contractors'::regclass) THEN
    ALTER TABLE ONLY public.contractors ADD CONSTRAINT pk_contractors PRIMARY KEY (contractor_id);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_contractors_code ON public.contractors USING btree (upper(btrim((contractor_code)::text)));
CREATE INDEX IF NOT EXISTS idx_contractors_name ON public.contractors USING btree (contractor_name);
CREATE INDEX IF NOT EXISTS idx_contractors_type ON public.contractors USING btree (contractor_type);

-- 2026-10-07: نوع المقاول gains «سمسار». Existing databases still carry the
-- four-word CHECK, so swap it once (only when «سمسار» is missing from it).
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_contractors_type'
                   AND conrelid = 'public.contractors'::regclass
                   AND pg_get_constraintdef(oid) LIKE '%سمسار%') THEN
    ALTER TABLE public.contractors DROP CONSTRAINT IF EXISTS ck_contractors_type;
    ALTER TABLE public.contractors ADD CONSTRAINT ck_contractors_type CHECK (((contractor_type)::text = ANY ((ARRAY['مقاول'::character varying, 'مورد'::character varying, 'استشاري'::character varying, 'دعاية وإعلان'::character varying, 'سمسار'::character varying])::text[])));
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.contractor_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_contractors_set_updated_at ON public.contractors;
CREATE TRIGGER trg_contractors_set_updated_at BEFORE UPDATE ON public.contractors FOR EACH ROW EXECUTE FUNCTION public.contractor_set_updated_at();

-- ---------------------------------------------------------------------------
-- الشركات والمشاريع — النموذج 9 «فروع الشركات + درج التفاصيل» (2026-09-25).
-- A company owns many projects (a two-level tree). Independent of the older
-- ``companies`` table, which holds the invoice letterhead (logo / stamp).
--   * ``company_code`` is text like «A-H/CO-1001»; ``project_code`` starts with
--     its company's code: «A-H/CO-1001/PR-01». The screen suggests both; the
--     user may edit them, so only uniqueness (trimmed, any case) is enforced.
--   * A company with projects cannot be deleted (ON DELETE RESTRICT).
CREATE TABLE IF NOT EXISTS public.client_companies (
    company_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    company_code character varying(30) NOT NULL,
    company_name character varying(200) NOT NULL,
    address character varying(300),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_client_companies_code_not_blank CHECK ((char_length(btrim((company_code)::text)) > 0)),
    CONSTRAINT ck_client_companies_name_not_blank CHECK ((char_length(btrim((company_name)::text)) > 0))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_client_companies' AND conrelid = 'public.client_companies'::regclass) THEN
    ALTER TABLE ONLY public.client_companies ADD CONSTRAINT pk_client_companies PRIMARY KEY (company_id);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_client_companies_code ON public.client_companies USING btree (upper(btrim((company_code)::text)));

CREATE TABLE IF NOT EXISTS public.company_projects (
    project_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    company_id integer NOT NULL,
    project_code character varying(40) NOT NULL,
    project_name character varying(200) NOT NULL,
    address character varying(300),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_company_projects_code_not_blank CHECK ((char_length(btrim((project_code)::text)) > 0)),
    CONSTRAINT ck_company_projects_name_not_blank CHECK ((char_length(btrim((project_name)::text)) > 0))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_company_projects' AND conrelid = 'public.company_projects'::regclass) THEN
    ALTER TABLE ONLY public.company_projects ADD CONSTRAINT pk_company_projects PRIMARY KEY (project_id);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_company_projects_code ON public.company_projects USING btree (upper(btrim((project_code)::text)));
CREATE INDEX IF NOT EXISTS idx_company_projects_company ON public.company_projects USING btree (company_id);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_company_projects_company' AND conrelid = 'public.company_projects'::regclass) THEN
    ALTER TABLE ONLY public.company_projects ADD CONSTRAINT fk_company_projects_company FOREIGN KEY (company_id) REFERENCES public.client_companies(company_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.client_company_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_client_companies_set_updated_at ON public.client_companies;
CREATE TRIGGER trg_client_companies_set_updated_at BEFORE UPDATE ON public.client_companies FOR EACH ROW EXECUTE FUNCTION public.client_company_set_updated_at();
DROP TRIGGER IF EXISTS trg_company_projects_set_updated_at ON public.company_projects;
CREATE TRIGGER trg_company_projects_set_updated_at BEFORE UPDATE ON public.company_projects FOR EACH ROW EXECUTE FUNCTION public.client_company_set_updated_at();

-- ---------------------------------------------------------------------------
-- عقود المقاولين — النموذجان 7 «شجرة الشركات والمشاريع» و8 «بطاقة المقاول»،
-- the screen shows both as tabs so the user can pick one (2026-09-25).
--   * ``contract_no`` is text like «A-H/CT-1001»: suggested by the screen,
--     editable, only kept unique (trimmed, any case).
--   * The company is not stored: it is the project's company, so the two can
--     never disagree.
--   * The four rates are PERCENTAGES of ``contract_value`` (0–100); the screen
--     computes their amounts. الصافي = القيمة − (تأمين الأعمال + الضرائب والخصم
--     + التأمينات الاجتماعية); the advance payment is shown apart, not deducted.
--   * A contractor or project that has contracts cannot be deleted (RESTRICT).
CREATE TABLE IF NOT EXISTS public.contractor_contracts (
    contract_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    contract_no character varying(30) NOT NULL,
    contract_date date DEFAULT CURRENT_DATE NOT NULL,
    contractor_id integer NOT NULL,
    project_id integer NOT NULL,
    contract_value numeric(18,2) DEFAULT 0 NOT NULL,
    advance_payment_pct numeric(5,2) DEFAULT 0 NOT NULL,   -- نسبة الدفعة المقدمة
    works_insurance_pct numeric(5,2) DEFAULT 0 NOT NULL,   -- نسبة تأمين الأعمال
    tax_discount_pct numeric(5,2) DEFAULT 0 NOT NULL,      -- نسبة الضرائب والخصم
    social_insurance_pct numeric(5,2) DEFAULT 0 NOT NULL,  -- نسبة التأمينات الاجتماعية
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_contractor_contracts_no_not_blank CHECK ((char_length(btrim((contract_no)::text)) > 0)),
    CONSTRAINT ck_contractor_contracts_value_non_negative CHECK ((contract_value >= (0)::numeric)),
    CONSTRAINT ck_contractor_contracts_pct_range CHECK ((
        advance_payment_pct BETWEEN 0 AND 100 AND works_insurance_pct BETWEEN 0 AND 100
        AND tax_discount_pct BETWEEN 0 AND 100 AND social_insurance_pct BETWEEN 0 AND 100
    ))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_contractor_contracts' AND conrelid = 'public.contractor_contracts'::regclass) THEN
    ALTER TABLE ONLY public.contractor_contracts ADD CONSTRAINT pk_contractor_contracts PRIMARY KEY (contract_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_contractor_contracts_contractor' AND conrelid = 'public.contractor_contracts'::regclass) THEN
    ALTER TABLE ONLY public.contractor_contracts ADD CONSTRAINT fk_contractor_contracts_contractor FOREIGN KEY (contractor_id) REFERENCES public.contractors(contractor_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_contractor_contracts_project' AND conrelid = 'public.contractor_contracts'::regclass) THEN
    ALTER TABLE ONLY public.contractor_contracts ADD CONSTRAINT fk_contractor_contracts_project FOREIGN KEY (project_id) REFERENCES public.company_projects(project_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_contractor_contracts_no ON public.contractor_contracts USING btree (upper(btrim((contract_no)::text)));
CREATE INDEX IF NOT EXISTS idx_contractor_contracts_contractor ON public.contractor_contracts USING btree (contractor_id);
CREATE INDEX IF NOT EXISTS idx_contractor_contracts_project ON public.contractor_contracts USING btree (project_id);

DROP TRIGGER IF EXISTS trg_contractor_contracts_set_updated_at ON public.contractor_contracts;
CREATE TRIGGER trg_contractor_contracts_set_updated_at BEFORE UPDATE ON public.contractor_contracts FOR EACH ROW EXECUTE FUNCTION public.client_company_set_updated_at();

-- ---------------------------------------------------------------------------
-- مستخلصات المقاولين — النموذجان 8 «بطاقة المقاول» و9 «مؤشرات العقد» كتبويبين
-- (2026-09-25). One extract (مستخلص) is one progress claim on one contract.
--   * ``extract_no`` is text like «A-H/CT-1001/EX-03» (the contract number plus
--     a sequence): suggested by the screen, editable, only kept unique.
--   * Only the INPUTS are stored; every amount is computed by the app:
--       الإجمالي قبل الضريبة = قيمة الأعمال ÷ (1 + نسبة الضريبة)
--       الدفعة المقدمة / تأمين الأعمال / التأمينات = قيمة الأعمال × النسبة
--       ضريبة الخصم = الإجمالي قبل الضريبة × النسبة
--       الصافي = الأعمال − المقدمة − ض.الخصم − تأمين الأعمال − التأمينات − خصومات أخرى
--   * ضريبة الخصم and التأمينات الاجتماعية: a list of usual choices, any rate 0–100 allowed.
--   * The contract's own rates are shown for reference only; a contract with
--     extracts cannot be deleted (RESTRICT).
CREATE TABLE IF NOT EXISTS public.contractor_extracts (
    extract_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    extract_no character varying(40) NOT NULL,
    extract_date date DEFAULT CURRENT_DATE NOT NULL,
    contract_id integer NOT NULL,
    works_value numeric(18,2) DEFAULT 0 NOT NULL,           -- قيمة الأعمال
    vat_pct numeric(6,3) DEFAULT 14 NOT NULL,               -- نسبة الضريبة
    advance_payment_pct numeric(6,3) DEFAULT 0 NOT NULL,    -- نسبة الدفعة المقدمة
    withholding_tax_pct numeric(6,3) DEFAULT 0 NOT NULL,    -- نسبة ضرائب الخصم
    works_insurance_pct numeric(6,3) DEFAULT 5 NOT NULL,    -- نسبة تأمين الأعمال
    social_insurance_pct numeric(6,3) DEFAULT 0 NOT NULL,   -- نسبة التأمينات الاجتماعية
    other_deductions numeric(18,2) DEFAULT 0 NOT NULL,      -- خصومات أخرى (قيمة)
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_contractor_extracts_no_not_blank CHECK ((char_length(btrim((extract_no)::text)) > 0)),
    CONSTRAINT ck_contractor_extracts_amounts_non_negative CHECK ((works_value >= (0)::numeric AND other_deductions >= (0)::numeric)),
    CONSTRAINT ck_contractor_extracts_pct_range CHECK ((
        vat_pct BETWEEN 0 AND 100 AND advance_payment_pct BETWEEN 0 AND 100 AND works_insurance_pct BETWEEN 0 AND 100
    ))
);

-- 2026-10-02: ضريبة الخصم / التأمينات are no longer limited to their lists —
-- the lists stay as the usual choices and any rate 0–100 can be typed.
ALTER TABLE public.contractor_extracts DROP CONSTRAINT IF EXISTS ck_contractor_extracts_withholding;
ALTER TABLE public.contractor_extracts DROP CONSTRAINT IF EXISTS ck_contractor_extracts_social;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_contractor_extracts_list_pct_range' AND conrelid = 'public.contractor_extracts'::regclass) THEN
    ALTER TABLE public.contractor_extracts ADD CONSTRAINT ck_contractor_extracts_list_pct_range
      CHECK (withholding_tax_pct BETWEEN 0 AND 100 AND social_insurance_pct BETWEEN 0 AND 100);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_contractor_extracts' AND conrelid = 'public.contractor_extracts'::regclass) THEN
    ALTER TABLE ONLY public.contractor_extracts ADD CONSTRAINT pk_contractor_extracts PRIMARY KEY (extract_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_contractor_extracts_contract' AND conrelid = 'public.contractor_extracts'::regclass) THEN
    ALTER TABLE ONLY public.contractor_extracts ADD CONSTRAINT fk_contractor_extracts_contract FOREIGN KEY (contract_id) REFERENCES public.contractor_contracts(contract_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_contractor_extracts_no ON public.contractor_extracts USING btree (upper(btrim((extract_no)::text)));
CREATE INDEX IF NOT EXISTS idx_contractor_extracts_contract ON public.contractor_extracts USING btree (contract_id);

DROP TRIGGER IF EXISTS trg_contractor_extracts_set_updated_at ON public.contractor_extracts;
CREATE TRIGGER trg_contractor_extracts_set_updated_at BEFORE UPDATE ON public.contractor_extracts FOR EACH ROW EXECUTE FUNCTION public.client_company_set_updated_at();

-- ---------------------------------------------------------------------------
-- دفعات المقاولين — النموذجان 4 «الشجرة» و7 «لوحة المقاول» كتبويبين (2026-09-26).
-- One payment (دفعة) is money paid to a contractor on one project.
--   * ``contractor_id`` + ``project_id`` are required (the company is the
--     project's). ``extract_id`` is OPTIONAL (user request, 2026-09-26): empty
--     = a general payment (دفعة عامة) on all the contractor's extracts on that
--     project; filled = paid against that extract, which the app checks belongs
--     to the same contractor and project.
--   * المتبقي على المستخلص = صافي المستخلص − دفعاته؛ المتبقي على المشروع = صافي
--     مستخلصاته − دفعاتها − الدفعات العامة (computed by the app; paying more is
--     warned about, not blocked).
--   * A contractor, project or extract that has payments cannot be deleted (RESTRICT).
CREATE TABLE IF NOT EXISTS public.contractor_payments (
    payment_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    payment_date date DEFAULT CURRENT_DATE NOT NULL,
    contractor_id integer NOT NULL,
    project_id integer NOT NULL,
    extract_id integer,                                     -- فاضي = دفعة عامة
    amount numeric(18,2) NOT NULL,                          -- المبلغ
    notes character varying(500),                           -- ملاحظات
    payment_method character varying(10) DEFAULT 'نقدي' NOT NULL,  -- طريقة الدفع: نقدي / شيك / تحويل
    reference_no character varying(50),                     -- رقم الشيك / الحوالة (شيك أو تحويل فقط)
    cheque_date date,                                       -- تاريخ الشيك (شيك أو تحويل فقط)
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_contractor_payments_amount_positive CHECK ((amount > (0)::numeric))
);

-- The first version (same day) had only extract_id: add the two columns,
-- fill them from the extract's contract, and let extract_id be empty.
ALTER TABLE public.contractor_payments ADD COLUMN IF NOT EXISTS contractor_id integer;
ALTER TABLE public.contractor_payments ADD COLUMN IF NOT EXISTS project_id integer;
UPDATE public.contractor_payments y SET contractor_id = k.contractor_id, project_id = k.project_id
  FROM public.contractor_extracts x JOIN public.contractor_contracts k ON k.contract_id = x.contract_id
 WHERE x.extract_id = y.extract_id AND (y.contractor_id IS NULL OR y.project_id IS NULL);
ALTER TABLE public.contractor_payments ALTER COLUMN contractor_id SET NOT NULL;
ALTER TABLE public.contractor_payments ALTER COLUMN project_id SET NOT NULL;
ALTER TABLE public.contractor_payments ALTER COLUMN extract_id DROP NOT NULL;

-- طريقة الدفع (2026-09-26): existing payments become نقدي.
ALTER TABLE public.contractor_payments ADD COLUMN IF NOT EXISTS payment_method character varying(10) DEFAULT 'نقدي' NOT NULL;
ALTER TABLE public.contractor_payments ADD COLUMN IF NOT EXISTS reference_no character varying(50);
ALTER TABLE public.contractor_payments ADD COLUMN IF NOT EXISTS cheque_date date;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_contractor_payments' AND conrelid = 'public.contractor_payments'::regclass) THEN
    ALTER TABLE ONLY public.contractor_payments ADD CONSTRAINT pk_contractor_payments PRIMARY KEY (payment_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_contractor_payments_extract' AND conrelid = 'public.contractor_payments'::regclass) THEN
    ALTER TABLE ONLY public.contractor_payments ADD CONSTRAINT fk_contractor_payments_extract FOREIGN KEY (extract_id) REFERENCES public.contractor_extracts(extract_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_contractor_payments_contractor' AND conrelid = 'public.contractor_payments'::regclass) THEN
    ALTER TABLE ONLY public.contractor_payments ADD CONSTRAINT fk_contractor_payments_contractor FOREIGN KEY (contractor_id) REFERENCES public.contractors(contractor_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_contractor_payments_method' AND conrelid = 'public.contractor_payments'::regclass) THEN
    ALTER TABLE ONLY public.contractor_payments ADD CONSTRAINT ck_contractor_payments_method CHECK (payment_method IN ('نقدي', 'شيك', 'تحويل'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_contractor_payments_project' AND conrelid = 'public.contractor_payments'::regclass) THEN
    ALTER TABLE ONLY public.contractor_payments ADD CONSTRAINT fk_contractor_payments_project FOREIGN KEY (project_id) REFERENCES public.company_projects(project_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_contractor_payments_extract ON public.contractor_payments USING btree (extract_id);
CREATE INDEX IF NOT EXISTS idx_contractor_payments_contractor ON public.contractor_payments USING btree (contractor_id, project_id);

DROP TRIGGER IF EXISTS trg_contractor_payments_set_updated_at ON public.contractor_payments;
CREATE TRIGGER trg_contractor_payments_set_updated_at BEFORE UPDATE ON public.contractor_payments FOR EACH ROW EXECUTE FUNCTION public.client_company_set_updated_at();

-- ---------------------------------------------------------------------------
-- مسودة / معتمد (user request, 2026-10-02) on the six contracting tables.
--   * «حفظ» stores a record as a draft (``status = 'draft'``); «اعتماد» makes
--     it ``'approved'``. Only approved records show outside their own screen:
--     the other screens' lists, every contracting report and the dashboard.
--   * Rows that existed before this change were all approved (user's choice):
--     the column is added with DEFAULT 'approved' and only then switched to
--     DEFAULT 'draft', inside the "column is missing" branch, so a re-run never
--     touches a row.
--   * ``approved_at`` / ``approved_by`` (users.id, no FK) record who approved.
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['contractors', 'client_companies', 'company_projects',
                           'contractor_contracts', 'contractor_extracts', 'contractor_payments'] LOOP
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = t AND column_name = 'status') THEN
      EXECUTE format('ALTER TABLE public.%I ADD COLUMN status character varying(10) DEFAULT %L NOT NULL', t, 'approved');
      EXECUTE format('ALTER TABLE public.%I ALTER COLUMN status SET DEFAULT %L', t, 'draft');
    END IF;
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS approved_at timestamp with time zone', t);
    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS approved_by integer', t);
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'ck_' || t || '_status' AND conrelid = ('public.' || t)::regclass) THEN
      EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I CHECK (status IN (''draft'', ''approved''))',
                     t, 'ck_' || t || '_status');
    END IF;
  END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- شاشة بيانات الشركة (user request, 2026-10-05): the companies the app prints
-- for. Their name, tax registration number, address and logo head the
-- printouts. More than one company is allowed (user, 2026-10-05); which one a
-- printout uses is decided later. Independent of the older ``companies`` table
-- (invoice letterheads) and of ``client_companies`` (the contracting clients).
--   * ``logo`` is the image itself (bytea, with its mime type), never a path.
--   * ``show_address_in_print`` is the «يظهر في الطباعة» box beside the
--     address. Only the address has one; the rest always prints.
--   * Two companies cannot share a name (trimmed, any case).
CREATE TABLE IF NOT EXISTS public.company_info (
    company_info_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    company_name character varying(200) NOT NULL,
    tax_registration_no character varying(50),
    address character varying(300),
    show_address_in_print boolean DEFAULT true NOT NULL,
    logo bytea,
    logo_mime character varying(64),
    updated_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_company_info_name_not_blank CHECK ((char_length(btrim((company_name)::text)) > 0))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_company_info' AND conrelid = 'public.company_info'::regclass) THEN
    ALTER TABLE ONLY public.company_info ADD CONSTRAINT pk_company_info PRIMARY KEY (company_info_id);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_company_info_name ON public.company_info USING btree (upper(btrim((company_name)::text)));

DROP TRIGGER IF EXISTS trg_company_info_set_updated_at ON public.company_info;
CREATE TRIGGER trg_company_info_set_updated_at BEFORE UPDATE ON public.company_info FOR EACH ROW EXECUTE FUNCTION public.client_company_set_updated_at();

-- ---------------------------------------------------------------------------
-- مرفقات عقود المقاولين (user request, 2026-10-05): pictures and PDF files
-- attached to a contract, kept apart on the screen (two tabs).
--   * ``data`` is the file itself (bytea), never a path, so every PC opens
--     the same file. ``thumbnail`` is a small PNG of a picture for the list.
--   * ``kind`` is 'image' or 'pdf'.
--   * Deleting a contract deletes its attachments (ON DELETE CASCADE).
CREATE TABLE IF NOT EXISTS public.contractor_contract_attachments (
    attachment_id integer GENERATED ALWAYS AS IDENTITY NOT NULL,
    contract_id integer NOT NULL,
    kind character varying(10) NOT NULL,
    file_name character varying(255) NOT NULL,
    mime_type character varying(64) NOT NULL,
    file_size integer NOT NULL,
    data bytea NOT NULL,
    thumbnail bytea,
    uploaded_by integer,
    uploaded_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_contract_attachments_kind CHECK (((kind)::text = ANY ((ARRAY['image'::character varying, 'pdf'::character varying])::text[]))),
    CONSTRAINT ck_contract_attachments_name_not_blank CHECK ((char_length(btrim((file_name)::text)) > 0))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pk_contract_attachments' AND conrelid = 'public.contractor_contract_attachments'::regclass) THEN
    ALTER TABLE ONLY public.contractor_contract_attachments ADD CONSTRAINT pk_contract_attachments PRIMARY KEY (attachment_id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_contract_attachments_contract ON public.contractor_contract_attachments USING btree (contract_id, kind);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_contract_attachments_contract' AND conrelid = 'public.contractor_contract_attachments'::regclass) THEN
    ALTER TABLE ONLY public.contractor_contract_attachments ADD CONSTRAINT fk_contract_attachments_contract FOREIGN KEY (contract_id) REFERENCES public.contractor_contracts(contract_id) ON UPDATE CASCADE ON DELETE CASCADE;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- نوع الحساب on contractor payments (user request, 2026-10-07): which balance a
-- payment comes out of. Payments made before the field existed were all against
-- the current balance, so they get رصيد جاري. A draft may leave it empty; the app
-- refuses اعتماد without one, so no default for new rows.
ALTER TABLE public.contractor_payments ADD COLUMN IF NOT EXISTS account_type character varying(20) DEFAULT 'رصيد جاري' NOT NULL;
ALTER TABLE public.contractor_payments ALTER COLUMN account_type DROP NOT NULL;
ALTER TABLE public.contractor_payments ALTER COLUMN account_type DROP DEFAULT;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_contractor_payments_account_type' AND conrelid = 'public.contractor_payments'::regclass) THEN
    ALTER TABLE ONLY public.contractor_payments ADD CONSTRAINT ck_contractor_payments_account_type CHECK (account_type IN ('رصيد جاري', 'تأمين أعمال', 'تأمينات اجتماعية'));
  END IF;
END $$;
