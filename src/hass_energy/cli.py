"""Command-line interface."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import ProjectConfig
from .generator import GenerationError, generate, inventory
from .loader import ConfigurationError, load_config
from .output import WriteResult, check_files, write_files
from .verification import VerificationError, missing_sources

DEFAULT_CONFIG = Path("config.yaml")
DEFAULT_OUTPUT = Path("packages")

#: Read when --token is not given, so a long-lived token stays out of shell
#: history and out of the process list.
TOKEN_VARIABLE = "HASS_TOKEN"


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
    validate_command.add_argument(
        "--home-assistant",
        metavar="URL",
        help="also confirm the source entities exist in a running instance",
    )
    validate_command.add_argument(
        "--token", help=f"access token for --home-assistant (default: ${TOKEN_VARIABLE})"
    )

    return parser


def _report(result: WriteResult, output: Path, checking: bool) -> None:
    verb = "would be written" if checking else "written"
    for path in result.written:
        print(f"{verb}: {path}")
    for path in result.removed:
        print(f"{'would be removed' if checking else 'removed'}: {path}")
    if not result.changed:
        print(f"up to date: {len(result.unchanged)} package(s) in {output}")

    # Entity ids are the join between generated packages and recorded history,
    # so a disappearing one is worth more than a line in a diff.
    if result.entities_removed:
        print(
            f"\n{len(result.entities_removed)} entity id(s) are no longer generated. "
            "Home Assistant keeps their recorded history under the old id, where "
            "nothing will write to it again:",
            file=sys.stderr,
        )
        for entity in result.entities_removed:
            print(f"  gone: {entity}", file=sys.stderr)
        if result.entities_added:
            print("Replaced by:", file=sys.stderr)
            for entity in result.entities_added:
                print(f"  new:  {entity}", file=sys.stderr)
        print(
            "Delete the old entities in Settings > Devices & services > Entities, "
            "or carry their totals over with the utility_meter.calibrate action.",
            file=sys.stderr,
        )


def _verify(args: argparse.Namespace, config: ProjectConfig) -> int:
    token = args.token or os.environ.get(TOKEN_VARIABLE)
    if not token:
        print(
            f"error: --home-assistant needs an access token, via --token or ${TOKEN_VARIABLE}",
            file=sys.stderr,
        )
        return 1

    try:
        missing = missing_sources(config, args.home_assistant, token)
    except VerificationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if missing:
        print(f"{len(missing)} source entity/entities do not exist:", file=sys.stderr)
        for entity in missing:
            print(f"  missing: {entity}", file=sys.stderr)
        return 1

    print(f"{args.home_assistant}: every source entity exists")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return a process exit code."""

    args = build_parser().parse_args(argv)

    try:
        config = load_config(args.config)
        files = generate(config)
        entities = inventory(config)
    except (ConfigurationError, GenerationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.command == "validate":
        print(
            f"{args.config}: valid, {len(files)} package(s) "
            f"and {len(entities)} entities would be generated"
        )
        return _verify(args, config) if args.home_assistant else 0

    checking: bool = args.check
    result = (
        check_files(files, args.output, entities)
        if checking
        else write_files(files, args.output, entities)
    )
    _report(result, args.output, checking)

    # A drifted output directory fails the check so that continuous integration
    # catches packages committed without regenerating.
    return 1 if checking and result.changed else 0
