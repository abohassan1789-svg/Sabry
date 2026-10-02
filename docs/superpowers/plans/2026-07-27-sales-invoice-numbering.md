# Global Sales Invoice Numbering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every Saudi sales invoice one editable, globally unique automatic number starting at `50001`, with higher manual numeric values advancing the sequence.

**Architecture:** PostgreSQL owns the concurrency-safe sequence and global uniqueness rule. The repository reserves numbers and synchronizes higher manual values inside invoice write transactions, the service exposes the numbering boundary and validates global duplicates, and the existing page requests a number for New and Duplicate flows.

**Tech Stack:** Python 3.11, PostgreSQL/psycopg, PySide6, pytest.

## Global Constraints

- The sequence is global across every seller company.
- The empty-database first number is exactly `50001`, without a prefix or zero padding.
- The invoice-number field remains editable for new invoices and editable drafts.
- A higher manual ASCII-decimal number advances the sequence; lower or non-numeric values do not.
- Automatic reservations may leave gaps when users cancel a new invoice.
- Approved invoices remain read-only.
- Historical invoice rows are never automatically renumbered or deleted.
- ZATCA ICV/PIH and receipt-voucher numbering are unchanged.
- Use `C:\Users\esraa\AppData\Local\Programs\Python\Python311\python.exe`; this checkout's Python 3.12 installation cannot start.
- Preserve unrelated modified and untracked files in the working tree.

## File Map

- Create `app/database/migrations/018_create_sales_invoice_numbering.sql`:
  sequence creation/reseed, duplicate preflight, and global unique index.
- Create `app/database/migrations/018_downgrade_sales_invoice_numbering.sql`:
  restores the seller-scoped uniqueness rule and removes only numbering objects.
- Create `tests/migration/test_sales_invoice_numbering_schema.py`:
  isolated-schema migration behavior and uniqueness tests.
- Modify `app/repositories/saudi_sales_invoice_repository.py`:
  reservation, global duplicate lookup, and transaction-local forward sync.
- Create `tests/repositories/test_saudi_sales_invoice_numbering_repository.py`:
  deterministic repository SQL/transaction behavior without touching production sequence state.
- Modify `app/services/saudi_sales_invoice_service.py`:
  UI-facing reservation and global duplicate validation.
- Modify `tests/services/test_saudi_sales_invoice_service.py`:
  fake repository contract and service behavior.
- Modify `app/ui/screens/saudi_sales_invoice_page.py`:
  populate New and Duplicate numbers and warn on reservation failure.
- Modify `tests/unit/test_saudi_sales_invoice_page.py`:
  widget-level New, Duplicate, editability, and failure behavior.
- Modify `PROJECT_STATE.md`:
  document the delivered numbering behavior and fresh verification.

---

### Task 1: Database Numbering Contract

**Files:**
- Create: `app/database/migrations/018_create_sales_invoice_numbering.sql`
- Create: `app/database/migrations/018_downgrade_sales_invoice_numbering.sql`
- Create: `tests/migration/test_sales_invoice_numbering_schema.py`

**Interfaces:**
- Consumes: existing table `sales_invoices(seller_company_id, invoice_number)`.
- Produces: sequence `sales_invoice_number_seq` and global unique index
  `uq_sales_invoices_invoice_number`.

- [ ] **Step 1: Write isolated-schema migration tests**

Create a test fixture that makes a temporary schema, binds `Database` to that
schema using the existing test pattern, and creates the minimum legacy shape:

```python
db.execute_script(
    """
    CREATE TABLE sales_invoices (
        id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        seller_company_id integer NOT NULL,
        invoice_number varchar(100) NOT NULL
    );
    CREATE UNIQUE INDEX uq_sales_invoices_company_number
        ON sales_invoices (seller_company_id, invoice_number);
    """
)
```

Add these behavior tests:

