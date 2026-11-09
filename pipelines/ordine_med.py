"""ordine_med.py — "Ordine MED" extraction: turns a raw ORDINE sheet into
the same "Ordine da creare" table Delta's Excel macro produces, plus two
things it didn't have: a raw-yarn availability/shortage check (against
Filato Disponibile stock, including NOTA grg alternative-yarn completion) and automatic Consegna dates assigned by walking
the order top-to-bottom and queuing each color onto its machine using the
same "2 colors/day, Friday off" Copertura logic the rest of the app uses.

Reverse-engineered from the Power Query embedded in the reference
ORDINE_MED-MACRO.xlsm the user sent (see Section1.m: queries 'Ordine',
'PT-GG', 'Filato') and verified field-by-field against its real sheets
(ORDINE, Ordine da creare, Filato Disponibile, تحضير خيط خام).

Follow-up / compatibility notes:
- The exact Prezzo lookup key the macro uses (Colore + a category "type"
  derived from an external Category Colori.xlsx this session doesn't have
  visibility into) -- Prezzo here reuses Biglietti's Articolo+Codice Listini
  lookup, with an article-and-colour-description fallback for MED order
  colour codes that differ from Listini codes.
"""

from __future__ import annotations
from utility.excel_io import safe_save_workbook

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Collection, Mapping

import openpyxl

from exporters.prezzi_workbook import PREZZI_HEADERS, price_cell, write_prezzi_workbook  # noqa: F401 -- PREZZI_HEADERS is re-exported
from exporters.biglietti_exporter import (
    _clean, _get, _key, _number, _prezzo_match_for, _read_sheet_rows,
)  # noqa: F401 -- shared normalization helpers
from calculate.constants import ABBINA_MACHINE_CODES
from utility.column_selection import pick_headers, pick_values, visible_positions
from utility.master_data import raw_articolo_for


# ---------------------------------------------------------------------------
# GRUPPO MACCHINA lookup -- Rocche-per-ABBIN-group total -> the 3300-series
# code this sheet uses (distinct from Biglietti's own M/C machine numbers;
# both derive from the same Rocche-count idea but are separate ERP fields).
# Sourced from constants.py (the single verified table, cross-checked
# against real DFM/Ordine da creare data) plus the MED-only 7-Rocche
# overlap this query alone needs.
# ---------------------------------------------------------------------------
GRUPPO_MACCHINA_TABLE: dict[int, int] = {**ABBINA_MACHINE_CODES, 7: 3301}


def _refresh_gruppo_macchina_table() -> None:
    from calculate import constants as _constants
    GRUPPO_MACCHINA_TABLE.clear()
    GRUPPO_MACCHINA_TABLE.update({**_constants.ABBINA_MACHINE_CODES, 7: 3301})


from calculate import constants as _constants_module  # noqa: E402
from utility.utils import logger
_constants_module.register_machine_listener(_refresh_gruppo_macchina_table)


def _polmoni_multiplier(polmoni_text: str) -> int:
    """'2 POLMONI' -> 8 (2 polmoni * 4 coni each), matching the reference
    query's Custom column."""
    digits = re.sub(r"[^0-9]", "", _clean(polmoni_text))
    return int(digits) * 4 if digits else 0


@dataclass
class OrdineMedRow:
    """One row of the MED order file plus the values computed for it (MC, group, titolo, cliente, commento, prezzo, bagno ...)."""
    riga: int
    code_org: str
    titolo: str
    descr_col: str
    articolo: str
    colore: str
    rocc: int
    abbin: Any
    consegna_input: Any
    pt_grg: str
    pt_med: str
    polmoni: str
    cliente_note: str
    nota_grg: str
    nota_col: str
    kg_note: str
    fabb: Any
    prezz_note: Any
    mc: int = 0
    gruppo_macchina: Any = None
    commento: str = ""
    cliente: str = ""
    data_riconsegna: Any = None
    consegna: Any = None
    prezzo: Any = ""
    livello: Any = ""
    check_articolo: str = ""
    prezzo_plus2: Any = ""
    bagno_reale: str = ""
    bagno_prepostato: str = ""
    _roc_with_polmoni: int = 0


def _normalize_abbin(value: Any) -> Any:
    """ABBIN 0 means "not paired with anything" -- it must never be
    treated as a real group key, or every ABBIN=0 row in the order would
    get grouped (and dyed) together as if they were meant to share a
    batch. Converted to None here, before compute_mc_and_gruppo() ever
    groups by it, so it's handled exactly like a blank ABBIN. Any other
    value, including two different rows that genuinely share the same
    non-zero number, is left untouched -- that's still a real pairing.

    Deliberately not using _number()/_clean() here: _clean() does
    ``str(v or "")``, so a genuine numeric 0 comes back as "" and then
    _number("") is None -- indistinguishable from an already-blank cell,
    which would make this always return the *original* value unchanged
    instead of catching zero.
    """
    if value in (None, ""):
        return None
    try:
        return None if float(value) == 0 else value
    except (TypeError, ValueError):
        return value


def _to_date_value(value: Any) -> Any:
    """CONSEGNA as a real date (midnight datetime) whenever it can be read as one -- text with or
    without a time ("20/10/2026", "2026-10-20 00:00:00"), a date, an Excel serial number.  Blank
    and NaN/NaT (an empty cell read by pandas) -> None; anything unreadable is returned unchanged
    so no information is lost.  (utility/excel_values.py: the one converter every writer shares.)"""
    from utility.excel_values import to_excel_date

    return to_excel_date(value)


