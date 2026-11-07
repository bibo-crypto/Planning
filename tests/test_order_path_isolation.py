from types import SimpleNamespace
from unittest.mock import Mock

from gui.tabs import biglietti_tab, ordine_med_tab


def test_biglietti_order_selection_saves_only_its_page_preference(tmp_path, monkeypatch):
    order_file = tmp_path / "biglietti-order.xlsx"
    order_file.touch()
    page = SimpleNamespace(
        _pick_file=Mock(return_value=str(order_file)),
        _set_mirrored_label=Mock(),
        _save_prefs=Mock(),
    )
    monkeypatch.setattr(
        biglietti_tab,
        "save_source",
        Mock(side_effect=AssertionError("order paths must not be shared")),
    )

    biglietti_tab.BigliettiTab._pick_data(page)

    assert page.data_path == order_file
    page._save_prefs.assert_called_once_with(biglietti_data_path=str(order_file))


def test_ordine_med_order_selection_saves_only_its_page_preference(tmp_path, monkeypatch):
    order_file = tmp_path / "ordine-med-order.xlsx"
    order_file.touch()
    page = SimpleNamespace(_lbl_ordine=Mock(), _save_prefs=Mock())
    monkeypatch.setattr(ordine_med_tab.filedialog, "askopenfilename", lambda **_kwargs: str(order_file))

    ordine_med_tab.OrdineMedTab._on_select_ordine(page)

    assert page.ordine_path == order_file
    page._save_prefs.assert_called_once_with(ordine_med_data_path=str(order_file))


def test_biglietti_restore_does_not_fall_back_to_ordine_med_order_path(tmp_path, monkeypatch):
    shared_order = tmp_path / "legacy-shared-order.xlsx"
    shared_order.touch()
    source_lookups = []
    page = SimpleNamespace(
        _prefs={},
        data_path=None,
        dispo_path=None,
        template_path=None,
        shared_excel_path=None,
        _set_mirrored_label=Mock(),
        _set_dir_label=Mock(),
        _refresh_show_orders_page=Mock(),
        kamal_hide_quantities=Mock(),
        email_templates={},
        _sender_email="",
    )
    monkeypatch.setattr(
        biglietti_tab,
        "source_path",
        lambda source: source_lookups.append(source) or shared_order,
    )
    monkeypatch.setattr(biglietti_tab, "load_articoli_cache", lambda: {})
    monkeypatch.setattr(biglietti_tab, "load_densita_cache", lambda: {})
    monkeypatch.setattr(biglietti_tab, "load_magazino_cache", lambda: {})
    monkeypatch.setattr(biglietti_tab, "load_prezzi_cache", lambda: {})

    biglietti_tab.BigliettiTab._restore(page)

    assert page.data_path is None
    assert "data_ordine" not in source_lookups


def test_ordine_med_restore_does_not_fall_back_to_biglietti_order_path(tmp_path, monkeypatch):
    shared_order = tmp_path / "legacy-shared-order.xlsx"
    shared_order.touch()

    def variable():
        return SimpleNamespace(set=Mock())

    page = SimpleNamespace(
        _prefs={},
        _lbl_output=Mock(),
        _lbl_erp=Mock(),
        _lbl_filato=Mock(),
        _lbl_ordine=Mock(),
        _lbl_magazino=Mock(),
        _lbl_densita=Mock(),
        erp_enabled=variable(),
        filato_enabled=variable(),
        bagno_enabled=variable(),
        bagno_start_var=variable(),
        ordine_path=None,
    )
    monkeypatch.setattr(ordine_med_tab, "load_magazino_cache", lambda: {})
    monkeypatch.setattr(ordine_med_tab, "load_densita_cache", lambda: {})

    ordine_med_tab.OrdineMedTab._restore_saved_paths(page)

    assert page.ordine_path is None
