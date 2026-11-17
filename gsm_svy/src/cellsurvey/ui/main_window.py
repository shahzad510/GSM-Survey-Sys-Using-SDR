"""Main window: navigation sidebar, status header and the page area."""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cellsurvey import APP_NAME, __version__
from cellsurvey.config import AppConfig, AppPaths
from cellsurvey.receivers.manager import ReceiverManager
from cellsurvey.state import StatusStore
from cellsurvey.surveys import SurveyService
from cellsurvey.ui.navigation import PAGE_SPECS
from cellsurvey.ui.pages import create_page
from cellsurvey.ui.status_header import StatusHeader

logger = logging.getLogger(__name__)

_SIDEBAR_WIDTH = 240
_NAV_ROW_HEIGHT = 36


class MainWindow(QMainWindow):
    """Top-level window hosting every navigation page."""

    def __init__(
        self,
        config: AppConfig,
        paths: AppPaths,
        store: StatusStore,
        receivers: ReceiverManager,
        surveys: SurveyService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.resize(config.window_width, config.window_height)

        self._keys = [spec.key for spec in PAGE_SPECS]
        self.nav = QListWidget()
        self.nav.setObjectName("navList")
        self.pages = QStackedWidget()
        for spec in PAGE_SPECS:
            item = QListWidgetItem(spec.title, self.nav)
            # Explicit row height: the stylesheet's item padding is not
            # reflected in the list's own size calculation.
            item.setSizeHint(QSize(0, _NAV_ROW_HEIGHT))
            self.pages.addWidget(create_page(spec, store, paths, receivers, surveys))
        self.header = StatusHeader(store)

        work_area = QWidget()
        work_layout = QVBoxLayout(work_area)
        work_layout.setContentsMargins(0, 0, 0, 0)
        work_layout.setSpacing(0)
        work_layout.addWidget(self.header)
        work_layout.addWidget(self.pages, 1)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())
        layout.addWidget(work_area, 1)
        self.setCentralWidget(central)

        self.nav.currentRowChanged.connect(self._on_row_changed)
        self.nav.setCurrentRow(0)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(_SIDEBAR_WIDTH)

        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        title.setWordWrap(True)
        subtitle = QLabel("RF survey and measurement analysis")
        subtitle.setObjectName("appSubtitle")
        subtitle.setWordWrap(True)
        version = QLabel(f"Version {__version__}")
        version.setObjectName("appVersion")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.nav, 1)
        layout.addWidget(version)
        return sidebar

    def current_page_key(self) -> str:
        """Key of the page currently shown."""
        return self._keys[self.pages.currentIndex()]

    def show_page(self, key: str) -> None:
        """Navigate to the page with the given key.

        Raises:
            ValueError: no page has that key.
        """
        self.nav.setCurrentRow(self._keys.index(key))

    def _on_row_changed(self, row: int) -> None:
        self.pages.setCurrentIndex(row)
        logger.debug("Page changed", extra={"page": self._keys[row]})
