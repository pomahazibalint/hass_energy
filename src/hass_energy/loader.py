"""YAML configuration loading."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .config import ProjectConfig


class ConfigurationError(ValueError):
    """Raised when the project configuration cannot be loaded."""


def load_config(path: str | Path) -> ProjectConfig:
    """Load and validate a project configuration from YAML.

    Every failure mode surfaces as :class:`ConfigurationError` so that callers
    report configuration problems without knowing which library rejected the
    input.
    """

    config_path = Path(path)
    if not config_path.exists():
        raise ConfigurationError(f"Configuration file not found: {config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ConfigurationError(f"Configuration file is not valid YAML: {config_path}") from error

    if raw is None:
        raise ConfigurationError(f"Configuration file is empty: {config_path}")
    if not isinstance(raw, dict):
        raise ConfigurationError("Top-level configuration must be a mapping.")

    try:
        return ProjectConfig.model_validate(raw)
    except ValidationError as error:
        raise ConfigurationError(f"Invalid configuration in {config_path}:\n{error}") from error
