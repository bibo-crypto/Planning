#!/usr/bin/env bash
# Publish a report folder (made by ci/make_report.py) to the ``ci-reports`` branch of a repository.
#
#   ci/publish_report.sh <remote url> <report dir> [label]
#
# The branch holds only report files (latest/<workflow>.md|json and history/*), never code, so it can be
# read without any token by anyone who can read the repository.  It is created on first use (orphan branch).
# Pushes made with the workflow's GITHUB_TOKEN do not start new workflow runs, so this cannot loop.
set -euo pipefail

REMOTE="${1:?remote url}"
REPORT_DIR="${2:?report dir}"
LABEL="${3:-update}"
BRANCH="${CI_REPORTS_BRANCH:-ci-reports}"
KEEP_HISTORY="${CI_REPORTS_KEEP:-60}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

if git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
  git clone --quiet --branch "$BRANCH" --single-branch "$REMOTE" "$work"
else
  git init --quiet "$work"
  git -C "$work" checkout --quiet --orphan "$BRANCH"
  git -C "$work" remote add origin "$REMOTE"
fi

cd "$work"
git config user.name "ci-report"
git config user.email "ci-report@users.noreply.github.com"

mkdir -p latest history
cp -f "$REPORT_DIR"/latest/* latest/
cp -f "$REPORT_DIR"/history/* history/

# keep the newest $KEEP_HISTORY history files (names start with a UTC timestamp, so a name sort is a time sort)
extra="$(ls -1 history | sort | head -n "-$KEEP_HISTORY" || true)"
if [ -n "$extra" ]; then
  # plain rm: a file that is only in the work tree (just copied) is not tracked yet, `git add -A` records the deletions
  while IFS= read -r name; do rm -f -- "history/$name"; done <<< "$extra"
fi

if [ ! -f README.md ]; then
  cat > README.md <<'README'
# CI reports

Written automatically by the `ci-report` workflow after each `tests` / `windows-exe` run.
Start with `latest/tests.md` and `latest/windows-exe.md` (same content as `.json` for tools); older runs are in `history/`.
This branch contains no source code.
README
fi

git add -A
if git diff --cached --quiet; then
  echo "nothing new to publish"
  exit 0
fi
git commit --quiet -m "ci-report: ${LABEL}"

for attempt in 1 2 3 4 5; do
  if git push --quiet origin "HEAD:refs/heads/${BRANCH}"; then
    echo "published to ${BRANCH}"
    exit 0
  fi
  echo "push rejected (attempt ${attempt}); rebasing on the latest ${BRANCH}"
  git fetch --quiet origin "$BRANCH"
  git rebase --quiet "origin/${BRANCH}" || { git rebase --abort || true; }
  sleep $((attempt * 2))
done
echo "could not publish the report after 5 attempts" >&2
exit 1
