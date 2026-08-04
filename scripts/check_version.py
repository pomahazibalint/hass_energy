"""Keep the version numbers that describe a release from disagreeing.

Three places carry it, and HACS reads two of them for different purposes: the
version in ``manifest.json`` is what it considers installed, and the release
tag is what it considers available. Tag a release without bumping the manifest
and HACS offers an update forever — it downloads, finds the old version still
there, and offers it again. That failure is silent and easy to cause, because
tagging feels like the whole job.

    python scripts/check_version.py              # manifest and pyproject agree
    python scripts/check_version.py --tag v0.2.0 # ...and the tag agrees too
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "custom_components" / "hass_energy" / "manifest.json"
PYPROJECT = ROOT / "pyproject.toml"


def manifest_version() -> str:
    return str(json.loads(MANIFEST.read_text(encoding="utf-8"))["version"])


def project_version() -> str:
    return str(tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"])


def normalise(tag: str) -> str:
    """A tag is conventionally prefixed, the versions it refers to are not."""

    return tag[1:] if tag.startswith("v") else tag


def disagreements(tag: str | None = None) -> list[str]:
    """Every pair that should match and does not."""

    manifest, project = manifest_version(), project_version()
    problems = []
    if manifest != project:
        problems.append(
            f"custom_components/hass_energy/manifest.json says {manifest}, "
            f"pyproject.toml says {project}"
        )
    if tag is not None and normalise(tag) != manifest:
        problems.append(
            f"tag {tag} does not match the manifest version {manifest}; "
            "HACS would offer an update that never applies"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="release tag to check against, e.g. v0.1.0")
    args = parser.parse_args(argv)

    problems = disagreements(args.tag)
    if problems:
        print("Version numbers disagree:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1

    checked = f"{manifest_version()}" + (f" and tag {args.tag}" if args.tag else "")
    print(f"versions agree: {checked}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
