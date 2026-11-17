"""Detect columns that look like subscriber or personal identifiers.

Those columns are never mapped into the normalized measurement schema and are
redacted in stored source values. Aggregate survey measurements stay; subscriber
identity does not.
"""

from __future__ import annotations

import re

_BRACKETED = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_NOT_ALPHANUMERIC = re.compile(r"[^a-z0-9]")

# Exact keys after normalization.
_PII_KEYS = frozenset(
    {
        "imei",
        "imeisv",
        "imsi",
        "msisdn",
        "phone",
        "phonenumber",
        "mobilenumber",
        "subscriber",
        "subscriberid",
        "subscribernumber",
        "iccid",
        "simid",
        "androidid",
        "deviceid",
        "serialnumber",
        "deviceserial",
        "email",
        "emailaddress",
        "username",
        "personname",
        "fullname",
    }
)

_PII_FRAGMENTS = ("imei", "imsi", "msisdn", "iccid")
_DIGIT_IDENTITY = re.compile(r"^[0-9]{14,16}$")


def _key(column: str) -> str:
    lowered = column.lower()
    return _NOT_ALPHANUMERIC.sub("", _BRACKETED.sub("", lowered)) or _NOT_ALPHANUMERIC.sub(
        "", lowered
    )


def is_pii_column(column: str) -> bool:
    """Whether a source column name indicates a personal or subscriber identifier."""
    key = _key(column)
    if key in _PII_KEYS:
        return True
    return any(fragment in key for fragment in _PII_FRAGMENTS)


def quarantine_columns(columns: tuple[str, ...]) -> tuple[str, ...]:
    """Columns that must not enter the normalized survey database."""
    return tuple(column for column in columns if is_pii_column(column))


def redact_source_values(
    columns: tuple[str, ...], row: tuple[str | None, ...]
) -> dict[str, str | None]:
    """Build ``source_values`` with quarantined columns replaced by a marker."""
    values: dict[str, str | None] = {}
    for column, value in zip(columns, row, strict=True):
        if is_pii_column(column):
            values[column] = "[quarantined]" if value is not None else None
        else:
            values[column] = value
    return values


def looks_like_identity_value(text: str | None) -> bool:
    """Whether a cell looks like an IMEI/IMSI-style digit string."""
    return bool(text and _DIGIT_IDENTITY.fullmatch(text.strip()))
