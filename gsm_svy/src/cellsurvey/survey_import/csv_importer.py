"""Read delimited text files (CSV, TSV, semicolon-separated)."""

from __future__ import annotations

import codecs
import csv
import io
from pathlib import Path

from cellsurvey.survey_import.source import Extraction, SurveyImportError, build_table

_DELIMITERS = ",;\t|"
_SNIFF_CHARACTERS = 16384


def read_csv(path: Path) -> Extraction:
    """Read a delimited text file. The first non-empty line is the header.

    Raises:
        SurveyImportError: the file is empty.
        OSError: the file cannot be read.
    """
    text, notes = _decode(path.read_bytes())
    try:
        dialect: type[csv.Dialect] = csv.Sniffer().sniff(text[:_SNIFF_CHARACTERS], _DELIMITERS)
    except csv.Error:
        dialect = csv.excel  # one column, or too irregular to tell: assume commas

    reader = csv.reader(io.StringIO(text, newline=""), dialect)
    header: list[str] | None = None
    rows: list[tuple[int, list[str]]] = []
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        if header is None:
            header = row
        else:
            rows.append((reader.line_num, row))
    if header is None:
        raise SurveyImportError(f"{path.name} is empty.")
    return Extraction((build_table(path.stem, header, rows),), tuple(notes))


def _decode(raw: bytes) -> tuple[str, list[str]]:
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16"), []
    try:
        return raw.decode("utf-8-sig"), []
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace"), [
            "The file is not valid UTF-8 and was read as Windows-1252. "
            "Check names that contain accented or non-Latin characters."
        ]
