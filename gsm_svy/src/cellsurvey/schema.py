"""Common measurement schema.

One :class:`Measurement` describes one cellular measurement, whatever produced
it: an imported survey file today, a phone or another receiver later. Every
field except ``record_id`` is optional, and a value that the source did not
provide is ``None``; nothing is filled in.

Field names carry their unit where there is one (``rssi_dbm``, ``altitude_m``).
The unit and the valid range of each field are declared here once and are used
by validation, the user interface and exports.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

WGS84 = "EPSG:4326"
"""Coordinate reference system of ``latitude`` and ``longitude``."""


class Technology(str, Enum):
    """Radio access technology of a measurement."""

    GSM = "GSM"
    UMTS = "UMTS"
    LTE = "LTE"


class SourceFormat(str, Enum):
    """File format a measurement was imported from."""

    CSV = "csv"
    XLSX = "xlsx"
    XLS = "xls"
    JSON = "json"
    GEOJSON = "geojson"
    PDF = "pdf"


class MeasurementMethod(str, Enum):
    """How a measurement value reached this application."""

    STRUCTURED_FILE = "structured_file"
    """Read from a structured data file (CSV, Excel, JSON, GeoJSON)."""
    PDF_TEXT_EXTRACTION = "pdf_text_extraction"
    """Extracted from the text of a PDF document.

    Extraction can misread a table, so these values are not verified against
    the instrument that produced the document.
    """


class ValidationStatus(str, Enum):
    """Quality of one normalized record after import validation."""

    VALID = "valid"
    """Every mapped value converted cleanly."""
    VALID_WITH_WARNINGS = "valid_with_warnings"
    """Imported, but some values were dropped or look suspicious."""
    INVALID = "invalid"
    """Not imported: no usable mapped value remained after validation."""


def _field(description: str, unit: str | None = None, **constraints: Any) -> Any:
    return Field(
        default=None, description=description, json_schema_extra={"unit": unit}, **constraints
    )


class Measurement(BaseModel):
    """One cellular measurement with its position and provenance."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    # Identification
    record_id: str = Field(description="Unique identifier of the record (UUID).")
    survey_id: int | None = _field("Survey the record belongs to; null until it is stored.")
    timestamp: AwareDatetime | None = _field("Time of the measurement.", "UTC")
    technology: Technology | None = _field("Radio access technology.")
    country: str | None = _field("Country, as stated by the source.")
    operator: str | None = _field("Operator name, as stated by the source.")
    mcc: str | None = _field("Mobile country code: three digits.", pattern=r"^[0-9]{3}$")
    mnc: str | None = _field(
        "Mobile network code: two or three digits, leading zeros kept.",
        pattern=r"^[0-9]{2,3}$",
    )
    plmn: str | None = _field("Public land mobile network identity as MCC-MNC.")
    band: str | None = _field("Radio band label as stated by the source.")
    notes: str | None = _field("Free-text notes from the source row.")

    # Cell information — ARFCN, UARFCN and EARFCN stay separate; never convert between them.
    cell_id: int | None = _field("Cell identity (GSM CI, UMTS UC-ID or LTE ECI).", ge=0, le=2**28 - 1)
    lac: int | None = _field("Location area code (GSM, UMTS).", ge=0, le=65535)
    tac: int | None = _field("Tracking area code (LTE).", ge=0, le=65535)
    arfcn: int | None = _field("GSM absolute radio-frequency channel number.", ge=0, le=1023)
    uarfcn: int | None = _field("UMTS absolute radio-frequency channel number.", ge=0, le=16383)
    earfcn: int | None = _field("LTE absolute radio-frequency channel number.", ge=0, le=262143)
    bsic: int | None = _field("GSM base station identity code, as a decimal number.", ge=0, le=63)
    psc: int | None = _field("UMTS primary scrambling code.", ge=0, le=511)
    pci: int | None = _field("LTE physical cell identity.", ge=0, le=503)
    frequency_mhz: float | None = _field("Carrier frequency.", "MHz", ge=1, le=100_000)

    # Measurements
    rssi_dbm: float | None = _field("Received signal strength indicator.", "dBm", ge=-150, le=0)
    rsrp_dbm: float | None = _field("LTE reference signal received power.", "dBm", ge=-160, le=-20)
    rsrq_db: float | None = _field("LTE reference signal received quality.", "dB", ge=-40, le=10)
    sinr_db: float | None = _field("Signal to interference and noise ratio.", "dB", ge=-30, le=60)
    rscp_dbm: float | None = _field("UMTS received signal code power.", "dBm", ge=-130, le=-10)
    ecno_db: float | None = _field("UMTS energy per chip over noise density.", "dB", ge=-40, le=0)

    # Geographic information
    latitude: float | None = _field("Latitude, north positive.", "degrees", ge=-90, le=90)
    longitude: float | None = _field("Longitude, east positive.", "degrees", ge=-180, le=180)
    altitude_m: float | None = _field("Altitude.", "m", ge=-1000, le=100_000)
    position_accuracy_m: float | None = _field(
        "Horizontal position accuracy, if the source supplies it.", "m", ge=0, le=100_000
    )
    coordinate_reference_system: str | None = _field(
        "Reference system of latitude and longitude; null when there is no position."
    )

    # Provenance and quality
    source_filename: str | None = _field("Name of the file the record was imported from.")
    source_format: SourceFormat | None = _field("Format of the source file.")
    source_instrument: str | None = _field("Survey instrument, as stated at import.")
    source_software: str | None = _field("Survey software, as stated at import.")
    import_timestamp: AwareDatetime | None = _field("Time the record was imported.", "UTC")
    measurement_method: MeasurementMethod | None = _field("How the values were obtained.")
    validation_status: ValidationStatus | None = _field(
        "Outcome of import validation for this record."
    )
    source_row: int | None = _field("Row or record number in the source file.")
    source_values: dict[str, str | None] | None = _field(
        "The original row as text. Personal-identifier columns are redacted."
    )


FIELD_NAMES: tuple[str, ...] = tuple(Measurement.model_fields)


def field_unit(name: str) -> str | None:
    """Unit of a measurement field, or ``None`` if it has none."""
    extra = Measurement.model_fields[name].json_schema_extra
    return extra.get("unit") if isinstance(extra, dict) else None  # type: ignore[return-value]


def field_description(name: str) -> str:
    """Documentation of a measurement field."""
    return Measurement.model_fields[name].description or ""


def field_range(name: str) -> tuple[float, float] | None:
    """Inclusive valid range of a numeric field, or ``None`` if it is unbounded."""
    lower = upper = None
    for constraint in Measurement.model_fields[name].metadata:
        lower = getattr(constraint, "ge", lower)
        upper = getattr(constraint, "le", upper)
    return None if lower is None or upper is None else (lower, upper)
