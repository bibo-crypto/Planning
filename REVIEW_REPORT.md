# Planning 1.1.11 — Review Report

## Scope

The attached archive `Planning_1.1.11_merged.zip` was unpacked and reviewed without modifying the original uploaded archive. The requested MED bath-sequence feature was implemented only in the separate working copy and then refined against the supplied screenshot example.

## Verification

| Check | Result |
|---|---|
| Python bytecode compilation | PASS |
| Full automated test suite before feature | **243 passed** |
| Full automated test suite after feature | **247 passed** |
| GUI smoke test in this sandbox | Not executed: the environment has no graphical display (`$DISPLAY`) |
| ZIP/archive integrity | Original archive unpacked successfully |

## Findings

### Critical defects

No reproducible critical defect was found in the automated checks.

### Important operational notes

1. **GUI startup needs a desktop/display.** `test_startup.py` creates `ConverterApp()` directly and is not headless-safe. This is an environment limitation rather than an application regression, but a CI pipeline should run it under Windows or Xvfb.
2. **Development test dependencies are not listed in `requirements.txt`.** The runtime dependencies are present, but `pytest` is used by the repository tests and should be installed separately in a development/CI requirements file.
3. **Some GUI worker paths use broad exception handling.** This prevents user-facing crashes, but can hide source/cache problems in logs. No failing behavior was exposed by the current tests; future hardening should add more specific logging around those paths.
4. **Excel output is generated asynchronously.** This is correct for responsiveness, but manual acceptance should verify that users do not open/lock the target workbook while conversion is writing it.

## Implemented MED feature

The MED tab now includes:

- A text field for the first bath, e.g. `T1200`.
- A checkbox named **Use bagno sequence**.
- Default state: **disabled**.
- The value is persisted in application preferences.
- Invalid values are rejected unless they match letters plus a number, such as `T1200`.

When enabled, the sequence is calculated in source-row order. A group qualifies only if consecutive rows share:

- the same five-digit-normalized colour code;
- the same machine (`GRUPPO MACCHINA`); and
- the same non-zero `ABBIN`.

The sequence advances once per contiguous row group. For a qualifying split group, the first row is left blank and the following rows receive the bath. For rows without a qualifying group, the output remains blank. The internal calculation also records **Bagno Reale** for every sequential group. The value written to the ERP-facing column is **BAGNO PREPOSTO** in:

- `Ordine_MED.xlsx` → `Dati sistema (B-N)`;
- the separate ERP workbook `EXCEL PER ORDINE VENDITA EGITTO.xlsx`.

Example result for a repeated MED colour/machine/ABBIN group:

```text
Bagno Reale:     T1200, T1201, T1201, T1202
Bagno Preposato: blank,  blank,  T1201, blank
```

## Files changed in the working copy

- `pipelines/ordine_med.py`
- `gui/tabs/ordine_med_tab.py`
- `tests/test_regressions.py`

## Recommendation

After Convert finishes (success or error), First bagno is cleared and Use bagno sequence is automatically disabled.

The implementation is ready for MED-only user acceptance with a real ORDINE workbook. The next validation should compare the two generated workbooks against one known-good MED order, especially rows where the same colour appears on adjacent rows with the same machine and non-zero ABBIN.


## Latest Bagno counter correction

The counter now advances one position for every preceding ABBIN=0 row and one position for each consecutive non-zero ABBIN group. This prevents a preceding run of zero rows from being collapsed by colour/machine matching. The supplied scenario now produces `S1219`, blank, `S1220`, blank, `S1221` after the preceding rows, as requested.
