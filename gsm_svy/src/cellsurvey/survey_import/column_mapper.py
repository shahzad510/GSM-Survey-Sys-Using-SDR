"""Map the columns of a source table to fields of the common measurement schema."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from cellsurvey.survey_import.privacy import is_pii_column

FieldKind = Literal["text", "integer", "number", "timestamp", "technology"]

# Aliases that are useful but easy to misread; they get a lower confidence score.
_WEAK_ALIASES = frozenset(
    {
        "time",
        "date",
        "system",
        "network",
        "signalstrength",
        "signalstrengthdbm",
        "freq",
        "alt",
        "long",
    }
)

# Column keys that are too ambiguous to assign automatically.
_AMBIGUOUS_KEYS = frozenset({"channel", "signal", "level", "power", "id", "code"})


@dataclass(frozen=True)
class MappableField:
    """A schema field that a source column can be mapped to."""

    name: str
    """Field name in :class:`cellsurvey.schema.Measurement`."""
    label: str
    """Name shown to the user, with the unit where there is one."""
    kind: FieldKind
    """How source text is converted to the field's value."""
    aliases: tuple[str, ...]
    """Column names that suggest this field, most specific first."""


@dataclass(frozen=True)
class MappingSuggestion:
    """One automatic mapping from a source column to a schema field."""

    field: str
    column: str
    confidence: float
    """0.0–1.0. Below 0.7 should be reviewed carefully."""
    reason: str


MAPPABLE_FIELDS: tuple[MappableField, ...] = (
    MappableField(
        "timestamp",
        "Timestamp",
        "timestamp",
        (
            "timestamp",
            "datetime",
            "datetimeutc",
            "utctime",
            "timeutc",
            "measurementtime",
            "date_time",
            "time",
            "date",
            "surveydate",
        ),
    ),
    MappableField(
        "technology",
        "Technology",
        "technology",
        ("technology", "tech", "rat", "radiotechnology", "networktype", "networktech", "system"),
    ),
    MappableField("country", "Country", "text", ("country", "countryname")),
    MappableField(
        "operator",
        "Operator",
        "text",
        ("operator", "operatorname", "networkname", "network", "carrier", "provider"),
    ),
    MappableField("mcc", "MCC", "text", ("mcc", "mobilecountrycode", "mobile_country_code")),
    MappableField("mnc", "MNC", "text", ("mnc", "mobilenetworkcode", "mobile_network_code")),
    MappableField(
        "cell_id",
        "Cell ID",
        "integer",
        ("cellid", "cell.id", "cid", "ci", "cellidentity", "eci"),
    ),
    MappableField("lac", "LAC", "integer", ("lac", "cell.lac", "celllac", "locationareacode")),
    MappableField("tac", "TAC", "integer", ("tac", "cell.tac", "celltac", "trackingareacode")),
    MappableField("arfcn", "ARFCN", "integer", ("arfcn", "bccharfcn", "bcch")),
    MappableField("uarfcn", "UARFCN", "integer", ("uarfcn",)),
    MappableField("earfcn", "EARFCN", "integer", ("earfcn",)),
    MappableField("bsic", "BSIC", "integer", ("bsic",)),
    MappableField("psc", "PSC", "integer", ("psc", "primaryscramblingcode", "scramblingcode")),
    MappableField("pci", "PCI", "integer", ("pci", "physicalcellid", "physicalcellidentity")),
    MappableField(
        "frequency_mhz",
        "Frequency (MHz)",
        "number",
        ("frequencymhz", "freqmhz", "frequency", "freq", "centerfrequency", "centrefrequency"),
    ),
    MappableField(
        "band",
        "Band",
        "text",
        ("band", "bandname", "frequencyband", "lteband", "umtsband", "gsmband"),
    ),
    MappableField(
        "rssi_dbm",
        "RSSI (dBm)",
        "number",
        (
            "rssidbm",
            "rssi",
            "rxlevdbm",
            "rxlev",
            "rxlevel",
            "rxlevfull",
            "rxlevsub",
            "signalstrength",
            "signalstrengthdbm",
        ),
    ),
    MappableField(
        "rsrp_dbm",
        "RSRP (dBm)",
        "number",
        ("rsrpdbm", "rsrp", "referencesignalpower", "reference_signal_power"),
    ),
    MappableField(
        "rsrq_db",
        "RSRQ (dB)",
        "number",
        ("rsrqdb", "rsrq", "referencesignalquality", "reference_signal_quality"),
    ),
    MappableField(
        "sinr_db",
        "SINR (dB)",
        "number",
        (
            "sinrdb",
            "sinr",
            "rssnr",
            "snr",
            "signaltointerferencenoiseratio",
            "signal_to_interference_noise_ratio",
        ),
    ),
    MappableField(
        "rscp_dbm",
        "RSCP (dBm)",
        "number",
        ("rscpdbm", "rscp", "cpichrscp", "receivedsignalcodepower", "received_signal_code_power"),
    ),
    MappableField(
        "ecno_db",
        "Ec/No (dB)",
        "number",
        ("ecnodb", "ecno", "ecn0", "eciodb", "ecio", "cpichecno"),
    ),
    MappableField(
        "latitude",
        "Latitude (degrees)",
        "number",
        ("latitude", "lat", "gpslatitude", "gpslat", "geometrylatitude"),
    ),
    MappableField(
        "longitude",
        "Longitude (degrees)",
        "number",
        (
            "longitude",
            "lon",
            "long",
            "lng",
            "gpslongitude",
            "gpslon",
            "gpslong",
            "geometrylongitude",
        ),
    ),
    MappableField(
        "altitude_m",
        "Altitude (m)",
        "number",
        ("altitudem", "altitude", "alt", "elevation", "gpsaltitude", "geometryaltitude"),
    ),
    MappableField(
        "position_accuracy_m",
        "Position accuracy (m)",
        "number",
        ("positionaccuracym", "positionaccuracy", "gpsaccuracy", "accuracy", "hdop", "gpserror"),
    ),
    MappableField("notes", "Notes", "text", ("notes", "note", "comment", "remarks", "description")),
)

