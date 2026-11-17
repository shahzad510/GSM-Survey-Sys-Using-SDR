from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from PySide6.QtCore import QEventLoop, QTimer, SignalInstance
from PySide6.QtWidgets import QApplication

from cellsurvey.receivers.adb import AdbError, AdbNotFoundError
from cellsurvey.receivers.base import CapabilityReport, ConnectionState, ReceiverError
from cellsurvey.receivers.manager import ReceiverManager
from cellsurvey.state import StatusStore
from fakes import DEVICES_NONE, DEVICES_READY, DEVICES_UNAUTHORIZED, SERIAL, FakeAdb

RECEIVER_ID = f"android_adb:{SERIAL}"


def wait_for(signal: SignalInstance, trigger: Callable[[], None]) -> tuple[object, ...]:
    """Run ``trigger`` and spin the event loop until ``signal`` is emitted."""
    loop = QEventLoop()
    received: list[tuple[object, ...]] = []

    def on_emit(*args: object) -> None:
        received.append(args)
        loop.quit()

    signal.connect(on_emit)
    QTimer.singleShot(5000, loop.quit)
    trigger()
    loop.exec()
    signal.disconnect(on_emit)
    assert received, "signal was not emitted within 5 s"
    return received[0]


@pytest.fixture
def store(qapp: QApplication) -> StatusStore:
    return StatusStore()


@pytest.fixture
def adb() -> FakeAdb:
    return FakeAdb(DEVICES_READY)


@pytest.fixture
def manager(store: StatusStore, adb: FakeAdb) -> Iterator[ReceiverManager]:
    manager = ReceiverManager(store, adb)
    yield manager
    manager.close()


def test_scan_lists_identified_receiver(manager: ReceiverManager) -> None:
    (info,) = manager.scan_now()

    assert info.receiver_id == RECEIVER_ID
    assert info.state is ConnectionState.READY
    assert info.display_name == "Samsung SM-A600F"


def test_detecting_a_receiver_does_not_connect_it(
    manager: ReceiverManager, store: StatusStore
) -> None:
    manager.scan_now()

    assert manager.active_id is None
    assert store.status.receiver_connected is False


def test_connect_and_disconnect_update_status(manager: ReceiverManager, store: StatusStore) -> None:
    active: list[object] = []
    manager.active_changed.connect(active.append)
    manager.scan_now()

    manager.connect_receiver(RECEIVER_ID)
    assert manager.active_id == RECEIVER_ID
    assert store.status.receiver_connected is True
    assert store.status.receiver_name == "Samsung SM-A600F"

    manager.disconnect_receiver()
    assert manager.active_id is None
    assert store.status.receiver_connected is False
    assert store.status.receiver_name is None
    assert active == [RECEIVER_ID, None]


def test_cannot_connect_unknown_or_unready_receiver(
    manager: ReceiverManager, adb: FakeAdb, store: StatusStore
) -> None:
    with pytest.raises(ReceiverError, match="Unknown receiver"):
        manager.connect_receiver(RECEIVER_ID)

    adb.devices_output = DEVICES_UNAUTHORIZED
    manager.scan_now()
    with pytest.raises(ReceiverError, match="not ready"):
        manager.connect_receiver(RECEIVER_ID)
    assert store.status.receiver_connected is False


@pytest.mark.parametrize("later_output", [DEVICES_NONE, DEVICES_UNAUTHORIZED])
def test_losing_the_active_receiver_disconnects_it(
    manager: ReceiverManager, adb: FakeAdb, store: StatusStore, later_output: str
) -> None:
    manager.scan_now()
    manager.connect_receiver(RECEIVER_ID)

    adb.devices_output = later_output
    manager.scan_now()

    assert manager.active_id is None
    assert store.status.receiver_connected is False


def test_receivers_changed_is_emitted_only_on_change(manager: ReceiverManager) -> None:
    changes: list[object] = []
    manager.receivers_changed.connect(changes.append)

    manager.scan_now()
    manager.scan_now()

    assert len(changes) == 1


def test_scan_failure_clears_receivers_and_reports_once(
    manager: ReceiverManager, adb: FakeAdb, store: StatusStore
) -> None:
    failures: list[str] = []
    manager.scan_failed.connect(failures.append)
    manager.scan_now()
    manager.connect_receiver(RECEIVER_ID)

    adb.error = AdbNotFoundError("adb was not found")
    assert manager.scan_now() == []
    manager.scan_now()

    assert failures == ["adb was not found"]
    assert store.status.receiver_connected is False


def test_recovery_after_failure_is_announced_even_if_list_is_unchanged(
    store: StatusStore,
) -> None:
    adb = FakeAdb(DEVICES_NONE, error=AdbError("server down"))
    manager = ReceiverManager(store, adb)
    changes: list[object] = []
    manager.receivers_changed.connect(changes.append)
    manager.scan_now()

    adb.error = None
    manager.scan_now()

    assert changes == [[]]
    manager.close()


def test_background_scan_reports_through_signal(manager: ReceiverManager) -> None:
    (infos,) = wait_for(manager.receivers_changed, manager.scan)

    assert [info.receiver_id for info in infos] == [RECEIVER_ID]  # type: ignore[attr-defined]


def test_background_scan_failure_reports_through_signal(
    manager: ReceiverManager, adb: FakeAdb
) -> None:
    adb.error = AdbError("server down")

    assert wait_for(manager.scan_failed, manager.scan) == ("server down",)


def test_background_inspection_delivers_report(manager: ReceiverManager) -> None:
    manager.scan_now()

    (report,) = wait_for(manager.capabilities_ready, lambda: manager.inspect(RECEIVER_ID))

    assert isinstance(report, CapabilityReport)
    assert report.receiver_id == RECEIVER_ID


def test_background_inspection_failure_is_reported(manager: ReceiverManager, adb: FakeAdb) -> None:
    manager.scan_now()
    adb.error = AdbError("device offline")

    receiver_id, message = wait_for(
        manager.inspection_failed, lambda: manager.inspect(RECEIVER_ID)
    )

    assert (receiver_id, message) == (RECEIVER_ID, "device offline")


def test_inspecting_unknown_receiver_raises(manager: ReceiverManager) -> None:
    with pytest.raises(ReceiverError, match="Unknown receiver"):
        manager.inspect("android_adb:nope")
