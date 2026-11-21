"""Style model: MapLibre-style layers, scale-to-zoom, and override handling."""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from .colors import parse_color
from .expressions import (
    EvalContext,
    StyleError,
    evaluate_property,
    validate,
    validate_property,
)
from .profiles import ScaleProfile

DEFAULT_STYLE_PATH = Path(__file__).resolve().parent / "styles" / "maastokartta.json"


def approx_latitude(northing: float) -> float:
    """EPSG:3067 northing to degrees latitude (approximate, Finland)."""
    return northing / 110_860


def scale_to_zoom(scale: int, northing: float) -> float:
    lat = math.radians(approx_latitude(northing))
    return math.log2(156543.034 * math.cos(lat) / (scale * 0.00028))


@dataclass
class StyleLayer:
    id: str
    type: str
    source_layer: str | None
    minzoom: float
    maxzoom: float
    filter: Any
    paint: dict = field(default_factory=dict)
    layout: dict = field(default_factory=dict)

    def visible_at(self, zoom: float) -> bool:
        return self.minzoom <= zoom < self.maxzoom and self.layout.get("visibility") != "none"

    def get(self, prop: str, ctx: EvalContext, default: Any = None) -> Any:
        """Evaluated property; the default if it is absent, None or fails to evaluate.

        MapLibre falls back to the property default when a feature's data breaks an
        expression, so one bad feature never fails the map.
        """
        for section in (self.paint, self.layout):
            if prop in section:
                try:
                    value = evaluate_property(prop, section[prop], ctx)
                except (StyleError, TypeError, ValueError):
                    return default
                return default if value is None else value
        return default

    def number(self, prop: str, ctx: EvalContext, default: float) -> float:
        value = self.get(prop, ctx, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def color(self, prop: str, ctx: EvalContext, default: str) -> tuple:
        try:
            return parse_color(self.get(prop, ctx, default))
        except ValueError:
            return parse_color(default)


@dataclass
class Style:
    layers: list[StyleLayer]


def _validate_layer(layer: StyleLayer) -> None:
    try:
        validate(layer.filter)
        for section in (layer.paint, layer.layout):
            for key, value in section.items():
                validate_property(key, value)
    except StyleError as exc:
        raise StyleError(f"layer {layer.id!r}: {exc}") from exc


def _scaled(value: Any, factor: float) -> Any:
    """A paint value multiplied by ``factor``: number, legacy stops or expression."""
    if isinstance(value, (int, float)):
        return value * factor
    if isinstance(value, dict) and "stops" in value:
        return {**value, "stops": [[z, v * factor] for z, v in value["stops"]]}
    return ["*", factor, copy.deepcopy(value)]


def _apply_overrides(layers: list[StyleLayer], overrides: dict) -> None:
    by_id = {layer.id: layer for layer in layers}
    for layer_id, ov in overrides.items():
        layer = by_id.get(layer_id)
        if layer is None:
            raise StyleError(f"override for unknown layer {layer_id!r}")
        if "visibility" in ov:
            layer.layout["visibility"] = ov["visibility"]
        for key in ("minzoom", "maxzoom"):
            if key in ov:
                setattr(layer, key, ov[key])
        if "filter" in ov:  # narrows the layer: ANDed with its own filter
            extra = copy.deepcopy(ov["filter"])
            layer.filter = extra if layer.filter is None else ["all", layer.filter, extra]
        layer.paint.update(copy.deepcopy(ov.get("paint", {})))
        if "line-width-scale" in ov:  # applied after any paint override
            layer.paint["line-width"] = _scaled(
                layer.paint.get("line-width", 1), ov["line-width-scale"]
            )
        layer.layout.update(copy.deepcopy(ov.get("layout", {})))
        _validate_layer(layer)


def load_style(path: Path | None = None, overrides: dict | None = None) -> Style:
    raw = json.loads((path or DEFAULT_STYLE_PATH).read_text(encoding="utf-8"))
    layers = [
        StyleLayer(
            id=ly["id"],
            type=ly["type"],
            source_layer=ly.get("source-layer"),
            minzoom=ly.get("minzoom", 0),
            maxzoom=ly.get("maxzoom", 24),
            filter=ly.get("filter"),
            paint=dict(ly.get("paint", {})),
            layout=dict(ly.get("layout", {})),
        )
        for ly in raw["layers"]
    ]
    for layer in layers:
        _validate_layer(layer)
    _apply_overrides(layers, overrides or {})
    return Style(layers)


@cache
def _style_for_scale(scale: int) -> Style:
    from .profiles import PROFILES

    return load_style(overrides=PROFILES[scale].overrides)


def style_for(profile: ScaleProfile) -> Style:
    """Style with the profile's overrides applied (cached per scale)."""
    return _style_for_scale(profile.scale)
