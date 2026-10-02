"""Import the legacy Access data into the Tawrid module tables.

Phase 1 covers الجرارات (``tbgrarat`` -> ``tawrid_tractors``), phase 2 العملاء
(``fanii`` -> ``tawrid_customers``) with its price grid (``CarCus``), and phase 3
الكسّارات/الموردين (``pruduct`` -> ``tawrid_suppliers``). Later phases add their
own ``import_*`` function here following the same shape:

* **Read-only** on the Access side (see :mod:`app.migrations.access_reader`).
* **Idempotent** — keyed on ``legacy_id``, so re-running updates the row in place
  instead of creating a duplicate. Safe to run again after fixing a value.
* **Reports, never guesses** — every value the importer had to adjust is listed
  in the returned :class:`ImportReport` so a human can check it.

Run it from the project root::

    python -m app.migrations.tawrid_import              # import
    python -m app.migrations.tawrid_import --dry-run    # report only, no writes

The target database is whichever one the app is configured for — the same
connection profile the application itself uses.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.database.db import Database
from app.migrations.access_reader import AccessReader

TRACTORS_QUERY = (
    "SELECT id, number1, NAME123, numbmaatora, numbwesh, sen, raml, BalancFirst, date123 "
    "FROM tbgrarat ORDER BY number1"
)


@dataclass
class ImportReport:
    table: str
    read: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    # (legacy id, driver name, what was adjusted) — shown to the operator.
    adjustments: list[tuple[Any, str, str]] = field(default_factory=list)
    errors: list[tuple[Any, str, str]] = field(default_factory=list)

    def note(self, legacy_id: Any, name: str, what: str) -> None:
        self.adjustments.append((legacy_id, name, what))

    def as_text(self) -> str:
        lines = [
            f"جدول: {self.table}",
            f"  مقروء من الأكسس : {self.read}",
            f"  مُضاف           : {self.inserted}",
            f"  مُحدَّث           : {self.updated}",
            f"  متخطّى          : {self.skipped}",
        ]
        if self.adjustments:
            lines.append(f"  تعديلات تلقائية ({len(self.adjustments)}):")
            for legacy_id, name, what in self.adjustments:
                lines.append(f"    • [{legacy_id}] {name}: {what}")
        if self.errors:
            lines.append(f"  أخطاء ({len(self.errors)}):")
            for legacy_id, name, what in self.errors:
                lines.append(f"    ✗ [{legacy_id}] {name}: {what}")
        return "\n".join(lines)


def _plate(value: Any) -> str | None:
    """Access stores plate numbers as integers; the new column is text."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _amount(value: Any) -> Decimal:
    return Decimal("0") if value is None else Decimal(str(value))


def _insert_only_sql(upsert_sql: str) -> str:
    """Turn a ``... ON CONFLICT ... DO UPDATE SET ... RETURNING`` upsert into an
    insert-only statement — the same ``ON CONFLICT`` target but ``DO NOTHING`` in
    place of the update, keeping the same ``RETURNING``.

    Used by ``--new-only`` runs (re-importing an updated Access file): they must
    **add** the rows the customer appended without ever rewriting a row already in
    the app. On a conflict ``DO NOTHING`` returns no row, so ``fetch_one`` yields
    ``None`` and :func:`_count_result` records it متخطّى instead of محدَّث.
    """
    before, sep, after = upsert_sql.partition(" DO UPDATE SET")
    if not sep:
        return upsert_sql
    returning = after[after.index("RETURNING"):]
    return f"{before} DO NOTHING\n{returning}"


def _count_result(report: ImportReport, result: Any, new_only: bool) -> None:
    """Tally one write. ``inserted`` is the fresh-insert flag from ``RETURNING``;
    under ``--new-only`` a ``None`` result means the row already existed and was
    left untouched (متخطّى), otherwise it was updated in place."""
    if result and result.get("inserted"):
        report.inserted += 1
    elif new_only:
        report.skipped += 1
    else:
        report.updated += 1


def map_tractor(row: dict[str, Any], report: ImportReport) -> dict[str, Any]:
    """Turn one ``tbgrarat`` row into ``tawrid_tractors`` column values."""
    legacy_id = row["id"]
    raw_name = row.get("NAME123") or ""
    name = raw_name.strip()
    if name != raw_name:
        report.note(legacy_id, name, "أُزيلت مسافات زائدة من الاسم")

    values = {
        "legacy_id": legacy_id,
        "tractor_code": row["number1"],
        "driver_name": name,
        "trailer_no": _plate(row.get("numbmaatora")),
        "head_no": _plate(row.get("numbwesh")),
        "price_sen": _amount(row.get("sen")),
        "price_raml": _amount(row.get("raml")),
        "opening_balance": _amount(row.get("BalancFirst")),
        "opening_date": row.get("date123"),
        "is_active": True,
    }
    if row.get("sen") is None:
        report.note(legacy_id, name, "سعر السن كان فارغاً -> 0")
    if row.get("raml") is None:
        report.note(legacy_id, name, "سعر الرمل كان فارغاً -> 0")
    if row.get("BalancFirst") is None:
        report.note(legacy_id, name, "رصيد أول المدة كان فارغاً -> 0")
    if values["opening_balance"] < 0:
        report.note(legacy_id, name,
                    f"رصيد أول المدة سالب ({values['opening_balance']}) — نُقل كما هو")
    return values


# Positional placeholders on purpose: ``Database.fetch_one`` coerces its params
# with ``list(...)``, which turns a dict into a list of its keys and breaks named
# placeholders. COLUMN_ORDER keeps the tuple and the statement in step.
COLUMN_ORDER = (
    "legacy_id", "tractor_code", "driver_name", "trailer_no", "head_no",
    "price_sen", "price_raml", "opening_balance", "opening_date", "is_active",
)

_UPSERT = """
INSERT INTO tawrid_tractors
    (legacy_id, tractor_code, driver_name, trailer_no, head_no,
     price_sen, price_raml, opening_balance, opening_date, is_active)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (legacy_id) WHERE legacy_id IS NOT NULL DO UPDATE SET
    tractor_code    = EXCLUDED.tractor_code,
    driver_name     = EXCLUDED.driver_name,
    trailer_no      = EXCLUDED.trailer_no,
    head_no         = EXCLUDED.head_no,
    price_sen       = EXCLUDED.price_sen,
    price_raml      = EXCLUDED.price_raml,
    opening_balance = EXCLUDED.opening_balance,
    opening_date    = EXCLUDED.opening_date
RETURNING (xmax = 0) AS inserted
"""


def import_tractors(
    access_path: str | None = None,
    db: Database | None = None,
    dry_run: bool = False,
    new_only: bool = False,
) -> ImportReport:
    """Import ``tbgrarat`` into ``tawrid_tractors``. Returns what happened."""
    report = ImportReport(table="tawrid_tractors")
    database = db or Database()
    sql = _insert_only_sql(_UPSERT) if new_only else _UPSERT

    # ``tractor_code`` is UNIQUE. On a re-import from an updated Access file a
    # brand-new tractor can carry a مسلسل that Access reused after a card was
    # deleted — a number now held in the app by a موقوف recovered ghost (its
    # code was assigned MAX+1 at the first migration). Give such a NEW card the
    # next free مسلسل instead of colliding; an existing card keeps its own code
    # (its legacy_id is already ours, so it is only ever updated/skipped in place).
    owned_code = {
        r["legacy_id"]: r["tractor_code"]
        for r in database.fetch_all(
            "SELECT legacy_id, tractor_code FROM tawrid_tractors WHERE legacy_id IS NOT NULL"
        )
    }
    used_codes = {
        r["tractor_code"]
        for r in database.fetch_all("SELECT tractor_code FROM tawrid_tractors")
    }
    next_free = max(used_codes) if used_codes else 0

    with AccessReader(access_path) as reader:
        rows = list(reader.rows(TRACTORS_QUERY))

    report.read = len(rows)
    for row in rows:
        values = map_tractor(row, report)
        if not values["driver_name"]:
            report.errors.append((row["id"], "", "اسم السائق فارغ — لم يُنقل"))
            report.skipped += 1
            continue
        if values["legacy_id"] not in owned_code and values["tractor_code"] in used_codes:
            next_free += 1
            report.note(values["legacy_id"], values["driver_name"],
                        f"المسلسل {values['tractor_code']} محجوز بالفعل بالبرنامج -> {next_free}")
            values["tractor_code"] = next_free
            used_codes.add(next_free)
        if dry_run:
            continue
        try:
            params = [values[name] for name in COLUMN_ORDER]
            _count_result(report, database.fetch_one(sql, params), new_only)
        except Exception as exc:
            report.errors.append((row["id"], values["driver_name"], str(exc).splitlines()[0]))
            report.skipped += 1
    return report


