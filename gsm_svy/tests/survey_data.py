"""Synthetic survey files for tests.

Nothing here comes from a real survey: the operator is the international test
network 001-01, cell identities are invented and positions are arbitrary.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

import pymupdf
from openpyxl import Workbook

HEADER = [
    "Timestamp",
    "Technology",
    "Operator",
    "MCC",
    "MNC",
    "Cell ID",
    "LAC",
    "ARFCN",
    "RSSI (dBm)",
    "Latitude",
    "Longitude",
    "Comment",
]
START = datetime(2024, 3, 1, 9, 0, 0)


def survey_rows(count: int = 5) -> list[list[str]]:
    """``count`` GSM measurements ten seconds apart, as text."""
    return [
        [
            (START + timedelta(seconds=10 * index)).strftime("%Y-%m-%d %H:%M:%S"),
            "GSM",
            "Test Network",
            "001",
            "01",
            str(1000 + index),
            "200",
            "62",
            str(-70 - index),
            f"{10.0 + index * 0.001:.6f}",
            "20.000000",
            f"point {index + 1}",
        ]
        for index in range(count)
    ]


def write_csv(
    path: Path,
    rows: Sequence[Sequence[str]] | None = None,
    header: Sequence[str] = HEADER,
    delimiter: str = ",",
    encoding: str = "utf-8",
) -> Path:
    with path.open("w", encoding=encoding, newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter)
        writer.writerow(header)
        writer.writerows(survey_rows() if rows is None else rows)
    return path


def write_xlsx(path: Path, sheets: dict[str, Sequence[Sequence[object]]] | None = None) -> Path:
    """Write a workbook; each sheet is a list of rows, the first being its header."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in (sheets or {"Measurements": [HEADER, *survey_rows()]}).items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(list(row))
    workbook.save(path)
    return path


def records(count: int = 5) -> list[dict[str, object]]:
    """The survey rows as JSON-style objects with native numbers."""
    return [
        {
            "timestamp": row[0].replace(" ", "T") + "Z",
            "technology": row[1],
            "operator": row[2],
            "mcc": row[3],
            "mnc": row[4],
            "cell": {"id": int(row[5]), "lac": int(row[6])},
            "arfcn": int(row[7]),
            "rssi_dbm": float(row[8]),
            "latitude": float(row[9]),
            "longitude": float(row[10]),
        }
        for row in survey_rows(count)
    ]


def write_json(path: Path, document: object | None = None) -> Path:
    path.write_text(json.dumps(records() if document is None else document), encoding="utf-8")
    return path


def write_geojson(path: Path, extra_features: Sequence[dict[str, object]] = ()) -> Path:
    features: list[dict[str, object]] = []
    for record in records():
        properties = {k: v for k, v in record.items() if k not in ("latitude", "longitude")}
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [record["longitude"], record["latitude"], 250.0],
                },
                "properties": properties,
            }
        )
    document = {"type": "FeatureCollection", "features": [*features, *extra_features]}
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def write_pdf(
    path: Path,
    rows: Sequence[Sequence[str]] | None = None,
    header: Sequence[str] = HEADER,
    rows_per_page: int = 20,
) -> Path:
    """Write a report with a ruled table, continued over pages with the header repeated."""
    rows = survey_rows() if rows is None else rows
    document = pymupdf.open()
    width, row_height, left, top = 64, 18, 30, 80
    for start in range(0, len(rows), rows_per_page):
        page = document.new_page(width=left * 2 + width * len(header), height=595)
        page.insert_text((left, 50), "Synthetic GSM survey report", fontsize=14)
        for line, cells in enumerate([header, *rows[start : start + rows_per_page]]):
            for column, text in enumerate(cells):
                x, y = left + column * width, top + line * row_height
                page.draw_rect(pymupdf.Rect(x, y, x + width, y + row_height), width=0.5)
                page.insert_text((x + 2, y + 12), text, fontsize=6)
    document.save(path)
    document.close()
    return path


def write_scanned_pdf(path: Path, source: Path) -> Path:
    """Write a PDF whose only page is an image of ``source``'s first page: no text layer."""
    with pymupdf.open(source) as original:
        image = original[0].get_pixmap(dpi=72)
        size = original[0].rect
    document = pymupdf.open()
    page = document.new_page(width=size.width, height=size.height)
    page.insert_image(page.rect, pixmap=image)
    document.save(path)
    document.close()
    return path
