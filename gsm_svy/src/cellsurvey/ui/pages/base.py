"""Common page layout and the generic placeholder page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from cellsurvey.ui.navigation import PageSpec


def section_title(text: str) -> QLabel:
    """A heading for a block of content inside a page."""
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def note(text: str) -> QLabel:
    """Muted, word-wrapped explanatory text."""
    label = QLabel(text)
    label.setObjectName("note")
    label.setWordWrap(True)
    return label


class BasePage(QWidget):
    """A page with a title, a one-line summary and a ``body`` layout for content."""

    def __init__(self, spec: PageSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spec = spec

        title = QLabel(spec.title)
        title.setObjectName("pageTitle")
        summary = QLabel(spec.summary)
        summary.setObjectName("pageSummary")

        self._title_row = QHBoxLayout()
        self._title_row.addWidget(title)
        self._title_row.addStretch(1)

        self.body = QVBoxLayout()
        self.body.setSpacing(12)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(4)
        layout.addLayout(self._title_row)
        layout.addWidget(summary)
        layout.addSpacing(14)
        layout.addLayout(self.body, 1)

    def add_badge(self, text: str) -> None:
        """Show a small label to the right of the page title."""
        badge = QLabel(text)
        badge.setObjectName("badge")
        self._title_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)


class PlaceholderPage(BasePage):
    """Stands in for a page that a later milestone implements."""

    def __init__(self, spec: PageSpec, parent: QWidget | None = None) -> None:
        super().__init__(spec, parent)
        if spec.milestone is None:
            self.add_badge("Not implemented yet")
            self.body.addWidget(note("This page is not implemented yet."))
        else:
            self.add_badge(f"Planned: Milestone {spec.milestone}")
            self.body.addWidget(
                note(f"This page is not implemented yet. It is part of Milestone {spec.milestone}.")
            )
        if spec.planned:
            self.body.addWidget(section_title("Planned capabilities"))
            self.body.addWidget(QLabel("\n".join(f"•  {item}" for item in spec.planned)))
        self.body.addStretch(1)
