from __future__ import annotations

from pathlib import Path

import pytest

from cellsurvey.config import AppConfig, AppPaths, ConfigError, load_config, save_config


def test_home_override_places_everything_under_one_directory(tmp_path: Path) -> None:
    paths = AppPaths.resolve({"CELLSURVEY_HOME": str(tmp_path)})

    assert paths.config_file == tmp_path / "config" / "config.json"
    assert paths.data_dir == tmp_path / "data"
    assert paths.log_file == tmp_path / "logs" / "cellsurvey.log"


def test_xdg_directories_are_used(tmp_path: Path) -> None:
    paths = AppPaths.resolve(
        {
            "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_STATE_HOME": str(tmp_path / "state"),
        }
    )

    assert paths.config_dir == tmp_path / "cfg" / "cellsurvey"
    assert paths.data_dir == tmp_path / "data" / "cellsurvey"
    assert paths.log_dir == tmp_path / "state" / "cellsurvey" / "logs"


def test_relative_xdg_value_falls_back_to_home_default() -> None:
    paths = AppPaths.resolve({"XDG_CONFIG_HOME": "relative/dir"})

    assert paths.config_dir == Path.home() / ".config" / "cellsurvey"


def test_missing_file_yields_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path / "absent.json") == AppConfig()


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "config.json"
    config = AppConfig(log_level="DEBUG", window_width=1600, window_height=900)

    save_config(config, path)

    assert load_config(path) == config


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        '{"log_level": "LOUD"}',
        '{"window_width": 10}',
        '{"log_levle": "DEBUG"}',
    ],
    ids=["malformed", "bad-level", "too-small", "unknown-key"],
)
def test_invalid_file_raises_config_error(tmp_path: Path, content: str) -> None:
    path = tmp_path / "config.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(path)
