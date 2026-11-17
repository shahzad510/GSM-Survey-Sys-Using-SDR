from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtWidgets import QApplication, QTableWidget

from cellsurvey.receivers.adb import AdbNotFoundError
from cellsurvey.receivers.manager import ReceiverManager
from cellsurvey.state import StatusStore
from cellsurvey.ui.navigation import PAGE_SPECS
from cellsurvey.ui.pages.receiver_manager import ReceiverManagerPage
from fakes import DEVICES_NONE, DEVICES_READY, DEVICES_UNAUTHORIZED, SERIAL, FakeAdb
from test_receiver_manager import wait_for

SPEC = next(spec for spec in PAGE_SPECS if spec.key == "receivers")


def _row(table: QTableWidget, row: int) -> list[str]:
    return [table.item(row, column).text() for column in range(table.columnCount())]


@pytest.fixture
def adb() -> FakeAdb:
    return FakeAdb(DEVICES_NONE)


@pytest.fixture
def manager(qapp: QApplication, adb: FakeAdb) -> Iterator[ReceiverManager]:
    manager = ReceiverManager(StatusStore(), adb)
    yield manager
    manager.close()


@pytest.fixture
def page(manager: ReceiverManager) -> ReceiverManagerPage:
    return ReceiverManagerPage(SPEC, manager)


def test_no_receivers(page: ReceiverManagerPage, manager: ReceiverManager) -> None:
    manager.scan_now()

    assert page.receivers_table.rowCount() == 0
    assert page.message.text().startswith("No receivers detected.")
    assert not page.connect_button.isEnabled()
    assert not page.inspect_button.isEnabled()


def test_ready_receiver_is_listed_and_selected(
    page: ReceiverManagerPage, manager: ReceiverManager, adb: FakeAdb
) -> None:
    adb.devices_output = DEVICES_READY
    manager.scan_now()

    assert _row(page.receivers_table, 0) == [
        "Samsung SM-A600F",
        "Android phone (ADB)",
        SERIAL,
        "Android 10 (API 29)",
        "Ready",
    ]
    assert page.selected() is not None
    assert page.message.text() == ""
    assert page.connect_button.isEnabled()
    assert page.inspect_button.isEnabled()


def test_unauthorized_receiver_shows_hint_and_cannot_be_used(
    page: ReceiverManagerPage, manager: ReceiverManager, adb: FakeAdb
) -> None:
    adb.devices_output = DEVICES_UNAUTHORIZED
    manager.scan_now()

    assert _row(page.receivers_table, 0)[-1] == "Unauthorized"
    assert "Allow USB debugging" in page.message.text()
    assert not page.connect_button.isEnabled()
    assert not page.inspect_button.isEnabled()


def test_connect_button_toggles_connection(
    page: ReceiverManagerPage, manager: ReceiverManager, adb: FakeAdb
) -> None:
    adb.devices_output = DEVICES_READY
    manager.scan_now()

    page.connect_button.click()
    assert manager.active_id == f"android_adb:{SERIAL}"
    assert _row(page.receivers_table, 0)[-1] == "Connected"
    assert page.connect_button.text() == "Disconnect"
    assert page.selected() is not None

    page.connect_button.click()
    assert manager.active_id is None
    assert _row(page.receivers_table, 0)[-1] == "Ready"
    assert page.connect_button.text() == "Connect"


def test_scan_error_is_shown_and_cleared_on_recovery(
    page: ReceiverManagerPage, manager: ReceiverManager, adb: FakeAdb
) -> None:
    adb.error = AdbNotFoundError("adb was not found. Install it with: sudo apt install adb")
    manager.scan_now()
    assert page.message.text() == "adb was not found. Install it with: sudo apt install adb"

    adb.error = None
    manager.scan_now()
    assert page.message.text().startswith("No receivers detected.")


def test_inspection_fills_capability_table(
    page: ReceiverManagerPage, manager: ReceiverManager, adb: FakeAdb
) -> None:
    adb.devices_output = DEVICES_READY
    manager.scan_now()
    assert page.capabilities_table.rowCount() == 0

    wait_for(manager.capabilities_ready, page.inspect_button.click)

    table = page.capabilities_table
    rows = {table.item(row, 0).text(): _row(table, row) for row in range(table.rowCount())}
    assert rows["Operator MCC and MNC"] == [
        "Operator MCC and MNC",
        "Device diagnostics",
        "getprop gsm.operator.numeric",
        "Reported: 00101",
    ]
    assert rows["RF samples and spectrum"][1:3] == ["Unavailable", "—"]
    assert page.capabilities_note.text().startswith("Inspected ")
    assert page.inspect_button.isEnabled()


def test_inspection_failure_is_shown(
    page: ReceiverManagerPage, manager: ReceiverManager, adb: FakeAdb
) -> None:
    adb.devices_output = DEVICES_READY
    manager.scan_now()
    adb.shell_outputs.clear()  # the fake now fails on any shell command

    wait_for(manager.inspection_failed, page.inspect_button.click)

    assert page.capabilities_note.text().startswith("Inspection failed:")
    assert page.capabilities_table.rowCount() == 0
