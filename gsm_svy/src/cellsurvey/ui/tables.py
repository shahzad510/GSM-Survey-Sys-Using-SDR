"""Shared table helpers for the desktop UI."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem


def make_table(headers: Sequence[str], *, multi_select: bool = False) -> QTableWidget:
    """Create a read-only table with stretched columns."""
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(
        QAbstractItemView.SelectionMode.ExtendedSelection
        if multi_select
        else QAbstractItemView.SelectionMode.SingleSelection
    )
    table.setAlternatingRowColors(True)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return table


def fill_table(table: QTableWidget, rows: Sequence[Sequence[object]]) -> None:
    """Replace the contents of ``table`` with ``rows``."""
    table.setRowCount(len(rows))
    for row_index, values in enumerate(rows):
        for column, value in enumerate(values):
            text = "" if value is None else str(value)
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            table.setItem(row_index, column, item)


def text_item(text: str) -> QTableWidgetItem:
    """A table cell with the given text and matching tooltip."""
    item = QTableWidgetItem(text)
    item.setToolTip(text)
    return item
