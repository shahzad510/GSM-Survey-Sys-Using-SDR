"""Status strip above the working area.

Shows the receiver connection, current survey, serving technology and the
time of the last measurement.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QWidget

from cellsurvey.state import AppStatus, StatusStore, SurveyState
from cellsurvey.ui import status_text

_SURVEY_LEVELS = {
    SurveyState.IDLE: "off",
    SurveyState.RECORDING: "ok",
    SurveyState.PAUSED: "warn",
}


class StatusIndicator(QWidget):
    """A caption over a value, optionally preceded by a coloured state dot."""

    def __init__(self, caption: str, with_dot: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(7)
        layout.setVerticalSpacing(2)

        caption_label = QLabel(caption.upper())
        caption_label.setObjectName("indicatorCaption")
        self._value = QLabel()
        self._value.setObjectName("indicatorValue")

        self._dot: QLabel | None = None
        column = 0
        if with_dot:
            self._dot = QLabel()
            self._dot.setObjectName("statusDot")
            self._dot.setFixedSize(10, 10)
            layout.addWidget(self._dot, 1, 0)
            column = 1
        layout.addWidget(caption_label, 0, column)
        layout.addWidget(self._value, 1, column)

    def set_value(self, text: str, level: str = "off") -> None:
        """Set the value text and the dot level (``"off"``, ``"ok"`` or ``"warn"``)."""
        self._value.setText(text)
        if self._dot is not None and self._dot.property("level") != level:
            self._dot.setProperty("level", level)
            # Re-evaluate the stylesheet for the changed dynamic property.
            self._dot.style().unpolish(self._dot)
            self._dot.style().polish(self._dot)

    def text(self) -> str:
        """The value currently displayed."""
        return self._value.text()

    def level(self) -> str | None:
        """The dot level, or ``None`` for an indicator without a dot."""
        return None if self._dot is None else self._dot.property("level")


class StatusHeader(QFrame):
    """Displays the :class:`AppStatus` held by a :class:`StatusStore`."""

    def __init__(self, store: StatusStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusHeader")

        self.receiver = StatusIndicator("Receiver", with_dot=True)
        self.survey = StatusIndicator("Survey", with_dot=True)
        self.technology = StatusIndicator("Technology")
        self.timestamp = StatusIndicator("Last measurement")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(48)
        for indicator in (self.receiver, self.survey, self.technology, self.timestamp):
            layout.addWidget(indicator)
        layout.addStretch(1)

        store.changed.connect(self._apply)
        self._apply(store.status)

    def _apply(self, status: AppStatus) -> None:
        self.receiver.set_value(
            status_text.receiver_text(status), "ok" if status.receiver_connected else "off"
        )
        self.survey.set_value(status_text.survey_text(status), _SURVEY_LEVELS[status.survey_state])
        self.technology.set_value(status_text.technology_text(status))
        self.timestamp.set_value(status_text.timestamp_text(status))
