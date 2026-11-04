"""ملف Create Orders المشترك: إضافة/تحديث/حذف الصفوف وتاريخ التعديلات وPG-X.

جزء من حزمة exporters.biglietti (انظر ARCHITECTURE_AR.md). الواجهة القديمة
exporters/biglietti_exporter.py تعيد تصدير كل الأسماء من هنا."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import openpyxl

from calculate.raw_batch import MED_CODE, is_blank_raw, is_customer_lot
from exporters.biglietti.fields import _clean, _key, _number, _polmoni_segment
from exporters.biglietti.loaders import ELVY_CODE, _get, _read_sheet_rows
from exporters.biglietti.records import OrderRecord
from exporters.biglietti.workbook_io import _serialized_workbook_write, style_sheet
from utility.excel_io import safe_save_workbook
from utility.master_data import raw_articolo_for
from utility.utils import logger

CREATE_EXCEL_HEADERS = [
    "Dispo/Riga", "Cliente", "Articolo", "Titolo", "Formato", "Ordine", "Codice",
    "Colore", "Rocche", "KG", "M/C", "Partita Col", "Consegna",
    "Commento", "Bagno", "Partita GG", "Delivery Date", "Partita MED",
    "Cliente MED", "POLMON", "Color Tube", "VMM22", "Prezzo",
    "Densita` (360-390)", "Print",
]


def _create_excel_row(record: OrderRecord, customer: str) -> list[Any]:
    """Return the stable superset row used by the shared order workbook."""
    polmon = _polmoni_segment(record.additional_raw) if customer == "MED" else ""
    return [
        record.dispo, record.customer_name or customer,
        record.article, record.title, record.formato, record.order_no,
        record.color_code, record.color_name, record.quantity_cones,
        record.kg, record.machine, record.colored_batch, record.delivery,
        record.commento, record.bagno, record.raw_batch, record.delivery_date,
        record.partita_med, record.cliente_med, polmon, record.color_tube,
        record.vmm22, record.prezzo, record.densita, record.print_flag,
    ]


def _partita_key(value: Any) -> str:
    value = _clean(value)
    number = _number(value)
    if number is not None:
        return str(int(number)) if float(number).is_integer() else str(number)
    return value.casefold()


def pg_x_batch_stock_status(articles: list[str], partita_gg: str, magazino_summary) -> str:
    """Classify an uploaded raw batch against the required raw articles."""
    expected_articles = {
        raw_articolo_for(article).strip().upper()
        for article in articles
        if _clean(article)
    }
    if not expected_articles:
        return "mismatch"
    if magazino_summary is None or magazino_summary.empty:
        return "missing"

    batch_key = _partita_key(partita_gg)
    batch_stock = magazino_summary[
        magazino_summary["partita"].map(_partita_key) == batch_key
    ]
    if batch_stock.empty:
        return "missing"

    stocked_articles = set(
        batch_stock["articolo"].astype(str).str.strip().str.upper()
    )
    return "available" if expected_articles.issubset(stocked_articles) else "mismatch"


@_serialized_workbook_write
def remove_uploaded_pgx_rows(path: Path, row_indices: list[int]) -> int:
    """Remove successfully processed data rows from the uploaded workbook."""
    if not row_indices:
        return 0

    from openpyxl import load_workbook

    path = Path(path)
    workbook = load_workbook(path, keep_vba=path.suffix.casefold() == ".xlsm")
    try:
        worksheet = workbook.active
        removed = 0
        for row_index in sorted(set(row_indices), reverse=True):
            if row_index > 1 and row_index <= worksheet.max_row:
                worksheet.delete_rows(row_index, 1)
                removed += 1
        if removed:
            safe_save_workbook(workbook, path)
        return removed
    finally:
        workbook.close()


def _is_pg_x(value: Any, customer_code: Any = "") -> bool:
    """True when a row belongs in PG-X.

    Blank batches always wait.  MED lots that do not start with ``1`` also
    wait: they are displayed as Partita GG, yet are not our assigned yarn.
    """
    return is_blank_raw(value) or is_customer_lot(value, customer_code)


def _deduplicate_create_excel_rows(wb) -> int:
    """Keep the first non-empty Partita Col across Orders and PG-X."""
    seen: set[str] = set()
    removed = 0
    for sheet_name in ("Orders", "PG-X"):
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        headers = [_clean(cell.value) for cell in ws[1]]
        partita_col = next(
            (index + 1 for index, header in enumerate(headers) if _key(header) == _key("Partita Col")),
            None,
        )
        if partita_col is None:
            continue
        duplicate_rows = []
        for row_idx in range(2, ws.max_row + 1):
            key = _partita_key(ws.cell(row=row_idx, column=partita_col).value)
            if not key:
                continue
            if key in seen:
                duplicate_rows.append(row_idx)
            else:
                seen.add(key)
        for row_idx in reversed(duplicate_rows):
            ws.delete_rows(row_idx, 1)
        removed += len(duplicate_rows)
    return removed


@_serialized_workbook_write
def deduplicate_create_excel(path: Path) -> int:
    """Remove duplicate Partita Col rows from the shared Orders workbook."""
    from openpyxl import load_workbook

    wb = load_workbook(path)
    try:
        removed = _deduplicate_create_excel_rows(wb)
        if removed:
            safe_save_workbook(wb, path)
            _sync_workbook_history(path, wb)
        return removed
    finally:
        wb.close()


@_serialized_workbook_write
def append_create_excel(path: Path, records: list[OrderRecord], customer: str) -> dict[str, Any]:
    """Create or append the shared workbook used by the dyeing review flow.

    ``Partita Col`` is the business key: rows whose key already exists in the
    workbook are skipped.  The complete data set is then sorted numerically by
    that column, with blank/non-numeric values at the end.
    """
    from openpyxl import Workbook, load_workbook

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        wb = load_workbook(path)
        ws = wb["Orders"] if "Orders" in wb.sheetnames else wb.active
        headers = [_clean(c.value) for c in ws[1]]
        if "Partita Col" not in headers:
            wb.close()
            raise ValueError("The selected Excel file has no 'Partita Col' column.")
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Orders"
        headers = list(CREATE_EXCEL_HEADERS)
        ws.append(headers)

    if "Print" not in headers:
        headers.append("Print")
        ws.cell(row=1, column=len(headers)).value = "Print"

    pg_ws = wb["PG-X"] if "PG-X" in wb.sheetnames else wb.create_sheet("PG-X")
    if pg_ws.max_row == 1 and all(c.value is None for c in pg_ws[1]):
        pg_ws.delete_rows(1)
    if pg_ws.max_row == 0:
        pg_ws.append(headers)
    pg_headers = [_clean(c.value) for c in pg_ws[1]]
    if not pg_headers or "Partita Col" not in pg_headers:
        if pg_ws.max_row > 0:
            pg_ws.delete_rows(1, pg_ws.max_row)
        pg_headers = list(headers)
        pg_ws.append(pg_headers)
    elif "Print" not in pg_headers:
        pg_headers.append("Print")
        pg_ws.cell(row=1, column=len(pg_headers)).value = "Print"

    # Migrate legacy shared files: rows still waiting for raw yarn belong on PG-X --
    # no Partita GG, or (MED only) a customer lot that does not start with 1.
    raw_col = next((i + 1 for i, h in enumerate(headers) if _key(h) == _key("Partita GG")), None)
    if raw_col and ws.max_row > 1:
        customer_col = next((i + 1 for i, h in enumerate(headers) if _key(h) == _key("Cliente")), None)

        def waits_in_pg_x(row_idx: int) -> bool:
            customer = _clean(ws.cell(row=row_idx, column=customer_col).value) if customer_col else ""
            customer_code = next(
                (code for name, code in (("MED", MED_CODE), ("ELVY", ELVY_CODE)) if customer.upper().startswith(name)), "",
            )
            return _is_pg_x(ws.cell(row=row_idx, column=raw_col).value, customer_code)

        waiting_rows = [row_idx for row_idx in range(2, ws.max_row + 1) if waits_in_pg_x(row_idx)]
        for row_idx in waiting_rows:
            row = [ws.cell(row=row_idx, column=col_idx).value for col_idx in range(1, ws.max_column + 1)]
            pg_ws.append([dict(zip(headers, row)).get(header, "") for header in pg_headers])
        for row_idx in reversed(waiting_rows):
            ws.delete_rows(row_idx, 1)

    _deduplicate_create_excel_rows(wb)

    def col(name: str) -> int | None:
        wanted = _key(name)
        for idx, header in enumerate(headers, start=1):
            if _key(header) == wanted:
                return idx
        return None

    existing = set()
    for candidate_ws, candidate_headers in ((ws, headers), (pg_ws, pg_headers)):
        candidate_col = next((i + 1 for i, h in enumerate(candidate_headers) if _key(h) == _key("Partita Col")), None)
        if candidate_col:
            existing.update(
                _partita_key(candidate_ws.cell(row=row, column=candidate_col).value)
                for row in range(2, candidate_ws.max_row + 1)
                if _partita_key(candidate_ws.cell(row=row, column=candidate_col).value)
            )
    added = 0
    skipped = 0
    for record in records:
        key = _partita_key(record.colored_batch)
        if not key or key in existing:
            skipped += 1
            continue
        values = dict(zip(CREATE_EXCEL_HEADERS, _create_excel_row(record, customer)))
        target_ws = pg_ws if _is_pg_x(record.raw_batch, record.customer_code) else ws
        target_headers = pg_headers if target_ws is pg_ws else headers
        target_ws.append([values.get(header, "") for header in target_headers])
        existing.add(key)
        added += 1

    def sort_sheet(target_ws, target_headers):
        target_col = next(i + 1 for i, h in enumerate(target_headers) if _key(h) == _key("Partita Col"))
        rows = list(target_ws.iter_rows(min_row=2, values_only=True))
        rows.sort(key=lambda row: (
            _number(row[target_col - 1]) is None,
            _number(row[target_col - 1]) if _number(row[target_col - 1]) is not None else 0,
        ))
        if target_ws.max_row > 1:
            target_ws.delete_rows(2, target_ws.max_row - 1)
        for row in rows:
            target_ws.append(list(row))
        style_sheet(target_ws, date_columns=("Consegna", "Delivery Date"))

    sort_sheet(ws, headers)
    sort_sheet(pg_ws, pg_headers)
    safe_save_workbook(wb, path)
    _sync_workbook_history(path, wb)
    wb.close()
    return {"added": added, "skipped": skipped, "total": ws.max_row - 1 + pg_ws.max_row - 1}


def _sync_workbook_history(path: Path, wb) -> None:
    """Best-effort mirror of the live Create workbook into SQLite history."""
    try:
        from utility.orders_db import partita_key, reconcile_sheet, sync_rows
        keys_by_sheet: dict[str, set[str]] = {}
        for sheet_name in ("Orders", "PG-X"):
            if sheet_name not in wb.sheetnames:
                continue
            ws = wb[sheet_name]
            headers = [_clean(cell.value) for cell in ws[1]]
            rows = [dict(zip(headers, values)) for values in ws.iter_rows(min_row=2, values_only=True)]
            sync_rows(path, sheet_name, rows)
            if "Partita Col" in headers:   # without that column nothing can be said about what left the sheet
                keys_by_sheet[sheet_name] = {partita_key(row.get("Partita Col")) for row in rows} - {""}
        # A row that moved between the two sheets must not stay "open" in the old one.
        for sheet_name, keys in keys_by_sheet.items():
            other = next((name for name in keys_by_sheet if name != sheet_name), None)
            moved_to = {key: other for key in keys_by_sheet.get(other, ())} if other else {}
            reconcile_sheet(path, sheet_name, keys, moved_to)
    except Exception as _ignored:
        # History must never prevent the operational Excel export from saving.
        logger.debug("exporters.biglietti.shared_workbook._sync_workbook_history: ignored %r", _ignored)


def sync_workbook_history(path: Path) -> None:
    """Import an existing Create workbook into SQLite without changing it."""
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        _sync_workbook_history(path, wb)
    finally:
        wb.close()


def load_create_excel_records(path: Path, partita_gg: str = "", sheet_name: str = "Orders") -> list[OrderRecord]:
    """Read shared-workbook rows, optionally filtered by ``Partita GG``."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        if sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
        elif sheet_name == "Orders":
            ws = wb.active
        else:
            return []
        rows = _read_sheet_rows(ws)
    finally:
        wb.close()
    wanted = _partita_key(partita_gg) if _clean(partita_gg) else ""
    out: list[OrderRecord] = []
    for row in rows:
        if wanted and _partita_key(_get(row, "Partita GG")) != wanted:
            continue
        customer = _clean(_get(row, "Cliente")) or "ELVY"
        code = "3004" if customer.upper().startswith("MED") else "3009"
        out.append(OrderRecord(
            customer_code=code, customer_name=customer,
            article=_clean(_get(row, "Articolo")),
            description=_clean(_get(row, "Titolo")), additional_raw=_clean(_get(row, "Commento")),
            color_code=_clean(_get(row, "Codice")), color_name=_clean(_get(row, "Colore")),
            order_no=_clean(_get(row, "Ordine")), order_row="",
            colored_batch=_clean(_get(row, "Partita Col")), raw_batch=_clean(_get(row, "Partita GG")),
            quantity_cones=_number(_get(row, "Rocche")), raw_weight=_number(_get(row, "KG")),
            dispo=_clean(_get(row, "Dispo/Riga")), bagno=_clean(_get(row, "Bagno")),
            delivery=_get(row, "Consegna"), machine=_clean(_get(row, "M/C")),
            title=_clean(_get(row, "Titolo")), commento=_clean(_get(row, "Commento")),
            partita_med=_clean(_get(row, "Partita MED")), cliente_med=_clean(_get(row, "Cliente MED")),
            kg=_number(_get(row, "KG")), color_tube=_clean(_get(row, "Color Tube")),
            vmm22=_number(_get(row, "VMM22")), prezzo=_get(row, "Prezzo"),
            densita=_get(row, "Densita` (360-390)"), delivery_date=_get(row, "Delivery Date"),
            print_flag=_clean(_get(row, "Print")),
        ))
    if not out and not _clean(partita_gg):
        return []
    if not out:
        raise ValueError(f"No rows were found for Partita GG '{partita_gg}'.")
    return out


