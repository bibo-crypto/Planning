# tests — FAILURE

- commit: `1e79dab` on `v1.3.8` — chore(release): bump version to 1.3.6
- run: https://github.com/bibo-crypto/Planning/actions/runs/45211961986
- event: push   |   report written: 2026-11-23 16:08 UTC

## Jobs

| job | result | failed steps |
|---|---|---|
| pytest (3.14) | failure | Run the test suite |
| pytest (3.12) | failure | Run the test suite |

## pytest — pytest-log-py3.12

`9 failed, 1064 passed, 9 skipped in 274.36s (0:04:34)`

Failed / errored:

- `FAILED tests/test_update_script.py::test_when_the_backup_cannot_be_made_the_installation_is_left_exactly_as_it_was - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_copy_that_never_succeeds_rolls_back_to_the_exact_previous_installation - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_new_version_that_never_starts_is_rolled_back_and_the_old_one_relaunched - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_rollback_that_cannot_be_completed_says_so_and_deletes_nothing_more - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_stage_folder_reached_through_its_short_8_3_name_is_verified_correctly - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_stage_folder_with_spaces_and_odd_spellings_is_verified_on_the_first_attempt - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_rolled_back_update_leaves_a_note_for_the_program - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_copy_that_never_completes_gives_the_reason_in_the_note - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_backup_failure_also_leaves_a_note_and_no_stale_note_survives_a_new_update - assert 4 == 2`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
- `SKIPPED [1] tests\test_update_script.py:120: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
- `SKIPPED [1] tests\test_update_script.py:149: needs an unprivileged user: permissions do not bind root (verified by hand with runuser)`
- `SKIPPED [1] tests\test_update_script.py:389: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`

## pytest — pytest-log-py3.14

`9 failed, 1064 passed, 9 skipped in 227.41s (0:03:47)`

Failed / errored:

- `FAILED tests/test_update_script.py::test_when_the_backup_cannot_be_made_the_installation_is_left_exactly_as_it_was - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_copy_that_never_succeeds_rolls_back_to_the_exact_previous_installation - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_new_version_that_never_starts_is_rolled_back_and_the_old_one_relaunched - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_rollback_that_cannot_be_completed_says_so_and_deletes_nothing_more - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_stage_folder_reached_through_its_short_8_3_name_is_verified_correctly - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_stage_folder_with_spaces_and_odd_spellings_is_verified_on_the_first_attempt - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_rolled_back_update_leaves_a_note_for_the_program - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_copy_that_never_completes_gives_the_reason_in_the_note - assert 4 == 2`
- `FAILED tests/test_update_script.py::test_a_backup_failure_also_leaves_a_note_and_no_stale_note_survives_a_new_update - assert 4 == 2`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
- `SKIPPED [1] tests\test_update_script.py:120: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
- `SKIPPED [1] tests\test_update_script.py:149: needs an unprivileged user: permissions do not bind root (verified by hand with runuser)`
- `SKIPPED [1] tests\test_update_script.py:389: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