# ---------------------------------------------------------------------------
# استرجاع الجرارات المحذوفة من الأكسس
# ---------------------------------------------------------------------------
# ``tbgrarat`` lost four rows (Access ids 27, 34, 46, 47) but nothing that
# referenced them was cleaned up, because Access enforced no foreign keys. They
# are still named in the tickets: ``TBBOOn.namemand`` carries the driver's name
# and ``numberwesh`` his plate, on 264 tickets, plus 50 payment vouchers in
# ``SanadCAR``.
#
# So the cards are recoverable, and they have to be: without them the price-grid
# rows that point at them cannot be imported, and neither can those 264 tickets
# when البونات is built. They come across **موقوف** so they never appear in the
# tractor picker for new work — they exist to carry history, not to be used.
#
# Everything about a recovered card is stated, never guessed: the name and plate
# are the most frequent values on that tractor's own tickets, and the count is
# put in the report so a human can judge it.

RECOVERY_TICKETS_QUERY = (
    "SELECT maatora_id, numberwesh, namemand, date123 FROM TBBOOn"
)
RECOVERY_VOUCHERS_QUERY = "SELECT Gararid FROM SanadCAR"


def _is_a_real_name(text: str) -> bool:
    """A name has at least one letter. ``22222`` is a number someone typed."""
    return any(ch.isalpha() for ch in text)


def _most_common(values: list[Any]) -> tuple[Any, int]:
    """The most frequent meaningful value and how often it occurs.

    ``"0"`` is skipped along with blanks: Access stored an unset plate number as
    the integer zero, so carrying it across would put a plate of ``0`` on the
    card instead of leaving it empty.
    """
    counts: dict[Any, int] = {}
    for value in values:
        if value in (None, "", "0"):
            continue
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return None, 0
    best = max(counts.items(), key=lambda item: item[1])
    return best


def import_recovered_tractors(
    access_path: str | None = None,
    db: Database | None = None,
    dry_run: bool = False,
    new_only: bool = False,
) -> ImportReport:
    """Rebuild the tractor cards Access deleted, from the tickets that survived.

    Already insert-only regardless of ``new_only``: it skips any ``legacy_id`` that
    is present in ``tawrid_tractors`` (the ``already`` set), so a re-run only
    rebuilds cards newly orphaned by the appended tickets and never touches one it
    recovered before. ``new_only`` is accepted for a uniform call signature.
    """
    report = ImportReport(table="tawrid_tractors (مستردة)")
    database = db or Database()

    with AccessReader(access_path) as reader:
        live_ids = {row["id"] for row in reader.rows("SELECT id FROM tbgrarat")}
        tickets = list(reader.rows(RECOVERY_TICKETS_QUERY))
        vouchers = [row["Gararid"] for row in reader.rows(RECOVERY_VOUCHERS_QUERY)]

    orphaned: dict[Any, list[dict[str, Any]]] = {}
    for ticket in tickets:
        tractor_id = ticket.get("maatora_id")
        if tractor_id in (None, "", 0) or tractor_id in live_ids:
            continue
        orphaned.setdefault(tractor_id, []).append(ticket)

    report.read = len(orphaned)
    if not orphaned:
        return report

    next_code = int(
        database.fetch_one(
            "SELECT COALESCE(MAX(tractor_code), 0) + 1 AS c FROM tawrid_tractors"
        )["c"]
    )
    already = {
        row["legacy_id"]
        for row in database.fetch_all(
            "SELECT legacy_id FROM tawrid_tractors WHERE legacy_id IS NOT NULL"
        )
    }

    for legacy_id in sorted(orphaned):
        rows = orphaned[legacy_id]
        name, name_hits = _most_common([(r.get("namemand") or "").strip() for r in rows])
        head_no, head_hits = _most_common([_plate(r.get("numberwesh")) for r in rows])
        voucher_count = sum(1 for g in vouchers if g == legacy_id)

        if name and _is_a_real_name(name):
            driver_name = name
            report.note(legacy_id, driver_name,
                        f"اسم مسترد من {name_hits} بون من أصل {len(rows)}")
        else:
            # The tickets only ever carried a number here, so there is no name to
            # recover. Say so instead of storing the number as if it were one.
            driver_name = f"جرار محذوف {legacy_id}"
            report.note(legacy_id, driver_name,
                        f"مفيش اسم في البونات (المكتوب: {name!r}) — اسم بديل")
        if head_no:
            report.note(legacy_id, driver_name,
                        f"رقم الوش {head_no} مسترد من {head_hits} بون من أصل {len(rows)}")
        report.note(legacy_id, driver_name,
                    f"{len(rows)} بون و{voucher_count} سند صرف معلّقين عليه — نُقل موقوفاً")

        if legacy_id in already:
            report.skipped += 1
            continue
        if dry_run:
            continue

        values = {
            "legacy_id": legacy_id,
            "tractor_code": next_code,
            "driver_name": driver_name,
            "trailer_no": None,   # never recorded on a ticket
            "head_no": head_no,
            "price_sen": Decimal("0"),
            "price_raml": Decimal("0"),
            "opening_balance": Decimal("0"),
            "opening_date": None,
            # موقوف: these carry history, they are not available for new work.
            "is_active": False,
        }
        try:
            result = database.fetch_one(_UPSERT, [values[name] for name in COLUMN_ORDER])
            if result and result.get("inserted"):
                report.inserted += 1
                next_code += 1
            else:
                report.updated += 1
        except Exception as exc:
            report.errors.append((legacy_id, driver_name, str(exc).splitlines()[0]))
            report.skipped += 1
    return report


# ---------------------------------------------------------------------------
# Phase 2 — العملاء (``fanii``) وشبكة أسعار العميل × الجرار (``CarCus``)
# ---------------------------------------------------------------------------

# ``sen++`` needs the brackets in Jet SQL; the alias keeps the Python side sane.
CUSTOMERS_QUERY = (
    "SELECT id, number1, NAME123, sen1, sen2, sen3, sen6safi, sen6bodra, sen3adsa, "
    "bodra, raml, [sen++] AS sen_plus, SeenModarg, Des, BalancFirst, date123 "
    "FROM fanii ORDER BY number1"
)

PRICES_QUERY = (
    "SELECT id, inv_id, maatora_id, numberwesh, tak3ib, PriceSen, PriceRaml "
    "FROM CarCus ORDER BY inv_id, maatora_id"
)

# Access column -> new column. The Arabic label beside each is what FEMP showed,
# which is why ``sen3`` lands in ``price_sen_ataqa``: the users read «سن عتاقة».
ITEM_PRICE_MAP = (
    ("sen1", "price_sen1"),                # سن 1
    ("sen2", "price_sen2"),                # سن 2
    ("sen3", "price_sen_ataqa"),           # سن عتاقة
    ("sen6safi", "price_sen6_safi"),       # سن 6 صافي
    ("sen6bodra", "price_sen6_bodra"),     # سن 6 بالبودرة
    ("sen3adsa", "price_sen_adsa"),        # سن عدسة
    ("bodra", "price_bodra"),              # بودرة
    ("raml", "price_raml"),                # رملة
    ("sen_plus", "price_sen_plus"),        # سن+   (Access ``sen++``)
    ("SeenModarg", "price_sen_modarag"),   # سن مدرج
)


def map_customer(row: dict[str, Any], report: ImportReport) -> dict[str, Any]:
    """Turn one ``fanii`` row into ``tawrid_customers`` column values."""
    legacy_id = row["id"]
    raw_name = row.get("NAME123") or ""
    name = raw_name.strip()
    if raw_name and name != raw_name:
        report.note(legacy_id, name, "أُزيلت مسافات زائدة من الاسم")

    is_active = True
    if not name:
        # ``customer_name`` is NOT NULL and UNIQUE, so this row cannot be carried
        # across as-is. Dropping it would lose the legacy id that later phases
        # join on, so it is imported موقوف under a name that says what it is.
        # It is safe: this customer has no tickets and no receipts at all.
        name = f"بدون اسم — مسلسل {row.get('number1')}"
        is_active = False
        report.note(legacy_id, name, "لا يوجد اسم في الأكسس — نُقل موقوفاً باسم بديل")

    values: dict[str, Any] = {
        "legacy_id": legacy_id,
        "customer_code": row["number1"],
        "customer_name": name,
        "phone": None,          # ``fanii`` has no phone column at all
        "discount_percent": _amount(row.get("Des")),
        "opening_balance": _amount(row.get("BalancFirst")),
        "opening_date": row.get("date123"),
        "is_active": is_active,
    }
    for source, target in ITEM_PRICE_MAP:
        values[target] = _amount(row.get(source))

    if row.get("BalancFirst") is None:
        report.note(legacy_id, name, "رصيد أول المدة كان فارغاً -> 0")
    if values["opening_balance"] < 0:
        report.note(legacy_id, name,
                    f"رصيد أول المدة سالب ({values['opening_balance']}) — نُقل كما هو")
    return values


CUSTOMER_COLUMN_ORDER = (
    "legacy_id", "customer_code", "customer_name", "phone",
    "price_sen1", "price_sen2", "price_sen_ataqa", "price_sen6_safi",
    "price_sen6_bodra", "price_sen_adsa", "price_bodra", "price_raml",
    "price_sen_plus", "price_sen_modarag",
    "discount_percent", "opening_balance", "opening_date", "is_active",
)

