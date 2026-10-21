"""utility.output_cleanup: only the named customer's generated files are removed."""
from utility.output_cleanup import (
    CUSTOMER_OUTPUT_PATTERNS,
    clear_previous_outputs,
    register_output_patterns,
)


def _touch(folder, *names):
    paths = [folder / name for name in names]
    for path in paths:
        path.write_text("x", encoding="utf-8")
    return paths


def test_removes_only_the_customers_files_and_reports_them(tmp_path):
    elvy_old, elvy_new, med = _touch(tmp_path, "PO-1_ELVY.xlsx", "PO-2_ELVY.xlsx", "MED-D-1-2026_MED.xlsx")
    removed = clear_previous_outputs(tmp_path, "elvy", keep={elvy_new})
    assert removed == [elvy_old]
    assert elvy_new.exists() and med.exists() and not elvy_old.exists()


def test_a_missing_folder_or_unknown_customer_removes_nothing(tmp_path):
    (survivor,) = _touch(tmp_path, "PO-1_ELVY.xlsx")
    assert clear_previous_outputs(tmp_path / "nope", "ELVY") == []
    assert clear_previous_outputs(tmp_path, "UNKNOWN") == []
    assert survivor.exists()


def test_a_new_customer_needs_only_a_registry_entry(tmp_path):
    (mine,) = _touch(tmp_path, "ACME-7_ACME.xlsx")
    register_output_patterns("acme", ("ACME-*_ACME.xlsx",))
    try:
        assert clear_previous_outputs(tmp_path, "ACME") == [mine]
    finally:
        CUSTOMER_OUTPUT_PATTERNS.pop("ACME", None)
