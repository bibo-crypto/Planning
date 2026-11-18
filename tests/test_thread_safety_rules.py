"""Tkinter may only be touched from the main thread.

Worker threads (``threading.Thread(target=...)`` in gui/) must not read Tk variables, call winfo_* or open dialogs
themselves: they take a snapshot of what they need on the UI thread before starting, and hand results back with
``post_to_ui``.  Before this rule was enforced, four ``BooleanVar.get()`` calls (Ordine MED, Ordine Kamal), one
``winfo_exists()`` (Overview export) and two direct ``widget.after()`` calls (PG-X upload) ran in worker threads;
tkinter refuses ``after()`` from a worker while the main thread is not in mainloop (inside a modal dialog).
"""
import ast
import threading
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
VAR_CONSTRUCTORS = {"StringVar", "BooleanVar", "IntVar", "DoubleVar", "Variable"}
DIALOG_MODULES = {"messagebox", "filedialog", "simpledialog"}


def violations_in(source: str, filename: str = "<memory>") -> list[str]:
    """Direct Tk access (variables, winfo_*, dialogs) in the body of every worker-thread target.

    Lambdas and nested functions are skipped: they are the callbacks handed to post_to_ui, which run on the UI thread.
    """
    tree = ast.parse(source)
    var_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            constructor = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if constructor in VAR_CONSTRUCTORS:
                var_names.update(t.attr if isinstance(t, ast.Attribute) else getattr(t, "id", "") for t in node.targets)
    functions = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions.setdefault(node.name, []).append(node)
    found = []
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        func = call.func
        if not ((isinstance(func, ast.Attribute) and func.attr == "Thread") or getattr(func, "id", "") == "Thread"):
            continue
        target = next((k.value for k in call.keywords if k.arg == "target"), None)
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", None)
        for worker in functions.get(name, []):
            stack = list(worker.body)
            while stack:
                node = stack.pop()
                if isinstance(node, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    attr, base = node.func.attr, node.func.value
                    base_name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
                    if attr in {"get", "set"} and base_name in var_names:
                        found.append(f"{filename}:{node.lineno} {name}() uses the Tk variable {ast.unparse(node.func)}")
                    elif attr in {"after", "after_idle"}:
                        found.append(f"{filename}:{node.lineno} {name}() schedules with {ast.unparse(node.func)} itself; use post_to_ui")
                    elif attr.startswith("winfo_"):
                        found.append(f"{filename}:{node.lineno} {name}() calls {ast.unparse(node.func)}")
                    elif base_name in DIALOG_MODULES:
                        found.append(f"{filename}:{node.lineno} {name}() opens a dialog: {ast.unparse(node.func)}")
                stack.extend(ast.iter_child_nodes(node))
    return found


def test_no_worker_thread_in_the_gui_touches_tkinter_directly():
    found = []
    for path in sorted((ROOT / "gui").rglob("*.py")):
        found += violations_in(path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix())
    assert found == [], "Read Tk variables on the UI thread before starting the worker (snapshot) and use post_to_ui:\n  " + "\n  ".join(found)


def test_the_checker_detects_each_kind_of_violation():
    source = '''
import threading
import tkinter as tk
from tkinter import messagebox

class Tab:
    def __init__(self):
        self.flag = tk.BooleanVar(value=True)
    def start(self):
        threading.Thread(target=self._worker, daemon=True).start()
    def _worker(self):
        if self.flag.get():
            pass
        if self.winfo_exists():
            pass
        messagebox.showinfo("x", "y")
        self.after(0, lambda: None)
        post_to_ui(self, lambda: self.flag.get())          # inside a callback: allowed
'''
    found = violations_in(source)
    assert len(found) == 4
    assert "Tk variable self.flag.get" in found[0] or any("Tk variable self.flag.get" in line for line in found)
    assert any("winfo_exists" in line for line in found) and any("opens a dialog" in line for line in found)
    assert any("schedules with self.after itself" in line for line in found)


def test_a_worker_that_only_uses_a_snapshot_is_clean():
    source = '''
import threading
import tkinter as tk

class Tab:
    def __init__(self):
        self.flag = tk.BooleanVar(value=True)
    def start(self):
        self._flag_snapshot = bool(self.flag.get())
        threading.Thread(target=self._worker, daemon=True).start()
    def _worker(self):
        if self._flag_snapshot:
            pass
'''
    assert violations_in(source) == []


# ------------------------------------------------------------------ behaviour
def test_snapshot_of_uses_the_snapshot_and_falls_back_to_the_variable_on_the_calling_thread():
    from gui.tabs.kamal_tab import KamalTab
    variable = SimpleNamespace(get=lambda: True)
    holder = SimpleNamespace()
    assert KamalTab._snapshot_of(holder, "_update_erp_snapshot", variable) is True        # no snapshot: direct call, reads it
    holder._update_erp_snapshot = False
    assert KamalTab._snapshot_of(holder, "_update_erp_snapshot", variable) is False       # a snapshot wins over the live variable


def test_the_overview_export_never_calls_winfo_exists_from_its_worker_thread(tmp_path, monkeypatch):
    import gui.tabs.overview_tab as overview
    main = threading.main_thread()
    calls, posted = [], []

    class Parent:
        def winfo_exists(self):
            calls.append(threading.current_thread())
            return True

    target = tmp_path / "out.xlsx"
    monkeypatch.setattr(overview.filedialog, "asksaveasfilename", lambda **kw: str(target))
    monkeypatch.setattr(overview, "post_to_ui", lambda widget, callback, *args: posted.append(callback) or True)
    monkeypatch.setattr(overview.messagebox, "showinfo", lambda *a, **k: posted.append(("info", a)))
    monkeypatch.setattr(overview.messagebox, "showerror", lambda *a, **k: posted.append(("error", a)))
    started = []
    real_thread = threading.Thread

    class Recording(real_thread):
        def start(self):
            started.append(self)
            super().start()

    monkeypatch.setattr(overview.threading, "Thread", Recording)
    overview.export_dataframe_fast(pd.DataFrame({"a": [1, 2]}), "x.xlsx", parent=Parent())
    started[0].join(10)
    assert all(thread is main for thread in calls), "winfo_exists ran in a worker thread"
    assert target.is_file() and len(posted) == 1                       # the result is still handed to the UI thread
    posted[0]()
    assert posted[-1][0] == "info" and "Exported to" in posted[-1][1][1]


def test_the_overview_export_is_silent_when_there_is_no_parent(tmp_path, monkeypatch):
    import gui.tabs.overview_tab as overview
    posted = []
    monkeypatch.setattr(overview.filedialog, "asksaveasfilename", lambda **kw: str(tmp_path / "o.xlsx"))
    monkeypatch.setattr(overview, "post_to_ui", lambda *a, **k: posted.append(a) or True)
    started = []
    real_thread = threading.Thread

    class Recording(real_thread):
        def start(self):
            started.append(self)
            super().start()

    monkeypatch.setattr(overview.threading, "Thread", Recording)
    overview.export_dataframe_fast(pd.DataFrame({"a": [1]}), "x.xlsx", parent=None)
    started[0].join(10)
    assert posted == [] and (tmp_path / "o.xlsx").is_file()           # unchanged: nothing is posted without a parent
