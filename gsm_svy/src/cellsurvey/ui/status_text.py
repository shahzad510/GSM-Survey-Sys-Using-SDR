"""Text shown for application status, shared by the header and the dashboard."""

from __future__ import annotations

from datetime import timezone

from cellsurvey.state import AppStatus, SurveyState

NO_VALUE = "—"
"""Shown where a value is not available. Never substituted with a number."""

_SURVEY_LABELS = {
    SurveyState.IDLE: "Idle",
    SurveyState.RECORDING: "Recording",
    SurveyState.PAUSED: "Paused",
}


def receiver_text(status: AppStatus) -> str:
    """Connection state, with the receiver name when connected."""
    if not status.receiver_connected:
        return "Not connected"
    return status.receiver_name or "Connected"


def survey_text(status: AppStatus) -> str:
    """Survey state, with the session name while a survey is active."""
    label = _SURVEY_LABELS[status.survey_state]
    if status.survey_state is not SurveyState.IDLE and status.survey_name:
        return f"{label}: {status.survey_name}"
    return label


def technology_text(status: AppStatus) -> str:
    """Serving radio technology, if known."""
    return status.technology or NO_VALUE


def timestamp_text(status: AppStatus) -> str:
    """Time of the last measurement in UTC, if any."""
    if status.last_measurement_at is None:
        return NO_VALUE
    return status.last_measurement_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
