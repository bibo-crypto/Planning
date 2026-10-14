import os
from pathlib import Path

from utility import backup


def test_planning_backups_keep_only_the_ten_newest(tmp_path, monkeypatch):
    """Old program-created backups are pruned, unrelated ZIPs are untouched."""
    monkeypatch.setattr(backup, "APP_DATA_DIR", tmp_path / "app-data")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    for index in range(12):
        path = backup_dir / f"planning_backup_20260101_0000{index:02}.zip"
        backup.create_backup(path)
        os.utime(path, (index + 1, index + 1))

    unrelated = backup_dir / "customer_archive.zip"
    unrelated.write_bytes(b"not a Planning backup")
    backup._prune_old_backups(backup_dir)

    retained = sorted(path.name for path in backup_dir.glob("planning_backup_*.zip"))
    assert len(retained) == backup.MAX_BACKUPS
    assert retained == [f"planning_backup_20260101_0000{index:02}.zip" for index in range(2, 12)]
    assert unrelated.exists()