```python
def test_fresh_migration_starts_sequence_at_50001(db):
    db.execute_script(UPGRADE.read_text(encoding="utf-8"))
    assert db.fetch_one(
        "SELECT nextval('sales_invoice_number_seq') AS n"
    )["n"] == 50001


def test_migration_seeds_after_greatest_existing_numeric_number(db):
    db.execute(
        "INSERT INTO sales_invoices (seller_company_id, invoice_number) "
        "VALUES (1, '50010'), (2, 'MANUAL-A')"
    )
    db.execute_script(UPGRADE.read_text(encoding="utf-8"))
    assert db.fetch_one(
        "SELECT nextval('sales_invoice_number_seq') AS n"
    )["n"] == 50011


def test_global_unique_index_rejects_same_number_for_another_seller(db):
    db.execute_script(UPGRADE.read_text(encoding="utf-8"))
    db.execute(
        "INSERT INTO sales_invoices (seller_company_id, invoice_number) "
        "VALUES (1, '50001')"
    )
    with pytest.raises(Exception):
        db.execute(
            "INSERT INTO sales_invoices (seller_company_id, invoice_number) "
            "VALUES (2, '50001')"
        )


def test_migration_aborts_without_mutating_duplicate_history(db):
    db.execute(
        "INSERT INTO sales_invoices (seller_company_id, invoice_number) "
        "VALUES (1, 'SHARED'), (2, 'SHARED')"
    )
    with pytest.raises(Exception, match="duplicate"):
        db.execute_script(UPGRADE.read_text(encoding="utf-8"))
    assert db.fetch_one(
        "SELECT COUNT(*) AS c FROM sales_invoices WHERE invoice_number='SHARED'"
    )["c"] == 2
```

Also test upgrade idempotence and downgrade restoration of
`uq_sales_invoices_company_number`.

- [ ] **Step 2: Run the migration tests and verify RED**

Run:

```powershell
& 'C:\Users\esraa\AppData\Local\Programs\Python\Python311\python.exe' -m pytest tests\migration\test_sales_invoice_numbering_schema.py -q
```

Expected: FAIL because migration files do not exist.

- [ ] **Step 3: Implement the upgrade migration**

The migration must:

```sql
BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM sales_invoices
        GROUP BY invoice_number
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Cannot enable global invoice numbering: duplicate invoice numbers exist';
    END IF;
END $$;

CREATE SEQUENCE IF NOT EXISTS sales_invoice_number_seq
    AS bigint MINVALUE 50001 START WITH 50001;

DO $$
DECLARE
    max_numeric bigint;
    sequence_last bigint;
    sequence_called boolean;
BEGIN
    SELECT COALESCE(
        MAX(btrim(invoice_number)::bigint)
            FILTER (WHERE btrim(invoice_number) ~ '^[0-9]+$'),
        50000
    )
    INTO max_numeric
    FROM sales_invoices;

    SELECT last_value, is_called
    INTO sequence_last, sequence_called
    FROM sales_invoice_number_seq;

    IF max_numeric >= 50001
       AND (NOT sequence_called OR max_numeric > sequence_last) THEN
        PERFORM setval('sales_invoice_number_seq', max_numeric, true);
    END IF;
END $$;

DROP INDEX IF EXISTS uq_sales_invoices_company_number;
CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_invoices_invoice_number
    ON sales_invoices (invoice_number);

COMMIT;
```

The downgrade must drop `uq_sales_invoices_invoice_number`, recreate the old
seller/company composite unique index, and drop
`sales_invoice_number_seq`. It must not delete or renumber rows.

- [ ] **Step 4: Run migration tests and verify GREEN**

Run the command from Step 2.

Expected: all tests PASS.

- [ ] **Step 5: Commit the database contract**

```powershell
git add app/database/migrations/018_create_sales_invoice_numbering.sql app/database/migrations/018_downgrade_sales_invoice_numbering.sql tests/migration/test_sales_invoice_numbering_schema.py
git commit -m "Add global sales invoice numbering schema"
```

---

### Task 2: Repository Reservation and Forward Synchronization

**Files:**
- Modify: `app/repositories/saudi_sales_invoice_repository.py:185-205`
- Modify: `app/repositories/saudi_sales_invoice_repository.py:318-390`
- Create: `tests/repositories/test_saudi_sales_invoice_numbering_repository.py`

**Interfaces:**
- Consumes: `sales_invoice_number_seq` and
  `uq_sales_invoices_invoice_number` from Task 1.
- Produces:
  `reserve_invoice_number() -> str`,
  `invoice_number_exists(invoice_number: str, exclude_id: int | None = None) -> bool`,
  and private `_sync_invoice_number_sequence(cur, invoice_number: object) -> None`.

- [ ] **Step 1: Write repository unit tests with a recording transaction fake**

Build a fake connection/cursor that returns queued rows and records SQL/params.
The tests must assert observable repository results and the relevant SQL
boundary:

