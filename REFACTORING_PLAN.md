# Refactoring plan (SOLID review)

Status of the review done on 2026-10-21.  Everything below is backed by the test
suite (`pytest`, 345 tests) and a headless start-up of the real window that opens
every tab (17 pages, 0 Tk callback errors).

## Done in this pass

| Principle | Change |
|-----------|--------|
| DRY / SRP | One price rule: `calculate/situazione.py` `parse_price`, `listini_loaded`, `price_issue`.  The "errori prezzi colori" table, the red rows of Situazione Generale and the price notifications all use it (they used to hold three copies that disagreed: a Prezzo Ord. without a Listini price was never listed or highlighted). |
| DRY / SRP | `utility/ui_thread.post_to_ui`: the single place where a worker thread hands a result to the Tk main loop (replaced ~60 raw `widget.after(0, ...)` calls).  A window closed mid-task no longer kills the worker with a traceback. |
| SRP | `calculate/raw_batch.py`: one definition of what a Partita GG value means (ours / MED customer lot / none) used by Smart Auto-Assign, printing and the PG-X report. |
| SRP | Kamal colour handling: `parsers/dfm_lookup.colour_name_key` / `lookup_dfm_color_by_name` (matching rule) is separate from `pipelines/ordine_kamal.resolve_kamal_colours` (applying it to rows). |
| Docs | Docstrings on 474 of the 517 functions/classes longer than 14 lines (91%); 667 of 1108 definitions overall (60%). |

## Findings that still need work (in priority order)

1. **God mixins in the GUI.** `SharedOrdersWindowMixin` (~760 lines),
   `SharedOrdersActionsMixin` (~750), `SituationSourcesMixin` (~640),
   `BigliettiTab` (~740) mix widget building, business rules and threading in one
   class.  Target: move the rules into plain modules with no Tk imports
   (`shared_orders_service`, `situazione_sources_service`) and keep the mixins as
   thin views.  `_open_shared_orders_window` is a single 500-line function whose
   inner functions share state through closures -- turn it into a small class.
2. **Long functions** (cyclomatic complexity E/F, from `radon cc -n D`):
   `biglietti_tab._run_convert` (42), `kamal_tab._run_conversion` (39),
   `shared_order_actions._smart_auto_assign_pg_x` (39),
   `purchase_orders._run_po_conversion` (36), `pdf_parser._lines_to_rows` (41),
   `master_import._route` (49), `prezzi.build_price_lookup` (49),
   `situazione._compute_new_comm` (45), `biglietti_exporter.save_pg_x_partita` (42),
   `append_create_excel` (39), `load_order` (37).  Split each into named steps
   (validate -> load -> transform -> write); the existing tests pin the behaviour.
3. **Duplicated Excel export styling** in `magazino_filato_tab._on_export`,
   `situazione_tab._on_export` / `_export_abbina`, `situazione_settimana_tab._on_export`,
   `prezzi_tab._write_export_file`: extract one `write_styled_table(...)` helper
   (the Kamal/Elvy/Bolla exporters already share `exporters/excel_common`).
4. **`exporters/biglietti_exporter.py` (2300 lines)** holds loading, enrichment,
   Excel writing and Word writing.  Split into `loaders`, `enrichment`,
   `excel_writer`, `word_writer` (keep the current module as a re-exporting facade
   so imports and tests do not change).
5. **Dependency direction.** Pipelines import GUI-agnostic helpers, but several
   `gui` modules import `exporters.biglietti_exporter` private names (`_style_sheet`,
   `_prezzo_match_for`).  Give those a public name first, then depend on it.
6. **Docstrings** for the remaining 43 functions of 15+ lines and the ~400 shorter
   ones (mostly one-line UI handlers).
7. **CI.** There is no `.github/workflows` file; `publish.py` expects tests to run
   before a push.  Add a workflow that runs `pytest` on `windows-latest`.

## How to refactor safely

Run `pytest` after every step, keep each commit to one move, and never change
behaviour and structure in the same commit.
