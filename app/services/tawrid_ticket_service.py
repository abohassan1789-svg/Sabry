"""Ticket (البون) queries for the Tawrid module — phase 4.

The البون is the heart of the module: one ticket carries three independent price
layers at once (customer / crusher / hauler), and all three account statements
read from it. The generic ``ReviewDataService`` handles the row's own INSERT /
UPDATE / DELETE through ``TABLE_SPECS['tawrid_tickets']``; everything this service
adds is the work that spans the four other tables:

* allocating the next البون number (``ticket_no``),
* the **item catalogue** (``tawrid_items``) that maps a chosen item to one of the
  ten fixed price columns — the deliberate home for what ``Fboun`` did with 10
  hardcoded ``IF`` branches,
* looking a **price** up on each of the three cards for that item, and
* loading one ticket back **joined** to the customer / crusher / tractor / item
  so the screen can show their names and the generated totals.

No presentation logic lives here: it returns values, and the screen formats them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.database.db import Database

# The ten fixed price columns shared by ``tawrid_customers`` and
# ``tawrid_suppliers``. A price column is chosen from ``tawrid_items`` and then
# interpolated into a query, so it is validated against this frozen set first —
# nothing else may ever reach the SQL string.
PRICE_COLUMNS = frozenset(
    {
        "price_sen1",
        "price_sen2",
        "price_sen_ataqa",
        "price_sen6_safi",
        "price_sen6_bodra",
        "price_sen_adsa",
        "price_bodra",
        "price_raml",
        "price_sen_plus",
        "price_sen_modarag",
    }
)

# The item family (typeharka) that is hauled at the رمل rate rather than the سن
# rate on the customer×tractor grid.
_RAML_FAMILY = "رمل"


@dataclass(frozen=True)
class ItemDef:
    """One catalogue row: the printed name, its family and its price column."""

    item_id: Any
    item_name: str
    item_family: str
    price_column: str


@dataclass(frozen=True)
class TicketPrices:
    """The three prices resolved for one (customer, crusher, tractor, item)."""

    price_cus: Decimal = Decimal("0")
    price_res: Decimal = Decimal("0")
    price_man: Decimal = Decimal("0")
    discount_percent: Decimal = Decimal("0")


class TawridTicketService:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()

    # -- helpers ---------------------------------------------------------

    def _scalar(self, query: str, params: list[Any], key: str, default: Any) -> Any:
        row = self._db.fetch_one(query, params)
        if not row or row.get(key) is None:
            return default
        return row[key]

    @staticmethod
    def _dec(value: Any) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        return Decimal(str(value))

    # -- numbering -------------------------------------------------------

    def next_ticket_no(self) -> int:
        """The next free البون number — ``MAX(ticket_no) + 1``, starting at 1.

        A display-only suggestion for a new ticket: the user may overwrite it,
        and the UNIQUE index on ``ticket_no`` is what actually guarantees no two
        tickets share one. The legacy numbers run 0..4117 with gaps, so
        continuing from the maximum (not the count) is the only safe rule.
        """
        row = self._db.fetch_one(
            "SELECT COALESCE(MAX(ticket_no), 0) + 1 AS n FROM tawrid_tickets"
        )
        return int(row["n"]) if row else 1

    def ticket_no_exists(self, ticket_no: Any, exclude_id: Any = None) -> bool:
        """Whether *ticket_no* is already taken (optionally ignoring one row).

        Lets the screen warn before the UNIQUE index raises a raw error on save.
        """
        if ticket_no in (None, ""):
            return False
        if exclude_id in (None, ""):
            row = self._db.fetch_one(
                "SELECT 1 AS x FROM tawrid_tickets WHERE ticket_no = %s LIMIT 1",
                [ticket_no],
            )
        else:
            row = self._db.fetch_one(
                "SELECT 1 AS x FROM tawrid_tickets WHERE ticket_no = %s AND ticket_id <> %s LIMIT 1",
                [ticket_no, exclude_id],
            )
        return bool(row)

    # -- the item catalogue ----------------------------------------------

    def items(self) -> list[ItemDef]:
        """Active catalogue items, in display order. The البون item combo."""
        rows = self._db.fetch_all(
            "SELECT item_id, item_name, item_family, price_column "
            "FROM tawrid_items WHERE is_active ORDER BY sort_order, item_name"
        )
        return [
            ItemDef(
                item_id=r["item_id"],
                item_name=r["item_name"] or "",
                item_family=r["item_family"] or "",
                price_column=r["price_column"],
            )
            for r in rows
        ]

    def item(self, item_id: Any) -> ItemDef | None:
        if item_id in (None, ""):
            return None
        r = self._db.fetch_one(
            "SELECT item_id, item_name, item_family, price_column "
            "FROM tawrid_items WHERE item_id = %s",
            [item_id],
        )
        if not r:
            return None
        return ItemDef(
            item_id=r["item_id"],
            item_name=r["item_name"] or "",
            item_family=r["item_family"] or "",
            price_column=r["price_column"],
        )

    # -- price resolution -------------------------------------------------

    def prices_for(
        self,
        customer_id: Any,
        supplier_id: Any,
        tractor_id: Any,
        item_id: Any,
    ) -> TicketPrices:
        """Resolve the three layer prices + the customer's default discount.

        * customer price and crusher price come from the item's fixed column on
          each card (``tawrid_customers`` / ``tawrid_suppliers``);
        * the hauler's rate comes from the customer×tractor grid for the item's
          family (سن vs رمل), falling back to the tractor card's own rate — the
          same lookup the grid on the customers screen exists to feed;
        * the discount defaults from the customer card (already a real percent).

        Any layer with no card, no item or no price resolves to zero rather than
        raising, so the screen can call this on every partial selection.
        """
        item = self.item(item_id)
        column = item.price_column if item else None
        family = item.item_family if item else ""

        price_cus = Decimal("0")
        discount = Decimal("0")
        if customer_id not in (None, ""):
            if column in PRICE_COLUMNS:
                price_cus = self._dec(
                    self._scalar(
                        f"SELECT {column} AS p FROM tawrid_customers WHERE customer_id = %s",
                        [customer_id],
                        "p",
                        0,
                    )
                )
            discount = self._dec(
                self._scalar(
                    "SELECT discount_percent AS d FROM tawrid_customers WHERE customer_id = %s",
                    [customer_id],
                    "d",
                    0,
                )
            )

        price_res = Decimal("0")
        if supplier_id not in (None, "") and column in PRICE_COLUMNS:
            price_res = self._dec(
                self._scalar(
                    f"SELECT {column} AS p FROM tawrid_suppliers WHERE supplier_id = %s",
                    [supplier_id],
                    "p",
                    0,
                )
            )

        price_man = self._hauler_price(customer_id, tractor_id, family)

        return TicketPrices(
            price_cus=price_cus,
            price_res=price_res,
            price_man=price_man,
            discount_percent=discount,
        )

    def grid_volume(self, customer_id: Any, tractor_id: Any) -> Decimal | None:
        """The load defined for this (customer, tractor) pair on the price grid.

        ``tawrid_customer_tractor_prices.load_volume`` is the Access ``CarCus.tak3ib``
        — the cubic-metre load the user set up for this customer against this
        tractor on the customers screen. The البون auto-fills ``cus_volume`` from
        it so the volume is not re-typed on every ticket.

        Returns ``None`` when the pair has no grid row, so the screen knows to
        leave whatever is already in the box rather than zeroing it.
        """
        if customer_id in (None, "") or tractor_id in (None, ""):
            return None
        row = self._db.fetch_one(
            "SELECT load_volume FROM tawrid_customer_tractor_prices "
            "WHERE customer_id = %s AND tractor_id = %s",
            [customer_id, tractor_id],
        )
        if not row or row.get("load_volume") is None:
            return None
        return self._dec(row["load_volume"])

    def _hauler_price(self, customer_id: Any, tractor_id: Any, family: str) -> Decimal:
        """The transport rate for a (customer, tractor, family) trip.

        The grid rate wins when the pair is priced there (208 of 221 legacy grid
        rows differ from the tractor's own default, which is the whole reason the
        grid exists); otherwise the tractor card's default is used.
        """
        if tractor_id in (None, ""):
            return Decimal("0")
        grid_col = "price_raml" if family == _RAML_FAMILY else "price_sen"
        if customer_id not in (None, ""):
            row = self._db.fetch_one(
                f"SELECT {grid_col} AS p FROM tawrid_customer_tractor_prices "
                "WHERE customer_id = %s AND tractor_id = %s",
                [customer_id, tractor_id],
            )
            if row and row.get("p") is not None:
                return self._dec(row["p"])
        # Fall back to the tractor card's own rate for that family.
        return self._dec(
            self._scalar(
                f"SELECT {grid_col} AS p FROM tawrid_tractors WHERE tractor_id = %s",
                [tractor_id],
                "p",
                0,
            )
        )

    # -- picker rows ------------------------------------------------------

    def customer_picker_rows(self) -> list[dict[str, Any]]:
        """Active-first customer cards for the البون customer picker."""
        return list(
            self._db.fetch_all(
                "SELECT customer_id, customer_code, customer_name, phone, is_active "
                "FROM tawrid_customers ORDER BY is_active DESC, customer_name"
            )
        )

    def supplier_picker_rows(self) -> list[dict[str, Any]]:
        """Active-first crusher cards for the البون crusher picker."""
        return list(
            self._db.fetch_all(
                "SELECT supplier_id, supplier_code, supplier_name, is_active "
                "FROM tawrid_suppliers ORDER BY is_active DESC, supplier_name"
            )
        )

    def tractor_picker_rows(self) -> list[dict[str, Any]]:
        """Active tractor cards for the البون tractor picker.

        Only active ones: the موقوف cards are the recovered/deleted tractors,
        which exist so old tickets resolve but are never picked for new work.
        """
        return list(
            self._db.fetch_all(
                "SELECT tractor_id, tractor_code, driver_name, trailer_no, head_no, "
                "price_sen, price_raml "
                "FROM tawrid_tractors WHERE is_active ORDER BY driver_name"
            )
        )

    def customer_tractor_picker_rows(self, customer_id: Any) -> list[dict[str, Any]]:
        """Only the tractors set up for *customer_id* on the price grid.

        The «جرارات العميل» half of the tractor picker: the pairs the user
        configured on the customers screen (``tawrid_customer_tractor_prices``),
        so the البون can be narrowed to the tractors that actually haul for this
        customer. Same shape as :meth:`tractor_picker_rows` so the dialog treats
        both lists identically.
        """
        if customer_id in (None, ""):
            return []
        return list(
            self._db.fetch_all(
                "SELECT t.tractor_id, t.tractor_code, t.driver_name, t.trailer_no, "
                "t.head_no, t.price_sen, t.price_raml "
                "FROM tawrid_customer_tractor_prices p "
                "JOIN tawrid_tractors t ON t.tractor_id = p.tractor_id "
                "WHERE p.customer_id = %s ORDER BY t.driver_name",
                [customer_id],
            )
        )

    def crusher_tractor_picker_rows(self, supplier_id: Any) -> list[dict[str, Any]]:
        """Only the tractors that hauled from *supplier_id* (the crusher).

        The «جرارات الكسّارة» half of the tractor picker: the distinct tractors
        that appear on this crusher's تكعيب الكسّارات sheets
        (``tawrid_crusher_cubing`` + its lines). Same shape as
        :meth:`tractor_picker_rows` so the dialog treats both lists identically.
        Returns an empty list when the crusher has no cubing sheets yet (or the
        cubing tables do not exist on this database).
        """
        if supplier_id in (None, ""):
            return []
        try:
            return list(
                self._db.fetch_all(
                    "SELECT DISTINCT t.tractor_id, t.tractor_code, t.driver_name, "
                    "t.trailer_no, t.head_no, t.price_sen, t.price_raml "
                    "FROM tawrid_crusher_cubing_lines l "
                    "JOIN tawrid_crusher_cubing h ON h.cubing_id = l.cubing_id "
                    "JOIN tawrid_tractors t ON t.tractor_id = l.tractor_id "
                    "WHERE h.crusher_id = %s AND l.tractor_id IS NOT NULL "
                    "ORDER BY t.driver_name",
                    [supplier_id],
                )
            )
        except Exception:  # noqa: BLE001 - a missing cubing table must not break البون
            return []

    # -- tractor-first filtering (the «بون 2» flow) ----------------------

    def customers_for_tractor(self, tractor_id: Any) -> list[dict[str, Any]]:
        """The customers set up for *tractor_id* on the price grid.

        The reverse of :meth:`customer_tractor_picker_rows`: given the tractor
        chosen first on the «بون 2» screen, the customers that actually haul with
        it — the pairs configured on the customers screen
        (``tawrid_customer_tractor_prices``). Same shape as
        :meth:`customer_picker_rows` so the customer picker treats both lists
        identically. Empty when the tractor has no grid pair yet.
        """
        if tractor_id in (None, ""):
            return []
        return list(
            self._db.fetch_all(
                "SELECT c.customer_id, c.customer_code, c.customer_name, c.phone, "
                "c.is_active "
                "FROM tawrid_customer_tractor_prices p "
                "JOIN tawrid_customers c ON c.customer_id = p.customer_id "
                "WHERE p.tractor_id = %s "
                "ORDER BY c.is_active DESC, c.customer_name",
                [tractor_id],
            )
        )

    def crushers_for_tractor(self, tractor_id: Any) -> list[dict[str, Any]]:
        """The crushers that *tractor_id* hauled from, from the تكعيب sheets.

        The reverse of :meth:`crusher_tractor_picker_rows`: given the tractor
        chosen first on «بون 2», the distinct crushers whose تكعيب الكسّارات sheets
        (``tawrid_crusher_cubing`` + its lines) list this tractor. Same shape as
        :meth:`supplier_picker_rows` so the crusher picker treats both lists
        identically. Empty when the tractor appears on no sheet (or the cubing
        tables do not exist on this database).
        """
        if tractor_id in (None, ""):
            return []
        try:
            return list(
                self._db.fetch_all(
                    "SELECT DISTINCT s.supplier_id, s.supplier_code, s.supplier_name, "
                    "s.is_active "
                    "FROM tawrid_crusher_cubing_lines l "
                    "JOIN tawrid_crusher_cubing h ON h.cubing_id = l.cubing_id "
                    "JOIN tawrid_suppliers s ON s.supplier_id = h.crusher_id "
                    "WHERE l.tractor_id = %s "
                    "ORDER BY s.is_active DESC, s.supplier_name",
                    [tractor_id],
                )
            )
        except Exception:  # noqa: BLE001 - a missing cubing table must not break البون
            return []

    def crusher_volume(self, supplier_id: Any, tractor_id: Any) -> Decimal | None:
        """The crusher's تكعيب for this (crusher, tractor) pair, most recent first.

        Read from the تكعيب الكسّارات sheets: the volume this tractor hauled from
        this crusher on its **latest** sheet. The البون auto-fills ``res_volume``
        (تكعيب الكسّارة) from it when a crusher's own tractor is picked, so the
        crusher-side volume is not re-typed. Returns ``None`` when the pair has no
        cubing line (so the screen leaves whatever is in the box).
        """
        if supplier_id in (None, "") or tractor_id in (None, ""):
            return None
        try:
            row = self._db.fetch_one(
                "SELECT l.volume FROM tawrid_crusher_cubing_lines l "
                "JOIN tawrid_crusher_cubing h ON h.cubing_id = l.cubing_id "
                "WHERE h.crusher_id = %s AND l.tractor_id = %s "
                "ORDER BY h.sheet_date DESC, h.cubing_id DESC, l.line_id DESC "
                "LIMIT 1",
                [supplier_id, tractor_id],
            )
        except Exception:  # noqa: BLE001 - a missing cubing table must not break البون
            return None
        if not row or row.get("volume") is None:
            return None
        return self._dec(row["volume"])

    # -- one ticket, joined for display -----------------------------------

    def for_ticket(self, ticket_id: Any) -> dict[str, Any] | None:
        """Load one ticket joined to every party, with the generated totals.

        ``ReviewDataService.get_record`` returns only the ticket's own writable
        columns; this adds the names (which live on the other tables) and the
        five generated figures, so the screen's cards need one call, not five.
        """
        if ticket_id in (None, ""):
            return None
        return self._db.fetch_one(
            """
            SELECT t.ticket_id, t.ticket_no, t.receipt_no, t.ticket_date,
                   t.customer_id, t.supplier_id, t.tractor_id, t.item_id,
                   t.item_name, t.item_family,
                   t.cus_volume, t.price_cus, t.discount_percent,
                   t.res_volume, t.price_res, t.price_man,
                   t.total_cus, t.amount_dis, t.safi_cus, t.total_res, t.total_man,
                   t.notes,
                   c.customer_name, c.customer_code,
                   s.supplier_name, s.supplier_code,
                   g.driver_name, g.trailer_no, g.head_no
              FROM tawrid_tickets t
              LEFT JOIN tawrid_customers c ON c.customer_id = t.customer_id
              LEFT JOIN tawrid_suppliers s ON s.supplier_id = t.supplier_id
              LEFT JOIN tawrid_tractors  g ON g.tractor_id  = t.tractor_id
             WHERE t.ticket_id = %s
            """,
            [ticket_id],
        )

    # -- the search dialog ------------------------------------------------

    def search_tickets(self, keyword: str = "", limit: int = 300) -> list[dict[str, Any]]:
        """Rows for the «بحث عن بون» dialog: newest first, filtered by keyword.

        Matches the البون number, the receipt number or the customer/crusher
        name. An empty keyword returns the most recent *limit* tickets so the
        dialog opens on something useful rather than blank.
        """
        needle = str(keyword or "").strip()
        base = """
            SELECT t.ticket_id, t.ticket_no, t.receipt_no, t.ticket_date, t.item_name,
                   t.safi_cus, t.total_res, t.total_man,
                   c.customer_name, s.supplier_name
              FROM tawrid_tickets t
              LEFT JOIN tawrid_customers c ON c.customer_id = t.customer_id
              LEFT JOIN tawrid_suppliers s ON s.supplier_id = t.supplier_id
        """
        if needle:
            like = f"%{needle}%"
            rows = self._db.fetch_all(
                base
                + """
                 WHERE CAST(t.ticket_no AS TEXT) ILIKE %s
                    OR COALESCE(t.receipt_no, '') ILIKE %s
                    OR COALESCE(c.customer_name, '') ILIKE %s
                    OR COALESCE(s.supplier_name, '') ILIKE %s
                 ORDER BY t.ticket_no DESC
                 LIMIT %s
                """,
                [like, like, like, like, limit],
            )
        else:
            rows = self._db.fetch_all(
                base + " ORDER BY t.ticket_no DESC LIMIT %s", [limit]
            )
        return list(rows)