```python
def test_reserve_invoice_number_returns_decimal_sequence_value():
    repo, cursor = repository_with_rows([{"n": 50001}, None])
    assert repo.reserve_invoice_number() == "50001"
    assert any("nextval('sales_invoice_number_seq')" in sql for sql, _ in cursor.calls)


def test_global_duplicate_lookup_has_no_seller_predicate():
    repo, db = repository_with_fetch_one({"exists": 1})
    assert repo.invoice_number_exists("50001") is True
    sql, params = db.fetch_one_calls[-1]
    assert "seller_company_id" not in sql
    assert params == ["50001"]


def test_forward_sync_moves_sequence_to_higher_manual_number():
    repo, cursor = repository_with_rows([None, {"last_value": 50002}])
    repo._sync_invoice_number_sequence(cursor, "50010")
    assert any(
        "setval('sales_invoice_number_seq'" in sql and params == [50010]
        for sql, params in cursor.calls
    )


@pytest.mark.parametrize("manual", ["50001", "49999", "MANUAL-A", "", None])
def test_forward_sync_never_moves_sequence_back_or_for_non_numeric_values(manual):
    repo, cursor = repository_with_rows([None, {"last_value": 50010}])
    repo._sync_invoice_number_sequence(cursor, manual)
    assert not any("setval(" in sql for sql, _ in cursor.calls)
```

Add a test proving both `insert_invoice` and `update_invoice` call the sync
helper inside their existing transaction before it exits.

- [ ] **Step 2: Run repository tests and verify RED**

```powershell
& 'C:\Users\esraa\AppData\Local\Programs\Python\Python311\python.exe' -m pytest tests\repositories\test_saudi_sales_invoice_numbering_repository.py -q
```

Expected: FAIL because the new signatures and methods are absent.

- [ ] **Step 3: Implement minimal repository logic**

Add:

```python
_INVOICE_NUMBER_LOCK_KEY = 824_501_001
_AUTOMATIC_INVOICE_START = 50_001


def invoice_number_exists(
    self, invoice_number: str, exclude_id: int | None = None
) -> bool:
    if exclude_id is None:
        row = self.db.fetch_one(
            f"SELECT 1 AS exists FROM {TBL_INVOICES} "
            "WHERE invoice_number = %s LIMIT 1",
            [invoice_number],
        )
    else:
        row = self.db.fetch_one(
            f"SELECT 1 AS exists FROM {TBL_INVOICES} "
            "WHERE invoice_number = %s AND id <> %s LIMIT 1",
            [invoice_number, int(exclude_id)],
        )
    return row is not None


def reserve_invoice_number(self) -> str:
    with self._txn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                [_INVOICE_NUMBER_LOCK_KEY],
            )
            while True:
                cur.execute(
                    "SELECT nextval('sales_invoice_number_seq') AS n"
                )
                candidate = int(cur.fetchone()["n"])
                cur.execute(
                    f"SELECT 1 FROM {TBL_INVOICES} "
                    "WHERE invoice_number = %s LIMIT 1",
                    [str(candidate)],
                )
                if cur.fetchone() is None:
                    return str(candidate)
```

Implement `_sync_invoice_number_sequence` using
`str(invoice_number).strip().isascii()` plus `isdigit()`, the minimum `50001`,
the same advisory lock, `SELECT last_value`, and forward-only `setval`.

Call the helper from `insert_invoice` after the header insert and from
`update_invoice` after the guarded header update, using the final stored
invoice number.

- [ ] **Step 4: Run repository tests and existing repository contract tests**

```powershell
& 'C:\Users\esraa\AppData\Local\Programs\Python\Python311\python.exe' -m pytest tests\repositories\test_saudi_sales_invoice_numbering_repository.py tests\repositories\test_saudi_sales_invoice_repository.py -q
```

Expected: numbering tests PASS; pre-existing live-DB skips/failures must be
reported exactly and must not be hidden.

- [ ] **Step 5: Commit repository behavior**

```powershell
git add app/repositories/saudi_sales_invoice_repository.py tests/repositories/test_saudi_sales_invoice_numbering_repository.py
git commit -m "Add sales invoice number reservation"
```

---

### Task 3: Service Global Numbering Boundary

**Files:**
- Modify: `app/services/saudi_sales_invoice_service.py:332-370`
- Modify: `app/services/saudi_sales_invoice_service.py:538-565`
- Modify: `tests/services/test_saudi_sales_invoice_service.py:20-115`
- Modify: `tests/services/test_saudi_sales_invoice_service.py:570-605`

**Interfaces:**
- Consumes:
  `repository.reserve_invoice_number() -> str` and
  `repository.invoice_number_exists(invoice_number, exclude_id=None) -> bool`.
- Produces: `SaudiSalesInvoiceService.reserve_invoice_number() -> str`.

- [ ] **Step 1: Change the fake contract and write failing service tests**

