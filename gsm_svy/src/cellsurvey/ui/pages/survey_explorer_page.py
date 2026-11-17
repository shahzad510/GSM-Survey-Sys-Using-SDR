"""Browse, inspect, export and delete imported surveys."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cellsurvey.database.repositories.survey_repository import (
    SurveyFilter,
    SurveySummary,
)
from cellsurvey.schema import field_unit
from cellsurvey.survey_import.validation import CHECK_LABELS
from cellsurvey.survey_processing.exporter import ExportFormat, export_records
from cellsurvey.surveys import SurveyService
from cellsurvey.ui.navigation import PageSpec
from cellsurvey.ui.pages.base import BasePage, note, section_title
from cellsurvey.ui.status_text import NO_VALUE
from cellsurvey.ui.tables import fill_table, make_table

_EXPORT_FILTERS = {
    ExportFormat.CSV: ("CSV (*.csv)", "csv"),
    ExportFormat.JSON: ("JSON (*.json)", "json"),
    ExportFormat.XLSX: ("Excel (*.xlsx)", "xlsx"),
    ExportFormat.GEOJSON: ("GeoJSON (*.geojson)", "geojson"),
}
_ALL = "(all)"


class SurveyExplorerPage(BasePage):
    """Searchable list of imported surveys with record and import details."""

    def __init__(
        self, spec: PageSpec, surveys: SurveyService, parent: QWidget | None = None
    ) -> None:
        super().__init__(spec, parent)
        self._surveys = surveys
        self._repository = surveys.repository
        self._summaries: list[SurveySummary] = []
        self._visible: list[SurveySummary] = []

        self.body.addLayout(self._build_filters())
        actions = QHBoxLayout()
        self._refresh = QPushButton("Refresh")
        self._refresh.clicked.connect(self.reload)
        self._open = QPushButton("Open")
        self._open.clicked.connect(self._open_selected)
        self._export = QPushButton("Export…")
        self._export.clicked.connect(self._export_selected)
        self._delete = QPushButton("Delete…")
        self._delete.clicked.connect(self._delete_selected)
        for button in (self._refresh, self._open, self._export, self._delete):
            actions.addWidget(button)
        actions.addStretch(1)
        self.body.addLayout(actions)

        self._surveys_table = make_table(
            (
                "Name",
                "Records",
                "First measurement",
                "Last measurement",
                "Technology",
                "Country",
                "Operator",
                "Instrument",
                "Source file",
            )
        )
        self._surveys_table.itemSelectionChanged.connect(self._refresh_actions)
        self._surveys_table.itemDoubleClicked.connect(lambda _: self._open_selected())
        self.body.addWidget(self._surveys_table, 1)
        self._list_message = note("No imported surveys yet. Use Import Survey to add one.")
        self.body.addWidget(self._list_message)

        self._detail_tabs = QTabWidget()
        self._records_table = make_table(())
        self._imports_text = QTextEdit()
        self._imports_text.setReadOnly(True)
        self._detail_tabs.addTab(self._records_table, "Records")
        self._detail_tabs.addTab(self._imports_text, "Import metadata")
        self.body.addWidget(section_title("Selected survey"))
        self.body.addWidget(self._detail_tabs, 2)

        surveys.surveys_changed.connect(self.reload)
        self.reload()

    def _build_filters(self) -> QFormLayout:
        form = QFormLayout()
        self._name = QLineEdit()
        self._name.setPlaceholderText("Contains…")
        self._name.textChanged.connect(self._apply_filters)
        self._from = QDateEdit()
        self._from.setCalendarPopup(True)
        self._from.setSpecialValueText(_ALL)
        self._from.setDate(self._from.minimumDate())
        self._from.dateChanged.connect(self._apply_filters)
        self._to = QDateEdit()
        self._to.setCalendarPopup(True)
        self._to.setSpecialValueText(_ALL)
        self._to.setDate(self._to.minimumDate())
        self._to.dateChanged.connect(self._apply_filters)
        self._technology = QComboBox()
        self._country = QComboBox()
        self._operator = QComboBox()
        self._mcc = QComboBox()
        self._mnc = QComboBox()
        self._instrument = QComboBox()
        for box in (
            self._technology,
            self._country,
            self._operator,
            self._mcc,
            self._mnc,
            self._instrument,
        ):
            box.currentIndexChanged.connect(self._apply_filters)
        form.addRow("Survey name", self._name)
        dates = QHBoxLayout()
        dates.addWidget(QLabel("From"))
        dates.addWidget(self._from)
        dates.addWidget(QLabel("To"))
        dates.addWidget(self._to)
        dates.addStretch(1)
        form.addRow("Survey date", dates)
        form.addRow("Technology", self._technology)
        form.addRow("Country", self._country)
        form.addRow("Operator", self._operator)
        form.addRow("MCC", self._mcc)
        form.addRow("MNC", self._mnc)
        form.addRow("Instrument", self._instrument)
        return form

    # -- list ------------------------------------------------------------------

    def reload(self) -> None:
        """Reload surveys from the database."""
        selected_id = self._selected_id()
        self._summaries = self._repository.list_surveys()
        self._refill_filter_choices()
        self._apply_filters()
        if selected_id is not None:
            for row, summary in enumerate(self._visible):
                if summary.survey_id == selected_id:
                    self._surveys_table.selectRow(row)
                    break
        self._refresh_actions()

    def _refill_filter_choices(self) -> None:
        def refill(box: QComboBox, values: set[str]) -> None:
            current = box.currentData()
            box.blockSignals(True)
            box.clear()
            box.addItem(_ALL, None)
            for value in sorted(values):
                box.addItem(value, value)
            index = box.findData(current)
            box.setCurrentIndex(max(0, index))
            box.blockSignals(False)

        refill(self._technology, {value for s in self._summaries for value in s.technologies})
        refill(self._country, {value for s in self._summaries for value in s.countries})
        refill(self._operator, {value for s in self._summaries for value in s.operators})
        refill(self._mcc, {value for s in self._summaries for value in s.mccs})
        refill(self._mnc, {value for s in self._summaries for value in s.mncs})
        refill(self._instrument, {value for s in self._summaries for value in s.instruments})

    def _apply_filters(self) -> None:
        criteria = SurveyFilter(
            name=self._name.text(),
            date_from=_optional_date(self._from),
            date_to=_optional_date(self._to),
            technology=self._technology.currentData(),
            country=self._country.currentData(),
            operator=self._operator.currentData(),
            instrument=self._instrument.currentData(),
        )
        self._visible = [summary for summary in self._summaries if criteria.matches(summary)]
        fill_table(
            self._surveys_table,
            [
                (
                    summary.name,
                    summary.record_count,
                    _timestamp(summary.first_timestamp),
                    _timestamp(summary.last_timestamp),
                    ", ".join(summary.technologies) or NO_VALUE,
                    ", ".join(summary.countries) or NO_VALUE,
                    ", ".join(summary.operators) or NO_VALUE,
                    ", ".join(summary.instruments) or NO_VALUE,
                    ", ".join(summary.source_files) or NO_VALUE,
                )
                for summary in self._visible
            ],
        )
        if self._summaries and not self._visible:
            self._list_message.setText("No surveys match the current filters.")
        elif not self._summaries:
            self._list_message.setText("No imported surveys yet. Use Import Survey to add one.")
        else:
            self._list_message.setText(
                f"Showing {len(self._visible)} of {len(self._summaries)} surveys."
            )
        self._clear_details()
        self._refresh_actions()

    def _selected(self) -> SurveySummary | None:
        row = self._surveys_table.currentRow()
        return self._visible[row] if 0 <= row < len(self._visible) else None

    def _selected_id(self) -> int | None:
        selected = self._selected()
        return None if selected is None else selected.survey_id

    def _refresh_actions(self) -> None:
        selected = self._selected() is not None
        self._open.setEnabled(selected)
        self._export.setEnabled(selected)
        self._delete.setEnabled(selected)

    # -- details ---------------------------------------------------------------

    def _clear_details(self) -> None:
        self._records_table.setRowCount(0)
        self._records_table.setColumnCount(0)
        self._imports_text.clear()

    def _open_selected(self) -> None:
        summary = self._selected()
        if summary is None:
            return
        fields = self._repository.populated_fields(summary.survey_id)
        headers = ["source_row", *fields, "measurement_method"]
        self._records_table.setColumnCount(len(headers))
        self._records_table.setHorizontalHeaderLabels(
            [
                f"{name}" + (f" ({unit})" if (unit := field_unit(name)) else "")
                if name in fields
                else name
                for name in headers
            ]
        )
        records = self._repository.records(summary.survey_id, limit=500)
        fill_table(
            self._records_table,
            [
                [
                    record.source_row,
                    *[
                        _display(getattr(record, name))
                        for name in fields
                    ],
                    _display(record.measurement_method),
                ]
                for record in records
            ],
        )
        more = max(0, summary.record_count - len(records))
        self._detail_tabs.setTabText(
            0, f"Records ({len(records)}" + (f", {more} more" if more else "") + ")"
        )

        blocks = []
        for details in self._repository.import_details(summary.survey_id):
            findings = "\n".join(
                f"  - [{finding.severity.value}] {CHECK_LABELS.get(finding.check, finding.check)}"
                f"{' / ' + finding.field if finding.field else ''}: {finding.message}"
                f" (rows={finding.row_count or 0})"
                for finding in details.findings
            ) or "  (none)"
            blocks.append(
                f"Imported {details.imported_at:%Y-%m-%d %H:%M:%S} UTC\n"
                f"Source file: {details.filename}\n"
                f"Original path: {details.original_path}\n"
                f"Archived copy: {details.archived_path}\n"
                f"SHA-256: {details.sha256}\n"
                f"Format: {details.source_format}; size: {details.size_bytes} bytes\n"
                f"Table: {details.table_name}\n"
                f"Instrument: {details.source_instrument or NO_VALUE}\n"
                f"Software: {details.source_software or NO_VALUE}\n"
                f"Method: {details.measurement_method}\n"
                f"Rows read: {details.rows_read}; records imported: {details.records_imported}\n"
                f"Column mapping: {details.column_mapping}\n"
                f"Options: {details.options}\n"
                f"Imported by Cellular Survey System {details.software_version}\n"
                f"Validation findings:\n{findings}"
            )
        self._imports_text.setPlainText(
            f"Survey: {summary.name}\nNotes: {summary.notes or NO_VALUE}\n\n"
            + ("\n\n".join(blocks) if blocks else "No import metadata.")
        )
        self._detail_tabs.setCurrentIndex(0)

    # -- export / delete -------------------------------------------------------

    def _export_selected(self) -> None:
        summary = self._selected()
        if summary is None:
            return
        path_str, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export survey",
            f"{summary.name}.csv",
            ";;".join(label for label, _ in _EXPORT_FILTERS.values()),
        )
        if not path_str:
            return
        export_format = next(
            fmt for fmt, (label, _) in _EXPORT_FILTERS.items() if label == selected_filter
        )
        path = Path(path_str)
        if path.suffix.lower() != f".{_EXPORT_FILTERS[export_format][1]}":
            path = path.with_suffix(f".{_EXPORT_FILTERS[export_format][1]}")
        try:
            result = export_records(self._repository.records(summary.survey_id), path, export_format)
        except OSError as exc:
            QMessageBox.warning(self, "Export", f"Could not write {path.name}: {exc}")
            return
        message = f"Wrote {result.written} records to {result.path}."
        if result.skipped_without_position:
            message += (
                f"\n{result.skipped_without_position} records without coordinates "
                "were omitted from the GeoJSON export."
            )
        QMessageBox.information(self, "Export complete", message)

    def _delete_selected(self) -> None:
        summary = self._selected()
        if summary is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete survey",
            f"Delete survey “{summary.name}” and its {summary.record_count} stored records?\n\n"
            "The original source file and its archived copy are kept.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self._repository.delete_survey(summary.survey_id):
            self._surveys.notify_changed()
            self._clear_details()


def _optional_date(widget: QDateEdit) -> date | None:
    value = widget.date()
    if value == widget.minimumDate():
        return None
    return date(value.year(), value.month(), value.day())


def _timestamp(value: datetime | None) -> str:
    if value is None:
        return NO_VALUE
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _display(value: object) -> str:
    if value is None:
        return NO_VALUE
    if hasattr(value, "value"):
        return str(value.value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(value)
