"""Per-scale rendering profiles for the vector map, loaded from ``styles/profiles.json``.

The values (and the reasons for them, in "note"/"notes" fields) live in the JSON file;
this module only loads and validates it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .expressions import StyleError

PROFILES_PATH = Path(__file__).resolve().parent / "styles" / "profiles.json"

_NOTE_KEYS = frozenset({"note", "notes"})
_REQUIRED = ("tile_level", "px_mm", "zoom_offset", "overrides")
_OPTIONAL = ("text_scale", "halo_scale")
_PROFILE_KEYS = frozenset(_REQUIRED + _OPTIONAL) | _NOTE_KEYS
# what style._apply_overrides understands
_OVERRIDE_KEYS = frozenset(
    {
        "visibility",
        "minzoom",
        "maxzoom",
        "filter",
        "paint",
        "layout",
        "line-width-scale",
        "line-width-add",
    }
)
_OVERRIDE_NUMBERS = ("minzoom", "maxzoom", "line-width-scale", "line-width-add")


@dataclass(frozen=True)
class ScaleProfile:
    """How the style is drawn at one print scale.

    ``px_mm`` is the paper size of one style pixel (line widths, icons, spacing);
    ``zoom_offset`` is added to the scale's style zoom; ``overrides`` are per-layer
    style overrides (see ``style._apply_overrides``). ``text_scale`` and ``halo_scale``
    multiply text sizes and halo widths on top of ``px_mm``.
    """

    scale: int
    tile_level: int
    px_mm: float
    zoom_offset: float
    overrides: dict[str, dict]
    text_scale: float = 1.0
    halo_scale: float = 1.0


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _unknown(keys: Any, allowed: frozenset[str], where: str) -> None:
    extra = sorted(set(keys) - allowed)
    if extra:
        raise StyleError(f"{where}: unknown key(s) {extra}; allowed: {sorted(allowed)}")


def _override(layer_id: str, raw: Any, where: str) -> dict:
    where = f"{where} override {layer_id!r}"
    if not isinstance(raw, dict):
        raise StyleError(f"{where}: must be an object")
    _unknown(raw, _OVERRIDE_KEYS | {"note"}, where)
    for key in _OVERRIDE_NUMBERS:
        if key in raw and not _is_number(raw[key]):
            raise StyleError(f"{where}: {key} must be a number")
    for key in ("paint", "layout"):
        if key in raw and not isinstance(raw[key], dict):
            raise StyleError(f"{where}: {key} must be an object")
    if "visibility" in raw and raw["visibility"] not in ("visible", "none"):
        raise StyleError(f"{where}: visibility must be 'visible' or 'none'")
    return {k: v for k, v in raw.items() if k != "note"}


def _profile(key: str, raw: Any) -> ScaleProfile:
    where = f"profile {key!r}"
    if not key.isdigit():
        raise StyleError(f'{where}: key must be a scale denominator, e.g. "25000"')
    if not isinstance(raw, dict):
        raise StyleError(f"{where}: must be an object")
    _unknown(raw, _PROFILE_KEYS, where)
    missing = [k for k in _REQUIRED if k not in raw]
    if missing:
        raise StyleError(f"{where}: missing {missing}")
    if not isinstance(raw["tile_level"], int) or isinstance(raw["tile_level"], bool):
        raise StyleError(f"{where}: tile_level must be an integer")
    for k in ("px_mm", "zoom_offset", *_OPTIONAL):
        if k in raw and not _is_number(raw[k]):
            raise StyleError(f"{where}: {k} must be a number")
    notes = raw.get("notes", {})
    if not isinstance(notes, dict):
        raise StyleError(f"{where}: notes must be an object")
    _unknown(notes, frozenset(_REQUIRED + _OPTIONAL), f"{where} notes")
    if not isinstance(raw["overrides"], dict):
        raise StyleError(f"{where}: overrides must be an object")
    overrides = {lid: _override(lid, ov, where) for lid, ov in raw["overrides"].items()}
    return ScaleProfile(
        int(key),
        raw["tile_level"],
        raw["px_mm"],
        raw["zoom_offset"],
        overrides,
        **{k: raw[k] for k in _OPTIONAL if k in raw},
    )


def load_profiles(path: Path = PROFILES_PATH) -> dict[int, ScaleProfile]:
    """The scale profiles in ``path``, validated (unknown keys raise :class:`StyleError`)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise StyleError(f"{path.name}: must be an object of scale profiles")
    profiles = {}
    for key, value in raw.items():
        if key in _NOTE_KEYS:
            continue
        profile = _profile(key, value)
        profiles[profile.scale] = profile
    return profiles


PROFILES: dict[int, ScaleProfile] = load_profiles()
