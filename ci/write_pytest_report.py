"""Write a human-readable CI summary from pytest's JUnit XML."""
from __future__ import annotations
import argparse
from pathlib import Path
import xml.etree.ElementTree as ET


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--xml", required=True); parser.add_argument("--log", required=True); parser.add_argument("--out", required=True); args = parser.parse_args()
    root = ET.parse(args.xml).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = failures = errors = skipped = 0; failed_names: list[str] = []
    for suite in suites:
        tests += int(suite.attrib.get("tests", 0)); failures += int(suite.attrib.get("failures", 0)); errors += int(suite.attrib.get("errors", 0)); skipped += int(suite.attrib.get("skipped", 0))
        for case in suite.iter("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                failed_names.append(f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}")
    passed = tests - failures - errors - skipped
    status = "PASS" if failures == errors == 0 else "FAIL"
    lines = [f"# Pytest report — **{status}**", "", f"- Tests: **{tests}**", f"- Passed: **{passed}**", f"- Failed: **{failures}**", f"- Skipped: **{skipped}**", f"- Errors: **{errors}**", "", "## Failed tests"]
    lines += [f"- `{name}`" for name in failed_names] or ["- None"]
    lines += ["", "## Full log", "", f"See `{Path(args.log).name}` in the uploaded artifact.", ""]
    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    summary = Path(__import__("os").environ.get("GITHUB_STEP_SUMMARY", "")) if __import__("os").environ.get("GITHUB_STEP_SUMMARY") else None
    if summary: summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0

if __name__ == "__main__": raise SystemExit(main())
