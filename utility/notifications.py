"""Persisted, categorized notification store used by the desktop UI."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from utility.utils import APP_DATA_DIR, logger

_PATH = APP_DATA_DIR / "settings" / "notifications.json"
CATEGORIES = ("Urgent", "Raw Yarn", "Prices", "Quality", "Delay", "Files", "System", "Other")


class NotificationStoreError(OSError):
    """notifications.json exists but cannot be read (or kept safe) right now.

    Raised to WRITERS only: every write is read-modify-write of the whole file, so writing after a failed
    read used to replace the whole history with just the new entries.
    """


def _quarantine() -> Path:
    """Move an unreadable notifications.json aside (same folder) so a fresh list can start without losing it.

    Moving, not copying: the corrupt file is gone from its place after the first writer, so the next writer
    sees "no file yet" instead of making another identical copy.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = _PATH.with_name(f"notifications.corrupt-{stamp}.json")
    counter = 1
    while target.exists():
        target = _PATH.with_name(f"notifications.corrupt-{stamp}-{counter}.json")
        counter += 1
    import os
    os.replace(_PATH, target)
    return target


def _read(strict: bool = False) -> list[dict]:
    """The stored notifications.

    A missing file is simply "none yet".  An unreadable one is logged and shown as empty to readers
    (``strict=False``: a list on screen).  Writers pass ``strict=True``: a read error raises
    NotificationStoreError instead of letting them overwrite the file, and a corrupt file is first moved to
    ``notifications.corrupt-<time>.json`` so its content survives the fresh start.
    """
    try:
        text = _PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.error("notifications.json could not be read: %s", exc)
        if strict:
            raise NotificationStoreError(f"notifications.json could not be read: {exc}") from exc
        return []
    try:
        data = json.loads(text)
    except ValueError as exc:
        data = None
        logger.error("notifications.json is not valid JSON: %s", exc)
    if isinstance(data, list):
        return data
    if data is not None:
        logger.error("notifications.json does not hold a list; ignoring it")
    if strict:
        try:
            kept = _quarantine()
        except OSError as exc:
            raise NotificationStoreError(f"could not set aside the unreadable notifications.json: {exc}") from exc
        logger.error("The unreadable notifications.json was kept as %s; starting a new list", kept.name)
    return []


def _write(items: list[dict]) -> None:
    from utility.atomic import atomic_write_text
    atomic_write_text(_PATH, json.dumps(items[-1000:], ensure_ascii=False, indent=2))


# Notification families that a completed check keeps up to date: the check re-reports the problem for as long
# as it exists and closes the notification itself (resolve_missing / resolve) once it is gone.  Resolving one of
# these by hand while the check still reports it needs the user's confirmation (see dismiss()).
# tests/test_notification_dismissal.py checks that every prefix passed to resolve_missing() is listed here.
LIVE_PREFIXES = ("situazione-price-", "situazione-raw-yarn-available:", "prezzi-")
LIVE_KEYS = ("situazione-abbina-pending",)
INFORMATION_PREFIXES = ("prezzi-price-changes",)      # notices, not problems: no check re-reports them


def is_live(key: str) -> bool:
    """True when *key* belongs to a family that a check re-reports while its problem exists."""
    key = str(key)
    if key.startswith(INFORMATION_PREFIXES):
        return False
    return key in LIVE_KEYS or key.startswith(LIVE_PREFIXES)


def category_for(key: str, title: str = "", page: str = "") -> str:
    """Pick a notification's category (Prices, Raw Yarn, Quality, Delay, Files, System or Other) from keywords in its key, title and page."""
    text = f"{key} {title} {page}".casefold()
    if any(x in text for x in ("price", "prezzi", "prezzo")):
        return "Prices"
    if any(x in text for x in ("pg-x", "filato", "yarn", "raw")):
        return "Raw Yarn"
    if any(x in text for x in ("quality", "qualita", "c.q", "cq")):
        return "Quality"
    if any(x in text for x in ("delay", "ritard", "consegna", "delivery")):
        return "Delay"
    if any(x in text for x in ("file", "upload", "excel", "listini")):
        return "Files"
    if any(x in text for x in ("error", "failed", "system", "save")):
        return "System"
    return "Other"