@_serialized_workbook_write
def update_pg_x_row(path: Path, partita_col: str, updates: dict[str, Any]) -> int:
    """Update editable fields for a PG-X color without assigning it yet."""
    from openpyxl import load_workbook

    wb = load_workbook(path)
    try:
        if "PG-X" not in wb.sheetnames:
            raise ValueError("The shared Excel has no PG-X sheet.")
        ws = wb["PG-X"]
        headers = [_clean(c.value) for c in ws[1]]

        def header_col(name):
            wanted = _key(name)
            return next((i + 1 for i, value in enumerate(headers) if _key(value) == wanted), None)

        partita_col_idx = header_col("Partita Col")
        if not partita_col_idx:
            raise ValueError("Partita Col column is missing.")
        wanted = _partita_key(partita_col)
        matches = [
            row_idx for row_idx in range(2, ws.max_row + 1)
            if _partita_key(ws.cell(row=row_idx, column=partita_col_idx).value) == wanted
        ]
        if not matches:
            raise ValueError(f"Partita Col '{partita_col}' was not found in PG-X.")

        columns = {name: header_col(name) for name in updates}
        for name, value in updates.items():
            column = columns[name]
            if column:
                for row_idx in matches:
                    ws.cell(row=row_idx, column=column).value = value
        style_sheet(ws, date_columns=("Consegna", "Delivery Date"))
        safe_save_workbook(wb, path)
        return len(matches)
    finally:
        wb.close()


