"""البحث في الجداول المرجعية: الأسعار، الكثافة، تاريخ التسليم، Marca/Titolo، VMM22.

جزء من حزمة exporters.biglietti (انظر ARCHITECTURE_AR.md). الواجهة القديمة
exporters/biglietti_exporter.py تعيد تصدير كل الأسماء من هنا."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import openpyxl

from exporters.biglietti.fields import _clean, _key, _number
from exporters.biglietti.loaders import _get, _read_sheet_rows
from exporters.biglietti.records import OrderRecord
from utility.utils import logger


def load_articoli_titolo_map() -> dict[str, str]:
    try:
        import utility.situazione_db as situazione_db
        return situazione_db.load_codes()  # {articolo_filato: titolo}
    except Exception:
        logger.warning("Yarn codes could not be loaded from SQLite; titles will be empty", exc_info=True)
        return {}


def load_articoli_marca_map(path: Path) -> tuple[dict[str, str], list[str]]:
    """Articolo Filato -> Marca (the fuller descriptive text, e.g.
    '100/2 - COTTON 100%') -- confirmed against real data as the actual
    source for the ticket's Titolo, NOT the shorter 'TITOLO' column that
    Situazione's own Articoli upload uses."""
    from utility import disk_cache
    return disk_cache.cached_load(
        "articoli_marca", path, lambda: _load_articoli_marca_map_uncached(path),
        is_valid=lambda result: bool(result[0]),
    )


def _load_articoli_marca_map_uncached(path: Path) -> tuple[dict[str, str], list[str]]:
    """Read Articoli.xlsx (Sheet2, or the active sheet) into {ARTICOLO FILATO: Marca}.
    Returns (map, errors); an empty map is reported as an error.
    """
    errors: list[str] = []
    out: dict[str, str] = {}
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        target = wb["Sheet2"] if "Sheet2" in wb.sheetnames else wb.active
        for row in _read_sheet_rows(target):
            art = _clean(_get(row, "Articolo Filato")).upper()
            marca = _clean(_get(row, "Marca"))
            if art and marca:
                out.setdefault(art, marca)
    finally:
        wb.close()
    if not out:
        errors.append("Nessuna riga Articolo Filato/Marca trovata nel file Articoli.")
    return out, errors


def load_articoli_marca_lookup() -> dict[str, str]:
    """Return Articoli Marca from SQLite first; Excel is upload-only."""
    try:
        from utility.source_manager import load as load_source
        frame = load_source("articoli_marca")
        if frame is not None and not frame.empty and {"articolo", "marca"}.issubset(frame.columns):
            return {str(r.articolo).strip().upper(): str(r.marca).strip()
                    for r in frame.itertuples(index=False) if str(r.articolo).strip() and str(r.marca).strip()}
    except Exception as _ignored:
        logger.debug("exporters.biglietti.lookups.load_articoli_marca_lookup: ignored %r", _ignored)
    return {}


def _titolo_lookup(articolo: str, codes_map: dict[str, str]) -> str:
    art = _clean(articolo).upper()
    if not art or not codes_map:
        return ""
    if art in codes_map:
        return codes_map[art]
    if art[:1] in ("C", "G"):
        swapped = ("G" if art[:1] == "C" else "C") + art[1:]
        if swapped in codes_map:
            return codes_map[swapped]
    return ""


# ---------------------------------------------------------------------------
# Prezzo lookup -- reuses the existing Listini/Prezzi infrastructure
# (prezzi_cache remembers the last uploaded file; no separate button needed
# here since the Prezzi tab already provides one).
# ---------------------------------------------------------------------------

_PREZZO_LOOKUP_CACHE: tuple[str, int, int, tuple, dict[tuple, tuple], str] | None = None


