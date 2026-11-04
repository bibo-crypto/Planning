"""
machine_timeline.py
Pure logic behind the "Machine Timeline" page (an OrgaTEX-style Gantt of the
dyeing machines).  No Tk here, so it can be tested on its own.

One *block* = one Copertura batch (one Bagno) on one machine:

    machine, start, end, status (done / running / queued),
    bagno, codice, colore, partita, rgb (#rrggbb), label, rows (Situazione rows)

Where the data comes from
  * Copertura  -> which machine, in which order, from when (Batch Start, and
                  Batch End when the export has it);
  * Situazione -> codice / colore / partita / cliente / ... of the Bagno;
  * Produzione -> the dye colour (``Color RGB`` column) of the Partita Colore.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import pandas as pd

from calculate.constants import MACHINE_NUMBER_BY_CODE
from calculate.situazione import (
    _is_elvy_client,
    _parse_delivery_date,
    bagno_key,
    clean_text,
    machine_number_from_label,
)

DEFAULT_BATCH_HOURS = 12.0        # "2 colours per day per machine"
MAX_ESTIMATED_HOURS = 36.0        # an estimated end never runs past the next batch or this
NO_COLOR = "#cbd5e1"              # batch whose colour is not in the Produzione file

_RGB_RE = re.compile(r"(\d{1,3})\D+(\d{1,3})\D+(\d{1,3})")

BLOCK_COLUMNS = [
    "machine", "start", "end", "end_known", "status", "bagno", "codice", "colore",
    "partita", "rgb", "has_color", "label", "planedate", "late", "rows",
]


# ----------------------------------------------------------------------
# Colours
# ----------------------------------------------------------------------
def parse_rgb(value) -> str | None:
    """``RGB(153/133/116)`` (also ``153,133,116``) -> ``#998574``; None when unreadable."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    match = _RGB_RE.search(str(value))
    if not match:
        return None
    red, green, blue = (int(group) for group in match.groups())
    if max(red, green, blue) > 255:
        return None
    return f"#{red:02x}{green:02x}{blue:02x}"


