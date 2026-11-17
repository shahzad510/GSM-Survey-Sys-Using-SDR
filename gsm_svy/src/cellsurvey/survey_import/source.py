"""What a survey file looks like once it has been read, before any interpretation.

Every format is reduced to one or more tables of text cells. Cells keep the
text of the source; nothing is converted or guessed at this stage.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

from cellsurvey.schema import MeasurementMethod, SourceFormat


class SurveyImportError(Exception):
    """A survey file could not be read or imported. The message is shown to the user."""


@dataclass(frozen=True)
class SourceTable:
    """One table of a source file: a worksheet, a PDF table, or a list of records."""

    name: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str | None, ...], ...]
    """Cell text per row, aligned with ``columns``; an empty cell is ``None``."""
    row_numbers: tuple[int, ...]
    """Position of each row in the source (spreadsheet row, line or record number)."""

    def column_values(self, column: str) -> list[str | None]:
        """All values of one column, in row order."""
        index = self.columns.index(column)
        return [row[index] for row in self.rows]


@dataclass(frozen=True)
class Extraction:
    """What a format reader returns."""

    tables: tuple[SourceTable, ...]
    notes: tuple[str, ...] = ()
    """Things the user should know about how the file was read."""


@dataclass(frozen=True)
class SourceFile:
    """A survey file that has been read."""

    path: Path
    format: SourceFormat
    size_bytes: int
    sha256: str
    tables: tuple[SourceTable, ...]
    notes: tuple[str, ...]
    measurement_method: MeasurementMethod

    def table(self, name: str) -> SourceTable:
        """The table with the given name.

        Raises:
            KeyError: the file has no such table.
        """
        for table in self.tables:
            if table.name == name:
                return table
        raise KeyError(name)


def cell_text(value: object) -> str | None:
    """Text of one source cell; ``None`` for an empty cell."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, float) and math.isnan(value):
        return None  # how pandas represents an empty spreadsheet cell
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, (date, time)):
        return value.isoformat()
    return str(value)


def build_table(
    name: str, header: Sequence[object], rows: Iterable[tuple[int, Sequence[object]]]
) -> SourceTable:
    """Build a table from a header row and numbered data rows.

    Rows without any value are dropped. Rows are padded to a common width, and
    a row wider than the header gets extra columns rather than losing cells.
    """
    numbers: list[int] = []
    cells: list[list[str | None]] = []
    for number, row in rows:
        texts = [cell_text(value) for value in row]
        if any(text is not None for text in texts):
            numbers.append(number)
            cells.append(texts)

    width = max([len(header), *(len(row) for row in cells)])
    columns = _column_names([*header, *[None] * (width - len(header))])
    return SourceTable(
        name=name,
        columns=columns,
        rows=tuple(tuple(row + [None] * (width - len(row))) for row in cells),
        row_numbers=tuple(numbers),
    )


def build_table_from_records(
    name: str, records: Iterable[tuple[int, Mapping[str, object]]]
) -> SourceTable:
    """Build a table from numbered records; the columns are the union of their keys."""
    numbered = list(records)
    columns: dict[str, None] = {}
    for _, record in numbered:
        columns.update(dict.fromkeys(record))
    header = list(columns)
    return build_table(
        name, header, ((number, [record.get(key) for key in header]) for number, record in numbered)
    )


def _column_names(header: Sequence[object]) -> tuple[str, ...]:
    """Unique, non-empty column names: blanks are numbered and repeats get a suffix."""
    names: list[str] = []
    for position, value in enumerate(header, start=1):
        base = " ".join((cell_text(value) or f"Column {position}").split())
        name, repeat = base, 1
        while name in names:
            repeat += 1
            name = f"{base} ({repeat})"
        names.append(name)
    return tuple(names)