_CUSTOMER_UPSERT = """
INSERT INTO tawrid_customers
    (legacy_id, customer_code, customer_name, phone,
     price_sen1, price_sen2, price_sen_ataqa, price_sen6_safi,
     price_sen6_bodra, price_sen_adsa, price_bodra, price_raml,
     price_sen_plus, price_sen_modarag,
     discount_percent, opening_balance, opening_date, is_active)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (legacy_id) WHERE legacy_id IS NOT NULL DO UPDATE SET
    customer_code     = EXCLUDED.customer_code,
    customer_name     = EXCLUDED.customer_name,
    price_sen1        = EXCLUDED.price_sen1,
    price_sen2        = EXCLUDED.price_sen2,
    price_sen_ataqa   = EXCLUDED.price_sen_ataqa,
    price_sen6_safi   = EXCLUDED.price_sen6_safi,
    price_sen6_bodra  = EXCLUDED.price_sen6_bodra,
    price_sen_adsa    = EXCLUDED.price_sen_adsa,
    price_bodra       = EXCLUDED.price_bodra,
    price_raml        = EXCLUDED.price_raml,
    price_sen_plus    = EXCLUDED.price_sen_plus,
    price_sen_modarag = EXCLUDED.price_sen_modarag,
    discount_percent  = EXCLUDED.discount_percent,
    opening_balance   = EXCLUDED.opening_balance,
    opening_date      = EXCLUDED.opening_date
RETURNING (xmax = 0) AS inserted
"""


def import_customers(
    access_path: str | None = None,
    db: Database | None = None,
    dry_run: bool = False,
    new_only: bool = False,
) -> ImportReport:
    """Import ``fanii`` into ``tawrid_customers``. Returns what happened."""
    report = ImportReport(table="tawrid_customers")
    database = db or Database()
    sql = _insert_only_sql(_CUSTOMER_UPSERT) if new_only else _CUSTOMER_UPSERT

    with AccessReader(access_path) as reader:
        rows = list(reader.rows(CUSTOMERS_QUERY))

    report.read = len(rows)
    for row in rows:
        values = map_customer(row, report)
        if dry_run:
            continue
        try:
            params = [values[name] for name in CUSTOMER_COLUMN_ORDER]
            _count_result(report, database.fetch_one(sql, params), new_only)
        except Exception as exc:
            report.errors.append((row["id"], values["customer_name"], str(exc).splitlines()[0]))
            report.skipped += 1
    return report


_PRICE_UPSERT = """
INSERT INTO tawrid_customer_tractor_prices
    (legacy_id, customer_id, tractor_id, load_volume, price_sen, price_raml)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (legacy_id) WHERE legacy_id IS NOT NULL DO UPDATE SET
    customer_id = EXCLUDED.customer_id,
    tractor_id  = EXCLUDED.tractor_id,
    load_volume = EXCLUDED.load_volume,
    price_sen   = EXCLUDED.price_sen,
    price_raml  = EXCLUDED.price_raml
RETURNING (xmax = 0) AS inserted
"""


def import_customer_tractor_prices(
    access_path: str | None = None,
    db: Database | None = None,
    dry_run: bool = False,
    new_only: bool = False,
) -> ImportReport:
    """Import ``CarCus`` into ``tawrid_customer_tractor_prices``.

    Both sides are resolved through ``legacy_id``, so this depends on the
    customers and the tractors already being imported — the grid must line up
    with the tractor cards the الجرارات screen shows, not with raw Access ids.

    Access had no foreign keys here, so some rows cannot be carried across:
    12 of the 236 point at tractors (Access ids 27, 34, 46, 47) that were
    deleted. They are reported, not silently dropped and not forced in.

    ``CarCus.numberwesh`` is deliberately not stored — it is a copy of the
    tractor's own رقم الوش. Every row is still compared against the tractor card
    and any disagreement is reported, because a stale copy means the Access row
    was pointing at a tractor whose plate later changed.
    """
    report = ImportReport(table="tawrid_customer_tractor_prices")
    database = db or Database()
    sql = _insert_only_sql(_PRICE_UPSERT) if new_only else _PRICE_UPSERT

    customers = {
        row["legacy_id"]: (row["customer_id"], row["customer_name"])
        for row in database.fetch_all(
            "SELECT legacy_id, customer_id, customer_name FROM tawrid_customers "
            "WHERE legacy_id IS NOT NULL"
        )
    }
    tractors = {
        row["legacy_id"]: (row["tractor_id"], row["driver_name"], row["head_no"])
        for row in database.fetch_all(
            "SELECT legacy_id, tractor_id, driver_name, head_no FROM tawrid_tractors "
            "WHERE legacy_id IS NOT NULL"
        )
    }

    with AccessReader(access_path) as reader:
        rows = list(reader.rows(PRICES_QUERY))

    report.read = len(rows)
    for row in rows:
        legacy_id = row["id"]
        customer = customers.get(row["inv_id"])
        tractor = tractors.get(row["maatora_id"])
        label = customer[1] if customer else f"عميل {row['inv_id']}"

        if customer is None:
            report.errors.append(
                (legacy_id, label,
                 f"العميل (id={row['inv_id']}) غير موجود بعد الترحيل — لم يُنقل الصف")
            )
            report.skipped += 1
            continue
        if tractor is None:
            report.errors.append(
                (legacy_id, label,
                 f"الجرار (id={row['maatora_id']}) محذوف من الأكسس — لم يُنقل الصف")
            )
            report.skipped += 1
            continue

        _tractor_id, driver_name, head_no = tractor
        grid_wesh = _plate(row.get("numberwesh"))
        if grid_wesh and head_no and grid_wesh != str(head_no):
            report.note(
                legacy_id,
                f"{label} / {driver_name}",
                f"رقم الوش في CarCus ({grid_wesh}) يخالف كارت الجرار ({head_no}) "
                "— اعتُمد كارت الجرار",
            )

        if dry_run:
            continue
        try:
            _count_result(report, database.fetch_one(sql, [
                legacy_id,
                customer[0],
                tractor[0],
                _amount(row.get("tak3ib")),
                _amount(row.get("PriceSen")),
                _amount(row.get("PriceRaml")),
            ]), new_only)
        except Exception as exc:
            report.errors.append((legacy_id, label, str(exc).splitlines()[0]))
            report.skipped += 1
    return report


# ---------------------------------------------------------------------------
# Phase 3 — الكسّارات / الموردين (``pruduct``)
# ---------------------------------------------------------------------------

SUPPLIERS_QUERY = (
    "SELECT id, number1, productName, notees, BalancFirst, date123, "
    "sen1, sen2, sen3, sen6safi, sen6bodra, sen3adsa, bodra, raml, "
    "[Sen++] AS sen_plus, SeenModarg "
    "FROM pruduct ORDER BY id"
)

# How many tickets / payment vouchers each crusher has. Used only to decide
# which cards come across موقوف — a card with no movement of any kind is one of
# the 7 that filled the Access combo without ever being bought from.
SUPPLIER_TICKETS_QUERY = "SELECT [res-id] AS sid, COUNT(*) AS n FROM TBBOOn GROUP BY [res-id]"
SUPPLIER_VOUCHERS_QUERY = "SELECT supid AS sid, COUNT(*) AS n FROM sanadsup GROUP BY supid"


def _supplier_code_overrides(rows: list[dict[str, Any]]) -> dict[Any, int]:
    """Fresh مسلسل values for the rows whose ``number1`` is already taken.

    ``Fproduct`` computed its default مسلسل as ``DMax("[number1]","fanii")+1`` —
    off the CUSTOMERS table — so ``pruduct`` ended up with 26, 31 and 46 each
    used twice. ``supplier_code`` is UNIQUE in the new table, so one of each pair
    has to move.

    The **first** row to use a number keeps it (lowest Access id wins, and the
    query is ordered by id), and every later claimant is pushed past the highest
    number in use. Computed from the Access rows alone, never from the target
    table, so re-running the import assigns exactly the same numbers instead of
    walking them forward on every pass.
    """
    seen: set[int] = set()
    overrides: dict[Any, int] = {}
    next_free = max((int(r["number1"]) for r in rows if r.get("number1")), default=0)
    for row in rows:
        code = row.get("number1")
        code = int(code) if code else 0
        if code and code not in seen:
            seen.add(code)
            continue
        next_free += 1
        overrides[row["id"]] = next_free
        seen.add(next_free)
    return overrides


