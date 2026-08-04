"""Copy the settlement engine into the integration.

The integration has to be self-contained: Home Assistant installs a custom
component by copying one directory, and anything it declares in
``manifest.json`` requirements is pip-installed at setup, which is a network
round-trip and a way for the integration to fail to load at all.

So the engine is vendored, and the copy is an artifact in exactly the sense the
generated packages are: source of truth in ``src``, copy in git so it ships,
and a check that they have not drifted apart.

    python scripts/vendor_billing.py           # refresh the copy
    python scripts/vendor_billing.py --check   # fail if it is stale
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src" / "hass_energy" / "billing"
TARGET = ROOT / "custom_components" / "hass_energy" / "billing"

HEADER = """\
# Vendored copy. Do not edit: edits are lost the next time the engine is
# copied. The original is src/hass_energy/billing/{name}, and
# scripts/vendor_billing.py keeps this in step with it.
"""


def vendored(path: Path) -> str:
    """What the copy of one engine module should contain."""

    # A comment before the docstring leaves it the first statement, so the
    # module docstring survives being labelled.
    return HEADER.format(name=path.name) + path.read_text(encoding="utf-8")


def expected() -> dict[str, str]:
    return {path.name: vendored(path) for path in sorted(SOURCE.glob("*.py"))}


def check() -> list[str]:
    """Names of vendored files that are missing, stale or no longer wanted."""

    wanted = expected()
    problems = [
        name
        for name, content in wanted.items()
        if not (TARGET / name).exists()
        or (TARGET / name).read_text(encoding="utf-8") != content
    ]
    problems += [
        path.name for path in sorted(TARGET.glob("*.py")) if path.name not in wanted
    ]
    return sorted(set(problems))


def write() -> list[str]:
    """Refresh the copy, returning what changed."""

    TARGET.mkdir(parents=True, exist_ok=True)
    wanted = expected()
    changed = []
    for name, content in wanted.items():
        path = TARGET / name
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
            changed.append(name)
    for path in sorted(TARGET.glob("*.py")):
        if path.name not in wanted:
            path.unlink()
            changed.append(path.name)
    return changed


def main(argv: list[str]) -> int:
    if "--check" in argv:
        stale = check()
        if stale:
            print(
                "The vendored engine is out of step with src/hass_energy/billing:\n  "
                + "\n  ".join(stale)
                + "\nRun: python scripts/vendor_billing.py",
                file=sys.stderr,
            )
            return 1
        print(f"vendored engine is up to date ({len(expected())} files)")
        return 0

    changed = write()
    print(f"updated: {', '.join(changed)}" if changed else "already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
