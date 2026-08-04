"""Command-line entry point for hass_energy."""

from __future__ import annotations

from pathlib import Path

from .config import load_config


def main() -> None:
    """Run the command-line interface."""

    config_path = Path("config.yaml")
    config = load_config(config_path)
    print(config.model_dump_json(indent=2))
