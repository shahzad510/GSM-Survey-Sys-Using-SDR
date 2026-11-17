"""Receiver Manager page: detected receivers, connection and capability inspection."""

from __future__ import annotations

from datetime import timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from cellsurvey.receivers.base import (
    AccessMethod,
    CapabilityReport,
    ConnectionState,
    ReceiverError,
    ReceiverInfo,
    ReceiverKind,
)
from cellsurvey.receivers.manager import ReceiverManager
from cellsurvey.ui.navigation import PageSpec
from cellsurvey.ui.pages.base import BasePage, note, section_title
from cellsurvey.ui.status_text import NO_VALUE

_KIND_LABELS = {ReceiverKind.ANDROID_ADB: "Android phone (ADB)"}

_STATE_LABELS = {
    ConnectionState.READY: "Ready",
    ConnectionState.UNAUTHORIZED: "Unauthorized",
    ConnectionState.OFFLINE: "Offline",
    ConnectionState.NO_PERMISSIONS: "No USB permission",
    ConnectionState.UNAVAILABLE: "Unavailable",
    ConnectionState.DISCONNECTED: "Disconnected",
}

_STATE_HINTS = {
    ConnectionState.UNAUTHORIZED: (
        "Unlock the phone and accept the 'Allow USB debugging' prompt, then scan again."
    ),
    ConnectionState.OFFLINE: "The device is not responding. Reconnect the USB cable.",
    ConnectionState.NO_PERMISSIONS: (
        "This computer is not permitted to open the device. Check the Android udev "
        "rules and your membership of the plugdev group, then reconnect."
    ),
    ConnectionState.UNAVAILABLE: (
        "The device is in a mode that cannot be used. Boot it normally and reconnect."
    ),
}

_ACCESS_LABELS = {
    AccessMethod.DOCUMENTED_API: "Documented API",
    AccessMethod.DEVICE_DIAGNOSTICS: "Device diagnostics",
    AccessMethod.UNAVAILABLE: "Unavailable",
}

_NO_RECEIVERS = (
    "No receivers detected. Connect the phone by USB with USB debugging enabled. "
    "The list refreshes automatically."
)
_INSPECT_PROMPT = "Select a ready receiver and choose Inspect capabilities."