def load_ordine(path: Path) -> list[OrdineMedRow]:
    """Read the MED order workbook (sheet ORDINE, else the first sheet) into OrdineMedRow objects, one per row that has an ARTICOLO."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        sheet = "ORDINE" if "ORDINE" in wb.sheetnames else wb.sheetnames[0]
        rows = _read_sheet_rows(wb[sheet])
    finally:
        wb.close()

    out: list[OrdineMedRow] = []
    for i, row in enumerate(rows, start=1):
        articolo = _clean(_get(row, "ARTICOLO"))
        if not articolo:
            continue
        out.append(OrdineMedRow(
            riga=i,
            code_org=_clean(_get(row, "CODE.ORG")),
            titolo=_clean(_get(row, "TITOLO")),
            descr_col=_clean(_get(row, "DESCR COL")),
            articolo=articolo,
            colore=_clean(_get(row, "COLORE")),
            rocc=int(_number(_get(row, "ROCC")) or 0),
            abbin=_normalize_abbin(_get(row, "ABBIN")),
            consegna_input=_to_date_value(_get(row, "CONSEGNA")),
            pt_grg=_clean(_get(row, "PT GRG")),
            pt_med=_clean(_get(row, "PT MED")),
            polmoni=_clean(_get(row, "POLMONI")),
            cliente_note=_clean(_get(row, "cliente")),
            nota_grg=_clean(_get(row, "NOTA grg")),
            nota_col=_clean(_get(row, "NOTA col")),
            kg_note=_clean(_get(row, "KG")),
            fabb=_get(row, "FABB"),
            prezz_note=_get(row, "PREZZ"),
        ))
    if not out:
        raise ValueError('Nessuna riga trovata nel foglio "ORDINE" (colonna ARTICOLO vuota su tutte le righe).')
    return out


def compute_mc_and_gruppo(records: list[OrdineMedRow]) -> None:
    """M/C = Rocche summed across every row sharing the same non-null ABBIN
    (+ Polmoni*4), applied to every row in that group; GRUPPO MACCHINA is
    the fixed lookup off that total."""
    groups: dict[Any, list[OrdineMedRow]] = {}
    for r in records:
        roc = r.rocc + _polmoni_multiplier(r.polmoni)
        r._roc_with_polmoni = roc
        if r.abbin not in (None, ""):
            groups.setdefault(r.abbin, []).append(r)
        else:
            r.mc = roc
            r.gruppo_macchina = GRUPPO_MACCHINA_TABLE.get(roc)
    for abbin, members in groups.items():
        total = sum(m._roc_with_polmoni for m in members)
        gm = GRUPPO_MACCHINA_TABLE.get(total)
        for m in members:
            m.mc = total
            m.gruppo_macchina = gm


def assign_bagno_prepostato(records: list[OrdineMedRow], starting_bagno: str | None) -> None:
    """Assign a bath sequence, retaining only the scheduled row per group.

    The bath counter follows the order rows exactly. Every ABBIN=0 row is
    one independent bath position. Consecutive rows with the same non-zero
    ABBIN form one shared bath group; their colour/machine values must not
    collapse earlier ABBIN=0 positions, which is important for MED's ERP
    numbering. The first row of a shared group is the real bath start and
    remains blank in Bagno Preposato; following rows carry that bath value.
    """
    for record in records:
        record.bagno_reale = ""
        record.bagno_prepostato = ""
    if not starting_bagno:
        return

    match = re.fullmatch(r"\s*([A-Za-z]+)\s*(\d+)\s*", str(starting_bagno))
    if not match:
        raise ValueError("Il primo bagno deve avere il formato, ad esempio, T1200.")
    if not records:
        return
    prefix, number_text = match.groups()
    next_number = int(number_text)

    def has_abbin(value: Any) -> bool:
        if value in (None, ""):
            return False
        try:
            return float(value) != 0
        except (TypeError, ValueError):
            return bool(_clean(value))

    index = 0
    while index < len(records):
        current = records[index]
        abbin = current.abbin
        end = index + 1
        # ABBIN=0 is deliberately a single row. For non-zero ABBIN, only
        # consecutive identical ABBIN values share the bath, preserving one
        # counter step for every preceding order row/group.
        if has_abbin(abbin):
            while end < len(records) and records[end].abbin == abbin:
                end += 1

        bagno = f"{prefix}{next_number}"
        for row in records[index:end]:
            row.bagno_reale = bagno

        # A pre-posted bath is meaningful only for a repeated non-zero ABBIN
        # group. The first row is the bath's real starting row, therefore it
        # remains blank in the ERP Bagno Preposato column.
        if has_abbin(abbin) and end - index > 1:
            for row in records[index + 1:end]:
                row.bagno_prepostato = bagno
        next_number += 1
        index = end


def compute_titolo(records: list[OrdineMedRow], marca_map: dict[str, str]) -> None:
    """Overrides the raw sheet's own (sometimes corrupted -- can literally
    contain a date) Titolo with a lookup off CODE.ORG, same C/G-swap
    fallback Biglietti uses."""
    for r in records:
        art = r.code_org.upper()
        titolo = marca_map.get(art, "")
        if not titolo and art[:1] in ("C", "G"):
            swapped = ("G" if art[:1] == "C" else "C") + art[1:]
            titolo = marca_map.get(swapped, "")
        if titolo:
            r.titolo = titolo


def compute_cliente(records: list[OrdineMedRow]) -> None:
    for r in records:
        code = r.code_org.upper()
        if code.startswith("C130"):
            r.cliente = "3009"
        elif code.startswith("C010") or code.startswith("C011"):
            r.cliente = "3004"
        else:
            r.cliente = ""


def pg_token(pt_grg: Any) -> str:
    """What goes after "PG-" in the Commento for a PT GRG value.

    * blank                         -> "X"          (no raw yarn yet)
    * a number starting with 1      -> unchanged    (one of OUR raw batches,
      e.g. 159233 -> "PG-159233-PM...")
    * any other number              -> "X(<number>)" (the MED customer's own lot,
      e.g. 837756 -> "PG-X(837756)-PM...": the row waits in PG-X; Smart Auto-Assign
      looks the lot up in the stock and our raw batch replaces it)
    * anything that is not a number -> unchanged
    """
    text = _clean(pt_grg).strip()
    if not text:
        return "X"
    if re.fullmatch(r"\d+\.0+", text):          # an Excel float such as 837756.0
        text = text.split(".", 1)[0]
    if not text.isdigit() or text.startswith("1"):
        return text
    return f"X({text})"


def compute_commento(records: list[OrdineMedRow]) -> None:
    """Build every row's ERP Commento: PG-<pg_token>-PM-<PT MED>-<polmoni>-<cliente>-<nota col>
    (the last three cut to 10 characters, empty parts dropped)."""
    for r in records:
        segments = [
            "PG",
            pg_token(r.pt_grg),
            "PM",
            r.pt_med or "X",
            (r.polmoni[:10] if r.polmoni else ""),
            (r.cliente_note[:10] if r.cliente_note else ""),
            (r.nota_col[:10] if r.nota_col else ""),
        ]
        text = "-".join(segments)
        text = re.sub(r"-{2,}", "-", text).rstrip("-")
        r.commento = text


def compute_data_riconsegna(records: list[OrdineMedRow]) -> None:
    for r in records:
        v = r.consegna if r.consegna is not None else r.consegna_input
        try:
            r.data_riconsegna = v - timedelta(days=1)
        except TypeError:
            r.data_riconsegna = None


# ---------------------------------------------------------------------------
# Consegna auto-scheduling: walk the order top-to-bottom, and for every
# machine (GRUPPO MACCHINA -> plain 3-12 number), queue new colors onto
# whatever the machine's *current* Copertura coverage already is.
# ---------------------------------------------------------------------------

def assign_consegna(records: list[OrdineMedRow], machine_totals: dict[int, int]) -> None:
    """machine_totals: {machine_number (3-12): colors_already_queued}, from
    situazione_logic.compute_machine_totals(situation_df, copertura_df) --
    the same baseline the Copertura window itself shows. Schedule delivery
    fourteen days after machine coverage, unless the order already has a later
    requested date. Rows without a machine/date default to fourteen days from today."""
    from calculate.consegna import ConsegnaPlanner

    planner = ConsegnaPlanner(machine_totals)   # the one rule shared with ELVY and Kamal
    for r in records:
        delivery_date = planner.base_date(r.gruppo_macchina)

        requested = _to_date_value(r.consegna_input)
        if isinstance(requested, datetime):
            delivery_date = max(delivery_date, requested.date())
        elif isinstance(requested, date):
            delivery_date = max(delivery_date, requested)
        elif requested not in (None, ""):
            r.consegna = requested
            continue
        r.consegna = datetime.combine(delivery_date, datetime.min.time())


# ---------------------------------------------------------------------------
# Prezzo -- use Biglietti's Listini lookup, falling back to a unique matching
# colour description when the MED order's colour code differs from Listini.
# ---------------------------------------------------------------------------

def compute_prezzo(records: list[OrdineMedRow], price_lookup: dict[tuple, tuple]) -> None:
    for r in records:
        prezzo, _, _, livello = _prezzo_match_for(r.articolo, r.colore, price_lookup)
        if prezzo in ("", None) and r.descr_col:
            description_key = (
                "__ARTICLE_COLOR_DESCRIPTION__",
                _clean(r.articolo).upper(),
                _clean(r.descr_col).casefold(),
            )
            livello, prezzo = price_lookup.get(description_key, (None, None))
        r.prezzo = "" if prezzo is None else prezzo
        r.livello = "" if livello is None else livello


# Machines (by their Rocche-based M/C total) that get a $2 surcharge on
# top of Prezzo. Shared with Situazione's own Prezzo column -- see
# biglietti_exporter.apply_machine_surcharge / PREZZO_SURCHARGE_MACHINES.
def compute_prezzo_plus2(records: list[OrdineMedRow]) -> None:
    """PREZZO + 2$ column: +2 on top of Prezzo for the 3 specific machine
    sizes (56/32/24 Rocche), otherwise the same price carried over as-is."""
    from exporters.biglietti_exporter import apply_machine_surcharge
    for r in records:
        r.prezzo_plus2 = apply_machine_surcharge(r.prezzo, r.mc)


_DFM_PAIRS_CACHE: tuple[str, int, int, set[tuple[str, str]]] | None = None


def load_dfm_articolo_colore(path: Path) -> set[tuple[str, str]]:
    """{(ARTICOLODFM, COLOREDFM)} pairs seen historically in the DFM
    export -- read from the raw DFM sheet directly (not the simplified
    situazione_loaders.load_dfm, which drops the color column), so 'Check
    Articolo' can tell a genuinely new Articolo+Colore combination from one
    that's simply missing a color code.

    Result is cached by (path, mtime_ns, size) so that the 20 000+ row DFM
    file is only re-read when it actually changes on disk -- identical to the
    pattern used by _ARTICOLI_MARCA_CACHE and _PREZZO_LOOKUP_CACHE in
    biglietti_exporter.py."""
    global _DFM_PAIRS_CACHE
    stat = path.stat()
    cache_key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _DFM_PAIRS_CACHE and _DFM_PAIRS_CACHE[:3] == cache_key:
        return _DFM_PAIRS_CACHE[3]

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        sheet = "DFM" if "DFM" in wb.sheetnames else wb.sheetnames[0]
        rows = _read_sheet_rows(wb[sheet])
    finally:
        wb.close()
    pairs: set[tuple[str, str]] = set()
    for row in rows:
        art = _clean(_get(row, "ARTICOLODFM", "Articolo")).upper()
        col = _clean(_get(row, "COLOREDFM", "Colore"))
        if art:
            pairs.add((art, col))

    _DFM_PAIRS_CACHE = (*cache_key, pairs)
    return pairs



def compute_check_articolo(records: list[OrdineMedRow], dfm_pairs: set[tuple[str, str]]) -> None:
    """'NEW' when this Articolo+Colore combination has never been dyed
    before (not found in DFM). Left blank rather than defaulting to 'NEW'
    when no DFM data is available at all, to avoid flagging everything
    as new just because the source wasn't provided."""
    if not dfm_pairs:
        for r in records:
            r.check_articolo = ""
        return
    def normalize_article(value: Any) -> str:
        article = _clean(value).upper()
        return article[1:] if article[:1] in {"C", "G"} else article

    def normalize_colour(value: Any) -> str:
        number = _number(value)
        return str(int(number)) if number is not None and float(number).is_integer() else _clean(value).upper()

    normalized_pairs = {(normalize_article(article), normalize_colour(colour)) for article, colour in dfm_pairs}
    for r in records:
        key = (normalize_article(r.articolo), normalize_colour(r.colore))
        r.check_articolo = "" if key in normalized_pairs else "NEW"


