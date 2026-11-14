"""
source_hub.py
One place that knows every shared input file of the program (no GUI here).

  * which files exist (Articoli, DFM, Listini, Magazino, Lotto, Densità, Produzione,
    Copertura, Wincoint, Uscita, Qualità) and what each page needs (PAGE_SOURCES);
  * whether a file's data is in the program (``is_ready``) and which file it came from
    (``file_label``) -- from SQLite and the saved paths, not from any page's widgets;
  * ``save_densita``: the density workbook -> SQLite (it used to be duplicated on two pages);
  * ``reconcile_paths``: makes the many path stores agree (path_manager, the legacy
    ``*_cache`` files and the SQLite upload log), so a file uploaded on one page is
    known to every other page.

The actual reading of a file stays in each loader; gui.py's ``upload_source`` routes a
chosen file to the right one and the page "source bars" (gui/source_bar.py) show the state.
"""
from __future__ import annotations

import logging
import os
from collections import OrderedDict
from pathlib import Path

logger = logging.getLogger(__name__)

# key -> (button text, long name)
SOURCES: "OrderedDict[str, tuple[str, str]]" = OrderedDict([
    ("articoli", ("Articoli", "Articoli (Titolo / Marca)")),
    ("dfm", ("DFM", "DFM (machine data)")),
    ("listini", ("Listini", "Listini (prices)")),
    ("magazino", ("Magazino", "Magazino (raw yarn stock)")),
    ("lotti", ("LOTTO", "LOTTO (raw yarn lots)")),
    ("densita", ("Densità", "Densità Query")),
    ("produzione", ("Produzione", "Produzione (production + colours)")),
    ("copertura", ("Copertura", "Copertura (machine schedule)")),
    ("wincoint", ("Wincoint", "Wincoint (customer orders)")),
    ("uscita", ("Uscita", "Uscita (warehouse exit)")),
    ("qualita", ("Qualità", "Qualità (quality check)")),
])

# What each page really reads (found by following its code).  Situazione builds its table
# only when all six of its own sources are in, so the pages that use that table list them.
_SITUAZIONE_SIX = ["wincoint", "dfm", "produzione", "copertura", "uscita", "qualita"]

PAGE_SOURCES: dict[str, list[str]] = {
    # Ordine Med: Articoli, DFM, Listini, Magazino and LOTTO. Delivery scheduling
    # comes from the same machine queue shown on Overview.
    "ordine_med": ["articoli", "dfm", "listini", "magazino", "lotti"],
    # Ordine Kamal looks colours up in DFM and matches raw yarn by Magazino + Lotto.
    "ordine_kamal": ["dfm", "magazino", "lotti"],
    # Ordine Elvy: DFM (colour / titolo), Listini (livello / prezzo), raw yarn (Magazino + Lotto).
    "ordine_elvy": ["dfm", "listini", "magazino", "lotti"],
    # Biglietti: Articoli (titolo/marca), Densità, Magazino (stock), Listini (prices).
    "biglietti": ["articoli", "densita", "magazino", "listini"],
    "magazino": ["magazino", "lotti"],
    "prezzi": ["listini", "articoli"],
    "situazione_extra": ["magazino", "lotti", "densita"],
    "overview": ["wincoint", "dfm", "produzione", "copertura", "uscita", "qualita", "magazino", "listini"],
    "timeline": ["copertura", "produzione", "wincoint", "dfm"],
    "settimana": list(_SITUAZIONE_SIX),
    "shared_orders": ["uscita"],
}

# source key -> row of the SQLite upload_log written by the loaders
_UPLOAD_NAME = {
    "dfm": "dfm", "wincoint": "wincoint", "produzione": "data_prod", "copertura": "copertura",
    "uscita": "uscita", "qualita": "qualita", "articoli": "codes", "listini": "listini",
}
# source key -> normalized SQLite snapshot written by the upload
_SNAPSHOT_NAME = {"magazino": "magazino_summary", "lotti": "lotti_summary", "densita": "densita_lookup"}
# source key -> path_manager key
_PATH_KEY = {"produzione": "produzione", "articoli": "articoli", "listini": "listini", "densita": "densita"}


