"""Application entry point."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from collections.abc import Sequence

from PySide6.QtCore import QMessageLogContext, QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from cellsurvey import APP_NAME, __version__
from cellsurvey.config import AppConfig, AppPaths, ConfigError, load_config
from cellsurvey.logging_setup import install_exception_hook, setup_logging
from cellsurvey.database import DatabaseError
from cellsurvey.receivers.adb import AdbClient
from cellsurvey.receivers.manager import ReceiverManager
from cellsurvey.state import StatusStore
from cellsurvey.surveys import SurveyService
from cellsurvey.ui.main_window import MainWindow
from cellsurvey.ui.theme import apply_theme

logger = logging.getLogger(__name__)

_QT_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}


def _log_qt_message(mode: QtMsgType, _context: QMessageLogContext, message: str) -> None:
    """Route Qt's own diagnostics into the application log."""
    logging.getLogger("cellsurvey.qt").log(_QT_LEVELS.get(mode, logging.WARNING), message)


def _parse_args(argv: Sequence[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(prog="cellsurvey", description=APP_NAME)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="override the configured log level for this run",
    )
    # Unrecognised arguments (e.g. -platform offscreen) are passed on to Qt.
    return parser.parse_known_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Start the desktop application and return its exit code."""
    argv = sys.argv if argv is None else list(argv)
    args, qt_args = _parse_args(argv[1:])

    paths = AppPaths.resolve()
    config_error: ConfigError | None = None
    try:
        config = load_config(paths.config_file)
    except ConfigError as exc:
        config, config_error = AppConfig(), exc

    log_file = setup_logging(paths.log_file, args.log_level or config.log_level)
    install_exception_hook()
    qInstallMessageHandler(_log_qt_message)

    logger.info(
        "Starting %s",
        APP_NAME,
        extra={"version": __version__, "log_file": str(log_file) if log_file else None},
    )
    if config_error is not None:
        logger.warning("Using default settings: %s", config_error)

    # Python's SIGINT handler cannot run while Qt's event loop is in control,
    # so restore the default action to let Ctrl+C in the terminal quit the app.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication([argv[0], *qt_args])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    apply_theme(app)

    try:
        surveys = SurveyService(paths, app)
    except DatabaseError as exc:
        logger.error("Cannot open the survey database: %s", exc)
        print(f"Cannot open the survey database: {exc}", file=sys.stderr)
        return 1

    store = StatusStore(app)
    receivers = ReceiverManager(store, AdbClient(config.adb_path), app)
    app.aboutToQuit.connect(receivers.close)
    app.aboutToQuit.connect(surveys.close)

    window = MainWindow(config, paths, store, receivers, surveys)
    window.show()
    receivers.start()

    exit_code = app.exec()
    logger.info("Exiting", extra={"exit_code": exit_code})
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
