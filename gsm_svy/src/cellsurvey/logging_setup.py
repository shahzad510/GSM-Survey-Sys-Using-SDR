"""Application logging.

Two handlers are installed on the root logger:

* console (stderr): human-readable lines for development;
* file: one JSON object per line, rotated, for later inspection and tooling.

Extra context is attached the standard way and ends up as JSON fields::

    logger.info("Page changed", extra={"page": "dashboard"})
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

_MAX_LOG_BYTES = 2_000_000
_BACKUP_COUNT = 5
_OWNED_ATTR = "_cellsurvey_owned"

# Attributes every LogRecord has; anything else was supplied through ``extra``.
_RECORD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    """Format a log record as a single-line JSON object with a UTC timestamp."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _RECORD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def setup_logging(log_file: Path, level: str = "INFO") -> Path | None:
    """Configure root logging; safe to call more than once.

    Returns:
        The log file in use, or ``None`` when it could not be opened. In that
        case console logging still works and the reason is logged.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _OWNED_ATTR, False):
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    _install(root, console)

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=_MAX_LOG_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
    except OSError as exc:
        logging.getLogger(__name__).warning("File logging disabled: %s", exc)
        return None

    file_handler.setFormatter(JsonFormatter())
    _install(root, file_handler)
    return log_file


def install_exception_hook() -> None:
    """Log uncaught exceptions, including those raised inside Qt slots."""

    def hook(
        exc_type: type[BaseException],
        exc: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, traceback)
            return
        logging.getLogger("cellsurvey").critical(
            "Uncaught exception", exc_info=(exc_type, exc, traceback)
        )

    sys.excepthook = hook


def _install(root: logging.Logger, handler: logging.Handler) -> None:
    setattr(handler, _OWNED_ATTR, True)
    root.addHandler(handler)