def _channels(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def text_color_for(hex_color: str) -> str:
    """Black or white text, whichever reads better on *hex_color*."""
    red, green, blue = _channels(hex_color)
    luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    return "#111827" if luminance > 150 else "#ffffff"


def blend(hex_color: str, other: str = "#ffffff", amount: float = 0.55) -> str:
    """Mix *hex_color* towards *other* (used to fade finished batches)."""
    r1, g1, b1 = _channels(hex_color)
    r2, g2, b2 = _channels(other)
    mixed = (round(r1 + (r2 - r1) * amount), round(g1 + (g2 - g1) * amount), round(b1 + (b2 - b1) * amount))
    return "#%02x%02x%02x" % mixed


def darker(hex_color: str, amount: float = 0.35) -> str:
    return blend(hex_color, "#000000", amount)


def _norm(value) -> str:
    """Upper-case, single-spaced text with a trailing '.0' (Excel number) removed."""
    text = " ".join(clean_text(value).upper().split())
    return text[:-2] if text.endswith(".0") else text


_REWORK_SUFFIX_RE = re.compile(r"\s*(RI|T\.C)$")


def _code_key(value) -> str:
    """Colour code for matching: no rework suffix ('000417 RI'), no leading zeros of a pure number."""
    text = _REWORK_SUFFIX_RE.sub("", _norm(value))
    return (text.lstrip("0") or "0") if text.isdigit() else text


_partita_key = _norm


class ColorIndex:
    """Where a batch's colour can be found in the Produzione file, most reliable first:

    1. its own Bagno (already dyed -> the exact row);
    2. its Partita Colore;
    3. the same colour dyed before: Codice + Colore, then the Codice alone (a Codice is one RGB: the latest
       Produzione row of that code), then a colour name that only ever had one RGB.
    The file is read oldest -> newest, so the latest row wins for a repeated key.
    """

    def __init__(self, colors_df=None):
        self.by_bagno: dict[str, str] = {}
        self.by_partita: dict[str, str] = {}
        self.by_colour: dict[tuple[str, str], str] = {}
        self.by_codice: dict[str, str] = {}
        self.by_colore: dict[str, str] = {}
        self.names_by_bagno: dict[str, tuple[str, str]] = {}   # bagno -> (codice, colore) as written in Produzione
        self._latest_by_codice: dict[str, str] = {}
        self._by_colore: dict[str, set[str]] = {}
        if colors_df is None or getattr(colors_df, "empty", True):
            return
        size = len(colors_df)
        empty = [""] * size
        columns = (
            colors_df["rgb"], colors_df["partita"] if "partita" in colors_df else empty,
            colors_df["bagno"] if "bagno" in colors_df else empty,
            colors_df["codice"] if "codice" in colors_df else empty,
            colors_df["colore"] if "colore" in colors_df else empty,
        )
        for rgb, partita, bagno, codice, colore in zip(*columns):
            if not rgb:
                continue
            if _norm(partita):
                self.by_partita[_norm(partita)] = rgb
            if _norm(bagno):
                self.by_bagno[_norm(bagno)] = rgb
                self.names_by_bagno[_norm(bagno)] = (clean_text(codice), clean_text(colore))
            if _code_key(codice) and _norm(colore):
                self.by_colour[(_code_key(codice), _norm(colore))] = rgb
            if _code_key(codice):
                self._latest_by_codice[_code_key(codice)] = rgb       # rows run oldest -> newest
            if _norm(colore):
                self._by_colore.setdefault(_norm(colore), set()).add(rgb)
        # A Codice is one colour: the latest Produzione row of that code gives its RGB.
        self.by_codice = dict(self._latest_by_codice)
        # last resort: a colour name that only ever had ONE colour
        self.by_colore = {k: next(iter(v)) for k, v in self._by_colore.items() if len(v) == 1}

    def resolve(self, bagno, rows) -> str | None:
        """Colour of one batch from its Bagno and its Situazione rows (dicts)."""
        rgb = self.by_bagno.get(_norm(bagno))
        if rgb:
            return rgb
        for row in rows:
            rgb = self.by_partita.get(_norm(row.get("partita")))
            if rgb:
                return rgb
        for row in rows:
            rgb = self.by_colour.get((_code_key(row.get("codice")), _norm(row.get("colore"))))
            if rgb:
                return rgb
        for row in rows:                                  # same Codice -> same RGB
            rgb = self.by_codice.get(_code_key(row.get("codice")))
            if rgb:
                return rgb
        for row in rows:                                  # last resort: a colour name with a single RGB
            rgb = self.by_colore.get(_norm(row.get("colore")))
            if rgb:
                return rgb
        return None


def color_lookup(colors_df) -> ColorIndex:
    return ColorIndex(colors_df)


# ----------------------------------------------------------------------
# Machines
# ----------------------------------------------------------------------
def machine_code(machine_number: int) -> str:
    """Delta's 33xx code of a machine number (6 -> '3304')."""
    for code, number in MACHINE_NUMBER_BY_CODE.items():
        if int(number) == int(machine_number):
            return str(code)
    return ""


def machine_row_label(machine_number: int) -> str:
    """Row title as OrgaTEX shows it: ``3304 (MC06)``."""
    code = machine_code(machine_number)
    return f"{code} (MC{int(machine_number):02d})" if code else f"MC{int(machine_number):02d}"


def all_machines() -> list[int]:
    """Every machine of the Master Data table, in number order (3-12 by default)."""
    numbers = sorted({int(n) for n in MACHINE_NUMBER_BY_CODE.values()})
    return numbers or list(range(3, 13))


# ----------------------------------------------------------------------
# Blocks
# ----------------------------------------------------------------------
def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return pd.Timestamp(value).to_pydatetime()
    except (TypeError, ValueError):
        return None


def block_status(start: datetime, end: datetime, now: datetime) -> str:
    """done = already finished (left of the red line), running = on the machine now, queued = to come."""
    if end <= now:
        return "done"
    if start <= now:
        return "running"
    return "queued"


def _parse_planedate(value):
    text = clean_text(value)
    if text.upper().startswith("PROD."):
        text = text[5:].strip()
    return _parse_delivery_date(text)


def delivery_delay_days(planedate, row) -> int | None:
    """Days late after allowing three calendar days for quality checks and invoicing.

    Positive values are late days; zero is exactly on time; negative values are
    the remaining buffer. Elvy's Delivery Date takes priority when valid.
    """
    dye_date = _parse_planedate(planedate)
    if dye_date is None:
        return None

    if _is_elvy_client(row.get("cliente", "")):
        target_date = _parse_delivery_date(row.get("delivery_date"))
        if target_date is None:
            target_date = _parse_delivery_date(row.get("consegna"))
    else:
        target_date = _parse_delivery_date(row.get("consegna"))

    if target_date is None:
        return None
    available_days = (target_date.date() - dye_date.date()).days
    return 3 - available_days


def delivery_delay_text(planedate, row) -> str:
    delay = delivery_delay_days(planedate, row)
    if delay is None:
        return "RITARDO: unavailable (missing valid PlaneDate or delivery date)"
    if delay > 0:
        unit = "day" if delay == 1 else "days"
        return f"RITARDO: late by {delay} {unit}"
    buffer_days = -delay                    # days to spare after the three reserved ones
    unit = "day" if buffer_days == 1 else "days"
    return f"RITARDO: no - on time ({buffer_days} {unit} buffer)"


def build_blocks(situation_df, copertura_df, colors_df=None, now: datetime | None = None,
                 default_hours: float = DEFAULT_BATCH_HOURS) -> pd.DataFrame:
    """Turn Copertura (+ Situazione, + Produzione colours) into the timeline blocks.

    Batches without a start time cannot be placed on a time axis and are skipped.
    A batch's end is, in order: Copertura's own Batch End; else the start of the
    next batch on the machine, but at most ``MAX_ESTIMATED_HOURS`` later; the last
    batch of a machine gets ``default_hours``.
    """
    now = now or datetime.now()
    empty = pd.DataFrame(columns=BLOCK_COLUMNS)
    if copertura_df is None or getattr(copertura_df, "empty", True):
        return empty
    if not {"bagno", "machine", "batch_start"}.issubset(copertura_df.columns):
        return empty

    cop = copertura_df.copy().reset_index(drop=True)
    cop["_machine"] = cop["machine"].map(machine_number_from_label)
    cop["_start"] = cop["batch_start"].map(_to_datetime)
    cop["_end"] = cop["batch_end"].map(_to_datetime) if "batch_end" in cop.columns else None
    cop = cop[cop["_machine"].notna() & cop["_start"].notna()]
    if cop.empty:
        return empty
    cop["_bagno_key"] = cop["bagno"].map(bagno_key)
    cop = cop.sort_values(["_machine", "_start"], kind="stable")

    # Situazione rows grouped by Bagno (a Bagno can carry several order rows)
    rows_by_bagno: dict[str, list[dict]] = {}
    if situation_df is not None and not getattr(situation_df, "empty", True) and "bagno" in situation_df.columns:
        keyed = situation_df.copy()
        keyed["_bagno_key"] = keyed["bagno"].map(bagno_key)
        for key, group in keyed.groupby("_bagno_key", sort=False):
            rows_by_bagno[key] = group.drop(columns="_bagno_key").to_dict("records")

    palette = color_lookup(colors_df)
    delta_default = timedelta(hours=default_hours)
    delta_cap = timedelta(hours=MAX_ESTIMATED_HOURS)

    blocks: list[dict] = []
    for machine, group in cop.groupby("_machine", sort=True):
        records = group.to_dict("records")
        for index, record in enumerate(records):
            start = record["_start"]
            end = record.get("_end")
            end_known = end is not None and end > start
            if not end_known:
                following = records[index + 1]["_start"] if index + 1 < len(records) else None
                if following is not None and following > start:
                    end = min(following, start + delta_cap)
                else:
                    end = start + delta_default
            rows = rows_by_bagno.get(record["_bagno_key"], [])
            first = rows[0] if rows else {}
            bagno = clean_text(record["bagno"])
            rgb = palette.resolve(bagno, rows)
            codice, colore = clean_text(first.get("codice")), clean_text(first.get("colore"))
            if not (codice and colore):                      # Bagno not in Situazione: use Produzione's own names
                known = palette.names_by_bagno.get(_norm(bagno), ("", ""))
                codice, colore = codice or known[0], colore or known[1]
            blocks.append({
                "machine": int(machine),
                "start": start,
                "end": end,
                "end_known": end_known,
                "status": block_status(start, end, now),
                "bagno": bagno,
                "codice": codice,
                "colore": colore,
                "partita": clean_text(first.get("partita")),
                "rgb": rgb or NO_COLOR,
                "has_color": bool(rgb),
                "label": " - ".join(part for part in (codice, colore, bagno) if part),
                "planedate": record.get("planedate"),
                # Worked out once here (not on every redraw): some order row would arrive late.
                "late": any(
                    (delay := delivery_delay_days(record.get("planedate"), order_row)) is not None and delay > 0
                    for order_row in rows
                ),
                "rows": rows,
            })
    return pd.DataFrame(blocks, columns=BLOCK_COLUMNS)


def search_blocks(blocks: pd.DataFrame, text: str) -> list[int]:
    """Row positions of the blocks matching *text* (codice, colore, bagno, partita, cliente, articolo, ordine)."""
    needle = clean_text(text).casefold()
    if not needle or blocks is None or blocks.empty:
        return []
    fields = ("codice", "colore", "bagno", "partita", "cliente", "articolo", "ordine")
    hits = []
    for position, (label_bagno, label_codice, label_colore, label_partita, rows) in enumerate(
        zip(blocks["bagno"], blocks["codice"], blocks["colore"], blocks["partita"], blocks["rows"])
    ):
        haystack = [label_bagno, label_codice, label_colore, label_partita]
        for row in rows:
            haystack.extend(clean_text(row.get(name)) for name in fields)
        if any(needle in clean_text(part).casefold() for part in haystack):
            hits.append(position)
    return hits
