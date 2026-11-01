"""
situazione_loaders.py
Reads each of the 6 raw source files, finds the real header row (these ERP
exports sometimes have a title row or a duplicated header row above the
data), validates that the expected columns exist, and returns a clean
pandas DataFrame plus a list of problems (empty list = OK).
"""
import datetime as _dt
import os
import re

import pandas as pd

# Cache of already-parsed raw sheets, keyed by (path, sheet_name, mtime_ns,
# size). Several tabs independently need the same DFM/Produzione/Listini
# export in the same running session (Situazione, Situazione Settimana,
# Ordine MED, Biglietti, the cross-tab background sync...), and these are
# frequently old .xls exports -- pandas has to use the pure-Python xlrd
# engine for those (openpyxl only reads .xlsx/.xlsm), which is dramatically
# slower than openpyxl on anything but a small sheet, especially when the
# file's Excel "used range" is bloated by years of manual formatting far
# past the real data. Memoizing the raw read here means each distinct file
# only pays that cost once per session, no matter how many tabs ask for it,
# and the cache still invalidates itself the moment the file is replaced
# (mtime/size check) so a re-uploaded/edited file is never served stale.
_RAW_SHEET_CACHE: dict[tuple, pd.DataFrame] = {}


def _read_raw(path, sheet_name=0):
    key = None
    try:
        stat = os.stat(path)
        key = (str(path), sheet_name, stat.st_mtime_ns, stat.st_size)
    except OSError:
        pass  # fall through to an uncached read; let pandas raise the real error
    if key is not None and key in _RAW_SHEET_CACHE:
        return _RAW_SHEET_CACHE[key]
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
    if key is not None:
        _RAW_SHEET_CACHE[key] = raw
    return raw


def _find_header_row(raw, required_cols, search_rows=20):
    """Scan the first few rows for the one that contains all required_cols."""
    required_set = {_header_key(value) for value in required_cols}
    for r in range(min(search_rows, len(raw))):
        row_vals = {_header_key(v) for v in raw.iloc[r].tolist() if v is not None}
        if required_set.issubset(row_vals):
            return r
    return None


def _header_key(value):
    """Compare Excel headers while ignoring accidental spaces/case differences."""
    return " ".join(str(value).strip().split()).casefold()


def _s(series):
    """Convert a column to string safely: missing values become '' instead of the literal text 'nan'."""
    return series.fillna("").astype(str).str.strip()


def _load_with_header(path, required_cols, sheet_name=0):
    """Read a sheet whose header row is not necessarily the first line.
    Finds the row holding the required columns, uses it as the header, drops a repeated header row and returns (DataFrame | None, [error messages]).
    """
    raw = _read_raw(path, sheet_name=sheet_name)
    header_row = _find_header_row(raw, required_cols)
    if header_row is None:
        return None, [f"Expected header row was not found. The file must contain: {', '.join(required_cols)}"]

    df = raw.iloc[header_row + 1:].copy()
    raw_headers = raw.iloc[header_row].tolist()
    required_by_key = {_header_key(value): value for value in required_cols}
    df.columns = [required_by_key.get(_header_key(value), value) for value in raw_headers]

    # some exports repeat the header row right after it -- drop it if so
    if len(df) and all(str(df.iloc[0][c]).strip() == str(c).strip() for c in required_cols):
        df = df.iloc[1:]

    df = df.reset_index(drop=True)
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        return None, [f"Missing required columns: {', '.join(missing)}"]

    # some exports repeat a header-like row further down (or with slightly
    # different blank columns) -- drop any row whose first required column
    # still literally equals that column's own name.
    first_col = required_cols[0]
    df = df[df[first_col].astype(str) != str(first_col)]
    df = df.reset_index(drop=True)
    return df, []


# ---------------------------------------------------------------------------
# Each loader below returns (DataFrame or None, errors:list)
# ---------------------------------------------------------------------------