Update `FakeSaudiInvoiceRepo` so global duplicates are detected without seller:

```python
def invoice_number_exists(self, number, exclude_id=None):
    return any(
        inv["header"]["invoice_number"] == number
        and inv["header"]["id"] != exclude_id
        for inv in self.invoices.values()
    )

def reserve_invoice_number(self):
    value = self.next_reserved_number
    self.next_reserved_number += 1
    return str(value)
```

Replace the current “same number allowed for different seller” test with:

```python
def test_same_number_rejected_for_different_seller():
    repo = FakeSaudiInvoiceRepo()
    svc = make_service(repo)
    svc.create_draft(valid_form(invoice_number="SHARED", seller_company_id=10))
    with pytest.raises(
        SaudiSalesInvoiceValidationError,
        match="مستخدم مسبقًا",
    ):
        svc.create_draft(valid_form(invoice_number="SHARED", seller_company_id=11))


def test_service_reserves_invoice_number_through_repository():
    repo = FakeSaudiInvoiceRepo()
    repo.next_reserved_number = 50001
    assert make_service(repo).reserve_invoice_number() == "50001"
```

Keep/update the existing test proving an invoice can retain its own number
during draft update through `exclude_id`.

- [ ] **Step 2: Run service tests and verify RED**

```powershell
& 'C:\Users\esraa\AppData\Local\Programs\Python\Python311\python.exe' -m pytest tests\services\test_saudi_sales_invoice_service.py -q
```

Expected: FAIL because the service still passes seller ID and has no reservation
method.

- [ ] **Step 3: Implement the service boundary**

Add:

```python
def reserve_invoice_number(self) -> str:
    return self.repository.reserve_invoice_number()
```

Change `_prepare_header` to:

```python
if self.repository.invoice_number_exists(
    invoice_number, exclude_id=exclude_id
):
    raise SaudiSalesInvoiceValidationError(
        "رقم الفاتورة مستخدم مسبقًا."
    )
```

Do not restrict the field to digits and do not alter existing blank validation.

- [ ] **Step 4: Run service tests and verify GREEN**

Run the command from Step 2.

Expected: all tests PASS.

- [ ] **Step 5: Commit service behavior**

```powershell
git add app/services/saudi_sales_invoice_service.py tests/services/test_saudi_sales_invoice_service.py
git commit -m "Enforce global sales invoice numbers"
```

---

### Task 4: Prefill New and Duplicate Invoice Numbers

**Files:**
- Modify: `app/ui/screens/saudi_sales_invoice_page.py:1427-1467`
- Modify: `app/ui/screens/saudi_sales_invoice_page.py:1585-1655`
- Modify: `tests/unit/test_saudi_sales_invoice_page.py:20-95`
- Modify: `tests/unit/test_saudi_sales_invoice_page.py:1000-1060`

**Interfaces:**
- Consumes: `SaudiSalesInvoiceService.reserve_invoice_number() -> str`.
- Produces: page helper `_populate_reserved_invoice_number() -> None`.

- [ ] **Step 1: Extend the page fake and write failing widget tests**

Give `FakeRepo` a deterministic queue:

```python
self.reserved_numbers = iter(["50001", "50002", "50003"])

def reserve_invoice_number(self):
    return next(self.reserved_numbers)
```

Replace the old blank-number New assertion and update duplicate expectations:

```python
def test_new_mode_prefills_editable_reserved_invoice_number(page):
    page.on_new()
    assert page.invoice_number_input.text() == "50001"
    assert page.invoice_number_input.isReadOnly() is False


def test_duplicate_reserves_a_new_number(page):
    page.on_new()  # consumes 50001
    page.service.repository.loaded = _invoice_with_lines(88)
    page.load_invoice(88)
    page.on_duplicate()
    assert page.invoice_number_input.text() == "50002"
    assert page.invoice_number_input.isReadOnly() is False


def test_reservation_failure_warns_and_allows_manual_number(page, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        page.service,
        "reserve_invoice_number",
        lambda: (_ for _ in ()).throw(RuntimeError("sequence unavailable")),
    )
    monkeypatch.setattr(
        sales_page.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )
    page.on_new()
    assert page.invoice_number_input.text() == ""
    assert page.invoice_number_input.isReadOnly() is False
    assert warnings and warnings[0][1] == "تعذّر إنشاء رقم الفاتورة"
```

- [ ] **Step 2: Run the three widget tests and verify RED**

```powershell
& 'C:\Users\esraa\AppData\Local\Programs\Python\Python311\python.exe' -m pytest tests\unit\test_saudi_sales_invoice_page.py -k "reserved_invoice_number or duplicate_reserves or reservation_failure" -q
```

