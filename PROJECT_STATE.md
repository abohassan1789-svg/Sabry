# CRM Project State

Last updated: 2026-09-04

## قسم التوريدات — phase 6: سندات قبض العملاء (added 2026-09-04)

**Built, verified AND migrated.** The customer receipt voucher — one payment
collected from one customer — replacing the Access table `sanadCus` («مدفوعات
العملاء»). The user picked **Model 9** («عمودان + نداء الرصيد الجديد») and had it
refined with **cards + a donut chart** (نسبة تحصيل العميل).

- **`tawrid_customer_receipts`**: `receipt_id` PK, `receipt_no` INT UNIQUE (← the
  Access row `id`; the table had no receipt-number column at all — only its id),
  `customer_id` FK→`tawrid_customers` **NOT NULL ON DELETE RESTRICT** (← `empid`,
  an employee-template leftover name that is really the customer link),
  `receipt_date` (← `date123`), `amount` numeric(18,2) **allowing negatives** (3
  legacy rows are genuine reversals; SUM nets them — no `> 0` check), `statement`
  (← `bian`), audit cols, `legacy_id`.
- **`app/services/tawrid_customer_receipt_service.py`**: `next_receipt_no`
  (MAX+1), `receipt_no_exists`, `customer_picker_rows`, `for_receipt` (joined to
  the customer), `search_receipts` («بحث عن سند»), and `account_for` — which
  delegates the opening/invoiced/collected figures to `TawridCustomerService`
  (one source of truth for «الرصيد») and subtracts the on-screen receipt's own
  amount so the screen can preview «قبل / بعد» in both new and view mode.
- **`app/ui/screens/tawrid_customer_receipts_screen.py`** (Model 9): entry cards
  on the right (رقم/تاريخ, العميل via picker, a large amount box with **المبلغ
  بالحروف** from a compact Arabic tafqit, البيان); the left column is the live
  account panel — a «الرصيد الجديد» callout, a `_DonutChart` (QPainter) of the
  collection ratio with a legend, and three stat cards (رصيد سابق ← هذا السند ←
  الرصيد بعده). Like البون/التكعيب there is **no voucher list on the screen** —
  «بحث عن سند» (`tawrid_receipt_picker.py`) + الاول/السابق/التالي/الاخير.
- Wired through the usual **five edits** (`TABLE_SPECS`, `theme.py`,
  `main_window.py` MODULES + NAV_SECTIONS, `permission_registry.py`).

### Access defects fixed, each tied to a measured finding

- **A real FK to the customer.** Access enforced none: 308 receipts point at a
  deleted customer → they land on the same موقوف «عميل محذوف» placeholder
  (`legacy_id = -1`) the البون import created.
- **A visible, unique receipt number** — `sanadCus` had only a row id.
- **`amount` allows negatives** — 3 legacy reversals kept as-is; the 3 null
  amounts import as 0, all 6 flagged.

### Migrated (2026-09-04)

`import_customer_receipts` in `app/migrations/tawrid_import.py` (step
`customer_receipts`), idempotent on `legacy_id` (= the Access `id`, also reused as
`receipt_no`). **All 1,164 receipts imported, 0 skipped, SUM(amount) =
92,844,090.50 — matches Access exactly.** 1,164 distinct `receipt_no`; 3 negatives
+ 3 zeros (the nulls); 197 with بيان; **308 on the «عميل محذوف» placeholder**; 42
distinct customers (41 real + placeholder). Re-run: 0 inserted / 1,164 updated.
Verified end-to-end on live SiskoDB — the customer balance strip's «المحصّل» /
«الرصيد» now light up (`movements_available: True`) with **no change** to
`tawrid_customer_service.py`.

**Tests: 465 passing `-k tawrid`** (+34: service, picker, screen — layout, the
tafqit, the donut ratio, and save validation).

After this: سندات صرف (suppliers `sanadsup` 139 rows, tractors `SanadCAR`) and the
three account statements (customer/supplier/tractor).

## قسم التوريدات — phase 5: تكعيب الكسّارات (added 2026-09-04)

**Built, verified AND migrated.** A **master→detail cubing document** — the first
header+lines document in the module. It replaces the Access objects `sallesHead` /
`Sallesdata` / `SallesInvoice`, which despite their *sales-invoice* names carry
**no price at all** (audited: only the تكعيب/volume of each tractor from each
crusher). The user confirmed: build it as a cubing sheet with **no price**, and
the menu label is **«تكعيب الكسّارات»**. Layout is **Model 9** (line-cards).

- **`tawrid_crusher_cubing`** (header ← `sallesHead`): `cubing_id` PK, `sheet_no`
  UNIQUE (← `number1`, auto MAX+1), `crusher_id` FK→`tawrid_suppliers` **NOT NULL**
  `ON DELETE RESTRICT`, `sheet_date`, `notes`, audit cols, `legacy_id`. The dead
  Access columns `inv_id` (text: "0"×19) and `t1` (bool, all True) are **dropped**.
- **`tawrid_crusher_cubing_lines`** (lines ← `Sallesdata`): `line_id` PK,
  `cubing_id` FK→header **ON DELETE CASCADE** (Access left lines orphaned),
  `line_seq`, `tractor_id` FK→`tawrid_tractors` (nullable, RESTRICT),
  `driver_name_snapshot` + `trailer_no_snapshot` (a fallback only for a deleted
  tractor), `volume` (← `tak3ib`), `legacy_id`. رقم الوش/اسم السائق are read live
  from the tractor card, not re-stored.
- **`app/services/tawrid_cubing_service.py`**: next sheet no, sheet-no uniqueness,
  the crusher/tractor picker rows, the lines joined to the tractor card (live name
  falling back to snapshot; a موقوف/missing tractor flags the line محذوف), add /
  update-volume / delete of one line (each its own statement — the customers-grid
  pattern, no cross-table transaction), the per-sheet totals (count / total /
  average / max / zeros / deleted), `for_cubing`, and `search_cubing`.
- **`app/ui/screens/tawrid_cubing_screen.py`** (Model 9): a header band + a
  crusher picker, each line a small **card** with an inline volume box, a totals
  footer, and — like البون — **no sheet list on screen**: «بحث عن كشف»
  (`tawrid_cubing_picker.py`) + الاول/السابق/التالي/الاخير + the full CRUD toolbar.
  Subclasses `BaseCrudScreen`; a line can only be added once the header is saved.
- Wired through the usual **five edits** (`TABLE_SPECS`, `theme.py`,
  `main_window.py` MODULES + NAV_SECTIONS, `permission_registry.py`).