def load_wincoint_orders(path):
    """WINCOINT sheet / Table3: raw customer orders.

    In the current Wincoint export the display fields are positional:
    column F is Codice and column G is Colore.  The remaining fields are
    resolved by their header names so blank/extra columns cannot shift them.
    """
    required = ["Cliente", "Articolo", "Data",
                "Consegna", "Partita", "Ordinata", "Descrizione aggiuntiva ordine", "Bagno"]
    df, errors = _load_with_header(path, required)
    if df is None:
        return None, errors
    df = df[df["Partita"].notna()]
    df = df[df["Partita"].astype(str).str.strip() != ""]
    df = df[df["Partita"].astype(str) != "Partita"]
    df = df[df["Cliente"] != "TOTALE GENERALE"]
    if len(df.columns) < 7:
        return None, ["Wincoint must contain at least columns A through G (Codice and Colore)."]

    out = pd.DataFrame({
        "cliente": _s(df["Cliente"]),
        "articolo": _s(df["Articolo"]),
        "codice": _s(df.iloc[:, 5]),        # Wincoint column F -> Codice
        "colore": _s(df.iloc[:, 6]),        # Wincoint column G -> Colore
        "ordine": _s(df["Ordine"]) if "Ordine" in df.columns else "",  # no positional fallback: wrong index risks silently duplicating Codice
        "riga": _s(df["Riga"]) if "Riga" in df.columns else "",
        "data": pd.to_datetime(df["Data"], errors="coerce"),
        "consegna": pd.to_datetime(df["Consegna"], errors="coerce"),
        "partita": _s(df["Partita"]),
        "rocche": df["Ordinata"],
        "comment": _s(df["Descrizione aggiuntiva ordine"]),
        "cq": _s(df["Bagno"]),
        # The price actually entered in Wincoint for this Articolo+Codice
        # (per-machine surcharge already baked in on the ERP side, if any).
        # Optional/name-based like Ordine/Riga: some exports omit it, and a
        # missing column must never break the rest of the load.
        "prezzo": _s(df["Prezzo"]) if "Prezzo" in df.columns else "",
    })
    return out, []


def load_dfm(path):
    """DFM sheet / Table8: machine + batch (Bagno) info."""
    required = ["DESCRIZIONECDMACCHINA", "PARTITADFM", "NUMEROPROGRAMMANEWDFM", "ARTICOLODFM"]
    df, errors = _load_with_header(path, required)
    if df is None:
        return None, errors
    df = df[df["NUMEROPROGRAMMANEWDFM"] != "NUMEROPROGRAMMANEWDFM"]
    split = df["DESCRIZIONECDMACCHINA"].astype(str).str.split(" ", n=1, expand=True)
    out = pd.DataFrame({
        "partita": _s(df["PARTITADFM"]),
        "mc": pd.to_numeric(split[0], errors="coerce"),
        "bagno": _s(df["NUMEROPROGRAMMANEWDFM"]),
        "articolo": _s(df["ARTICOLODFM"]),
    })
    out = out.sort_values("partita")
    return out, []


def load_data_prod(path):
    """Data prod. sheet: when a batch finished production (End Prod.)."""
    required = ["Partia Col", "End", "Rilavorazione"]
    df, errors = _load_with_header(path, required)
    if df is None:
        return None, errors
    df = df[(df["Partia Col"].notna()) & (df["Partia Col"] != "PROVA") & (df["Rilavorazione"] == 0)]
    end_split = df["End"].astype(str).str.split(" ", n=1, expand=True)
    out = pd.DataFrame({
        "partita": _s(df["Partia Col"]),
        "end_prod": _s(end_split[0]).str.replace(".", "/", regex=False),
    })
    out = out.drop_duplicates(subset="partita")
    return out, []


# Header names (compared with _header_key) under which the Copertura export may
# carry the end of a batch.
_BATCH_END_HEADERS = {"batch end", "batch finish", "batch stop", "end batch", "fine batch", "batch fine"}


_DURATION_RE = re.compile(r"^\s*(\d+):(\d{1,2})(?::(\d{1,2}))?\s*$")


def _parse_duration(value):
    """"7:56" / 7:56:00 / an Excel time / a fraction of a day -> Timedelta (NaT when unreadable)."""
    if value is None:
        return pd.NaT
    try:
        if pd.isna(value):
            return pd.NaT
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timedelta):
        return value
    if isinstance(value, _dt.timedelta):
        return pd.Timedelta(value)
    if isinstance(value, _dt.datetime):
        value = value.time()
    if isinstance(value, _dt.time):
        return pd.Timedelta(hours=value.hour, minutes=value.minute, seconds=value.second)
    if isinstance(value, (int, float)):
        return pd.Timedelta(days=float(value)) if 0 < float(value) < 1 else pd.Timedelta(hours=float(value))
    match = _DURATION_RE.match(str(value))
    if not match:
        return pd.NaT
    hours, minutes, seconds = int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)
    return pd.Timedelta(hours=hours, minutes=minutes, seconds=seconds)