# ---------------------------------------------------------------------------
# Availability / shortage check (the PT-GG query) -- group the order by
# (Articolo, Titolo, PT GRG) summing Rocche, join against Filato
# Disponibile's Mag. Rocche, compute Manca / Disponibilita'.
# ---------------------------------------------------------------------------

_FILATO_DISPONIBILE_CACHE: tuple[str, int, int, dict] | None = None


def load_filato_disponibile(path: Path | None = None) -> dict[int, int]:
    """Return Filato Disponibile from SQLite first; *path* is legacy migration only.

    {PARTITA: Mag.Rocche} -- filters to the same stock semantics as the
    original workbook loader.
    """
    try:
        from utility.source_manager import load as load_source
        frame = load_source("magazino_summary")
        if frame is not None and not frame.empty and {"partita", "mag_rocche"}.issubset(frame.columns):
            out = {}
            for row in frame.itertuples(index=False):
                try:
                    out[int(float(row.partita))] = int(float(row.mag_rocche or 0))
                except (TypeError, ValueError):
                    continue
            return out
    except Exception as _ignored:
        logger.debug("pipelines.ordine_med.load_filato_disponibile: ignored %r", _ignored)
    if path is None or not Path(path).is_file():
        return {}
    """{PARTITA: Mag.Rocche} -- filters to MAGAZZINO in {900160, 900910},
    excludes committed stock (MAGAZZINO=900160 and ORDINE=0), sums COLLI
    per PARTITA. Verified against real data.

    Reads a sheet named 'Filato Disponibile' or 'Magazino' when present
    (this is commonly a multi-sheet workbook shared with other tabs, e.g.
    ORDINE_MED-MACRO.xlsm bundles DFM/ORDINE/Filato Disponibile/etc. in
    one file) -- wb.active is whichever sheet was open when the file was
    last saved, not necessarily this one, so it's only the last resort.

    Result is cached by (path, mtime_ns, size) so repeated Convert clicks
    with the same file skip the Excel parse entirely."""
    global _FILATO_DISPONIBILE_CACHE
    stat = path.stat()
    cache_key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _FILATO_DISPONIBILE_CACHE and _FILATO_DISPONIBILE_CACHE[:3] == cache_key:
        return _FILATO_DISPONIBILE_CACHE[3]

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        sheet_name = next(
            (s for s in wb.sheetnames if _key(s) in (_key("Filato Disponibile"), _key("Magazino"))),
            wb.active.title,
        )
        rows = _read_sheet_rows(wb[sheet_name])
    finally:
        wb.close()
    totals: dict[int, int] = {}
    for row in rows:
        magazzino = _number(_get(row, "MAGAZZINO"))
        if magazzino not in (900160, 900910):
            continue
        ordine = _number(_get(row, "ORDINE"))
        if magazzino == 900160 and (ordine or 0) == 0:
            continue
        partita = _number(_get(row, "PARTITA"))
        if partita is None:
            continue
        colli = _number(_get(row, "COLLI"))
        if colli is None:
            continue
        totals[int(partita)] = totals.get(int(partita), 0) + int(colli)

    _FILATO_DISPONIBILE_CACHE = (*cache_key, totals)
    return totals



