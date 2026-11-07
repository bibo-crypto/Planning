"""Project-wide pytest setup -- runs before anything imports the application.

The suite must never touch the machine it runs on.  In a source checkout the application
keeps its settings, saved source paths, orders database and caches inside the project
folder, and it looks for ``Biglietti.docx`` on the user's Desktop; so on a developer's PC
the tests used to read the real saved files (some tests then failed only there) and to
write test rows into the real orders database.  Everything is redirected to a throw-away
folder here, and git is told to ignore the user's / system configuration.
"""
import atexit
import os
import shutil
import tempfile
from pathlib import Path

_SANDBOX = Path(tempfile.mkdtemp(prefix="planning-tests-"))
atexit.register(shutil.rmtree, _SANDBOX, ignore_errors=True)

_HOME = _SANDBOX / "home"
_HOME.mkdir()
os.environ["PLANNING_DATA_DIR"] = str(_SANDBOX / "appdata")   # settings/, data/, cache/, logs/ ...
os.environ["HOME"] = os.environ["USERPROFILE"] = str(_HOME)    # Path.home(): Desktop, OneDrive\Desktop
for _name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
    os.environ.pop(_name, None)

_GIT_CONFIG = _SANDBOX / "gitconfig"
_GIT_CONFIG.write_text("", encoding="utf-8")
os.environ["GIT_CONFIG_GLOBAL"] = str(_GIT_CONFIG)             # tests set their own identity
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
