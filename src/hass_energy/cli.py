"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .generator import GenerationError, generate
from .loader import ConfigurationError, load_config
from .output import WriteResult, check_files, write_files

DEFAULT_CONFIG = Path("config.yaml")
DEFAULT_OUTPUT = Path("packages")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""

    parser = argparse.ArgumentParser(
        prog="hass-energy",
        description="Generate Home Assistant energy accounting packages.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    generate_command = subcommands.add_parser(
        "generate", help="write Home Assistant packages from a configuration"
    )
    generate_command.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG, help="project configuration (YAML)"
    )
    generate_command.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="directory to write packages into"
    )
    generate_command.add_argument(
        "--check",
        action="store_true",
        help="report whether the packages are up to date instead of writing them",
    )

    validate_command = subcommands.add_parser(
        "validate", help="check that a configuration loads and can be generated"
    )
    validate_command.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    return parser


def _report(result: WriteResult, output: Path, checking: bool) -> None:
    verb = "would be written" if checking else "written"
    for path in result.written:
        print(f"{verb}: {path}")
    for path in result.removed:
        print(f"{'would be removed' if checking else 'removed'}: {path}")
    if not result.changed:
        print(f"up to date: {len(result.unchanged)} package(s) in {output}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return a process exit code."""

    args = build_parser().parse_args(argv)

    try:
        config = load_config(args.config)
        files = generate(config)
    except (ConfigurationError, GenerationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.command == "validate":
        print(f"{args.config}: valid, {len(files)} package(s) would be generated")
        return 0

    checking: bool = args.check
    result = check_files(files, args.output) if checking else write_files(files, args.output)
    _report(result, args.output, checking)

    # A drifted output directory fails the check so that continuous integration
    # catches packages committed without regenerating.
    return 1 if checking and result.changed else 0
