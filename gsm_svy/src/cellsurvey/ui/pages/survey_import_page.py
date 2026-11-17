"""Six-step wizard for importing a historical survey file."""

from __future__ import annotations

from datetime import timezone
from pathlib import Path
from zoneinfo import available_timezones

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cellsurvey.survey_import.column_mapper import (
    MAPPABLE_FIELDS,
    suggest_mapping,
    validate_mapping,
)
from cellsurvey.survey_import.file_detector import SUPPORTED_EXTENSIONS
from cellsurvey.survey_import.importer import (
    PreparedImport,
    SurveyImporter,
    already_imported_message,
    load_source,
)
from cellsurvey.survey_import.source import SourceFile, SurveyImportError
from cellsurvey.survey_import.validation import CHECK_LABELS, Severity
from cellsurvey.survey_processing.normalizer import (
    DateOrder,
    NormalizationOptions,
    suggest_date_order,
)
from cellsurvey.surveys import SurveyService
from cellsurvey.ui.navigation import PageSpec
from cellsurvey.ui.pages.base import BasePage, note, section_title
from cellsurvey.ui.status_text import NO_VALUE
from cellsurvey.ui.tables import fill_table, make_table

_STEPS = (
    "1. Select file",
    "2. Inspect",
    "3. Map columns",
    "4. Validate",
    "5. Preview",
    "6. Import",
)
_SAMPLE_ROWS = 8
_PREVIEW_ROWS = 50
_NONE = "(not mapped)"
_DATE_ORDERS = {
    DateOrder.ISO_ONLY: "ISO only (YYYY-MM-DD…)",
    DateOrder.DAY_FIRST: "Day first (DD/MM/YYYY…)",
    DateOrder.MONTH_FIRST: "Month first (MM/DD/YYYY…)",
}
_FILTER = (
    "Survey files ("
    + " ".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS)
    + ");;All files (*)"
)


