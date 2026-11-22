"""A broad ``except Exception`` that only logs a warning/error must log the traceback too, or the log cannot say where it failed.

Sites that run in a loop or at high frequency deliberately stay without a traceback (one line per item instead of a
screenful per item); see REVIEW_REPORT.md.
"""
import logging
from pathlib import Path

import pytest

from parsers import elvy_mapping
from utility import file_cache


def _with_traceback(caplog, fragment):
    records = [r for r in caplog.records if r.levelno >= logging.WARNING and fragment in r.getMessage()]
    assert len(records) == 1, [r.getMessage() for r in caplog.records]
    assert records[0].exc_info and records[0].exc_info[0] is not None
    return records[0]


def test_a_damaged_file_cache_is_logged_with_its_traceback(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(file_cache, "CACHE_DIR", tmp_path)
    file_cache._cache_path("dfm").write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="converter"):
        assert file_cache.load_file_cache("dfm")["source_path"] == ""
    _with_traceback(caplog, "file cache")


def test_a_file_cache_that_cannot_be_saved_is_logged_with_its_traceback(tmp_path, monkeypatch, caplog):
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(file_cache, "CACHE_DIR", blocker / "cache")           # mkdir under a file fails
    with caplog.at_level(logging.WARNING, logger="converter"):
        file_cache.save_file_cache("dfm", Path("a.xlsx"))
    _with_traceback(caplog, "file cache")


def test_a_damaged_elvy_mapping_is_logged_with_its_traceback(tmp_path, monkeypatch, caplog):
    damaged = tmp_path / "elvy_mapping.json"
    damaged.write_text("[[[", encoding="utf-8")
    monkeypatch.setattr(elvy_mapping, "MAPPING_FILE", damaged)
    with caplog.at_level(logging.WARNING, logger="converter"):
        assert elvy_mapping.load_elvy_mapping() == {}
    _with_traceback(caplog, "Elvy mapping")


def test_a_pdf_that_cannot_be_parsed_is_logged_with_its_traceback(tmp_path, caplog):
    from parsers.pdf_parser import PDFParser

    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 this is not a real pdf")
    with caplog.at_level(logging.WARNING, logger="converter"), pytest.raises(RuntimeError, match="Could not parse"):
        PDFParser(broken).parse()
    _with_traceback(caplog, "Failed to parse")
