"""Read GeoJSON: each Point feature is one measurement record."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from cellsurvey.survey_import.json_importer import flatten, load_json
from cellsurvey.survey_import.source import (
    Extraction,
    SurveyImportError,
    build_table_from_records,
)

LONGITUDE_COLUMN = "geometry.longitude"
LATITUDE_COLUMN = "geometry.latitude"
ALTITUDE_COLUMN = "geometry.altitude"

_WGS84_NAMES = ("crs84", "epsg::4326", "epsg:4326")


def read_geojson(path: Path) -> Extraction:
    """Read the features of a GeoJSON file.

    Feature properties become columns. A Point geometry adds the columns
    ``geometry.longitude``, ``geometry.latitude`` and, if present,
    ``geometry.altitude``. Features without geometry are kept; features with
    any other geometry are skipped and counted in the notes.

    Raises:
        SurveyImportError: the file is not GeoJSON or has no usable feature.
    """
    document = load_json(path)
    kind = document.get("type") if isinstance(document, dict) else None
    if kind == "FeatureCollection" and isinstance(document.get("features"), list):  # type: ignore[union-attr]
        features = document["features"]  # type: ignore[index]
    elif kind == "Feature":
        features = [document]
    else:
        raise SurveyImportError(f"{path.name} is not a GeoJSON Feature or FeatureCollection.")

    records: list[tuple[int, dict[str, object]]] = []
    skipped: Counter[str] = Counter()
    for number, feature in enumerate(features, start=1):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            skipped["an invalid structure"] += 1
            continue
        properties = feature.get("properties")
        record: dict[str, object] = dict(flatten(properties if isinstance(properties, dict) else {}))
        geometry = feature.get("geometry")
        if geometry is not None:
            coordinates = _point_coordinates(geometry)
            if coordinates is None:
                geometry_type = geometry.get("type") if isinstance(geometry, dict) else None
                skipped[f"geometry type {geometry_type}"] += 1
                continue
            record.update(zip((LONGITUDE_COLUMN, LATITUDE_COLUMN, ALTITUDE_COLUMN), coordinates))
        records.append((number, record))

    if not records:
        raise SurveyImportError(f"{path.name} contains no Point features to import.")

    notes = [
        f"{count} feature(s) with {reason} were skipped. Only Point features are "
        "imported as measurements."
        for reason, count in skipped.items()
    ]
    declared = _declared_crs(document)
    if declared is not None:
        notes.append(
            f"The file declares the coordinate reference system {declared}. Coordinates are "
            "read as WGS 84 longitude and latitude, so positions will be wrong or rejected."
        )
    return Extraction((build_table_from_records(path.stem, records),), tuple(notes))


def _point_coordinates(geometry: object) -> list[str] | None:
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not 2 <= len(coordinates) <= 3:
        return None
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in coordinates):
        return None
    return [repr(value) for value in coordinates]


def _declared_crs(document: object) -> str | None:
    """Name of a legacy ``crs`` member, unless it says WGS 84."""
    crs = document.get("crs") if isinstance(document, dict) else None
    if not isinstance(crs, dict):
        return None
    properties = crs.get("properties")
    name = str(properties.get("name")) if isinstance(properties, dict) else str(crs)
    return None if name.lower().endswith(_WGS84_NAMES) else name
