"""Export normalized measurement records to CSV, JSON, XLSX and GeoJSON.

Every export carries the schema's field names (which include the unit), the
provenance of each record and its original source values. JSON, XLSX and
GeoJSON also carry a description and unit for every field. Null values are
written as empty cells or JSON ``null``, never as zero.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from openpyxl import Workbook

from cellsurvey import APP_NAME, __version__
from cellsurvey.schema import FIELD_NAMES, Measurement, field_description, field_unit


class ExportFormat(str, Enum):
    """File formats records can be exported to."""

    CSV = "csv"
    JSON = "json"
    XLSX = "xlsx"
    GEOJSON = "geojson"


@dataclass(frozen=True)
class ExportResult:
    """Outcome of an export."""

    path: Path
    written: int
    skipped_without_position: int
    """Records left out of a GeoJSON export because they have no coordinates."""


def export_records(
    records: Sequence[Measurement], path: Path, export_format: ExportFormat
) -> ExportResult:
    """Write ``records`` to ``path``.

    Raises:
        OSError: the file cannot be written.
    """
    if export_format is ExportFormat.GEOJSON:
        located = [r for r in records if r.latitude is not None and r.longitude is not None]
        _write_json(path, _geojson(located))
        return ExportResult(path, len(located), len(records) - len(located))
    if export_format is ExportFormat.JSON:
        _write_json(
            path, {**_metadata(), "records": [record.model_dump(mode="json") for record in records]}
        )
    elif export_format is ExportFormat.CSV:
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(FIELD_NAMES)
            writer.writerows(_flat_row(record) for record in records)
    else:
        _write_xlsx(path, records)
    return ExportResult(path, len(records), 0)


def _metadata() -> dict[str, object]:
    return {
        "generator": f"{APP_NAME} {__version__}",
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fields": {
            name: {"unit": field_unit(name), "description": field_description(name)}
            for name in FIELD_NAMES
        },
    }


def _flat_row(record: Measurement) -> list[object]:
    """One spreadsheet row: scalars as they are, the source values as JSON text."""
    values = record.model_dump(mode="json")
    if values["source_values"] is not None:
        values["source_values"] = json.dumps(values["source_values"], ensure_ascii=False)
    return [values[name] for name in FIELD_NAMES]


def _geojson(records: Sequence[Measurement]) -> dict[str, object]:
    features = []
    for record in records:
        coordinates = [record.longitude, record.latitude]
        if record.altitude_m is not None:
            coordinates.append(record.altitude_m)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coordinates},
                "properties": record.model_dump(mode="json"),
            }
        )
    # "metadata" is a foreign member, which RFC 7946 allows.
    return {"type": "FeatureCollection", "metadata": _metadata(), "features": features}


def _write_json(path: Path, document: dict[str, object]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _write_xlsx(path: Path, records: Sequence[Measurement]) -> None:
    workbook = Workbook(write_only=True)
    measurements = workbook.create_sheet("Measurements")
    measurements.append(FIELD_NAMES)
    for record in records:
        measurements.append(_flat_row(record))

    fields = workbook.create_sheet("Fields")
    fields.append(("Field", "Unit", "Description"))
    for name in FIELD_NAMES:
        fields.append((name, field_unit(name), field_description(name)))

    about = workbook.create_sheet("About")
    about.append(("Generator", f"{APP_NAME} {__version__}"))
    about.append(("Exported at (UTC)", datetime.now(timezone.utc).isoformat(timespec="seconds")))
    workbook.save(path)