@_serialized_workbook_write
def update_order_row(
    path: Path,
    partita_col: str,
    updates: dict[str, Any],
    magazino_summary=None,
    allow_article_mismatch: bool = False,
) -> dict[str, Any]:
    """Edit an Orders row; clearing Partita GG moves it back to PG-X."""
    from openpyxl import load_workbook

    wb = load_workbook(path)
    try:
        if "Orders" not in wb.sheetnames or "PG-X" not in wb.sheetnames:
            raise ValueError("The shared Excel must contain Orders and PG-X sheets.")
        orders_ws, pg_ws = wb["Orders"], wb["PG-X"]
        order_headers = [_clean(c.value) for c in orders_ws[1]]
        pg_headers = [_clean(c.value) for c in pg_ws[1]]

        def header_col(headers, name):
            wanted = _key(name)
            return next((i + 1 for i, value in enumerate(headers) if _key(value) == wanted), None)

        part_col_idx = header_col(order_headers, "Partita Col")
        gg_col_idx = header_col(order_headers, "Partita GG")
        if not part_col_idx or not gg_col_idx:
            raise ValueError("Orders is missing Partita Col or Partita GG columns.")
        wanted = _partita_key(partita_col)
        matches = [
            row_idx for row_idx in range(2, orders_ws.max_row + 1)
            if _partita_key(orders_ws.cell(row=row_idx, column=part_col_idx).value) == wanted
        ]
        if not matches:
            raise ValueError(f"Partita Col '{partita_col}' was not found in Orders.")

        # "Partita GG" may not be in *updates* at all (e.g. a caller only
        # changing Articolo) -- that must never be read as "cleared" (which
        # would wrongly move the row to PG-X) nor let a changed Articolo
        # skip validation against whatever Partita GG the row already has.
        # Only an explicit, empty "Partita GG" in updates means "clear it".
        partita_gg_submitted = "Partita GG" in updates
        if partita_gg_submitted:
            new_gg = _clean(updates.get("Partita GG", ""))
        else:
            new_gg = _clean(orders_ws.cell(row=matches[0], column=gg_col_idx).value)
        if new_gg and magazino_summary is not None:
            article_col_idx = header_col(order_headers, "Articolo")
            color_article = _clean(updates.get("Articolo"))
            if not color_article and article_col_idx:
                color_article = _clean(orders_ws.cell(row=matches[0], column=article_col_idx).value)
            color_article = color_article.upper()
            expected_raw = raw_articolo_for(color_article)
            batch_key = _partita_key(new_gg)
            matching_stock = magazino_summary[
                (magazino_summary["articolo"].astype(str).str.strip().str.upper() == expected_raw)
                & (magazino_summary["partita"].map(_partita_key) == batch_key)
            ]
            if matching_stock.empty and not allow_article_mismatch:
                raise ValueError(
                    f"Partita GG {new_gg} does not belong to article {expected_raw} "
                    f"required by color article {color_article}."
                )

        updates_by_header = {header_col(order_headers, name): value for name, value in updates.items()}
        for row_idx in matches:
            for column, value in updates_by_header.items():
                if column:
                    orders_ws.cell(row=row_idx, column=column).value = value

        moved_to_pgx = partita_gg_submitted and not new_gg
        if moved_to_pgx:
            # These columns are only ever populated by save_pg_x_partita()
            # when a raw yarn batch gets assigned (see there): KG and VMM22
            # are computed from that batch's Rocche, and Densita`/Color Tube
            # are looked up from it. Clearing Partita GG must clear them
            # back out too -- otherwise the row moves back to PG-X still
            # showing stale numbers from the raw yarn that was just removed.
            for header in ("KG", "Densita` (360-390)", "Color Tube", "VMM22"):
                column = header_col(order_headers, header)
                if column:
                    for row_idx in matches:
                        orders_ws.cell(row=row_idx, column=column).value = ""
            for row_idx in matches:
                pg_values = {header: orders_ws.cell(row=row_idx, column=idx + 1).value for idx, header in enumerate(order_headers)}
                pg_ws.append([pg_values.get(header, "") for header in pg_headers])
            for row_idx in reversed(matches):
                orders_ws.delete_rows(row_idx, 1)

        style_sheet(orders_ws, date_columns=("Consegna", "Delivery Date"))
        style_sheet(pg_ws, date_columns=("Consegna", "Delivery Date"))
        safe_save_workbook(wb, path)
        _sync_workbook_history(path, wb)
        return {"updated": len(matches), "moved_to_pgx": moved_to_pgx}
    finally:
        wb.close()


