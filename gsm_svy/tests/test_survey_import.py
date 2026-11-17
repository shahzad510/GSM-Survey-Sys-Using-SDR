"""Import pipeline: formats, mapping, validation, storage and export."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from cellsurvey.database import Database
from cellsurvey.database.repositories.survey_repository import SurveyRepository
from cellsurvey.schema import SourceFormat, Technology
from cellsurvey.survey_import.column_mapper import suggest_mapping
from cellsurvey.survey_import.file_detector import detect_format
from cellsurvey.survey_import.importer import SurveyImporter, load_source
from cellsurvey.survey_import.pdf_importer import ScannedPdfError
from cellsurvey.survey_import.source import SurveyImportError
from cellsurvey.survey_import.validation import Severity
from cellsurvey.survey_processing.duplicate_detection import content_hash, split_duplicates
from cellsurvey.survey_processing.exporter import ExportFormat, export_records
from cellsurvey.survey_processing.normalizer import (
    DateOrder,
    NormalizationOptions,
    Provenance,
    normalize_table,
    parse_timestamp,
    suggest_date_order,
)
from survey_data import (
    HEADER,
    write_csv,
    write_geojson,
    write_json,
    write_pdf,
    write_scanned_pdf,
    write_xlsx,
)


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[tuple[SurveyRepository, SurveyImporter]]:
    database = Database(tmp_path / "test.sqlite3")
    repository = SurveyRepository(database)
    importer = SurveyImporter(repository, tmp_path / "sources")
    yield repository, importer
    database.close()


# -- format detection and readers ---------------------------------------------


def test_detect_format_by_signature_and_extension(tmp_path: Path) -> None:
    assert detect_format(write_csv(tmp_path / "a.csv")) is SourceFormat.CSV
    assert detect_format(write_xlsx(tmp_path / "a.xlsx")) is SourceFormat.XLSX
    assert detect_format(write_json(tmp_path / "a.json")) is SourceFormat.JSON
    assert detect_format(write_geojson(tmp_path / "a.geojson")) is SourceFormat.GEOJSON
    assert detect_format(write_pdf(tmp_path / "a.pdf")) is SourceFormat.PDF
    geo_as_json = write_geojson(tmp_path / "points.json")
    assert detect_format(geo_as_json) is SourceFormat.GEOJSON


def test_csv_semicolon_and_windows_encoding(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "eu.csv", delimiter=";", encoding="cp1252")
    source = load_source(path)
    assert source.format is SourceFormat.CSV
    assert len(source.tables[0].rows) == 5


@pytest.mark.parametrize(
    ("writer", "name"),
    [(write_xlsx, "a.xlsx"), (write_json, "a.json"), (write_geojson, "a.geojson")],
)
def test_xlsx_and_json_and_geojson_round_trip_values(tmp_path: Path, writer, name) -> None:
    source = load_source(writer(tmp_path / name))
    table = source.tables[0]
    mapping = suggest_mapping(table.columns)
    assert "timestamp" in mapping and "rssi_dbm" in mapping
    assert "latitude" in mapping and "longitude" in mapping


def test_json_nested_cell_fields_are_suggested(tmp_path: Path) -> None:
    source = load_source(write_json(tmp_path / "nested.json"))
    mapping = suggest_mapping(source.tables[0].columns)
    assert mapping["cell_id"] == "cell.id"
    assert mapping["lac"] == "cell.lac"


def test_pdf_extracts_tables_and_scanned_pdf_is_refused(tmp_path: Path) -> None:
    digital = write_pdf(tmp_path / "digital.pdf")
    source = load_source(digital)
    assert source.format is SourceFormat.PDF
    assert source.tables
    assert "not been verified" in " ".join(source.notes).lower()

    scanned = write_scanned_pdf(tmp_path / "scan.pdf", digital)
    with pytest.raises(ScannedPdfError, match="OCR"):
        load_source(scanned)


# -- mapping and normalization ------------------------------------------------


def test_column_mapping_suggestions_ignore_units() -> None:
    mapping = suggest_mapping(["RSSI (dBm)", "RxLev", "Lat", "Lon", "Date/Time"])
    assert mapping["rssi_dbm"] == "RSSI (dBm)"
    assert mapping["latitude"] == "Lat"
    assert mapping["longitude"] == "Lon"


def test_normalization_preserves_mnc_leading_zero_and_rejects_bad_values(
    tmp_path: Path,
) -> None:
    rows = [
        ["2024-03-01T09:00:00Z", "GSM", "Test", "001", "01", "10", "20", "-70", "comment"],
        ["not-a-date", "GSM", "Test", "001", "01", "10", "20", "-70", "comment"],
        ["2024-03-01T09:00:10Z", "GSM", "Test", "001", "01", "91", "20", "-999", "comment"],
        ["2024-03-01T09:00:20Z", "LTE", "Test", "001", "01", "10", "20", "-75", "comment"],
    ]
    header = [
        "Timestamp",
        "Technology",
        "Operator",
        "MCC",
        "MNC",
        "Latitude",
        "Longitude",
        "RSSI (dBm)",
        "Comment",
    ]
    source = load_source(write_csv(tmp_path / "mixed.csv", rows, header))
    from cellsurvey.survey_import.validation import FindingCollector

    collector = FindingCollector()
    records = normalize_table(
        source.tables[0],
        suggest_mapping(source.tables[0].columns),
        NormalizationOptions(),
        Provenance(
            "mixed.csv",
            SourceFormat.CSV,
            source.measurement_method,
            parse_timestamp("2024-01-01T00:00:00Z", DateOrder.ISO_ONLY, __import__("zoneinfo").ZoneInfo("UTC")),
        ),
        collector,
    )
    assert records[0].mnc == "01"
    assert records[0].technology is Technology.GSM
    assert any(f.check == "invalid_timestamp" for f in collector.findings())
    assert any(f.check == "out_of_range" and f.field == "rssi_dbm" for f in collector.findings())
    bad = next(r for r in records if r.rssi_dbm is None and r.timestamp is not None)
    assert bad.source_values is not None


def test_date_order_suggestion_and_parsing() -> None:
    assert suggest_date_order(["03/04/2024", "15/04/2024"]) is DateOrder.DAY_FIRST
    assert suggest_date_order(["03/15/2024", "04/01/2024"]) is DateOrder.MONTH_FIRST
    assert suggest_date_order(["2024-03-01", "03/04/2024"]) is DateOrder.ISO_ONLY
    from zoneinfo import ZoneInfo

    utc = ZoneInfo("UTC")
    day = parse_timestamp("15/04/2024 13:45", DateOrder.DAY_FIRST, utc)
    assert day.day == 15 and day.month == 4


def test_duplicate_detection_ignores_records_without_timestamp() -> None:
    from cellsurvey.schema import Measurement

    a = Measurement(record_id="1", timestamp=parse_timestamp(
        "2024-03-01T09:00:00Z", DateOrder.ISO_ONLY, __import__("zoneinfo").ZoneInfo("UTC")
    ), rssi_dbm=-70)
    b = Measurement(record_id="2", timestamp=a.timestamp, rssi_dbm=-70)
    c = Measurement(record_id="3", rssi_dbm=-70)
    kept, hashes, duplicates = split_duplicates([a, b, c])
    assert [r.record_id for r in kept] == ["1", "3"]
    assert [r.record_id for r in duplicates] == ["2"]
    assert content_hash(c) is None
    assert hashes[0] == content_hash(a)


# -- database import / export -------------------------------------------------


def test_import_commit_lists_exports_and_rejects_duplicates(
    repo: tuple[SurveyRepository, SurveyImporter], tmp_path: Path
) -> None:
    repository, importer = repo
    path = write_csv(tmp_path / "survey.csv")
    source = load_source(path)
    prepared = importer.prepare(
        source,
        source.tables[0].name,
        suggest_mapping(source.tables[0].columns),
        NormalizationOptions(),
        source_instrument="Scanner X",
    )
    assert prepared.count(Severity.ERROR) == 0
    survey_id = importer.commit(prepared, "Field survey A", "notes")

    summaries = repository.list_surveys()
    assert summaries[0].name == "Field survey A"
    assert summaries[0].record_count == 5
    assert summaries[0].instruments == ("Scanner X",)
    records = repository.records(survey_id)
    assert records[0].mnc == "01"
    assert records[0].source_filename == "survey.csv"
    assert (tmp_path / "sources" / source.sha256 / "survey.csv").is_file()

    with pytest.raises(SurveyImportError, match="already imported"):
        importer.commit(prepared, "Again")

    for export_format in ExportFormat:
        result = export_records(
            records, tmp_path / f"out.{export_format.value}", export_format
        )
        assert result.written == 5
        assert result.path.is_file()

    geo = json.loads((tmp_path / "out.geojson").read_text(encoding="utf-8"))
    assert geo["type"] == "FeatureCollection"
    assert len(geo["features"]) == 5
    assert "fields" in geo["metadata"]

    assert repository.delete_survey(survey_id) is True
    assert repository.list_surveys() == []
    assert (tmp_path / "sources" / source.sha256 / "survey.csv").is_file()


def test_failed_commit_rolls_back_and_keeps_archive_clean(
    repo: tuple[SurveyRepository, SurveyImporter], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, importer = repo
    source = load_source(write_csv(tmp_path / "survey.csv"))
    prepared = importer.prepare(
        source,
        source.tables[0].name,
        suggest_mapping(source.tables[0].columns),
        NormalizationOptions(),
    )

    def boom(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("disk full")

    monkeypatch.setattr(repository, "save_import", boom)
    with pytest.raises(SurveyImportError, match="nothing was saved"):
        importer.commit(prepared, "Will fail")
    assert repository.list_surveys() == []
    assert list((tmp_path / "sources").glob("*/*")) == []


def test_incomplete_coordinates_are_dropped(tmp_path: Path) -> None:
    rows = [["2024-03-01T09:00:00Z", "GSM", "10.0", "", "-70"]]
    header = ["Timestamp", "Technology", "Latitude", "Longitude", "RSSI (dBm)"]
    source = load_source(write_csv(tmp_path / "coords.csv", rows, header))
    from cellsurvey.survey_import.validation import FindingCollector
    from zoneinfo import ZoneInfo

    collector = FindingCollector()
    records = normalize_table(
        source.tables[0],
        suggest_mapping(source.tables[0].columns),
        NormalizationOptions(),
        Provenance(
            "coords.csv",
            SourceFormat.CSV,
            source.measurement_method,
            parse_timestamp("2024-01-01T00:00:00Z", DateOrder.ISO_ONLY, ZoneInfo("UTC")),
        ),
        collector,
    )
    assert records[0].latitude is None and records[0].longitude is None
    assert any(f.check == "incomplete_coordinates" for f in collector.findings())


def test_xlsx_multi_sheet_import(tmp_path: Path) -> None:
    path = write_xlsx(
        tmp_path / "multi.xlsx",
        {
            "Sheet1": [HEADER, *[["2024-03-01 09:00:00", "GSM", "Test Network", "001", "01",
                                   "1", "2", "62", "-70", "10", "20", "a"]]],
            "Empty": [["Only", "Header"]],
        },
    )
    source = load_source(path)
    assert [table.name for table in source.tables] == ["Sheet1"]