def map_supplier(
    row: dict[str, Any],
    report: ImportReport,
    code_override: int | None = None,
    no_movement: bool = False,
) -> dict[str, Any]:
    """Turn one ``pruduct`` row into ``tawrid_suppliers`` column values."""
    legacy_id = row["id"]
    raw_name = row.get("productName") or ""
    name = raw_name.strip()
    if raw_name and name != raw_name:
        report.note(legacy_id, name, "أُزيلت مسافات زائدة من الاسم")

    is_active = True
    if not name:
        # ``supplier_name`` is NOT NULL and UNIQUE, so this row cannot be carried
        # across as-is. Dropping it would lose the legacy id that later phases
        # join on, so it is imported موقوف under a name that says what it is.
        name = f"بدون اسم — مسلسل {row.get('number1')}"
        is_active = False
        report.note(legacy_id, name, "لا يوجد اسم في الأكسس — نُقل موقوفاً باسم بديل")
    elif no_movement:
        # No ticket, no voucher and no opening balance. Kept — deleting is what
        # orphaned crusher 22's tickets — but stopped, so it stops competing in
        # the search list with the crushers actually in use.
        is_active = False
        report.note(legacy_id, name, "لا حركة ولا رصيد على الكارت — نُقل موقوفاً")

    code = row.get("number1")
    if code_override is not None:
        report.note(legacy_id, name,
                    f"المسلسل {code} كان مكرراً في الأكسس -> {code_override}")
        code = code_override

    values: dict[str, Any] = {
        "legacy_id": legacy_id,
        "supplier_code": code,
        "supplier_name": name,
        "phone": None,          # ``pruduct`` has no contact column at all
        "opening_balance": _amount(row.get("BalancFirst")),
        "opening_date": row.get("date123"),
        # ``notees`` is empty in all 23 rows, but it is read rather than assumed:
        # the column exists, and the only reason it is empty is that Fproduct
        # never put a control on it.
        "notes": (row.get("notees") or "").strip() or None,
        "is_active": is_active,
    }
    for source, target in ITEM_PRICE_MAP:
        values[target] = _amount(row.get(source))

    if row.get("BalancFirst") is None:
        report.note(legacy_id, name, "رصيد أول المدة كان فارغاً -> 0")
    if values["opening_balance"] < 0:
        report.note(legacy_id, name,
                    f"رصيد أول المدة سالب ({values['opening_balance']}) — نُقل كما هو")
    return values


SUPPLIER_COLUMN_ORDER = (
    "legacy_id", "supplier_code", "supplier_name", "phone",
    "price_sen1", "price_sen2", "price_sen_ataqa", "price_sen6_safi",
    "price_sen6_bodra", "price_sen_adsa", "price_bodra", "price_raml",
    "price_sen_plus", "price_sen_modarag",
    "opening_balance", "opening_date", "notes", "is_active",
)

_SUPPLIER_UPSERT = """
INSERT INTO tawrid_suppliers
    (legacy_id, supplier_code, supplier_name, phone,
     price_sen1, price_sen2, price_sen_ataqa, price_sen6_safi,
     price_sen6_bodra, price_sen_adsa, price_bodra, price_raml,
     price_sen_plus, price_sen_modarag,
     opening_balance, opening_date, notes, is_active)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (legacy_id) WHERE legacy_id IS NOT NULL DO UPDATE SET
    supplier_code     = EXCLUDED.supplier_code,
    supplier_name     = EXCLUDED.supplier_name,
    price_sen1        = EXCLUDED.price_sen1,
    price_sen2        = EXCLUDED.price_sen2,
    price_sen_ataqa   = EXCLUDED.price_sen_ataqa,
    price_sen6_safi   = EXCLUDED.price_sen6_safi,
    price_sen6_bodra  = EXCLUDED.price_sen6_bodra,
    price_sen_adsa    = EXCLUDED.price_sen_adsa,
    price_bodra       = EXCLUDED.price_bodra,
    price_raml        = EXCLUDED.price_raml,
    price_sen_plus    = EXCLUDED.price_sen_plus,
    price_sen_modarag = EXCLUDED.price_sen_modarag,
    opening_balance   = EXCLUDED.opening_balance,
    opening_date      = EXCLUDED.opening_date,
    notes             = EXCLUDED.notes
RETURNING (xmax = 0) AS inserted
"""


def import_suppliers(
    access_path: str | None = None,
    db: Database | None = None,
    dry_run: bool = False,
    new_only: bool = False,
) -> ImportReport:
    """Import ``pruduct`` into ``tawrid_suppliers``. Returns what happened.

    Note what is deliberately **not** done here: crusher id 22 was deleted in
    Access while 4 tickets still point at it, and ``TBBOOn`` stores no crusher
    name — only ``res-id`` — so unlike the tractors there is nothing to rebuild
    the card from. It is left out; the البون phase has to decide whether those 4
    tickets get a placeholder card or stay behind.

    ``is_active`` is the one field an update deliberately does **not** touch:
    once someone has stopped or restarted a crusher on the screen, re-running the
    import must not undo it.
    """
    report = ImportReport(table="tawrid_suppliers")
    database = db or Database()
    sql = _insert_only_sql(_SUPPLIER_UPSERT) if new_only else _SUPPLIER_UPSERT

    with AccessReader(access_path) as reader:
        rows = list(reader.rows(SUPPLIERS_QUERY))
        movement: dict[Any, int] = {}
        for query in (SUPPLIER_TICKETS_QUERY, SUPPLIER_VOUCHERS_QUERY):
            for row in reader.rows(query):
                movement[row["sid"]] = movement.get(row["sid"], 0) + int(row["n"] or 0)

    report.read = len(rows)
    overrides = _supplier_code_overrides(rows)
    for row in rows:
        idle = not movement.get(row["id"]) and not _amount(row.get("BalancFirst"))
        values = map_supplier(row, report, overrides.get(row["id"]), no_movement=idle)
        if dry_run:
            continue
        try:
            params = [values[name] for name in SUPPLIER_COLUMN_ORDER]
            _count_result(report, database.fetch_one(sql, params), new_only)
        except Exception as exc:
            report.errors.append((row["id"], values["supplier_name"], str(exc).splitlines()[0]))
            report.skipped += 1
    return report


# ---------------------------------------------------------------------------
# Phase 5 — تكعيب الكسّارات (``sallesHead`` / ``Sallesdata``)
# ---------------------------------------------------------------------------
# A master→detail cubing document. Despite the *sales-invoice* names, the two
# tables carry NO price at all — only the تكعيب (volume) each tractor hauled from
# each crusher (audited 2026-09-04). Deviations from Access, each measured:
#
#   * ``sallesHead.productNam`` → the crusher (``pruduct.id`` → tawrid_suppliers).
#     3 headers have no crusher and 1 points at deleted crusher 22; all four land
#     on a موقوف «كسّارة محذوفة» placeholder so ``crusher_id`` (NOT NULL) resolves
#     and no sheet is dropped.
#   * ``Sallesdata.maatora_id`` → the tractor (``tbgrarat.id`` → tawrid_tractors).
#     45 of 125 lines point at deleted tractors; the 7 recovered in phase 1
#     resolve, and the 9 truly-gone ones import with ``tractor_id`` NULL and the
#     name/plate kept in the snapshot columns (``namemand`` / ``numberwesh``), so
#     the line still reads and is flagged محذوف on screen.
#   * The dead ``inv_id`` (text) and ``t1`` (bool) columns are not carried.

# A stable sentinel ``legacy_id`` for the one shared «كسّارة محذوفة» placeholder,
# well clear of the positive ``pruduct.id`` values phase 3 uses.
_DELETED_CRUSHER_LEGACY_ID = -1

CUBING_HEADERS_QUERY = (
    "SELECT id, number1, inv_date, productNam FROM sallesHead ORDER BY number1"
)
CUBING_LINES_QUERY = (
    "SELECT id, inv_id, maatora_id, numberwesh, namemand, tak3ib "
    "FROM Sallesdata ORDER BY inv_id, id"
)


def _as_date(value: Any) -> Any:
    """Access returns ``inv_date`` as a datetime; the column is a plain date."""
    to_date = getattr(value, "date", None)
    return to_date() if callable(to_date) else value


def _ensure_placeholder_crusher(
    database: Database, report: ImportReport, dry_run: bool
) -> Any:
    """Return the id of the shared موقوف «كسّارة محذوفة» card, creating it once.

    Access left 3 cubing sheets with no crusher and 1 on deleted crusher 22, and
    ``crusher_id`` is NOT NULL. Rather than drop those sheets, they point at one
    placeholder crusher — the same call البون will make for its own orphans. It
    comes across موقوف so it never appears in the active crusher pickers.
    """
    existing = database.fetch_one(
        "SELECT supplier_id FROM tawrid_suppliers WHERE legacy_id = %s",
        [_DELETED_CRUSHER_LEGACY_ID],
    )
    if existing:
        return existing["supplier_id"]
    if dry_run:
        report.note(_DELETED_CRUSHER_LEGACY_ID, "كسّارة محذوفة",
                    "سيتم إنشاء كارت «كسّارة محذوفة» موقوف للكشوف بلا كسّارة")
        return None
    next_code = int(
        database.fetch_one(
            "SELECT COALESCE(MAX(supplier_code), 0) + 1 AS c FROM tawrid_suppliers"
        )["c"]
    )
    row = database.fetch_one(
        """
        INSERT INTO tawrid_suppliers
            (legacy_id, supplier_code, supplier_name, opening_balance, is_active)
        VALUES (%s, %s, %s, 0, FALSE)
        RETURNING supplier_id
        """,
        [_DELETED_CRUSHER_LEGACY_ID, next_code, "كسّارة محذوفة"],
    )
    report.note(_DELETED_CRUSHER_LEGACY_ID, "كسّارة محذوفة",
                f"أُنشئ كارت «كسّارة محذوفة» موقوف (مسلسل {next_code}) للكشوف بلا كسّارة")
    return row["supplier_id"] if row else None


_CUBING_HEADER_UPSERT = """
INSERT INTO tawrid_crusher_cubing (legacy_id, sheet_no, sheet_date, crusher_id, notes)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (legacy_id) WHERE legacy_id IS NOT NULL DO UPDATE SET
    sheet_no   = EXCLUDED.sheet_no,
    sheet_date = EXCLUDED.sheet_date,
    crusher_id = EXCLUDED.crusher_id,
    notes      = EXCLUDED.notes
RETURNING (xmax = 0) AS inserted
"""


