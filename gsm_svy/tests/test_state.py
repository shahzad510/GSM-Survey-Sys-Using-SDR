from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtWidgets import QApplication

from cellsurvey.state import AppStatus, StatusStore, SurveyState
from cellsurvey.ui import status_text


def test_initial_status_claims_nothing() -> None:
    status = AppStatus()

    assert status.receiver_connected is False
    assert status.survey_state is SurveyState.IDLE
    assert status.technology is None
    assert status.last_measurement_at is None


def test_update_emits_only_on_change(qapp: QApplication) -> None:
    store = StatusStore()
    seen: list[AppStatus] = []
    store.changed.connect(seen.append)

    store.update(technology="LTE")
    store.update(technology="LTE")

    assert seen == [AppStatus(technology="LTE")]
    assert store.status.technology == "LTE"


def test_update_rejects_unknown_field(qapp: QApplication) -> None:
    with pytest.raises(TypeError):
        StatusStore().update(signal_bars=4)


def test_status_text_for_unknown_values() -> None:
    status = AppStatus()

    assert status_text.receiver_text(status) == "Not connected"
    assert status_text.survey_text(status) == "Idle"
    assert status_text.technology_text(status) == status_text.NO_VALUE
    assert status_text.timestamp_text(status) == status_text.NO_VALUE


def test_status_text_for_known_values() -> None:
    status = AppStatus(
        receiver_connected=True,
        receiver_name="SM-A600F",
        survey_state=SurveyState.PAUSED,
        survey_name="Site A",
        technology="UMTS",
        last_measurement_at=datetime(2026, 1, 2, 8, 4, 5, tzinfo=timezone(timedelta(hours=5))),
    )

    assert status_text.receiver_text(status) == "SM-A600F"
    assert status_text.survey_text(status) == "Paused: Site A"
    assert status_text.technology_text(status) == "UMTS"
    assert status_text.timestamp_text(status) == "2026-01-02 03:04:05 UTC"
