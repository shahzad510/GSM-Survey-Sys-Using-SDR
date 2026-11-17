"""Read tables from PDF survey reports.

Only PDFs with a text layer are supported. A scanned PDF holds page images and
would need OCR, which this version does not provide; such a file is refused
with an explanation rather than read as if it were empty.

Table extraction reconstructs rows and columns from the position of text on the
page and can misread a document. Values obtained this way are therefore marked
as unverified (``MeasurementMethod.PDF_TEXT_EXTRACTION``) wherever they go.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from cellsurvey.survey_import.source import (
    Extraction,
    SourceTable,
    SurveyImportError,
    build_table,
)

UNVERIFIED_NOTE = (
    "These values were extracted from the text of a PDF and have not been verified. "
    "Table extraction can misread a document: compare the preview with the original "
    "before relying on the data."
)


class ScannedPdfError(SurveyImportError):
    """The PDF has no text layer, so nothing can be extracted without OCR."""


def read_pdf(path: Path) -> Extraction:
    """Extract the tables of a PDF.

    Tables with the same header row, typically one table continued over several
    pages, are joined into one.

    Raises:
        ScannedPdfError: no page has extractable text.
        SurveyImportError: the PDF cannot be opened or has no tables.
    """
    try:
        document = pymupdf.open(path)
    except Exception as exc:  # noqa: BLE001 - PyMuPDF raises several unrelated error types
        raise SurveyImportError(f"{path.name} could not be opened as a PDF: {exc}") from exc

    with document:
        if document.needs_pass:
            raise SurveyImportError(f"{path.name} is password-protected.")

        # header -> (pages the table appears on, data rows)
        groups: dict[tuple[str, ...], tuple[list[int], list[list[str | None]]]] = {}
        pages_without_text = 0
        for page in document:
            if not page.get_text().strip():
                pages_without_text += 1
                continue
            for table in page.find_tables().tables:
                rows = [[_clean(cell) for cell in row] for row in table.extract()]
                if len(rows) < 2:
                    continue
                pages, data = groups.setdefault(tuple(cell or "" for cell in rows[0]), ([], []))
                pages.append(page.number + 1)
                data.extend(rows[1:])
        page_count = document.page_count

    if page_count and pages_without_text == page_count:
        raise ScannedPdfError(
            f"{path.name} has no extractable text. It appears to be a scanned document, "
            "which needs OCR. OCR is not available in this version."
        )
    if not groups:
        raise SurveyImportError(f"{path.name} contains text, but no tables were found in it.")

    tables = tuple(
        _table(number, header, pages, data)
        for number, (header, (pages, data)) in enumerate(groups.items(), start=1)
    )
    notes = [UNVERIFIED_NOTE]
    if pages_without_text:
        notes.append(
            f"{pages_without_text} of {page_count} pages have no extractable text "
            "(probably scanned images) and were not read."
        )
    return Extraction(tables, tuple(notes))


def _table(
    number: int, header: tuple[str, ...], pages: list[int], data: list[list[str | None]]
) -> SourceTable:
    span = f"page {pages[0]}" if pages[0] == pages[-1] else f"pages {pages[0]}–{pages[-1]}"
    return build_table(f"Table {number} ({span})", header, enumerate(data, start=1))


def _clean(cell: str | None) -> str | None:
    """Join the lines of a wrapped cell."""
    return " ".join(cell.split()) or None if cell else None
