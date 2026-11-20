import pytest
import os
import sys
import time
import tkinter as tk
from pathlib import Path
import tempfile

from tests.git_helpers import git, write


def create_tk_root():
    """Create Tk with retries; only an absent display may skip the test."""
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        pytest.skip("no display available for Tk")
    last_error = None
    for attempt in range(5):
        try:
            return tk.Tk()
        except tk.TclError as exc:
            last_error = exc
            if attempt < 4:
                time.sleep(0.5)
    raise last_error


@pytest.fixture(scope="session", autouse=True)
def git_ceiling_for_pytest_basetemp(pytestconfig):
    """Keep git discovery below pytest's basetemp, even if basetemp is inside a repository."""
    basetemp = pytestconfig.getoption("basetemp")
    if not basetemp:
        basetemp = str(Path(tempfile.gettempdir()) / "planning-pytest")
    previous = os.environ.get("GIT_CEILING_DIRECTORIES")
    os.environ["GIT_CEILING_DIRECTORIES"] = basetemp
    yield
    if previous is None:
        os.environ.pop("GIT_CEILING_DIRECTORIES", None)
    else:
        os.environ["GIT_CEILING_DIRECTORIES"] = previous


@pytest.fixture(autouse=True)
def isolated_situazione_db(tmp_path_factory, monkeypatch):
    """Give every test its own empty Situazione database with the schema created.

    Without it a page built in a test (SituazioneTab reads the upload log in its
    constructor) used the project's real ``situazione/dyeing_tracker.db``: missing on a
    fresh checkout -- "no such table: upload_log" -- and polluted by earlier tests
    otherwise.  Tests that point DB_PATH somewhere else simply override this.
    """
    from utility import situazione_db

    monkeypatch.setattr(situazione_db, "DB_PATH", str(tmp_path_factory.mktemp("situazione") / "dyeing_tracker.db"))
    situazione_db.init_db()


@pytest.fixture
def repo(tmp_path):
    """A repo with one commit, a .gitignore and a bare 'origin' it is already tracking."""
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    git(tmp_path, "init", "-b", "main", str(work))
    git(work, "config", "user.name", "Test User")
    git(work, "config", "user.email", "test@example.com")
    write(work, ".gitignore", "settings/\n*.sqlite3\n*.xlsx\n")
    write(work, "calculate/prezzi.py", "a = 1\n")
    write(work, "gui/gui.py", "b = 1\n")
    git(work, "add", "-A")
    git(work, "commit", "-m", "initial")
    git(work, "remote", "add", "origin", str(remote))
    git(work, "push", "-u", "origin", "main")
    return work