@_serialized_workbook_write
def save_pg_x_partita(
    path: Path,
    partita_col: str,
    partita_gg: str,
    densita_map: dict[int, dict[str, Any]] | None = None,
    vmm_ratio_map: dict[int, float] | None = None,
    magazino_summary=None,
    allow_article_mismatch: bool = False,
    lotto: str = "",
    allow_missing_magazino_batch: bool = False,
    move_to_orders: bool = True,
) -> dict[str, Any]:
    """Assign raw yarn to a PG-X color and optionally move it to Orders.

    ``lotto`` is an optional identifier extracted from ``Commento``.  When it
    is supplied, callers may validate it against the warehouse summary before
    calling this function; the final Partita GG is always the selected stock
    batch. Set ``move_to_orders=False`` to leave the assigned row in PG-X for
    a later manual move.
    """
    from openpyxl import load_workbook

    densita_map = densita_map or {}
    vmm_ratio_map = vmm_ratio_map or {}
    wb = load_workbook(path)
    if "PG-X" not in wb.sheetnames:
        wb.close()
        raise ValueError("The shared Excel has no PG-X sheet.")
    pg_ws = wb["PG-X"]
    orders_ws = wb["Orders"] if "Orders" in wb.sheetnames else wb.active
    pg_headers = [_clean(c.value) for c in pg_ws[1]]
    order_headers = [_clean(c.value) for c in orders_ws[1]]

    def header_col(headers, name):
        wanted = _key(name)
        return next((i + 1 for i, value in enumerate(headers) if _key(value) == wanted), None)

    col_partita_col = header_col(pg_headers, "Partita Col")
    col_partita_gg = header_col(pg_headers, "Partita GG")
    if not col_partita_col or not col_partita_gg:
        wb.close()
        raise ValueError("PG-X is missing Partita Col or Partita GG columns.")
    wanted_col = _partita_key(partita_col)
    matching_rows = [
        row_idx for row_idx in range(2, pg_ws.max_row + 1)
        if _partita_key(pg_ws.cell(row=row_idx, column=col_partita_col).value) == wanted_col
    ]
    if not matching_rows:
        wb.close()
        raise ValueError(f"Partita Col '{partita_col}' was not found in PG-X.")

    source_map = {header: index + 1 for index, header in enumerate(pg_headers)}
    batch_number = _number(partita_gg)
    density_entry = densita_map.get(int(batch_number)) if batch_number is not None else None
    moved_rows = []
    available_total = 0.0
    for row_idx in matching_rows:
        rocche_col = header_col(pg_headers, "Rocche")
        rocche = _number(pg_ws.cell(row=row_idx, column=rocche_col).value) if rocche_col else 0
        values = {header: pg_ws.cell(row=row_idx, column=col_idx).value for header, col_idx in source_map.items()}
        values["Partita GG"] = partita_gg
        comment_header = next((h for h in order_headers if _key(h) == _key("Commento")), None)
        if comment_header:
            # Preserve the suffix (PM-X, PO-123, etc.) while replacing the
            # complete token immediately after PG-.  PG-X-PMX becomes
            # PG-158922-PM-X, as required by the ERP import convention.
            original_comment = _clean(values.get(comment_header))
            if original_comment:
                replaced = re.sub(r"(?i)(PG-)([^\s-]+)-?PM-?X",
                                  lambda m: f"{m.group(1)}{partita_gg}-PM-X", original_comment, count=1)
                if replaced == original_comment:
                    replaced = re.sub(r"(?i)(PG-)[^-\s]+", rf"\g<1>{partita_gg}", original_comment, count=1)
                values[comment_header] = replaced
        if magazino_summary is not None:
            color_article = _clean(values.get("Articolo")).upper()
            expected_raw_article = raw_articolo_for(color_article)
            batch_key = str(int(batch_number)) if batch_number is not None else _clean(partita_gg)
            batch_stock = magazino_summary[
                magazino_summary["partita"].map(_partita_key) == batch_key
            ]
            matching_stock = magazino_summary[
                (magazino_summary["articolo"].astype(str).str.strip().str.upper() == expected_raw_article)
                & (magazino_summary["partita"].map(_partita_key) == batch_key)
            ]
            if matching_stock.empty:
                batch_is_unknown = batch_stock.empty
                if not (batch_is_unknown and allow_missing_magazino_batch) and not allow_article_mismatch:
                    wb.close()
                    raise ValueError(
                        f"Partita GG {partita_gg} does not belong to article {expected_raw_article} "
                        f"required by color article {color_article}."
                    )
            if not matching_stock.empty:
                available_total += float(matching_stock.iloc[0].get("mag_rocche", 0) or 0)
        if density_entry:
            if density_entry.get("peso_net") is not None:
                values["KG"] = int(round(density_entry["peso_net"] * (rocche or 0)))
            values["Densita` (360-390)"] = density_entry.get("densita", "")
            values["Color Tube"] = density_entry.get("color_tube", "")
        if batch_number is not None and int(batch_number) in vmm_ratio_map:
            values["VMM22"] = round(vmm_ratio_map[int(batch_number)] * (rocche or 0), 2)
        moved_rows.append([values.get(header, "") for header in order_headers])

    if move_to_orders:
        for row in moved_rows:
            orders_ws.append(row)

        for row_idx in reversed(matching_rows):
            pg_ws.delete_rows(row_idx, 1)
    else:
        for row_idx, row in zip(matching_rows, moved_rows):
            values = dict(zip(order_headers, row))
            for header, col_idx in source_map.items():
                pg_ws.cell(row=row_idx, column=col_idx).value = values.get(header, "")

    def sort_sheet(ws, headers):
        col_idx = header_col(headers, "Partita Col")
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        rows.sort(key=lambda row: (_number(row[col_idx - 1]) is None, _number(row[col_idx - 1]) or 0))
        if ws.max_row > 1:
            ws.delete_rows(2, ws.max_row - 1)
        for row in rows:
            ws.append(list(row))
        style_sheet(ws, date_columns=("Consegna", "Delivery Date"))

    sort_sheet(pg_ws, pg_headers)
    sort_sheet(orders_ws, order_headers)
    safe_save_workbook(wb, path)
    _sync_workbook_history(path, wb)
    wb.close()
    return {"updated": len(matching_rows), "partita_gg": partita_gg, "available": available_total}


