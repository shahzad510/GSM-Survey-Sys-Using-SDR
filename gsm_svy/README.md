# Cellular Survey System (CSS)

A desktop application for passive cellular RF survey and measurement analysis
(2G GSM, 3G UMTS/WCDMA, 4G LTE).

Measurement sources:

- A Samsung Galaxy A6 (SM-A600F) over ADB (live receiver path).
- Historical survey files imported into a common schema (CSV, Excel, JSON,
  GeoJSON, PDF).
- RTL-SDR and other SDR receivers are planned later. The receiver abstraction
  and the database are designed so they can be added without rewriting the
  import or reporting paths.

The application only collects measurements that a receiver or a source file
exposes. It does not transmit, does not intercept subscriber communications,
does not use root access or modem modifications, and never fabricates a value:
anything unavailable is stored and shown as null.

## Status

| Milestone | Scope | State |
|-----------|-------|-------|
| 1 | Project skeleton, environment, PySide6 main window, navigation, logging | Done |
| 2 | Receiver abstraction, ADB detection, device capability inspection | Done |
| 2b | Survey import and data management (CSV/Excel/JSON/GeoJSON/PDF, SQLite, explorer, export) | Done |
| 3 | Live measurement acquisition from the phone | Not started |
| 4 | GPS and live survey recording | Not started |
| 5 | Live graphs, geographic mapping, historical analysis | Not started |
| 6 | Formal PDF survey reports | Not started |
| 7 | SDR receivers (RTL-SDR first, then SoapySDR / USRP / Pluto / bladeRF) | Not started |

Further modules specified but not started:

- **GSM Survey Analysis and Geographic Reporting** (Natural Earth boundaries,
  cross-border aggregate comparison, ReportLab PDF reports). Import and the
  database from 2b are the foundation.
- **MCC/MNC Operator Identification Engine**.

## Importing a survey file

1. Open **Import Survey**.
2. Select a CSV, XLSX, XLS, JSON, GeoJSON or PDF file.
3. Inspect detected tables, columns and sample rows.
4. Confirm or correct the column mapping. Suggestions are based on column names.
5. Review validation findings. Invalid values become null; they are never corrected.
6. Preview normalized records, name the survey and import.

Imported source files are copied unchanged into the survey-source archive.
Duplicate file content and duplicate measurements (same timestamp and values)
are refused. Deleting a survey removes stored records but keeps the archived
source file.

Open **Survey Explorer** to filter, inspect, export (CSV / JSON / XLSX /
GeoJSON) or delete imported surveys.

PDF notes:

- Digitally generated PDFs with a text layer can be read. Extracted values are
  marked as unverified (`pdf_text_extraction`).
- Scanned PDFs are refused. OCR is optional and not installed in this version.

## Using a phone as the receiver

1. On the phone, enable Developer options and USB debugging.
2. Connect it by USB and accept the "Allow USB debugging" prompt.
3. Open **Receiver Manager**. The phone appears within a few seconds (the list
   refreshes every 5 seconds, or choose **Scan now**).
4. Select it and choose **Connect**, then **Inspect capabilities**.

The application runs only read-only commands on the phone (`getprop` and
`dumpsys telephony.registry`) as the unprivileged `shell` user.

### What the SM-A600F exposes

Investigated on a Samsung SM-A600F running Android 10 (API 29) on a UMTS
network. Other phones and Android versions may differ.

| Data | Through ADB | Notes |
|------|-------------|-------|
| Network technology | Yes | One value per SIM slot |
| Operator name, MCC, MNC | Yes | MNC keeps its leading zero |
| Channel number (UARFCN), PSC | Yes | |
| RSSI, RSCP | Yes | Serving cell only |
| Ec/No | Not established | Printed as `0` |
| Cell identity, LAC | **No** | Android prints `<MASKED>` |
| Neighbouring cells | Not seen | |
| Raw modem data, RF samples | No | A phone is not an SDR |

Android writes `2147483647` where a value is unavailable; that must become null.

## Requirements

- Ubuntu 24.04 LTS
- Python 3.12 or newer with the `venv` module (`sudo apt install python3-venv`)
- Qt X11 libraries: `sudo apt install libxcb-cursor0 libegl1 libxkbcommon-x11-0`
- ADB: `sudo apt install adb`

SDR software is not installed before Milestone 7. Tesseract OCR is not required.

## Installation

```bash
cd gsm_svy
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Dependencies include PySide6, PyQtGraph, Matplotlib, Folium, NumPy, SciPy,
Pandas, SQLAlchemy, Pydantic, OpenPyXL, xlrd, PyMuPDF and Pytest.

## Running

```bash
cellsurvey                      # or: python -m cellsurvey
cellsurvey --log-level DEBUG
cellsurvey --version
python -m pytest
```

## Configuration, database and logs

| Item | Default location |
|------|------------------|
| Configuration file | `~/.config/cellsurvey/config.json` |
| SQLite database | `~/.local/share/cellsurvey/cellsurvey.sqlite3` |
| Survey source archive | `~/.local/share/cellsurvey/survey_sources/` |
| Log file | `~/.local/state/cellsurvey/logs/cellsurvey.log` |

Set `CELLSURVEY_HOME=/some/dir` to keep everything under one directory.

```json
{
  "log_level": "INFO",
  "window_width": 1280,
  "window_height": 800,
  "adb_path": null
}
```

## Project layout

```
pyproject.toml
src/cellsurvey/
    app.py                  Entry point
    schema.py               Common Measurement model
    surveys.py              SurveyService (database + importer for the UI)
    config.py / logging_setup.py / state.py
    receivers/              BaseReceiver, ADB, AndroidADBReceiver, ReceiverManager
    survey_import/          File readers, column mapping, validation, importer
    survey_processing/      Normalization, duplicate detection, export
    database/               SQLAlchemy models and SurveyRepository
    ui/                     Main window, theme, Import Survey, Survey Explorer, …
tests/                      Pytest suite (synthetic survey fixtures; no phone needed)
```

## RTL-SDR (later)

RTL-SDR support is deferred. When it is added it will implement the existing
`BaseReceiver` interface, store RF acquisitions separately from phone-reported
and imported cellular measurements, and will not claim absolute dBm values
without a documented calibration procedure. No RTL-SDR packages are installed yet.
