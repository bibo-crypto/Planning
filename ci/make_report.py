"""Turn the artifacts and metadata of one finished GitHub Actions run into a short report (Markdown + JSON).

    python ci/make_report.py --artifacts <dir of downloaded artifacts> --meta <run.json from `gh run view --json ...`> --out-dir <dir>

The report is published to the ``ci-reports`` branch by ci/publish_report.sh, so a person -- or a tool that can only
read the repository's files -- sees pytest results, failing tests, skip reasons and the packaged-EXE smoke log
without downloading anything.  Standard library only; it only reads text, it never runs anything from the artifacts.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

MAX_LINES = 40
SUMMARY_RE = re.compile(r"(?P<line>=*\s*(?:\d+ (?:passed|failed|skipped|error|errors|xfailed|xpassed|deselected|warnings?)(?:, )?)+ in [\d.]+s.*)")
COUNT_RE = re.compile(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed|deselected|warnings?)")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").replace("\r", "")


def parse_pytest_log(text: str) -> dict:
    """Counts, failed/errored tests and skip reasons of one pytest log (``-rfEs`` output)."""
    lines = text.splitlines()
    summary = ""
    for line in reversed(lines):
        match = SUMMARY_RE.search(line)
        if match:
            summary = match.group("line").strip("= ").strip()
            break
    counts: dict[str, int] = {}
    for number, word in COUNT_RE.findall(summary):
        counts["error" if word.startswith("error") else word.rstrip("s") if word == "warnings" else word] = int(number)
    return {
        "summary": summary or "no pytest summary line found",
        "counts": counts,
        "failed": [line[:300] for line in lines if line.startswith(("FAILED ", "ERROR "))],
        "skipped": [line[:300] for line in lines if line.startswith("SKIPPED ")],
    }


def parse_exe_logs(files: list[Path]) -> dict:
    """What the packaged-EXE smoke test left behind: its converter.log lines and any hang evidence."""
    log_lines: list[str] = []
    hang_files: list[str] = []
    for path in files:
        if path.name == "startup_hang.log":
            hang_files.append(path.name)
        elif path.name == "converter.log":
            log_lines += _text(path).splitlines()
    started = sum("Planning started: all pages built" in line for line in log_lines)
    problems = [line[:300] for line in log_lines if any(m in line for m in ("Traceback", "ERROR", "could not build"))]
    return {"log_lines": log_lines, "started_count": started, "hang_files": hang_files, "problem_lines": problems}


def _job_rows(meta: dict) -> list[dict]:
    rows = []
    for job in meta.get("jobs", []) or []:
        failed_steps = [step.get("name", "?") for step in job.get("steps", []) or [] if step.get("conclusion") == "failure"]
        rows.append({"name": job.get("name", "?"), "conclusion": job.get("conclusion") or job.get("status", "?"), "failed_steps": failed_steps})
    return rows


def build_report(artifacts: Path, meta: dict) -> tuple[str, dict]:
    pytest_logs = {}
    for path in sorted(artifacts.rglob("pytest.log")):
        pytest_logs[path.parent.name] = parse_pytest_log(_text(path))
    exe_files = [path for path in artifacts.rglob("*.log") if path.name != "pytest.log"]
    exe = parse_exe_logs(exe_files) if exe_files else None
    jobs = _job_rows(meta)

    workflow = meta.get("workflowName") or meta.get("name") or "?"
    sha = str(meta.get("headSha", ""))[:7]
    conclusion = meta.get("conclusion", "?")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = [f"# {workflow} — {conclusion.upper() if isinstance(conclusion, str) else conclusion}", ""]
    out += [f"- commit: `{sha}` on `{meta.get('headBranch', '?')}` — {meta.get('displayTitle', '')}",
            f"- run: {meta.get('url', '')}", f"- event: {meta.get('event', '?')}   |   report written: {now}", ""]

    out += ["## Jobs", "", "| job | result | failed steps |", "|---|---|---|"]
    out += [f"| {row['name']} | {row['conclusion']} | {', '.join(row['failed_steps']) or '-'} |" for row in jobs] or ["| (no job data) | | |"]
    out.append("")

    failed_tests: list[str] = []
    for name, result in pytest_logs.items():
        out += [f"## pytest — {name}", "", f"`{result['summary']}`", ""]
        if result["failed"]:
            out += ["Failed / errored:", ""] + [f"- `{line}`" for line in result["failed"][:MAX_LINES]]
            if len(result["failed"]) > MAX_LINES:
                out.append(f"- … {len(result['failed']) - MAX_LINES} more")
            out.append("")
            failed_tests += [f"{name}: {line}" for line in result["failed"]]
        if result["skipped"]:
            out += ["Skipped (reason):", ""] + [f"- `{line}`" for line in result["skipped"][:MAX_LINES]] + [""]
    if not pytest_logs:
        out += ["## pytest", "", "No pytest.log artifact for this run.", ""]

    exe_ok = None
    if exe is not None:
        exe_ok = exe["started_count"] >= 2 and not exe["hang_files"] and not exe["problem_lines"]
        out += ["## Packaged EXE smoke test", "",
                f"- result: **{'OK' if exe_ok else 'CHECK'}** — `Planning started` logged {exe['started_count']}× (expected 2: empty profile, then restart)"]
        if exe["hang_files"]:
            out.append(f"- hang evidence present: {', '.join(exe['hang_files'])}")
        out += ["", "```", *exe["log_lines"][:MAX_LINES], "```", ""]
        if exe["problem_lines"]:
            out += ["Problem lines:", ""] + [f"- `{line}`" for line in exe["problem_lines"][:MAX_LINES]] + [""]

    data = {
        "workflow": workflow, "conclusion": conclusion, "sha": sha, "branch": meta.get("headBranch", ""),
        "url": meta.get("url", ""), "written": now,
        "jobs": jobs, "pytest": {name: {"summary": r["summary"], "counts": r["counts"], "failed": r["failed"], "skipped": r["skipped"]} for name, r in pytest_logs.items()},
        "failed_tests": failed_tests,
        "exe_smoke": None if exe is None else {"ok": exe_ok, "started_count": exe["started_count"], "hang_files": exe["hang_files"]},
    }
    return "\n".join(out).rstrip() + "\n", data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--meta", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    meta = json.loads(args.meta.read_text(encoding="utf-8")) if args.meta.is_file() else {}
    args.artifacts.mkdir(parents=True, exist_ok=True)
    markdown, data = build_report(args.artifacts, meta)
    workflow = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(data["workflow"])).strip("-") or "run"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (args.out_dir / "latest").mkdir(parents=True, exist_ok=True)
    (args.out_dir / "history").mkdir(parents=True, exist_ok=True)
    (args.out_dir / "latest" / f"{workflow}.md").write_text(markdown, encoding="utf-8")
    (args.out_dir / "latest" / f"{workflow}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (args.out_dir / "history" / f"{stamp}_{data['sha'] or 'unknown'}_{workflow}.md").write_text(markdown, encoding="utf-8")
    print(f"report written for {workflow} ({data['conclusion']}) in {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
