"""Guards for the structure documented in ARCHITECTURE_AR.md (so it cannot silently rot)."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NON_GUI_LAYERS = ("calculate", "parsers", "pipelines", "exporters", "utility")
# exporters/biglietti: each module may import only from the modules before it in this list.
BIGLIETTI_ORDER = ["records", "fields", "machines", "loaders", "lookups", "enrichment",
                   "workbook_io", "excel_writer", "shared_workbook", "word_writer"]


def _imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_only_the_gui_layer_imports_gui():
    offenders = [
        f"{path.relative_to(ROOT)} imports {module}"
        for layer in NON_GUI_LAYERS for path in (ROOT / layer).rglob("*.py")
        for module in _imports(path) if module.split(".")[0] == "gui"
    ]
    assert not offenders, offenders


def test_biglietti_modules_depend_only_on_earlier_ones():
    package = ROOT / "exporters" / "biglietti"
    for position, name in enumerate(BIGLIETTI_ORDER):
        allowed = {f"exporters.biglietti.{earlier}" for earlier in BIGLIETTI_ORDER[:position]}
        used = {m for m in _imports(package / f"{name}.py") if m.startswith("exporters.biglietti.")}
        assert used <= allowed, f"{name} imports {sorted(used - allowed)}"
    assert {p.stem for p in package.glob("*.py")} - {"__init__"} == set(BIGLIETTI_ORDER)


def test_old_biglietti_exporter_import_path_still_works():
    from exporters import biglietti_exporter as facade
    from exporters.biglietti import excel_writer, word_writer
    assert facade.export_workbook is excel_writer.export_workbook
    assert facade.export_word is word_writer.export_word
    assert facade._style_sheet is facade.style_sheet
