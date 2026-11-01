"""Create (EXCEL+Biglietti): converting the order of ONE customer.

Single responsibility: given a request (which customer, which files, where to write)
and the shared lookup data, produce that customer's Excel workbook, Word tickets and
-- for ELVY and MED -- the optional Filato file and the shared Show Orders rows.
No Tk in here: the page gathers its state into a ConversionRequest, runs this on a
worker thread and shows the returned summary.

A customer is converted on its own, so converting one never touches, deletes or
overwrites the files of another.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from calculate.raw_batch import is_assigned_raw
from exporters.biglietti_exporter import (
    _filato_rows,
    append_create_excel,
    build_el_kamal_excel_stem,
    build_el_kamal_stem,
    build_output_stem,
    detect_order_format,
    enrich_records,
    export_word,
    export_workbook,
    load_el_kamal_order,
    load_order,
)
from pipelines.ordini_elvy import RawYarnMatch, export_filato_full

# customer page -> (ERP customer code, name used by the exporters)
CUSTOMERS = {
    "elvy": ("3009", "ELVY"),
    "med": ("3004", "MED"),
    "el_kamal": ("3019", "EL_KAMAL"),
}
FILATO_FILE_NAME = "Filato x Tinturia {customer}.xlsx"   # one file per customer: they share one folder


@dataclass(frozen=True)
class ConversionRequest:
    """Everything one customer's conversion needs, as plain values."""
    kind: str                                  # "elvy" | "med" | "el_kamal"
    data_path: Path
    dispo_path: Path | None
    template: Path
    output_dir: Path
    filato_dir: Path | None = None             # ELVY / MED: write the raw-yarn file there
    shared_excel: Path | None = None           # ELVY / MED: the Show Orders workbook
    hide_kamal_quantities: bool = True         # EL KAMAL: leave Rocche / KG empty


@dataclass(frozen=True)
class CommonSources:
    """The shared lookup data every conversion reads (see BigliettiTab._load_common_sources)."""
    codes_map: Any = None
    densita_map: Any = None
    vmm_ratio_map: Any = None
    price_lookup: Any = None
    magazino_summary: Any = None


@dataclass
class ConversionResult:
    """What a conversion produced."""
    items: list[str] = field(default_factory=list)     # human-readable lines for the final message
    files: list[Path] = field(default_factory=list)    # the customer's files, for "Prepare Email"
    filato_file: Path | None = None                    # the raw-yarn file, not part of the e-mail
    tickets: int = 0


def customer_records(kind: str, data_path: Path, dispo_path: Path | None):
    """(records, raw_rows, order_format) of ``kind`` read from the order file.

    An Ordine Kamal workbook belongs to the EL KAMAL page only; an ERP dump holds every
    customer and is filtered here.  Raises ValueError when the file has no row for the
    customer (or is the wrong kind of file for it)."""
    code, _name = CUSTOMERS[kind]
    order_format = detect_order_format(data_path)
    if order_format == "EL_KAMAL":
        if kind != "el_kamal":
            raise ValueError("This file is an Ordine Kamal workbook: convert it from the EL KAMAL page.")
        records, raw = load_el_kamal_order(data_path, dispo_path)
    else:
        records, raw = load_order(data_path, dispo_path)
        records = [record for record in records if record.customer_code == code]
    if not records:
        raise ValueError(f"No {CUSTOMERS[kind][1].replace('_', ' ')} rows (customer {code}) found in the selected order file.")
    return records, raw, order_format


def convert_customer(request: ConversionRequest, sources: CommonSources) -> ConversionResult:
    """Convert the order of ``request.kind`` and return what was created."""
    if not request.template or not Path(request.template).is_file():
        raise ValueError("Forma Biglietti not found. Select the Biglietti.docx template first.")
    records, raw, _format = customer_records(request.kind, request.data_path, request.dispo_path)
    if request.kind == "el_kamal":
        return _convert_kamal(request, records, raw, sources)
    return _convert_shared_customer(request, records, raw, sources)


def _enrich(records, customer: str, sources: CommonSources) -> None:
    enrich_records(
        records, customer, codes_map=sources.codes_map, densita_map=sources.densita_map,
        vmm_ratio_map=sources.vmm_ratio_map, price_lookup=sources.price_lookup,
    )


