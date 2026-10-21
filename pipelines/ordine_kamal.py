"""
ordine_kamal.py
Builds "Ordine Kamal" rows from parsed Kamal order-letter rows
(kamal_parser.KamalOrderRow), matching each colour's Articolo (C170xxxx)
via its Titolo ("نمرة الغزل") against the DFM reference -- Kamal's PDFs
don't carry an Article No column the way Elvy's do.

Column structure mirrors OrdiniElvyRow exactly (same order, same fixed
defaults) with only CLIENTE changed to Kamal's code -- COLORE holds the
COLOREDFM code, same convention as Elvy's own "COLORE" column, not a text
colour name.

COMMENTO format (legacy): "PG-X-ORD.nr.<year>(LETTER <reply no>)".
When the operator enables the optional order number, the format becomes
"PG-X-ORD.Nr.<order no>-<year>-(LETTER <reply no>)". X gets replaced with
the matched raw yarn Partita the same way as Elvy orders, via
ordini_elvy.match_raw_yarn().
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re

from calculate.abbina_calculator import MACHINE_CODES, _smallest_fitting_machine, split_into_batches
from calculate.bagno import sequence_bagno
from parsers.dfm_lookup import find_articolo_by_titolo, lookup_dfm_color_by_name
from parsers.kamal_parser import KamalOrderRow
from pipelines.ordini_elvy import (
    CONSEGNA_LEAD_DAYS,
    LAVORANTE_CODE,
    LAVORANTE_SUCCESSIVO_CODE,
    SIGLA_DISPO_CODE,
    STOCK_MAG_CODE,
)
from utility.utils import clean_text, logger

CLIENTE_CODE = 3017
KAMAL_ARTICLE_PREFIX = "C170"


@dataclass
class OrdineKamalRow:
    """One derived row for the "Ordine Kamal" sheet -- same column set as
    OrdiniElvyRow, same order, same fixed-field defaults."""
    cliente: int = CLIENTE_CODE
    articolo_delta: str = ""
    coloredfm: str = ""            # "COLORE" column -- the COLOREDFM code, same as Elvy
    peso_kg: float = 0.0           # "Q.TA" column -- weight in kg for Kamal (agreed)
    data_consegna: datetime | None = None
    commento: str = ""
    abbina: str = ""
    lavorante: int = LAVORANTE_CODE
    lavorante_successivo: int = LAVORANTE_SUCCESSIVO_CODE
    data_riconsegna: datetime | None = None
    stock_mag: int = STOCK_MAG_CODE
    sigla_dispo: str = SIGLA_DISPO_CODE
    bagno_proposto: str = ""
    macchina: int | None = None
    sender_msg_no: str = ""        # "رقم رسالة الخام" -- used to match Lotto in LOTTI
    batch_no: int = 0              # machine batch of its colour group (0 = first)
    colore_name: str = ""          # "اللون" -- Kamal's own colour label, used as the
                                    # GRUPPO MACCHINA grouping key when COLOREDFM is blank
    titolo: str = ""               # yarn count; grouped by /1 versus /2 class
    order_no: str = ""              # optional operator-supplied order number

    @property
    def quantity_cones(self) -> float:
        """Compatibility alias for the shared ERP writer/matching helpers.

        Kamal requests are measured in kilograms, but the common Ordini
        helpers use ``quantity_cones`` as their quantity field.  Exposing the
        alias keeps the shared header mapping intact without changing the
        Kamal workbook's public ``peso_kg`` field.
        """
        return self.peso_kg


def _titolo_group(value: str) -> str:
    """Return the machine-group class for a Kamal yarn count.

    Kamal's rule is based on the number of plies, not the full yarn count:
    ``50/1``, ``96/1`` and ``70/1`` may share a colour machine, while any
    ``/2`` count belongs to a separate group.  Unknown formats remain exact
    values so they are never merged accidentally.
    """
    normalised = re.sub(r"\s+", "", clean_text(value)).casefold()
    match = re.search(r"/(1|2)$", normalised)
    if match:
        return f"plies/{match.group(1)}"
    return f"exact/{normalised}"


def _machine_group_key(row: OrdineKamalRow) -> tuple[str, str, str] | None:
    """
    Grouping key used to sum weight and pick a machine for GRUPPO MACCHINA.

    COLOREDFM plus the Titolo ply class is the primary key. When a row has no COLOREDFM (blank),
    fall back to grouping by Colore ("اللون", Kamal's own colour label)
    plus the Titolo ply class instead of skipping the row -- rows sharing the
    same Colore and ply class still get their Peso (kg) summed together and rounded to one
    machine; a group that appears on its own is rounded using its own weight. Rows
    with neither COLOREDFM nor Colore have no grouping key and are left
    unassigned. This deliberately prevents, for example, 50/1 and 100/2
    from sharing a machine even when their colour code is identical.
    """
    color = clean_text(row.coloredfm)
    titolo = _titolo_group(row.titolo)
    if color:
        return ("coloredfm", color, titolo)
    colore = clean_text(row.colore_name)
    if colore:
        return ("colore", colore, titolo)
    return None


def assign_ordine_kamal_machines(rows: list[OrdineKamalRow]) -> None:
    """Assign GRUPPO MACCHINA consistently for workbook and ERP exports."""
    # Rows of one colour are filled into machine batches in order: a batch never
    # exceeds the largest machine, so a colour whose total is bigger than that
    # is split over several machines instead of overfilling one.
    members: dict[tuple[str, str, str], list[OrdineKamalRow]] = {}
    for row in rows:
        key = _machine_group_key(row)
        if key is not None:
            members.setdefault(key, []).append(row)

    for group in members.values():
        batch_ids = split_into_batches([r.peso_kg for r in group])
        for batch in sorted(set(batch_ids)):
            batch_rows = [r for r, b in zip(group, batch_ids) if b == batch]
            capacity = _smallest_fitting_machine(sum(r.peso_kg or 0.0 for r in batch_rows))
            for r in batch_rows:
                r.macchina = MACHINE_CODES.get(capacity)
                r.abbina = f"Machine {capacity} Cones"
                r.batch_no = batch


def assign_bagno_prepostato(rows: list[OrdineKamalRow], first_bagno: str | None) -> None:
    """Fill BAGNO PREPOSTO from the operator's "First bagno" (e.g. "T1200").

    Same principle as Ordine MED, with Kamal's own grouping: every row that
    shares a COLOREDFM (or, when that is blank, the same Colore) is dyed in
    ONE machine batch -- wherever it sits in the letter -- so that is one
    bath.  Baths are numbered in order of first appearance; the first row of
    a bath stays blank (the ERP numbers it) and every further row carries
    the bath number.  A row with neither COLOREDFM nor Colore has no machine
    batch, so it is a bath of its own (takes one number, stays blank).

    Call it AFTER assign_ordine_kamal_machines(), so both use the same key.
    An empty first_bagno clears the column; a malformed one raises ValueError.
    """
    values = sequence_bagno(
        [None if _machine_group_key(r) is None else (_machine_group_key(r), r.batch_no) for r in rows],
        first_bagno,
    )
    for row, value in zip(rows, values):
        row.bagno_proposto = value


def resolve_kamal_colours(rows: list[KamalOrderRow], dfm_c170_entries: list[dict]) -> int:
    """Look every row's colour NAME up in the DFM (C170) and, when found, take
    COLOREDFM and the colour name from DFM -- in place, so the raw sheet, the
    Ordine Kamal sheet and the ERP file all agree.

    Not found: the PDF's own name stays, and COLOREDFM stays as the PDF gave it
    (blank in practice) for manual entry -- nothing is guessed.  Safe to call
    twice: a name already taken from DFM resolves to itself.
    Returns how many rows were resolved from DFM.
    """
    resolved = 0
    missing: list[str] = []
    for r in rows:
        name = clean_text(r.colore_name)
        if not name:
            continue
        articolo = find_articolo_by_titolo(dfm_c170_entries, r.titolo) if r.titolo else ""
        code, dfm_name = lookup_dfm_color_by_name(name, dfm_c170_entries, articolo)
        if code:
            r.coloredfm, r.colore_name = code, dfm_name
            resolved += 1
        elif name not in missing:
            missing.append(name)
    if missing:
        logger.warning("Ordine Kamal: %d colour name(s) not found in DFM: %s", len(missing), ", ".join(missing))
    return resolved


def build_ordine_kamal_rows(
    rows: list[KamalOrderRow],
    dfm_c170_entries: list[dict],
    order_no: str | None = None,
) -> list[OrdineKamalRow]:
    """
    dfm_c170_entries: dfm_lookup.load_dfm_entries_by_prefix("C170") --
    passed in rather than loaded here so the caller only loads it once per
    conversion run.
    """
    resolve_kamal_colours(rows, dfm_c170_entries)

    # Dates are written as real Excel dates -- midnight, no time of day.
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    data_consegna_dt = today + timedelta(days=CONSEGNA_LEAD_DAYS)
    data_riconsegna_dt = data_consegna_dt - timedelta(days=1)

    out: list[OrdineKamalRow] = []
    unmatched = 0

    for r in rows:
        articolo = find_articolo_by_titolo(dfm_c170_entries, r.titolo) if r.titolo else ""
        if r.titolo and not articolo:
            unmatched += 1

        year = _extract_year(r.order_date)
        supplied_order_no = clean_text(order_no)
        if supplied_order_no:
            commento = f"PG-X-ORD.Nr.{supplied_order_no}-{year}-(LETTER {clean_text(r.reply_no)})"
        else:
            commento = f"PG-X-ORD.nr.{year}(LETTER {clean_text(r.reply_no)})"

        out.append(OrdineKamalRow(
            articolo_delta=articolo,
            coloredfm=r.coloredfm,
            peso_kg=r.peso_kg,
            data_consegna=data_consegna_dt,
            commento=commento,
            data_riconsegna=data_riconsegna_dt,
            sender_msg_no=clean_text(r.sender_msg_no),
            colore_name=clean_text(r.colore_name),
            titolo=clean_text(r.titolo),
            order_no=supplied_order_no,
        ))

    if unmatched:
        logger.warning("Ordine Kamal: %d row(s) had a Titolo but no matching C170 Articolo in DFM", unmatched)

    return out


def match_by_lotto(rows: list[OrdineKamalRow], lotti_summary) -> int:
    """
    Fills in the Partita number in place of "X" in "PG-X-..." by matching
    each row's sender_msg_no (Kamal's own "رقم رسالة الخام") against the
    Lotto column in the LOTTI reference (lotti_logic.summarize_by_partita()
    output: columns partita, lotto) -- this is Kamal's own deterministic
    reference for which raw yarn batch to use, so it takes priority over
    quantity-based matching (ordini_elvy.match_raw_yarn).
    Returns how many rows were matched.
    """
    if lotti_summary is None or lotti_summary.empty:
        return 0

    lotto_to_partita: dict[str, str] = {}
    for _, r in lotti_summary.iterrows():
        lotto_to_partita.setdefault(str(r["lotto"]).strip(), str(r["partita"]).strip())

    matched = 0
    for row in rows:
        if "PG-X" not in (row.commento or ""):
            continue
        msg_no = clean_text(row.sender_msg_no)
        if not msg_no:
            continue
        partita = lotto_to_partita.get(msg_no)
        if partita:
            row.commento = row.commento.replace("PG-X", f"PG-{partita}")
            matched += 1

    return matched


def _extract_year(order_date: str) -> str:
    for part in clean_text(order_date).replace("-", "/").split("/"):
        if len(part) == 4 and part.isdigit():
            return part
    return str(datetime.now().year)
