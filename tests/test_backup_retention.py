import os
from datetime import date, timedelta

from utility import backup


def _make(directory, day, hhmmss="000000"):
    path = directory / f"planning_backup_{day:%Y%m%d}_{hhmmss}.zip"
    backup.create_backup(path)
    return path


def test_planning_backups_keep_only_the_ten_newest_days(tmp_path, monkeypatch):
    """Backups of older days are pruned (all backups of a kept day stay); unrelated ZIPs are untouched."""
    monkeypatch.setattr(backup, "APP_DATA_DIR", tmp_path / "app-data")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    today = date(2026, 11, 3)
    for back in range(12):
        _make(backup_dir, today - timedelta(days=back))
    extra_today = _make(backup_dir, today, "235959")          # a second backup the same day
    unrelated = backup_dir / "customer_archive.zip"
    unrelated.write_bytes(b"not a Planning backup")
    backup._prune_old_backups(backup_dir)

    retained = sorted(path.name for path in backup_dir.glob("planning_backup_*.zip"))
    assert len(retained) == backup.KEEP_DAYS + 1               # ten days, the newest day twice
    assert extra_today.exists() and unrelated.exists()
    assert not (backup_dir / "planning_backup_20260101_000000.zip").exists()


def test_daily_backup_runs_once_per_day(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "APP_DATA_DIR", tmp_path / "app-data")
    (tmp_path / "app-data").mkdir()
    target = tmp_path / "backups"
    today = date(2026, 11, 3)
    first = backup.daily_backup(target, today=today)
    assert first is not None and first.is_file()
    assert backup.daily_backup(target, today=today) is None    # already done today
    assert backup.daily_backup(target, today=today + timedelta(days=1)) is not None
    assert len(list(target.glob("planning_backup_*.zip"))) == 2
