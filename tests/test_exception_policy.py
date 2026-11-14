"""No new silent ``except Exception``.

A broad handler may swallow an error only if it leaves a trace: it re-raises, logs, or uses the exception (e.g.
shows it to the user).  A handler that just does ``pass`` / ``return`` / ``continue`` hides real failures -- on this
program's own log a transient SQLite "disk I/O error" was being read as "no data".  The few places where
staying silent is right are listed below with the reason; adding to the list needs a reason too.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"tests", "ci", "venv", ".git", "build", "dist", "docs", "__pycache__"}
LOG_METHODS = {"exception", "error", "warning", "info", "debug", "critical", "log"}

# (file, function) -> why it is allowed to be silent
ALLOWED = {
    ("gui/gui.py", "emit"): "logging.Handler.emit: the standard way to report a failing handler is self.handleError(record)",
    ("main.py", "_write_startup_error"): "last resort while reporting a startup crash: it must never raise itself",
    ("main.py", "<module>"): "the startup-crash reporter: it writes startup_error.log first, then tries to show a dialog",
    ("sync_venv_packages.py", "_applies_here"): "developer tool: an unreadable marker is treated as 'needed', which is the safe side",
}


def _is_broad(handler: ast.ExceptHandler) -> bool:
    kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return handler.type is None or any(isinstance(k, ast.Name) and k.id in ("Exception", "BaseException") for k in kinds)


def _leaves_a_trace(handler: ast.ExceptHandler) -> bool:
    nodes = [n for statement in handler.body for n in ast.walk(statement)]
    if any(isinstance(n, ast.Raise) for n in nodes):
        return True
    if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in LOG_METHODS for n in nodes):
        return True
    return handler.name is not None and any(isinstance(n, ast.Name) and n.id == handler.name for n in nodes)


def _silent_handlers():
    found = []
    for path in sorted(ROOT.rglob("*.py")):
        if SKIP_DIRS & set(path.relative_to(ROOT).parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and _is_broad(node) and not _leaves_a_trace(node):
                scope = node
                while scope in parents and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    scope = parents[scope]
                found.append((rel, scope.name if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) else "<module>", node.lineno))
    return found


def test_every_broad_except_leaves_a_trace_unless_it_is_listed_with_a_reason():
    unexpected = [f"{file}:{line} (in {function})" for file, function, line in _silent_handlers() if (file, function) not in ALLOWED]
    assert unexpected == [], (
        "These `except Exception` handlers swallow the error without a trace. Log it (logger.warning(..., exc_info=True) "
        "for a data path, logger.debug for polling/probing), re-raise it, or narrow the exception type:\n  " + "\n  ".join(unexpected))


def test_the_allow_list_has_no_stale_entries():
    present = {(file, function) for file, function, _line in _silent_handlers()}
    stale = sorted(set(ALLOWED) - present)
    assert stale == [], f"remove these from ALLOWED, they no longer exist or now leave a trace: {stale}"


def test_the_checker_itself_detects_a_silent_handler():
    silent = ast.parse("try:\n    x()\nexcept Exception:\n    pass\n").body[0].handlers[0]
    logged = ast.parse("try:\n    x()\nexcept Exception:\n    logger.warning('a', exc_info=True)\n").body[0].handlers[0]
    used = ast.parse("try:\n    x()\nexcept Exception as exc:\n    show(str(exc))\n").body[0].handlers[0]
    narrow = ast.parse("try:\n    x()\nexcept ValueError:\n    pass\n").body[0].handlers[0]
    assert _is_broad(silent) and not _leaves_a_trace(silent)
    assert _leaves_a_trace(logged) and _leaves_a_trace(used) and not _is_broad(narrow)