def import_cubing_headers(
    access_path: str | None = None,
    db: Database | None = None,
    dry_run: bool = False,
    new_only: bool = False,
) -> ImportReport:
    """Import ``sallesHead`` into ``tawrid_crusher_cubing``.

    Depends on the crushers already being imported (phase 3): the header's
    crusher is resolved through ``tawrid_suppliers.legacy_id`` = ``pruduct.id``.
    """
    report = ImportReport(table="tawrid_crusher_cubing")
    database = db or Database()
    sql = _insert_only_sql(_CUBING_HEADER_UPSERT) if new_only else _CUBING_HEADER_UPSERT

    crushers = {
        row["legacy_id"]: row["supplier_id"]
        for row in database.fetch_all(
            "SELECT legacy_id, supplier_id FROM tawrid_suppliers WHERE legacy_id IS NOT NULL"
        )
    }

    with AccessReader(access_path) as reader:
        rows = list(reader.rows(CUBING_HEADERS_QUERY))

    report.read = len(rows)
    placeholder_id: Any = None
    for row in rows:
        legacy_id = row["id"]
        sheet_no = row.get("number1")
        label = f"كشف {sheet_no}"
        crusher_legacy = row.get("productNam")
        crusher_id = crushers.get(crusher_legacy)
        if crusher_id is None:
            # No crusher, or deleted crusher 22 → the shared placeholder card.
            if placeholder_id is None:
                placeholder_id = _ensure_placeholder_crusher(database, report, dry_run)
            crusher_id = placeholder_id
            why = "بدون كسّارة" if crusher_legacy in (None, "") else f"كسّارة محذوفة (id={crusher_legacy})"
            report.note(legacy_id, label, f"{why} — رُبط بكارت «كسّارة محذوفة»")

        if dry_run:
            continue
        try:
            _count_result(report, database.fetch_one(sql, [
                legacy_id, sheet_no, _as_date(row.get("inv_date")), crusher_id, None,
            ]), new_only)
        except Exception as exc:
            report.errors.append((legacy_id, label, str(exc).splitlines()[0]))
            report.skipped += 1
    return report


_CUBING_LINE_UPSERT = """
INSERT INTO tawrid_crusher_cubing_lines
    (legacy_id, cubing_id, line_seq, tractor_id,
     driver_name_snapshot, trailer_no_snapshot, volume)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (legacy_id) WHERE legacy_id IS NOT NULL DO UPDATE SET
    cubing_id            = EXCLUDED.cubing_id,
    line_seq             = EXCLUDED.line_seq,
    tractor_id           = EXCLUDED.tractor_id,
    driver_name_snapshot = EXCLUDED.driver_name_snapshot,
    trailer_no_snapshot  = EXCLUDED.trailer_no_snapshot,
    volume               = EXCLUDED.volume
RETURNING (xmax = 0) AS inserted
"""


def import_cubing_lines(
    access_path: str | None = None,
    db: Database | None = None,
    dry_run: bool = False,
    new_only: bool = False,
) -> ImportReport:
    """Import ``Sallesdata`` into ``tawrid_crusher_cubing_lines``.

    Both sides resolve through ``legacy_id``: the header via
    ``tawrid_crusher_cubing.legacy_id`` = ``sallesHead.id`` (so the headers must
    be imported first), and the tractor via ``tawrid_tractors.legacy_id`` =
    ``tbgrarat.id``. A line whose tractor cannot be resolved (deleted, never
    recovered) is kept with ``tractor_id`` NULL and its name/plate in the snapshot
    columns — no line is dropped, and the البون-style history stays readable.
    """
    report = ImportReport(table="tawrid_crusher_cubing_lines")
    database = db or Database()
    sql = _insert_only_sql(_CUBING_LINE_UPSERT) if new_only else _CUBING_LINE_UPSERT

    headers = {
        row["legacy_id"]: row["cubing_id"]
        for row in database.fetch_all(
            "SELECT legacy_id, cubing_id FROM tawrid_crusher_cubing WHERE legacy_id IS NOT NULL"
        )
    }
    tractors = {
        row["legacy_id"]: (row["tractor_id"], row["driver_name"])
        for row in database.fetch_all(
            "SELECT legacy_id, tractor_id, driver_name FROM tawrid_tractors "
            "WHERE legacy_id IS NOT NULL"
        )
    }

    with AccessReader(access_path) as reader:
        rows = list(reader.rows(CUBING_LINES_QUERY))

    report.read = len(rows)
    seq_by_header: dict[Any, int] = {}
    for row in rows:
        legacy_id = row["id"]
        header_legacy = row.get("inv_id")
        cubing_id = headers.get(header_legacy)
        if cubing_id is None:
            report.errors.append(
                (legacy_id, f"سطر {legacy_id}",
                 f"الكشف (sallesHead.id={header_legacy}) غير موجود بعد الترحيل — لم يُنقل السطر")
            )
            report.skipped += 1
            continue

        seq_by_header[header_legacy] = seq_by_header.get(header_legacy, 0) + 1
        line_seq = seq_by_header[header_legacy]

        maatora_id = row.get("maatora_id")
        tractor = tractors.get(maatora_id)
        driver_snapshot = ""
        trailer_snapshot = ""
        if tractor is not None:
            tractor_id = tractor[0]
        else:
            # Deleted tractor never recovered: keep it as a snapshot so the line
            # still reads and is flagged محذوف on screen, instead of dropping it.
            tractor_id = None
            driver_snapshot = (row.get("namemand") or "").strip()
            trailer_snapshot = _plate(row.get("numberwesh")) or ""
            report.note(legacy_id, driver_snapshot or f"سطر {legacy_id}",
                        f"الجرار (id={maatora_id}) محذوف — نُقل بالاسم بدون ربط بكارت")

        if dry_run:
            continue
        try:
            _count_result(report, database.fetch_one(sql, [
                legacy_id, cubing_id, line_seq, tractor_id,
                driver_snapshot, trailer_snapshot, _amount(row.get("tak3ib")),
            ]), new_only)
        except Exception as exc:
            report.errors.append((legacy_id, f"سطر {legacy_id}", str(exc).splitlines()[0]))
            report.skipped += 1
    return report


# ---------------------------------------------------------------------------
# Phase 4 (data) — البون (``TBBOOn`` → ``tawrid_tickets``)
# ---------------------------------------------------------------------------
# The heart of the module: 4,072 tickets, each carrying three price layers. The
# screen and table were built earlier; this is the deferred data migration.
# Deviations from Access, each tied to a measured fact (see tawrid-boun-findings):
#
#   * **Every party is a real FK.** Access enforced none: ~912 tickets have no
#     customer (899 deleted + 13 NULL) and 4 point at deleted crusher 22. The
#     unrecoverable customer/crusher land on موقوف «محذوف» placeholder cards so no
#     ticket is dropped and the NOT NULL FKs resolve. ``maatora_id`` resolves for
#     all but 1 (the phase-1 recovered cards cover the rest); the odd one gets a
#     NULL tractor (the column is nullable).
#   * **``discount_percent`` is a real percent.** ``TBBOOn.disc`` is a fraction
#     (0.01 = 1%), so the ticket stores ``disc × 100``. The customers' own default
#     (``tawrid_customers.discount_percent``, still the 0.01 fraction) is rescaled
#     here too — ``>0 AND <1 → ×100`` — idempotent (1.0 is not < 1).
#   * **The five money totals are GENERATED**, so they are not written — only the
#     base columns are inserted and the database computes the rest.
#   * **``item_id`` links to the catalogue** (``tawrid_items``), replacing the 10
#     hardcoded IF branches; the free-text ``productName`` is still kept in
#     ``item_name`` for the printed bon. A few legacy spellings are aliased
#     (سن+→سن +, سن 3→سن عتاقة, س1→سن 1, س 2→سن 2); the rest match by ignoring
#     spaces. An unmappable name leaves ``item_id`` NULL.
#   * **``ticket_no`` is UNIQUE and > 0.** One legacy ticket has ``number1`` = 0;
#     it is renumbered to ``MAX(number1)+1`` (stable, from the Access rows alone).

TICKETS_QUERY = (
    "SELECT id, number1, NumberEissal, date123, cus_id, [res-id] AS res_id, "
    "maatora_id, productName, typeharka, PriceCus, Tak3ib, Priceres, Tak3ibres, "
    "Pricemand, disc FROM TBBOOn ORDER BY number1"
)

# A sentinel legacy_id for the موقوف «عميل محذوف» placeholder, well clear of the
# positive ``fanii.id`` values phase 2 uses. (The crusher placeholder — sentinel
# −1 in ``tawrid_suppliers`` — is the one phase 5 already created and is reused.)
_DELETED_CUSTOMER_LEGACY_ID = -1


def _item_norm(name: Any) -> str:
    """Compare item names ignoring all whitespace, so «سن+» == «سن +»."""
    return "".join(str(name or "").split())


