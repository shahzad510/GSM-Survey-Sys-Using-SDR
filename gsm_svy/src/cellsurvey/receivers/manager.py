"""Receiver Manager: detects receivers, tracks their status and the active one.

ADB commands block, so detection and inspection run on a single worker thread.
Results are handed back through a Qt signal and applied on the thread this
object lives in, which keeps all state changes on one thread.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from cellsurvey.receivers.adb import AdbClient
from cellsurvey.receivers.android import AndroidADBReceiver
from cellsurvey.receivers.base import BaseReceiver, ConnectionState, ReceiverError, ReceiverInfo
from cellsurvey.state import StatusStore

logger = logging.getLogger(__name__)

POLL_INTERVAL_MS = 5000


class ReceiverManager(QObject):
    """Keeps the list of attached receivers current and manages the active receiver."""

    receivers_changed = Signal(object)
    """Emitted with ``list[ReceiverInfo]`` when the set or state of receivers changes."""
    active_changed = Signal(object)
    """Emitted with the active receiver's id, or ``None`` when there is none."""
    scan_failed = Signal(str)
    """Emitted with a message when receivers could not be listed."""
    capabilities_ready = Signal(object)
    """Emitted with a :class:`CapabilityReport` when an inspection finishes."""
    inspection_failed = Signal(str, str)
    """Emitted with ``(receiver_id, message)`` when an inspection fails."""

    _job_finished = Signal(object, object, object)

    def __init__(self, store: StatusStore, adb: AdbClient, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._adb = adb
        self._receivers: dict[str, BaseReceiver] = {}
        self._infos: list[ReceiverInfo] = []
        self._active_id: str | None = None
        self._last_error: str | None = None
        self._scan_pending = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="receiver")
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.scan)
        # Queued, so results are always delivered from the event loop, even when
        # a job finishes before its completion callback is attached.
        self._job_finished.connect(self._on_job_finished, Qt.ConnectionType.QueuedConnection)

    @property
    def active_id(self) -> str | None:
        """Identifier of the receiver in use, if any."""
        return self._active_id

    def receivers(self) -> list[ReceiverInfo]:
        """Receivers found by the most recent scan."""
        return list(self._infos)

    def start(self) -> None:
        """Scan now and keep rescanning periodically."""
        self.scan()
        self._timer.start()

    def close(self) -> None:
        """Stop scanning and wait for the command in progress, if any."""
        self._timer.stop()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def scan(self) -> None:
        """Look for receivers in the background; results arrive through signals."""
        if self._scan_pending:
            return
        self._scan_pending = True
        self._submit(self._discover, self._apply_scan, self._on_scan_error)

    def scan_now(self) -> list[ReceiverInfo]:
        """Look for receivers and wait for the result."""
        try:
            found = self._discover()
        except ReceiverError as exc:
            self._on_scan_error(exc)
        else:
            self._apply_scan(found)
        return self.receivers()

    def connect_receiver(self, receiver_id: str) -> None:
        """Make a ready receiver the active measurement source.

        Raises:
            ReceiverError: the receiver is unknown or not ready.
        """
        info = self._info(receiver_id)
        if info is None:
            raise ReceiverError(f"Unknown receiver: {receiver_id}")
        if info.state is not ConnectionState.READY:
            raise ReceiverError(f"{info.display_name} is not ready (state: {info.state.value})")
        self._active_id = receiver_id
        self._store.update(receiver_connected=True, receiver_name=info.display_name)
        logger.info("Receiver connected", extra={"receiver_id": receiver_id})
        self.active_changed.emit(receiver_id)

    def disconnect_receiver(self) -> None:
        """Stop using the active receiver. Does nothing if there is none."""
        if self._active_id is None:
            return
        logger.info("Receiver disconnected", extra={"receiver_id": self._active_id})
        self._active_id = None
        self._store.update(receiver_connected=False, receiver_name=None)
        self.active_changed.emit(None)

    def inspect(self, receiver_id: str) -> None:
        """Inspect a receiver's capabilities in the background.

        Raises:
            ReceiverError: the receiver is unknown.
        """
        receiver = self._receivers.get(receiver_id)
        if receiver is None:
            raise ReceiverError(f"Unknown receiver: {receiver_id}")

        def failed(exc: BaseException) -> None:
            logger.warning(
                "Capability inspection failed: %s", exc, extra={"receiver_id": receiver_id}
            )
            self.inspection_failed.emit(receiver_id, str(exc))

        self._submit(receiver.inspect_capabilities, self.capabilities_ready.emit, failed)

    # -- worker thread -----------------------------------------------------

    def _discover(self) -> dict[str, BaseReceiver]:
        found: dict[str, BaseReceiver] = {}
        for device in self._adb.devices():
            receiver_id = AndroidADBReceiver.receiver_id_for(device.serial)
            receiver = self._receivers.get(receiver_id)
            if not isinstance(receiver, AndroidADBReceiver):
                receiver = AndroidADBReceiver(self._adb, device.serial)
            receiver.update(device)
            found[receiver_id] = receiver
        return found

    def _submit(
        self,
        work: Callable[[], object],
        on_done: Callable[[object], None],
        on_error: Callable[[BaseException], None],
    ) -> None:
        future = self._executor.submit(work)
        future.add_done_callback(lambda done: self._job_finished.emit(done, on_done, on_error))

    # -- owning thread -----------------------------------------------------

    def _on_job_finished(
        self,
        future: Future[object],
        on_done: Callable[[object], None],
        on_error: Callable[[BaseException], None],
    ) -> None:
        if future.cancelled():
            return
        error = future.exception()
        if error is None:
            on_done(future.result())
            return
        if not isinstance(error, ReceiverError):
            logger.error("Unexpected receiver error", exc_info=error)
        on_error(error)

    def _apply_scan(self, found: dict[str, BaseReceiver]) -> None:
        self._scan_pending = False
        self._receivers = found
        infos = [receiver.info for receiver in found.values()]
        recovered = self._last_error is not None
        self._last_error = None

        active = self._info(self._active_id, infos)
        if self._active_id is not None:
            if active is None or active.state is not ConnectionState.READY:
                logger.warning("Active receiver lost", extra={"receiver_id": self._active_id})
                self.disconnect_receiver()
            else:
                self._store.update(receiver_name=active.display_name)

        if infos != self._infos or recovered:
            self._infos = infos
            logger.info(
                "Receivers changed",
                extra={"receivers": {info.identifier: info.state.value for info in infos}},
            )
            self.receivers_changed.emit(list(infos))

    def _on_scan_error(self, error: BaseException) -> None:
        self._scan_pending = False
        # Without a device list nothing is known to be attached.
        self.disconnect_receiver()
        self._receivers = {}
        if self._infos:
            self._infos = []
            self.receivers_changed.emit([])
        message = str(error)
        if message != self._last_error:
            self._last_error = message
            logger.warning("Receiver scan failed: %s", message)
            self.scan_failed.emit(message)

    def _info(
        self, receiver_id: str | None, infos: list[ReceiverInfo] | None = None
    ) -> ReceiverInfo | None:
        for info in self._infos if infos is None else infos:
            if info.receiver_id == receiver_id:
                return info
        return None