@_serialized_workbook_write
def move_pg_x_to_orders(path: Path, partita_col: str) -> int:
    """Move the selected PG-X color row to Orders."""
    from openpyxl import load_workbook
    wb = load_workbook(path)
    if "PG-X" not in wb.sheetnames or "Orders" not in wb.sheetnames:
        wb.close()
        raise ValueError("The shared Excel must contain Orders and PG-X sheets.")
    pg_ws, orders_ws = wb["PG-X"], wb["Orders"]
    pg_headers = [_clean(c.value) for c in pg_ws[1]]
    order_headers = [_clean(c.value) for c in orders_ws[1]]
    pg_col = next((i + 1 for i, h in enumerate(pg_headers) if _key(h) == _key("Partita Col")), None)
    order_col = next((i + 1 for i, h in enumerate(order_headers) if _key(h) == _key("Partita Col")), None)
    if not pg_col or not order_col:
        wb.close()
        raise ValueError("Partita Col column is missing.")
    wanted = _partita_key(partita_col)
    matches = [r for r in range(2, pg_ws.max_row + 1) if _partita_key(pg_ws.cell(r, pg_col).value) == wanted]
    if not matches:
        # Not an error: this happens whenever the row already moved out of
        # PG-X between when the caller decided to move it and when this
        # runs (e.g. a row moved by an earlier "Print Assigned PG-X" pass).
        # Nothing to move is a no-op success, not a crash.
        wb.close()
        return 0
    existing = {_partita_key(orders_ws.cell(r, order_col).value) for r in range(2, orders_ws.max_row + 1)}
    for row_idx in matches:
        values = {header: pg_ws.cell(row_idx, idx + 1).value for idx, header in enumerate(pg_headers)}
        row = [values.get(header, "") for header in order_headers]
        if _partita_key(row[order_col - 1]) not in existing:
            orders_ws.append(row)
            existing.add(_partita_key(row[order_col - 1]))
    for row_idx in reversed(matches):
        pg_ws.delete_rows(row_idx, 1)
    safe_save_workbook(wb, path)
    _sync_workbook_history(path, wb)
    wb.close()
    return len(matches)


