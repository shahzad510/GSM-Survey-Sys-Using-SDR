"""Turn the text rows of a source table into normalized :class:`Measurement` records.

Conversion is strict. Text that is not clearly a value of the mapped field is
reported and the field is left null; it is never coerced, rounded or guessed.
Personal-identifier columns are redacted in ``source_values``.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from cellsurvey.schema import (
    Measurement,
    MeasurementMethod,
    SourceFormat,
    Technology,
    ValidationStatus,
)
from cellsurvey.survey_import.column_mapper import (
    FIELDS_BY_NAME,
    MappableField,
    validate_mapping,
)
from cellsurvey.survey_import.privacy import redact_source_values
from cellsurvey.survey_import.source import SourceTable
from cellsurvey.survey_import.validation import FindingCollector, Severity, build_measurement


class DateOrder(str, Enum):
    """How to read dates written with day and month as numbers, like 03/04/2024.

    Dates that start with the year (ISO 8601) are unambiguous and always accepted.
    """

    ISO_ONLY = "iso_only"
    """Accept only dates that start with the year."""
    DAY_FIRST = "day_first"
    MONTH_FIRST = "month_first"


@dataclass(frozen=True)
class NormalizationOptions:
    """Choices the user makes about how to read a source table."""

    date_order: DateOrder = DateOrder.ISO_ONLY
    timezone: str = "UTC"
    """IANA time zone of timestamps that carry no UTC offset."""


@dataclass(frozen=True)
class Provenance:
    """Where the records of one import come from."""

    source_filename: str
    source_format: SourceFormat
    measurement_method: MeasurementMethod
    import_timestamp: datetime
    source_instrument: str | None = None
    source_software: str | None = None


@dataclass(frozen=True)
class NormalizationResult:
    """Accepted records plus counts by validation status."""

    records: list[Measurement]
    """Records that can be imported (``valid`` and ``valid_with_warnings``)."""
    valid: int
    valid_with_warnings: int
    invalid: int
    """Rows with no usable mapped value after validation."""


class _ConversionError(ValueError):
    def __init__(self, check: str, message: str) -> None:
        super().__init__(message)
        self.check = check
        self.message = message


_INTEGER = re.compile(r"[+-]?[0-9]+(\.0*)?")
_NUMBER = re.compile(r"[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?")
_NUMERIC_DATE = re.compile(
    r"(?P<first>[0-9]{1,2})[/.-](?P<second>[0-9]{1,2})[/.-](?P<year>[0-9]{4})"
    r"(?:[ T]+(?P<hour>[0-9]{1,2}):(?P<minute>[0-9]{2})"
    r"(?::(?P<second_of_minute>[0-9]{2})(?:\.(?P<fraction>[0-9]{1,6}))?)?"
    r"(?:\s*(?P<meridiem>[AaPp][Mm]))?)?"
)

_TECHNOLOGIES = {
    Technology.GSM: ("gsm", "2g", "gprs", "edge"),
    Technology.UMTS: ("umts", "wcdma", "3g", "hspa", "hspa+", "hspap", "hsdpa", "hsupa", "dchspap"),
    Technology.LTE: ("lte", "4g", "ltea", "lte+", "lteca", "eutran"),
}
_TECHNOLOGY_BY_NAME = {name: tech for tech, names in _TECHNOLOGIES.items() for name in names}
_TECHNOLOGY_WITH_BAND = re.compile(r"(gsm|umts|wcdma|lte)[0-9]+")


def parse_timestamp(text: str, date_order: DateOrder, zone: ZoneInfo) -> datetime:
    """Parse a timestamp and return it in UTC.

    Raises:
        ValueError: the text is not a timestamp in an accepted format.
    """
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        match = _NUMERIC_DATE.fullmatch(text) if date_order is not DateOrder.ISO_ONLY else None
        if match is None:
            raise
        moment = _from_numeric_date(match, date_order)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return moment.astimezone(timezone.utc)


def suggest_date_order(values: Iterable[str | None]) -> DateOrder:
    """Work out the date order from the values, where they settle it."""
    day_first = month_first = False
    for value in values:
        match = _NUMERIC_DATE.fullmatch(value) if value else None
        if match:
            day_first |= int(match["first"]) > 12
            month_first |= int(match["second"]) > 12
    if day_first == month_first:
        return DateOrder.ISO_ONLY
    return DateOrder.DAY_FIRST if day_first else DateOrder.MONTH_FIRST


def normalize_table(
    table: SourceTable,
    mapping: Mapping[str, str],
    options: NormalizationOptions,
    provenance: Provenance,
    collector: FindingCollector,
) -> NormalizationResult:
    """Convert every row of ``table`` to a :class:`Measurement`.

    Rows with no usable mapped value are counted as invalid and left out of
    ``records``. All problems are reported to ``collector``.

    Raises:
        ValueError: the mapping does not fit the table, or the time zone is unknown.
    """
    validate_mapping(mapping, table.columns)
    try:
        zone = ZoneInfo(options.timezone)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Unknown time zone: {options.timezone}") from exc

    columns = [
        (FIELDS_BY_NAME[name], table.columns.index(column)) for name, column in mapping.items()
    ]
    shared = {
        "source_filename": provenance.source_filename,
        "source_format": provenance.source_format,
        "source_instrument": provenance.source_instrument,
        "source_software": provenance.source_software,
        "import_timestamp": provenance.import_timestamp,
        "measurement_method": provenance.measurement_method,
    }

    records: list[Measurement] = []
    valid = valid_with_warnings = invalid = 0
    for number, row in zip(table.row_numbers, table.rows):
        values: dict[str, object] = {}
        row_errors = 0
        row_warnings = 0
        for field, index in columns:
            raw = row[index]
            if raw is None:
                collector.add(
                    Severity.INFO,
                    "missing_value",
                    "No value in the source; stored as null",
                    field=field.name,
                    row=number,
                )
                continue
            try:
                values[field.name] = _convert(field, raw, options.date_order, zone)
            except _ConversionError as exc:
                row_errors += 1
                collector.add(
                    Severity.ERROR, exc.check, exc.message, field=field.name, row=number, example=raw
                )

        errors_before = _row_findings(collector, number, Severity.ERROR)
        warnings_before = _row_findings(collector, number, Severity.WARNING)
        record = build_measurement(
            {
                **values,
                **shared,
                "record_id": str(uuid.uuid4()),
                "source_row": number,
                "source_values": redact_source_values(table.columns, row),
            },
            number,
            collector,
        )
        row_errors += _row_findings(collector, number, Severity.ERROR) - errors_before
        row_warnings += _row_findings(collector, number, Severity.WARNING) - warnings_before

        if all(getattr(record, field.name) is None for field, _ in columns):
            invalid += 1
            collector.add(
                Severity.WARNING,
                "empty_row",
                "No usable value in any mapped column; the row was skipped",
                row=number,
            )
            continue

        if row_errors or row_warnings:
            status = ValidationStatus.VALID_WITH_WARNINGS
            valid_with_warnings += 1
        else:
            status = ValidationStatus.VALID
            valid += 1
        records.append(record.model_copy(update={"validation_status": status}))

    return NormalizationResult(records, valid, valid_with_warnings, invalid)


def _row_findings(collector: FindingCollector, row: int, severity: Severity) -> int:
    return sum(
        1
        for finding in collector.findings()
        if finding.severity is severity and row in finding.sample_rows
    )


def _convert(field: MappableField, text: str, date_order: DateOrder, zone: ZoneInfo) -> object:
    if field.kind == "text":
        return text
    if field.kind == "timestamp":
        try:
            return parse_timestamp(text, date_order, zone)
        except ValueError:
            raise _ConversionError(
                "invalid_timestamp", "Not a date and time in the selected format"
            ) from None
    if field.kind == "technology":
        key = re.sub(r"[\s_/-]", "", text.lower())
        technology = _TECHNOLOGY_BY_NAME.get(key)
        if technology is None and (match := _TECHNOLOGY_WITH_BAND.fullmatch(key)):
            technology = _TECHNOLOGY_BY_NAME[match[1]]
        if technology is None:
            raise _ConversionError("invalid_technology", "Not a recognised GSM, UMTS or LTE name")
        return technology

    number = text.replace("\u2212", "-")
    if field.kind == "integer":
        if not _INTEGER.fullmatch(number):
            raise _ConversionError("invalid_number", "Not a whole number")
        return int(float(number)) if "." in number else int(number)
    if not _NUMBER.fullmatch(number):
        raise _ConversionError("invalid_number", "Not a number")
    return float(number)


def _from_numeric_date(match: re.Match[str], date_order: DateOrder) -> datetime:
    first, second = int(match["first"]), int(match["second"])
    day, month = (first, second) if date_order is DateOrder.DAY_FIRST else (second, first)
    hour = int(match["hour"] or 0)
    meridiem = (match["meridiem"] or "").lower()
    if meridiem:
        if not 1 <= hour <= 12:
            raise ValueError("hour out of range for a 12-hour clock")
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    return datetime(
        int(match["year"]),
        month,
        day,
        hour,
        int(match["minute"] or 0),
        int(match["second_of_minute"] or 0),
        int((match["fraction"] or "0").ljust(6, "0")),
    )
