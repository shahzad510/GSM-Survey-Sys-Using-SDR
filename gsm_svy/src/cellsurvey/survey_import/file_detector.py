"""Identify the format of a survey file from its content and its extension."""

from __future__ import annotations

import json
from pathlib import Path

from cellsurvey.schema import SourceFormat
from cellsurvey.survey_import.source import SurveyImportError

# Leading bytes that identify a format whatever the file is called.
_SIGNATURES = (
    (b"%PDF-", SourceFormat.PDF),
    (b"PK\x03\x04", SourceFormat.XLSX),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", SourceFormat.XLS),
)

_EXTENSIONS = {
    ".csv": SourceFormat.CSV,
    ".tsv": SourceFormat.CSV,
    ".txt": SourceFormat.CSV,
    ".xlsx": SourceFormat.XLSX,
    ".xlsm": SourceFormat.XLSX,
    ".xls": SourceFormat.XLS,
    ".json": SourceFormat.JSON,
    ".geojson": SourceFormat.GEOJSON,
    ".pdf": SourceFormat.PDF,
}
SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(_EXTENSIONS)

_BINARY_FORMATS = frozenset({SourceFormat.XLSX, SourceFormat.XLS, SourceFormat.PDF})
_GEOJSON_TYPES = frozenset({"FeatureCollection", "Feature"})


def detect_format(path: Path) -> SourceFormat:
    """Return the format of ``path``.

    Raises:
        SurveyImportError: the file cannot be read, is of an unsupported type,
            or its content contradicts its extension.
    """
    try:
        with path.open("rb") as stream:
            head = stream.read(8)
    except OSError as exc:
        raise SurveyImportError(f"Cannot read {path.name}: {exc.strerror or exc}") from exc

    for signature, source_format in _SIGNATURES:
        if head.startswith(signature):
            return source_format

    suffix = path.suffix.lower()
    source_format = _EXTENSIONS.get(suffix)
    if source_format is None:
        raise SurveyImportError(
            f"{path.name} is not a supported file type. "
            f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}."
        )
    if source_format in _BINARY_FORMATS:
        raise SurveyImportError(
            f"{path.name} has the extension {suffix} but its content is not in that format."
        )
    if source_format is SourceFormat.JSON and _is_geojson(path):
        return SourceFormat.GEOJSON
    return source_format


def _is_geojson(path: Path) -> bool:
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False  # the JSON reader reports what is wrong
    return isinstance(document, dict) and document.get("type") in _GEOJSON_TYPES
