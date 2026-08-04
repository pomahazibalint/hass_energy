"""The versions describing a release have to agree.

Checked here as well as in the workflow, so bumping one and forgetting the
other fails during the same test run rather than at release time.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from check_version import (  # noqa: E402
    disagreements,
    manifest_version,
    normalise,
    project_version,
)


def test_the_manifest_and_the_project_agree() -> None:
    assert disagreements() == [], (
        f"manifest {manifest_version()} vs pyproject {project_version()}"
    )


def test_a_matching_tag_is_accepted() -> None:
    assert disagreements(f"v{manifest_version()}") == []
    assert disagreements(manifest_version()) == []


def test_a_tag_that_moved_without_the_manifest_is_caught() -> None:
    """The failure this exists for: HACS would offer an endless update."""

    problems = disagreements("v99.0.0")

    assert len(problems) == 1
    assert "never applies" in problems[0]


def test_the_conventional_prefix_is_not_part_of_the_version() -> None:
    assert normalise("v1.2.3") == "1.2.3"
    assert normalise("1.2.3") == "1.2.3"
