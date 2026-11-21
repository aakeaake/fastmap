"""Evaluator for the MapLibre style-expression subset used by the converted style.

Supports expression syntax, legacy filter syntax and legacy ``{"stops": ...}``
zoom functions. Colour strings are returned as-is.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


class StyleError(ValueError):
    """Raised for unknown operators or malformed style expressions."""


@dataclass(frozen=True)
class EvalContext:
    props: Mapping[str, Any]
    zoom: float
    geom_type: str  # "Point" | "LineString" | "Polygon"


# Operators whose bare-string second element marks the legacy filter syntax.
_LEGACY_KEY_OPS = frozenset({"==", "!=", "<", "<=", ">", ">=", "in", "!in", "has", "!has"})
_LEGACY_ONLY_OPS = frozenset({"!in", "!has", "none"})


def _is_legacy(expr: list) -> bool:
    op = expr[0]
    return op in _LEGACY_KEY_OPS and len(expr) > 1 and isinstance(expr[1], str)


def _legacy_value(key: str, ctx: EvalContext) -> Any:
    if key == "$type":
        return ctx.geom_type
    return ctx.props.get(key)


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _compare(op: str, a: Any, b: Any) -> bool:
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if a is None or b is None:
        return False
    if _num(a) != _num(b):
        return False
    try:
        if op == "<":
            return a < b
        if op == "<=":
            return a <= b
        if op == ">":
            return a > b
        return a >= b
    except TypeError:
        return False


def _legacy(expr: list, ctx: EvalContext) -> Any:
    op, key, rest = expr[0], expr[1], expr[2:]
    val = _legacy_value(key, ctx)
    if op in ("==", "!=", "<", "<=", ">", ">="):
        return _compare(op, val, rest[0])
    if op == "in":
        return val in rest
    if op == "!in":
        return val not in rest
    if op == "has":
        return key in ctx.props
    return key not in ctx.props  # !has


def _round_half_away(x: float) -> int:
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def _to_string(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _to_number(*args: Any) -> Any:
    for v in args:
        if v is None:
            continue
        if _num(v):
            return v
        if isinstance(v, bool):
            return 1 if v else 0
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    raise StyleError("to-number: could not convert value")


def _number_format(value: Any, opts: Any) -> str:
    opts = opts if isinstance(opts, Mapping) else {}
    min_d = int(opts.get("min-fraction-digits", 0))
    max_d = int(opts.get("max-fraction-digits", max(min_d, 3)))
    q = Decimal(1).scaleb(-max_d)
    d = Decimal(repr(float(value))).quantize(q, rounding=ROUND_HALF_UP)
    text = format(d, "f")
    if "." in text:
        whole, frac = text.split(".")
        frac = frac.rstrip("0").ljust(min_d, "0")
        text = f"{whole}.{frac}" if frac else whole
    elif min_d:
        text += "." + "0" * min_d
    return text


def _interp_t(kind: Any, z: float, z0: float, z1: float) -> float:
    base = 1.0
    if isinstance(kind, list) and kind and kind[0] == "exponential":
        base = float(kind[1])
    elif not (isinstance(kind, list) and kind and kind[0] == "linear"):
        raise StyleError(f"interpolate: unsupported interpolation type {kind!r}")
    if z1 == z0:
        return 0.0
    if base == 1:
        return (z - z0) / (z1 - z0)
    return (base ** (z - z0) - 1) / (base ** (z1 - z0) - 1)


def _interpolate(kind: Any, x: Any, stops: list[tuple[Any, Any]]) -> Any:
    if not _num(x):
        raise StyleError("interpolate: input is not a number")
    if x <= stops[0][0]:
        return stops[0][1]
    if x >= stops[-1][0]:
        return stops[-1][1]
    for (z0, v0), (z1, v1) in zip(stops, stops[1:], strict=False):
        if z0 <= x <= z1:
            if not (_num(v0) and _num(v1)):
                raise StyleError("interpolate: only numeric outputs are supported")
            t = _interp_t(kind, x, z0, z1)
            return v0 + t * (v1 - v0)
    return stops[-1][1]  # pragma: no cover


def _step(x: Any, first: Any, stops: list[tuple[Any, Any]]) -> Any:
    out = first
    if not _num(x):
        return out
    for s, v in stops:
        if x >= s:
            out = v
        else:
            break
    return out


def _stops_function(fn: Mapping, ctx: EvalContext) -> Any:
    stops = [(s[0], s[1]) for s in fn["stops"]]
    if not stops:
        raise StyleError("empty stops function")
    z = ctx.zoom
    if all(_num(v) for _, v in stops):
        base = fn.get("base", 1)
        kind = ["exponential", base] if base != 1 else ["linear"]
        return _interpolate(kind, z, stops)
    return _step(z, stops[0][1], stops[1:])


# --- operator implementations (args are already-evaluated unless special) ---


def _op_get(a, ctx):
    return ctx.props.get(a[0])


def _op_has(a, ctx):
    return a[0] in ctx.props


def _op_in(a, ctx):
    needle, hay = a[0], a[1]
    if hay is None:
        return False
    if isinstance(hay, str):
        return isinstance(needle, str) and needle in hay
    return needle in hay


def _numeric(fn):
    """Arithmetic on missing/non-numeric operands yields null (so coalesce falls through)."""

    def wrapped(a, ctx):
        if not all(_num(v) for v in a):
            return None
        return fn(a, ctx)

    return wrapped


def _op_mod(a, ctx):
    return a[0] % a[1]


def _op_div(a, ctx):
    return a[0] / a[1]


def _op_mul(a, ctx):
    out = 1
    for v in a:
        out *= v
    return out


def _op_add(a, ctx):
    return sum(a)


def _op_sub(a, ctx):
    return -a[0] if len(a) == 1 else a[0] - a[1]


_EAGER: dict[str, Callable[[list, EvalContext], Any]] = {
    "get": _op_get,
    "has": _op_has,
    "==": lambda a, c: _compare("==", a[0], a[1]),
    "!=": lambda a, c: _compare("!=", a[0], a[1]),
    "<": lambda a, c: _compare("<", a[0], a[1]),
    "<=": lambda a, c: _compare("<=", a[0], a[1]),
    ">": lambda a, c: _compare(">", a[0], a[1]),
    ">=": lambda a, c: _compare(">=", a[0], a[1]),
    "in": _op_in,
    "%": _numeric(_op_mod),
    "/": _numeric(_op_div),
    "*": _numeric(_op_mul),
    "+": _numeric(_op_add),
    "-": _numeric(_op_sub),
    "floor": _numeric(lambda a, c: math.floor(a[0])),
    "round": _numeric(lambda a, c: _round_half_away(a[0])),
    "to-string": lambda a, c: _to_string(a[0]),
    "to-number": lambda a, c: _to_number(*a),
    "zoom": lambda a, c: c.zoom,
    "geometry-type": lambda a, c: c.geom_type,
}


def _eval_literal(args, ctx):
    return args[0]


def _eval_match(args, ctx):
    x = evaluate(args[0], ctx)
    rest = args[1:]
    for label, out in zip(rest[0:-1:2], rest[1:-1:2], strict=False):
        labels = label if isinstance(label, list) else [label]
        if any(x == lb for lb in labels):
            return evaluate(out, ctx)
    return evaluate(rest[-1], ctx)


def _eval_case(args, ctx):
    for cond, out in zip(args[0:-1:2], args[1:-1:2], strict=False):
        if evaluate(cond, ctx):
            return evaluate(out, ctx)
    return evaluate(args[-1], ctx)


def _eval_coalesce(args, ctx):
    for a in args:
        v = evaluate(a, ctx)
        if v is not None:
            return v
    return None


def _eval_all(args, ctx):
    return all(evaluate(a, ctx) for a in args)


def _eval_any(args, ctx):
    return any(evaluate(a, ctx) for a in args)


def _eval_none(args, ctx):
    return not any(evaluate(a, ctx) for a in args)


def _eval_not(args, ctx):
    return not evaluate(args[0], ctx)


def _eval_number_format(args, ctx):
    return _number_format(evaluate(args[0], ctx), args[1] if len(args) > 1 else {})


def _pairs(args, ctx):
    return [(evaluate(k, ctx), v) for k, v in zip(args[0::2], args[1::2], strict=False)]


def _eval_interpolate(args, ctx):
    kind, x = args[0], evaluate(args[1], ctx)
    stops = [(k, evaluate(v, ctx)) for k, v in _pairs(args[2:], ctx)]
    return _interpolate(kind, x, stops)


def _eval_step(args, ctx):
    x = evaluate(args[0], ctx)
    first = evaluate(args[1], ctx)
    stops = [(k, evaluate(v, ctx)) for k, v in _pairs(args[2:], ctx)]
    return _step(x, first, stops)


_LAZY: dict[str, Callable[[list, EvalContext], Any]] = {
    "literal": _eval_literal,
    "match": _eval_match,
    "case": _eval_case,
    "coalesce": _eval_coalesce,
    "all": _eval_all,
    "any": _eval_any,
    "none": _eval_none,
    "!": _eval_not,
    "number-format": _eval_number_format,
    "interpolate": _eval_interpolate,
    "step": _eval_step,
}

_KNOWN_OPS = frozenset(_EAGER) | frozenset(_LAZY) | _LEGACY_ONLY_OPS | _LEGACY_KEY_OPS


def evaluate(expr: Any, ctx: EvalContext) -> Any:
    """Evaluate a style value: literals pass through, lists are expressions."""
    if isinstance(expr, Mapping):
        if "stops" in expr:
            return _stops_function(expr, ctx)
        return expr
    if not isinstance(expr, list) or not expr or not isinstance(expr[0], str):
        return expr
    op = expr[0]
    if op not in _KNOWN_OPS:
        raise StyleError(f"unknown expression operator {op!r}")
    if _is_legacy(expr):
        return _legacy(expr, ctx)
    args = expr[1:]
    if op in _LAZY:
        return _LAZY[op](args, ctx)
    if op in _EAGER:
        return _EAGER[op]([evaluate(a, ctx) for a in args], ctx)
    raise StyleError(f"malformed expression for operator {op!r}")


def filter_matches(flt: Any, ctx: EvalContext) -> bool:
    if flt is None:
        return True
    return bool(evaluate(flt, ctx))


def validate(expr: Any) -> None:
    """Raise StyleError naming the first unknown operator in ``expr``."""
    if isinstance(expr, Mapping):
        for stop in expr.get("stops", []):
            validate(stop[1])
        return
    if not isinstance(expr, list) or not expr or not isinstance(expr[0], str):
        return
    op = expr[0]
    if op not in _KNOWN_OPS:
        raise StyleError(f"unknown expression operator {op!r}")
    if _is_legacy(expr) or op == "literal":
        return
    args = expr[1:]
    if op == "match":
        validate(args[0])
        rest = args[1:]
        for out in rest[1:-1:2]:
            validate(out)
        validate(rest[-1])
    elif op == "interpolate":
        validate(args[1])
        for v in args[3::2]:
            validate(v)
    elif op == "step":
        validate(args[0])
        validate(args[1])
        for v in args[3::2]:
            validate(v)
    elif op == "number-format":
        validate(args[0])
    else:
        for a in args:
            validate(a)
