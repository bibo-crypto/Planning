"""قراءة ملفات الإدخال (ERP / Dispo-Bagno / EL KAMAL) وتحويلها إلى OrderRecord.

جزء من حزمة exporters.biglietti (انظر ARCHITECTURE_AR.md). الواجهة القديمة
exporters/biglietti_exporter.py تعيد تصدير كل الأسماء من هنا."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl

from calculate.raw_batch import LOT_CUSTOMER_CODES, MED_CODE
from exporters.biglietti.fields import (
    _clean,
    _dispo_number,
    _dispo_suffix,
    _first_match,
    _kamal_kg,
    _key,
    _number,
    _order_number,
    _raw_batch_from_comment,
)
from exporters.biglietti.records import OrderRecord
from utility.utils import logger


def _read_sheet_rows(ws) -> list[dict[str, Any]]:
    """Read a sheet using its most likely header row, even after export shifts."""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    known_headers = {
        "cliente", "clienti", "articolo", "codice", "colore", "ordine", "riga",
        "consegna", "ordinata", "assegnata", "descrizioneaggiuntivaordine",
        "dispo", "bagno", "partita", "partitagg", "titolo", "mc", "rocche",
        "qta", "q ta", "dataconsegna", "data consegna", "commento",
        "disposizione", "numbagno",
    }
    candidates = []
    for idx in range(min(12, len(rows))):
        if idx < len(rows):
            headers = [_key(x) or f"__col{i + 1}" for i, x in enumerate(rows[idx])]
            known_score = sum(header in known_headers for header in headers)
            nonempty_score = sum(bool(x) for x in headers)
            candidates.append((known_score, nonempty_score, idx, headers))
    best_known = max((item[0] for item in candidates), default=0)
    if best_known >= 2:
        _, _, header_idx, headers = max(
            candidates, key=lambda item: (item[0], item[1], -item[2])
        )
    else:
        _, _, header_idx, headers = max(
            candidates, key=lambda item: (item[1], -item[2]), default=(0, 0, 0, [])
        )
    out = []
    for values in rows[header_idx + 1:]:
        if not any(_clean(x) for x in values):
            continue
        # Many ERP exports repeat the header row twice.  Do not turn that
        # repeated header into a real data record (especially important for
        # the first Dispo-Bagno row).
        comparable = [(i, _key(values[i]), headers[i]) for i in range(min(len(values), len(headers))) if _clean(values[i]) and headers[i].startswith("__") is False]
        if comparable and sum(a == b for _, a, b in comparable) >= max(2, len(comparable) // 2):
            continue
        rec = {}
        for i, value in enumerate(values):
            if i < len(headers):
                # Keep the first duplicate header; this avoids row-2 blank
                # labels replacing the actual row-1 label.
                rec.setdefault(headers[i], value)
                rec.setdefault(f"__col{i + 1}", value)
        rec["__headers"] = headers
        out.append(rec)
    return out


# Other header spellings each name is also looked up under (shared with the input check).
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "articolo": ("codice articolo", "articolo codice"),
    "colore": ("codice colore", "colore codice", "descrizione colore"),
    "ordinata": ("qta", "q ta", "q.t.a", "quantita", "quantità", "rocche"),
    "riga": ("numero riga", "nr riga", "n riga"),
    "consegna": ("data consegna", "delivery date"),
    "descrizione aggiuntiva ordine": ("descrizione ordine", "commento ordine", "commento"),
    "dispo": ("disposizione", "sigla disposizione"),
    "bagno": ("n bagno", "numero bagno"),
    "partita": ("partita col", "partita colore"),
    "partita.gg": ("partita gg", "partita grezzo", "partita filato"),
}


def _get(row: dict[str, Any], *names: str) -> Any:
    """Read a value from a sheet row by any of several header names (case/spacing-insensitive).
    Known aliases are added automatically (e.g. "colore" also tries "codice colore"); the first non-blank hit wins, else "".
    """
    expanded = list(names)
    for name in names:
        expanded.extend(HEADER_ALIASES.get(_key(name), ()))
    for name in expanded:
        if _key(name) in row and _clean(row[_key(name)]):
            return row[_key(name)]
    return ""


def _name_after_color_code(row: dict[str, Any]) -> str:
    """The colour name: the cell right after the 'Colore' (colour code) column
    of the uploaded order file.  Located by header, so it survives an export
    that shifts the columns; column 7 is the fallback for the usual layout."""
    headers = row.get("__headers") or []
    if "colore" in headers:
        idx = headers.index("colore")
        name = _clean(row.get(f"__col{idx + 2}"))
        if name:
            return name
    return _clean(row.get("__col7"))


def detect_order_format(data_path: Path) -> str:
    """'ELVY_MED' or 'EL_KAMAL', by peeking at the workbook's sheet names
    and Sheet1's own header row.  A single Data Ordine picker serves every
    customer without needing a separate picker per source shape.

    Detection order:
    1. A workbook with an "Ordine Kamal" or "Kamal Order" sheet is always
       EL_KAMAL -- this is the Excel file produced by the Ordine Kamal tab
       and can be dropped straight into Create Excel + Biglietti.
    2. EL KAMAL's ERP-export Sheet1 carries CODICE / M/C / Clienti headers.
    3. ELVY/MED's ERP dump carries 'Descrizione aggiuntiva ordine' + 'Cliente'.
    Defaults to 'ELVY_MED' when none of the above is conclusive."""
    wb = openpyxl.load_workbook(data_path, read_only=True)
    try:
        # A workbook produced by the Ordine Kamal tab has "Ordine Kamal" /
        # "Kamal Order" sheets and no Sheet1 -- detect it as EL_KAMAL so
        # load_el_kamal_order is used instead of load_order.
        sheetnames_lower = {_key(s) for s in wb.sheetnames}
        if _key("Ordine Kamal") in sheetnames_lower or _key("Kamal Order") in sheetnames_lower:
            wb.close()
            return "EL_KAMAL"
        if "Sheet1" not in wb.sheetnames:
            return "ELVY_MED"
        rows = list(wb["Sheet1"].iter_rows(values_only=True, max_row=1))
    finally:
        wb.close()
    if not rows:
        return "ELVY_MED"
    headers = {_key(v) for v in rows[0] if v}
    el_kamal_signature = {_key("CODICE"), _key("Clienti"), _key("M/C")}
    elvy_med_signature = {_key("Descrizione aggiuntiva ordine"), _key("Cliente")}
    if el_kamal_signature.issubset(headers):
        return "EL_KAMAL"
    if elvy_med_signature.issubset(headers):
        return "ELVY_MED"
    return "EL_KAMAL" if "Doispo-Bagno" not in wb.sheetnames else "ELVY_MED"


def load_dispo_bagno_rows(path: Path) -> list[dict[str, Any]]:
    """Reads a Dispo-Bagno source regardless of shape: a .csv (EL KAMAL's
    own export), or an .xlsx with the data on its first sheet."""
    if path.suffix.lower() == ".csv":
        return _read_dispo_csv(path)
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        sheet = next(
            (ws for ws in wb.worksheets
             if "dispo" in _key(ws.title) and "bagno" in _key(ws.title)),
            wb.active,
        )
        return _read_sheet_rows(sheet)
    finally:
        wb.close()


# Customer codes the ERP order dump (Sheet1) may contain.  3019 = EL KAMAL: the
# same raw ERP dump as ELVY/MED, but its quantity is in KG and its machine and
# cone count come from the Dispo rows (Field3 / Field10), not from the order.
ELVY_CODE, KAMAL_CODE = "3009", "3019"          # MED_CODE ("3004") comes from calculate.raw_batch
_ERP_DUMP_CUSTOMER_CODES = {ELVY_CODE, MED_CODE, KAMAL_CODE}
_DEFAULT_KAMAL_NAME = "EL KAMAL"


def _master_data_customer_name(code: str, default: str) -> str:
    """The customer name saved for *code* in Master Data > Customers, else *default*."""
    try:
        from utility import master_data
        for row in master_data.load().get("customers", []):
            if _clean(row.get("code")) == code and _clean(row.get("name")):
                return _clean(row.get("name"))
    except Exception as _ignored:  # noqa: BLE001 -- reference data is optional here
        logger.debug("exporters.biglietti.loaders._master_data_customer_name: ignored %r", _ignored)
    return default


def _machine_number_from_dispo_code(value: Any) -> str:
    """Dispo's Field3 holds the machine GROUP code (e.g. 3309); the ticket shows
    the machine number (3309 -> 3).  Unknown code -> blank, never a guess."""
    try:
        from calculate.constants import MACHINE_NUMBER_BY_CODE
        number = MACHINE_NUMBER_BY_CODE.get(int(float(_clean(value))))
    except (TypeError, ValueError):
        return ""
    return str(number) if number is not None else ""


def load_order(input_path: Path, dispo_path: Path | None = None) -> tuple[list[OrderRecord], list[dict[str, Any]]]:
    """Load an ELVY / MED / EL KAMAL order from the uploaded Excel files.

    Reads the order dump (and the optional Dispo file), keeps the rows of the
    supported customers (ERP codes 3009 / 3019 ...), joins each row to its Dispo
    row, and builds one OrderRecord per colour line.  For Kamal the colour name is
    the cell right after the colour code in the order file.
    Returns (records, raw_rows) where raw_rows are the untouched sheet rows.
    """
    wb = openpyxl.load_workbook(input_path, data_only=True, read_only=True)
    order_sheet = next(
        (name for name in wb.sheetnames if _key(name) in {"ordine", "sheet1"}),
        None,
    )
    if order_sheet is None:
        raise ValueError('Il file Data Ordine deve contenere un foglio Ordine o Sheet1.')
    data = _read_sheet_rows(wb[order_sheet])
    dispo_sheet = next(
        (name for name in wb.sheetnames
         if "dispo" in _key(name) and "bagno" in _key(name)),
        None,
    )
    dispo_rows = _read_sheet_rows(wb[dispo_sheet]) if dispo_sheet else []
    raw_sheet = next(
        (name for name in wb.sheetnames
         if "filato" in _key(name) or "tinturia" in _key(name)),
        None,
    )
    raw_rows = _read_sheet_rows(wb[raw_sheet]) if raw_sheet else []
    if dispo_path and dispo_path != input_path:
        dispo_rows = load_dispo_bagno_rows(dispo_path)
    if not data:
        raise ValueError("Sheet1 non contiene righe d'ordine.")
    dispo_by_riga = {
        _dispo_suffix(_get(r, "Dispo")): r
        for r in dispo_rows if _clean(_get(r, "Dispo"))
    }
    raw_by_article = {_clean(_get(r, "Articolo")).upper(): r for r in raw_rows}
    color_name_by_code: dict[str, str] = {}
    for r in data:
        name = _name_after_color_code(r)
        if name:
            color_name_by_code.setdefault(_clean(_get(r, "Colore")), name)
    result: list[OrderRecord] = []
    for row in data:
        code = _clean(_get(row, "Cliente"))
        if code not in _ERP_DUMP_CUSTOMER_CODES:
            continue
        article = _clean(_get(row, "Articolo"))
        raw = raw_by_article.get(("G" + article[1:]).upper(), {}) if article else {}
        additional = _clean(_get(row, "Descrizione aggiuntiva ordine"))
        if code in LOT_CUSTOMER_CODES:
            # MED / ELVY: Partita GG is never taken from the raw-yarn sheet.  Its
            # comment may name either one of our batches or MED's own lot;
            # the latter remains in PG-X but is retained for output/lookups.
            raw_batch = _raw_batch_from_comment(additional, code)
        else:
            raw_batch = _clean(_get(raw, "Partita.GG", "Partita")) or _first_match(additional, r"PG[- ]*([0-9]+)")
        riga = _clean(_get(row, "Riga"))
        dispo = dispo_by_riga.get(_dispo_suffix(riga), {})
        if code == KAMAL_CODE:
            # EL KAMAL: Ordinata is in KG.  The Dispo row carries what the ticket
            # needs: Field2 = Bagno, Field3 = machine group code, Field9 = KG and
            # Field10 = number of cones.  Commento is the order's own comment
            # (PG-...-ORD.nr...(LETTER n)); it is not a dash-encoded one.
            kg = _kamal_kg(_get(dispo, "Field9")) or _kamal_kg(_get(row, "Ordinata", "Assegnata"))
            result.append(OrderRecord(
                customer_code=code,
                customer_name=_master_data_customer_name(KAMAL_CODE, _DEFAULT_KAMAL_NAME),
                article=article,
                description=additional or article,
                additional_raw=additional,
                color_code=_clean(_get(row, "Colore")),
                # Colour name = the column right after the colour code in the
                # uploaded order file -- never from the Dispo file, whose
                # name is a shorter label.  A row whose own name cell is empty
                # borrows the name of another row with the same colour code.
                color_name=(
                    _name_after_color_code(row)
                    or color_name_by_code.get(_clean(_get(row, "Colore")), "")
                    or _clean(_get(row, "Colore"))
                ),
                order_no=_order_number(_get(row, "Ordine")),
                order_row=riga,
                colored_batch=_clean(_get(row, "Partita")),
                raw_batch=raw_batch,
                quantity_cones=_number(_get(dispo, "Field10")),
                raw_weight=kg,
                dispo=_clean(_get(dispo, "Dispo")),
                bagno=_clean(_get(dispo, "Field2", "Bagno")),
                delivery=_get(row, "Consegna"),
                title=_clean(_get(raw, "Titolo")) or _clean(_get(row, "Descrizione")),
                formato="7777",
                machine=_machine_number_from_dispo_code(_get(dispo, "Field3")),
                commento=additional,
                kg=kg,
            ))
            continue
        result.append(OrderRecord(
            customer_code=code,
            customer_name=_clean(_get(row, "__col2")) or ("MED" if code == "3004" else "ELVY"),
            article=article,
            description=additional or article,
            additional_raw=additional,
            color_code=_clean(_get(row, "Colore")),
            color_name=_clean(_get(row, "__col7")) or _clean(_get(row, "Colore")),
            order_no=_order_number(_get(row, "Ordine")),
            order_row=riga,
            colored_batch=_clean(_get(row, "Partita")),
            raw_batch=raw_batch,
            quantity_cones=_number(_get(row, "Ordinata", "Assegnata")) or _number(_get(raw, "عدد")),
            # A MED row still waiting for raw yarn gets no KG/VMM22 from the raw sheet.
            raw_weight=None if (code in LOT_CUSTOMER_CODES and not raw_batch) else _number(_get(raw, "وزن", "Peso")),
            dispo=_clean(_get(dispo, "Dispo")),
            bagno=_clean(_get(dispo, "Field2", "Bagno")),
            delivery=_get(row, "Consegna"),
            title=_clean(_get(raw, "Titolo")) or _clean(_get(row, "Descrizione")),
        ))
    wb.close()
    if not result:
        raise ValueError("Non sono state trovate righe con Cliente 3004, 3009 o 3019.")
    return result, raw_rows


# ---------------------------------------------------------------------------
# EL KAMAL -- third customer, different source shape entirely: their own
# order export (Sheet1) already arrives with Titolo/KG/M-C/Bagno computed,
# instead of the raw ERP dump ELVY/MED use. The companion Dispo-Bagno file
# is a semicolon CSV (same columns as the Doispo-Bagno sheet) rather than a
# second sheet in the same workbook. Sheet1's own "Dispo" text embeds the
# row's sequence number as 'RIGA N', which is what joins to the CSV's
# 'D-...-00N' suffix -- same join pattern as MED's Riga column, just
# extracted from a different place.
# ---------------------------------------------------------------------------

def _read_dispo_csv(path: Path) -> list[dict[str, Any]]:
    """Read a Dispo CSV (delimiter sniffed among ; , and tab, UTF-8 with BOM) into row dicts keyed like the Excel reader, including the positional __colN keys."""
    import csv
    with open(path, encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        except csv.Error:
            dialect = csv.excel
            dialect.delimiter = ";"
        reader = csv.reader(f, dialect)
        rows = list(reader)
    if not rows:
        return []
    headers = [_key(x) or f"__col{i + 1}" for i, x in enumerate(rows[0])]
    out = []
    for values in rows[1:]:
        if not any(_clean(x) for x in values):
            continue
        rec: dict[str, Any] = {}
        for i, value in enumerate(values):
            if i < len(headers):
                rec.setdefault(headers[i], value)
                rec.setdefault(f"__col{i + 1}", value)
        out.append(rec)
    return out


def load_el_kamal_order(data_path: Path, dispo_path: Path | None = None) -> tuple[list[OrderRecord], list[dict[str, Any]]]:
    """Load an EL KAMAL order from its dedicated workbook.

    Accepts two source shapes:
    * ERP export with "Sheet1" (CODICE / DESCR COL / Clienti columns).
    * Kamal-tab Excel export with "Ordine Kamal" sheet (CLIENTE / ARTICOLO /
      COLORE / Q.TA / COMMENTO columns) -- the workbook the Ordine Kamal tab
      produces can be fed directly into Create Excel + Biglietti.

    Returns (records, []): one OrderRecord per colour line.  The raw-rows list
    is always empty because these layouts carry no raw-yarn sheet.
    """
    wb = openpyxl.load_workbook(data_path, data_only=True, read_only=True)
    # Prefer "Ordine Kamal" (Kamal-tab export) over "Sheet1" (ERP dump).  The Kamal-tab
    # workbook ALSO holds "Kamal Order" -- the raw PDF rows, listed first and with other
    # columns -- which must never be mistaken for the order sheet.
    sheet_by_key = {_key(name): name for name in wb.sheetnames}
    ordine_kamal_sheet = sheet_by_key.get(_key("Ordine Kamal"))
    if ordine_kamal_sheet:
        data = _read_sheet_rows(wb[ordine_kamal_sheet])
        # The order sheet only carries the DFM colour CODE; the colour NAME is on the
        # raw PDF sheet next to the same code.
        pdf_sheet = sheet_by_key.get(_key("Kamal Order"))
        color_name_by_code: dict[str, str] = {}
        if pdf_sheet:
            for pdf_row in _read_sheet_rows(wb[pdf_sheet]):
                code, name = _clean(_get(pdf_row, "COLOREDFM")), _clean(_get(pdf_row, "Colore"))
                if code and name:
                    color_name_by_code.setdefault(code, name)
        # Also load Filato x Tinturia rows for raw-yarn info when present.
        raw_sheet = next(
            (s for s in wb.sheetnames if "filato" in _key(s) or "tinturia" in _key(s)),
            None,
        )
        raw_rows_kt = _read_sheet_rows(wb[raw_sheet]) if raw_sheet else []
        wb.close()
        if not data:
            raise ValueError("Ordine Kamal sheet non contiene righe d'ordine.")
        # Build records from Kamal-tab export columns.
        result: list[OrderRecord] = []
        raw_by_colore: dict[str, dict] = {
            _clean(_get(r, "Partita Col", "Partita")).upper(): r for r in raw_rows_kt if _clean(_get(r, "Partita Col", "Partita"))
        }
        def ordered_kg(sheet_row: dict) -> float | int | None:
            """A KG column holds the ERP's tenths-of-a-kilo; Q.TA here is already kilograms."""
            return _kamal_kg(_get(sheet_row, "KG")) or _number(_get(sheet_row, "Q.TA"))

        for row in data:
            partita_col = _clean(_get(row, "Partita Col", "Partita"))
            raw_r = raw_by_colore.get(partita_col.upper(), {})
            result.append(OrderRecord(
                customer_code="3019",
                customer_name=_master_data_customer_name(KAMAL_CODE, _DEFAULT_KAMAL_NAME),
                article=_clean(_get(row, "ARTICOLO", "Articolo")),
                description=_clean(_get(row, "COMMENTO", "Commento")),
                additional_raw=_clean(_get(row, "COMMENTO", "Commento")),
                color_code=_clean(_get(row, "COLORE", "Colore")),
                color_name=color_name_by_code.get(_clean(_get(row, "COLORE", "Colore")), _clean(_get(row, "COLORE", "Colore"))),
                order_no=_order_number(_get(row, "ORDINE", "Ordine")),
                order_row="",
                colored_batch=partita_col,
                raw_batch=_clean(_get(row, "Partita GG")) or _clean(_get(raw_r, "Partita GG")),
                # Q.TA on this sheet is the ordered WEIGHT in kg, not a number of cones.
                quantity_cones=_number(_get(row, "ROCCHE", "Rocche")),
                raw_weight=ordered_kg(row) or _kamal_kg(_get(raw_r, "KG")),
                dispo=_clean(_get(row, "SIGLA DISPOSIZIONE", "Dispo")),
                bagno=_clean(_get(row, "BAGNO PREPOSTO", "Bagno")),
                delivery=_get(row, "CONSEGNA", "Consegna"),
                title=_clean(_get(row, "TITOLO", "Titolo")),
                formato="7777",
                machine=_clean(_get(row, "GRUPPO MACCHINA", "M/C")),
                commento=_clean(_get(row, "COMMENTO", "Commento")),
                kg=ordered_kg(row) or _kamal_kg(_get(raw_r, "KG")),
            ))
        if not result:
            raise ValueError("Non sono state trovate righe d'ordine EL KAMAL in 'Ordine Kamal'.")
        return result, []
    if "Sheet1" not in wb.sheetnames:
        wb.close()
        raise ValueError('Il file Data Ordine EL KAMAL deve contenere il foglio "Sheet1" o "Ordine Kamal".')
    data = _read_sheet_rows(wb["Sheet1"])
    wb.close()
    if not data:
        raise ValueError("Sheet1 non contiene righe d'ordine.")

    dispo_by_riga: dict[str, dict[str, Any]] = {}
    if dispo_path and dispo_path.is_file():
        dispo_rows = load_dispo_bagno_rows(dispo_path)
        dispo_by_riga = {
            _dispo_suffix(_get(r, "Dispo")): r
            for r in dispo_rows if _clean(_get(r, "Dispo"))
        }

    result: list[OrderRecord] = []
    for row in data:
        dispo_text = _clean(_get(row, "Dispo"))
        riga = _first_match(dispo_text, r"RIGA\s*([0-9]+)")
        dispo_row = dispo_by_riga.get(_dispo_suffix(riga), {}) if riga else {}
        bagno = _clean(_get(row, "Bagno")) or _clean(_get(dispo_row, "Field2", "Bagno"))
        result.append(OrderRecord(
            customer_code="3019",
            customer_name=_clean(_get(row, "Clienti")) or "EL KAMAL",
            article=_clean(_get(row, "CODICE", "Articolo")),
            description=_clean(_get(row, "COMMENTO RIGO ORDINE")),
            additional_raw=_clean(_get(row, "COMMENTO RIGO ORDINE")),
            color_code=_clean(_get(row, "COLORE", "Codice")),
            color_name=_clean(_get(row, "DESCR COL", "Colore")),
            order_no=_order_number(_get(row, "ORDINE", "Ordine")),
            order_row=riga,
            colored_batch=_clean(_get(row, "Partita Col", "Partita")),
            raw_batch=_clean(_get(row, "Partita GG")),
            quantity_cones=_number(_get(row, "ROCCHE", "Rocche")),
                raw_weight=_kamal_kg(_get(row, "KG")),
            dispo=dispo_text or _clean(_get(dispo_row, "Dispo")),
            bagno=bagno,
            delivery=_get(row, "CONSEGNA", "Consegna"),
            title=_clean(_get(row, "TITOLO", "Titolo")),
            formato=_clean(_get(row, "Formmato", "Formato")) or "7777",
            machine=_clean(_get(row, "M/C")),
            commento=_clean(_get(row, "COMMENTO RIGO ORDINE")),
                kg=_kamal_kg(_get(row, "KG")),
        ))
    if not result:
        raise ValueError("Non sono state trovate righe d'ordine EL KAMAL in Sheet1.")
    return result, []


