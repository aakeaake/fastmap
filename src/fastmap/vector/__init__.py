"""Vector map rendering from MML open vector tiles."""

from .profiles import PROFILES
from .render import render_vector_map

VECTOR_SCALES = frozenset(PROFILES)

__all__ = ["VECTOR_SCALES", "render_vector_map"]