### Access defects fixed, each tied to a measured finding

- **Real FKs both sides.** Access had none: 3 headers had no crusher, 1 pointed at
  deleted crusher 22, 45 of 125 lines pointed at deleted tractors.
- **ON DELETE CASCADE header→lines** (Access left lines with no parent at all).
- **`sheet_no` UNIQUE, auto** (1..21, zero duplicates in the source).
- **رقم الوش/الاسم read from the tractor card** (Access `Sallesdata` stored its own
  drifting copy); a snapshot is kept only for a deleted tractor.
- **The dead `inv_id` / `t1` columns are gone.**

### Migrated (2026-09-04)

`import_cubing_headers` + `import_cubing_lines` in `app/migrations/tawrid_import.py`
(steps `cubing_headers`, `cubing_lines`), idempotent on `legacy_id`. **All 21
headers + 125 lines imported, 0 skipped, total volume 6583.0 — matches Access
exactly.** The 4 orphan headers (3 no-crusher + 1 on deleted crusher 22) share one
موقوف **«كسّارة محذوفة»** placeholder (sentinel `legacy_id = -1`, code 88) — the same
placeholder البون's import will reuse. The 23 lines on the 9 never-recovered deleted
tractors imported with `tractor_id` NULL + a name/plate snapshot (nothing dropped);
the 7 phase-1-recovered tractors resolved normally. Re-run reported 0 inserted /
21+125 updated (idempotent).

### البون now consumes the cubing data (added 2026-09-04)

At the user's request, the **البون** tractor picker gained a **third scope
«جرارات الكسّارة»** (beside «كل الجرارات» / «جرارات العميل»): the distinct tractors
that hauled from the chosen crusher, read from the تكعيب الكسّارات sheets. Picking a
tractor — or changing the crusher — now **auto-fills `res_volume` (تكعيب الكسّارة)**
from `TawridTicketService.crusher_volume(crusher, tractor)` = that pair's volume on
its **most recent** sheet. Unlike `cus_volume` (the customer grid) it only fills
when a cubing row exists and never clears — the cubing sheets are a supplementary
source, not the authoritative per-pair config. `tawrid_tractor_picker.py` now
accepts `crusher_rows`/`crusher_name` (a third radio); the two new service methods
degrade to empty/None if the cubing tables are absent, so البون never breaks on an
older database. Verified on live SiskoDB (الفهد → 6 tractors, احمد معروف → 62.5).

**Tests: 416 passing `-k tawrid`** (+78: service, screen, picker, import, and the
البون crusher-scope + res_volume auto-fill).

## قسم التوريدات — phase 4: البون (added 2026-09-04)

**البون — the ticket — is built and verified; data NOT yet migrated.** Two new
tables, a service, a screen and two pickers, wired through the usual five edits.

- **`tawrid_items`** (new): the deliberate home for the item→price-column mapping
  that Access `Fboun` did with 10 hardcoded `IF` branches. `item_name` UNIQUE,
  `item_family` (سن/رمل), `price_column` CHECK-pinned to the ten fixed columns.
  Seeded idempotently with the ten standard items (`ON CONFLICT (item_name)`).
  The standing "prices stay fixed columns" decision is untouched — this maps a
  chosen item onto one of those columns; it does not replace them.
- **`tawrid_tickets`** (replaces `TBBOOn`): three price layers, real FKs
  (`customer_id`/`supplier_id` NOT NULL, `tractor_id`/`item_id` nullable, all
  `ON DELETE RESTRICT` except item `SET NULL`). The five money totals are
  **`GENERATED ALWAYS ... STORED`** — each expression in base columns only
  (Postgres forbits a generated column referencing another), and `safi_cus`
  inlines the same rounded total/discount so it equals `total_cus − amount_dis`
  exactly. `total_man = round(price_man × cus_volume, 2)` — the **customer's**
  volume. `ticket_no` UNIQUE, `receipt_no` not. `legacy_id` for the import.
