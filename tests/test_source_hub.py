"""Source hub: page file lists, the density reader and the path reconciliation."""
import openpyxl

from exporters.biglietti_exporter import load_densita_query
from pipelines import master_import
from utility import source_hub as hub


def test_every_page_lists_known_sources():
    for page, keys in hub.PAGE_SOURCES.items():
        assert keys, page
        assert all(key in hub.SOURCES for key in keys), page
        assert len(keys) == len(set(keys)), page


def test_pages_that_need_the_files_the_user_named():
    assert hub.PAGE_SOURCES["ordine_med"] == ["articoli", "dfm", "listini", "magazino", "lotti"]
    assert {"dfm", "magazino", "lotti"} <= set(hub.PAGE_SOURCES["ordine_kamal"])
    assert set(hub.PAGE_SOURCES["biglietti"]) == {"articoli", "densita", "magazino", "listini"}


def test_reconcile_writes_the_best_path_into_every_store(tmp_path, monkeypatch):
    file = tmp_path / "MAGAZINO.xlsx"
    file.write_text("x")
    stores = {"path_manager": str(file), "legacy": ""}
    calls = []
    monkeypatch.setattr(hub, "stored_path", lambda key: str(file) if key == "magazino" else "")
    monkeypatch.setattr(hub, "_mirror_store_values", lambda key: [stores["path_manager"], stores["legacy"]])
    monkeypatch.setattr(hub, "mirror_path", lambda key, path: calls.append((key, path)))
    assert hub.reconcile_paths() == {"magazino": str(file)}
    assert calls == [("magazino", str(file))]
    stores["legacy"] = str(file)
    calls.clear()
    assert hub.reconcile_paths() == {} and calls == []


def test_explicit_density_file_is_read_instead_of_an_old_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "Densita Query.xlsx"
    workbook = openpyxl.Workbook()
    entry = workbook.active
    entry.title = "ENTRY"
    entry.append(["PARTITA", "Peso Lord", "Color Tube"])
    entry.append([12345, 1550, "T1"])
    density = workbook.create_sheet("Densità")
    density.append(["PARTITA", "Densita` (360-390)"])
    density.append([12345, 380])
    workbook.save(path)

    monkeypatch.setattr(
        "utility.source_manager.load",
        lambda _name: {"partita": [999], "densita": [1]},
    )
    density_map, errors = load_densita_query(path)

    assert errors == []
    assert density_map == {12345: {"peso_net": 1.505, "color_tube": "T1", "densita": 380}}


def test_single_workbook_density_sheet_pair_uses_shared_density_import(tmp_path, monkeypatch):
    path = tmp_path / "Master.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.title = "ENTRY"
    workbook.create_sheet("Densità")
    workbook.save(path)
    calls = []
    monkeypatch.setattr(hub, "save_densita", lambda source: (calls.append(source) or (1, [])))

    loaded, skipped = master_import.import_master_file(
        str(path), situazione_tab=None, magazino_tab=None,
    )

    assert calls == [str(path)]
    assert "Densita' Query" in loaded
    assert "Densita' Query" not in skipped


def test_directory_density_file_uses_shared_density_import(tmp_path, monkeypatch):
    path = tmp_path / "Densita Query.xlsx"
    path.write_bytes(b"workbook")
    calls = []
    monkeypatch.setattr(hub, "save_densita", lambda source: (calls.append(source) or (1, [])))

    loaded, _skipped = master_import.import_master_directory(
        tmp_path, situazione_tab=None, magazino_tab=None,
    )

    assert calls == [str(path)]
    assert any(item.startswith("Densita' Query (") for item in loaded)