def button_text(key: str) -> str:
    return SOURCES[key][0]


def long_name(key: str) -> str:
    return SOURCES[key][1]


def stored_path(key: str) -> str:
    """Best known file path of a source: the first one that still exists, else the first one known."""
    candidates = _all_paths(key)
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return next((c for c in candidates if c), "")


def _all_paths(key: str) -> list[str]:
    found: list[str] = []

    def add(value) -> None:
        text = str(value or "").strip()
        if text and text not in found:
            found.append(text)

    try:
        from utility.path_manager import load_source
        add(load_source(_PATH_KEY.get(key, key)).get("source_path"))
    except Exception as _ignored:  # noqa: BLE001
        logger.debug("utility.source_hub._all_paths: ignored %r", _ignored)
    for module, loader in _LEGACY_CACHES.get(key, ()):
        try:
            import importlib
            add(getattr(importlib.import_module(module), loader)().get("source_path"))
        except Exception as _ignored:  # noqa: BLE001
            logger.debug("utility.source_hub._all_paths: ignored %r", _ignored)
    try:
        from utility import situazione_db as db
        upload = db.get_upload(_UPLOAD_NAME.get(key, key))
        if upload:
            add(upload.get("file_path"))
        meta = db.snapshot_meta(_SNAPSHOT_NAME.get(key, key))
        if meta:
            add(meta.get("source_path"))
    except Exception as _ignored:  # noqa: BLE001
        logger.debug("utility.source_hub._all_paths: ignored %r", _ignored)
    return found


# The older per-source path files; every one of them must hold the same path.
_LEGACY_CACHES: dict[str, tuple[tuple[str, str], ...]] = {
    "articoli": (("utility.articoli_cache", "load_articoli_cache"),),
    "densita": (("utility.densita_cache", "load_densita_cache"),),
    "magazino": (("utility.magazino_cache", "load_magazino_cache"),),
    "lotti": (("utility.lotti_cache", "load_lotti_cache"),),
    "listini": (("utility.prezzi_cache", "load_prezzi_cache"),),
    "produzione": (("parsers.prod_lookup", "load_prod_cache"),),
    "dfm": (("parsers.dfm_lookup", "load_dfm_cache"),),
}


def is_ready(key: str) -> bool:
    """True when the data of that source is stored in the program (SQLite), whatever page loaded it."""
    try:
        from utility import situazione_db as db
        if key in _UPLOAD_NAME:
            upload = db.get_upload(_UPLOAD_NAME[key])
            if upload and str(upload.get("status", "")).lower() in {"ok", "success", ""}:
                return True
            if key == "dfm":
                return bool(db.snapshot_meta("dfm") or _dfm_pairs_available())
            return bool(db.snapshot_meta(_UPLOAD_NAME[key])) if key == "listini" else False
        name = _SNAPSHOT_NAME.get(key)
        return bool(name and db.snapshot_meta(name))
    except Exception:  # noqa: BLE001
        logger.debug("source status failed for %s", key, exc_info=True)
        return False


def _dfm_pairs_available() -> bool:
    try:
        from parsers.dfm_lookup import load_dfm_pairs
        return bool(load_dfm_pairs())
    except Exception:  # noqa: BLE001
        logger.debug("DFM readiness check failed", exc_info=True)
        return False


def file_label(key: str) -> str:
    """File name the data of a source came from (for the button's tooltip), '' when unknown."""
    try:
        from utility import situazione_db as db
        upload = db.get_upload(_UPLOAD_NAME.get(key, key))
        if upload and upload.get("file_name"):
            return str(upload["file_name"])
    except Exception as _ignored:  # noqa: BLE001
        logger.debug("utility.source_hub.file_label: ignored %r", _ignored)
    path = stored_path(key)
    return os.path.basename(path) if path else ""


def stamp(key: str) -> str:
    """Changes whenever the source is (re)loaded -- used to tell when an upload has finished."""
    try:
        from utility import situazione_db as db
        upload = db.get_upload(_UPLOAD_NAME.get(key, key)) or {}
        snapshot = db.snapshot_fingerprint(_SNAPSHOT_NAME.get(key, _UPLOAD_NAME.get(key, key))) or ""
        return f"{upload.get('uploaded_at', '')}|{snapshot}"
    except Exception:  # noqa: BLE001
        logger.debug("Source stamp could not be read", exc_info=True)
        return ""