def _table(headers: tuple[str, ...]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return table


def _fill(table: QTableWidget, rows: list[tuple[str, ...]]) -> None:
    table.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            table.setItem(row, column, item)


class ReceiverManagerPage(BasePage):
    """Lists receivers found by the :class:`ReceiverManager` and acts on the selected one."""

    def __init__(
        self, spec: PageSpec, manager: ReceiverManager, parent: QWidget | None = None
    ) -> None:
        super().__init__(spec, parent)
        self._manager = manager
        self._infos: list[ReceiverInfo] = []
        self._reports: dict[str, CapabilityReport] = {}
        self._scan_error: str | None = None
        self._inspection_errors: dict[str, str] = {}
        self._inspecting: set[str] = set()

        self.scan_button = QPushButton("Scan now")
        self.scan_button.clicked.connect(lambda: manager.scan())
        receivers_header = QHBoxLayout()
        receivers_header.addWidget(section_title("Detected receivers"))
        receivers_header.addStretch(1)
        receivers_header.addWidget(self.scan_button)
        self.body.addLayout(receivers_header)

        self.receivers_table = _table(("Receiver", "Type", "Identifier", "Software", "Status"))
        self.receivers_table.itemSelectionChanged.connect(self._refresh_selection)
        self.body.addWidget(self.receivers_table, 1)
        self.message = note("")
        self.body.addWidget(self.message)

        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._toggle_connection)
        self.inspect_button = QPushButton("Inspect capabilities")
        self.inspect_button.clicked.connect(self._inspect)
        capabilities_header = QHBoxLayout()
        capabilities_header.addWidget(section_title("Capabilities of the selected receiver"))
        capabilities_header.addStretch(1)
        capabilities_header.addWidget(self.connect_button)
        capabilities_header.addWidget(self.inspect_button)
        self.body.addSpacing(8)
        self.body.addLayout(capabilities_header)

        self.capabilities_table = _table(("Data", "Access", "Source", "Finding"))
        capability_columns = self.capabilities_table.horizontalHeader()
        for column in range(3):
            capability_columns.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.body.addWidget(self.capabilities_table, 3)
        self.capabilities_note = note("")
        self.body.addWidget(self.capabilities_note)
        self.body.addWidget(
            note(
                "The phone is a measurement source, not an SDR: it reports only what "
                "Android exposes without root access or modem modification. "
                "SDR receivers are planned for Milestone 7."
            )
        )

        manager.receivers_changed.connect(self._on_receivers_changed)
        manager.active_changed.connect(self._on_active_changed)
        manager.scan_failed.connect(self._on_scan_failed)
        manager.capabilities_ready.connect(self._on_capabilities_ready)
        manager.inspection_failed.connect(self._on_inspection_failed)
        self._on_receivers_changed(manager.receivers())

    def selected(self) -> ReceiverInfo | None:
        """The receiver whose row is selected, if any."""
        row = self.receivers_table.currentRow()
        return self._infos[row] if 0 <= row < len(self._infos) else None

    # -- manager signals -----------------------------------------------------

    def _on_receivers_changed(self, infos: list[ReceiverInfo]) -> None:
        previous = self.selected()
        self._infos = list(infos)
        self._scan_error = None
        self._fill_receivers()

        ids = [info.receiver_id for info in self._infos]
        if previous is not None and previous.receiver_id in ids:
            self.receivers_table.selectRow(ids.index(previous.receiver_id))
        elif ids:
            self.receivers_table.selectRow(0)
        self._refresh_selection()

    def _on_active_changed(self, _receiver_id: str | None) -> None:
        row = self.receivers_table.currentRow()
        self._fill_receivers()
        if row >= 0:
            self.receivers_table.selectRow(row)
        self._refresh_selection()

    def _on_scan_failed(self, message: str) -> None:
        self._scan_error = message
        self._refresh_selection()

    def _on_capabilities_ready(self, report: CapabilityReport) -> None:
        self._inspecting.discard(report.receiver_id)
        self._inspection_errors.pop(report.receiver_id, None)
        self._reports[report.receiver_id] = report
        self._refresh_selection()

    def _on_inspection_failed(self, receiver_id: str, message: str) -> None:
        self._inspecting.discard(receiver_id)
        self._inspection_errors[receiver_id] = message
        self._refresh_selection()

    # -- user actions --------------------------------------------------------

    def _toggle_connection(self) -> None:
        info = self.selected()
        if info is None:
            return
        if info.receiver_id == self._manager.active_id:
            self._manager.disconnect_receiver()
            return
        try:
            self._manager.connect_receiver(info.receiver_id)
        except ReceiverError as exc:
            # The receiver changed state between the last scan and the click.
            self.message.setText(str(exc))

    def _inspect(self) -> None:
        info = self.selected()
        if info is None:
            return
        self._inspecting.add(info.receiver_id)
        self._refresh_selection()
        try:
            self._manager.inspect(info.receiver_id)
        except ReceiverError as exc:
            self._on_inspection_failed(info.receiver_id, str(exc))

    # -- display -------------------------------------------------------------

    def _fill_receivers(self) -> None:
        # Refilling must not be mistaken for the user changing the selection.
        self.receivers_table.blockSignals(True)
        _fill(
            self.receivers_table,
            [
                (
                    info.display_name,
                    _KIND_LABELS[info.kind],
                    info.identifier,
                    info.software_version or NO_VALUE,
                    self._status_text(info),
                )
                for info in self._infos
            ],
        )
        self.receivers_table.blockSignals(False)

    def _status_text(self, info: ReceiverInfo) -> str:
        if info.receiver_id == self._manager.active_id:
            return "Connected"
        label = _STATE_LABELS[info.state]
        return f"{label} ({info.state_detail})" if info.state_detail else label

    def _refresh_selection(self) -> None:
        info = self.selected()
        ready = info is not None and info.state is ConnectionState.READY
        active = info is not None and info.receiver_id == self._manager.active_id
        inspecting = info is not None and info.receiver_id in self._inspecting

        self.connect_button.setText("Disconnect" if active else "Connect")
        self.connect_button.setEnabled(ready or active)
        self.inspect_button.setEnabled(ready and not inspecting)

        if self._scan_error is not None:
            self.message.setText(self._scan_error)
        elif info is None:
            self.message.setText(_NO_RECEIVERS)
        else:
            self.message.setText(_STATE_HINTS.get(info.state, ""))

        report = self._reports.get(info.receiver_id) if info is not None else None
        _fill(
            self.capabilities_table,
            [
                (
                    capability.name,
                    _ACCESS_LABELS[capability.access],
                    capability.source or NO_VALUE,
                    capability.detail,
                )
                for capability in (report.capabilities if report else ())
            ],
        )
        self.capabilities_note.setText(self._capabilities_text(info, report, inspecting))

    def _capabilities_text(
        self, info: ReceiverInfo | None, report: CapabilityReport | None, inspecting: bool
    ) -> str:
        if inspecting:
            return "Inspecting…"
        if info is not None and info.receiver_id in self._inspection_errors:
            return f"Inspection failed: {self._inspection_errors[info.receiver_id]}"
        if report is None:
            return _INSPECT_PROMPT
        inspected = report.inspected_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return (
            f"Inspected {inspected}. This shows which diagnostic sources respond. Which "
            "individual measurements they contain is established in Milestone 3."
        )
