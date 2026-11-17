from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from cellsurvey.logging_setup import setup_logging


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    """Leave the root logger as it was, closing handlers the test installed."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)


def _records(log_file: Path) -> list[dict[str, object]]:
    for handler in logging.getLogger().handlers:
        handler.flush()
    return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]


def test_file_log_is_json_lines_with_extra_fields(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "app.log"

    assert setup_logging(log_file, "INFO") == log_file
    logging.getLogger("cellsurvey.test").info("Page %s", "changed", extra={"page": "dashboard"})

    (record,) = _records(log_file)
    assert record["level"] == "INFO"
    assert record["logger"] == "cellsurvey.test"
    assert record["message"] == "Page changed"
    assert record["page"] == "dashboard"
    assert str(record["ts"]).endswith("+00:00")


def test_level_filters_records(tmp_path: Path) -> None:
    log_file = tmp_path / "app.log"
    setup_logging(log_file, "WARNING")

    logging.getLogger("cellsurvey.test").info("hidden")
    logging.getLogger("cellsurvey.test").warning("shown")

    assert [record["message"] for record in _records(log_file)] == ["shown"]


def test_exception_is_recorded(tmp_path: Path) -> None:
    log_file = tmp_path / "app.log"
    setup_logging(log_file)

    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("cellsurvey.test").exception("failed")

    (record,) = _records(log_file)
    assert "ValueError: boom" in str(record["exception"])


def test_repeated_setup_does_not_duplicate_output(tmp_path: Path) -> None:
    log_file = tmp_path / "app.log"
    setup_logging(log_file)
    setup_logging(log_file)

    logging.getLogger("cellsurvey.test").info("once")

    assert len(_records(log_file)) == 1


def test_unwritable_location_falls_back_to_console(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("", encoding="utf-8")

    assert setup_logging(blocker / "app.log") is None
    logging.getLogger("cellsurvey.test").info("still works")
