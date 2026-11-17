"""Validation of imported values and the findings it produces.

A value that fails validation is never corrected or replaced. It is left out of
the normalized record (the field becomes null), the original text stays with
the record as a source value, and a finding says what happened.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum

from pydantic import ValidationError

from cellsurvey.schema import WGS84, Measurement, field_range, field_unit

_SAMPLE_ROWS = 10


class Severity(str, Enum):
    """How serious a finding is."""

    ERROR = "error"
    """A value was unusable and was not imported."""
    WARNING = "warning"
    """Something was skipped or looks suspicious."""
    INFO = "info"
    """Worth knowing; nothing was rejected."""


CHECK_LABELS = {
    "invalid_timestamp": "Date format",
    "invalid_number": "Numeric value",
    "invalid_technology": "Technology",
    "invalid_format": "Value format",
    "out_of_range": "Value range",
    "incomplete_coordinates": "Coordinates",
    "zero_coordinates": "Coordinates",
    "missing_value": "Missing values",
    "empty_row": "Empty rows",
    "duplicate_in_file": "Duplicate records",
    "duplicate_in_database": "Duplicate records",
    "unmapped_columns": "Unmapped columns",
    "ambiguous_columns": "Ambiguous columns",
    "quarantined_columns": "Personal identifiers",
    "low_confidence_mapping": "Column mapping",
}


@dataclass
class Finding:
    """One kind of problem, with the rows it affects."""

    severity: Severity
    check: str
    """Identifier of the check; a key of :data:`CHECK_LABELS`."""
    message: str
    field: str | None = None
    row_count: int = 0
    sample_rows: list[int] = dataclasses.field(default_factory=list)
    """Source row numbers of the first affected rows."""
    example: str | None = None
    """An offending source value, for illustration."""


class FindingCollector:
    """Gathers findings, merging repeats of the same problem into one finding."""

    def __init__(self) -> None:
        self._findings: dict[tuple[str, str | None, str], Finding] = {}

    def add(
        self,
        severity: Severity,
        check: str,
        message: str,
        *,
        field: str | None = None,
        row: int | None = None,
        example: str | None = None,
    ) -> None:
        """Record a problem; ``row`` is omitted for findings about the whole table."""
        finding = self._findings.setdefault(
            (check, field, message), Finding(severity, check, message, field, example=example)
        )
        if row is not None:
            finding.row_count += 1
            if len(finding.sample_rows) < _SAMPLE_ROWS:
                finding.sample_rows.append(row)

    def findings(self) -> list[Finding]:
        """All findings, most serious first."""
        order = list(Severity)
        return sorted(self._findings.values(), key=lambda finding: order.index(finding.severity))


_FORMAT_MESSAGES = {
    "mcc": "MCC must be three digits",
    "mnc": "MNC must be two or three digits (a leading zero may have been lost in the source)",
}


def build_measurement(
    values: dict[str, object], row: int, collector: FindingCollector
) -> Measurement:
    """Create a :class:`Measurement`, dropping values that fail validation.

    Checks every value against the schema (ranges and formats) and checks that
    latitude and longitude come as a pair; a complete position is recorded as
    WGS 84. Each dropped value is reported to ``collector``. ``values`` itself
    is not modified.
    """
    values = dict(values)
    if "latitude" in values and "longitude" in values:
        values["coordinate_reference_system"] = WGS84

    try:
        measurement: Measurement | None = Measurement(**values)
    except ValidationError as exc:
        measurement = None
        for error in exc.errors():
            name = str(error["loc"][0])
            check, message = _describe(name, error["type"], error["msg"])
            collector.add(
                Severity.ERROR, check, message, field=name, row=row, example=str(values.get(name))
            )
            values.pop(name, None)

    latitude, longitude = values.get("latitude"), values.get("longitude")
    if (latitude is None) != (longitude is None):
        collector.add(
            Severity.ERROR,
            "incomplete_coordinates",
            "Latitude or longitude is missing or invalid, so the position was not imported",
            row=row,
        )
        measurement = None
        for name in ("latitude", "longitude", "coordinate_reference_system"):
            values.pop(name, None)
    elif latitude == 0 and longitude == 0:
        collector.add(
            Severity.WARNING,
            "zero_coordinates",
            "Position is exactly 0, 0, which usually means there was no GPS fix; imported as given",
            row=row,
        )

    mcc, mnc = values.get("mcc"), values.get("mnc")
    if isinstance(mcc, str) and isinstance(mnc, str):
        values["plmn"] = f"{mcc}-{mnc}"
        measurement = None

    return measurement if measurement is not None else Measurement(**values)


def _describe(name: str, error_type: str, fallback: str) -> tuple[str, str]:
    """Check identifier and message for a schema validation error."""
    if error_type in ("greater_than_equal", "less_than_equal"):
        limits = field_range(name)
        if limits is not None:
            unit = f" {field_unit(name)}" if field_unit(name) else ""
            return "out_of_range", f"Outside the valid range {limits[0]:g} to {limits[1]:g}{unit}"
    if error_type == "string_pattern_mismatch" and name in _FORMAT_MESSAGES:
        return "invalid_format", _FORMAT_MESSAGES[name]
    if error_type == "finite_number":
        return "invalid_number", "Not a finite number"
    return "invalid_format", fallback