class SurveyImportPage(BasePage):
    """Guided import of CSV, Excel, JSON, GeoJSON and PDF survey files."""

    def __init__(
        self, spec: PageSpec, surveys: SurveyService, parent: QWidget | None = None
    ) -> None:
        super().__init__(spec, parent)
        self._surveys = surveys
        self._importer: SurveyImporter = surveys.importer
        self._source: SourceFile | None = None
        self._prepared: PreparedImport | None = None
        self._mapping_boxes: dict[str, QComboBox] = {}

        self._step_label = QLabel()
        self._step_label.setObjectName("sectionTitle")
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_select())
        self._stack.addWidget(self._build_inspect())
        self._stack.addWidget(self._build_mapping())
        self._stack.addWidget(self._build_validate())
        self._stack.addWidget(self._build_preview())
        self._stack.addWidget(self._build_confirm())

        self._back = QPushButton("Back")
        self._back.clicked.connect(self._go_back)
        self._next = QPushButton("Next")
        self._next.clicked.connect(self._go_next)
        self._reset = QPushButton("Start over")
        self._reset.clicked.connect(self.reset)
        buttons = QHBoxLayout()
        buttons.addWidget(self._reset)
        buttons.addStretch(1)
        buttons.addWidget(self._back)
        buttons.addWidget(self._next)

        self.body.addWidget(self._step_label)
        self.body.addWidget(self._stack, 1)
        self.body.addLayout(buttons)
        self.reset()

    def reset(self) -> None:
        """Return the wizard to the first step with no file selected."""
        self._source = None
        self._prepared = None
        self._path_edit.clear()
        self._stack.setCurrentIndex(0)
        self._refresh_chrome()

    # -- steps -----------------------------------------------------------------

    def _build_select(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(section_title("Select a survey file"))
        layout.addWidget(
            note(
                "Supported formats: CSV, XLSX, XLS, JSON, GeoJSON and PDF. "
                "PDF text extraction is unverified; scanned PDFs need OCR, which is not available yet."
            )
        )
        row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("No file selected")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(self._path_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)
        self._select_message = note("")
        layout.addWidget(self._select_message)
        layout.addStretch(1)
        return page

    def _build_inspect(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(section_title("File inspection"))
        self._inspect_form = QFormLayout()
        self._inspect_labels = {
            key: QLabel()
            for key in ("file", "format", "size", "tables", "records", "sha256")
        }
        for caption, key in (
            ("File", "file"),
            ("Format", "format"),
            ("Size", "size"),
            ("Tables", "tables"),
            ("Records in selected table", "records"),
            ("Content SHA-256", "sha256"),
        ):
            self._inspect_form.addRow(caption, self._inspect_labels[key])
        layout.addLayout(self._inspect_form)

        table_row = QHBoxLayout()
        table_row.addWidget(QLabel("Table to import:"))
        self._table_box = QComboBox()
        self._table_box.currentIndexChanged.connect(self._on_table_changed)
        table_row.addWidget(self._table_box, 1)
        layout.addLayout(table_row)

        layout.addWidget(section_title("Columns"))
        self._columns_table = make_table(("Column", "Non-empty cells", "Sample values"))
        layout.addWidget(self._columns_table, 1)
        layout.addWidget(section_title("Sample rows"))
        self._sample_table = make_table(())
        layout.addWidget(self._sample_table, 1)
        self._inspect_notes = note("")
        layout.addWidget(self._inspect_notes)
        return page

    def _build_mapping(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(section_title("Column mapping"))
        layout.addWidget(
            note(
                "Suggested mappings are based on column names. Correct them before continuing. "
                "Unmapped columns are preserved as original source values."
            )
        )
        suggest = QPushButton("Re-apply suggestions")
        suggest.clicked.connect(self._apply_suggestions)
        layout.addWidget(suggest, 0, Qt.AlignmentFlag.AlignLeft)

        form = QFormLayout()
        for field in MAPPABLE_FIELDS:
            box = QComboBox()
            self._mapping_boxes[field.name] = box
            form.addRow(field.label, box)
        layout.addLayout(form)

        options = QFormLayout()
        self._date_order = QComboBox()
        for order, label in _DATE_ORDERS.items():
            self._date_order.addItem(label, order)
        self._timezone = QComboBox()
        self._timezone.addItem("UTC", "UTC")
        for name in sorted(available_timezones()):
            if name != "UTC":
                self._timezone.addItem(name, name)
        self._instrument = QLineEdit()
        self._instrument.setPlaceholderText("Optional")
        self._software = QLineEdit()
        self._software.setPlaceholderText("Optional")
        options.addRow("Date order", self._date_order)
        options.addRow("Timestamp time zone", self._timezone)
        options.addRow("Source instrument", self._instrument)
        options.addRow("Source software", self._software)
        layout.addWidget(section_title("Reading options"))
        layout.addLayout(options)
        self._mapping_message = note("")
        layout.addWidget(self._mapping_message)
        layout.addStretch(1)

        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setFrameShape(QScrollArea.Shape.NoFrame)
        page.setWidget(content)
        return page

    def _build_validate(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(section_title("Validation"))
        self._validate_summary = note("")
        layout.addWidget(self._validate_summary)
        self._findings_table = make_table(
            ("Severity", "Check", "Field", "Rows", "Message", "Example")
        )
        layout.addWidget(self._findings_table, 1)
        return page

    def _build_preview(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(section_title("Import preview"))
        self._preview_summary = note("")
        layout.addWidget(self._preview_summary)
        self._preview_table = make_table(())
        layout.addWidget(self._preview_table, 1)
        return page

    def _build_confirm(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(section_title("Confirm import"))
        layout.addWidget(
            note(
                "The source file is archived unchanged. Existing surveys are never "
                "overwritten. Import is all-or-nothing: if storage fails, nothing is saved."
            )
        )
        form = QFormLayout()
        self._survey_name = QLineEdit()
        self._survey_notes = QTextEdit()
        self._survey_notes.setAcceptRichText(False)
        self._survey_notes.setMaximumHeight(100)
        form.addRow("Survey name", self._survey_name)
        form.addRow("Notes", self._survey_notes)
        layout.addLayout(form)
        self._confirm_summary = note("")
        layout.addWidget(self._confirm_summary)
        layout.addStretch(1)
        return page

    # -- navigation ------------------------------------------------------------

    def _refresh_chrome(self) -> None:
        step = self._stack.currentIndex()
        self._step_label.setText(_STEPS[step])
        self._back.setEnabled(step > 0)
        self._next.setText("Import" if step == 5 else "Next")
        self._next.setEnabled(step > 0 or bool(self._path_edit.text()))

    def _go_back(self) -> None:
        step = self._stack.currentIndex()
        if step > 0:
            self._stack.setCurrentIndex(step - 1)
            self._refresh_chrome()

    def _go_next(self) -> None:
        step = self._stack.currentIndex()
        try:
            if step == 0:
                self._load_selected_file()
            elif step == 2:
                self._run_prepare()
            elif step == 5:
                self._commit()
                return
        except SurveyImportError as exc:
            self._show_error(str(exc))
            return
        except ValueError as exc:
            self._mapping_message.setText(str(exc))
            return
        if step < 5:
            self._stack.setCurrentIndex(step + 1)
            self._refresh_chrome()

    def _show_error(self, message: str) -> None:
        if self._stack.currentIndex() == 0:
            self._select_message.setText(message)
        else:
            QMessageBox.warning(self, "Import", message)

    # -- step actions ----------------------------------------------------------

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select survey file", "", _FILTER)
        if path:
            self._path_edit.setText(path)
            self._select_message.setText("")
            self._refresh_chrome()

    def _load_selected_file(self) -> None:
        path = Path(self._path_edit.text())
        source = load_source(path)
        previous = self._importer.previous_import(source)
        if previous is not None:
            raise SurveyImportError(already_imported_message(source, previous))
        self._source = source
        self._prepared = None
        self._fill_inspect()

    def _fill_inspect(self) -> None:
        source = self._source
        assert source is not None
        labels = self._inspect_labels
        labels["file"].setText(source.path.name)
        labels["format"].setText(source.format.value.upper())
        labels["size"].setText(_format_size(source.size_bytes))
        labels["tables"].setText(", ".join(table.name for table in source.tables))
        labels["sha256"].setText(source.sha256)
        labels["sha256"].setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._table_box.blockSignals(True)
        self._table_box.clear()
        for table in source.tables:
            self._table_box.addItem(f"{table.name} ({len(table.rows)} rows)", table.name)
        self._table_box.blockSignals(False)
        self._on_table_changed()
        self._inspect_notes.setText("\n".join(source.notes))

    def _on_table_changed(self) -> None:
        source = self._source
        if source is None or self._table_box.count() == 0:
            return
        table = source.table(self._table_box.currentData())
        self._inspect_labels["records"].setText(str(len(table.rows)))
        fill_table(
            self._columns_table,
            [
                (
                    column,
                    sum(1 for value in table.column_values(column) if value is not None),
                    ", ".join(
                        value
                        for value in table.column_values(column)
                        if value is not None
                    )[:120]
                    or NO_VALUE,
                )
                for column in table.columns
            ],
        )
        self._sample_table.setColumnCount(len(table.columns))
        self._sample_table.setHorizontalHeaderLabels(list(table.columns))
        fill_table(self._sample_table, table.rows[:_SAMPLE_ROWS])
        self._prepare_mapping_controls(table.columns)
        if "timestamp" in suggest_mapping(table.columns):
            order = suggest_date_order(
                table.column_values(suggest_mapping(table.columns)["timestamp"])
            )
            self._date_order.setCurrentIndex(list(DateOrder).index(order))

    def _prepare_mapping_controls(self, columns: tuple[str, ...]) -> None:
        for box in self._mapping_boxes.values():
            box.blockSignals(True)
            box.clear()
            box.addItem(_NONE, None)
            for column in columns:
                box.addItem(column, column)
            box.blockSignals(False)
        self._apply_suggestions()

    def _apply_suggestions(self) -> None:
        source = self._source
        if source is None or self._table_box.count() == 0:
            return
        table = source.table(self._table_box.currentData())
        suggested = suggest_mapping(table.columns)
        for name, box in self._mapping_boxes.items():
            column = suggested.get(name)
            box.setCurrentIndex(box.findData(column) if column else 0)
        self._mapping_message.setText(
            f"Suggested {len(suggested)} of {len(MAPPABLE_FIELDS)} fields from column names."
        )

    def _current_mapping(self) -> dict[str, str]:
        mapping = {
            name: box.currentData()
            for name, box in self._mapping_boxes.items()
            if box.currentData()
        }
        source = self._source
        assert source is not None
        validate_mapping(mapping, source.table(self._table_box.currentData()).columns)
        return mapping

    def _run_prepare(self) -> None:
        source = self._source
        assert source is not None
        mapping = self._current_mapping()
        options = NormalizationOptions(
            date_order=self._date_order.currentData(),
            timezone=self._timezone.currentData(),
        )
        prepared = self._importer.prepare(
            source,
            self._table_box.currentData(),
            mapping,
            options,
            source_instrument=self._instrument.text().strip() or None,
            source_software=self._software.text().strip() or None,
        )
        self._prepared = prepared
        self._fill_validation(prepared)
        self._fill_preview(prepared)
        self._fill_confirm(prepared)

    def _fill_validation(self, prepared: PreparedImport) -> None:
        errors = prepared.count(Severity.ERROR)
        warnings = prepared.count(Severity.WARNING)
        self._validate_summary.setText(
            f"Rows read: {prepared.rows_read}. "
            f"Records ready to import: {len(prepared.records)}. "
            f"Errors: {errors}. Warnings: {warnings}. "
            "Invalid values are left null; they are never corrected."
        )
        fill_table(
            self._findings_table,
            [
                (
                    finding.severity.value,
                    CHECK_LABELS.get(finding.check, finding.check),
                    finding.field or NO_VALUE,
                    finding.row_count or NO_VALUE,
                    finding.message,
                    finding.example or NO_VALUE,
                )
                for finding in prepared.findings
            ],
        )

    def _fill_preview(self, prepared: PreparedImport) -> None:
        fields = [
            field.name
            for field in MAPPABLE_FIELDS
            if any(getattr(record, field.name) is not None for record in prepared.records)
        ] or ["timestamp"]
        headers = ["source_row", *fields]
        self._preview_table.setColumnCount(len(headers))
        self._preview_table.setHorizontalHeaderLabels(headers)
        rows = []
        for record in prepared.records[:_PREVIEW_ROWS]:
            values: list[object] = [record.source_row]
            for name in fields:
                value = getattr(record, name)
                if hasattr(value, "value"):
                    value = value.value
                elif hasattr(value, "isoformat"):
                    value = value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                values.append(NO_VALUE if value is None else value)
            rows.append(values)
        fill_table(self._preview_table, rows)
        more = max(0, len(prepared.records) - _PREVIEW_ROWS)
        self._preview_summary.setText(
            f"Showing {len(rows)} of {len(prepared.records)} normalized records"
            + (f" ({more} more not shown)." if more else ".")
        )

    def _fill_confirm(self, prepared: PreparedImport) -> None:
        if not self._survey_name.text().strip():
            self._survey_name.setText(prepared.source.path.stem)
        self._confirm_summary.setText(
            f"File: {prepared.source.path.name}\n"
            f"Table: {prepared.table.name}\n"
            f"Records to import: {len(prepared.records)}\n"
            f"Validation errors: {prepared.count(Severity.ERROR)}; "
            f"warnings: {prepared.count(Severity.WARNING)}"
        )

    def _commit(self) -> None:
        prepared = self._prepared
        assert prepared is not None
        survey_id = self._importer.commit(
            prepared, self._survey_name.text(), self._survey_notes.toPlainText()
        )
        self._surveys.notify_changed()
        QMessageBox.information(
            self,
            "Import complete",
            f"Stored survey “{self._survey_name.text().strip()}” "
            f"(id {survey_id}) with {len(prepared.records)} records.\n\n"
            "Open Survey Explorer to browse or export it.",
        )
        self.reset()


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
