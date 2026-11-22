"""Style model: MapLibre-style layers, scale-to-zoom, and override handling."""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from .colors import parse_color
from .expressions import (
    EvalContext,
    StyleError,
    evaluate_property,
    filter_matches,
    is_legacy,
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


_TOKEN = re.compile(r"\{([^{}]+)\}")
_WHOLE_FEATURE_OPS = frozenset({"properties", "feature-state", "id", "accumulated"})
_FAILED = object()  # an evaluation that raised (cached like any result)
_ABSENT = object()  # an attribute the feature lacks (unlike one that is None)

# Evaluation results of the render in progress; None outside ``evaluation_cache``.
_RENDER_MEMO: ContextVar[dict | None] = ContextVar("fastmap_style_memo", default=None)


@contextmanager
def evaluation_cache() -> Iterator[dict]:
    """Share style evaluations between features for the duration of one render.

    Features with the same values for the attributes an expression reads share
    one result (most share their class and nothing else). The cache key leaves
    out the zoom, which is fixed within a render: callers must not evaluate at
    different zooms inside one ``evaluation_cache()``. Outside it, ``StyleLayer``
    evaluates uncached. Yields the memo dict (for tests).
    """
    memo: dict = {}
    token = _RENDER_MEMO.set(memo)
    try:
        yield memo
    finally:
        _RENDER_MEMO.reset(token)


def _evaluate(prop: str, raw: Any, ctx: EvalContext) -> Any:
    """The evaluated property, or ``_FAILED`` when the feature's data breaks it."""
    try:
        return evaluate_property(prop, raw, ctx)
    except (StyleError, TypeError, ValueError):
        return _FAILED


def _names_in(expr: Any) -> tuple[str, ...] | None:
    """The feature attributes ``expr`` reads, or None if that can't be known.

    Attributes are read by ``get`` / ``has`` / ``!has``, by legacy filters
    (``["==", "key", value]``), by ``{token}`` strings and by the ``property`` of a
    legacy stops function. A computed key or a whole-feature operator makes the
    set unknowable; such expressions are not cached.
    """
    names: set[str] = set()

    def walk(e: Any) -> bool:
        if isinstance(e, str):
            names.update(_TOKEN.findall(e))
        elif isinstance(e, dict):
            if isinstance(e.get("property"), str):
                names.add(e["property"])
            return all(walk(x) for x in e.values())
        elif isinstance(e, (list, tuple)) and e:
            op = e[0] if isinstance(e[0], str) else None
            if op in _WHOLE_FEATURE_OPS:
                return False
            if op in ("get", "has", "!has") and len(e) > 1:
                if not isinstance(e[1], str):
                    return False
                names.add(e[1])
            elif op is not None and is_legacy(e):
                names.add(e[1])
            return all(walk(x) for x in e)
        return True

    return tuple(sorted(names)) if walk(expr) else None


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
    # The attributes each expression reads (static analysis, one entry per property).
    _names: dict = field(default_factory=dict, init=False, repr=False, compare=False)

    def visible_at(self, zoom: float) -> bool:
        return self.minzoom <= zoom < self.maxzoom and self.layout.get("visibility") != "none"

    def _memo_slot(self, what: str, expr: Any, ctx: EvalContext) -> tuple[dict | None, Any]:
        """(render memo, key) for caching ``expr`` on this feature; (None, None) if not."""
        memo = _RENDER_MEMO.get()
        if memo is None:
            return None, None
        try:
            names = self._names[what]
        except KeyError:
            names = self._names[what] = _names_in(expr)
        if names is None:
            return None, None
        props = ctx.props
        key = (id(self), what, ctx.geom_type, tuple(props.get(n, _ABSENT) for n in names))
        try:
            hash(key)
        except TypeError:  # an unhashable attribute value: evaluate uncached
            return None, None
        return memo, key

    def matches(self, ctx: EvalContext) -> bool:
        """Whether a feature passes this layer's filter (cached within a render)."""
        if self.filter is None:
            return True
        memo, key = self._memo_slot("$filter", self.filter, ctx)
        if memo is None:
            return filter_matches(self.filter, ctx)
        try:
            return memo[key]
        except KeyError:
            value = memo[key] = filter_matches(self.filter, ctx)
            return value

    def get(self, prop: str, ctx: EvalContext, default: Any = None) -> Any:
        """Evaluated property; the default if it is absent, None or fails to evaluate.

        MapLibre falls back to the property default when a feature's data breaks an
        expression, so one bad feature never fails the map. Cached within a render.
        """
        for section in (self.paint, self.layout):
            if prop in section:
                raw = section[prop]
                memo, key = self._memo_slot(prop, raw, ctx)
                if memo is None:
                    value = _evaluate(prop, raw, ctx)
                else:
                    try:
                        value = memo[key]
                    except KeyError:
                        value = memo[key] = _evaluate(prop, raw, ctx)
                return default if value is None or value is _FAILED else value
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


_ARITH = {"*": lambda a, b: a * b, "+": lambda a, b: a + b}


def _adjusted(value: Any, op: str, n: float) -> Any:
    """A paint value combined with ``n`` (``op`` is "*" or "+"): number, stops or expression."""
    fn = _ARITH[op]
    if isinstance(value, (int, float)):
        return fn(value, n)
    if isinstance(value, dict) and "stops" in value:
        return {**value, "stops": [[z, fn(v, n)] for z, v in value["stops"]]}
    return [op, copy.deepcopy(value), n]


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
        # width adjustments apply after any paint override: scale, then add (px)
        for key, op in (("line-width-scale", "*"), ("line-width-add", "+")):
            if key in ov:
                layer.paint["line-width"] = _adjusted(layer.paint.get("line-width", 1), op, ov[key])
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
