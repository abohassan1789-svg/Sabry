"""كشف تكعيب الكسّارات — queries for the Tawrid module (phase 5).

The cubing sheet is a **master→detail document**: one header
(``tawrid_crusher_cubing`` — a crusher + a date + a sheet number) owns many
lines (``tawrid_crusher_cubing_lines`` — a tractor + its cubic volume). It
replaces the Access objects ``sallesHead`` / ``Sallesdata`` / ``SallesInvoice``,
which despite their *sales-invoice* names carry **no price** at all — only the
تكعيب (volume) of each tractor from each crusher (audited 2026-09-04).

The header's own INSERT / UPDATE / DELETE is the shared path
(``ReviewDataService`` + ``TABLE_SPECS['tawrid_crusher_cubing']``); everything
here is the work that spans the lines table and the joined display:

* allocating the next sheet number (``sheet_no``),
* the crusher / tractor picker row-sets,
* the sheet's lines, **joined to the tractor card** so رقم الوش / اسم السائق are
  read live (the snapshot columns are only a fallback for a deleted tractor),
* add / update-volume / delete of one line (each its own statement, like the
  customers-screen price grid — no cross-table transaction is needed),
* the per-sheet totals the screen shows (count / total / average / max / zeros /
  deleted), computed here so no arithmetic lives in the UI, and
* ``for_cubing`` (one header joined to its crusher) and ``search_cubing`` for the
  «بحث عن كشف» dialog.

No presentation logic lives here: it returns values, and the screen formats them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.database.db import Database


@dataclass(frozen=True)
class CubingLine:
    """One sheet line, resolved for display.

    ``driver_name`` / ``trailer_no`` are read from the tractor card when the
    tractor still exists, and fall back to the snapshot stored on the line for a
    deleted tractor. ``is_deleted`` is True when the line has no live active
    tractor behind it, so the screen can flag it («محذوف»).
    """

    line_id: Any
    cubing_id: Any
    line_seq: int
    tractor_id: Any
    driver_name: str
    trailer_no: str
    volume: Decimal
    is_deleted: bool


@dataclass(frozen=True)
class CubingTotals:
    """The aggregate figures for one sheet, shown in the totals footer."""

    line_count: int = 0
    total_volume: Decimal = Decimal("0")
    average_volume: Decimal = Decimal("0")
    max_volume: Decimal = Decimal("0")
    zero_count: int = 0
    deleted_count: int = 0


class TawridCubingService:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _dec(value: Any) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        return Decimal(str(value))

    # -- numbering -------------------------------------------------------

    def next_sheet_no(self) -> int:
        """The next free sheet number — ``MAX(sheet_no) + 1``, starting at 1.

        A display-only suggestion for a new sheet; the UNIQUE index on
        ``sheet_no`` is what actually guarantees no two sheets share one. The
        legacy numbers run 1..21 with no gaps, so continuing from the maximum
        (not the count) is the safe rule once rows are deleted.
        """
        row = self._db.fetch_one(
            "SELECT COALESCE(MAX(sheet_no), 0) + 1 AS n FROM tawrid_crusher_cubing"
        )
        return int(row["n"]) if row else 1

    def sheet_no_exists(self, sheet_no: Any, exclude_id: Any = None) -> bool:
        """Whether *sheet_no* is already taken (optionally ignoring one row).

        Lets the screen warn before the UNIQUE index raises a raw error on save.
        """
        if sheet_no in (None, ""):
            return False
        if exclude_id in (None, ""):
            row = self._db.fetch_one(
                "SELECT 1 AS x FROM tawrid_crusher_cubing WHERE sheet_no = %s LIMIT 1",
                [sheet_no],
            )
        else:
            row = self._db.fetch_one(
                "SELECT 1 AS x FROM tawrid_crusher_cubing "
                "WHERE sheet_no = %s AND cubing_id <> %s LIMIT 1",
                [sheet_no, exclude_id],
            )
        return bool(row)

    # -- picker rows ------------------------------------------------------

    def supplier_picker_rows(self) -> list[dict[str, Any]]:
        """Active-first crusher cards for the sheet's crusher picker."""
        return list(
            self._db.fetch_all(
                "SELECT supplier_id, supplier_code, supplier_name, is_active "
                "FROM tawrid_suppliers ORDER BY is_active DESC, supplier_name"
            )
        )

    def tractor_picker_rows(self) -> list[dict[str, Any]]:
        """Active tractor cards for the line's tractor picker.

        Only active ones: the موقوف cards are the recovered/deleted tractors,
        which exist so old sheets resolve but are never picked for new lines.
        """
        return list(
            self._db.fetch_all(
                "SELECT tractor_id, tractor_code, driver_name, trailer_no, head_no "
                "FROM tawrid_tractors WHERE is_active ORDER BY driver_name"
            )
        )

    # -- the lines --------------------------------------------------------

    def lines(self, cubing_id: Any) -> list[CubingLine]:
        """The sheet's lines, joined to the tractor card, in display order."""
        if cubing_id in (None, ""):
            return []
        rows = self._db.fetch_all(
            """
            SELECT l.line_id, l.cubing_id, l.line_seq, l.tractor_id,
                   l.driver_name_snapshot, l.trailer_no_snapshot, l.volume,
                   t.driver_name, t.trailer_no, t.head_no, t.is_active
              FROM tawrid_crusher_cubing_lines l
              LEFT JOIN tawrid_tractors t ON t.tractor_id = l.tractor_id
             WHERE l.cubing_id = %s
             ORDER BY l.line_seq, l.line_id
            """,
            [cubing_id],
        )
        out: list[CubingLine] = []
        for r in rows:
            live = r.get("driver_name")
            snapshot = r.get("driver_name_snapshot") or ""
            driver = live if live not in (None, "") else snapshot
            plate = r.get("head_no") or r.get("trailer_no") or r.get("trailer_no_snapshot") or ""
            # A line is "deleted" when it has no live tractor, or its tractor is
            # a موقوف card (the recovered/deleted ones from phase 1).
            is_deleted = r.get("tractor_id") is None or not bool(r.get("is_active"))
            out.append(
                CubingLine(
                    line_id=r["line_id"],
                    cubing_id=r["cubing_id"],
                    line_seq=int(r.get("line_seq") or 0),
                    tractor_id=r.get("tractor_id"),
                    driver_name=str(driver or ""),
                    trailer_no=str(plate or ""),
                    volume=self._dec(r.get("volume")),
                    is_deleted=is_deleted,
                )
            )
        return out

    def line_count(self, cubing_id: Any) -> int:
        if cubing_id in (None, ""):
            return 0
        row = self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM tawrid_crusher_cubing_lines WHERE cubing_id = %s",
            [cubing_id],
        )
        return int(row["n"]) if row else 0

    def add_line(
        self,
        cubing_id: Any,
        tractor_id: Any,
        volume: Any = 0,
        driver_name_snapshot: str = "",
        trailer_no_snapshot: str = "",
    ) -> Any:
        """Append one line to the sheet and return its ``line_id``.

        ``line_seq`` is set to ``MAX(line_seq)+1`` on this sheet so the display
        order is stable and the new line always lands at the bottom.
        """
        seq_row = self._db.fetch_one(
            "SELECT COALESCE(MAX(line_seq), 0) + 1 AS n "
            "FROM tawrid_crusher_cubing_lines WHERE cubing_id = %s",
            [cubing_id],
        )
        next_seq = int(seq_row["n"]) if seq_row else 1
        row = self._db.fetch_one(
            """
            INSERT INTO tawrid_crusher_cubing_lines
                (cubing_id, line_seq, tractor_id, driver_name_snapshot,
                 trailer_no_snapshot, volume)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING line_id
            """,
            [
                cubing_id,
                next_seq,
                tractor_id if tractor_id not in (None, "") else None,
                str(driver_name_snapshot or ""),
                str(trailer_no_snapshot or ""),
                self._dec(volume),
            ],
        )
        return row["line_id"] if row else None

    def update_line_volume(self, line_id: Any, volume: Any) -> None:
        """Set one line's volume (the only field the user edits inline)."""
        self._db.execute(
            "UPDATE tawrid_crusher_cubing_lines SET volume = %s WHERE line_id = %s",
            [self._dec(volume), line_id],
        )

    def delete_line(self, line_id: Any) -> None:
        self._db.execute(
            "DELETE FROM tawrid_crusher_cubing_lines WHERE line_id = %s", [line_id]
        )

    # -- totals -----------------------------------------------------------

    def totals(self, cubing_id: Any) -> CubingTotals:
        """The aggregate figures for one sheet's lines."""
        if cubing_id in (None, ""):
            return CubingTotals()
        row = self._db.fetch_one(
            """
            SELECT COUNT(*) AS line_count,
                   COALESCE(SUM(l.volume), 0) AS total_volume,
                   COALESCE(MAX(l.volume), 0) AS max_volume,
                   COUNT(*) FILTER (WHERE l.volume = 0) AS zero_count,
                   COUNT(*) FILTER (
                       WHERE l.tractor_id IS NULL OR t.is_active IS NOT TRUE
                   ) AS deleted_count
              FROM tawrid_crusher_cubing_lines l
              LEFT JOIN tawrid_tractors t ON t.tractor_id = l.tractor_id
             WHERE l.cubing_id = %s
            """,
            [cubing_id],
        )
        if not row:
            return CubingTotals()
        count = int(row["line_count"] or 0)
        total = self._dec(row["total_volume"])
        average = (total / count) if count else Decimal("0")
        return CubingTotals(
            line_count=count,
            total_volume=total,
            average_volume=average,
            max_volume=self._dec(row["max_volume"]),
            zero_count=int(row["zero_count"] or 0),
            deleted_count=int(row["deleted_count"] or 0),
        )

    # -- one sheet, joined for display -----------------------------------

    def for_cubing(self, cubing_id: Any) -> dict[str, Any] | None:
        """Load one sheet header joined to its crusher name."""
        if cubing_id in (None, ""):
            return None
        return self._db.fetch_one(
            """
            SELECT h.cubing_id, h.sheet_no, h.sheet_date, h.crusher_id, h.notes,
                   s.supplier_name, s.supplier_code
              FROM tawrid_crusher_cubing h
              LEFT JOIN tawrid_suppliers s ON s.supplier_id = h.crusher_id
             WHERE h.cubing_id = %s
            """,
            [cubing_id],
        )

    # -- the search dialog ------------------------------------------------

    def search_cubing(self, keyword: str = "", limit: int = 300) -> list[dict[str, Any]]:
        """Rows for the «بحث عن كشف» dialog: newest sheet first, filtered.

        Matches the sheet number or the crusher name; each row carries the line
        count and total volume so the dialog is informative. An empty keyword
        returns the most recent *limit* sheets so it opens on something useful.
        """
        needle = str(keyword or "").strip()
        base = """
            SELECT h.cubing_id, h.sheet_no, h.sheet_date, s.supplier_name,
                   COUNT(l.line_id) AS line_count,
                   COALESCE(SUM(l.volume), 0) AS total_volume
              FROM tawrid_crusher_cubing h
              LEFT JOIN tawrid_suppliers s ON s.supplier_id = h.crusher_id
              LEFT JOIN tawrid_crusher_cubing_lines l ON l.cubing_id = h.cubing_id
        """
        group = " GROUP BY h.cubing_id, h.sheet_no, h.sheet_date, s.supplier_name "
        if needle:
            like = f"%{needle}%"
            rows = self._db.fetch_all(
                base
                + " WHERE CAST(h.sheet_no AS TEXT) ILIKE %s OR COALESCE(s.supplier_name, '') ILIKE %s "
                + group
                + " ORDER BY h.sheet_no DESC LIMIT %s",
                [like, like, limit],
            )
        else:
            rows = self._db.fetch_all(
                base + group + " ORDER BY h.sheet_no DESC LIMIT %s", [limit]
            )
        return list(rows)
