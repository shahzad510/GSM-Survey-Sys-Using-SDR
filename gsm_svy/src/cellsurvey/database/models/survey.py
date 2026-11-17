"""Tables for surveys, their source files, imports and measurement records.

Deleting a survey removes its imports, validation findings and records
(``ON DELETE CASCADE``). ``survey_sources`` rows are never removed, so the
reference to every file that was ever imported is kept.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cellsurvey.database.models.base import Base, UtcDateTime


class Survey(Base):
    """A named set of measurement records."""

    __tablename__ = "surveys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class SurveySource(Base):
    """A source file, identified by the SHA-256 of its content."""

    __tablename__ = "survey_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    filename: Mapped[str] = mapped_column(Text)
    original_path: Mapped[str] = mapped_column(Text)
    """Where the file was when it was first imported."""
    archived_path: Mapped[str] = mapped_column(Text)
    """The unmodified copy kept in the application's data directory."""
    format: Mapped[str] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(Integer)
    first_imported_at: Mapped[datetime] = mapped_column(UtcDateTime)


class SurveyImport(Base):
    """One import of a source file into a survey, with the choices made for it."""

    __tablename__ = "survey_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    survey_id: Mapped[int] = mapped_column(
        ForeignKey("surveys.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("survey_sources.id"), index=True)
    imported_at: Mapped[datetime] = mapped_column(UtcDateTime)
    table_name: Mapped[str] = mapped_column(Text)
    """Worksheet, PDF table or record list that was imported."""
    column_mapping: Mapped[dict[str, Any]] = mapped_column(JSON)
    """``{field name: source column}`` as confirmed by the user."""
    options: Mapped[dict[str, Any]] = mapped_column(JSON)
    """Processing parameters, e.g. date order and time zone."""
    measurement_method: Mapped[str] = mapped_column(String(32))
    source_instrument: Mapped[str | None] = mapped_column(Text)
    source_software: Mapped[str | None] = mapped_column(Text)
    rows_read: Mapped[int] = mapped_column(Integer)
    records_imported: Mapped[int] = mapped_column(Integer)
    software_version: Mapped[str] = mapped_column(String(32))
    """Version of this application that performed the import."""


class ImportValidation(Base):
    """A validation finding of an import."""

    __tablename__ = "import_validations"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[int] = mapped_column(
        ForeignKey("survey_imports.id", ondelete="CASCADE"), index=True
    )
    severity: Mapped[str] = mapped_column(String(16))
    check_name: Mapped[str] = mapped_column(String(64))
    field: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    row_count: Mapped[int] = mapped_column(Integer)
    sample_rows: Mapped[list[Any]] = mapped_column(JSON)
    example: Mapped[str | None] = mapped_column(Text)


class MeasurementRecord(Base):
    """A normalized cellular measurement. Columns mirror ``cellsurvey.schema.Measurement``.

    Provenance that is the same for every record of an import (file name,
    format, instrument, import time) is stored once, on the import.
    """

    __tablename__ = "measurement_records"
    __table_args__ = (
        Index("ix_measurement_records_survey_timestamp", "survey_id", "timestamp"),
        Index("ix_measurement_records_survey_technology", "survey_id", "technology"),
        Index("ix_measurement_records_survey_country", "survey_id", "country"),
        Index("ix_measurement_records_survey_operator", "survey_id", "operator"),
        Index("ix_measurement_records_survey_mcc", "survey_id", "mcc"),
        Index("ix_measurement_records_survey_mnc", "survey_id", "mnc"),
        Index("ix_measurement_records_import_row", "import_id", "source_row"),
    )

    record_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id", ondelete="CASCADE"))
    import_id: Mapped[int | None] = mapped_column(
        ForeignKey("survey_imports.id", ondelete="CASCADE")
    )
    """Null for records that were not imported from a file."""
    content_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    """Fingerprint used to refuse duplicates; null for records without a timestamp."""
    measurement_method: Mapped[str | None] = mapped_column(String(32))
    validation_status: Mapped[str | None] = mapped_column(String(32))
    source_row: Mapped[int | None] = mapped_column(Integer)
    source_values: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    timestamp: Mapped[datetime | None] = mapped_column(UtcDateTime)
    technology: Mapped[str | None] = mapped_column(String(8))
    country: Mapped[str | None] = mapped_column(Text)
    operator: Mapped[str | None] = mapped_column(Text)
    mcc: Mapped[str | None] = mapped_column(String(3))
    mnc: Mapped[str | None] = mapped_column(String(3))
    plmn: Mapped[str | None] = mapped_column(String(8))
    band: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    cell_id: Mapped[int | None] = mapped_column(Integer)
    lac: Mapped[int | None] = mapped_column(Integer)
    tac: Mapped[int | None] = mapped_column(Integer)
    arfcn: Mapped[int | None] = mapped_column(Integer)
    uarfcn: Mapped[int | None] = mapped_column(Integer)
    earfcn: Mapped[int | None] = mapped_column(Integer)
    bsic: Mapped[int | None] = mapped_column(Integer)
    psc: Mapped[int | None] = mapped_column(Integer)
    pci: Mapped[int | None] = mapped_column(Integer)
    frequency_mhz: Mapped[float | None] = mapped_column(Float)

    rssi_dbm: Mapped[float | None] = mapped_column(Float)
    rsrp_dbm: Mapped[float | None] = mapped_column(Float)
    rsrq_db: Mapped[float | None] = mapped_column(Float)
    sinr_db: Mapped[float | None] = mapped_column(Float)
    rscp_dbm: Mapped[float | None] = mapped_column(Float)
    ecno_db: Mapped[float | None] = mapped_column(Float)

    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    altitude_m: Mapped[float | None] = mapped_column(Float)
    position_accuracy_m: Mapped[float | None] = mapped_column(Float)
    coordinate_reference_system: Mapped[str | None] = mapped_column(String(32))
