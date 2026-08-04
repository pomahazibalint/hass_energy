"""The vendored engine has to stay in step with the original.

Checked here as well as in the workflow so that editing the wrong copy fails
during the same test run that the edit was made for, rather than on push.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from vendor_billing import SOURCE, TARGET, check, expected  # noqa: E402


def test_the_vendored_engine_is_current() -> None:
    stale = check()

    assert stale == [], (
        f"Vendored engine is out of step with {SOURCE.relative_to(ROOT)}: "
        f"{', '.join(stale)}. Run: python scripts/vendor_billing.py"
    )


def test_every_engine_module_is_vendored() -> None:
    originals = {path.name for path in SOURCE.glob("*.py")}
    copies = {path.name for path in TARGET.glob("*.py")}

    assert originals == copies


def test_the_copy_says_it_is_one() -> None:
    """A file people will open expecting to be able to edit."""

    for name, content in expected().items():
        assert content.startswith("# Vendored copy. Do not edit"), name


def test_the_copy_keeps_the_module_docstring() -> None:
    """A comment before the docstring leaves it the first statement."""

    import ast

    for name, content in expected().items():
        assert ast.get_docstring(ast.parse(content)) is not None, name
