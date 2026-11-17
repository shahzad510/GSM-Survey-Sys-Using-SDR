"""Application-wide status shared between the header, dashboard and pages.

Later milestones (receiver manager, acquisition, survey manager) publish their
state here; the UI only ever reads it. Values that are not known are ``None``
and are never replaced with invented defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum

from PySide6.QtCore import QObject, Signal


class SurveyState(Enum):
    """Lifecycle of the current survey session."""

    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"


@dataclass(frozen=True)
class AppStatus:
    """Snapshot of what the application currently knows."""

    receiver_connected: bool = False
    receiver_name: str | None = None
    survey_state: SurveyState = SurveyState.IDLE
    survey_name: str | None = None
    technology: str | None = None
    """Serving radio technology (e.g. ``"GSM"``, ``"UMTS"``, ``"LTE"``)."""
    last_measurement_at: datetime | None = None
    """Time of the most recent measurement; must be timezone-aware."""


class StatusStore(QObject):
    """Holds the current :class:`AppStatus` and notifies listeners of changes."""

    changed = Signal(object)
    """Emitted with the new :class:`AppStatus` whenever it differs from the old one."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._status = AppStatus()

    @property
    def status(self) -> AppStatus:
        """The current status snapshot."""
        return self._status

    def update(self, **changes: object) -> None:
        """Replace the given :class:`AppStatus` fields.

        Raises:
            TypeError: a keyword is not an ``AppStatus`` field.
        """
        updated = replace(self._status, **changes)
        if updated != self._status:
            self._status = updated
            self.changed.emit(updated)
