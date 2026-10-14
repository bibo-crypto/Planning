# Performance Report — Planning v1.1.11

Generated: 2026-10-10

## Verification

| Check | Result |
|---|---:|
| Full test suite with virtual display | **PASS — 226 passed** |
| Python compile check | **PASS** |
| Fresh-process GUI startup smoke test | **PASS** |
| Lazy-page traversal in a running Tk event loop | **PASS — 21 distinct page labels reached, no captured page-build errors** |
| Direct-import static checks for the five lazy pages | **PASS** |
| PyInstaller binary build in this environment | **NOT RUN — PyInstaller is not installed and package download is unavailable offline** |

## SQLite changes

- New normalized snapshots use one compact `payload_json` field written through pandas' vectorized serializer. This avoids one Python `json.dumps` call and one SQLite insert per source row.
- Identical uploads update only source metadata after comparing content fingerprints; they do not rewrite an existing compact payload. Changed data is replaced in one transaction.
- Older `source_snapshot_row` snapshots migrate to the compact payload on first read, preserving column order and known datetime columns. Older `frame_cache` snapshots also migrate when first read through `source_manager`.
- `source_manager` now memoizes a defensive copy of each frame by content fingerprint. Subsequent consumers reuse RAM instead of decoding the JSON payload again, while source path/mtime freshness checks remain active.
- WAL mode is configured during DB initialization rather than on every short-lived connection; connections retain a 5-second busy timeout, `synchronous=NORMAL`, and foreign keys.

## Local synthetic benchmark

A 50,000-row, five-column DataFrame was written and read in the local Linux test environment:

| Operation | Measured time |
|---|---:|
| Save a new compact snapshot | 0.072 s |
| First direct SQLite read + JSON decode | 0.110 s |
| First source-manager load in a cold process (SQLite read + JSON decode) | 0.110 s |
| Repeated source-manager load from RAM | 0.002 s |
| Re-save identical data without payload rewrite | 0.033 s |

These are local synthetic measurements, not guarantees for Windows/production data. The first load in a fresh process must still decode the stored payload once.

## Runtime fixes retained from the 1.1.8 review

- Lazy page factories use ordinary imports so PyInstaller can discover Create/Biglietti, Ordine Kamal, Ordine MED, Situazione Settimanale, and Master Data.
- The scheduled PG-X email report initializes the Create page in the background only when enabled and a recipient exists.
- Snapshot metadata restores datetime columns required by `compute_situation`; legacy row snapshots also receive a compatibility migration.
- A snapshot is not served as current when a registered existing source file has changed path/mtime; when that source file is gone, the SQLite snapshot remains usable.
- Price lookup caching keys on the Listini content fingerprint plus category-source fingerprint, so price edits with unchanged row/column counts invalidate the cache.
- DFM is read once per upload and saves each supported prefix plus the complete Article+Color pair set used by `Ordine MED`'s Check Articolo.
- Startup does not show a modal for absent Situazione files.

## Validation limits

The repository was tested on Linux with a virtual display and pandas 2.2.3. A binary PyInstaller build could not be repeated here because PyInstaller is unavailable and network installation is disabled. The AST regression test confirms the lazy modules are import-reachable from normal import statements, but Windows/PyInstaller packaging still needs CI or a Windows build-machine verification.
