"""Shared fixtures. Qt runs on the offscreen platform so no display is needed."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cellsurvey.config import HOME_ENV_VAR, AppPaths  # noqa: E402
from cellsurvey.ui.theme import apply_theme  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """The single QApplication shared by all UI tests."""
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """Application directories inside a temporary directory."""
    return AppPaths.resolve({HOME_ENV_VAR: str(tmp_path)})