Expected: FAIL because New/Duplicate currently clear the number.

- [ ] **Step 3: Implement the page helper and wire both flows**

Add:

```python
def _populate_reserved_invoice_number(self) -> None:
    self.invoice_number_input.clear()
    try:
        number = self.service.reserve_invoice_number()
    except Exception:  # noqa: BLE001
        QMessageBox.warning(
            self,
            "تعذّر إنشاء رقم الفاتورة",
            "تعذّر إنشاء رقم فاتورة تلقائيًا. يمكنك إدخال الرقم يدويًا.",
        )
        return
    self.invoice_number_input.setText(str(number))
```

Call it in `enter_new_mode()` after `_clear_form()` and in
`_detach_as_new_draft()` instead of `invoice_number_input.clear()`. Keep
`_dirty = False` after automatic population so generated defaults do not trigger
the discard prompt.

- [ ] **Step 4: Run the complete page and service suites**

```powershell
& 'C:\Users\esraa\AppData\Local\Programs\Python\Python311\python.exe' -m pytest tests\unit\test_saudi_sales_invoice_page.py tests\services\test_saudi_sales_invoice_service.py -q
```

Expected: all tests PASS, including WhatsApp behavior and existing editability
mode tests.

- [ ] **Step 5: Commit UI behavior**

```powershell
git add app/ui/screens/saudi_sales_invoice_page.py tests/unit/test_saudi_sales_invoice_page.py
git commit -m "Prefill editable sales invoice numbers"
```

---

### Task 5: Apply, Verify, and Document

**Files:**
- Modify: `PROJECT_STATE.md`

**Interfaces:**
- Consumes: completed database, repository, service, and UI behavior.
- Produces: applied local schema, verification evidence, and current project
  handoff notes.

- [ ] **Step 1: Back up and apply the upgrade migration to the configured database**

Use the project's existing backup mechanism or create a PostgreSQL backup
before schema mutation. Then execute
`018_create_sales_invoice_numbering.sql` once through `Database.execute_script`.

Read back, without consuming a number:

```sql
SELECT last_value, is_called FROM sales_invoice_number_seq;
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'sales_invoices'
  AND indexname IN (
      'uq_sales_invoices_company_number',
      'uq_sales_invoices_invoice_number'
  );
```

Expected on the currently empty database:
`last_value = 50001`, `is_called = false`, and only the global unique index is
present.

- [ ] **Step 2: Run targeted verification**

```powershell
& 'C:\Users\esraa\AppData\Local\Programs\Python\Python311\python.exe' -m pytest tests\migration\test_sales_invoice_numbering_schema.py tests\repositories\test_saudi_sales_invoice_numbering_repository.py tests\services\test_saudi_sales_invoice_service.py tests\unit\test_saudi_sales_invoice_page.py -q
```

Expected: all targeted tests PASS.

- [ ] **Step 3: Compile changed Python modules**

```powershell
& 'C:\Users\esraa\AppData\Local\Programs\Python\Python311\python.exe' -m py_compile app\repositories\saudi_sales_invoice_repository.py app\services\saudi_sales_invoice_service.py app\ui\screens\saudi_sales_invoice_page.py tests\repositories\test_saudi_sales_invoice_numbering_repository.py tests\services\test_saudi_sales_invoice_service.py tests\unit\test_saudi_sales_invoice_page.py
```

Expected: exit code `0`.

- [ ] **Step 4: Run the full suite**

```powershell
& 'C:\Users\esraa\AppData\Local\Programs\Python\Python311\python.exe' -m pytest -q
```

Expected: no new failures. Report the three previously observed unrelated
failures separately if they remain:

- live ZATCA counter expectation (`1` versus current database value);
- daily-follow-up debounce test;
- skeleton database name (`CRM` versus `InvPhase2`).

- [ ] **Step 5: Update project state**

Add a dated section to `PROJECT_STATE.md` recording:

- global automatic numbering from `50001`;
- editable manual override and forward-only advancement;
- migration/index names;
- New and Duplicate UI behavior;
- targeted/full-suite evidence;
- any remaining unrelated failures.

- [ ] **Step 6: Commit documentation**

```powershell
git add PROJECT_STATE.md
git commit -m "Document automatic sales invoice numbering"
```

- [ ] **Step 7: Final diff and status audit**

```powershell
git diff --check
git status --short
git log -6 --oneline
```

Confirm no unrelated file was staged, overwritten, or deleted.
