"""Definition of the main navigation pages, in sidebar order."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageSpec:
    """Static description of one navigation page."""

    key: str
    """Stable identifier used in code and logs."""
    title: str
    summary: str
    milestone: int | None = None
    """Milestone that implements the page; ``None`` if not yet scheduled."""
    planned: tuple[str, ...] = ()
    """Capabilities the page will provide once implemented."""


PAGE_SPECS: tuple[PageSpec, ...] = (
    PageSpec(
        key="dashboard",
        title="Dashboard",
        summary="Receiver, survey and measurement status at a glance.",
        milestone=1,
    ),
    PageSpec(
        key="receivers",
        title="Receiver Manager",
        summary="Detect, identify and connect measurement receivers.",
        milestone=2,
    ),
    PageSpec(
        key="network",
        title="Network Information",
        summary="Operator and serving-cell details reported by the receiver.",
        milestone=3,
        planned=(
            "Operator name, MCC and MNC",
            "Serving-cell identity with LAC (GSM/UMTS) or TAC (LTE)",
            "Channel number (ARFCN, UARFCN, EARFCN) where the receiver exposes it",
        ),
    ),
    PageSpec(
        key="live",
        title="Live Measurements",
        summary="Current measurements for serving and neighbouring cells.",
        milestone=3,
        planned=(
            "GSM: RSSI",
            "UMTS/WCDMA: PSC, RSCP, Ec/No",
            "LTE: PCI, RSRP, RSRQ, RSSNR/SINR",
            "Provenance and confidence for every value; unavailable values shown as null",
        ),
    ),
    PageSpec(
        key="survey",
        title="Survey Manager",
        summary="Record named survey sessions from a live receiver.",
        milestone=4,
        planned=(
            "Start, stop, pause and resume a survey",
            "Session names and metadata",
            "Collection status with GPS position association",
        ),
    ),
    PageSpec(
        key="import",
        title="Import Survey",
        summary="Import historical survey files into the standard measurement schema.",
        milestone=2,
    ),
    PageSpec(
        key="explorer",
        title="Survey Explorer",
        summary="Browse, inspect and export imported survey datasets.",
        milestone=2,
    ),
    PageSpec(
        key="graphs",
        title="Signal Graphs",
        summary="Time-series plots and statistics of signal strength and quality.",
        milestone=5,
        planned=(
            "Live signal-strength and signal-quality graphs",
            "Statistics and measurement comparison",
            "Missing-data analysis (missing values are never treated as zero)",
        ),
    ),
    PageSpec(
        key="map",
        title="Geographic Map",
        summary="Survey routes and measurement points on OpenStreetMap.",
        milestone=5,
        planned=(
            "Survey locations and routes",
            "Measurement points with signal-strength observations",
            "Technology-specific layers",
        ),
    ),
    PageSpec(
        key="reports",
        title="Reports",
        summary="Export survey data and generate summaries.",
        milestone=6,
        planned=(
            "CSV, JSON and GeoJSON exports",
            "PDF survey summaries and statistical reports",
        ),
    ),
    PageSpec(
        key="settings",
        title="Settings",
        summary="Application configuration.",
        planned=(
            "Log level and window size (currently set in the configuration file)",
            "Acquisition and storage options as later milestones introduce them",
        ),
    ),
)