- **`app/services/tawrid_ticket_service.py`**: next البون number, the item
  catalogue, `prices_for(...)` (resolves the three prices + the customer's
  default discount, hauler rate from the customer×tractor grid → tractor card),
  the three picker row-sets, `for_ticket(id)` (joined display) and
  `search_tickets(keyword)` for the «بحث عن بون» dialog. The dynamic price column
  is validated against a frozen whitelist before it ever reaches the SQL.
  `grid_volume(customer, tractor)` returns the pair's `load_volume`
  (= `CarCus.tak3ib`) so the screen **auto-fills `cus_volume`** the moment both
  customer and tractor are chosen — the volume is configured per pair on the
  customers screen, not re-typed per ticket. Fired only on the customer/tractor
  picks (never on an item switch), so a hand-typed volume survives switching the
  صنف. A pick always reflects the NEW pair: the new tractor's load, or a cleared
  box when that pair has no grid row — leaving the previous tractor's number was
  a reported bug. `customer_tractor_picker_rows(customer)` powers a **scope
  toggle** on the tractor picker: «كل الجرارات» (default) vs «جرارات العميل»
  (the customer's own grid pairs). The toggle is opt-in — the picker shows it
  only when the البون passes the customer's rows, so the customers screen's own
  use of the same dialog is unchanged.
- **`app/ui/screens/tawrid_tickets_screen.py`** — the user picked **Model 3**
  (stacked full-width cards, one per party: header + customer/green +
  crusher/amber + hauler/blue), **no ticket list on the screen**, «بحث عن بون» +
  الاول/السابق/التالي/الاخير, and the full shared toolbar
  (جديد/تعديل/حفظ/حذف/إلغاء/خروج). Live totals preview the generated columns with
  the identical formulas. Two new dialogs:
  `tawrid_customer_picker.py`, `tawrid_ticket_picker.py` (live search).

### Decisions taken (the four open questions, all per the recommendation)

1. **Discount is a REAL percentage (0..100), not the legacy fraction.** The
   ticket's `discount_percent` is the percent itself and the generated column
   divides by 100. `tawrid_customers.discount_percent` (still holding the `0.01`
   fraction from `fanii.Des`) will be **rescaled to a real percent at import**
   (multiply values `>0 AND <1` by 100 — idempotent). Until that import runs the
   one discounted customer's default reads 0.01% on a new ticket; harmless while
   البون is empty, but the rescale MUST land in the same import step.
2. **Orphan tickets get موقوف «محذوف» placeholder cards at import** so no ticket
   is dropped and every NOT NULL FK resolves (~923 with no customer, 4 on crusher
   id 22). Not built yet — it is the migration step.
3. **Item→price mapping lives in `tawrid_items`**, not IF branches or a Python
   dict.
4. **Screen + tables first, migration second.** The 4,072-row `import_tickets`
   step is **not written yet** — it is the next task, pending sign-off on the
   built screen.

### Verified

- Schema applies idempotently to SiskoDB; generated columns compute exactly
  (60.5×80=4,840.00; disc 1% = 48.40; safi 4,791.60; res 59×55=3,245.00;
  man 15×60.5=907.50).
- Headless end-to-end: build screen → new → pick parties/item → live preview →
  save (generated columns stored exactly) → load back (joined labels) → delete.
- Tests: **338 passing** under `-k tawrid` (302 + 36 new across the two pickers
  and the screen). Three new test files.

### البون data — MIGRATED (2026-09-04)

`import_tickets` in `app/migrations/tawrid_import.py` (step `tickets`), idempotent
on `legacy_id`. **All 4,072 tickets imported, 0 skipped, and the five DB-GENERATED
totals match Access on every row** (rounded 2dp). How the decisions landed:

- **~911 tickets with no customer** (deleted + NULL) → one موقوف **«عميل محذوف»**
  placeholder (`tawrid_customers.legacy_id = -1`). The **4 crusher-22 tickets** →
  the phase-5 **«كسّارة محذوفة»** placeholder (reused, `tawrid_suppliers.legacy_id
  = -1`). **1 ticket** with an unresolvable tractor → `tractor_id` NULL; all others
  resolve through the phase-1 recovered cards.
- **Discount** — `TBBOOn.disc` (a fraction, 0.01 = 1%) stored as a percent (×100);
  177 tickets at 1%. The customers' own default `discount_percent` was rescaled
  in the same step (1 customer, 0.01 → 1.0), idempotently.
- **`ticket_no`** — the one legacy `number1 = 0` renumbered to 4118 (the column is
  `> 0` and UNIQUE); stable, from the Access rows alone.
- **Item** — mapped to `tawrid_items` ignoring spaces + a small alias set
  (سن+→سن +, سن 3→سن عتاقة, س1→سن 1, س 2→سن 2); the printed `productName` is kept
  verbatim in `item_name`. Only the empty-name ticket has a NULL `item_id`.

Re-run reported 0 inserted / 4,072 updated (idempotent). Verified end-to-end
through the البون screen (joined party names incl. «عميل محذوف», item family, live
totals). ⚠ The `.accdb` is open in Access and shifts by a row between reads — verify
orphan counts dynamically, not against a frozen number. **430 tests pass
`-k tawrid`.**

After البون: سندات القبض/الصرف and the three account statements.

## قسم التوريدات — phases 1, 2 & 3 (added 2026-09-03)

A **new module** built on SiskoDB, modelled on the legacy Access app in
`review/sisko.Accdb` (a sand/gravel haulage business: a crusher supplies, a
tractor hauls, a customer receives, and every load is one بون). Every table is
prefixed `tawrid_` and is independent of the existing `customers` / `suppliers` /
`purchase_invoices` tables, which belong to a different, older module. Nothing in
those was touched.

**Phase 1 — الجرارات (done, migrated).** `tawrid_tractors`,
`app/services/tawrid_tractor_service.py`,
`app/ui/screens/tawrid_tractors_screen.py`. Screen layout is the "Model 8" the
user picked: the shared CRUD form plus a live account-summary strip (three stat
tiles + a small ledger).

**Phase 2 — العملاء (done, migrated).** Two tables, `tawrid_customers` and
`tawrid_customer_tractor_prices` (replacing Access `fanii` and its subform table
`CarCus`), plus `app/services/tawrid_customer_service.py`,
`app/ui/screens/tawrid_customers_screen.py` and
`app/ui/dialogs/tawrid_tractor_picker.py`. Screen layout is "Model 2": the same
shape as the tractors screen, with the ten item prices and the customer × tractor
price grid in two tabs under the form.

Adding a screen here needs **five edits and no migration file**: idempotent DDL
appended to `app/database/schema/full_schema.sql` (it self-applies on startup), a
`TableSpec` in `TABLE_SPECS`, `LOOKUP_LAYOUT_KEYS` + `RIGHT_ALIGNED_FIELDS` in
`app/ui/common/theme.py`, `MODULES` + `NAV_SECTIONS` in `main_window.py`, and
`SCREEN_TARGETS` in `app/services/permission_registry.py`.

### Data migrated from Access (2026-09-03)

`app/migrations/tawrid_import.py` (+ `access_reader.py`). Read-only on the Access
side, **idempotent** (keyed on a `legacy_id` column that preserves the Access
`id`), with `--dry-run` and `--only <step>`. Steps run in order:
`tractors` → `recovered` → `customers` → `prices`.

| source | rows | result |
|---|---|---|
| `tbgrarat` → `tawrid_tractors` | 25 | all migrated, verified field-by-field |
| recovered tractor cards | 9 | rebuilt from the tickets — see below |
| `fanii` → `tawrid_customers` | 45 | all migrated, verified field-by-field |
| `CarCus` → `tawrid_customer_tractor_prices` | 236 | all migrated, 0 orphans |
| `pruduct` → `tawrid_suppliers` | 23 | all migrated, verified field-by-field |

`legacy_id` is load-bearing: البونات (`TBBOOn.cus_id` / `maatora_id`) and the
vouchers reference these rows by the Access id, so later phases join on it.

**Nine deleted tractor cards were rebuilt from the tickets.** `tbgrarat` had lost
ids 27/33/34/35/38/39/42/46/47, but nothing referencing them was cleaned up —
Access enforced no foreign keys. `TBBOOn.namemand` and `numberwesh` still name
them across 264 tickets, plus 53 `SanadCAR` vouchers, so
`import_recovered_tractors` restores each card from the most frequent name and
plate on that tractor's own tickets and reports the counts. They come across
**موقوف**, so they never appear in the tractor picker for new work. Three had only
digits in `namemand` (`22222`, `33333`, `6565656`) — not a name — and are stored
as «جرار محذوف <id>». Without this, neither the 12 price-grid rows pointing at
them nor those 264 tickets could ever have been imported.

### Access defects fixed, each tied to a measured finding

- **Real foreign keys.** Access had none: 911 tickets and 308 receipts point at
  deleted customers, 12 grid rows at deleted tractors.
- **A customer with movement cannot be deleted,** only stopped (`is_active`).
- **`(customer, tractor)` is UNIQUE** and the picker only offers tractors not yet
  priced — Access instead trapped the resulting error 3022 and asked the user to
  retry.
- **رقم المقطورة / رقم الوش are read from the tractor card,** not stored again:
  three of the 236 `CarCus` rows had already drifted from the tractor.
- **`opening_date` is on the form.** `fanii.date123` existed and the statement
  query read it, but `FEMP` never showed it, so opening balances were undated.
- **Name is NOT NULL, UNIQUE and trimmed.** One legacy row had no name at all and
  two began with a stray space.
- **A new grid row starts at the tractor's own rate,** not blank — and that
  default is shown beside the customer's rate, because 208 of the 221 resolvable
  legacy rows differ from it. That grid is the reason the البون screen looks the
  pair up before falling back to the tractor.
- The delete prompt no longer says «هل تريد حذف الموظف» (text left over from a
  different program).

### Decisions to honour, not re-litigate

- **The ten item prices stay as fixed columns** (`price_sen1 … price_sen_modarag`),
  mirroring `fanii`. The user chose this after being shown the trade-off. An items
  table is still expected later, and `tawrid_customers` will need altering then.
- **المورد = الكسّارة** — supplier and crusher are one entity, as in Access.
- **The Access reader always works on a temp copy**, never `review/sisko.Accdb`
  itself: the user keeps it open in Microsoft Access. Do not "fix" this back.
- `pyodbc` is needed for migration only and is deliberately **not** in
  `requirements.txt`.

**Phase 3 — الكسارات/الموردين (done, migrated).** One table,
`tawrid_suppliers` (replacing Access `pruduct`), plus
`app/services/tawrid_supplier_service.py`,
`app/ui/screens/tawrid_suppliers_screen.py` and
`app/ui/dialogs/tawrid_supplier_picker.py`. Screen layout is "Model 2-ب": the
same summary strip + form as the customers screen, but **no list panel** — the
record list moved into a search dialog behind a «بحث عن كسّارة» button at the
user's request, and the ten item prices sit in a wide panel beside the form
(three columns). `الاول/السابق/التالي/الاخير` came back with it: they are on
`Fproduct` already and are the only way to walk the cards once the list is gone.

Two implementation notes that are easy to get wrong:

- The list panel is **built and hidden**, not removed. The base class drives
  selection, `_select_row_by_id` and the record count through `self.table`.
- `QTableView.selectRow` is a **no-op** on a view inside a hidden parent, so
  `refresh_table`, `_select_row_by_id` and `_navigate` all use `setCurrentCell`
  instead. Without that the screen opens on a blank form and navigation dies
  silently.

### Access defects fixed in phase 3, each tied to a measured finding

- **The مسلسل came from the customers table.** `Fproduct.t1` defaulted to
  `DMax("[number1]","fanii")+1`, which counts `fanii`. Measured result: 3
  duplicate codes inside `pruduct` (26, 31, 46) and 5 codes shared with a
  customer (5, 7, 39, 43, 82). `supplier_code` is now UNIQUE off its own MAX.
- **`notees` and `date123` had no control on the form at all** — hence 23 rows
  of 23 with empty notes and no opening balance carrying its date. Both are on
  the form now.
- **Three boxes were left unlocked** (`Sen++`, `SeenModarg`, `BalancFirst`)
  while every other control was `Locked=True`, so they could be typed into
  without pressing «تعديل». Everything now switches mode together.
- **A crusher with movement cannot be deleted,** only stopped. Crusher id 22 was
  deleted while 4 tickets still reference it — and unlike the tractors, `TBBOOn`
  stores no crusher name, only `res-id`, so it cannot be recovered.
- **The search dialog shows الحالة and الرصيد.** The Access combo was
  `SELECT id, productName FROM pruduct` — every card, active or dead, in
  creation order. 7 of the 23 have no movement at all, and «مكة ستون» is at
  −11,125 (overpaid), which the old screen could not show.
- **The price panel heading counts what is priced** («9 من 10»). The legacy grid
  is 76% empty — 56 of 230 cells; 27 items are priced but never bought and 19
  were bought with no price on the card.

Verified against the data: the card price **is** the current price — over each
active crusher's last 30 tickets the ticket price matches the card 100% of the
time. The 2,281 whole-history mismatches are price history, not error.

### Phase 3 data migrated (2026-09-04)

`import_suppliers` in `app/migrations/tawrid_import.py` (step name `suppliers`,
independent of the others — `pruduct` references no other table). All 23 rows
verified field-by-field against Access, opening-balance total 3,007,077.00 on
both sides, and the import is idempotent (a second run reported 23 updated, 0
inserted, and the verification still passed).

Three decisions were taken without an answer from the user, all reversible:

- **The 3 duplicate مسلسل were renumbered.** The first row to use a number keeps
  it (lowest Access id wins): الجزيرة 26 → **85**, مشال فقط 31 → **86**,
  الفهد 46 → **87**. The mapping is computed from the Access rows alone, so
  re-running lands on the same numbers instead of walking them forward.
- **The 7 dead cards came across موقوف** (حسن عبد الرازق, النائب, الفاروق,
  الجزيرة, بترميكس, النيل, and the nameless id 23) — no ticket, no voucher, no
  opening balance. One click on الحالة reverses it.
- **The nameless row (id 23) is «بدون اسم — مسلسل 82», موقوف.** `supplier_name`
  is NOT NULL, and dropping the row would lose the `legacy_id` later phases join
  on.

`is_active` is deliberately **not** in the UPSERT's SET list: once someone stops
or restarts a crusher on the screen, re-running the import must not undo it.

**Crusher id 22 was deliberately NOT recreated.** It was deleted in Access with 4
tickets still pointing at it, and unlike the tractors `TBBOOn` stores no crusher
name — only `res-id` — so there is nothing to rebuild the card from. The البون
phase has to decide whether those 4 tickets get a placeholder or stay behind.

Tests: **302 passing** under `pytest tests -k tawrid`.

### Next — البون

`pruduct` (23 rows) is the crusher/supplier table. In this app
**المورد = الكسّارة**, one entity with two names: the menu button says «بيانات
الكسارات» while the screen's own caption says «شاشة إدخال بيانات الموردين», both
bound to `pruduct`. Same for `FSANADSUP` («مدفوعات الكسارات» / «مدفوعات
الموردين»).

`pruduct` **is** migrated as of 2026-09-04 — see the section above for the three
judgement calls the import made and how to reverse them.

Its shape is **almost exactly `fanii`**, which is why the customers screen was
the template:

    id · productName · number1 · notees · BalancFirst · date123
    sen1 · sen2 · sen3 · sen6safi · sen6bodra · sen3adsa · bodra · raml
    Sen++ · SeenModarg          <- the same ten fixed price columns

`tawrid_suppliers` is `tawrid_customers` minus the discount and the tractor
price grid (`pruduct` has no `Des` column and no subform) — the ten price
columns stay fixed columns here too, by the same standing decision. Vouchers:
`sanadsup` (139 rows, `supid` → `pruduct.id`, 0 orphans, but 119 of the 139 have
an empty بيان), which belongs to a later phase.

**البون** (`TBBOOn`, 4,072 rows, dated 2025-01-04 → 2026-08-22) is the heart of
the module: each ticket carries three independent price layers at once. Audited
2026-09-04; every formula below holds on **all 4,072 rows**, so all of them are
safe as PostgreSQL `GENERATED` columns:

    العميل    totalCus = PriceCus  × Tak3ib      SafiCus = totalCus − amountDis
    الكسّارة   totalres = Priceres  × Tak3ibres
    الجرار    totalman = Pricemand × Tak3ib      <- the CUSTOMER's volume

**There are two volumes on every ticket.** `Tak3ib` (customer) and `Tak3ibres`
(crusher) differ on **4,015 of 4,072** rows — 60.5 vs 59.0 and so on. The hauler
is paid on the customer's volume: `totalman` against `Tak3ibres` holds on only
214 rows. Collapsing the two into one number would silently rewrite the
crusher's account.

**`disc` is a fraction, not a percentage.** `amountDis = totalCus × disc` holds
on all 177 discounted tickets (`× disc/100` holds on 1). The only non-zero value
is `0.01` = 1%. ⚠ `tawrid_customers.discount_percent` stored `fanii.Des` — the
same `0.01` — in a column named *percent* with a `CHECK 0..100`. Before the البون
math is written, either that column is rescaled to `1.00` or the ticket divides
by 100; the two must agree or every discount is off by a factor of 100.

**Dangling references**, and whether they can be recovered:

| column | → | dangling | NULLs | recoverable? |
|---|---|---|---|---|
| `cus_id` | `fanii` | 911 | 12 | **No** — `TBBOOn` stores no customer name |
| `maatora_id` | `tbgrarat` | 305 | 1 | **Yes** — the 9 recovered tractor cards cover these |
| `res-id` | `pruduct` | 4 | 0 | **No** — crusher id 22; no name is stored |

So ~923 tickets have no customer and 4 have no crusher. That is the first
decision of the phase: placeholder cards, or leave them out. The tractor side is
already solved by phase 1.

**Numbering.** `number1` is the البون number — 4,072 distinct, **zero
duplicates**, range 0..4117, a sound unique key. `NumberEissal` is the receipt
number — 107 duplicated values and a max of `888888880`; do **not** make it
unique.

**`typeharka`** has three states only: `سن` 3,883 · `رمل` 178 · empty 11 — the
item family, sitting beside the free-text `productName`. That column has 14
distinct values across the tickets including the typos `س1` and `س 2`, one empty,
and `سن 3` (13) vs `سن عتاقة` (3) — the same item under two names. The Access
screen mapped this typed string to a price column through **10 hardcoded `IF`
branches**; prices stay fixed columns by standing decision, so that mapping has
to live somewhere deliberate.

After البون: سندات القبض والصرف and the three account statements.

## Automatic Schema Bootstrap + Installer v4.4.9 (added 2026-07-27)

The application and installer now build the database schema automatically, so a
fresh device works with **no manual migration step**, and future schema changes
no longer need numbered migration files.

- `app/database/schema/full_schema.sql` — one idempotent DDL file (every
  `CREATE TABLE/SEQUENCE/INDEX` is `IF NOT EXISTS`; constraints wrapped in a
  `pg_constraint`-guarded `DO $$` block; identity columns guarded via
  `pg_attribute.attidentity`; triggers `DROP ... IF EXISTS` + create; functions
  `CREATE OR REPLACE`). Generated from a `pg_dump --schema-only` of the reference
  `InvPhase2` DB, made idempotent by a transformer; two artifact tables
  (`app_users_legacy`, `backup_006_customers_area_code`) excluded.
- `app/database/schema_bootstrap.py` → `ensure_full_schema(db)` runs it via
  `Database.execute_script`. Wired into app startup (`review_window.py`
  `_bootstrap_security`) and the installer (`configure_cli.py` `_cmd_provision`),
  both before the existing security `ensure_schema` (now a redundant no-op).
- Adding a table/column later: add one idempotent statement to `full_schema.sql`
  (`CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) — it
  self-applies on every device at next launch. No numbered migrations.
- Traps fixed while generating it: pg_dump comment headers contain `;`; pg_dump
  18 emits `\restrict`/`\unrestrict` psql meta-commands that break psycopg;
  pg_dump's `set_config('search_path','')` blanked the shared connection's
  search_path and broke the security schema's unqualified DDL — all stripped.
- Bundling: `installer/PHASEINV2-app.spec` datas gains `app/database/schema`;
  `build_main_device.ps1` validates `full_schema.sql` is present in the bundle.
- Verification:
  - Idempotent across repeated applies (psql ×3, psycopg ×2), 24 base tables.
  - Safe no-op on a full copy of the live database — **zero data loss** (row
    counts identical before/after).
  - End-to-end `configure_cli provision` on a fresh DB: `ok:true`, 24 tables +
    `sales_invoices` + Admin + 104 permissions, idempotent on re-run.
  - `tests/unit/test_schema_bootstrap.py` (6 passed); full unit suite 758 passed
    (only the two pre-existing failures remain).
- Installer rebuilt to **v4.4.9**: `Successful compile (299.6 sec)`, all bundle
  checks incl. "full schema bundled (auto-provision)" pass. Output
  `D:\PHASEINV2\dist\PHASEINV2_MainDevice_Setup.exe` (~178 MB). Pre-build backup
  kept: `PHASEINV2_MainDevice_Setup_BACKUP_v4.4.8_20260727_120245.exe`.

## Main Device Installer v4.4.8 (added 2026-07-27)

The Main Device Windows installer was rebuilt to ship the latest code.

- Version bump: `installer/PHASEINV2-MainDevice.iss` `MyAppVersion` **4.4.7 → 4.4.8**
  (with a changelog comment block). `AppId` is unchanged, so it upgrades in place.
- Included updates (all code, bundled automatically by re-running the build):
  - **"حفظ وإرسال واتساب"** sales-invoice action (save → silent PDF export to a
    remembered folder → open the customer's WhatsApp Web chat and auto-send the
    PDF, PDF-only).
  - **Company-stamp print alignment** (stamp in-flow directly under the totals on
    all 8 templates, with pagination safety).
  - **Global sales-invoice numbering** (one editable, globally-unique automatic
    number, starting at 50001).
- Build: `powershell -NoProfile -ExecutionPolicy Bypass -File installer\build_main_device.ps1`
  ran clean — PyInstaller froze `PHASEINV2.exe` + `phaseinv2-config.exe`, all
  bundle validations passed (PySide6, QtWebEngine, psycopg, cryptography,
  migrations, ZATCA assets, all 8 print templates, frozen-config smoke test), and
  Inno Setup reported `Successful compile (303.8 sec)`.
- Output: `D:\PHASEINV2\dist\PHASEINV2_MainDevice_Setup.exe` (v4.4.8, ~178 MB).
  - Pre-build backup of the previous installer kept in the same folder:
    `PHASEINV2_MainDevice_Setup_BACKUP_v4.4.7_20260727_110113.exe`.
  - Verified the bundle actually carries the new code: the WhatsApp button string
    is present in `_internal\app\ui\screens\saudi_sales_invoice_page.py`, and
    migrations 017 + 018 are present under `_internal\app\database\migrations\`.
- ⚠️ **The installer ships the migration `.sql` files but does NOT apply them.**
  On every customer device, `017_add_company_stamp.sql` and
  `018_create_sales_invoice_numbering.sql` must be run by hand against that
  device's PostgreSQL DB, or the stamp and global-numbering features raise raw
  Postgres errors. (The local `InvPhase2` DB already has both applied.)

## Saudi Invoice Print Stamp Alignment (added 2026-07-27)

The optional company stamp now prints directly below the totals at the physical
right in all eight Saudi sales-invoice templates.

- Shared presentation:
  - The stamp uses a bounded `140px × 100px` box with `object-fit: contain`.
  - It prints at full opacity with controlled saturation, contrast, and
    brightness enhancement.
  - A 10px gap separates it from the totals, and it remains in normal document
    flow rather than being pinned to the page edge.
- Pagination safety:
  - Templates v3-v8 reserve the stamp's 110px vertical footprint on the last
    page only when **إظهار الختم** is enabled and valid company stamp bytes
    exist.
  - Stamp-free, disabled-stamp, and missing-stamp invoices keep their previous
    pagination.
- Verification:
  - Changed Python modules compile successfully with Python 3.11.
  - Targeted invoice-print regression suite: **292 passed, 1 skipped**.
  - Direct generated-HTML inspection confirmed the approved stamp contract in
    **8/8** templates.

## Global Saudi Sales Invoice Numbering (added 2026-07-27)

Saudi sales invoices now receive one editable, globally unique automatic
number shared by all seller companies.

- Automatic sequence:
  - PostgreSQL sequence: `sales_invoice_number_seq`.
  - Empty-database first number: `50001`, then `50002`, `50003`, and so on.
  - The sequence is concurrency-safe and reservations may leave gaps when a
    user cancels a new invoice.
  - A saved manual ASCII-numeric value at or above `50001` advances the
    sequence forward when necessary. Lower and non-numeric manual values never
    move it backward.
- Global uniqueness:
  - Migration `018_create_sales_invoice_numbering.sql` replaces the old
    seller-scoped unique constraint/index with
    `uq_sales_invoices_invoice_number` on `invoice_number`.
  - The repository and service now reject a duplicate number regardless of
    seller company.
  - Historical duplicates cause the migration to abort without renumbering or
    deleting any rows.
- UI:
  - **New** reserves and displays the next number while keeping the field
    editable.
  - **Duplicate Invoice** preserves copied invoice content but reserves a new
    number.
  - If reservation fails, an Arabic warning is shown and the field remains
    editable for manual entry.
  - Existing approved-invoice read-only behavior is unchanged.
- Live database application:
  - Safety backup created at
    `Backups/backup_manual_20260727_015827.sql`.
  - Migration 018 applied successfully to `InvPhase2`.
  - Immediately after application, the verified state was
    `last_value = 50001`, `is_called = false`, zero invoice rows, and only the
    global unique index.
  - The first real draft was subsequently created with invoice number `50001`.
    The live sequence is now `last_value = 50001`, `is_called = true`, so the
    next automatic invoice number is `50002`.
- Tests:
  - New isolated migration coverage handles both a standalone legacy index and
    the constraint-owned index used by the live database.
  - Targeted migration/repository/service/UI verification: **157 passed**.
  - Changed Python modules compile successfully.
  - Full suite: **1085 passed, 10 skipped, 3 failed**. The remaining failures
    are unrelated: two Daily Follow-up smart-report debounce/dropdown tests and
    `test_skeleton_imports_settings` (`CRM` expected versus `InvPhase2`).

## Saudi Invoice Save + WhatsApp Fix (added 2026-07-27)

The Saudi sales-invoice toolbar action **"حفظ وإرسال واتساب"** was saving and
exporting the invoice, but automatic WhatsApp delivery could miss the intended
customer or send the simulated keystrokes to the wrong window.

- Root causes in `app/ui/screens/saudi_sales_invoice_page.py`:
  - When WhatsApp Web was already open, the code searched the existing chat
    list instead of navigating to the customer's `send?phone=` URL. A new
    customer with no previous conversation therefore could not be selected.
  - The delayed `Ctrl+V` and `Enter` keystrokes were sent globally without
    refocusing WhatsApp Web immediately beforehand, so they could land in the
    CRM or another active window.
- Fix:
  - `_send_invoice_via_whatsapp(...)` now always opens the normalized customer
    number through `open_whatsapp_web_multi(target, "")`, even when WhatsApp Web
    is already open.
  - The flow calls `focus_whatsapp_web_window()` immediately before pasting the
    exported PDF and before every automatic send attempt.
  - Save failure, missing/invalid phone, PDF export failure, and browser-open
    failure still stop the flow through their existing guarded branches.
- Regression coverage in `tests/unit/test_saudi_sales_invoice_page.py`:
  - `test_whatsapp_send_opens_the_customer_url_even_when_whatsapp_is_already_open`
  - `test_whatsapp_send_refocuses_web_before_paste_and_send`
- Verification:
  - WhatsApp/invoice targeted suite: **113 passed**.
  - Python compile check for the changed page and test: passed.
  - No live customer message was sent during verification; external delivery
    was intentionally represented by controlled test doubles.

## F5 Smart Customer Entry on Daily Follow-up (added 2026-06-25)

Quick customer selection from the Daily Follow-up screen (شاشة المتابعة
اليية).

- Service: `app/services/review_data_service.py` ->
  `ReviewDataService.search_customers(keyword, limit=100)`.
  - Partial case-insensitive (`ILIKE`) search across `customer_id` (code),
    `customer_name`, and `phone_number` (Arabic + English work; partial phone
    numbers work).
  - Empty keyword returns all customers (`ORDER BY customer_id ASC LIMIT`).
  - Non-empty keyword orders an **exact code match first**, then by
    `customer_id ASC`.
  - Capped at 100 rows for performance.
  - Documented limitation: the `customers` table currently has **no separate
    mobile column** (only `phone_number`) and **no active/inactive flag** per
    `app/database/migrations/001_create_core_schema.sql`. If those are added,
    only this method needs a small `WHERE`/column change — noted in its
    docstring. No schema change was needed or made.
- Reusable UI: `app/ui/dialogs/customer_lookup_dialog.py` ->
  `CustomerLookupDialog`.
  - Title "اختيار العميل / Select Customer"; RTL; search box on top, results
    table below with column headers كود العميل / اسم العميل / الهاتف.
  - Reuses theme helpers (`GREEN`, `_button_style`); no SQL in the UI.
  - Search is debounced 200ms via `QTimer`; Enter = accept highlighted row,
    double-click = accept, Esc = close; null phone/code handled through the
    service `COALESCE` + cell `"" if None` rendering; "لا يوجد عملاء" shown
    on no results. Reads `selected_customer_id` / `selected_customer`.
- Daily Follow-up wiring: `app/ui/screens/daily_followups_screen.py` ->
  `DailyFollowupsScreen`.
  - Binds **F5** (`QShortcut`) to `open_customer_lookup()` — non-conflicting
    with the existing F1 record lookup.
  - On selection: enters a fresh new record (`new_record()` resets manual
    fields + defaults `follow_up_date` today), then fills **only
    customer-related fields** via the existing `_load_customer(...,
    prefill_installments=False)` (customer code/id, name, phone, area, building,
    unit, floor). Installments and other follow-up/status fields stay empty.
  - Moves focus to the first manual follow-up field (`follow_up_date`).
- Tests: `tests/unit/test_review_data_service.py` adds 2 cases for
  `search_customers` (empty keyword params; keyword params include the exact
  code sort key). All targeted UI/service tests pass (18 passed in
  `tests/unit/`) — only the pre-existing `test_skeleton_imports_settings`
  `CRM` vs `crm` assertion still fails, unchanged by this work.

## Working Directory

Main application folder:

`D:\PHASEINV2\CRM_PYTHON_APP_STRUCTURE`

The parent folder `D:\PHASEINV2` also contains Access analysis, PostgreSQL
design output, installers, and other reference material. The runnable PySide6
application is under `CRM_PYTHON_APP_STRUCTURE`.

## Users & Permissions system (added 2026-06-25)

A dynamic users/roles/permissions system was added with login and enforcement.

- DB layer: `app/database/db.py` (`Database` psycopg helper),
  `app/models/security_models.py` (DDL: roles, app_users, permissions,
  role_permissions, user_permissions, user_login_logs — all `IF NOT EXISTS`),
  `app/repositories/security_repository.py` (all SQL + `ensure_schema()`),
  migration `app/database/migrations/004_create_security_schema.sql`.
- Security primitives: `app/security/password_hasher.py` (PBKDF2-SHA256),
  `app/security/session_context.py` (`SESSION` — current user + effective codes,
  permissive when no user is logged in).
- Services: `app/services/permission_registry.py` (central screen/report/action
  registry; permission code = `module_code.target_code.action_code`; reports are
  auto-discovered from `app/reports/*` via a `PERMISSION_TARGET` attr),
  `app/services/permissions_sync_service.py` (upsert + deactivate-missing, never
  deletes), `app/services/permission_service.py` (effective resolution + matrix
  + role/override editing), `app/services/auth_service.py` (authenticate, seed
  Admin/1 full-access, login logs, user CRUD with last-admin guard).
- UI: `app/ui/login_window.py`, `app/ui/screens/users_page.py`,
  `roles_page.py`, `user_permissions_page.py`.
- Integration: `app/ui/main_window.py` has a collapsible RTL tree section
  "المستخدمين والصلاحيات" with 3 children; opening any screen is gated by the
  `view` permission and unviewable menu items are hidden. `base_crud_screen.py`
  gates New/Edit/Save/Delete by create/edit/save/delete. `run_app()` now:
  ensure schema → seed Admin/1 → sync permissions → login → load effective
  permissions into `SESSION` → splash → main window.
- Default login: **Admin / 1** (full access). Tests:
  `tests/unit/test_permission_system.py` (8 passed, no DB needed).

## Current App Shape

- Entry point: `app/main.py` -> `app/ui/review_window.py:run_app()`
- Active review UI is now split by module (see "UI Structure" below).
- Active CRUD/data metadata service: `app/services/review_data_service.py`
- PostgreSQL schema/migration scripts: `app/database/migrations/`
- Old per-form placeholder stubs still exist under `app/ui/screens/` (e.g. `customer_screen.py`, `login_screen.py`); they are unused legacy scaffolding, not the active screens.

## UI Structure (refactored 2026-06-25)

The previous single-file UI (`review_window.py`, ~929 lines, all screens in one
`QTabWidget`) was split into per-module screen files behind a sidebar shell.
Layering is UI / business / database:

- Shell + navigation: `app/ui/main_window.py` -> `ReviewMainWindow`.
  - Owns only the sidebar/main menu; its central area stays empty (a hint).
  - Each sidebar button opens its module as a **separate, maximized top-level
    window** via `open_screen(key)` (`showMaximized()`). Windows are cached per
    module in `open_windows` and re-focused if already open.
  - `MODULES` registry + `SCREEN_BY_KEY` map each screen; add a module there to
    expose it.
- Per-module screens (`app/ui/screens/`), each its own class:
  - `customers_screen.py` -> `CustomersScreen`
  - `employees_screen.py` -> `EmployeesScreen`
  - `daily_followups_screen.py` -> `DailyFollowupsScreen`
  - `places_screen.py` -> `PlacesScreen`
  - `case_statuses_screen.py` -> `CaseStatusesScreen`
- Reusable CRUD page: `app/ui/screens/base_crud_screen.py` -> `BaseCrudScreen`
  (was `ReviewCrudPage`; each screen subclasses it with its `TableSpec`).
- F1 lookup dialog: `app/ui/dialogs/record_lookup_dialog.py` -> `RecordLookupDialog`.
- Shared UI helpers: `app/ui/common/theme.py` (colors, button style, delegate,
  layout maps) and `app/ui/common/lookup_filters.py` (pure, unit-tested
  `filter_lookup_rows` / `project_visible_columns`).
- `app/ui/review_window.py` is now a thin launcher (`run_app()`) that re-exports
  the moved names for backward compatibility, so existing imports/tests like
  `from app.ui.review_window import filter_lookup_rows` and `ReviewCrudPage`
  still work.
- All database access still goes only through `ReviewDataService`; no SQL was
  moved into the UI. Screen behavior is unchanged from the tabbed version.

### Startup performance

To avoid the lag when a screen (especially daily follow-ups) was opened for the
first time:

- `ReviewDataService` now reuses **one long-lived autocommit connection**
  instead of opening/closing a PostgreSQL connection per query. `connect()` is
  now a context manager that yields the shared connection and reconnects if it
  goes stale. This is the main fix for first-open lag.
- On launch, `run_app()` shows a loading splash (`app/ui/common/loading_splash.py`
  -> `LoadingSplash`) and calls `ReviewMainWindow.prewarm_all(...)` to build every
  screen up front (daily follow-ups first) with a progress bar. Only when all
  screens are ready is the maximized main window shown — so it opens ready to use
  with no first-click lag. Clicking a module then re-uses its prebuilt window.
- `BaseCrudScreen._fill_combo` bulk-loads combos with view updates/signals
  disabled so filling the full customer list does not repaint per item.

## Latest Customer Screen Changes

Files changed for the latest customer-screen request:

- `app/ui/review_window.py`
  - Hides the four unused customer form fields:
    - `installment_duration_years`
    - `remaining_installments`
    - `installment_amount`
    - `legacy_area_number_2`
  - Uses a customer-only area selector for `place_area_feddan`, populated from `places`.
  - Adds an F1 customer lookup dialog.
  - The F1 dialog now shows only the search field and the results table (the "الأعمدة" column show/hide section was removed per request). Search runs across all non-hidden columns; double-click loads a customer into the main form.
  - Lookup table rebuild is optimized: columns/headers are set once, and row repopulation runs with `setUpdatesEnabled(False)` + a single `setRowCount(...)` to avoid per-keystroke repaint lag on the full customer list.
  - Search is debounced with a 200ms single-shot `QTimer`: typing restarts the timer and the table only refilters/redraws once typing pauses, instead of on every keystroke.
  - Makes the customer list panel wider and input controls slightly shorter.
  - Form layout is label-beside-input on one row (label right, input to its left), labels left-aligned within a 90px column.
  - All Customer Data input text is right-aligned: `QLineEdit` and the area `QComboBox` use `setLayoutDirection(Qt.LeftToRight)` + `setAlignment(Qt.AlignRight | Qt.AlignVCenter)` so both Arabic and numeric values sit on the visual right (RTL inheritance would otherwise flip `AlignRight`). The combo is editable+read-only with a right-aligned `lineEdit()`, and a `_RightAlignDelegate` right-aligns the dropdown items.
  - Input text matches the labels: `font-size:14px; font-weight:900; color:#111827`.

- `app/services/review_data_service.py`
  - Adds `FieldSpec.hidden_on_form`.
  - Adds `list_places_for_selection()`.
  - Adds `next_id()`.
  - Makes customer IDs start at `1001` when the table is empty; otherwise uses `MAX(customer_id) + 1`.
  - Keeps hidden form fields out of update payloads so editing a customer does not clear existing hidden values.

- `app/database/migrations/003_renumber_customers_from_1001.sql`
  - Renumbers existing customers to start at `1001`.
  - Updates `daily_followups.customer_id` through a temporary ID map in the same transaction.

- `tests/unit/test_review_data_service.py`
  - Covers hidden customer fields and customer ID generation.

- `tests/unit/test_customer_lookup_filter.py`
  - Covers lookup search and visible-column projection helpers.

## Verification State (updated 2026-07-27)

Passing WhatsApp/invoice verification:

```powershell
& 'C:\Users\esraa\AppData\Local\Programs\Python\Python311\python.exe' -m pytest tests\unit\test_saudi_invoice_whatsapp.py tests\unit\test_saudi_sales_invoice_page.py -q
```

Result:

`113 passed`

Passing compile check:

```powershell
& 'C:\Users\esraa\AppData\Local\Programs\Python\Python311\python.exe' -m py_compile app\ui\screens\saudi_sales_invoice_page.py tests\unit\test_saudi_sales_invoice_page.py
```

Full-suite result:

```powershell
& 'C:\Users\esraa\AppData\Local\Programs\Python\Python311\python.exe' -m pytest -q
```

Latest result: **1085 passed, 10 skipped, 3 failed**. The failures are outside
the WhatsApp and automatic-numbering changes:

- `tests/unit/test_daily_followup_smart_report_screen.py::test_customer_name_dropdown_remote_searches_full_customer_lookup_after_debounce`
  did not observe the expected debounced remote-search call.
- `tests/unit/test_daily_followup_smart_report_screen.py::test_customer_name_partial_search_opens_dropdown_with_all_matching_names`
  observed the preloaded placeholder/customer IDs instead of the debounced
  remote-search results.
- `tests/unit/test_skeleton.py::test_skeleton_imports_settings` expects database
  name `"CRM"`, while the current configuration returns `"InvPhase2"`.

## Python Note

Use the explicit Python 3.11 executable shown above for verification in this
checkout. The Python 3.12 installation currently resolves its prefix to the
working directory and fails during startup with `ModuleNotFoundError:
No module named 'encodings'`. The first `python` command on `PATH` still points
to the obsolete Python 3.4 installation.

## Git / CodeRabbit Note

`D:\PHASEINV2\CRM_PYTHON_APP_STRUCTURE` is a Git repository on branch
`feature/daily-followup-smart-report`. The working tree contains many existing
modified and untracked files. In particular, the Saudi invoice page and its
unit-test file currently appear as untracked, so both must be included
explicitly in any future commit containing this WhatsApp fix.
