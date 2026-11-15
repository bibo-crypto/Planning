# tests — FAILURE

- commit: `ca02676` on `main` — feat(shared-order, shared-orders, situazione-loaders): 3 added, 6 mod…
- run: https://github.com/bibo-crypto/Planning/actions/runs/43749337471
- event: push   |   report written: 2026-11-15 18:58 UTC

## Jobs

| job | result | failed steps |
|---|---|---|
| pytest (3.14) | failure | Run the test suite |
| pytest (3.12) | failure | Run the test suite |

## pytest — pytest-log-py3.12

`2 failed, 865 passed, 7 skipped in 139.76s (0:02:19)`

Failed / errored:

- `FAILED tests/test_shared_orders_window.py::test_the_editor_shows_stock_of_the_right_raw_article_in_green - AssertionError: assert 'Partita GG i...emain in PG-X' == 'Available: 4...article: G101'`
- `FAILED tests/test_shared_orders_window.py::test_the_editor_flags_a_wrong_raw_article_and_an_unknown_partita_in_red - AssertionError: assert ('Partita GG i...emain in PG-X' == 'Wrong articl...99 (5 rocche)'`

Skipped (reason):

- `SKIPPED [1] tests\test_category_integration.py:210: no display available`
- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`

## pytest — pytest-log-py3.14

`2 failed, 866 passed, 6 skipped in 166.24s (0:02:46)`

Failed / errored:

- `FAILED tests/test_shared_orders_window.py::test_the_editor_shows_stock_of_the_right_raw_article_in_green - AssertionError: assert 'Partita GG i...emain in PG-X' == 'Available: 4...article: G101'`
- `FAILED tests/test_shared_orders_window.py::test_the_editor_flags_a_wrong_raw_article_and_an_unknown_partita_in_red - AssertionError: assert ('Partita GG i...emain in PG-X' == 'Wrong articl...99 (5 rocche)'`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