@dataclass
class FilatoAvailabilityRow:
    articolo: str
    titolo: str
    pt_grg: int
    rocche: int
    kg: Any
    mag_rocche: Any
    manca: Any
    disponibilita: str
    completamento_pt_1: int | None = None
    completamento_rocche_1: int | None = None
    completamento_pt_2: int | None = None
    completamento_rocche_2: int | None = None


@dataclass
class FilatoInventory:
    stock_by_partita: dict[int, int]
    stock_by_article_partita: dict[tuple[str, int], int]
    lotto_by_partita: dict[int, str]


_NOTA_GRG_NUMBER_RE = re.compile(r"\d+(?:\.0+)?")


def _alternative_pt_grg(nota_grg: str) -> list[int]:
    """Return distinct numeric yarn references in NOTA grg."""
    alternatives: list[int] = []
    for value in _NOTA_GRG_NUMBER_RE.findall(nota_grg):
        pt_grg = int(float(value))
        if pt_grg not in alternatives:
            alternatives.append(pt_grg)
    return alternatives


def load_filato_inventory(path: Path | None = None) -> FilatoInventory:
    """Load available yarn by article/Partita and the Partita-to-Lotto relation."""
    from utility.source_manager import load as load_source

    frame = load_source("magazino_summary")
    if frame is None or frame.empty or not {"articolo", "partita", "mag_rocche"}.issubset(frame.columns):
        frame = None
    if frame is None and path is not None and Path(path).is_file():
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        try:
            sheet_name = next(
                (s for s in wb.sheetnames if _key(s) in (_key("Filato Disponibile"), _key("Magazino"))),
                wb.active.title,
            )
            rows = _read_sheet_rows(wb[sheet_name])
        finally:
            wb.close()
        import pandas as pd

        stock_rows = []
        for row in rows:
            warehouse = _number(_get(row, "MAGAZZINO"))
            order = _number(_get(row, "ORDINE"))
            partita = _number(_get(row, "PARTITA"))
            quantity = _number(_get(row, "COLLI"))
            if warehouse is not None:
                if warehouse not in (900160, 900910) or (warehouse == 900160 and (order or 0) == 0):
                    continue
            else:
                quantity = _number(_get(row, "MAG.ROCCHE", "MAG ROCCHE"))
            if partita is None or quantity is None:
                continue
            stock_rows.append({
                "articolo": _clean(_get(row, "ARTICOLO")),
                "partita": int(partita),
                "mag_rocche": quantity,
            })
        frame = pd.DataFrame(stock_rows)

    stock_by_partita: dict[int, int] = {}
    stock_by_article_partita: dict[tuple[str, int], int] = {}
    if frame is not None:
        for row in frame.itertuples(index=False):
            try:
                partita = int(float(row.partita))
                quantity = int(float(row.mag_rocche or 0))
            except (TypeError, ValueError):
                continue
            article = _clean(getattr(row, "articolo", "")).upper()
            stock_by_partita[partita] = stock_by_partita.get(partita, 0) + quantity
            key = (article, partita)
            stock_by_article_partita[key] = stock_by_article_partita.get(key, 0) + quantity

    lotto_by_partita: dict[int, str] = {}
    lotti = load_source("lotti_summary")
    if lotti is not None and not lotti.empty and {"partita", "lotto"}.issubset(lotti.columns):
        for row in lotti.itertuples(index=False):
            try:
                partita = int(float(row.partita))
            except (TypeError, ValueError):
                continue
            lotto = _clean(row.lotto)
            if lotto:
                lotto_by_partita[partita] = lotto

    return FilatoInventory(stock_by_partita, stock_by_article_partita, lotto_by_partita)