def _clean_ref(value) -> str:
    """Ordine / Riga as the text people read: "" for blank/nan, "3" for 3.0."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.casefold() in {"", "nan", "none", "nat"}:
        return ""
    try:
        number = float(text)
        if number.is_integer() and "e" not in text.casefold():
            return str(int(number))
    except ValueError:
        pass
    return text


def list_all() -> list[dict]:
    items = _read()
    for item in items:
        item.setdefault("ordine", "")   # notifications saved before these fields existed
        item.setdefault("riga", "")
        item.setdefault("category", category_for(item.get("key", ""), item.get("title", ""), item.get("page", "")))
        item.setdefault("status", "resolved" if item.get("resolved") else "open")
    return items


def list_open(category: str = "All") -> list[dict]:
    """The notifications still open: not resolved, not snoozed into the future, optionally limited to one category."""
    now = datetime.now()
    result = []
    for item in list_all():
        if item.get("resolved") or item.get("status") == "resolved":
            continue
        until = item.get("snoozed_until", "")
        if until:
            try:
                if datetime.fromisoformat(until) > now:
                    continue
            except ValueError:
                pass
        if category != "All" and item.get("category", "Other") != category:
            continue
        result.append(item)
    return sorted(result, key=lambda item: (item.get("severity") != "high", item.get("created_at", "")), reverse=False)


def add_many(entries: Iterable[dict]) -> int:
    """Add several notifications at once and return how many were new.

    Entries are de-duplicated on their "key" against the OPEN notifications: an
    already-open one is not added again (only its missing Ordine/Riga are filled in
    from the new report).  A key the user dismissed (see dismiss()) is not re-opened either.
    Everything is read and written in one pass.
    """
    items = _read(strict=True)
    known_keys = {item.get("key") for item in items if not item.get("resolved")}
    open_by_key = {item.get("key"): item for item in items if not item.get("resolved")}
    dismissed_keys = {item.get("key") for item in items if item.get("dismissed") and item.get("resolved")}
    now = datetime.now().isoformat(timespec="seconds")
    import re
    added = 0
    backfilled = False
    for entry in entries:
        key = str(entry["key"])
        if key in dismissed_keys:
            continue            # resolved by hand while the problem existed: stays hidden until the problem is gone
        if key in known_keys:
            # Already open (not duplicated), but it may predate the Ordine/Riga
            # columns: fill them in from this report instead of leaving them blank.
            existing = open_by_key.get(key)
            if existing is not None:
                for field in ("ordine", "riga"):
                    value = _clean_ref(entry.get(field))
                    if value and not _clean_ref(existing.get(field)):
                        existing[field] = value
                        backfilled = True
            continue
        title = str(entry["title"])
        message = str(entry["message"])
        page = str(entry.get("page", ""))
        severity = str(entry.get("severity", "medium"))
        partita_colore = str(entry.get("partita_colore", ""))
        if not partita_colore or partita_colore in ("None", "nan"):
            match = re.search(r"(?i)(?:Partita|color code|code)\s+([A-Z0-9_\-/]+)", message)
            partita_colore = match.group(1).strip() if match else ""
            if not partita_colore:
                parts = key.split(":")
                if len(parts) >= 3 and parts[0].startswith("situazione-price"):
                    candidate = parts[3] if len(parts) > 3 and not parts[3].replace(".", "").isdigit() else parts[2]
                    if candidate and candidate not in ("None", "nan"):
                        partita_colore = candidate
            partita_colore = partita_colore or "N/A"
        ordine = _clean_ref(entry.get("ordine"))
        riga = _clean_ref(entry.get("riga"))
        category = str(entry.get("category", ""))
        item_category = category if category in CATEGORIES else category_for(key, title, page)
        items.append({
            "key": key, "title": title, "message": message, "page": page,
            "partita_colore": partita_colore, "ordine": ordine, "riga": riga,
            "category": item_category,
            "severity": severity, "status": "open",
            "created_at": now, "resolved": False, "snoozed_until": "",
        })
        known_keys.add(key)
        open_by_key[key] = items[-1]
        added += 1
    if added or backfilled:
        _write(items)
    return added


def add(key: str, title: str, message: str, page: str, severity: str = "medium", partita_colore: str = "",
        category: str = "", ordine="", riga="") -> bool:
    return bool(add_many([{
        "key": key, "title": title, "message": message, "page": page,
        "severity": severity, "partita_colore": partita_colore, "category": category,
        "ordine": ordine, "riga": riga,
    }]))


def resolve(key: str) -> None:
    """Close the open notification *key*; a dismissed one is not open, but its dismissal is cleared because
    whoever calls this (a check that no longer finds the problem) says the problem is gone."""
    items = _read(strict=True)
    changed = False
    for item in items:
        if item.get("key") != key:
            continue
        if item.get("dismissed"):
            item["dismissed"] = False
            changed = True
        elif not item.get("resolved"):
            item["status"] = "resolved"
            item["resolved"] = True
            item["snoozed_until"] = ""
            changed = True
    if changed:
        _write(items)


def dismiss(key: str) -> None:
    """Resolve *key* by hand although the check still reports its problem, and keep it hidden.

    It stays hidden for as long as the check reports the same key; once a completed check no longer reports it
    (resolve_missing / resolve) the dismissal is cleared, so the alert comes back if the problem returns.  If the
    values in the key change, it is a different problem and is reported as new.
    """
    items = _read(strict=True)
    changed = False
    for item in items:
        if item.get("key") == key and not item.get("resolved"):
            item["status"] = "resolved"
            item["resolved"] = True
            item["snoozed_until"] = ""
            item["dismissed"] = True
            changed = True
    if changed:
        _write(items)


def resolve_missing(prefix: str, current_keys: Iterable[str]) -> int:
    """Resolve open notifications under *prefix* whose issue no longer exists.

    A pass that reports the complete list of current problems for a feature
    passes that list as *current_keys*; any open notification with this key
    prefix that is NOT in it was fixed, so it closes by itself instead of
    staying open until someone resolves it by hand. Snoozed notifications are
    closed too.  A notification the user dismissed by hand and that is no longer reported just forgets its
    dismissal.  Returns how many open ones were resolved.

    Call this only after the pass actually completed -- never after a
    failure, or every notification would look "fixed".
    """
    keep = set(current_keys)
    items = _read(strict=True)
    resolved = 0
    cleared = 0
    for item in items:
        key = str(item.get("key", ""))
        if not key.startswith(prefix) or key in keep:
            continue
        if item.get("dismissed"):
            item["dismissed"] = False        # the problem is gone: report it again if it ever returns
            cleared += 1
            continue
        if item.get("resolved"):
            continue
        item["status"] = "resolved"
        item["resolved"] = True
        item["snoozed_until"] = ""
        resolved += 1
    if resolved or cleared:
        _write(items)
    return resolved


def update_status(key: str, status: str) -> None:
    items = _read(strict=True)
    changed = False
    for item in items:
        if item.get("key") == key and not item.get("resolved"):
            item["status"] = status
            item["resolved"] = status == "resolved"
            if status != "snoozed":
                item["snoozed_until"] = ""
            changed = True
    if changed:
        _write(items)


def snooze(key: str, hours: int = 24) -> None:
    items = _read(strict=True)
    until = (datetime.now() + timedelta(hours=hours)).isoformat(timespec="seconds")
    changed = False
    for item in items:
        if item.get("key") == key and not item.get("resolved"):
            item["status"] = "snoozed"
            item["snoozed_until"] = until
            changed = True
    if changed:
        _write(items)