def _record_history_before_delete(path: Path, sheet_name: str, ws, headers: list, col_idx: int,
                                  match_rows: list[int], reason: str) -> None:
    """Write the rows' history (upsert, then archive) BEFORE they are deleted
    from the workbook.  If that fails nothing is deleted: the history is the
    only record that remains once the rows are gone."""
    try:
        from utility.orders_db import archive, sync_rows
        rows = [dict(zip(headers, [cell.value for cell in ws[row_idx]])) for row_idx in match_rows]
        sync_rows(path, sheet_name, rows)   # make sure each row exists in the history first
        archive(path, sheet_name, [ws.cell(row=r, column=col_idx).value for r in match_rows], reason=reason)
    except Exception as exc:
        raise RuntimeError(
            "The order history could not be updated, so nothing was deleted from the workbook. "
            f"Details: {exc}"
        ) from exc


@_serialized_workbook_write
def delete_pg_x_row(path: Path, partita_col: str) -> int:
    """Delete the selected PG-X color row."""
    from openpyxl import load_workbook
    wb = load_workbook(path)
    if "PG-X" not in wb.sheetnames:
        wb.close()
        raise ValueError("The shared Excel has no PG-X sheet.")
    ws = wb["PG-X"]
    headers = [_clean(c.value) for c in ws[1]]
    col_idx = next((i + 1 for i, h in enumerate(headers) if _key(h) == _key("Partita Col")), None)
    if not col_idx:
        wb.close()
        raise ValueError("Partita Col column is missing.")
    wanted = _partita_key(partita_col)
    matches = [r for r in range(2, ws.max_row + 1) if _partita_key(ws.cell(r, col_idx).value) == wanted]
    if not matches:
        wb.close()
        raise ValueError(f"Partita Col '{partita_col}' was not found in PG-X.")
    try:
        _record_history_before_delete(path, "PG-X", ws, headers, col_idx, matches, "deleted")
    except Exception:
        wb.close()
        raise
    for row_idx in reversed(matches):
        ws.delete_rows(row_idx, 1)
    safe_save_workbook(wb, path)
    wb.close()
    return len(matches)


