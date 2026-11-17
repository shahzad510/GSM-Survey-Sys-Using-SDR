"""Read JSON files that hold lists of records."""

from __future__ import annotations

import json
from pathlib import Path

from cellsurvey.survey_import.source import (
    Extraction,
    SurveyImportError,
    build_table_from_records,
)


def load_json(path: Path) -> object:
    """Parse a JSON file.

    Raises:
        SurveyImportError: the file is not valid JSON.
        OSError: the file cannot be read.
    """

    def reject_constant(name: str) -> object:
        raise ValueError(f"{name} is not a valid JSON value")

    try:
        return json.loads(path.read_bytes().decode("utf-8-sig"), parse_constant=reject_constant)
    except json.JSONDecodeError as exc:
        raise SurveyImportError(
            f"{path.name} is not valid JSON: {exc.msg} (line {exc.lineno})."
        ) from exc
    except ValueError as exc:  # includes UnicodeDecodeError
        raise SurveyImportError(f"{path.name} is not valid JSON: {exc}.") from exc


def flatten(record: dict[str, object], prefix: str = "") -> dict[str, str | None]:
    """Flatten nested objects into dotted keys; lists are kept as JSON text."""
    flat: dict[str, str | None] = {}
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten(value, f"{name}."))
        elif value is None or isinstance(value, str):
            flat[name] = value
        else:
            flat[name] = json.dumps(value, ensure_ascii=False)
    return flat


def read_json(path: Path) -> Extraction:
    """Read record lists from a JSON file.

    The file is either a list of objects, or an object in which one or more
    members are lists of objects; each such list becomes a table.

    Raises:
        SurveyImportError: the file is not valid JSON or holds no record list.
    """
    document = load_json(path)
    if isinstance(document, list):
        candidates: dict[str, object] = {path.stem: document}
    elif isinstance(document, dict):
        candidates = dict(document)
    else:
        candidates = {}

    tables = tuple(
        build_table_from_records(
            name, ((number, flatten(record)) for number, record in enumerate(value, start=1))
        )
        for name, value in candidates.items()
        if _is_record_list(value)
    )
    if not tables:
        raise SurveyImportError(
            f"{path.name} does not contain a list of records. Expected a list of objects, "
            "or an object with a list of objects as one of its members."
        )
    return Extraction(tables)


def _is_record_list(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, dict) for item in value)