def load_prezzo_lookup() -> tuple[dict[tuple, tuple], str]:
    """Runtime lookup: SQLite first, with a one-time legacy-file fallback."""
    global _PREZZO_LOOKUP_CACHE
    try:
        from calculate import prezzi as prezzi_logic
        from utility import situazione_db
        from utility.source_manager import is_current
        from utility.source_manager import load as load_source
        from utility.source_manager import source_name
        if is_current("listini"):
            # Keyed by the snapshot's CONTENT fingerprint: a new Listini with the same
            # number of rows and columns (only prices changed) must not reuse the old
            # lookup, and checking it first avoids re-reading ~10k rows on every call.
            fingerprint = situazione_db.snapshot_fingerprint("listini")
            if fingerprint:
                key = ("sqlite", fingerprint, prezzi_logic.category_sources_fingerprint())
                if _PREZZO_LOOKUP_CACHE and _PREZZO_LOOKUP_CACHE[:3] == key:
                    return _PREZZO_LOOKUP_CACHE[3], _PREZZO_LOOKUP_CACHE[4]
                df = load_source("listini")
                if df is not None and not df.empty:
                    # Rows saved before a category was assigned/removed keep their old
                    # CATEGORY; re-applying the rules makes manual assignments count.
                    df = prezzi_logic.enrich_categories(df)
                    lookup = prezzi_logic.build_price_lookup(df)
                    name = source_name("listini") or "SQLite"
                    _PREZZO_LOOKUP_CACHE = (*key, lookup, name)
                    return lookup, name
    except Exception:
        # A failing SQLite read used to be a one-line debug note; it decides whether prices exist at all.
        logger.warning("Prezzi lookup could not be read from SQLite; trying the configured workbook", exc_info=True)
    # Legacy/test compatibility: if an installation has no SQLite Listini
    # snapshot yet, allow the explicitly configured workbook to be imported.
    try:
        import calculate.prezzi as prezzi_logic
        import utility.prezzi_cache as prezzi_cache
        cache = prezzi_cache.load_prezzi_cache()
        path = cache.get("source_path")
        if not path or not Path(path).is_file():
            return {}, ""
        source = Path(path)
        stat = source.stat()
        key = (str(source), stat.st_mtime_ns, stat.st_size, prezzi_logic.category_sources_fingerprint())
        if _PREZZO_LOOKUP_CACHE and _PREZZO_LOOKUP_CACHE[:4] == key:
            return _PREZZO_LOOKUP_CACHE[4], _PREZZO_LOOKUP_CACHE[5]
        df, errors = prezzi_logic.load_prezzi(path)
        if df is None or df.empty or errors:
            return {}, ""
        lookup = prezzi_logic.build_price_lookup(df)
        source_file = cache.get("source_file", "")
        _PREZZO_LOOKUP_CACHE = (*key, lookup, source_file)
        return lookup, source_file
    except Exception:
        logger.warning("Prezzi lookup could not be loaded; continuing without prices", exc_info=True)
        return {}, ""


# ---------------------------------------------------------------------------
# Delivery Date (ELVY only) -- how many working days out an order is quoted,
# based on whether the raw batch/yarn is already assigned (Partita GG) and
# whether it's already priced (Prezzo), plus which machine tier it's on.
# Working days skip Friday (pushed to Saturday if a computed date lands on
# one) -- matches the 'AddDaysSkipFriday' Power Query logic exactly.
# ---------------------------------------------------------------------------
_DELIVERY_MACHINES_LONG = {7, 8, 9, 10, 11, 12}
_DELIVERY_MACHINES_MED = {3, 4, 5, 6}


def _add_days_skip_friday(start_date, days_to_add: int):
    target = start_date + timedelta(days=days_to_add)
    if target.weekday() == 4:  # Friday
        target += timedelta(days=1)
    return target


def _compute_delivery_date(raw_batch: Any, prezzo: Any, machine: Any, today=None) -> Any:
    """Delivery date of a colour line, or "Pending for yarn" while it has no raw batch.
    The lead time depends on the machine group (8, 16 or 24 days when there is no price) and is counted from today.
    """
    if not _clean(raw_batch):
        return "Pending for yarn"
    today = today or datetime.now().date()
    try:
        mc = int(_number(machine))
    except (TypeError, ValueError):
        mc = None
    has_prezzo = prezzo not in (None, "")
    if not has_prezzo:
        if mc in _DELIVERY_MACHINES_LONG:
            days = 24
        elif mc in _DELIVERY_MACHINES_MED:
            days = 16
        else:
            days = 8
    else:
        if mc in _DELIVERY_MACHINES_LONG:
            days = 16
        elif mc in _DELIVERY_MACHINES_MED:
            days = 8
        else:
            days = 0
    return _add_days_skip_friday(today, days)


def compute_delivery_date(records: list["OrderRecord"]) -> None:
    today = datetime.now().date()
    for r in records:
        r.delivery_date = _compute_delivery_date(r.raw_batch, r.prezzo, r.machine, today)