# Legacy spellings that do not match a catalogue name even after ignoring spaces,
# mapped to the canonical name (normalised). Keyed on the normalised legacy text.
_ITEM_ALIASES = {
    _item_norm("سن 3"): _item_norm("سن عتاقة"),   # same item, two names (13 rows)
    _item_norm("س1"): _item_norm("سن 1"),          # typo (1 row)
    _item_norm("س 2"): _item_norm("سن 2"),         # typo (1 row)
}


def _ensure_placeholder_customer(
    database: Database, report: ImportReport, dry_run: bool
) -> Any:
    """Return the id of the موقوف «عميل محذوف» card, creating it once.

    ~912 tickets point at a customer Access deleted (or none at all), and
    ``customer_id`` is NOT NULL. Rather than drop them they share one placeholder,
    موقوف so it never appears in the active customer pickers.
    """
    existing = database.fetch_one(
        "SELECT customer_id FROM tawrid_customers WHERE legacy_id = %s",
        [_DELETED_CUSTOMER_LEGACY_ID],
    )
    if existing:
        return existing["customer_id"]
    if dry_run:
        report.note(_DELETED_CUSTOMER_LEGACY_ID, "عميل محذوف",
                    "سيتم إنشاء كارت «عميل محذوف» موقوف للبونات بلا عميل")
        return None
    next_code = int(
        database.fetch_one(
            "SELECT COALESCE(MAX(customer_code), 0) + 1 AS c FROM tawrid_customers"
        )["c"]
    )
    row = database.fetch_one(
        "INSERT INTO tawrid_customers (legacy_id, customer_code, customer_name, is_active) "
        "VALUES (%s, %s, %s, FALSE) RETURNING customer_id",
        [_DELETED_CUSTOMER_LEGACY_ID, next_code, "عميل محذوف"],
    )
    report.note(_DELETED_CUSTOMER_LEGACY_ID, "عميل محذوف",
                f"أُنشئ كارت «عميل محذوف» موقوف (مسلسل {next_code}) للبونات بلا عميل")
    return row["customer_id"] if row else None


def _ticket_number_overrides(rows: list[dict[str, Any]]) -> dict[Any, int]:
    """Fresh البون numbers for rows whose ``number1`` is 0/blank (illegal: >0).

    Assigned past the highest number in use, in id order, from the Access rows
    alone so a re-run lands on the same numbers instead of walking them forward.
    """
    next_free = max((int(r["number1"]) for r in rows if r.get("number1")), default=0)
    overrides: dict[Any, int] = {}
    for row in rows:
        number = row.get("number1")
        if not number or int(number) <= 0:
            next_free += 1
            overrides[row["id"]] = next_free
    return overrides


_TICKET_UPSERT = """
INSERT INTO tawrid_tickets
    (legacy_id, ticket_no, receipt_no, ticket_date, customer_id, supplier_id,
     tractor_id, item_id, item_name, item_family,
     cus_volume, price_cus, discount_percent, res_volume, price_res, price_man)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (legacy_id) WHERE legacy_id IS NOT NULL DO UPDATE SET
    ticket_no        = EXCLUDED.ticket_no,
    receipt_no       = EXCLUDED.receipt_no,
    ticket_date      = EXCLUDED.ticket_date,
    customer_id      = EXCLUDED.customer_id,
    supplier_id      = EXCLUDED.supplier_id,
    tractor_id       = EXCLUDED.tractor_id,
    item_id          = EXCLUDED.item_id,
    item_name        = EXCLUDED.item_name,
    item_family      = EXCLUDED.item_family,
    cus_volume       = EXCLUDED.cus_volume,
    price_cus        = EXCLUDED.price_cus,
    discount_percent = EXCLUDED.discount_percent,
    res_volume       = EXCLUDED.res_volume,
    price_res        = EXCLUDED.price_res,
    price_man        = EXCLUDED.price_man
RETURNING (xmax = 0) AS inserted
"""


def import_tickets(
    access_path: str | None = None,
    db: Database | None = None,
    dry_run: bool = False,
    new_only: bool = False,
) -> ImportReport:
    """Import ``TBBOOn`` into ``tawrid_tickets``. Returns what happened.

    Depends on the three party imports (customers, suppliers, tractors +
    recovered) already having run: each party is resolved through its own
    ``legacy_id``, with موقوف «محذوف» placeholders for the unrecoverable ones.
    """
    report = ImportReport(table="tawrid_tickets")
    database = db or Database()
    sql = _insert_only_sql(_TICKET_UPSERT) if new_only else _TICKET_UPSERT

    customers = {
        r["legacy_id"]: r["customer_id"]
        for r in database.fetch_all(
            "SELECT legacy_id, customer_id FROM tawrid_customers WHERE legacy_id IS NOT NULL"
        )
    }
    suppliers = {
        r["legacy_id"]: r["supplier_id"]
        for r in database.fetch_all(
            "SELECT legacy_id, supplier_id FROM tawrid_suppliers WHERE legacy_id IS NOT NULL"
        )
    }
    tractors = {
        r["legacy_id"]: r["tractor_id"]
        for r in database.fetch_all(
            "SELECT legacy_id, tractor_id FROM tawrid_tractors WHERE legacy_id IS NOT NULL"
        )
    }
    items_by_norm = {
        _item_norm(r["item_name"]): r["item_id"]
        for r in database.fetch_all("SELECT item_id, item_name FROM tawrid_items")
    }

    # Rescale the customers' own default discount from a fraction to a percent.
    # Idempotent: 0.01 → 1.0, and 1.0 is not < 1, so a second run is a no-op.
    if not dry_run:
        rescaled = database.fetch_all(
            "UPDATE tawrid_customers SET discount_percent = discount_percent * 100 "
            "WHERE discount_percent > 0 AND discount_percent < 1 RETURNING customer_id"
        )
        if rescaled:
            report.note(0, "خصم العملاء",
                        f"أُعيد ضبط نسبة الخصم من كسر إلى نسبة مئوية لـ {len(rescaled)} عميل")

    with AccessReader(access_path) as reader:
        rows = list(reader.rows(TICKETS_QUERY))

    report.read = len(rows)
    overrides = _ticket_number_overrides(rows)
    placeholder_customer: Any = None
    placeholder_supplier: Any = None

    # ``ticket_no`` is UNIQUE, and ``ON CONFLICT (legacy_id) DO NOTHING`` does not
    # catch a *ticket_no* clash. On a re-import a brand-new بون can carry a رقم
    # that Access (which enforces no uniqueness) also gave an earlier ticket, or
    # that the first migration synthesised for a number1≤0 ticket. Such a NEW بون
    # gets the next free number instead of colliding; an existing one keeps its
    # number (its legacy_id is already ours, so it is only skipped/updated in
    # place). The free number is taken past both the app's and Access's maxima so
    # it cannot land on another incoming ticket's number.
    owned_ticket = {
        r["legacy_id"]
        for r in database.fetch_all(
            "SELECT legacy_id FROM tawrid_tickets WHERE legacy_id IS NOT NULL"
        )
    }
    used_nos = {
        r["ticket_no"] for r in database.fetch_all("SELECT ticket_no FROM tawrid_tickets")
    }
    next_free_no = max(
        [int(r["number1"]) for r in rows if r.get("number1")]
        + [int(n) for n in used_nos if n is not None]
        + [0]
    )

    for row in rows:
        legacy_id = row["id"]
        number = row.get("number1")
        if legacy_id in overrides:
            new_no = overrides[legacy_id]
            report.note(legacy_id, f"بون {number}",
                        f"رقم البون {number} غير صالح (يجب أن يكون > 0) -> {new_no}")
            number = new_no
        if legacy_id not in owned_ticket and number in used_nos:
            next_free_no += 1
            report.note(legacy_id, f"بون {number}",
                        f"رقم البون {number} محجوز بالفعل بالبرنامج -> {next_free_no}")
            number = next_free_no
            used_nos.add(number)

        # Customer — placeholder when deleted or missing.
        customer_id = customers.get(row.get("cus_id"))
        if customer_id is None:
            if placeholder_customer is None:
                placeholder_customer = _ensure_placeholder_customer(database, report, dry_run)
            customer_id = placeholder_customer

        # Crusher — placeholder (the phase-5 «كسّارة محذوفة») when deleted/missing.
        supplier_id = suppliers.get(row.get("res_id"))
        if supplier_id is None:
            if placeholder_supplier is None:
                placeholder_supplier = _ensure_placeholder_crusher(database, report, dry_run)
            supplier_id = placeholder_supplier

        # Tractor — nullable; the recovered cards cover all but a stray NULL.
        tractor_id = tractors.get(row.get("maatora_id"))

        # Item — best-effort link to the catalogue; the printed name is kept as-is.
        norm = _item_norm(row.get("productName"))
        item_id = items_by_norm.get(norm) or items_by_norm.get(_ITEM_ALIASES.get(norm))

        discount_percent = _amount(row.get("disc")) * Decimal("100")

        if dry_run:
            continue
        try:
            _count_result(report, database.fetch_one(sql, [
                legacy_id,
                number,
                _plate(row.get("NumberEissal")),
                _as_date(row.get("date123")),
                customer_id,
                supplier_id,
                tractor_id,
                item_id,
                (str(row.get("productName") or "").strip())[:60],
                (str(row.get("typeharka") or "").strip())[:20],
                _amount(row.get("Tak3ib")),
                _amount(row.get("PriceCus")),
                discount_percent,
                _amount(row.get("Tak3ibres")),
                _amount(row.get("Priceres")),
                _amount(row.get("Pricemand")),
            ]), new_only)
        except Exception as exc:
            report.errors.append((legacy_id, f"بون {number}", str(exc).splitlines()[0]))
            report.skipped += 1
    return report


