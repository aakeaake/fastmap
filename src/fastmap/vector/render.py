"""Entry point: draw the vector map for an extent into a ReportLab canvas."""

from __future__ import annotations

from collections import defaultdict

from reportlab.pdfgen.canvas import Canvas

from fastmap.services.print_layout import Extent

from .draw import MapFrame, background_color, draw_fill_line_layers
from .geometry import clip_features, merge_by_mtk_id, simplify_features
from .labels import collect_candidates, place
from .labels import draw as draw_labels
from .model import Feature
from .profiles import PROFILES
from .style import Style, StyleLayer, evaluation_cache, scale_to_zoom, style_for
from .symbols import Symbols, draw_icon_layers
from .tiles import FeatureFilter, load_tiles, tile_size_m

CLIP_BUFFER_FRACTION = 0.02
# Largest shape change from vertex simplification, in mm on paper: well below
# a 600 dpi printer dot (0.042 mm), so the print looks the same.
SIMPLIFY_MM = 0.02


def feature_filter(style: Style, zoom: float) -> FeatureFilter:
    """Whether any style layer visible at ``zoom`` would draw a tile feature."""
    by_source: dict[str, list[StyleLayer]] = defaultdict(list)
    for layer in style.layers:
        if layer.source_layer and layer.visible_at(zoom):
            by_source[layer.source_layer].append(layer)
    return FeatureFilter(dict(by_source), zoom)


def _prepared_features(
    extent: Extent, level: int, keep: FeatureFilter, buffer_m: float, tolerance_m: float
) -> list[Feature]:
    """The drawn tile features around ``extent``: joined across tiles, clipped, simplified."""
    features = load_tiles(extent.buffered(buffer_m), level, keep)
    features = simplify_features(features, tolerance_m, "LineString")  # before joining: cheaper
    features = merge_by_mtk_id(features)
    features = clip_features(features, extent, buffer_m)
    return simplify_features(features, tolerance_m, "Polygon")  # after: cut edges stay exact


def render_vector_map(
    c: Canvas,
    extent: Extent,
    rect: tuple[float, float, float, float],
    scale: int,
) -> None:
    """Draw the map for ``extent`` into ``rect`` = (x, y, w, h) in pt, clipped to it."""
    try:
        profile = PROFILES[scale]
    except KeyError:
        raise ValueError("Vector map supports 1:25 000 and 1:50 000 only") from None
    with evaluation_cache():  # style results shared by features; one zoom per render
        style = style_for(profile)
        northing = (extent.miny + extent.maxy) / 2
        zoom = scale_to_zoom(scale, northing) + profile.zoom_offset

        buffer_m = CLIP_BUFFER_FRACTION * extent.width_m
        tolerance_m = SIMPLIFY_MM / 1000 * scale
        keep = feature_filter(style, zoom)
        features = _prepared_features(extent, profile.tile_level, keep, buffer_m, tolerance_m)
        by_layer: dict[str, list[Feature]] = defaultdict(list)
        for f in features:
            by_layer[f.layer].append(f)

        x, y, w, h = rect
        frame = MapFrame(extent, x, y, w, h)
        c.saveState()
        clip = c.beginPath()
        clip.rect(x, y, w, h)
        c.clipPath(clip, stroke=0, fill=0)
        r, g, b, a = background_color(style, zoom)
        c.setFillColorRGB(1, 1, 1)
        c.rect(x, y, w, h, stroke=0, fill=1)
        if a > 0:
            c.setFillColorRGB(r, g, b)
            c.setFillAlpha(a)
            c.rect(x, y, w, h, stroke=0, fill=1)
            c.setFillAlpha(1)
        symbols = Symbols()
        tile_m = tile_size_m(profile.tile_level)
        draw_fill_line_layers(c, frame, style, by_layer, zoom, profile.px_mm, symbols, tile_m)
        draw_icon_layers(c, frame, style, by_layer, zoom, profile.px_mm, symbols)
        candidates = collect_candidates(
            style, by_layer, zoom, frame, profile.px_mm, profile.text_scale, profile.halo_scale
        )
        draw_labels(c, place(candidates, frame))
        c.restoreState()
