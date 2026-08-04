from pathlib import Path

import pytest

from hass_energy.config import load_config


def test_load_config_requires_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.yaml")