def compute_filato_availability(
    records: list[OrdineMedRow],
    densita_map: dict[int, dict[str, Any]] | None,
    stock_map: dict[int, int] | FilatoInventory,
    lotto_by_partita: dict[int, str] | None = None,
) -> list[FilatoAvailabilityRow]:
    """Groups by (ARTICOLO with C->G swap, PT GRG) -- Titolo intentionally
    excluded from the key so that minor Titolo variations across rows for the
    same raw-yarn batch never split that batch into two separate groups.
    The first-seen Titolo for each (art_g, pt_grg) pair is kept for display.
    Sums Rocche, computes Kg via Densita' Query's peso_net when available
    (same source Biglietti's KG uses), joins Mag.Rocche from Filato Disponibile."""
    densita_map = densita_map or {}
    if isinstance(stock_map, FilatoInventory):
        inventory = stock_map
        stock_by_partita = inventory.stock_by_partita
        stock_by_article_partita = inventory.stock_by_article_partita
        lotto_by_partita = inventory.lotto_by_partita
    else:
        stock_by_partita = stock_map
        stock_by_article_partita = {}
        lotto_by_partita = lotto_by_partita or {}
    groups: dict[tuple, dict[str, Any]] = {}
    for r in records:
        try:
            pt_grg = int(_number(r.pt_grg))
        except (TypeError, ValueError):
            continue
        art_g = raw_articolo_for(r.articolo) if r.articolo[:1].upper() == "C" else r.articolo
        # Key: (art_g, pt_grg) only -- Titolo is stored on first-seen and NOT
        # used as a discriminator, preventing the same batch from being counted
        # twice when different order rows carry slightly different Titolo text.
        key = (art_g, pt_grg)
        if key not in groups:
            groups[key] = {"rocche": 0, "titolo": r.titolo, "records": []}
        groups[key]["rocche"] += r.rocc  # Q.TA only — POLMONI is machine overhead, not raw-yarn demand
        groups[key]["records"].append(r)

    def available_for(article: str, partita: int) -> int:
        key = (article.upper(), partita)
        if stock_by_article_partita:
            return stock_by_article_partita.get(key, 0)
        return stock_by_partita.get(partita, 0)

    def has_stock_entry(article: str, partita: int) -> bool:
        if stock_by_article_partita:
            return (article.upper(), partita) in stock_by_article_partita
        return partita in stock_by_partita

    # Non-1 PT GRG values are customer lots, not warehouse raw-yarn Partitas.
    # Keep one only when Magazino Filato confirms that this raw yarn is in stock.
    groups = {
        key: group for key, group in groups.items()
        if str(key[1]).startswith("1") or available_for(key[0], key[1]) > 0
    }

    primary_demand_by_pt: dict[tuple[str, int], int] = {}
    for (article, pt_grg), group in groups.items():
        key = (article.upper(), pt_grg)
        primary_demand_by_pt[key] = primary_demand_by_pt.get(key, 0) + group["rocche"]
    remaining_stock = {
        key: max(available_for(*key) - demand, 0)
        for key, demand in primary_demand_by_pt.items()
    }

    out: list[FilatoAvailabilityRow] = []
    for (art_g, pt_grg), g in groups.items():
        rocche = g["rocche"]
        titolo = g["titolo"]
        peso_net = densita_map.get(pt_grg, {}).get("peso_net")
        kg = round(peso_net * rocche, 2) if peso_net is not None else None
        mag_rocche = available_for(art_g, pt_grg) if has_stock_entry(art_g, pt_grg) else None
        manca = (mag_rocche - rocche) if mag_rocche is not None else None
        disponibilita = "OK" if (mag_rocche is not None and mag_rocche >= rocche) else "NO"
        completions: list[tuple[int, int]] = []
        shortage = max(rocche - int(mag_rocche or 0), 0)
        candidates: list[int] = []
        for record in g["records"]:
            for candidate in _alternative_pt_grg(record.nota_grg):
                if candidate != pt_grg and candidate not in candidates:
                    candidates.append(candidate)
        if not candidates and lotto_by_partita.get(pt_grg):
            primary_lotto = lotto_by_partita[pt_grg]
            candidates = [
                candidate_partita
                for candidate_article, candidate_partita in stock_by_article_partita
                if candidate_article == art_g.upper()
                and candidate_partita != pt_grg
                and lotto_by_partita.get(candidate_partita) == primary_lotto
            ]
        for candidate in candidates:
            if shortage <= 0 or len(completions) == 2:
                break
            candidate_key = (art_g.upper(), candidate)
            available = remaining_stock.get(candidate_key)
            if available is None:
                available = max(
                    available_for(art_g, candidate) - primary_demand_by_pt.get(candidate_key, 0),
                    0,
                )
            assigned = min(shortage, available)
            if assigned:
                completions.append((candidate, assigned))
                remaining_stock[candidate_key] = available - assigned
                shortage -= assigned
        completion_values = [value for pair in completions for value in pair]
        completion_values.extend([None] * (4 - len(completion_values)))
        out.append(FilatoAvailabilityRow(
            art_g, titolo, pt_grg, rocche, kg, mag_rocche, manca, disponibilita,
            *completion_values,
        ))
    out.sort(key=lambda x: x.pt_grg)
    return out


