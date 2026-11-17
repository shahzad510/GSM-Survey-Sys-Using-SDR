"""Dashboard: current status and application information."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from cellsurvey import __version__
from cellsurvey.config import AppPaths
from cellsurvey.state import AppStatus, StatusStore
from cellsurvey.ui import status_text
from cellsurvey.ui.navigation import PageSpec
from cellsurvey.ui.pages.base import BasePage, note, section_title


class StatCard(QFrame):
    """A bordered card showing one captioned value."""

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        caption_label = QLabel(caption.upper())
        caption_label.setObjectName("cardCaption")
        self._value = QLabel()
        self._value.setObjectName("cardValue")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        layout.addWidget(caption_label)
        layout.addWidget(self._value)

    def set_value(self, text: str) -> None:
        """Set the displayed value."""
        self._value.setText(text)

    def text(self) -> str:
        """The value currently displayed."""
        return self._value.text()


class DashboardPage(BasePage):
    """Summarises the :class:`AppStatus` and shows where the application keeps its files."""

    def __init__(
        self,
        spec: PageSpec,
        store: StatusStore,
        paths: AppPaths,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(spec, parent)

        self.receiver_card = StatCard("Receiver")
        self.survey_card = StatCard("Survey")
        self.technology_card = StatCard("Technology")
        self.timestamp_card = StatCard("Last measurement")

        cards = QHBoxLayout()
        cards.setSpacing(12)
        for card in (
            self.receiver_card,
            self.survey_card,
            self.technology_card,
            self.timestamp_card,
        ):
            cards.addWidget(card, 1)
        self.body.addLayout(cards)
        self.body.addWidget(
            note(
                "Connect a receiver on the Receiver Manager page. Measurement acquisition "
                "arrives in Milestone 3, so technology and measurements are not shown yet."
            )
        )

        self.body.addSpacing(8)
        self.body.addWidget(section_title("Application"))
        self.body.addWidget(self._application_card(paths))
        self.body.addStretch(1)

        store.changed.connect(self._apply)
        self._apply(store.status)

    @staticmethod
    def _application_card(paths: AppPaths) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        form = QFormLayout(card)
        form.setContentsMargins(16, 14, 16, 14)
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(8)
        for caption, value in (
            ("Version", __version__),
            ("Configuration file", str(paths.config_file)),
            ("Database", str(paths.database_file)),
            ("Survey source archive", str(paths.survey_sources_dir)),
            ("Log file", str(paths.log_file)),
        ):
            value_label = QLabel(value)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(caption, value_label)
        return card

    def _apply(self, status: AppStatus) -> None:
        self.receiver_card.set_value(status_text.receiver_text(status))
        self.survey_card.set_value(status_text.survey_text(status))
        self.technology_card.set_value(status_text.technology_text(status))
        self.timestamp_card.set_value(status_text.timestamp_text(status))