# ----------------------------------------------------------------------
# Densità: read once, used by Biglietti / Ordine Med / Situazione
# ----------------------------------------------------------------------
def save_densita(path) -> tuple[int, list[str]]:
    """Read the Densità Query workbook and store it: the path in every path store and
    the data as the ``densita_lookup`` SQLite snapshot.  Returns (rows stored, errors)."""
    import pandas as pd
    from exporters.biglietti_exporter import load_densita_query
    from utility.densita_cache import save_densita_cache
    from utility.path_manager import save_source
    from utility.source_manager import save as save_snapshot

    path = Path(path)
    density_map, errors = load_densita_query(path)
    rows = [{"partita": partita, **values} for partita, values in density_map.items()]
    if not rows:
        return 0, list(errors) or ["No density rows were found in this file."]
    save_snapshot("densita_lookup", pd.DataFrame(rows), path)
    save_densita_cache(path)
    save_source("densita", path)
    try:
        from utility import situazione_db as db
        db.save_upload("densita", path.name, len(rows), "ok", f"✅ {len(rows)} rows - {path.name}", file_path=str(path))
    except Exception:  # noqa: BLE001
        logger.debug("could not log the densita upload", exc_info=True)
    return len(rows), list(errors)


# ----------------------------------------------------------------------
# Keeping every path store in agreement
# ----------------------------------------------------------------------
def mirror_path(key: str, path) -> None:
    """Write *path* into every path store of the source (path_manager + its legacy cache)."""
    path = str(path)
    try:
        from utility.path_manager import save_source
        save_source(_PATH_KEY.get(key, key), path)
    except Exception:  # noqa: BLE001
        logger.debug("path_manager mirror failed for %s", key, exc_info=True)
    savers = {
        "articoli": ("utility.articoli_cache", "save_articoli_cache"),
        "densita": ("utility.densita_cache", "save_densita_cache"),
        "magazino": ("utility.magazino_cache", "save_magazino_cache"),
        "lotti": ("utility.lotti_cache", "save_lotti_cache"),
        "listini": ("utility.prezzi_cache", "save_prezzi_cache"),
        "produzione": ("parsers.prod_lookup", "save_prod_cache"),
    }
    entry = savers.get(key)
    if entry:
        try:
            import importlib
            getattr(importlib.import_module(entry[0]), entry[1])(path)
        except Exception:  # noqa: BLE001
            logger.debug("legacy cache mirror failed for %s", key, exc_info=True)


def _mirror_store_values(key: str) -> list[str]:
    """What each plain path store (path_manager + the legacy cache of the source) holds; '' when empty."""
    values: list[str] = []
    try:
        from utility.path_manager import load_source
        values.append(str(load_source(_PATH_KEY.get(key, key)).get("source_path") or ""))
    except Exception:  # noqa: BLE001
        logger.debug("Stored source path could not be read", exc_info=True)
        values.append("")
    for module, loader in _LEGACY_CACHES.get(key, ()):
        try:
            import importlib
            values.append(str(getattr(importlib.import_module(module), loader)().get("source_path") or ""))
        except Exception:  # noqa: BLE001
            logger.debug("Legacy source path could not be read", exc_info=True)
            values.append("")
    return values


def reconcile_paths() -> dict[str, str]:
    """For every source: take the best known path and write it into every path store that is
    empty or holds another file.  Returns {key: path} of what was repaired.

    DFM is left alone: its cache holds the parsed entries, and the loader that builds them
    writes the path itself.
    """
    repaired: dict[str, str] = {}
    for key in SOURCES:
        if key == "dfm":
            continue
        best = stored_path(key)
        if not best or not os.path.isfile(best):
            continue
        wanted = os.path.normcase(os.path.normpath(best))
        if any(not v or os.path.normcase(os.path.normpath(v)) != wanted for v in _mirror_store_values(key)):
            mirror_path(key, best)
            repaired[key] = best
    return repaired
