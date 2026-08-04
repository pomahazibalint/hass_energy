"""The contract every package generator implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from ..config import ProjectConfig
from .rendering import render_package


class GenerationError(RuntimeError):
    """Raised when a configuration cannot produce a usable package."""


@dataclass(frozen=True)
class GeneratedFile:
    """One rendered package file, not yet written to disk."""

    filename: str
    content: str


class Generator(ABC):
    """Turns a project configuration into a single Home Assistant package.

    Subclasses describe *what* the package contains; rendering, the generated
    file header and file naming are handled here so that every generated file
    looks the same.
    """

    filename: ClassVar[str]
    description: ClassVar[str]

    def applies_to(self, config: ProjectConfig) -> bool:
        """Whether this package has anything to contribute.

        Only for genuinely optional output, such as solar sensors for a
        household without panels. A generator whose required inputs are missing
        raises :class:`GenerationError` from :meth:`build` instead of quietly
        producing nothing.
        """

        return True

    @abstractmethod
    def build(self, config: ProjectConfig) -> dict[str, Any]:
        """Build the package as plain data."""

    def generate(self, config: ProjectConfig) -> GeneratedFile:
        """Render this package for the given configuration."""

        return GeneratedFile(self.filename, render_package(self.description, self.build(config)))