def _prezzo_match_for(articolo: str, codice: str, lookup: dict[tuple, tuple]) -> tuple[Any, bool, str, Any]:
    """Find the Listini price for one order line.

    Tries an exact (article, colour) match over every spelling of the colour code;
    an unambiguous direct match wins.  Otherwise falls back to the article's
    category price for that colour.
    Returns (price, from_category, category, level): from_category is True when the
    price came from the category fallback; price is "" when nothing matched.
    """
    if not lookup:
        return "", False, "", None
    from calculate.prezzi import _price_color_variants

    article = _clean(articolo).upper()
    code = _clean(codice)
    direct_matches: list[tuple[Any, Any]] = []
    for color_variant in _price_color_variants(code):
        for key in ((article, color_variant), (_clean(articolo), color_variant)):
            if key not in lookup:
                continue
            level, price = lookup[key]
            try:
                has_price = price is not None and float(price) != 0
            except (TypeError, ValueError):
                has_price = bool(_clean(price))
            if has_price and (level, price) not in direct_matches:
                direct_matches.append((level, price))
    if len(direct_matches) == 1:
        level, price = direct_matches[0]
        return price, False, "", level
    category = lookup.get(("__ARTICLE_CATEGORY__", article), "")
    if not category:
        try:
            category = load_articoli_marca_lookup().get(article, "")
        except Exception:
            logger.debug("Articoli/marca lookup failed for %r; category left empty", article, exc_info=True)
            category = ""
    if category:
        category_key = str(category).casefold()
        value = next(
            (
                lookup[("__CATEGORY__", color_variant, category_key)]
                for color_variant in _price_color_variants(code)
                if ("__CATEGORY__", color_variant, category_key) in lookup
            ),
            None,
        )
        if value:
            level, price = value
            if price is not None and price != 0:
                return price, True, str(category), level
    return "", False, str(category), None


def _prezzo_for(articolo: str, codice: str, lookup: dict[tuple, tuple]) -> Any:
    return _prezzo_match_for(articolo, codice, lookup)[0]


# Public alias -- other tabs (Situazione) reuse this same matching logic
# for their own Prezzo column instead of re-implementing it.
prezzo_for = _prezzo_for
prezzo_match_for = _prezzo_match_for


# Machines (by their Rocche-based M/C total, e.g. Situazione's own 'mc'
# field or Ordine MED's) that get a $2 surcharge on top of the Listini
# price. Shared here since both Ordine MED's 'PREZZO + 2$' column and
# Situazione's own Prezzo column apply the exact same rule.
# The same machines may appear as capacity (24/32/56) or as the operator's
# machine number (12/9/10) in Situazione and the editing dialogs.
PREZZO_SURCHARGE_MACHINES = {24, 32, 56}


def apply_machine_surcharge(price: Any, machine: Any) -> Any:
    """price + 2 when machine is 24/32/56 Rocche, otherwise price
    unchanged. machine may be an int, numeric string, or None/blank --
    anything that doesn't cleanly parse just skips the surcharge rather
    than raising."""
    if not isinstance(price, (int, float)):
        return price
    try:
        mc = int(_number(machine))
    except (TypeError, ValueError):
        return price
    return round(price + 2, 2) if mc in PREZZO_SURCHARGE_MACHINES else price


# ---------------------------------------------------------------------------
# Densita' Query workbook -- KG (PESO ROCCHE query) + Densita`(360-390),
# both keyed by Partita (raw_batch / "Partita GG").
# ---------------------------------------------------------------------------

def load_densita_query(path: Path | None = None) -> tuple[dict[int, dict[str, Any]], list[str]]:
    """Read an explicitly selected workbook; otherwise use the shared SQLite snapshot."""
    if path is not None:
        if not Path(path).is_file():
            return {}, [f"Densita' Query file not found: {path}"]
        from utility import disk_cache
        return disk_cache.cached_load(
            "densita_query", path, lambda: _load_densita_query_uncached(Path(path)),
            is_valid=lambda result: bool(result[0]),
        )

    try:
        from utility.source_manager import load as load_source
        frame = load_source("densita_lookup")
        if frame is not None and not frame.empty and "partita" in frame.columns:
            out = {}
            for row in frame.itertuples(index=False):
                partita = int(row.partita)
                values = {}
                for field in ("peso_net", "color_tube", "densita"):
                    if hasattr(row, field):
                        value = getattr(row, field)
                        if value is not None and str(value) != "nan":
                            values[field] = value
                out[partita] = values
            return out, []
    except Exception as _ignored:
        logger.debug("exporters.biglietti.lookups.load_densita_query: ignored %r", _ignored)
    return {}, ["Densita' Query is not stored in SQLite yet. Upload it once to update the database."]


