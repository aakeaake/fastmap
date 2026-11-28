"""The route overlay on a PDF page: a line, or an orienteering course, plus
named waypoints. Sizes are millimetres on paper, independent of map scale.
"""

from __future__ import annotations

from collections.abc import Sequence

from reportlab.lib.colors import Color, white
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from fastmap.services.course_geometry import (
    CONTROL_D_MM,
    DOT_D_MM,
    FINISH_CLEAR_MM,
    FINISH_D_MM,
    HALO_MM,
    LEG_GAP_MM,
    NUMBER_H_MM,
    NUMBER_OFFSET_MM,
    START_RADIUS_MM,
    START_SIDE_MM,
    WAYPOINT_NAME_H_MM,
    course_legs,
    finish_outer_radius,
    number_direction,
    start_triangle,
)
from fastmap.services.print_layout import Extent

_NUMBER_FONT = "Helvetica-Bold"
_NAME_FONT = "Helvetica"


def _halo_text(c: canvas.Canvas, x: float, y: float, text: str, *, centred: bool) -> None:
    """Text with a thin white halo under it, in the current fill colour."""
    draw = c.drawCentredString if centred else c.drawString
    c.saveState()
    c.setStrokeColor(white)
    c.setLineWidth(2 * HALO_MM * mm)
    c.setLineJoin(1)
    draw(x, y, text, mode=1)  # stroke only: the halo
    c.restoreState()
    draw(x, y, text)


def _dot(c: canvas.Canvas, x: float, y: float, width: float) -> None:
    c.circle(x, y, max(DOT_D_MM * mm, width) / 2, stroke=0, fill=1)


def _draw_course(c: canvas.Canvas, pts: list[tuple[float, float]], width: float) -> None:
    finish_r = (
        FINISH_D_MM[0] / 2 * mm,
        finish_outer_radius(
            FINISH_D_MM[0] / 2 * mm, FINISH_D_MM[1] / 2 * mm, width, FINISH_CLEAR_MM * mm
        ),
    )
    legs = course_legs(
        pts,
        START_RADIUS_MM * mm,
        CONTROL_D_MM / 2 * mm,
        finish_r[1],
        LEG_GAP_MM * mm + width / 2,  # clear of the symbol's stroke, however thick
    )
    for a, b in legs:
        c.line(a[0], a[1], b[0], b[1])

    start, finish = pts[0], pts[-1]
    tri = start_triangle(start, pts[1], START_SIDE_MM * mm)
    p = c.beginPath()
    p.moveTo(*tri[0])
    p.lineTo(*tri[1])
    p.lineTo(*tri[2])
    p.close()
    c.drawPath(p, stroke=1, fill=0)
    for r in finish_r:
        c.circle(finish[0], finish[1], r, stroke=1, fill=0)

    size = NUMBER_H_MM * mm
    c.setFont(_NUMBER_FONT, size)
    offset = (CONTROL_D_MM / 2 + NUMBER_OFFSET_MM) * mm
    for k in range(1, len(pts) - 1):
        x, y = pts[k]
        c.circle(x, y, CONTROL_D_MM / 2 * mm, stroke=1, fill=0)
        dx, dy = number_direction(pts[k - 1], pts[k], pts[k + 1])
        # drawCentredString centres horizontally; drop the baseline to centre vertically
        _halo_text(c, x + dx * offset, y + dy * offset - 0.35 * size, str(k), centred=True)

    for x, y in pts:
        _dot(c, x, y, width)


def _draw_waypoints(c: canvas.Canvas, pts: list[tuple[float, float, str]], width: float) -> None:
    size = WAYPOINT_NAME_H_MM * mm
    c.setFont(_NAME_FONT, size)
    for x, y, name in pts:
        c.circle(x, y, CONTROL_D_MM / 2 * mm, stroke=1, fill=0)
        _dot(c, x, y, width)
        if name:
            _halo_text(c, x + (CONTROL_D_MM / 2 + 1) * mm, y - 0.35 * size, name, centred=False)


def draw_route(
    c: canvas.Canvas,
    extent: Extent,
    x0: float,
    y0: float,
    w: float,
    h: float,
    *,
    routes: Sequence[Sequence[Sequence[float]]],
    look: str,
    waypoints: Sequence[dict],
    rgb: tuple[float, float, float],
    width: float,
    opacity: float,
) -> None:
    """Draw the route and waypoints into the map box (x0, y0, w, h), clipped to it."""
    ext_w = extent.maxx - extent.minx
    ext_h = extent.maxy - extent.miny
    if ext_w <= 0 or ext_h <= 0 or not (routes or waypoints):
        return

    def project(gx: float, gy: float) -> tuple[float, float]:
        return (gx - extent.minx) / ext_w * w + x0, (gy - extent.miny) / ext_h * h + y0

    c.saveState()
    clip = c.beginPath()
    clip.rect(x0, y0, w, h)
    c.clipPath(clip, stroke=0, fill=0)
    color = Color(*rgb, alpha=opacity)
    c.setStrokeColor(color)
    c.setFillColor(color)
    c.setLineWidth(width)

    if look == "course" and len(routes) == 1 and len(routes[0]) >= 2:
        _draw_course(c, [project(p[0], p[1]) for p in routes[0]], width)
    else:
        for route in routes:
            p = c.beginPath()
            for i, (gx, gy) in enumerate(route):
                px, py = project(gx, gy)
                if i == 0:
                    p.moveTo(px, py)
                else:
                    p.lineTo(px, py)
            c.drawPath(p, stroke=1, fill=0)

    if waypoints:
        pts = [(*project(wp["x"], wp["y"]), wp.get("name", "")) for wp in waypoints]
        _draw_waypoints(c, pts, width)
    c.restoreState()
