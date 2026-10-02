# Invoice Print Stamp Alignment Design

## Goal

Update the optional company stamp in all eight Saudi sales-invoice print
templates so that it appears directly below the totals, aligned to the physical
right edge instead of the physical left edge. Increase its printed width from
90px to 140px and make the source image look clearer and more vivid without
changing the stored company stamp.

## Scope

- Applies to `saudi_invoice_print.py` and templates `v2` through `v8`.
- Changes only the optional printed company stamp.
- Does not change the company logo, QR code, totals content, invoice data,
  pagination policy, or the "إظهار الختم" checkbox behavior.

## Architecture

All eight templates already render the stamp through the shared
`stamp_overlay_html(data)` helper in `saudi_invoice_print.py`, immediately after
their totals block. The implementation will preserve that shared boundary and
change the helper once instead of adding eight independent positioning rules.

The generated stamp wrapper will remain an in-flow block. It will use physical
right alignment so RTL/LTR direction differences between templates cannot
reverse the requested placement. The image will use a 140px by 100px bounding
box, preserve its aspect ratio inside that box, use full opacity, and apply
`saturate(1.25) contrast(1.12) brightness(1.03)` for a brighter print
appearance.

## Rendering Rules

- Wrapper:
  - Remains directly after the totals block.
  - Uses `text-align: right`.
  - Uses a 10px top margin to separate it from the totals.
  - Retains page-break protection so the image is not split.
- Image:
  - Uses a 140px by 100px bounding box.
  - Uses `object-fit: contain`.
  - Uses `opacity: 1` and
    `filter: saturate(1.25) contrast(1.12) brightness(1.03)`.
- Visibility:
  - No stamp is emitted when the checkbox is off.
  - No stamp is emitted when the seller has no stored stamp.

## Data Flow and Failure Behavior

The existing flow is unchanged:

1. The print action passes invoice data and `show_stamp`.
2. `stamp_overlay_html` checks that the stamp is enabled.
3. `company_stamp_data_uri` converts the stored stamp bytes to a data URI.
4. The helper emits the aligned HTML only when valid stamp bytes exist.

Invalid, absent, or disabled stamp data continues to produce an empty string,
so printing remains safe and no broken image placeholder appears.

## Verification

Automated tests will verify:

- The shared stamp HTML contains right alignment, a 140px width, full opacity,
  and the vividness filter.
- The stamp still stays hidden when disabled or unavailable.
- Every one of the eight template builders includes exactly one stamp when
  enabled and inherits the shared size/alignment styling.
- Existing invoice print tests continue to pass.

Generated output will also be checked with a last-page line count near each
template's pagination limit. If any fixed-height template would clip the
140px-by-100px stamp box, its last-page row budget will reserve the missing
space only when the stamp is enabled. This keeps short and stamp-free invoices
unchanged while preventing overlap with the footer.
