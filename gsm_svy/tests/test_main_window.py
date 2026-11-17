from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtWidgets import QApplication

from cellsurvey.config import AppConfig, AppPaths
from cellsurvey.receivers.manager import ReceiverManager
from cellsurvey.state import StatusStore, SurveyState
from cellsurvey.surveys import SurveyService
from cellsurvey.ui.main_window import MainWindow
from cellsurvey.ui.navigation import PAGE_SPECS
from cellsurvey.ui.pages.base import PlaceholderPage
from cellsurvey.ui.pages.dashboard import DashboardPage
from cellsurvey.ui.pages.receiver_manager import ReceiverManagerPage
from cellsurvey.ui.pages.survey_explorer_page import SurveyExplorerPage
from cellsurvey.ui.pages.survey_import_page import SurveyImportPage
from fakes import DEVICES_READY, SERIAL, FakeAdb

EXPECTED_TITLES = [
    "Dashboard",
    "Receiver Manager",
    "Network Information",
    "Live Measurements",
    "Survey Manager",
    "Import Survey",
    "Survey Explorer",
    "Signal Graphs",
    "Geographic Map",
    "Reports",
    "Settings",
]


@pytest.fixture
def store(qapp: QApplication) -> StatusStore:
    return StatusStore()


@pytest.fixture
def receivers(store: StatusStore) -> Iterator[ReceiverManager]:
    manager = ReceiverManager(store, FakeAdb(DEVICES_READY))
    yield manager
    manager.close()


@pytest.fixture
def surveys(paths: AppPaths) -> Iterator[SurveyService]:
    service = SurveyService(paths)
    yield service
    service.close()


@pytest.fixture
def window(
    store: StatusStore, paths: AppPaths, receivers: ReceiverManager, surveys: SurveyService
) -> MainWindow:
    return MainWindow(AppConfig(), paths, store, receivers, surveys)


def test_page_keys_are_unique() -> None:
    keys = [spec.key for spec in PAGE_SPECS]

    assert len(set(keys)) == len(keys)


def test_navigation_lists_required_pages_in_order(window: MainWindow) -> None:
    titles = [window.nav.item(row).text() for row in range(window.nav.count())]

    assert titles == EXPECTED_TITLES
    assert window.pages.count() == len(EXPECTED_TITLES)


def test_starts_on_dashboard(window: MainWindow) -> None:
    assert window.current_page_key() == "dashboard"
    assert isinstance(window.pages.currentWidget(), DashboardPage)


def test_selecting_navigation_row_switches_page(window: MainWindow) -> None:
    window.nav.setCurrentRow(1)

    assert window.current_page_key() == "receivers"
    assert isinstance(window.pages.currentWidget(), ReceiverManagerPage)


def test_show_page_by_key(window: MainWindow) -> None:
    window.show_page("import")
    assert isinstance(window.pages.currentWidget(), SurveyImportPage)

    window.show_page("explorer")
    assert isinstance(window.pages.currentWidget(), SurveyExplorerPage)

    window.show_page("reports")
    assert window.nav.currentRow() == EXPECTED_TITLES.index("Reports")
    assert isinstance(window.pages.currentWidget(), PlaceholderPage)

    with pytest.raises(ValueError):
        window.show_page("no-such-page")


def test_window_uses_configured_size(
    store: StatusStore,
    paths: AppPaths,
    receivers: ReceiverManager,
    surveys: SurveyService,
) -> None:
    config = AppConfig(window_width=1000, window_height=700)
    window = MainWindow(config, paths, store, receivers, surveys)

    assert (window.width(), window.height()) == (1000, 700)


def test_header_and_dashboard_start_without_data(window: MainWindow) -> None:
    dashboard = window.pages.widget(0)
    assert isinstance(dashboard, DashboardPage)

    assert window.header.receiver.text() == "Not connected"
    assert window.header.receiver.level() == "off"
    assert window.header.survey.text() == "Idle"
    assert window.header.technology.text() == "—"
    assert window.header.timestamp.text() == "—"
    assert dashboard.receiver_card.text() == "Not connected"
    assert dashboard.technology_card.text() == "—"
    assert dashboard.timestamp_card.text() == "—"


def test_header_and_dashboard_follow_status_changes(window: MainWindow, store: StatusStore) -> None:
    dashboard = window.pages.widget(0)
    assert isinstance(dashboard, DashboardPage)

    store.update(
        receiver_connected=True,
        receiver_name="SM-A600F",
        survey_state=SurveyState.RECORDING,
        survey_name="Site A",
        technology="LTE",
    )

    assert window.header.receiver.text() == "SM-A600F"
    assert window.header.receiver.level() == "ok"
    assert window.header.survey.text() == "Recording: Site A"
    assert window.header.survey.level() == "ok"
    assert window.header.technology.text() == "LTE"
    assert dashboard.receiver_card.text() == "SM-A600F"
    assert dashboard.survey_card.text() == "Recording: Site A"


def test_connecting_a_receiver_updates_header_and_dashboard(
    window: MainWindow, receivers: ReceiverManager
) -> None:
    dashboard = window.pages.widget(0)
    assert isinstance(dashboard, DashboardPage)
    receivers.scan_now()
    assert window.header.receiver.text() == "Not connected"

    receivers.connect_receiver(f"android_adb:{SERIAL}")

    assert window.header.receiver.text() == "Samsung SM-A600F"
    assert window.header.receiver.level() == "ok"
    assert dashboard.receiver_card.text() == "Samsung SM-A600F"
    # Connecting a receiver must not invent a technology or a measurement time.
    assert window.header.technology.text() == "—"
    assert window.header.timestamp.text() == "—"
