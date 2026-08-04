"""Home Assistant energy accounting.

Deliberately empty of imports. ``hass_energy.billing`` depends on nothing
outside the standard library, and re-exporting the generator's models here
would make every consumer of the settlement engine install pydantic and a YAML
parser to get at it.
"""

from __future__ import annotations