FIELDS_BY_NAME: dict[str, MappableField] = {field.name: field for field in MAPPABLE_FIELDS}

_BRACKETED = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_NOT_ALPHANUMERIC = re.compile(r"[^a-z0-9]")


def column_key(column: str) -> str:
    """Reduce a column name to lower-case letters and digits for comparison.

    Bracketed parts, which usually hold a unit, are ignored:
    ``"RSSI (dBm)"`` and ``"rssi"`` give the same key.
    """
    lowered = column.lower()
    return _NOT_ALPHANUMERIC.sub("", _BRACKETED.sub("", lowered)) or _NOT_ALPHANUMERIC.sub(
        "", lowered
    )


def ambiguous_columns(columns: Sequence[str]) -> tuple[str, ...]:
    """Columns that must not be auto-mapped because their meaning is unclear.

    Example: ``channel`` could be ARFCN, UARFCN or EARFCN.
    """
    return tuple(
        column
        for column in columns
        if column_key(column) in _AMBIGUOUS_KEYS and not is_pii_column(column)
    )


def suggest_mappings(columns: Sequence[str]) -> list[MappingSuggestion]:
    """Suggest mappings with confidence scores.

    Quarantined personal-identifier columns and ambiguous columns are never
    suggested. A column is assigned to at most one field.
    """
    usable = [column for column in columns if not is_pii_column(column)]
    blocked = {column_key(column) for column in ambiguous_columns(usable)}
    columns_by_key: dict[str, str] = {}
    for column in usable:
        key = column_key(column)
        if key not in blocked:
            columns_by_key.setdefault(key, column)

    suggestions: list[MappingSuggestion] = []
    used_columns: set[str] = set()
    for field in MAPPABLE_FIELDS:
        candidates = (field.name, *field.aliases)
        for index, alias in enumerate(candidates):
            column = columns_by_key.get(column_key(alias))
            if column is None or column in used_columns:
                continue
            confidence, reason = _confidence(field.name, alias, index)
            suggestions.append(
                MappingSuggestion(field.name, column, confidence, reason)
            )
            used_columns.add(column)
            break
    return suggestions


def suggest_mapping(columns: Sequence[str]) -> dict[str, str]:
    """Suggest a ``{field name: source column}`` mapping from the column names."""
    return {item.field: item.column for item in suggest_mappings(columns)}


def validate_mapping(mapping: Mapping[str, str], columns: Sequence[str]) -> None:
    """Check that a mapping can be applied to a table with the given columns.

    Raises:
        ValueError: the mapping is empty, refers to an unknown field or column,
            or tries to map a quarantined personal-identifier column.
    """
    if not mapping:
        raise ValueError("Map at least one column to a field.")
    for name, column in mapping.items():
        if name not in FIELDS_BY_NAME:
            raise ValueError(f"Unknown field: {name}")
        if column not in columns:
            raise ValueError(f"The file has no column named {column!r}.")
        if is_pii_column(column):
            raise ValueError(
                f"Column {column!r} looks like a personal or subscriber identifier "
                "and cannot be imported into the survey database."
            )


def _confidence(field_name: str, alias: str, alias_index: int) -> tuple[float, str]:
    key = column_key(alias)
    if key == column_key(field_name) or alias_index == 0:
        return 1.0, "Exact field-name match"
    if key in _WEAK_ALIASES:
        return 0.55, f"Weak alias match ({alias})"
    if alias_index <= 2:
        return 0.9, f"Strong alias match ({alias})"
    return 0.75, f"Alias match ({alias})"