def _load_densita_query_uncached(path: Path) -> tuple[dict[int, dict[str, Any]], list[str]]:
    """Read the density query workbook (sheet "Entry") into {partita: {peso_net, color_tube, ...}}.
    Net weight is derived from the gross weight (minus 45, in kg).  Returns (map, errors).
    """
    errors: list[str] = []
    out: dict[int, dict[str, Any]] = {}
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        sheet_by_key = {_key(name): name for name in wb.sheetnames}
        entry_sheet = sheet_by_key.get(_key("Entry"))
        density_sheet = sheet_by_key.get(_key("Densita")) or sheet_by_key.get(_key("Densità"))
        if entry_sheet:
            for row in _read_sheet_rows(wb[entry_sheet]):
                partita = _number(_get(row, "PARTITA", "Partita"))
                peso_lord = _number(_get(row, "Peso Lord", "Peso Lordo"))
                if partita is None:
                    continue
                peso_net = (peso_lord - 45) / 1000 if peso_lord is not None else None
                out.setdefault(int(partita), {})["peso_net"] = peso_net
                color_tube = _clean(_get(row, "Colore Tube", "Color Tube"))
                if color_tube:
                    out[int(partita)]["color_tube"] = color_tube
        else:
            errors.append('Nel file Densita\' Query.xlsx manca il foglio "Entry" (serve per KG).')
        if density_sheet:
            for row in _read_sheet_rows(wb[density_sheet]):
                partita = _number(_get(row, "PARTITA", "Partita"))
                if partita is None:
                    continue
                out.setdefault(int(partita), {})["densita"] = _get(row, "Densita` (360-390)", "Densita")
        else:
            errors.append('Nel file Densita\' Query.xlsx manca il foglio "Densita" (serve per Densita`(360-390)).')
    finally:
        wb.close()
    if not out and not errors:
        errors.append("Nessuna riga valida trovata nel file Densita' Query.")
    return out, errors


# ---------------------------------------------------------------------------
# Magazino (Color Tube) workbook -- Color Tube + kg-per-cone by Partita,
# used for the Biglietti "Color Tube" and "VMM22" columns. This is a
# different file from the raw-yarn Magazino used elsewhere in the app.
# ---------------------------------------------------------------------------

def load_vmm22_ratio_from_magazino(path: Path | None) -> tuple[dict[int, float], list[str]]:
    """{PARTITA: kg-per-cone}, using the SQLite Magazino snapshot first."""
    try:
        from utility.source_manager import load as load_source
        frame = load_source("magazino_summary")
        if frame is not None and not frame.empty and {"partita", "mag_rocche", "mag_peso"}.issubset(frame.columns):
            ratio = {}
            for row in frame.itertuples(index=False):
                rocche = float(getattr(row, "mag_rocche") or 0)
                peso = float(getattr(row, "mag_peso") or 0)
                if rocche:
                    ratio[int(row.partita)] = peso / rocche
            if ratio:
                return ratio, []
    except Exception as _ignored:
        logger.debug("exporters.biglietti.lookups.load_vmm22_ratio_from_magazino: ignored %r", _ignored)
    if path is None or not Path(path).is_file():
        return {}, ["Magazino is not stored in SQLite yet. Upload it once to update the database."]
    """{PARTITA: kg-per-cone} for VMM22, from the same raw Magazino Filato
    export already uploaded elsewhere in the app (Magazino Filato /
    Ordine Kamal tabs, cached path in magazino_cache.py) -- no separate
    upload needed. Per Partita: sum ESISTENZA (kg) and COLLI (cones)
    across MAGAZZINO 900910, 900160 and 900923, ratio = kg per cone.
    VMM22 for an order line = that ratio * the line's own Rocche."""
    from utility import disk_cache
    return disk_cache.cached_load(
        "vmm22_ratio", path, lambda: _load_vmm22_ratio_from_magazino_uncached(path),
        is_valid=lambda result: bool(result[0]),
    )


def _load_vmm22_ratio_from_magazino_uncached(path: Path) -> tuple[dict[int, float], list[str]]:
    """Compute the VMM22 ratio per partita from the Magazino file: the sum of ESISTENZA divided by the sum of COLLI, over warehouses 900910, 900160 and 900923.
    Returns ({partita: ratio}, errors).
    """
    errors: list[str] = []
    totals: dict[int, list[float]] = {}  # partita -> [esistenza_sum, colli_sum]
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        for row in _read_sheet_rows(wb.active):
            magazzino = _number(_get(row, "MAGAZZINO"))
            if magazzino not in (900910, 900160, 900923):
                continue
            partita = _number(_get(row, "PARTITA"))
            if partita is None:
                continue
            esistenza = _number(_get(row, "ESISTENZA")) or 0
            colli = _number(_get(row, "COLLI")) or 0
            bucket = totals.setdefault(int(partita), [0.0, 0.0])
            bucket[0] += esistenza
            bucket[1] += colli
    finally:
        wb.close()
    out = {p: (e / c) for p, (e, c) in totals.items() if c}
    if not out:
        errors.append("Nessuna riga valida trovata nel file Magazino Filato per VMM22.")
    return out, errors
