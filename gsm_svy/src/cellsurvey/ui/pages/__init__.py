"""Navigation pages."""

from __future__ import annotations

from cellsurvey.config import AppPaths
from cellsurvey.receivers.manager import ReceiverManager
from cellsurvey.state import StatusStore
from cellsurvey.surveys import SurveyService
from cellsurvey.ui.navigation import PageSpec
from cellsurvey.ui.pages.base import BasePage, PlaceholderPage
from cellsurvey.ui.pages.dashboard import DashboardPage
from cellsurvey.ui.pages.receiver_manager import ReceiverManagerPage
from cellsurvey.ui.pages.survey_explorer_page import SurveyExplorerPage
from cellsurvey.ui.pages.survey_import_page import SurveyImportPage


def create_page(
    spec: PageSpec,
    store: StatusStore,
    paths: AppPaths,
    receivers: ReceiverManager,
    surveys: SurveyService,
) -> BasePage:
    """Build the widget for ``spec``; pages without an implementation get a placeholder."""
    if spec.key == "dashboard":
        return DashboardPage(spec, store, paths)
    if spec.key == "receivers":
        return ReceiverManagerPage(spec, receivers)
    if spec.key == "import":
        return SurveyImportPage(spec, surveys)
    if spec.key == "explorer":
        return SurveyExplorerPage(spec, surveys)
    return PlaceholderPage(spec)