def _split_pg_x(records):
    """(ready, waiting): ready rows hold one of our raw batches; the others wait in PG-X."""
    ready, waiting = [], []
    for record in records:
        (ready if is_assigned_raw(record.raw_batch, record.customer_code) else waiting).append(record)
    return ready, waiting


def _convert_shared_customer(request: ConversionRequest, records, raw, sources: CommonSources) -> ConversionResult:
    """ELVY and MED: workbook + tickets (ready ones, and the PG-X ones in their own file),
    the rows appended to the Show Orders workbook, and the optional Filato file."""
    _code, customer = CUSTOMERS[request.kind]
    out_dir = Path(request.output_dir)
    stem = build_output_stem(records, customer)
    suffix = "" if customer == "ELVY" else f"_{customer}"          # ELVY: PO-1500-2026.xlsx / .docx
    xlsx, docx = out_dir / f"{stem}{suffix}.xlsx", out_dir / f"{stem}{suffix}.docx"
    pgx_docx = docx.with_name(f"{docx.stem}-pg-x{docx.suffix}")

    _enrich(records, customer, sources)
    export_workbook(xlsx, records, raw, include_filato=True, stem=stem, customer=customer,
                    magazino_summary=sources.magazino_summary)
    result = ConversionResult(tickets=len(records), files=[xlsx])
    shared = append_create_excel(request.shared_excel, records, customer) if request.shared_excel else None

    ready, waiting = _split_pg_x(records)
    if ready:
        export_word(docx, request.template, ready, stem=stem)
        result.files.append(docx)
    if waiting:
        export_word(pgx_docx, request.template, waiting, stem=f"{stem}-PG-X")
        result.files.append(pgx_docx)

    word_text = ", ".join(path.name for path in result.files[1:]) or "no Word tickets"
    line = f"• {customer}: {len(records)} tickets ({word_text})\n   ↳ Saved to: {xlsx}"
    if shared:
        line += f"\n   ↳ Shared Excel: +{shared['added']} rows, {shared['skipped']} duplicate Partita Col skipped"
    result.items.append(line)

    if request.filato_dir and raw:
        filato_dir = Path(request.filato_dir)
        filato_dir.mkdir(parents=True, exist_ok=True)
        filato_file = filato_dir / FILATO_FILE_NAME.format(customer=customer)
        matches = [
            RawYarnMatch(articolo=row["Articolo"], titolo=row["Titolo"], partita=row["Partita"],
                         rocce=row["Rocche"], peso=row["Peso"], label=row["تحضير خام"])
            for row in _filato_rows(records, raw, sources.magazino_summary)
        ]
        count = export_filato_full(filato_file, matches)
        result.filato_file = filato_file
        result.items.append(f"• Raw Yarn (Filato) {customer}: {filato_file.name} ({count} rows)\n   ↳ Saved to: {filato_file}")
    return result


def _convert_kamal(request: ConversionRequest, records, raw, sources: CommonSources) -> ConversionResult:
    """EL KAMAL: a workbook and the tickets -- no Show Orders workbook, no Filato file."""
    out_dir = Path(request.output_dir)
    ticket_stem = build_el_kamal_stem(records)
    excel_stem = build_el_kamal_excel_stem(records)
    xlsx, docx = out_dir / f"{excel_stem}_EL_KAMAL.xlsx", out_dir / f"{ticket_stem}.docx"

    _enrich(records, "EL_KAMAL", sources)
    export_workbook(xlsx, records, raw, include_filato=True, stem=ticket_stem, customer="EL_KAMAL",
                    magazino_summary=sources.magazino_summary,
                    hide_kamal_quantities=request.hide_kamal_quantities)
    export_word(docx, request.template, records, stem=ticket_stem,
                hide_kamal_quantities=request.hide_kamal_quantities)
    return ConversionResult(
        tickets=len(records), files=[xlsx, docx],
        items=[f"• EL KAMAL: {len(records)} tickets ({docx.name})\n   ↳ Saved to: {xlsx}"],
    )