# قسم التوريدات — المرحلة السادسة: سندات قبض العملاء (sanadCus).
# The Access table is a flat five-column log; ``empid`` is the customer link (an
# employee-template leftover name), and there is NO receipt-number column — only
# the row id, which becomes the new ``receipt_no`` (unique, 1..1214) as well as
# the ``legacy_id`` provenance.
SANADCUS_QUERY = "SELECT id, date123, empid, amount, bian FROM sanadCus ORDER BY id"

_RECEIPT_UPSERT = """
INSERT INTO tawrid_customer_receipts
    (legacy_id, receipt_no, receipt_date, customer_id, amount, statement)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (legacy_id) WHERE legacy_id IS NOT NULL DO UPDATE SET
    receipt_no   = EXCLUDED.receipt_no,
    receipt_date = EXCLUDED.receipt_date,
    customer_id  = EXCLUDED.customer_id,
    amount       = EXCLUDED.amount,
    statement    = EXCLUDED.statement
RETURNING (xmax = 0) AS inserted
"""


def import_customer_receipts(
    access_path: str | None = None,
    db: Database | None = None,
    dry_run: bool = False,
    new_only: bool = False,
) -> ImportReport:
    """Import ``sanadCus`` into ``tawrid_customer_receipts``. Returns what happened.

    Depends on the customers already being imported (phase 2): each receipt's
    customer is resolved through ``tawrid_customers.legacy_id`` = ``fanii.id``,
    with the موقوف «عميل محذوف» placeholder for the 308 that point at a deleted
    customer — the same placeholder the البون import uses. The Access row ``id``
    becomes both the ``legacy_id`` and the (previously non-existent) ``receipt_no``.
    """
    report = ImportReport(table="tawrid_customer_receipts")
    database = db or Database()
    sql = _insert_only_sql(_RECEIPT_UPSERT) if new_only else _RECEIPT_UPSERT

    customers = {
        r["legacy_id"]: r["customer_id"]
        for r in database.fetch_all(
            "SELECT legacy_id, customer_id FROM tawrid_customers WHERE legacy_id IS NOT NULL"
        )
    }

    with AccessReader(access_path) as reader:
        rows = list(reader.rows(SANADCUS_QUERY))

    report.read = len(rows)
    placeholder_customer: Any = None

    for row in rows:
        legacy_id = row["id"]

        # Customer — placeholder «عميل محذوف» when deleted or missing.
        customer_id = customers.get(row.get("empid"))
        if customer_id is None:
            if placeholder_customer is None:
                placeholder_customer = _ensure_placeholder_customer(database, report, dry_run)
            customer_id = placeholder_customer

        # Amount — a null becomes 0 (flagged); a negative is a genuine reversal,
        # kept as-is so SUM(amount) nets it (flagged so a human can check).
        raw_amount = row.get("amount")
        if raw_amount is None:
            amount = Decimal("0")
            report.note(legacy_id, f"سند {legacy_id}", "المبلغ كان فارغاً -> 0")
        else:
            amount = _amount(raw_amount)
            if amount < 0:
                report.note(legacy_id, f"سند {legacy_id}",
                            f"مبلغ سالب ({amount}) — مرتجع، نُقل كما هو")

        bian = row.get("bian")
        statement = str(bian).strip() if bian is not None else None
        if statement == "":
            statement = None

        if dry_run:
            continue
        try:
            _count_result(report, database.fetch_one(sql, [
                legacy_id,
                legacy_id,  # receipt_no = the Access id (unique, no other number exists)
                _as_date(row.get("date123")),
                customer_id,
                amount,
                statement,
            ]), new_only)
        except Exception as exc:
            report.errors.append((legacy_id, f"سند {legacy_id}", str(exc).splitlines()[0]))
            report.skipped += 1
    return report


# قسم التوريدات — المرحلة السابعة: سندات صرف الكسّارات (sanadsup).
# The mirror of ``sanadCus``: a flat five-column log; ``supid`` is the crusher
# link (→ ``pruduct.id``), and there is NO voucher-number column — only the row
# id, which becomes the new ``payment_no`` (unique, 1..149) as well as the
# ``legacy_id`` provenance. The audit found 0 orphans and 0 null/negative amounts,
# so the placeholder/flag branches below are the pattern kept in step with the
# customer-receipt import and never fire on this data.
SANADSUP_QUERY = "SELECT id, date123, supid, amount, bian FROM sanadsup ORDER BY id"

_PAYMENT_UPSERT = """
INSERT INTO tawrid_supplier_payments
    (legacy_id, payment_no, payment_date, supplier_id, amount, statement)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (legacy_id) WHERE legacy_id IS NOT NULL DO UPDATE SET
    payment_no   = EXCLUDED.payment_no,
    payment_date = EXCLUDED.payment_date,
    supplier_id  = EXCLUDED.supplier_id,
    amount       = EXCLUDED.amount,
    statement    = EXCLUDED.statement
RETURNING (xmax = 0) AS inserted
"""


def import_supplier_payments(
    access_path: str | None = None,
    db: Database | None = None,
    dry_run: bool = False,
    new_only: bool = False,
) -> ImportReport:
    """Import ``sanadsup`` into ``tawrid_supplier_payments``. Returns what happened.

    Depends on the crushers already being imported (phase 3): each payment's
    crusher is resolved through ``tawrid_suppliers.legacy_id`` = ``pruduct.id``,
    with the موقوف «كسّارة محذوفة» placeholder for any that point at a deleted
    crusher — the same placeholder the البون/التكعيب imports use (here the audit
    found 0 orphans, so it is not created). The Access row ``id`` becomes both the
    ``legacy_id`` and the (previously non-existent) ``payment_no``.
    """
    report = ImportReport(table="tawrid_supplier_payments")
    database = db or Database()
    sql = _insert_only_sql(_PAYMENT_UPSERT) if new_only else _PAYMENT_UPSERT

    suppliers = {
        r["legacy_id"]: r["supplier_id"]
        for r in database.fetch_all(
            "SELECT legacy_id, supplier_id FROM tawrid_suppliers WHERE legacy_id IS NOT NULL"
        )
    }

    with AccessReader(access_path) as reader:
        rows = list(reader.rows(SANADSUP_QUERY))

    report.read = len(rows)
    placeholder_supplier: Any = None

    for row in rows:
        legacy_id = row["id"]

        # Crusher — placeholder «كسّارة محذوفة» when deleted or missing.
        supplier_id = suppliers.get(row.get("supid"))
        if supplier_id is None:
            if placeholder_supplier is None:
                placeholder_supplier = _ensure_placeholder_crusher(database, report, dry_run)
            supplier_id = placeholder_supplier
            report.note(legacy_id, f"سند صرف {legacy_id}",
                        f"كسّارة محذوفة (supid={row.get('supid')}) — رُبط بكارت «كسّارة محذوفة»")

        # Amount — a null becomes 0 (flagged); a negative is a genuine reversal,
        # kept as-is so SUM(amount) nets it (flagged so a human can check).
        raw_amount = row.get("amount")
        if raw_amount is None:
            amount = Decimal("0")
            report.note(legacy_id, f"سند صرف {legacy_id}", "المبلغ كان فارغاً -> 0")
        else:
            amount = _amount(raw_amount)
            if amount < 0:
                report.note(legacy_id, f"سند صرف {legacy_id}",
                            f"مبلغ سالب ({amount}) — مرتجع، نُقل كما هو")

        bian = row.get("bian")
        statement = str(bian).strip() if bian is not None else None
        if statement == "":
            statement = None

        if dry_run:
            continue
        try:
            _count_result(report, database.fetch_one(sql, [
                legacy_id,
                legacy_id,  # payment_no = the Access id (unique, no other number exists)
                _as_date(row.get("date123")),
                supplier_id,
                amount,
                statement,
            ]), new_only)
        except Exception as exc:
            report.errors.append((legacy_id, f"سند صرف {legacy_id}", str(exc).splitlines()[0]))
            report.skipped += 1
    return report


# قسم التوريدات — المرحلة الثامنة: سندات صرف الجرارات (SanadCAR).
# The tractor-side mirror of ``sanadsup``: a flat five-column log; ``Gararid``
# (capital G) is the tractor link (→ ``tbgrarat.id``), and there is NO
# voucher-number column — only the row id, which becomes the new ``payment_no``
# (unique) as well as the ``legacy_id`` provenance. Unlike the crusher side the
# audit found real defects that fire below: 54 vouchers orphaned on 3 deleted
# tractors (Gararid 27/42 resolve to the موقوف cards phase 1 recovered; Gararid
# 19 is truly gone → a موقوف «جرار محذوف» placeholder), and 1 null amount
# (Access id 453 → 0, flagged). SUM(amount) = 32,287,459.50.
SANADCAR_QUERY = "SELECT id, date123, Gararid, amount, bian FROM SanadCAR ORDER BY id"

