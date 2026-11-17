"""Application look: Fusion style, a fixed light palette and one stylesheet.

The palette is set explicitly so the application looks the same whether the
desktop is using a light or a dark system theme.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

_TEXT = "#1f2933"
_MUTED = "#627d98"
_BORDER = "#d9e2ec"
_SURFACE = "#ffffff"
_BACKGROUND = "#f5f7fa"
_SIDEBAR = "#1f2933"
_ACCENT = "#2f80ed"

STYLESHEET = f"""
QFrame#sidebar {{ background: {_SIDEBAR}; }}
QLabel#appTitle {{ color: #ffffff; font-size: 15px; font-weight: 600; padding: 18px 16px 2px 16px; }}
QLabel#appSubtitle {{ color: #9aa5b1; font-size: 11px; padding: 0 16px 14px 16px; }}
QLabel#appVersion {{ color: #7b8794; font-size: 11px; padding: 12px 16px; }}

QListWidget#navList {{ background: {_SIDEBAR}; border: none; outline: none; }}
QListWidget#navList::item {{
    color: #cbd2d9; padding: 0 13px; border-left: 3px solid transparent;
}}
QListWidget#navList::item:hover {{ background: #2a3642; }}
QListWidget#navList::item:selected {{
    background: #323f4b; color: #ffffff; border-left: 3px solid {_ACCENT};
}}

QFrame#statusHeader {{ background: {_SURFACE}; border-bottom: 1px solid {_BORDER}; }}
QLabel#indicatorCaption, QLabel#cardCaption {{
    color: {_MUTED}; font-size: 10px; font-weight: 600; letter-spacing: 1px;
}}
QLabel#indicatorValue {{ font-size: 13px; font-weight: 600; }}
QLabel#statusDot {{ border-radius: 5px; background: #9aa5b1; }}
QLabel#statusDot[level="ok"] {{ background: #2e9e5b; }}
QLabel#statusDot[level="warn"] {{ background: #d98e04; }}

QLabel#pageTitle {{ font-size: 20px; font-weight: 600; }}
QLabel#pageSummary, QLabel#note {{ color: {_MUTED}; }}
QLabel#sectionTitle {{ font-size: 13px; font-weight: 600; }}
QLabel#badge {{
    color: {_MUTED}; background: #e4e7eb; border-radius: 3px; padding: 3px 8px; font-size: 11px;
}}

QFrame#card {{ background: {_SURFACE}; border: 1px solid {_BORDER}; border-radius: 4px; }}
QLabel#cardValue {{ font-size: 18px; font-weight: 600; }}

QTableWidget {{ background: {_SURFACE}; border: 1px solid {_BORDER}; gridline-color: {_BORDER}; }}
QHeaderView::section {{
    background: #eef1f5; color: {_MUTED}; font-weight: 600; padding: 5px 8px;
    border: none; border-bottom: 1px solid {_BORDER};
}}
"""


def _palette() -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: _BACKGROUND,
        QPalette.ColorRole.WindowText: _TEXT,
        QPalette.ColorRole.Base: _SURFACE,
        QPalette.ColorRole.AlternateBase: _BACKGROUND,
        QPalette.ColorRole.Text: _TEXT,
        QPalette.ColorRole.Button: "#e4e7eb",
        QPalette.ColorRole.ButtonText: _TEXT,
        QPalette.ColorRole.ToolTipBase: _SURFACE,
        QPalette.ColorRole.ToolTipText: _TEXT,
        QPalette.ColorRole.PlaceholderText: "#9aa5b1",
        QPalette.ColorRole.Highlight: _ACCENT,
        QPalette.ColorRole.HighlightedText: "#ffffff",
    }
    for role, colour in roles.items():
        palette.setColor(role, QColor(colour))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#9aa5b1"))
    return palette


def apply_theme(app: QApplication) -> None:
    """Apply the application style, palette and stylesheet."""
    app.setStyle("Fusion")
    app.setPalette(_palette())
    app.setStyleSheet(STYLESHEET)
