"""YAML configuration loading for hass_energy."""

from __future__ import annotations

from pathlib import Path

import yaml

from .config import ProjectConfig


class ConfigurationError(ValueError):
    """Raised when the project configuration cannot be loaded."""


def load_config(path: str | Path) -> ProjectConfig:
    """Load a project configuration from YAML."""

    config_path = Path(path)
    if not config_path.exists():
        raise ConfigurationError(f"Configuration file not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if raw is None:
        raise ConfigurationError(f"Configuration file is empty: {config_path}")
    if not isinstance(raw, dict):
        raise ConfigurationError("Top-level configuration must be a mapping.")

    return ProjectConfig.model_validate(raw)
