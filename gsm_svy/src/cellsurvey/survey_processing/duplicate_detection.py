"""Detect duplicate measurement records.

Two records are duplicates when they have the same timestamp and every other
measured value is identical. A record without a timestamp is never treated as a
duplicate: repeated readings of the same cell at the same place are legitimate
data, and without a time there is no way to tell them from a copied row.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from cellsurvey.schema import Measurement

# Everything that identifies or describes the record rather than the measurement.
_NOT_CONTENT = frozenset(
    {
        "record_id",
        "survey_id",
        "source_filename",
        "source_format",
        "source_instrument",
        "source_software",
        "import_timestamp",
        "measurement_method",
        "source_row",
        "source_values",
    }
)


def content_hash(record: Measurement) -> str | None:
    """Fingerprint of what was measured, or ``None`` for a record without a timestamp.

    Null fields do not contribute, so the fingerprint of an existing record
    stays the same when fields are added to the schema.
    """
    if record.timestamp is None:
        return None
    content = record.model_dump(mode="json", exclude=set(_NOT_CONTENT), exclude_none=True)
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def split_duplicates(
    records: Sequence[Measurement],
) -> tuple[list[Measurement], list[str | None], list[Measurement]]:
    """Separate repeated records from the first occurrence of each.

    Returns:
        The records to keep, their content hashes in the same order, and the
        duplicates that were removed.
    """
    kept: list[Measurement] = []
    hashes: list[str | None] = []
    duplicates: list[Measurement] = []
    seen: set[str] = set()
    for record in records:
        digest = content_hash(record)
        if digest is not None and digest in seen:
            duplicates.append(record)
            continue
        if digest is not None:
            seen.add(digest)
        kept.append(record)
        hashes.append(digest)
    return kept, hashes, duplicates