def _delete_shared_rows(path: Path, partita_cols, sheet_name: str, reason: str) -> int:
    """Delete selected Partita Col values from either shared-workbook sheet."""
    from openpyxl import load_workbook

    wb = load_workbook(path)
    try:
        if sheet_name not in wb.sheetnames:
            raise ValueError(f"The shared Excel has no '{sheet_name}' sheet.")
        ws = wb[sheet_name]
        headers = [_clean(c.value) for c in ws[1]]
        col_idx = next((i + 1 for i, h in enumerate(headers) if _key(h) == _key("Partita Col")), None)
        if not col_idx:
            raise ValueError("Partita Col column is missing.")
        shipped = {_partita_key(value) for value in partita_cols if _partita_key(value)}
        matches = [
            row_idx for row_idx in range(2, ws.max_row + 1)
            if _partita_key(ws.cell(row=row_idx, column=col_idx).value) in shipped
        ]
        _record_history_before_delete(path, sheet_name, ws, headers, col_idx, matches, reason)
        for row_idx in reversed(matches):
            ws.delete_rows(row_idx, 1)
        style_sheet(ws, date_columns=("Consegna", "Delivery Date"))
        safe_save_workbook(wb, path)
        return len(matches)
    finally:
        wb.close()


@_serialized_workbook_write
def delete_shared_rows(path: Path, partita_cols, sheet_name: str) -> int:
    """Manually delete selected rows from either Orders or PG-X."""
    return _delete_shared_rows(path, partita_cols, sheet_name, "deleted")


@_serialized_workbook_write
def delete_shipped_shared_rows(path: Path, partita_cols, sheet_name: str) -> int:
    """Delete rows in one shared-workbook sheet whose Partita Col shipped."""
    return _delete_shared_rows(path, partita_cols, sheet_name, "shipped/invoiced")