def load_schedulato(path):
    """Copertura sheet (Sheet1): machine batch queue -> PlaneDate per Bagno."""
    required = ["N. Bagno", "Machine", "Batch Start"]
    df, errors = _load_with_header(path, required)
    if df is None:
        return None, errors
    df = df[df["N. Bagno"].notna()].copy()
    df["N. Bagno"] = _s(df["N. Bagno"])
    df["Machine"] = _s(df["Machine"])
    df["BatchDT"] = pd.to_datetime(df["Batch Start"], errors="coerce", dayfirst=True)
    # Optional: when the OrgaTEX export also carries the batch end, the machine
    # timeline draws each colour with its real length (otherwise it estimates).
    end_column = next((c for c in df.columns if _header_key(c) in _BATCH_END_HEADERS), None)
    df["BatchEndDT"] = (
        pd.to_datetime(df[end_column], errors="coerce", dayfirst=True) if end_column is not None else pd.NaT
    )
    # The OrgaTEX queue export has "Set time (HH:MM)": how long the batch runs.
    # Start + Set time is the real end of the colour on the machine.
    set_time_column = next((c for c in df.columns if _header_key(c).startswith("set time")), None)
    if set_time_column is not None:
        durations = df[set_time_column].map(_parse_duration)
        from_set_time = df["BatchDT"] + durations
        df["BatchEndDT"] = df["BatchEndDT"].where(df["BatchEndDT"].notna(), from_set_time)
    df = df.sort_values(["Machine", "BatchDT"])
    df["RowID"] = df.groupby("Machine").cumcount()

    def plan_date_for(group):
        """Planned dates of one batch group, in RowID order: row 0 is "IN MACC.", the others are the batch start date plus RowID // 2 days, pushed one day for every Friday crossed."""
        group = group.sort_values("RowID").reset_index(drop=True)
        start_date = group.loc[0, "BatchDT"]
        dates = []
        for _, r in group.iterrows():
            if r["RowID"] == 0:
                dates.append("IN MACC.")
                continue
            if pd.isna(start_date):
                dates.append(None)
                continue
            base_days = r["RowID"] // 2
            tentative = start_date + pd.Timedelta(days=base_days)
            # skip Fridays: add one day for every Friday crossed in the range
            date_range = pd.date_range(start_date, tentative, freq="D")
            fridays = sum(1 for d in date_range if d.dayofweek == 4)  # Monday=0 .. Friday=4
            final_date = tentative + pd.Timedelta(days=fridays)
            dates.append("PROD." + final_date.strftime("%d/%m/%Y"))
        group["PlaneDate"] = dates
        return group

    # Iterate the groups (rather than groupby.apply) so the Machine column survives on every pandas version.
    df = pd.concat([plan_date_for(group) for _, group in df.groupby("Machine")], ignore_index=True)
    out = pd.DataFrame({
        "bagno": df["N. Bagno"],
        "planedate": df["PlaneDate"],
        # Keep the scheduling fields as well: the Copertura dashboard uses
        # them to group the current colours by physical machine.
        "machine": df["Machine"],
        "batch_start": df["BatchDT"],
        "batch_end": df["BatchEndDT"],
    })
    return out, []


def load_uscita(path):
    """Uscita(J) sheet: warehouse exit date per Partita (shipped)."""
    required = ["Partita", "Bagno", "Data Mandato", "Contro Magazzino"]
    df, errors = _load_with_header(path, required)
    if df is None:
        return None, errors
    df = df[df["Contro Magazzino"].isin([3004, 3009, "3004", "3009"])]
    out = pd.DataFrame({
        "partita": _s(df["Partita"]),
        "data_uscita": pd.to_datetime(df["Data Mandato"], errors="coerce"),
    })
    out = out.dropna(subset=["data_uscita"]).drop_duplicates(subset="partita")
    return out, []


