"""Remove the previous generated files of one customer from an output folder.

Single responsibility: knowing WHICH files a customer's export produces and
deleting only those.  The Create (EXCEL+Biglietti) page used to hold this logic
inline; it now just calls ``clear_previous_outputs``.

Open/closed: the file-name shapes live in ``CUSTOMER_OUTPUT_PATTERNS`` -- a new
customer is one new entry (or ``register_output_patterns``), no code changes.
"""
from __future__ import annotations

from pathlib import Path

# Every pattern is anchored to the exact file-name shape that customer's export
# produces, so a folder shared by several customers (or by another page) never
# loses files that are not theirs:
#   * MED stems always start with "MED-" ("MED-D-<n>-<year>" / "MED-<year>"),
#     which keeps the Ordine MED page's own "Ordine_MED.xlsx" safe.
#   * Kamal tickets are "D-<n>-KAMAL-<year>_Biglietti.docx" or
#     "KAMAL-<year>_Biglietti.docx"; a bare "*_Biglietti.docx" would also match
#     the ELVY and MED ticket files.
CUSTOMER_OUTPUT_PATTERNS: dict[str, tuple[str, ...]] = {
    "ELVY": ("*_ELVY.xlsx", "*_ELVY_Biglietti.docx", "*_ELVY_Biglietti-pg-x.docx"),
    "MED": ("MED-*_MED.xlsx", "MED-*_MED_Biglietti.docx", "MED-*_MED_Biglietti-pg-x.docx"),
    "EL_KAMAL": ("*_EL_KAMAL.xlsx", "D-*-KAMAL-*_Biglietti.docx", "KAMAL-*_Biglietti.docx"),
}


def register_output_patterns(customer: str, patterns: tuple[str, ...]) -> None:
    """Teach the cleanup about a new customer's output file-name patterns."""
    CUSTOMER_OUTPUT_PATTERNS[customer.upper()] = tuple(patterns)


def clear_previous_outputs(output_dir: Path, customer: str, keep: set[Path] | None = None) -> list[Path]:
    """Delete the previous generated files of ``customer`` in ``output_dir``.

    Files listed in ``keep`` (the ones about to be written) are protected, as is
    everything that does not match the customer's patterns.  A file that cannot
    be deleted (e.g. open in Excel/Word) is left alone: the export that follows
    reports that error far more usefully than a cleanup would.
    Returns the files that were removed.
    """
    protected = {path.resolve() for path in (keep or set())}
    if not output_dir.is_dir():
        return []
    removed: list[Path] = []
    for pattern in CUSTOMER_OUTPUT_PATTERNS.get(customer.upper(), ()):
        for path in output_dir.glob(pattern):
            if path.resolve() in protected:
                continue
            try:
                path.unlink()
                removed.append(path)
            except OSError:
                pass
    return removed
