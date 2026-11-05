"""Guards for import direction and import-order safety (complements test_architecture_rules.py).

The layers are utility < parsers/calculate < exporters < pipelines < gui.  A handful of
imports already run "upwards" (most of them inside functions, which is what keeps them
from becoming import cycles).  They work and are covered by tests, so they are listed
here explicitly; the test fails only when a NEW upward import appears, so the list can
shrink but never silently grow.
"""
import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RANK = {"utility": 1, "parsers": 2, "calculate": 2, "exporters": 3, "pipelines": 4, "gui": 5}

# (file, imported module) pairs that already go "upwards" -- see the module docstring.
KNOWN_UPWARD_IMPORTS = {
    ("calculate/prezzi.py", "exporters.biglietti_exporter"),
    ("exporters/column_catalog.py", "pipelines.ordine_med"),
    ("exporters/excel_exporter.py", "pipelines.ordini_elvy"),
    ("exporters/kamal_excel_exporter.py", "pipelines.ordine_kamal"),
    ("exporters/kamal_excel_exporter.py", "pipelines.ordini_elvy"),
    ("utility/master_data.py", "calculate"),
    ("utility/source_hub.py", "exporters.biglietti_exporter"),
    ("utility/source_hub.py", "parsers.dfm_lookup"),
}


def _upward_imports():
    found = set()
    for layer in RANK:
        for path in (ROOT / layer).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    target = node.module.split(".")[0]
                    if target in RANK and RANK[target] > RANK[layer]:
                        found.add((path.relative_to(ROOT).as_posix(), node.module))
    return found


def test_no_new_upward_import_has_appeared():
    new = sorted(_upward_imports() - KNOWN_UPWARD_IMPORTS)
    assert not new, (
        "new import(s) from a lower layer into a higher one: "
        f"{new}. Move the shared piece down instead, or (if truly intended) add it to KNOWN_UPWARD_IMPORTS."
    )


# Modules on either side of the lazy imports above.  A module-level import added later
# would turn them into a real cycle, which only shows up for some import orders -- so
# each one is imported first in a fresh interpreter.
ENTRY_MODULES = [
    "calculate.prezzi", "exporters.biglietti_exporter", "exporters.column_catalog", "exporters.excel_exporter",
    "exporters.kamal_excel_exporter", "pipelines.ordine_kamal", "pipelines.ordine_med", "pipelines.ordini_elvy",
    "utility.master_data", "utility.source_hub",
]


@pytest.mark.parametrize("module", ENTRY_MODULES)
def test_module_imports_cleanly_when_it_is_the_first_one_imported(module):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-c", f"import {module}"], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-800:]
