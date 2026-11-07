"""The application version lives in version.txt; everything else must agree with it."""
import re
from pathlib import Path

from utility import updater

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = "1.0.2"


def test_version_txt_is_the_fixed_release_version():
    assert (ROOT / "version.txt").read_text(encoding="utf-8").strip() == EXPECTED


def test_the_fallback_version_and_the_installer_agree_with_version_txt():
    assert updater.DEFAULT_APP_VERSION == EXPECTED
    iss = (ROOT / "installer.iss").read_text(encoding="utf-8")
    assert re.search(r'#define\s+AppVersion\s+"%s"' % re.escape(EXPECTED), iss)


def test_the_running_version_is_the_one_in_version_txt():
    assert updater.get_installed_version() == EXPECTED
    assert updater.APP_VERSION == EXPECTED
