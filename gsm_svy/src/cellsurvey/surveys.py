"""Survey storage services used by the desktop UI."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from cellsurvey.config import AppPaths
from cellsurvey.database import Database
from cellsurvey.database.repositories.survey_repository import SurveyRepository
from cellsurvey.survey_import.importer import SurveyImporter

logger = logging.getLogger(__name__)


class SurveyService(QObject):
    """Opens the survey database and notifies the UI when surveys change."""

    surveys_changed = Signal()
    """Emitted after a survey is imported or deleted."""

    def __init__(self, paths: AppPaths, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.database = Database(paths.database_file)
        self.repository = SurveyRepository(self.database)
        self.importer = SurveyImporter(self.repository, paths.survey_sources_dir)

    def notify_changed(self) -> None:
        """Tell the UI that the list of surveys should be reloaded."""
        self.surveys_changed.emit()

    def close(self) -> None:
        """Release the database file."""
        self.database.close()
        logger.info("Survey database closed")
