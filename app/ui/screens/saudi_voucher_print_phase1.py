"""Phase-1 receipt-voucher print templates (المرحلة الأولى — سندات).

Three standalone, Arabic-first (RTL) printable «سند قبض» layouts for the new
«مرحلة أولى ← سندات» action on the Saudi sales-invoice screen. They are kept
**separate** from the nine Phase-2 voucher templates in
``saudi_receipt_voucher_print`` — exactly as the Phase-1 *invoice* templates are
kept separate from the Phase-2 invoice templates. Only the small, shared,
side-effect-free helpers are reused from the Phase-2 voucher module and the
invoice module (``_money`` / ``_date`` formatters, ``amount_in_words_ar``,
``company_logo_data_uri``, ``signature_line_html``, the preview dialog and the
direct-PDF export), so the two families behave identically where they overlap.

The three designs were chosen by the user from a mock-up gallery:

* النموذج الأول — «فاخر داكن بلمسة ذهبية»: a dark navy header band with a gold
  hairline, the logo in a gold ring, a cream amount box.
* النموذج الثاني — «جدول مؤطر بالكامل»: every field is a bordered grid cell; the
  top-right cell carries the logo and the seller's data.
* النموذج الثالث — «بكعب قابل للفصل»: a burgundy tear-off stub down the side
  carrying a second copy of the logo, serial, date and amount.

Every layout consumes the same ``data`` dict the Phase-2 vouchers do — keys
``number`` / ``issue_date`` / ``amount`` / ``received_from`` / ``purpose`` and a
``seller`` mapping (``name`` / ``cr`` / ``vat`` / ``address``) — so the sales
screen's :meth:`_collect_voucher_data` feeds preview, print and PDF unchanged.
Presentation only: nothing here touches the database.

The seller LOGO is the deliberate focus of all three (a user priority): when the
company has a stored logo it is drawn; when it does not, a labelled placeholder
box keeps the logo's position visible so the chosen layout still reads correctly.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QPageSize
from PySide6.QtWidgets import QMessageBox, QWidget

from app.ui.screens.saudi_invoice_print import (
    amount_in_words_ar,
    company_logo_data_uri,
    signature_line_html,
)
from app.ui.screens.saudi_receipt_voucher_print import (
    SaudiReceiptVoucherPreviewDialog,
    _date,
    _money,
    export_receipt_voucher_to_pdf,
)

# ---- النموذج الأول (luxury dark + gold) --------------------------------------
P1_NAVY = "#0f172a"        # header band
P1_GOLD = "#b8912f"        # the hairline + rings + accents
P1_GOLD_LT = "#d9b25a"     # gold text on the dark band
P1_CREAM = "#f6efe0"       # amount-box wash
P1_CREAM_INK = "#5c4a12"   # value on the cream wash
P1_INK = "#1f2937"         # primary values
P1_MUTED = "#6b7280"       # meta lines
P1_HEAD_SUB = "#c9cfda"    # cr / vat on the dark band

# ---- النموذج الثاني (fully framed grid) --------------------------------------
P2_TEAL = "#0b5563"        # the frame + dividers + title
P2_SOFT = "#e2eff1"        # label-cell fill
P2_INK = "#1f2937"         # values
P2_MUTED = "#5b6570"       # cr / vat meta
P2_LINE = "#cfe0e2"        # inner hairlines

# ---- النموذج الثالث (tear-off stub) ------------------------------------------
P3_WINE = "#7c2d12"        # the stub band + accents + title underline
P3_SOFT = "#f6e9e2"        # stub background wash
P3_INK = "#2c2c2a"         # values
P3_MUTED = "#5f5e5a"       # labels / meta
P3_LINE = "#e7d7cd"        # ledger underlines

# ---- النموذج الرابع (modern info tiles) --------------------------------------
P4_GREEN = "#1d9e75"       # accent — header, amount, tile labels
P4_GREEN_DK = "#0f6e56"    # darker green for the amount value
P4_SOFT = "#e1f5ee"        # amount panel + tile wash
P4_INK = "#1f2937"         # tile values
P4_MUTED = "#5b6b64"       # captions / meta
P4_LINE = "#cfe6dd"        # tile borders

# ---- النموذج الخامس (color-block / geometric) --------------------------------
P5_ORANGE = "#d85a30"      # the primary colour block + accents
P5_ORANGE_DK = "#993c1d"   # text on the pale-orange wash
P5_GREEN = "#1d9e75"       # the secondary colour block
P5_SOFT = "#faece7"        # amount wash
P5_INK = "#1f2937"         # values
P5_MUTED = "#6b6460"       # meta
P5_LINE = "#efdfd8"        # ledger underlines

# A neutral horizon emblem, used only when the company has no stored logo, so the
# logo's PLACE on the sheet is always visible. ``currentColor`` lets each design
# tint it to its own accent.
_LOGO_MARK_SVG = (
    '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="3" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="24" cy="20" r="8"/><path d="M6 38h36"/>'
    '<path d="M14 38c2-6 6-9 10-9s8 3 10 9"/></svg>'
)


def _seller_fields(data: dict[str, Any]) -> dict[str, str]:
    """Escape the seller header fields once for a builder."""
    seller = data.get("seller") or {}
    return {
        "name": html.escape(str(seller.get("name") or "")),
        "cr": html.escape(str(seller.get("cr") or "")),
        "vat": html.escape(str(seller.get("vat") or "")),
        "address": html.escape(str(seller.get("address") or "")),
    }


def _doc(sheet_inner: str, *, ink: str = "#1a1a1a") -> str:
    """Wrap a sheet body in the shared A4 print scaffold (fonts + @page)."""
    return f"""<!DOCTYPE html>
