from pathlib import Path

import pytest

from hass_energy.cli import main

CONFIG = """
grid:
  import_entity: sensor.grid_import
devices:
  - id: server
    entity: sensor.server_energy
"""


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


def test_generate_writes_packages(
    tmp_path: Path, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "packages"

    assert main(["generate", "--config", str(config_file), "--output", str(output)]) == 0
    assert (output / "utility_meters.yaml").exists()
    assert "written" in capsys.readouterr().out


def test_generate_is_idempotent(
    tmp_path: Path, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "packages"
    argv = ["generate", "--config", str(config_file), "--output", str(output)]
    main(argv)
    capsys.readouterr()

    assert main(argv) == 0
    assert "up to date" in capsys.readouterr().out


def test_check_fails_when_packages_are_missing(tmp_path: Path, config_file: Path) -> None:
    argv = ["generate", "--config", str(config_file), "--output", str(tmp_path / "out"), "--check"]

    assert main(argv) == 1


def test_check_succeeds_when_output_matches(tmp_path: Path, config_file: Path) -> None:
    output = tmp_path / "packages"
    main(["generate", "--config", str(config_file), "--output", str(output)])

    assert main(["generate", "--config", str(config_file), "--output", str(output), "--check"]) == 0


def test_validate_accepts_a_good_configuration(
    config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["validate", "--config", str(config_file)]) == 0
    assert "valid" in capsys.readouterr().out


def test_missing_configuration_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["validate", "--config", str(tmp_path / "absent.yaml")]) == 1
    assert "not found" in capsys.readouterr().err


def test_incomplete_configuration_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("project_name: home\n", encoding="utf-8")

    assert main(["validate", "--config", str(path)]) == 1
    assert "grid.import_entity is required" in capsys.readouterr().err
