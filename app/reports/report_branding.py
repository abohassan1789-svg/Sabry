"""Shared print branding — the company logo for report headers.

Every Tawrid print module (the three account statements, the comprehensive
report and the treasury statement) renders its header as a flex row and now
carries the **Cisco Egypt** logo on the left. The logo is embedded as a base64
``data:`` URI rather than a ``file://`` path so the generated HTML is
self-contained: it prints, previews and exports to PDF identically no matter
where the temp ``.html`` file lives.

The asset (``assets/report_logo.jpg``) is a resized copy (~420 px wide, ~26 KB)
of the original artwork, small enough to inline once per report. If it is ever
missing the helpers degrade to an empty string, so a header simply prints
without the logo instead of failing.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

# app/reports/report_branding.py → parents[2] is the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGO_PATH = _PROJECT_ROOT / "assets" / "report_logo.jpg"


@lru_cache(maxsize=1)
def logo_data_uri() -> str:
    """The logo as a ``data:image/jpeg;base64,…`` URI, or ``""`` if unavailable.

    Cached: the bytes are read and encoded once per process.
    """
    try:
        raw = LOGO_PATH.read_bytes()
    except OSError:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def logo_img_html(height_px: int = 64) -> str:
    """An ``<img>`` tag for the header logo, or ``""`` when no logo is available.

    ``height_px`` sets the printed height; the width scales with it. The element
    is ``flex:none`` so a flex header never squeezes it.
    """
    uri = logo_data_uri()
    if not uri:
        return ""
    return (
        f'<img src="{uri}" alt="Cisco Egypt" '
        f'style="height:{height_px}px; width:auto; flex:none; object-fit:contain;" />'
    )


__all__ = ["LOGO_PATH", "logo_data_uri", "logo_img_html"]