def load_qualita(path):
    """Qualita sheet: quality-check date per Partita."""
    required = ["Partita", "Bagno", "Data Mandato"]
    df, errors = _load_with_header(path, required)
    if df is None:
        return None, errors
    out = pd.DataFrame({
        "partita": _s(df["Partita"]),
        "data_qualita": pd.to_datetime(df["Data Mandato"], errors="coerce"),
    })
    out = out.sort_values(["partita", "data_qualita"]).drop_duplicates(subset="partita")
    return out, []


def load_codes(path):
    """Optional reference table: Articolo Filato -> Titolo. Uploaded rarely."""
    required = ["Articolo Filato", "TITOLO"]
    df, errors = _load_with_header(path, required)
    if df is None:
        return None, errors
    out = pd.DataFrame({
        "articolo_filato": _s(df["Articolo Filato"]),
        "titolo": _s(df["TITOLO"]),
    })
    out = out.drop_duplicates(subset="articolo_filato")
    return out, []


def load_produzione(path):
    """
    Raw production log (Situazione Settimana): one row per process event,
    with the machine, batch (Partia Col), weight (Peso), yarn code, and the
    date it was logged. Current Data Prod exports call that column ``End``;
    older weekly exports may call it ``Sheet Date``. Rework entries (Codice
    ending in "RI" or "T.C") are excluded, matching the original report's
    own rework flag.
    """
    required = ["Machine Name", "Partia Col", "Peso", "Codice"]
    df, errors = _load_with_header(path, required)
    if df is None:
        return None, errors
    date_column = "Sheet Date" if "Sheet Date" in df.columns else "End"
    if date_column not in df.columns:
        return None, ["Expected a production date column named End or Sheet Date"]

    df = df[df["Partia Col"].notna()]
    df = df[df["Partia Col"].astype(str) != "Partia Col"]
    is_rework = _s(df["Codice"]).str.upper().str.endswith(("RI", "T.C"))
    df = df[~is_rework]

    out = pd.DataFrame({
        "partita": _s(df["Partia Col"]),
        "machine_name": _s(df["Machine Name"]),
        "peso": pd.to_numeric(df["Peso"], errors="coerce"),
        "sheet_date": pd.to_datetime(df[date_column], errors="coerce", dayfirst=True),
    })
    out = out.dropna(subset=["partita"])
    out["week_of_year"] = out["sheet_date"].dt.isocalendar().week
    return out, []


def load_produzione_colors(path):
    """Produzione export -> the dye colour of every batch (for the machine timeline).

    ``Color RGB`` holds text such as ``RGB(153/133/116)``.  Besides the colour each
    row keeps what can identify it: Partita Colore (``Partia Col``), Bagno, and the
    colour itself (``Codice`` + ``Des.Colore``) -- a batch that has not been dyed yet
    is not in the file by Bagno, but the same colour was usually dyed before.
    Rows are ordered oldest -> newest so the latest colour wins when a key repeats.
    Returns (DataFrame[partita, bagno, codice, colore, rgb], errors).
    """
    from calculate.machine_timeline import parse_rgb

    required = ["Partia Col", "Color RGB"]
    df, errors = _load_with_header(path, required)
    if df is None:
        return None, errors

    def column(*names):
        wanted = {_header_key(n) for n in names}
        found = next((c for c in df.columns if _header_key(c) in wanted), None)
        return _s(df[found]) if found is not None else pd.Series([""] * len(df), index=df.index)

    out = pd.DataFrame({
        "partita": _s(df["Partia Col"]),
        "bagno": column("Bagno", "N. Bagno"),
        "codice": column("Codice"),
        "colore": column("Des.Colore", "Des. Colore", "Colore"),
        "rgb": [parse_rgb(v) for v in df["Color RGB"]],
    })
    start = column("Start")
    out["_when"] = pd.to_datetime(start, errors="coerce", dayfirst=True)
    out = out[out["rgb"].notna()].sort_values("_when", kind="stable", na_position="first")
    out = out.drop(columns="_when").reset_index(drop=True)
    return out, []


LOADERS = {
    "wincoint": ("Customer orders (WINCOINT)", load_wincoint_orders),
    "dfm": ("Machine data (DFM)", load_dfm),
    "data_prod": ("Production data", load_data_prod),
    "copertura": ("Schedule", load_schedulato),
    "uscita": ("Warehouse exit", load_uscita),
    "qualita": ("Quality check", load_qualita),
}
