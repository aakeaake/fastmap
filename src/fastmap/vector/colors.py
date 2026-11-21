"""Parse CSS colour strings used by the MapLibre style."""

from __future__ import annotations

import colorsys
import re
from functools import lru_cache

_NAMES = {
    "black": "#000000",
    "white": "#ffffff",
    "red": "#ff0000",
    "green": "#008000",
    "blue": "#0000ff",
    "yellow": "#ffff00",
    "cyan": "#00ffff",
    "magenta": "#ff00ff",
    "gray": "#808080",
    "grey": "#808080",
    "orange": "#ffa500",
    "brown": "#a52a2a",
    "transparent": "rgba(0, 0, 0, 0)",
}

_FUNC = re.compile(r"^(rgba?|hsla?)\(\s*([^)]*)\)$")


def _channel(part: str, full: float) -> float:
    part = part.strip()
    if part.endswith("%"):
        return float(part[:-1]) / 100
    return float(part) / full


def _clamp(v: float) -> float:
    return min(1.0, max(0.0, v))


@lru_cache(maxsize=1024)
def parse_color(value: str) -> tuple[float, float, float, float]:
    """CSS colour -> (r, g, b, a), each 0-1. Raises ValueError if unparseable."""
    if not isinstance(value, str):
        raise ValueError(f"not a colour: {value!r}")
    s = value.strip().lower()
    s = _NAMES.get(s, s)
    try:
        if s.startswith("#"):
            h = s[1:]
            if len(h) in (3, 4):
                h = "".join(ch * 2 for ch in h)
            if len(h) not in (6, 8):
                raise ValueError
            vals = [int(h[i : i + 2], 16) / 255 for i in range(0, len(h), 2)]
            return (vals[0], vals[1], vals[2], vals[3] if len(vals) == 4 else 1.0)
        m = _FUNC.match(s)
        if m is None:
            raise ValueError
        func, args = m.group(1), [a for a in m.group(2).split(",")]
        if len(args) not in (3, 4):
            raise ValueError
        alpha = _clamp(_channel(args[3], 1.0)) if len(args) == 4 else 1.0
        if func.startswith("rgb"):
            r, g, b = (_clamp(_channel(a, 255.0)) for a in args[:3])
        else:
            hue = (float(args[0].strip().removesuffix("deg")) % 360) / 360
            sat = _clamp(_channel(args[1], 100.0))
            light = _clamp(_channel(args[2], 100.0))
            r, g, b = colorsys.hls_to_rgb(hue, light, sat)
        return (r, g, b, alpha)
    except ValueError:
        raise ValueError(f"unsupported colour {value!r}") from None
