"""Application directories and user configuration.

Directories follow the XDG Base Directory specification. Setting the
``CELLSURVEY_HOME`` environment variable places everything under one
directory instead, which is useful for portable installs and for tests.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

APP_DIR_NAME = "cellsurvey"
HOME_ENV_VAR = "CELLSURVEY_HOME"

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class ConfigError(Exception):
    """The configuration file exists but cannot be read or is invalid."""


@dataclass(frozen=True)
class AppPaths:
    """Directories used by the application. Nothing is created on resolve."""

    config_dir: Path
    data_dir: Path
    log_dir: Path

    @property
    def config_file(self) -> Path:
        """User configuration file (JSON)."""
        return self.config_dir / "config.json"

    @property
    def log_file(self) -> Path:
        """Structured application log (JSON lines, rotated)."""
        return self.log_dir / "cellsurvey.log"

    @property
    def database_file(self) -> Path:
        """SQLite database of surveys and measurements."""
        return self.data_dir / "cellsurvey.sqlite3"

    @property
    def survey_sources_dir(self) -> Path:
        """Unmodified copies of imported survey files."""
        return self.data_dir / "survey_sources"

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> AppPaths:
        """Resolve directories from the environment (defaults to ``os.environ``)."""
        env = os.environ if env is None else env

        home_override = env.get(HOME_ENV_VAR)
        if home_override:
            root = Path(home_override).expanduser()
            return cls(root / "config", root / "data", root / "logs")

        def xdg(variable: str, fallback: str) -> Path:
            value = env.get(variable)
            # The XDG spec says relative paths must be ignored.
            base = Path(value) if value and Path(value).is_absolute() else Path.home() / fallback
            return base / APP_DIR_NAME

        return cls(
            config_dir=xdg("XDG_CONFIG_HOME", ".config"),
            data_dir=xdg("XDG_DATA_HOME", ".local/share"),
            log_dir=xdg("XDG_STATE_HOME", ".local/state") / "logs",
        )


class AppConfig(BaseModel):
    """User-editable application settings."""

    # Unknown keys are rejected so that a typo is reported instead of ignored.
    model_config = ConfigDict(extra="forbid")

    log_level: LogLevel = Field(default="INFO", description="Minimum severity written to the log.")
    window_width: int = Field(default=1280, ge=800, description="Initial window width, pixels.")
    window_height: int = Field(default=800, ge=600, description="Initial window height, pixels.")
    adb_path: str | None = Field(
        default=None, description="Path to the adb executable; null searches PATH."
    )


def load_config(path: Path) -> AppConfig:
    """Load configuration from ``path``; a missing file yields the defaults.

    Raises:
        ConfigError: the file exists but is unreadable, not JSON, or invalid.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return AppConfig()
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc

    try:
        return AppConfig.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ConfigError(f"Invalid configuration in {path}: {exc}") from exc


def save_config(config: AppConfig, path: Path) -> None:
    """Write ``config`` to ``path``, replacing the file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
