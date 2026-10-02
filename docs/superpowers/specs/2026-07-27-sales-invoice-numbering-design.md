# Global Sales Invoice Numbering Design

Date: 2026-07-27

## Goal

Automatically populate Saudi sales invoices with one global numeric sequence
starting at `50001`, while keeping the invoice-number field editable.

The sequence is shared by every seller company. Saving a higher manual numeric
value advances future automatic numbers, while a lower value never moves the
sequence backward.

## Confirmed Behavior

- Pressing **New** reserves and displays the next number.
- The first automatic number on an empty database is `50001`.
- Later automatic numbers are `50002`, `50003`, and so on.
- **Duplicate Invoice** reserves a new number instead of copying or clearing the
  source invoice number.
- The invoice-number field remains editable for new invoices and editable
  drafts.
- Saving manual `50010` makes the next automatic number at least `50011`.
- Saving a lower manual number does not move the sequence backward.
- Manual non-numeric values remain supported for backward compatibility and do
  not affect the numeric sequence.
- Invoice numbers are globally unique across seller companies.
- Reserving a number and then cancelling the new invoice may leave a gap. This
  is accepted so concurrent users never receive the same automatic number.
- Approved invoices keep the screen's existing read-only behavior.

## Chosen Approach

Use a PostgreSQL sequence plus a global unique index.

This is preferred over `MAX(invoice_number) + 1`, which can return the same
number to concurrent users. It is also preferred over assigning a number only
at save time because the requested number must be visible and editable as soon
as the user starts a new invoice.

## Database Design

Add an idempotent migration for the existing `sales_invoices` table:

1. Verify that no invoice number is duplicated globally. If duplicates exist,
   stop with an actionable error instead of changing historical data.
2. Create `sales_invoice_number_seq` as a `bigint` sequence with a minimum of
   `50001`.
3. Seed the sequence forward from the greatest numeric invoice number already
   stored, with `50000` as the empty-table baseline. The migration never moves
   an existing sequence backward.
4. Replace the seller-scoped unique index
   `uq_sales_invoices_company_number` with a global unique index on
   `sales_invoices(invoice_number)`.

The column remains `varchar`, so existing print, search, XML, audit, and report
code keeps receiving a string.

## Repository Responsibilities

`SaudiSalesInvoiceRepository` will expose:

- `reserve_invoice_number() -> str`
  - obtains the next sequence value atomically;
  - skips an already-stored value if external/manual data consumed that number;
  - returns the decimal string shown by the UI.
- transaction-local sequence synchronization used by invoice insert/update:
  - when the stored invoice number is ASCII digits and at least `50001`, move
    the sequence forward to that number if necessary;
  - never move it backward;
  - ignore non-numeric manual values.

Reservation and forward synchronization use the same PostgreSQL advisory-lock
key so an automatic reservation cannot race a higher manual save.

## Service Responsibilities

`SaudiSalesInvoiceService` will:

- expose `reserve_invoice_number()` as the UI-facing boundary;
- validate invoice-number uniqueness globally rather than per seller;
- preserve the existing required/non-blank validation;
- preserve manual text values and current Arabic validation messages, changing
  the duplicate message to describe global duplication.

The database global unique index remains the final concurrency guard.

## UI Flow

### New invoice

`enter_new_mode()` clears the form, requests a number from the service, places
it in `invoice_number_input`, and keeps the field editable.

If automatic reservation fails, the screen shows an Arabic warning and leaves
the editable field empty so the user can enter a number manually.

### Duplicate invoice

`_detach_as_new_draft()` keeps the copied seller, customer, lines, and other
draft data, but requests a new automatic invoice number and places it in the
field.

### Existing invoice

Loading an invoice continues to display its stored number. Draft edit mode
continues to allow manual changes. View mode and approved invoices remain
read-only through the existing mode rules.

## Error Handling

- Duplicate manual number: reject save with an Arabic validation warning.
- Sequence unavailable: warn and allow manual entry; do not crash or save an
  empty number.
- Database unique conflict after an external race: translate it into the same
  duplicate-number validation outcome where the repository/service boundary
  permits.
- Migration sees historical global duplicates: abort without deleting,
  renumbering, or merging data.

## Testing

Follow test-driven development.

### Repository tests

- Empty state reserves `50001`.
- Consecutive reservations increase.
- Existing higher numeric data seeds the sequence forward.
- Manual higher numeric save advances the next reservation.
- Manual lower numeric save does not move the sequence backward.
- Manual non-numeric save does not affect the sequence.
- Global uniqueness rejects the same number under a different seller.

### Service tests

- Reservation is delegated through the service.
- Duplicate number under another seller is rejected.
- Existing invoice update excludes its own row from duplicate detection.

### UI tests

- New mode displays the reserved number and leaves the field editable.
- Duplicate mode displays a newly reserved number.
- A reservation failure warns and leaves the field editable for manual input.

### Verification

- Run the targeted repository, service, and page test files.
- Compile the changed Python modules.
- Run the full suite and report any unrelated failures separately.

## Out of Scope

- Renumbering historical invoices.
- Removing gaps caused by abandoned drafts or cancelled New actions.
- Changing ZATCA's ICV/PIH chain.
- Changing receipt-voucher number derivation.
- Adding prefixes or zero padding to the automatic number.