# ---------------------------------------------------------------------------
# Export -- two sheets: "Ordine da creare" (the full computed table, plus a
# ready-to-import CLIENTE..GRUPPO MACCHINA slice) and "Filato X Tinturia"
# (the availability/shortage table).
# ---------------------------------------------------------------------------

# The full field set, used to build the system-import slice
# ("Dati sistema", CLIENTE..GRUPPO MACCHINA).
FULL_ROW_HEADERS = [
    "Riga", "CLIENTE", "ARTICOLO", "COLORE", "Q.TA", "CONSEGNA", "COMMENTO",
    "LAVORANTE", "LAV. SUCC", "DATA RICONSEGNA", "MAG. GREGGIO",
    "SIGLA DISPOSIZIONE", "BAGNO PREPOSTO", "GRUPPO MACCHINA",
    "TITOLO", "DESCR COL", "LIVELLO", "ABBIN", "M/C", "PREZZO",
    "PT GRG", "PT MED", "POLMONI", "Cliente MED", "NOTA grg", "NOTA col",
]

# The system-import slice: CLIENTE .. GRUPPO MACCHINA (columns B-N in the
# reference sheet's own layout, "Riga" excluded).
SYSTEM_IMPORT_HEADERS = FULL_ROW_HEADERS[1:14]

# "Ordine da creare"'s own display columns -- CLIENTE, COMMENTO and the
# fixed ERP constants (LAVORANTE..GRUPPO MACCHINA) live only in "Dati
# sistema" now; this sheet adds Check Articolo (after M/C) and
# PREZZO + 2$ (after PREZZO) instead.
ORDINE_DA_CREARE_HEADERS = [
    "Riga", "ARTICOLO", "COLORE", "Q.TA", "CONSEGNA", "DATA RICONSEGNA",
    "TITOLO", "DESCR COL", "LIVELLO", "ABBIN", "M/C", "Check Articolo",
    "PREZZO", "PREZZO + 2$",
    "PT GRG", "PT MED", "POLMONI", "Cliente MED", "NOTA grg", "NOTA col",
]

FILATO_AVAILABILITY_HEADERS = [
    "Articolo", "Titolo", "PT GRG", "Rocche", "Kg", "Mag. Rocche", "Manca", "Disponibilita'",
    "Custom", "تكمله من خام", "عدد.", "تكمله من خام..", "عدد..",
]


def _full_row(r: OrdineMedRow) -> dict[str, Any]:
    return dict(zip(FULL_ROW_HEADERS, [
        r.riga, r.cliente, r.articolo, r.colore, r.rocc, r.consegna, r.commento,
        900901, 900161, r.data_riconsegna, 900923, "D", r.bagno_prepostato, r.gruppo_macchina,
        r.titolo, r.descr_col, r.livello, r.abbin, r.mc, r.prezzo,
        r.pt_grg, r.pt_med, r.polmoni, r.cliente_note, r.nota_grg, r.nota_col,
    ]))


# Column type of every "Dati sistema" / ERP column -- the ERP import template
# (same one Elvy and Kamal fill) wants real numbers and real dates, not text
# that merely looks like them.
SYSTEM_COLUMN_TYPES: dict[str, str] = {
    "CLIENTE": "integer",
    "ARTICOLO": "text",
    "COLORE": "code",          # number when it is one, text otherwise (A12, 007)
    "Q.TA": "integer",
    "CONSEGNA": "date",
    "COMMENTO": "text",
    "LAVORANTE": "integer",
    "LAV. SUCC": "integer",
    "DATA RICONSEGNA": "date",
    "MAG. GREGGIO": "integer",
    "SIGLA DISPOSIZIONE": "text",
    "BAGNO PREPOSTO": "text",
    "GRUPPO MACCHINA": "integer",
}