def build_el_kamal_stem(records: list["OrderRecord"]) -> str:
    """Build the Kamal Biglietti filename stem.

    Kamal ticket files use the requested convention ``D-<dispo>-KAMAL-<year>``.
    The Excel filename is intentionally separate: it is derived from the
    ``ORD...`` portion of Commento by :func:`build_el_kamal_excel_stem`.
    """
    dispo_num = _dispo_number(records[0].dispo) if records else ""
    year = ""
    for record in records:
        match = re.search(r"\b(?:19|20)\d{2}\b", _clean(record.commento))
        if match:
            year = match.group(0)
            break
    if not year:
        year = str(datetime.now().year)
    return f"D-{dispo_num}-KAMAL-{year}" if dispo_num else f"KAMAL-{year}"


def build_el_kamal_excel_stem(records: list["OrderRecord"]) -> str:
    """Return the Excel stem from ``ORD`` through the end of Commento.

    Example: ``PG-159640-ORD.Nr.28-2026(LETTER 108)`` becomes
    ``ORD.Nr.28-2026(LETTER 108)``.  Characters that Windows does not allow
    in filenames are replaced conservatively.
    """
    for record in records:
        comment = _clean(record.commento)
        match = re.search(r"\bORD\b.*$", comment, re.IGNORECASE)
        if match:
            stem = match.group(0).strip()
            stem = re.sub(r"[<>:\"/\\|?*]", "_", stem)
            return stem.rstrip(" .") or "KAMAL"
    return "KAMAL"
