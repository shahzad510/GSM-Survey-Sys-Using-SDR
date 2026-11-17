"""Storage and retrieval of surveys, imports and measurement records."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from cellsurvey import __version__
from cellsurvey.database.connection import Database
from cellsurvey.database.models import (
    ImportValidation,
    MeasurementRecord,
    Survey,
    SurveyImport,
    SurveySource,
)
from cellsurvey.schema import FIELD_NAMES, Measurement
from cellsurvey.survey_import.validation import Finding, Severity

logger = logging.getLogger(__name__)

_QUERY_CHUNK = 500  # stays below SQLite's limit on bound parameters

# Measurement fields that are columns of measurement_records.
_RECORD_FIELDS = tuple(name for name in FIELD_NAMES if name in MeasurementRecord.__table__.columns)
# Fields a survey's records are described by; identifiers and provenance excluded.
CONTENT_FIELDS = tuple(
    name
    for name in _RECORD_FIELDS
    if name not in ("record_id", "survey_id", "measurement_method", "source_row", "source_values")
)


@dataclass(frozen=True)
class NewImport:
    """Everything stored for one import. Saved completely or not at all."""

    survey_name: str
    survey_notes: str | None
    sha256: str
    filename: str
    original_path: str
    archived_path: str
    source_format: str
    size_bytes: int
    imported_at: datetime
    table_name: str
    column_mapping: dict[str, str]
    options: dict[str, str]
    measurement_method: str
    source_instrument: str | None
    source_software: str | None
    rows_read: int
    records: Sequence[Measurement]
    content_hashes: Sequence[str | None]
    """Fingerprints of ``records``, in the same order."""
    findings: Sequence[Finding]


@dataclass(frozen=True)
class PreviousImport:
    """An existing import of a file."""

    survey_id: int
    survey_name: str
    imported_at: datetime


@dataclass(frozen=True)
class SurveySummary:
    """A survey with figures derived from its records."""

    survey_id: int
    name: str
    notes: str | None
    created_at: datetime
    record_count: int
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    technologies: tuple[str, ...]
    countries: tuple[str, ...]
    operators: tuple[str, ...]
    mccs: tuple[str, ...]
    mncs: tuple[str, ...]
    instruments: tuple[str, ...]
    source_files: tuple[str, ...]


@dataclass(frozen=True)
class SurveyFilter:
    """Criteria for narrowing a list of surveys. Unset criteria match everything."""

    name: str = ""
    date_from: date | None = None
    date_to: date | None = None
    technology: str | None = None
    country: str | None = None
    operator: str | None = None
    mcc: str | None = None
    mnc: str | None = None
    instrument: str | None = None

    def matches(self, survey: SurveySummary) -> bool:
        """Whether ``survey`` satisfies every criterion.

        The dates select surveys with measurements on or between them (UTC). A
        survey without timestamps never matches a date criterion.
        """
        if self.name.strip().casefold() not in survey.name.casefold():
            return False
        if self.date_from is not None or self.date_to is not None:
            if survey.first_timestamp is None or survey.last_timestamp is None:
                return False
            if self.date_from is not None and survey.last_timestamp.date() < self.date_from:
                return False
            if self.date_to is not None and survey.first_timestamp.date() > self.date_to:
                return False
        return all(
            wanted is None or wanted in present
            for wanted, present in (
                (self.technology, survey.technologies),
                (self.country, survey.countries),
                (self.operator, survey.operators),
                (self.mcc, survey.mccs),
                (self.mnc, survey.mncs),
                (self.instrument, survey.instruments),
            )
        )


@dataclass(frozen=True)
class ImportDetails:
    """Metadata of one import, for display."""

    import_id: int
    imported_at: datetime
    filename: str
    original_path: str
    archived_path: str
    sha256: str
    source_format: str
    size_bytes: int
    table_name: str
    column_mapping: dict[str, str]
    options: dict[str, str]
    measurement_method: str
    source_instrument: str | None
    source_software: str | None
    rows_read: int
    records_imported: int
    software_version: str
    findings: tuple[Finding, ...]


class SurveyRepository:
    """Reads and writes surveys. Every method is one transaction."""

    def __init__(self, database: Database) -> None:
        self._database = database

    # -- imports ---------------------------------------------------------------

    def find_import_of_file(self, sha256: str) -> PreviousImport | None:
        """The most recent import of the file with this content, if it is still stored."""
        with self._database.session() as session:
            row = session.execute(
                select(Survey.id, Survey.name, SurveyImport.imported_at)
                .join(SurveyImport, SurveyImport.survey_id == Survey.id)
                .join(SurveySource, SurveySource.id == SurveyImport.source_id)
                .where(SurveySource.sha256 == sha256)
                .order_by(SurveyImport.imported_at.desc())
            ).first()
        return None if row is None else PreviousImport(*row)

    def existing_content_hashes(self, hashes: Collection[str]) -> set[str]:
        """The subset of ``hashes`` that already belongs to stored records."""
        wanted = list(hashes)
        found: set[str] = set()
        with self._database.session() as session:
            for start in range(0, len(wanted), _QUERY_CHUNK):
                chunk = wanted[start : start + _QUERY_CHUNK]
                found.update(
                    session.scalars(
                        select(MeasurementRecord.content_hash).where(
                            MeasurementRecord.content_hash.in_(chunk)
                        )
                    )
                )
        return found

    def save_import(self, new: NewImport) -> int:
        """Store a new survey with its import, findings and records; return the survey id.

        Existing rows are never changed. If anything fails, nothing is stored.

        Raises:
            sqlalchemy.exc.SQLAlchemyError: the database refused the data.
        """
        with self._database.session() as session:
            source = session.scalar(select(SurveySource).where(SurveySource.sha256 == new.sha256))
            if source is None:
                source = SurveySource(
                    sha256=new.sha256,
                    filename=new.filename,
                    original_path=new.original_path,
                    archived_path=new.archived_path,
                    format=new.source_format,
                    size_bytes=new.size_bytes,
                    first_imported_at=new.imported_at,
                )
                session.add(source)
            survey = Survey(name=new.survey_name, notes=new.survey_notes, created_at=new.imported_at)
            session.add(survey)
            session.flush()

            survey_import = SurveyImport(
                survey_id=survey.id,
                source_id=source.id,
                imported_at=new.imported_at,
                table_name=new.table_name,
                column_mapping=new.column_mapping,
                options=new.options,
                measurement_method=new.measurement_method,
                source_instrument=new.source_instrument,
                source_software=new.source_software,
                rows_read=new.rows_read,
                records_imported=len(new.records),
                software_version=__version__,
            )
            session.add(survey_import)
            session.flush()

            session.add_all(
                ImportValidation(
                    import_id=survey_import.id,
                    severity=finding.severity.value,
                    check_name=finding.check,
                    field=finding.field,
                    message=finding.message,
                    row_count=finding.row_count,
                    sample_rows=finding.sample_rows,
                    example=finding.example,
                )
                for finding in new.findings
            )
            if new.records:
                session.execute(
                    insert(MeasurementRecord),
                    [
                        _record_row(record, survey.id, survey_import.id, digest)
                        for record, digest in zip(new.records, new.content_hashes, strict=True)
                    ],
                )
            survey_id = survey.id
        logger.info(
            "Survey stored",
            extra={"survey_id": survey_id, "survey": new.survey_name, "records": len(new.records)},
        )
        return survey_id

    # -- surveys ---------------------------------------------------------------

    def list_surveys(self) -> list[SurveySummary]:
        """All surveys, newest first."""
        with self._database.session() as session:
            surveys = session.scalars(
                select(Survey).order_by(Survey.created_at.desc(), Survey.id.desc())
            ).all()
            figures = {
                survey_id: (count, first, last)
                for survey_id, count, first, last in session.execute(
                    select(
                        MeasurementRecord.survey_id,
                        func.count(),
                        func.min(MeasurementRecord.timestamp),
                        func.max(MeasurementRecord.timestamp),
                    ).group_by(MeasurementRecord.survey_id)
                )
            }
            technologies = _distinct_per_survey(session, MeasurementRecord.technology)
            countries = _distinct_per_survey(session, MeasurementRecord.country)
            operators = _distinct_per_survey(session, MeasurementRecord.operator)
            mccs = _distinct_per_survey(session, MeasurementRecord.mcc)
            mncs = _distinct_per_survey(session, MeasurementRecord.mnc)
            instruments: defaultdict[int, set[str]] = defaultdict(set)
            files: defaultdict[int, set[str]] = defaultdict(set)
            for survey_id, instrument, filename in session.execute(
                select(
                    SurveyImport.survey_id, SurveyImport.source_instrument, SurveySource.filename
                ).join(SurveySource, SurveySource.id == SurveyImport.source_id)
            ):
                files[survey_id].add(filename)
                if instrument:
                    instruments[survey_id].add(instrument)

            return [
                SurveySummary(
                    survey_id=survey.id,
                    name=survey.name,
                    notes=survey.notes,
                    created_at=survey.created_at,
                    record_count=figures.get(survey.id, (0, None, None))[0],
                    first_timestamp=figures.get(survey.id, (0, None, None))[1],
                    last_timestamp=figures.get(survey.id, (0, None, None))[2],
                    technologies=tuple(sorted(technologies[survey.id])),
                    countries=tuple(sorted(countries[survey.id])),
                    operators=tuple(sorted(operators[survey.id])),
                    mccs=tuple(sorted(mccs[survey.id])),
                    mncs=tuple(sorted(mncs[survey.id])),
                    instruments=tuple(sorted(instruments[survey.id])),
                    source_files=tuple(sorted(files[survey.id])),
                )
                for survey in surveys
            ]

    def import_details(self, survey_id: int) -> list[ImportDetails]:
        """The imports that make up a survey, oldest first, with their findings."""
        with self._database.session() as session:
            findings: defaultdict[int, list[Finding]] = defaultdict(list)
            for row in session.scalars(
                select(ImportValidation)
                .join(SurveyImport, SurveyImport.id == ImportValidation.import_id)
                .where(SurveyImport.survey_id == survey_id)
                .order_by(ImportValidation.id)
            ):
                findings[row.import_id].append(
                    Finding(
                        severity=Severity(row.severity),
                        check=row.check_name,
                        message=row.message,
                        field=row.field,
                        row_count=row.row_count,
                        sample_rows=list(row.sample_rows),
                        example=row.example,
                    )
                )
            return [
                ImportDetails(
                    import_id=survey_import.id,
                    imported_at=survey_import.imported_at,
                    filename=source.filename,
                    original_path=source.original_path,
                    archived_path=source.archived_path,
                    sha256=source.sha256,
                    source_format=source.format,
                    size_bytes=source.size_bytes,
                    table_name=survey_import.table_name,
                    column_mapping=dict(survey_import.column_mapping),
                    options=dict(survey_import.options),
                    measurement_method=survey_import.measurement_method,
                    source_instrument=survey_import.source_instrument,
                    source_software=survey_import.source_software,
                    rows_read=survey_import.rows_read,
                    records_imported=survey_import.records_imported,
                    software_version=survey_import.software_version,
                    findings=tuple(findings[survey_import.id]),
                )
                for survey_import, source in session.execute(
                    select(SurveyImport, SurveySource)
                    .join(SurveySource, SurveySource.id == SurveyImport.source_id)
                    .where(SurveyImport.survey_id == survey_id)
                    .order_by(SurveyImport.id)
                )
            ]

    def delete_survey(self, survey_id: int) -> bool:
        """Delete a survey with its imports, findings and records.

        Source-file references and the files themselves are kept.

        Returns:
            ``False`` if there was no such survey.
        """
        with self._database.session() as session:
            deleted = session.execute(delete(Survey).where(Survey.id == survey_id)).rowcount > 0
        if deleted:
            logger.info("Survey deleted", extra={"survey_id": survey_id})
        return deleted

    # -- records ---------------------------------------------------------------

    def record_count(self, survey_id: int) -> int:
        """Number of records in a survey."""
        with self._database.session() as session:
            return session.scalar(
                select(func.count())
                .select_from(MeasurementRecord)
                .where(MeasurementRecord.survey_id == survey_id)
            ) or 0

    def populated_fields(self, survey_id: int) -> list[str]:
        """Measurement fields that have a value in at least one record of the survey."""
        with self._database.session() as session:
            counts = session.execute(
                select(
                    *(func.count(getattr(MeasurementRecord, name)) for name in CONTENT_FIELDS)
                ).where(MeasurementRecord.survey_id == survey_id)
            ).one()
        return [name for name, count in zip(CONTENT_FIELDS, counts) if count]

    def records(
        self, survey_id: int, offset: int = 0, limit: int | None = None
    ) -> list[Measurement]:
        """Records of a survey in source order, with their provenance filled in."""
        with self._database.session() as session:
            provenance = {
                survey_import.id: {
                    "source_filename": source.filename,
                    "source_format": source.format,
                    "source_instrument": survey_import.source_instrument,
                    "source_software": survey_import.source_software,
                    "import_timestamp": survey_import.imported_at,
                }
                for survey_import, source in session.execute(
                    select(SurveyImport, SurveySource)
                    .join(SurveySource, SurveySource.id == SurveyImport.source_id)
                    .where(SurveyImport.survey_id == survey_id)
                )
            }
            columns = [getattr(MeasurementRecord, name) for name in _RECORD_FIELDS]
            query = (
                select(MeasurementRecord.import_id, *columns)
                .where(MeasurementRecord.survey_id == survey_id)
                .order_by(
                    MeasurementRecord.import_id,
                    MeasurementRecord.source_row,
                    MeasurementRecord.record_id,
                )
                .offset(offset)
            )
            if limit is not None:
                query = query.limit(limit)
            return [
                Measurement(**dict(zip(_RECORD_FIELDS, values)), **provenance.get(import_id, {}))
                for import_id, *values in session.execute(query)
            ]


def _distinct_per_survey(session: Session, column: object) -> defaultdict[int, set[str]]:
    values: defaultdict[int, set[str]] = defaultdict(set)
    for survey_id, value in session.execute(
        select(MeasurementRecord.survey_id, column)  # type: ignore[call-overload]
        .where(column.is_not(None))  # type: ignore[attr-defined]
        .distinct()
    ):
        values[survey_id].add(value)
    return values


def _record_row(
    record: Measurement, survey_id: int, import_id: int, content_hash: str | None
) -> dict[str, object]:
    row: dict[str, object] = {
        name: value.value if isinstance(value := getattr(record, name), Enum) else value
        for name in _RECORD_FIELDS
    }
    row.update(survey_id=survey_id, import_id=import_id, content_hash=content_hash)
    return row