def _as_int_or_none(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = _clean(value).replace(",", ".")
    try:
        return int(float(text))
    except ValueError:
        return value  # not numeric at all: keep it visible as text


def _as_code(value: Any) -> Any:
    """Numeric codes become numbers; a leading zero or any letter keeps the
    value as text (007 -> 7 would no longer be the same colour code)."""
    text = _clean(value)
    if not text:
        return None
    if re.fullmatch(r"-?[1-9]\d*(\.0+)?|0", text):
        return int(float(text))
    return text


def _as_date_cell(value: Any) -> Any:
    converted = _to_date_value(value)
    return converted


def _system_value(header: str, value: Any) -> Any:
    kind = SYSTEM_COLUMN_TYPES.get(header, "text")
    if kind == "integer":
        return _as_int_or_none(value)
    if kind == "code":
        return _as_code(value)
    if kind == "date":
        return _as_date_cell(value)
    return None if value in (None, "") else str(value)


def system_row(r: "OrdineMedRow", headers: list[str] | None = None) -> list[Any]:
    """CLIENTE..GRUPPO MACCHINA (or only ``headers`` of them) with every value in its proper Excel type."""
    full = _full_row(r)
    return [_system_value(header, full[header]) for header in (headers or SYSTEM_IMPORT_HEADERS)]


def _apply_system_formats(ws) -> None:
    """Number formats that match the types: whole numbers as "0", dates as
    dd/mm/yyyy, text columns as text (so a bath like T1201 stays text)."""
    header = [c.value for c in ws[1]]
    for col_idx, name in enumerate(header, start=1):
        kind = SYSTEM_COLUMN_TYPES.get(name)
        if kind is None:
            continue
        fmt = {"integer": "0", "code": "General", "date": "dd/mm/yyyy", "text": "@"}[kind]
        for row_idx in range(2, ws.max_row + 1):
            ws.cell(row=row_idx, column=col_idx).number_format = fmt


def _ordine_da_creare_row(r: OrdineMedRow) -> list[Any]:
    return [
        r.riga, r.articolo, r.colore, r.rocc, r.consegna, r.data_riconsegna,
        r.titolo, r.descr_col, r.livello, r.abbin, r.mc, r.check_articolo,
        r.prezzo, r.prezzo_plus2,
        r.pt_grg, r.pt_med, r.polmoni, r.cliente_note, r.nota_grg, r.nota_col,
    ]


def _prezzi_row(r: OrdineMedRow) -> list[Any]:
    """One row of the Prezzi sheet for a MED order line."""
    return [
        r.riga, r.articolo, r.titolo, r.colore, r.rocc, r.descr_col,
        r.livello, r.mc, price_cell(r.prezzo), price_cell(r.prezzo_plus2),
    ]


PREZZI_FILE_STEM = "Prezzi Ordine Med"


def next_prezzi_path(folder: Path) -> Path:
    """``Prezzi Ordine Med <n>.xlsx`` in ``folder``, n being one more than the highest number there.

    Each order keeps its own price file: a new order never overwrites an earlier one."""
    pattern = re.compile(rf"^{re.escape(PREZZI_FILE_STEM)}\s+(\d+)\.xlsx$", re.IGNORECASE)
    taken = [int(m.group(1)) for p in folder.glob(f"{PREZZI_FILE_STEM}*.xlsx") if (m := pattern.match(p.name))] if folder.is_dir() else []
    return folder / f"{PREZZI_FILE_STEM} {max(taken, default=0) + 1}.xlsx"


def export_prezzi_workbook(
    path: Path, records: list[OrdineMedRow], hidden_columns: Collection[str] | None = None,
) -> None:
    """Write the Prezzi file ("Prezzi Ordine Med <n>.xlsx") for the MED order (layout: exporters.prezzi_workbook).

    hidden_columns: Prezzi columns switched off in the column picker."""
    write_prezzi_workbook(path, [_prezzi_row(record) for record in records], hidden_columns=hidden_columns)


def export_erp_order_workbook(path: Path, records: list[OrdineMedRow]) -> None:
    """Write the ERP-ready CLIENTE..GRUPPO MACCHINA sheet separately."""
    from openpyxl import Workbook
    from exporters.master_formats import apply_erp_master_format

    wb = Workbook()
    ws = wb.active
    ws.title = "Dati sistema (B-N)"
    ws.append(SYSTEM_IMPORT_HEADERS)
    for record in records:
        ws.append(system_row(record))
    # The ERP master formatter owns all styling; generic Biglietti styles leave
    # unrelated style records in this workbook.
    apply_erp_master_format(ws)   # the master file's look (exporters/master_formats.py); values untouched
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_save_workbook(wb, path, keep_backup=False)
    wb.close()


def export_filato_availability_workbook(
    path: Path,
    availability: list[FilatoAvailabilityRow],
    source_path: Path | None = None,
) -> None:
    """Write the availability result as a standalone ERP-support workbook."""
    import copy
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font
    from exporters.biglietti_exporter import style_sheet

    wb = Workbook()
    ws = wb.active
    ws.title = "Filato X Tinturia"
    exported_headers = FILATO_AVAILABILITY_HEADERS[:5] + ["Custom"] + FILATO_AVAILABILITY_HEADERS[9:]
    ws.append(exported_headers)
    for row in availability:
        ws.append([
            row.articolo, row.titolo, row.pt_grg, row.rocche, row.kg,
            "تحضير خام",
            row.completamento_pt_1, row.completamento_rocche_1,
            row.completamento_pt_2, row.completamento_rocche_2,
        ])
    style_sheet(ws)
    if source_path is not None and source_path.is_file():
        source_wb = load_workbook(source_path)
        try:
            source_ws = next(
                (sheet for sheet in source_wb.worksheets if _key(sheet.title) == _key("Filato X Tinturia")),
                None,
            )
            if source_ws is not None:
                source_columns = {cell.value: cell.column for cell in source_ws[1]}
                for target_column, header in enumerate(exported_headers, start=1):
                    source_column = source_columns.get(header)
                    if source_column is None:
                        continue
                    for target_row in range(1, ws.max_row + 1):
                        source_cell = source_ws.cell(target_row, source_column)
                        target_cell = ws.cell(target_row, target_column)
                        if source_cell.has_style:
                            target_cell.font = copy.copy(source_cell.font)
                            target_cell.fill = copy.copy(source_cell.fill)
                            target_cell.border = copy.copy(source_cell.border)
                            target_cell.alignment = copy.copy(source_cell.alignment)
                            target_cell.protection = copy.copy(source_cell.protection)
                            target_cell.number_format = source_cell.number_format
                    source_letter = source_ws.cell(1, source_column).column_letter
                    ws.column_dimensions[ws.cell(1, target_column).column_letter].width = (
                        source_ws.column_dimensions[source_letter].width
                    )
                ws.freeze_panes = source_ws.freeze_panes
        finally:
            source_wb.close()
    for row_index in range(2, ws.max_row + 1):
        custom_cell = ws.cell(row_index, 6)
        custom_cell.font = copy.copy(custom_cell.font) + Font(bold=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_save_workbook(wb, path, keep_backup=False)
    wb.close()


def export_ordine_med_workbook(
    path: Path,
    records: list[OrdineMedRow],
    availability: list[FilatoAvailabilityRow],
    hidden_columns: Mapping[str, Collection[str]] | None = None,
) -> None:
    """Write the Ordine MED workbook and save it (no backup kept).

    Three styled sheets: "Ordine da creare", the system-import sheet
    "Dati sistema (B-N)", and "Filato X Tinturia" where every row whose
    Disponibilita' is NO is shown in red.

    hidden_columns ({sheet title: labels}) leaves out the columns switched off in the
    column picker; nothing hidden (the default) writes every column.
    """
    from openpyxl import Workbook
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.styles import PatternFill
    from exporters.biglietti_exporter import style_sheet

    hidden_columns = hidden_columns or {}
    wb = Workbook()

    ws = wb.active
    ws.title = "Ordine da creare"
    creare_hidden = hidden_columns.get("Ordine da creare")
    creare_shown = visible_positions(ORDINE_DA_CREARE_HEADERS, creare_hidden)
    ws.append(pick_headers(ORDINE_DA_CREARE_HEADERS, creare_hidden))
    for r in records:
        ws.append(pick_values(_ordine_da_creare_row(r), creare_shown))
    style_sheet(ws, date_columns=("CONSEGNA", "DATA RICONSEGNA"))
    _style_ordine_da_creare_extras(ws)

    ws2 = wb.create_sheet("Dati sistema (B-N)")
    system_headers = pick_headers(SYSTEM_IMPORT_HEADERS, hidden_columns.get("Dati sistema (B-N)"))
    ws2.append(system_headers)
    for r in records:
        ws2.append(system_row(r, system_headers))
    style_sheet(ws2, date_columns=("CONSEGNA", "DATA RICONSEGNA"))
    _apply_system_formats(ws2)

    ws3 = wb.create_sheet("Filato X Tinturia")
    filato_hidden = hidden_columns.get("Filato X Tinturia")
    filato_shown = visible_positions(FILATO_AVAILABILITY_HEADERS, filato_hidden)
    filato_headers = pick_headers(FILATO_AVAILABILITY_HEADERS, filato_hidden)
    ws3.append(filato_headers)
    for a in availability:
        ws3.append(pick_values(
            [
                a.articolo, a.titolo, a.pt_grg, a.rocche, a.kg, a.mag_rocche, a.manca, a.disponibilita,
                "تحضير خام", a.completamento_pt_1, a.completamento_rocche_1,
                a.completamento_pt_2, a.completamento_rocche_2,
            ],
            filato_shown,
        ))
    style_sheet(ws3)
    # Highlight shortages (Disponibilita' = NO) in red.
    if ws3.max_row > 1:
        red_fill = PatternFill(start_color="FFFFC7CE", end_color="FFFFC7CE", fill_type="solid")
        if "Disponibilita'" in filato_headers:
            # Live rule on the Disponibilita' column, wherever it sits now.
            dispo = ws3.cell(row=1, column=filato_headers.index("Disponibilita'") + 1).column_letter
            ws3.conditional_formatting.add(
                f"A2:{ws3.cell(row=1, column=len(filato_headers)).column_letter}{ws3.max_row}",
                FormulaRule(formula=[f'${dispo}2="NO"'], fill=red_fill, stopIfTrue=False),
            )
        else:
            # The column itself is switched off: the shortage rows are still marked.
            for offset, a in enumerate(availability, start=2):
                if a.disponibilita == "NO":
                    for cell in ws3[offset]:
                        cell.fill = red_fill

    path.parent.mkdir(parents=True, exist_ok=True)
    safe_save_workbook(wb, path, keep_backup=False)
    wb.close()


def _style_ordine_da_creare_extras(ws) -> None:
    """The bespoke formatting "Ordine da creare" needs beyond the shared
    style_sheet borders/banding: Check Articolo highlighted red when
    'NEW', LIVELLO solid red throughout, ABBIN duplicates highlighted
    green, and the PREZZO + 2$ header given a distinct fill so it reads
    as a derived column rather than raw input."""
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.styles import Font, PatternFill

    header = [c.value for c in ws[1]]
    last_row = ws.max_row
    if last_row <= 1:
        return

    def col_letter(name: str) -> str | None:
        return ws.cell(row=1, column=header.index(name) + 1).column_letter if name in header else None

    red_fill = PatternFill(start_color="FFFFC7CE", end_color="FFFFC7CE", fill_type="solid")
    green_fill = PatternFill(start_color="FFC6EFCE", end_color="FFC6EFCE", fill_type="solid")

    check_col = col_letter("Check Articolo")
    if check_col:
        rng = f"{check_col}2:{check_col}{last_row}"
        ws.conditional_formatting.add(rng, FormulaRule(formula=[f'{check_col}2="NEW"'], fill=red_fill, stopIfTrue=False))

    livello_col = col_letter("LIVELLO")
    if livello_col:
        col_idx = header.index("LIVELLO") + 1
        for r in range(2, last_row + 1):
            ws.cell(row=r, column=col_idx).fill = red_fill

    abbin_col = col_letter("ABBIN")
    if abbin_col:
        rng = f"{abbin_col}2:{abbin_col}{last_row}"
        formula = f'AND({abbin_col}2<>"",COUNTIF(${abbin_col}$2:${abbin_col}${last_row},{abbin_col}2)>1)'
        ws.conditional_formatting.add(rng, FormulaRule(formula=[formula], fill=green_fill, stopIfTrue=False))

    plus2_col = col_letter("PREZZO + 2$")
    if plus2_col:
        header_cell = ws.cell(row=1, column=header.index("PREZZO + 2$") + 1)
        header_cell.fill = PatternFill(start_color="FFED7D31", end_color="FFED7D31", fill_type="solid")
        header_cell.font = Font(bold=True, color="FFFFFFFF")
