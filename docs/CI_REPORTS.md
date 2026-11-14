# CI reports (the `ci-reports` branch)

After every finished **tests** or **windows-exe** run, the `ci-report` workflow writes a short report to the
`ci-reports` branch, so a run's result can be read straight from the repository instead of downloading logs.

| file on the branch | content |
|---|---|
| `latest/tests.md` / `latest/tests.json` | newest `tests` run: commit, job results and failed steps, pytest counts per Python version, failed/errored tests, skip reasons |
| `latest/windows-exe.md` / `latest/windows-exe.json` | newest `windows-exe` run: jobs, and the packaged-EXE smoke log (`Planning started` must appear twice: empty profile, then restart) |
| `history/<UTC time>_<commit>_<workflow>.md` | the last 60 reports |

Read it without a token, e.g. `https://raw.githubusercontent.com/<owner>/<repo>/ci-reports/latest/tests.md`
(or `git fetch origin ci-reports`).

How it works: `.github/workflows/ci-report.yml` (trigger: `workflow_run`) downloads the finished run's artifacts,
`ci/make_report.py` turns them into the report, `ci/publish_report.sh` pushes it to the branch. The branch holds
only report files, never code. The workflow runs from the default branch's copy of the scripts, never for forks, and
a push made with `GITHUB_TOKEN` does not start other workflows, so it cannot loop. It needs the repository's
workflow permissions to allow the `contents: write` it requests (Settings > Actions > General).

If a report never appears: the workflow file must be on `main` and at least one `tests` run must finish after it
was pushed; open the **Actions** tab > `ci-report` for its own log.
