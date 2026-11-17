"""The import workflow: read a file, prepare its records, store them.

The three stages match the import wizard. Only the last one changes anything:

1. :func:`load_source` reads a file into tables of text.
2. :meth:`SurveyImporter.prepare` normalizes and validates one table against a
   column mapping and finds duplicates. The result can be inspected freely.
3. :meth:`SurveyImporter.commit` archives the source file and stores the
   prepared records in one database transaction.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from cellsurvey.database.repositories.survey_repository import (
    NewImport,
    PreviousImport,
    SurveyRepository,
)
from cellsurvey.schema import Measurement, MeasurementMethod, SourceFormat
from cellsurvey.survey_import.csv_importer import read_csv
from cellsurvey.survey_import.excel_importer import read_excel
from cellsurvey.survey_import.file_detector import detect_format
from cellsurvey.survey_import.geojson_importer import read_geojson
from cellsurvey.survey_import.json_importer import read_json
from cellsurvey.survey_import.pdf_importer import read_pdf
from cellsurvey.survey_import.source import (
    Extraction,
    SourceFile,
    SourceTable,
    SurveyImportError,
)
from cellsurvey.survey_import.validation import Finding, FindingCollector, Severity
from cellsurvey.survey_processing.duplicate_detection import split_duplicates
from cellsurvey.survey_processing.normalizer import (
    NormalizationOptions,
    Provenance,
    normalize_table,
)

logger = logging.getLogger(__name__)

_READERS: dict[SourceFormat, Callable[[Path], Extraction]] = {
    SourceFormat.CSV: read_csv,
    SourceFormat.XLSX: lambda path: read_excel(path, SourceFormat.XLSX),
    SourceFormat.XLS: lambda path: read_excel(path, SourceFormat.XLS),
    SourceFormat.JSON: read_json,
    SourceFormat.GEOJSON: read_geojson,
    SourceFormat.PDF: read_pdf,
}


def load_source(path: Path) -> SourceFile:
    """Read a survey file. Nothing is interpreted and nothing is stored.

    Raises:
        SurveyImportError: the file is missing, unreadable, unsupported or empty.
    """
    if not path.is_file():
        raise SurveyImportError(f"{path} is not a file.")
    source_format = detect_format(path)
    try:
        extraction = _READERS[source_format](path)
        digest = _sha256(path)
        size = path.stat().st_size
    except OSError as exc:
        raise SurveyImportError(f"Cannot read {path.name}: {exc.strerror or exc}") from exc

    logger.info(
        "Survey file read",
        extra={
            "file": str(path),
            "format": source_format.value,
            "tables": {table.name: len(table.rows) for table in extraction.tables},
        },
    )
    return SourceFile(
        path=path,
        format=source_format,
        size_bytes=size,
        sha256=digest,
        tables=extraction.tables,
        notes=extraction.notes,
        measurement_method=(
            MeasurementMethod.PDF_TEXT_EXTRACTION
            if source_format is SourceFormat.PDF
            else MeasurementMethod.STRUCTURED_FILE
        ),
    )


@dataclass(frozen=True)
class PreparedImport:
    """The outcome of normalizing and validating one table. Nothing is stored yet."""

    source: SourceFile
    table: SourceTable
    mapping: dict[str, str]
    options: NormalizationOptions
    provenance: Provenance
    records: tuple[Measurement, ...]
    """The records that would be stored."""
    content_hashes: tuple[str | None, ...]
    findings: tuple[Finding, ...]

    @property
    def rows_read(self) -> int:
        """Number of data rows in the source table."""
        return len(self.table.rows)

    def count(self, severity: Severity) -> int:
        """Number of findings of the given severity."""
        return sum(finding.severity is severity for finding in self.findings)


class SurveyImporter:
    """Prepares survey files for import and stores them."""

    def __init__(self, repository: SurveyRepository, archive_dir: Path) -> None:
        """
        Args:
            repository: where surveys are stored.
            archive_dir: directory that receives an unmodified copy of every
                imported file.
        """
        self._repository = repository
        self._archive_dir = archive_dir

    def previous_import(self, source: SourceFile) -> PreviousImport | None:
        """The stored import of a file with exactly this content, if there is one."""
        return self._repository.find_import_of_file(source.sha256)

    def prepare(
        self,
        source: SourceFile,
        table_name: str,
        mapping: Mapping[str, str],
        options: NormalizationOptions,
        source_instrument: str | None = None,
        source_software: str | None = None,
    ) -> PreparedImport:
        """Normalize and validate one table of ``source``.

        Raises:
            SurveyImportError: the mapping or the options cannot be applied.
        """
        table = source.table(table_name)
        provenance = Provenance(
            source_filename=source.path.name,
            source_format=source.format,
            measurement_method=source.measurement_method,
            import_timestamp=datetime.now(timezone.utc),
            source_instrument=source_instrument or None,
            source_software=source_software or None,
        )
        collector = FindingCollector()
        try:
            normalized = normalize_table(table, mapping, options, provenance, collector)
        except ValueError as exc:
            raise SurveyImportError(str(exc)) from exc

        unmapped = [column for column in table.columns if column not in mapping.values()]
        if unmapped:
            collector.add(
                Severity.INFO,
                "unmapped_columns",
                f"Not mapped to a field: {', '.join(unmapped)}. The values are kept with each "
                "record as original source values but are not available for analysis.",
            )

        records, hashes, duplicates = split_duplicates(normalized)
        for duplicate in duplicates:
            collector.add(
                Severity.WARNING,
                "duplicate_in_file",
                "Same timestamp and values as an earlier row of this file; the row was skipped",
                row=duplicate.source_row,
            )
        stored = self._repository.existing_content_hashes(
            [digest for digest in hashes if digest is not None]
        )
        for record, digest in zip(records, hashes):
            if digest in stored:
                collector.add(
                    Severity.WARNING,
                    "duplicate_in_database",
                    "Same timestamp and values as a record already in the database; "
                    "the row was skipped",
                    row=record.source_row,
                )
        new = [(record, digest) for record, digest in zip(records, hashes) if digest not in stored]

        return PreparedImport(
            source=source,
            table=table,
            mapping=dict(mapping),
            options=options,
            provenance=provenance,
            records=tuple(record for record, _ in new),
            content_hashes=tuple(digest for _, digest in new),
            findings=tuple(collector.findings()),
        )

    def commit(self, prepared: PreparedImport, survey_name: str, notes: str | None = None) -> int:
        """Store a prepared import as a new survey and return the survey's id.

        The source file is first copied, unmodified, into the archive directory.
        The database is then written in one transaction; if that fails, nothing
        is stored and the copy is removed again.

        Raises:
            SurveyImportError: the import cannot be stored. Nothing was changed.
        """
        source = prepared.source
        name = survey_name.strip()
        if not name:
            raise SurveyImportError("Enter a name for the survey.")
        if not prepared.records:
            raise SurveyImportError("There are no records to import.")
        previous = self.previous_import(source)
        if previous is not None:
            raise SurveyImportError(already_imported_message(source, previous))

        archived, created = self._archive(source)
        try:
            survey_id = self._repository.save_import(
                NewImport(
                    survey_name=name,
                    survey_notes=(notes or "").strip() or None,
                    sha256=source.sha256,
                    filename=source.path.name,
                    original_path=str(source.path.resolve()),
                    archived_path=str(archived),
                    source_format=source.format.value,
                    size_bytes=source.size_bytes,
                    imported_at=prepared.provenance.import_timestamp,
                    table_name=prepared.table.name,
                    column_mapping=prepared.mapping,
                    options={
                        key: getattr(value, "value", value)
                        for key, value in asdict(prepared.options).items()
                    },
                    measurement_method=source.measurement_method.value,
                    source_instrument=prepared.provenance.source_instrument,
                    source_software=prepared.provenance.source_software,
                    rows_read=prepared.rows_read,
                    records=prepared.records,
                    content_hashes=prepared.content_hashes,
                    findings=prepared.findings,
                )
            )
        except Exception as exc:
            if created:
                shutil.rmtree(archived.parent, ignore_errors=True)
            logger.error("Import failed and was rolled back", exc_info=exc)
            raise SurveyImportError(
                f"The import failed and nothing was saved: {exc.__class__.__name__}: {exc}"
            ) from exc

        logger.info(
            "Survey imported",
            extra={
                "survey_id": survey_id,
                "file": str(source.path),
                "sha256": source.sha256,
                "records": len(prepared.records),
                "rows_read": prepared.rows_read,
            },
        )
        return survey_id

    def _archive(self, source: SourceFile) -> tuple[Path, bool]:
        """Copy the source file into the archive; return the copy and whether it is new."""
        target = self._archive_dir / source.sha256 / source.path.name
        if target.is_file():
            return target, False
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source.path, target)
            unchanged = _sha256(target) == source.sha256
        except OSError as exc:
            shutil.rmtree(target.parent, ignore_errors=True)
            raise SurveyImportError(
                f"Cannot archive {source.path.name}: {exc.strerror or exc}"
            ) from exc
        if not unchanged:
            shutil.rmtree(target.parent, ignore_errors=True)
            raise SurveyImportError(
                f"{source.path.name} has changed since it was inspected. Select the file again."
            )
        return target, True


def already_imported_message(source: SourceFile, previous: PreviousImport) -> str:
    """Explanation shown when a file's content is already in the database."""
    return (
        f"{source.path.name} was already imported on "
        f"{previous.imported_at:%Y-%m-%d %H:%M} UTC as survey “{previous.survey_name}”. "
        "To import it again, delete that survey first."
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
