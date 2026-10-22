"""build.bat edits the existing venv in place: pip runs only when it has to."""
import sync_venv_packages as sync


def _root(tmp_path, text):
    (tmp_path / "requirements.txt").write_text(text, encoding="utf-8")
    return tmp_path


def test_fingerprint_changes_with_requirements_but_not_with_comments(tmp_path):
    a = sync.requirements_fingerprint(_root(tmp_path, "pytest>=8\nnumpy\n"))
    same = sync.requirements_fingerprint(_root(tmp_path, "# tools\npytest>=8   # tests\n\nnumpy\n"))
    other = sync.requirements_fingerprint(_root(tmp_path, "pytest>=8\nnumpy\nrequests\n"))
    assert a == same and a != other


def test_missing_requirements_ignores_markers_that_exclude_this_machine(tmp_path):
    root = _root(tmp_path, "pytest>=8\nnot-a-real-package-xyz>=1\nwindows-only-pkg; sys_platform == \"win32\"\n")
    assert sync.missing_requirements(root) == ["not-a-real-package-xyz"]


def test_nothing_runs_when_the_venv_is_current(tmp_path, monkeypatch):
    root, stamp = _root(tmp_path, "pytest>=8\n"), tmp_path / "stamp"
    stamp.write_text(sync.requirements_fingerprint(root), encoding="utf-8")
    monkeypatch.setattr(sync, "_pip_install", lambda path: (_ for _ in ()).throw(AssertionError("pip must not run")))
    monkeypatch.setattr(sync, "main", lambda: (_ for _ in ()).throw(AssertionError("no pruning needed")))
    assert sync.sync(root, stamp) == 0


def test_a_changed_requirements_file_installs_the_difference_and_updates_the_stamp(tmp_path, monkeypatch):
    root, stamp = _root(tmp_path, "pytest>=8\n"), tmp_path / "stamp"
    stamp.write_text("fingerprint of an older requirements.txt", encoding="utf-8")
    calls = []
    monkeypatch.setattr(sync, "main", lambda: calls.append("prune") or 0)
    monkeypatch.setattr(sync, "_pip_install", lambda path: calls.append(("pip", path.name)) or 0)
    assert sync.sync(root, stamp) == 0
    assert calls == ["prune", ("pip", "requirements.txt")]
    assert sync.is_environment_current(root, stamp)


def test_a_package_that_went_missing_is_reinstalled_even_with_a_matching_stamp(tmp_path, monkeypatch):
    root, stamp = _root(tmp_path, "pytest>=8\nnot-a-real-package-xyz\n"), tmp_path / "stamp"
    stamp.write_text(sync.requirements_fingerprint(root), encoding="utf-8")
    calls = []
    monkeypatch.setattr(sync, "main", lambda: 0)
    monkeypatch.setattr(sync, "_pip_install", lambda path: calls.append(path.name) or 0)
    assert sync.sync(root, stamp) == 0 and calls == ["requirements.txt"]


def test_a_failed_pip_run_does_not_mark_the_venv_current(tmp_path, monkeypatch):
    root, stamp = _root(tmp_path, "pytest>=8\n"), tmp_path / "stamp"
    monkeypatch.setattr(sync, "main", lambda: 0)
    monkeypatch.setattr(sync, "_pip_install", lambda path: 1)
    assert sync.sync(root, stamp) == 1
    assert not stamp.exists()