<html lang="ar">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Arabic:wght@400;500;600;700;800&family=Arimo:wght@400;700&display=swap" rel="stylesheet">
<style>
  html, body {{ margin: 0; padding: 0; background: #e9eaec; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .sheet {{ width: 794px; min-height: 1123px; position: relative; background: #ffffff;
    font-family: 'Noto Sans Arabic', 'Tahoma', 'Arial', sans-serif; color: {ink}; direction: rtl;
    box-sizing: border-box; margin: 0 auto; box-shadow: 0 1px 6px rgba(0,0,0,0.12); overflow: hidden; }}
  .ltr {{ direction: ltr; font-family: 'Arimo', 'Arial', sans-serif; unicode-bidi: isolate; }}
  @page {{ size: A4; margin: 0; }}
  @media print {{
    html, body {{ background: #ffffff; }}
    .sheet {{ margin: 0; box-shadow: none; min-height: 0; page-break-inside: avoid; break-inside: avoid; }}
  }}
</style>
</head>
<body>
  <div class="sheet">
{sheet_inner}
  </div>
</body>
</html>"""


# ======================================================================
# النموذج الأول — فاخر داكن بلمسة ذهبية
# ======================================================================
def build_phase1_voucher_html(data: dict[str, Any]) -> str:
    """«النموذج الأول»: dark navy letterhead band with a gold hairline, the logo in
    a gold ring at the head, and a cream amount panel."""
    s = _seller_fields(data)
    number = html.escape(str(data.get("number") or ""))
    amount = _money(data.get("amount"))
    issue_date = _date(data.get("issue_date"))
    received_from = html.escape(str(data.get("received_from") or ""))
    purpose = html.escape(str(data.get("purpose") or ""))
    words = html.escape(amount_in_words_ar(data.get("amount")))
    signature = signature_line_html(font_size="16px", color="#333")

    logo = company_logo_data_uri(data.get("seller") or {})
    logo_slot = (
        f'<div style="width:74px;height:74px;border-radius:50%;border:2px solid {P1_GOLD};'
        f'background:#fff;display:flex;align-items:center;justify-content:center;overflow:hidden;flex:none;">'
        f'<img src="{logo}" alt="logo" style="max-height:60px;max-width:60px;width:auto;height:auto;object-fit:contain;display:block;"/></div>'
        if logo
        else
        f'<div style="width:74px;height:74px;border-radius:50%;border:2px solid {P1_GOLD};'
        f'color:{P1_GOLD_LT};display:flex;align-items:center;justify-content:center;flex:none;">'
        f'<div style="width:40px;height:40px;">{_LOGO_MARK_SVG}</div></div>'
    )

    inner = f"""
    <!-- ===== DARK HEADER BAND ===== -->
    <div style="background:{P1_NAVY};color:#fff;padding:28px 44px;border-bottom:3px solid {P1_GOLD};
      display:flex;justify-content:space-between;align-items:center;gap:26px;">
      <div style="display:flex;align-items:center;gap:16px;">
        {logo_slot}
        <div style="text-align:right;line-height:1.7;">
          <div style="font-size:25px;font-weight:800;color:{P1_GOLD_LT};">{s['name']}</div>
          <div style="font-size:13.5px;color:{P1_HEAD_SUB};">سجل تجاري: <span class="ltr">{s['cr']}</span></div>
          <div style="font-size:13.5px;color:{P1_HEAD_SUB};">الرقم الضريبي: <span class="ltr">{s['vat']}</span></div>
        </div>
      </div>
      <div style="text-align:center;flex:none;color:{P1_GOLD_LT};">
        <div style="font-size:26px;font-weight:800;white-space:nowrap;">سند قبض</div>
        <div style="font-size:11px;letter-spacing:3px;color:{P1_HEAD_SUB};">RECEIPT VOUCHER</div>
      </div>
    </div>

    <!-- ===== META ROW ===== -->
    <div style="display:flex;justify-content:space-between;padding:20px 44px 0;font-size:14px;color:{P1_MUTED};">
      <div>العنوان: {s['address']}</div>
      <div>رقم السند: <span class="ltr" style="color:{P1_INK};font-weight:700;">{number}</span>
        &nbsp;&nbsp;•&nbsp;&nbsp; التاريخ: <span class="ltr" style="color:{P1_INK};font-weight:700;">{issue_date}</span></div>
    </div>

    <!-- ===== AMOUNT PANEL ===== -->
    <div style="margin:22px 44px;border:1.5px solid {P1_GOLD};border-radius:12px;background:{P1_CREAM};
      padding:20px 24px;display:flex;justify-content:space-between;align-items:center;">
      <div style="font-size:16px;font-weight:700;color:{P1_CREAM_INK};">المبلغ المستلَم</div>
      <div style="font-size:38px;font-weight:800;color:{P1_CREAM_INK};line-height:1;">
        <span class="ltr">{amount}</span> <span style="font-size:20px;">ر.س</span></div>
    </div>

    <!-- ===== DETAIL ROWS ===== -->
    <div style="padding:0 44px;">
      <div style="display:flex;align-items:baseline;padding:14px 0;border-bottom:1px solid #eee;">
        <div style="width:150px;flex:none;color:{P1_GOLD};font-size:15px;font-weight:700;">استلمنا من السيد</div>
        <div style="flex:1;font-size:17px;font-weight:700;color:{P1_INK};">{received_from}</div>
      </div>
      <div style="display:flex;align-items:baseline;padding:14px 0;border-bottom:1px solid #eee;">
        <div style="width:150px;flex:none;color:{P1_GOLD};font-size:15px;font-weight:700;">مبلغاً وقدره</div>
        <div style="flex:1;font-size:16px;font-weight:700;color:{P1_INK};">{words}</div>
      </div>
      <div style="display:flex;align-items:baseline;padding:14px 0;border-bottom:1px solid #eee;">
        <div style="width:150px;flex:none;color:{P1_GOLD};font-size:15px;font-weight:700;">وذلك قيمة</div>
        <div style="flex:1;font-size:17px;font-weight:700;color:{P1_INK};">{purpose}</div>
      </div>
    </div>

    <!-- ===== SIGNATURE ===== -->
    <div style="padding:54px 70px 0;">{signature}</div>
"""
    return _doc(inner)


# ======================================================================
# النموذج الثاني — جدول مؤطر بالكامل
# ======================================================================
def build_phase1_voucher_html_v2(data: dict[str, Any]) -> str:
    """«النموذج الثاني»: every field is a bordered grid cell; the top-right cell
    carries the logo and the seller's full data."""
    s = _seller_fields(data)
    number = html.escape(str(data.get("number") or ""))
    amount = _money(data.get("amount"))
    issue_date = _date(data.get("issue_date"))
    received_from = html.escape(str(data.get("received_from") or ""))
    purpose = html.escape(str(data.get("purpose") or ""))
    words = html.escape(amount_in_words_ar(data.get("amount")))
    signature = signature_line_html(font_size="15px", color="#333")

    logo = company_logo_data_uri(data.get("seller") or {})
    logo_slot = (
        f'<div style="width:64px;height:64px;border:1px solid {P2_LINE};border-radius:8px;background:#fff;'
        f'display:flex;align-items:center;justify-content:center;overflow:hidden;flex:none;">'
        f'<img src="{logo}" alt="logo" style="max-height:54px;max-width:54px;width:auto;height:auto;object-fit:contain;display:block;"/></div>'
        if logo
        else
        f'<div style="width:64px;height:64px;border:1px solid {P2_LINE};border-radius:8px;background:{P2_SOFT};'
        f'color:{P2_TEAL};display:flex;flex-direction:column;align-items:center;justify-content:center;flex:none;gap:2px;">'
        f'<div style="width:30px;height:30px;">{_LOGO_MARK_SVG}</div>'
        f'<span style="font-size:8px;font-weight:700;">شعار الشركة</span></div>'
    )

    # A label/value grid row helper (label cell on the right under RTL).
    def cell_row(label: str, value: str, *, ltr: bool = False, big: bool = False) -> str:
        val_cls = ' class="ltr"' if ltr else ""
        val_style = (
            f"flex:1;padding:11px 14px;font-size:{'19px' if big else '16px'};font-weight:700;color:{P2_INK};"
        )
        return (
            f'<div style="display:flex;border-top:1px solid {P2_LINE};">'
            f'<div style="width:150px;flex:none;background:{P2_SOFT};padding:11px 14px;border-left:1px solid {P2_LINE};'
            f'font-size:14px;font-weight:700;color:{P2_TEAL};">{label}</div>'
            f'<div{val_cls} style="{val_style}">{value}</div>'
            f'</div>'
        )

    inner = f"""
    <div style="padding:36px 40px;">
      <div style="border:2px solid {P2_TEAL};border-radius:6px;overflow:hidden;">

        <!-- ===== HEADER CELL: logo + seller | title + serial + date ===== -->
        <div style="display:flex;">
          <div style="flex:1;padding:16px;display:flex;gap:14px;align-items:center;border-left:1px solid {P2_TEAL};">
            {logo_slot}
            <div style="line-height:1.6;">
              <div style="font-size:21px;font-weight:800;color:{P2_TEAL};">{s['name']}</div>
              <div style="font-size:13px;color:{P2_MUTED};">سجل تجاري: <span class="ltr">{s['cr']}</span></div>
              <div style="font-size:13px;color:{P2_MUTED};">الرقم الضريبي: <span class="ltr">{s['vat']}</span></div>
              <div style="font-size:13px;color:{P2_MUTED};">العنوان: {s['address']}</div>
            </div>
          </div>
          <div style="width:200px;flex:none;background:{P2_SOFT};padding:16px;text-align:center;">
            <div style="font-size:22px;font-weight:800;color:{P2_TEAL};">سند قبض</div>
            <div style="font-size:10px;letter-spacing:2px;color:{P2_MUTED};margin-bottom:10px;">RECEIPT VOUCHER</div>
            <div style="font-size:13px;color:{P2_MUTED};">رقم السند</div>
            <div style="font-size:18px;font-weight:800;color:{P2_INK};" class="ltr">{number}</div>
            <div style="font-size:13px;color:{P2_MUTED};margin-top:6px;">التاريخ</div>
            <div style="font-size:16px;font-weight:700;color:{P2_INK};" class="ltr">{issue_date}</div>
          </div>
        </div>

        {cell_row("استلمنا من السيد", received_from)}
        {cell_row("مبلغاً وقدره", f'<span class="ltr">{amount}</span> ر.س', big=True)}
        {cell_row("المبلغ كتابةً", words)}
        {cell_row("وذلك قيمة", purpose)}
      </div>

      <div style="padding:46px 30px 0;">{signature}</div>
    </div>
"""
    return _doc(inner)


# ======================================================================
# النموذج الثالث — بكعب قابل للفصل
# ======================================================================
def build_phase1_voucher_html_v3(data: dict[str, Any]) -> str:
    """«النموذج الثالث»: a full-width burgundy header band + a tear-off stub (كعب)
    across the foot that repeats the serial, date and amount to be detached.

    IMPORTANT — why it is built this way. The first two drafts placed the كعب as a
    tall burgundy column down the *side* (a full-height ``flex`` band). Both
    rendered fine to PDF but showed a **blank preview** on the user's machine:
    the on-screen QtWebEngine compositor chokes on a tall, full-height, solid
    coloured flex child (النموذج الأول/الثاني, which have no such band, preview
    fine). So this layout uses ONLY constructs already proven on that machine — a
    short full-width header band (as النموذج الأول of the invoices) and the
    horizontal foot stub (exactly النموذج السادس's «كعب»), all in normal flow via
    :func:`_doc`. No side band, no full-height coloured column.
    """
    s = _seller_fields(data)
    number = html.escape(str(data.get("number") or ""))
    amount = _money(data.get("amount"))
    issue_date = _date(data.get("issue_date"))
    received_from = html.escape(str(data.get("received_from") or ""))
    purpose = html.escape(str(data.get("purpose") or ""))
    words = html.escape(amount_in_words_ar(data.get("amount")))
    signature = signature_line_html(font_size="15px", color="#333")

    logo = company_logo_data_uri(data.get("seller") or {})
    logo_slot = (
        f'<div style="width:70px;height:70px;border-radius:12px;background:#fff;'
        f'display:flex;align-items:center;justify-content:center;overflow:hidden;flex:none;">'
        f'<img src="{logo}" alt="logo" style="max-height:58px;max-width:58px;width:auto;height:auto;object-fit:contain;display:block;"/></div>'
        if logo
        else
        f'<div style="width:70px;height:70px;border-radius:12px;border:2px solid rgba(255,255,255,.6);'
        f'color:#ffffff;display:flex;align-items:center;justify-content:center;flex:none;">'
        f'<div style="width:38px;height:38px;">{_LOGO_MARK_SVG}</div></div>'
    )

    inner = f"""
    <!-- ===== FULL-WIDTH HEADER BAND ===== -->
    <div style="background:{P3_WINE};color:#fff;padding:24px 40px;display:flex;
      justify-content:space-between;align-items:center;gap:24px;">
      <div style="display:flex;align-items:center;gap:15px;">
        {logo_slot}
        <div style="text-align:right;line-height:1.7;">
          <div style="font-size:23px;font-weight:800;">{s['name']}</div>
          <div style="font-size:13px;opacity:.9;">سجل تجاري: <span class="ltr">{s['cr']}</span>
            &nbsp;•&nbsp; الرقم الضريبي: <span class="ltr">{s['vat']}</span></div>
          <div style="font-size:13px;opacity:.9;">العنوان: {s['address']}</div>
        </div>
      </div>
      <div style="text-align:center;flex:none;">
        <div style="font-size:25px;font-weight:800;white-space:nowrap;">سند قبض</div>
        <div style="font-size:11px;letter-spacing:3px;opacity:.85;">RECEIPT VOUCHER</div>
      </div>
    </div>

    <!-- ===== META ROW ===== -->
    <div style="display:flex;justify-content:space-between;padding:18px 40px 0;font-size:14px;color:{P3_MUTED};">
      <div>رقم السند: <span class="ltr" style="color:{P3_INK};font-weight:800;">{number}</span></div>
      <div>التاريخ: <span class="ltr" style="color:{P3_INK};font-weight:800;">{issue_date}</span></div>
    </div>

    <!-- ===== AMOUNT PANEL ===== -->
    <div style="margin:18px 40px;border:1.5px solid {P3_WINE};border-radius:12px;background:{P3_SOFT};
      padding:18px 22px;display:flex;justify-content:space-between;align-items:center;">
      <div style="font-size:16px;font-weight:700;color:{P3_WINE};">المبلغ المستلَم</div>
      <div style="font-size:36px;font-weight:800;color:{P3_WINE};line-height:1;">
        <span class="ltr">{amount}</span> <span style="font-size:19px;">ر.س</span></div>
    </div>

    <!-- ===== DETAIL ROWS ===== -->
    <div style="padding:0 40px;">
      <div style="display:flex;align-items:baseline;padding:13px 0;border-bottom:1px solid {P3_LINE};">
        <div style="width:150px;flex:none;color:{P3_WINE};font-size:15px;font-weight:700;">استلمنا من السيد</div>
        <div style="flex:1;font-size:17px;font-weight:700;color:{P3_INK};">{received_from}</div>
      </div>
      <div style="display:flex;align-items:baseline;padding:13px 0;border-bottom:1px solid {P3_LINE};">
        <div style="width:150px;flex:none;color:{P3_WINE};font-size:15px;font-weight:700;">المبلغ كتابةً</div>
        <div style="flex:1;font-size:16px;font-weight:700;color:{P3_INK};">{words}</div>
      </div>
      <div style="display:flex;align-items:baseline;padding:13px 0;border-bottom:1px solid {P3_LINE};">
        <div style="width:150px;flex:none;color:{P3_WINE};font-size:15px;font-weight:700;">وذلك قيمة</div>
        <div style="flex:1;font-size:17px;font-weight:700;color:{P3_INK};">{purpose}</div>
      </div>
    </div>

    <!-- ===== SIGNATURE ===== -->
    <div style="padding:40px 60px 0;">{signature}</div>

    <!-- ===== TEAR-OFF STUB (كعب) — detach and file ===== -->
    <div style="margin:34px 40px 30px;border-top:2px dashed {P3_WINE};padding-top:16px;
      display:flex;align-items:center;justify-content:space-between;">
      <div style="font-size:13px;font-weight:700;color:{P3_WINE};">كعب السند — يُفصل ويُحفظ للمراجعة</div>
      <div style="display:flex;gap:30px;">
        <div style="text-align:center;"><div style="font-size:11px;color:{P3_MUTED};">رقم السند</div>
          <div style="font-size:15px;font-weight:800;" class="ltr">{number}</div></div>
        <div style="text-align:center;"><div style="font-size:11px;color:{P3_MUTED};">التاريخ</div>
          <div style="font-size:15px;font-weight:800;" class="ltr">{issue_date}</div></div>
        <div style="text-align:center;"><div style="font-size:11px;color:{P3_MUTED};">المبلغ</div>
          <div style="font-size:15px;font-weight:800;color:{P3_WINE};"><span class="ltr">{amount}</span> ر.س</div></div>
      </div>
    </div>
"""
    return _doc(inner)


# ======================================================================
# النموذج الرابع — كروت حديثة (modern info tiles)
# ======================================================================
def build_phase1_voucher_html_v4(data: dict[str, Any]) -> str:
    """«النموذج الرابع»: a modern dashboard-style voucher — a green header, a large
    centred amount hero, then the key facts as a 2×2 grid of info tiles.

    Normal flow only (no side band), so it previews on screen safely. See the
    module docstring on the tall-flex-band blank-preview trap.
    """
    s = _seller_fields(data)
    number = html.escape(str(data.get("number") or ""))
    amount = _money(data.get("amount"))
    issue_date = _date(data.get("issue_date"))
    received_from = html.escape(str(data.get("received_from") or ""))
    purpose = html.escape(str(data.get("purpose") or ""))
    payment_type = html.escape(str(data.get("payment_type") or "نقداً"))
    words = html.escape(amount_in_words_ar(data.get("amount")))
    signature = signature_line_html(font_size="15px", color="#333")

    logo = company_logo_data_uri(data.get("seller") or {})
    logo_slot = (
        f'<div style="width:64px;height:64px;border-radius:50%;background:#fff;'
        f'display:flex;align-items:center;justify-content:center;overflow:hidden;flex:none;">'
        f'<img src="{logo}" alt="logo" style="max-height:54px;max-width:54px;width:auto;height:auto;object-fit:contain;display:block;"/></div>'
        if logo
        else
        f'<div style="width:64px;height:64px;border-radius:50%;border:2px solid rgba(255,255,255,.65);'
        f'color:#ffffff;display:flex;align-items:center;justify-content:center;flex:none;">'
        f'<div style="width:34px;height:34px;">{_LOGO_MARK_SVG}</div></div>'
    )

    def tile(label: str, value: str, *, ltr: bool = False, accent: bool = False) -> str:
        vcls = ' class="ltr"' if ltr else ""
        vcolor = P4_GREEN_DK if accent else P4_INK
        return (
            f'<div style="border:1px solid {P4_LINE};border-radius:12px;padding:12px 14px;background:#ffffff;">'
            f'<div style="font-size:12.5px;color:{P4_MUTED};">{label}</div>'
            f'<div{vcls} style="font-size:17px;font-weight:800;color:{vcolor};margin-top:2px;">{value}</div>'
            f'</div>'
        )

    inner = f"""
    <!-- ===== GREEN HEADER ===== -->
    <div style="background:{P4_GREEN};color:#fff;padding:24px 40px;display:flex;
      justify-content:space-between;align-items:center;gap:24px;">
      <div style="display:flex;align-items:center;gap:14px;">
        {logo_slot}
        <div style="text-align:right;line-height:1.6;">
          <div style="font-size:22px;font-weight:800;">{s['name']}</div>
          <div style="font-size:12.5px;opacity:.92;">سجل تجاري: <span class="ltr">{s['cr']}</span>
            &nbsp;•&nbsp; الرقم الضريبي: <span class="ltr">{s['vat']}</span></div>
          <div style="font-size:12.5px;opacity:.92;">العنوان: {s['address']}</div>
        </div>
      </div>
      <div style="text-align:center;flex:none;">
        <div style="font-size:24px;font-weight:800;white-space:nowrap;">سند قبض</div>
        <div style="font-size:11px;letter-spacing:3px;opacity:.85;">RECEIPT VOUCHER</div>
      </div>
    </div>

    <!-- ===== AMOUNT HERO ===== -->
    <div style="margin:24px 40px;border-radius:16px;background:{P4_SOFT};padding:22px;text-align:center;">
      <div style="font-size:14px;color:{P4_GREEN};font-weight:700;">المبلغ المستلَم</div>
      <div style="font-size:44px;font-weight:800;color:{P4_GREEN_DK};line-height:1.15;">
        <span class="ltr">{amount}</span> <span style="font-size:22px;">ر.س</span></div>
      <div style="font-size:15px;color:#3f4a45;margin-top:6px;">{words}</div>
    </div>

    <!-- ===== INFO TILES (2×2) ===== -->
    <div style="padding:0 40px;display:grid;grid-template-columns:1fr 1fr;gap:14px;">
      {tile("رقم السند", number, ltr=True)}
      {tile("التاريخ", issue_date, ltr=True)}
      {tile("المستلَم منه", received_from)}
      {tile("طريقة الدفع", payment_type)}
    </div>

    <!-- ===== PURPOSE ===== -->
    <div style="margin:16px 40px 0;border:1px solid {P4_LINE};border-radius:12px;padding:12px 14px;background:#ffffff;">
      <div style="font-size:12.5px;color:{P4_MUTED};">وذلك قيمة</div>
      <div style="font-size:16px;font-weight:700;color:{P4_INK};margin-top:2px;">{purpose}</div>
    </div>

    <!-- ===== SIGNATURE ===== -->
    <div style="padding:46px 60px 0;">{signature}</div>
"""
    return _doc(inner)


# ======================================================================
# النموذج الخامس — بلوك لوني (geometric color-block)
# ======================================================================
def build_phase1_voucher_html_v5(data: dict[str, Any]) -> str:
    """«النموذج الخامس»: a bold, modern color-block voucher — two full-width colour
    blocks at the top with the logo in a white disc overlapping them, then the
    fields in clean flow below.

    Full-width horizontal blocks + normal flow (no full-height side band), so it
    previews on screen safely — see the module docstring on the blank-preview trap.
    """
    s = _seller_fields(data)
    number = html.escape(str(data.get("number") or ""))
    amount = _money(data.get("amount"))
    issue_date = _date(data.get("issue_date"))
    received_from = html.escape(str(data.get("received_from") or ""))
    purpose = html.escape(str(data.get("purpose") or ""))
    payment_type = html.escape(str(data.get("payment_type") or "نقداً"))
    words = html.escape(amount_in_words_ar(data.get("amount")))
    signature = signature_line_html(font_size="15px", color="#333")

    logo = company_logo_data_uri(data.get("seller") or {})
    logo_slot = (
        f'<div style="width:76px;height:76px;border-radius:50%;background:#fff;border:3px solid #fff;'
        f'box-shadow:0 2px 8px rgba(0,0,0,.18);display:flex;align-items:center;justify-content:center;overflow:hidden;flex:none;">'
        f'<img src="{logo}" alt="logo" style="max-height:60px;max-width:60px;width:auto;height:auto;object-fit:contain;display:block;"/></div>'
        if logo
        else
        f'<div style="width:76px;height:76px;border-radius:50%;background:#fff;border:3px solid #fff;'
        f'box-shadow:0 2px 8px rgba(0,0,0,.18);color:{P5_ORANGE};display:flex;align-items:center;justify-content:center;flex:none;">'
        f'<div style="width:42px;height:42px;">{_LOGO_MARK_SVG}</div></div>'
    )

    def row(label: str, value: str, *, ltr: bool = False, big: bool = False) -> str:
        vcls = ' class="ltr"' if ltr else ""
        size = "20px" if big else "17px"
        return (
            f'<div style="display:flex;align-items:baseline;padding:12px 0;border-bottom:1px solid {P5_LINE};">'
            f'<div style="width:150px;flex:none;color:{P5_ORANGE};font-size:15px;font-weight:700;">{label}</div>'
            f'<div{vcls} style="flex:1;font-size:{size};font-weight:800;color:{P5_INK};">{value}</div>'
            f'</div>'
        )

    inner = f"""
    <!-- ===== TWO COLOUR BLOCKS (logo disc sits inside the orange one) ===== -->
    <div style="display:flex;height:100px;">
      <div style="flex:1.5;background:{P5_ORANGE};display:flex;align-items:center;gap:15px;padding:0 40px;">
        {logo_slot}
        <div style="color:#fff;"><div style="font-size:26px;font-weight:800;">سند قبض</div>
          <div style="font-size:11px;letter-spacing:3px;opacity:.9;">RECEIPT VOUCHER</div></div>
      </div>
      <div style="flex:1;background:{P5_GREEN};display:flex;flex-direction:column;justify-content:center;padding:0 32px;color:#fff;">
        <div style="font-size:11px;opacity:.9;">رقم السند</div>
        <div style="font-size:19px;font-weight:800;" class="ltr">{number}</div>
        <div style="font-size:11px;opacity:.9;margin-top:3px;" class="ltr">{issue_date}</div>
      </div>
    </div>

    <!-- ===== COMPANY BAND (below the blocks — no overlap) ===== -->
    <div style="padding:16px 40px 0;line-height:1.6;">
      <div style="font-size:21px;font-weight:800;color:{P5_INK};">{s['name']}</div>
      <div style="font-size:12.5px;color:{P5_MUTED};">سجل تجاري: <span class="ltr">{s['cr']}</span>
        &nbsp;•&nbsp; الرقم الضريبي: <span class="ltr">{s['vat']}</span>
        &nbsp;•&nbsp; العنوان: {s['address']}</div>
    </div>

    <!-- ===== AMOUNT PANEL ===== -->
    <div style="margin:20px 40px;border-radius:14px;background:{P5_SOFT};padding:18px 22px;
      display:flex;justify-content:space-between;align-items:center;">
      <div style="font-size:16px;font-weight:700;color:{P5_ORANGE_DK};">المبلغ المستلَم</div>
      <div style="font-size:36px;font-weight:800;color:{P5_ORANGE_DK};line-height:1;">
        <span class="ltr">{amount}</span> <span style="font-size:19px;">ر.س</span></div>
    </div>

    <!-- ===== ROWS ===== -->
    <div style="padding:0 40px;">
      {row("استلمنا من السيد", received_from)}
      {row("المبلغ كتابةً", words)}
      {row("وذلك قيمة", purpose)}
      {row("طريقة الدفع", payment_type)}
    </div>

    <!-- ===== SIGNATURE ===== -->
    <div style="padding:44px 60px 0;">{signature}</div>
"""
    return _doc(inner)


# ======================================================================
# النموذج السادس — تركوازي «طبق الأصل» (مرجع: سند مؤسسة ثوابت الرواسي)
# ======================================================================
# A faithful reproduction of the customer's own scanned «سند قبض»: a centred bold
# black title, a first framed table for the company (اسم الشركة / عنوان الشركة /
# رقم السجل) with turquoise label cells, a second framed grid of voucher facts
# (رقم السند · التاريخ · اسم العميل · المبلغ المستلَم · طريقة الدفع · التفاصيل · اسم
# البنك · الوصف), the «المبلغ بالأحرف» line, and a «توقيع المُستلِم» signature. Normal
# flow only (no logo, no QR, no tall coloured side band) — exactly the original,
# and safe from the blank-preview trap. Colours from the scan: label fill #AEE0E8.
# The label cells use the very same azure as the invoice's header band (#2F98E8),
# with white label text on it — so the new «فاتورة» and «سند» read as one set.
P6_CYAN = "#2f98e8"        # label-cell fill (matches the invoice band)
P6_LABEL_INK = "#ffffff"   # label text on the azure cells
P6_LINE = "#cddff0"        # table borders
P6_INK = "#20303a"         # values
P6_TITLE = "#12333a"       # the «سند قبض» heading


def build_phase1_voucher_html_v6(data: dict[str, Any]) -> str:
    """«النموذج السادس»: faithful turquoise «سند قبض» — two framed tables (company +
    voucher facts) with cyan label cells, amount-in-words and a receiver signature."""
    s = _seller_fields(data)
    number = html.escape(str(data.get("number") or ""))
    amount = _money(data.get("amount"))
    issue_date = _date(data.get("issue_date"))
    received_from = html.escape(str(data.get("received_from") or ""))
    purpose = html.escape(str(data.get("purpose") or ""))
    payment_type = html.escape(str(data.get("payment_type") or "نقداً"))
    bank = html.escape(str(data.get("bank_name") or "")) or "لا يوجد"
    words = html.escape(amount_in_words_ar(data.get("amount")))

    lbl = (
        f"background:{P6_CYAN};border:1px solid {P6_LINE};padding:12px 14px;"
        f"font-weight:700;color:{P6_LABEL_INK};font-size:14px;white-space:nowrap;vertical-align:middle;"
    )
    val = (
        f"border:1px solid {P6_LINE};padding:12px 14px;color:{P6_INK};font-size:14px;"
        f"font-weight:700;vertical-align:middle;"
    )

    inner = f"""
    <div style="padding:40px 44px;">

      <!-- ===== TITLE ===== -->
      <div style="text-align:center;font-size:30px;font-weight:800;color:{P6_TITLE};margin-bottom:24px;">
        سند قبض</div>

      <!-- ===== COMPANY TABLE ===== -->
      <table style="width:100%;border-collapse:collapse;table-layout:fixed;margin-bottom:18px;">
        <tr>
          <td style="{lbl}width:26%;">اسم الشركة</td>
          <td style="{val}">{s['name']}</td>
        </tr>
        <tr>
          <td style="{lbl}">عنوان الشركة</td>
          <td style="{val}">{s['address']}</td>
        </tr>
        <tr>
          <td style="{lbl}">رقم السجل</td>
          <td style="{val}"><span class="ltr">{s['cr']}</span></td>
        </tr>
      </table>

      <!-- ===== VOUCHER FACTS GRID ===== -->
      <table style="width:100%;border-collapse:collapse;table-layout:fixed;">
        <tr>
          <td style="{lbl}width:20%;">رقم السند</td>
          <td style="{val}width:30%;"><span class="ltr">{number}</span></td>
          <td style="{lbl}width:20%;">التاريخ</td>
          <td style="{val}width:30%;"><span class="ltr">{issue_date}</span></td>
        </tr>
        <tr>
          <td style="{lbl}">اسم العميل</td>
          <td style="{val}">{received_from}</td>
          <td style="{lbl}">المبلغ المستلَم</td>
          <td style="{val}"><span class="ltr">{amount}</span> ر.س</td>
        </tr>
        <tr>
          <td style="{lbl}">طريقة الدفع</td>
          <td style="{val}">{payment_type}</td>
          <td style="{lbl}">التفاصيل</td>
          <td style="{val}">{payment_type}</td>
        </tr>
        <tr>
          <td style="{lbl}">اسم البنك</td>
          <td style="{val}">{bank}</td>
          <td style="{lbl}">الوصف</td>
          <td style="{val}">{purpose}</td>
        </tr>
      </table>

      <!-- ===== AMOUNT IN WORDS ===== -->
      <!-- amount_in_words_ar already returns the full «... فقط لا غير» phrase; do
           NOT append another «فقط لا غير» or it doubles (as an early render showed). -->
      <div style="margin-top:22px;font-size:15px;font-weight:700;color:{P6_INK};">
        المبلغ بالأحرف: {words}</div>

      <!-- ===== SIGNATURE ===== -->
      <div style="margin-top:60px;display:flex;justify-content:flex-start;">
        <div style="text-align:center;color:#333;font-size:15px;">
          <div style="border-top:1px solid #9aa5ab;width:220px;padding-top:8px;">توقيع المُستلِم</div>
        </div>
      </div>

    </div>
"""
    return _doc(inner)


# ======================================================================
# Template registry + picker plumbing
# ======================================================================
PHASE1_VOUCHER_TEMPLATE_OPTIONS: tuple[str, ...] = (
    "النموذج الأول",
    "النموذج الثاني",
    "النموذج الثالث",
    "النموذج الرابع",
    "النموذج الخامس",
    "النموذج السادس",
)

# 1-based template index -> its HTML builder (None = reserved / not built yet).
_PHASE1_VOUCHER_BUILDERS: dict[int, Callable[[dict[str, Any]], str]] = {
    1: build_phase1_voucher_html,
    2: build_phase1_voucher_html_v2,
    3: build_phase1_voucher_html_v3,
    4: build_phase1_voucher_html_v4,
    5: build_phase1_voucher_html_v5,
    6: build_phase1_voucher_html_v6,
}


def phase1_voucher_builder_for(
    choice: int | None,
) -> "Callable[[dict[str, Any]], str] | None":
    """Return the HTML builder for a 1-based template choice, or ``None`` if the
    choice is out of range. All five Phase-1 voucher layouts exist."""
    if choice is None:
        return None
    return _PHASE1_VOUCHER_BUILDERS.get(choice)


# ======================================================================
# The three «مرحلة أولى ← سندات» actions (preview / print / PDF)
# ======================================================================
def preview_phase1_voucher(
    parent: QWidget,
    data: dict[str, Any],
    html_builder: Callable[[dict[str, Any]], str] = build_phase1_voucher_html,
) -> None:
    """Open the shared voucher preview window rendering the chosen Phase-1 layout."""
    dialog = SaudiReceiptVoucherPreviewDialog(data, parent=parent, html_builder=html_builder)
    dialog.exec()


def export_phase1_voucher_pdf(
    parent: QWidget,
    data: dict[str, Any],
    html_builder: Callable[[dict[str, Any]], str] = build_phase1_voucher_html,
) -> None:
    """Ask for a path and export the chosen Phase-1 voucher straight to a PDF."""
    export_receipt_voucher_to_pdf(parent, data, html_builder=html_builder)


def print_phase1_voucher(
    parent: QWidget,
    data: dict[str, Any],
    html_builder: Callable[[dict[str, Any]], str] = build_phase1_voucher_html,
) -> None:
    """Render the chosen Phase-1 voucher off-screen and send it to a printer."""
    try:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except Exception:  # noqa: BLE001 - print support may be unavailable
        QMessageBox.warning(parent, "الطباعة", "خدمة الطباعة غير متاحة.")
        return

    view = QWebEngineView(parent)
    # Keep a reference on the parent so the view survives the async print.
    holder = getattr(parent, "_phase1_voucher_print_views", None)
    if holder is None:
        holder = []
        parent._phase1_voucher_print_views = holder  # type: ignore[attr-defined]
    holder.append(view)

    def _cleanup() -> None:
        try:
            holder.remove(view)
        except ValueError:
            pass
        view.deleteLater()

    def _on_load(ok: bool) -> None:
        if not ok:
            _cleanup()
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.A4))
        dialog = QPrintDialog(printer, parent)
        if dialog.exec() != QPrintDialog.Accepted:
            _cleanup()
            return

        def _done(success: bool) -> None:  # noqa: ARG001
            try:
                view.printFinished.disconnect(_done)
            except (RuntimeError, TypeError):
                pass
            _cleanup()

        view.printFinished.connect(_done)
        # Let fonts/layout settle before handing the page to the printer.
        QTimer.singleShot(150, lambda: view.print(printer))

    view.loadFinished.connect(_on_load)
    view.setHtml(html_builder(data), QUrl("about:blank"))


__all__ = [
    "build_phase1_voucher_html",
    "build_phase1_voucher_html_v2",
    "build_phase1_voucher_html_v3",
    "build_phase1_voucher_html_v4",
    "build_phase1_voucher_html_v5",
    "build_phase1_voucher_html_v6",
    "PHASE1_VOUCHER_TEMPLATE_OPTIONS",
    "phase1_voucher_builder_for",
    "preview_phase1_voucher",
    "export_phase1_voucher_pdf",
    "print_phase1_voucher",
]
