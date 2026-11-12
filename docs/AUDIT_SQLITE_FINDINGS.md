# SQLite review — findings and status

Scope: `utility/situazione_db.py`, `utility/prezzi_db.py`, `utility/orders_db.py`, `utility/backup.py`.

| # | Priority | Finding | Evidence | Status |
|---|----------|---------|----------|-------------------------------------|
| F1 | High | `init_db()` swallows **every** `sqlite3.OperationalError` of its 7 `ALTER TABLE ... ADD COLUMN`. A read-only, I/O-failing or locked database skips the upgrade silently; later queries fail with "no such column". | `tests/test_sqlite_migration.py::test_a_failed_upgrade_is_reported_not_swallowed` (failed before the fix) | **FIXED**: a column is added only when `PRAGMA table_info` says it is missing; only "duplicate column name" is tolerated; anything else is raised. Existing data untouched. |
| F2 | Medium | `backup._snapshot_sqlite` returns False on any `sqlite3.Error` and the caller silently zips the **raw** file (possible torn state), and `daily_backup` swallows every exception without a log line — a broken backup is invisible. | code reading (backup.py) | **FIXED**: both places log a warning; the fallback is unchanged. |
| F3 | Medium | `prezzi_db.load_prezzi_frame` turns `sqlite3.Error` (including corruption / lock) into "no cache" with no log. Acceptable for a cache, but invisible. | code reading | **FIXED**: logs a warning, still returns None (cache rebuilt). |
| F4 | Low | No schema version (`PRAGMA user_version`): upgrades rely on idempotent ALTERs. Works, but the state of a database cannot be read. | code reading | OPEN (optional; not needed for correctness). |
| F5 | Low | `restore_backup` copies files one by one: a failure half-way leaves a partly restored profile. (It already removes stale `-wal/-shm` and rejects path traversal — good.) | code reading | OPEN: changes restore behaviour — needs your decision. |

Verified OK (by tests added in this phase): a fresh DB is created complete; an older DB (columns dropped) is upgraded without losing a row and a second upgrade changes nothing; a corrupted file raises and is left untouched; data saved by one process is read by the next; repeated restarts add no duplicates; identical re-save reports "no change"; no lock/open transaction is left after a run (`integrity_check` ok, WAL on).
