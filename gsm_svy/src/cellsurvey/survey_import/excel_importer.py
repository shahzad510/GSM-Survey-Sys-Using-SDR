"""Read Excel workbooks: .xlsx through OpenPyXL, legacy .xls through xlrd."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from cellsurvey.schema import SourceFormat
from cellsurvey.survey_import.source import (
    Extraction,
    SourceTable,
    SurveyImportError,
    build_table,
    cell_text,
)

_ENGINES = {SourceFormat.XLSX: "openpyxl", SourceFormat.XLS: "xlrd"}


def read_excel(path: Path, source_format: SourceFormat) -> Extraction:
    """Read every worksheet that has data. Each sheet's first non-empty row is its header.

    Raises:
        SurveyImportError: the workbook cannot be opened or has no data.
    """
    try:
        sheets = pd.read_excel(
            path, sheet_name=None, header=None, dtype=object, engine=_ENGINES[source_format]
        )
    except Exception as exc:  # noqa: BLE001 - the engines raise many unrelated error types
        raise SurveyImportError(
            f"{path.name} could not be read as an Excel workbook: {exc}"
        ) from exc

    tables: list[SourceTable] = []
    for name, frame in sheets.items():
        header: tuple[object, ...] | None = None
        rows: list[tuple[int, tuple[object, ...]]] = []
        for index, row in zip(frame.index, frame.itertuples(index=False, name=None)):
            if all(cell_text(value) is None for value in row):
                continue
            if header is None:
                header = row
            else:
                rows.append((int(index) + 1, row))  # spreadsheet rows count from 1
        if header is not None and rows:
            tables.append(build_table(str(name), header, rows))
    if not tables:
        raise SurveyImportError(f"{path.name} contains no data.")
    return Extraction(tuple(tables))