# A stable sentinel ``legacy_id`` for the one shared موقوف «جرار محذوف» card,
# well clear of the positive ``tbgrarat.id`` values phase 1 uses. The tractor
# table is separate from the crusher/customer ones, so −1 is free here too.
_DELETED_TRACTOR_LEGACY_ID = -1


def _ensure_placeholder_tractor(
    database: Database, report: ImportReport, dry_run: bool
) -> Any:
    """Return the id of the shared موقوف «جرار محذوف» card, creating it once.

    Access left 1 payment voucher (Gararid 19) on a tractor that was deleted and
    never recovered — and ``SanadCAR`` carries no name or plate to rebuild it
    from — while ``tractor_id`` is NOT NULL. Rather than drop the voucher it
    points at one placeholder tractor, موقوف so it never appears in the active
    tractor pickers. Mirrors ``_ensure_placeholder_crusher``.
    """
    existing = database.fetch_one(
        "SELECT tractor_id FROM tawrid_tractors WHERE legacy_id = %s",
        [_DELETED_TRACTOR_LEGACY_ID],
    )
    if existing:
        return existing["tractor_id"]
    if dry_run:
        report.note(_DELETED_TRACTOR_LEGACY_ID, "جرار محذوف",
                    "سيتم إنشاء كارت «جرار محذوف» موقوف للسندات بلا جرار")
        return None
    next_code = int(
        database.fetch_one(
            "SELECT COALESCE(MAX(tractor_code), 0) + 1 AS c FROM tawrid_tractors"
        )["c"]
    )
    row = database.fetch_one(
        """
        INSERT INTO tawrid_tractors
            (legacy_id, tractor_code, driver_name, opening_balance, is_active)
        VALUES (%s, %s, %s, 0, FALSE)
        RETURNING tractor_id
        """,
        [_DELETED_TRACTOR_LEGACY_ID, next_code, "جرار محذوف"],
    )
    report.note(_DELETED_TRACTOR_LEGACY_ID, "جرار محذوف",
                f"أُنشئ كارت «جرار محذوف» موقوف (مسلسل {next_code}) للسندات بلا جرار")
    return row["tractor_id"] if row else None


_TRACTOR_PAYMENT_UPSERT = """
INSERT INTO tawrid_tractor_payments
    (legacy_id, payment_no, payment_date, tractor_id, amount, statement)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (legacy_id) WHERE legacy_id IS NOT NULL DO UPDATE SET
    payment_no   = EXCLUDED.payment_no,
    payment_date = EXCLUDED.payment_date,
    tractor_id   = EXCLUDED.tractor_id,
    amount       = EXCLUDED.amount,
    statement    = EXCLUDED.statement
RETURNING (xmax = 0) AS inserted
"""


def import_tractor_payments(
    access_path: str | None = None,
    db: Database | None = None,
    dry_run: bool = False,
    new_only: bool = False,
) -> ImportReport:
    """Import ``SanadCAR`` into ``tawrid_tractor_payments``. Returns what happened.

    Depends on the tractors already being imported (phases 1 + recovered): each
    payment's tractor is resolved through ``tawrid_tractors.legacy_id`` =
    ``tbgrarat.id``. 53 of the 54 orphan vouchers land on the موقوف cards phase 1
    recovered (Gararid 27/42); the 1 truly-gone tractor (Gararid 19) lands on the
    موقوف «جرار محذوف» placeholder. The Access row ``id`` becomes both the
    ``legacy_id`` and the (previously non-existent) ``payment_no``.
    """
    report = ImportReport(table="tawrid_tractor_payments")
    database = db or Database()
    sql = _insert_only_sql(_TRACTOR_PAYMENT_UPSERT) if new_only else _TRACTOR_PAYMENT_UPSERT

    tractors = {
        r["legacy_id"]: r["tractor_id"]
        for r in database.fetch_all(
            "SELECT legacy_id, tractor_id FROM tawrid_tractors WHERE legacy_id IS NOT NULL"
        )
    }

    with AccessReader(access_path) as reader:
        rows = list(reader.rows(SANADCAR_QUERY))

    report.read = len(rows)
    placeholder_tractor: Any = None

    for row in rows:
        legacy_id = row["id"]

        # Tractor — placeholder «جرار محذوف» when deleted or missing.
        tractor_id = tractors.get(row.get("Gararid"))
        if tractor_id is None:
            if placeholder_tractor is None:
                placeholder_tractor = _ensure_placeholder_tractor(database, report, dry_run)
            tractor_id = placeholder_tractor
            report.note(legacy_id, f"سند صرف {legacy_id}",
                        f"جرار محذوف (Gararid={row.get('Gararid')}) — رُبط بكارت «جرار محذوف»")

        # Amount — a null becomes 0 (flagged); a negative is a genuine reversal,
        # kept as-is so SUM(amount) nets it (flagged so a human can check).
        raw_amount = row.get("amount")
        if raw_amount is None:
            amount = Decimal("0")
            report.note(legacy_id, f"سند صرف {legacy_id}", "المبلغ كان فارغاً -> 0")
        else:
            amount = _amount(raw_amount)
            if amount < 0:
                report.note(legacy_id, f"سند صرف {legacy_id}",
                            f"مبلغ سالب ({amount}) — مرتجع، نُقل كما هو")

        bian = row.get("bian")
        statement = str(bian).strip() if bian is not None else None
        if statement == "":
            statement = None

        if dry_run:
            continue
        try:
            _count_result(report, database.fetch_one(sql, [
                legacy_id,
                legacy_id,  # payment_no = the Access id (unique, no other number exists)
                _as_date(row.get("date123")),
                tractor_id,
                amount,
                statement,
            ]), new_only)
        except Exception as exc:
            report.errors.append((legacy_id, f"سند صرف {legacy_id}", str(exc).splitlines()[0]))
            report.skipped += 1
    return report


# Run in this order: the price grid resolves both of its sides through the
# ``legacy_id`` columns the two importers above populate.
STEPS = {
    "tractors": import_tractors,
    # Before the grid: 12 of its rows point at tractors Access deleted, and they
    # can only be imported once those cards have been rebuilt.
    "recovered": import_recovered_tractors,
    "customers": import_customers,
    "prices": import_customer_tractor_prices,
    # Independent of everything above — ``pruduct`` references no other table.
    "suppliers": import_suppliers,
    # Phase 4 data — البون. After all three party imports (it resolves customer,
    # crusher and tractor through their legacy_id, with موقوف placeholders).
    "tickets": import_tickets,
    # Phase 5 — تكعيب الكسّارات. Headers before lines (lines resolve their header
    # through its legacy_id), and both after suppliers/tractors/recovered.
    "cubing_headers": import_cubing_headers,
    "cubing_lines": import_cubing_lines,
    # Phase 6 — سندات قبض العملاء. After customers (it resolves each receipt's
    # customer through its legacy_id, with the موقوف «عميل محذوف» placeholder).
    "customer_receipts": import_customer_receipts,
    # Phase 7 — سندات صرف الكسّارات. After suppliers (it resolves each payment's
    # crusher through its legacy_id, with the موقوف «كسّارة محذوفة» placeholder).
    "supplier_payments": import_supplier_payments,
    # Phase 8 — سندات صرف الجرارات. After tractors + recovered (it resolves each
    # payment's tractor through its legacy_id, with the موقوف «جرار محذوف»
    # placeholder for the 1 truly-gone tractor).
    "tractor_payments": import_tractor_payments,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="نقل بيانات الأكسس إلى قسم التوريدات")
    parser.add_argument("--access-path", default=None,
                        help="مسار ملف الأكسس (الافتراضي: review/sisko.Accdb)")
    parser.add_argument("--dry-run", action="store_true",
                        help="عرض ما سيحدث دون الكتابة في قاعدة البيانات")
    parser.add_argument("--new-only", action="store_true",
                        help="إضافة الصفوف الجديدة فقط دون المساس بأي صف موجود "
                             "(لتحديث من ملف أكسس أحدث)")
    parser.add_argument("--only", choices=sorted(STEPS), action="append",
                        help="نقل خطوة واحدة فقط (يمكن تكرارها). الافتراضي: الكل")
    args = parser.parse_args(argv)

    # The whole report is Arabic, and the Windows console defaults to a legacy
    # codepage (cp1256 here) that renders it as mojibake and raises outright on
    # the ✗ used for errors. Force UTF-8 so the operator can actually read what
    # the import did — this is the only output this tool has.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001 - never let logging break the import
                pass

    db = Database()
    current = db.fetch_one("SELECT current_database() AS d")
    print(f"قاعدة البيانات الهدف: {current['d']}")
    if args.dry_run:
        print("(تجربة فقط — لن تُكتب أي بيانات)")
    if args.new_only:
        print("(إضافة الجديد فقط — لن يُمَس أي صف موجود)")

    # Order matters even when --only is given: the dict preserves it.
    chosen = [name for name in STEPS if not args.only or name in args.only]
    failed = False
    for name in chosen:
        report = STEPS[name](args.access_path, db, dry_run=args.dry_run,
                             new_only=args.new_only)
        print(report.as_text())
        print()
        failed = failed or bool(report.errors)
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
