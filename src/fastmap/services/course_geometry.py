"""Orienteering course geometry, shared rules with ``frontend/js/course.js``.

Pure functions on 2-D points in any one unit (paper points in the PDF).
Sizes are millimetres on paper, roughly the IOF ISOM course symbols.
"""

from math import atan2, cos, hypot, pi, radians, sin, sqrt

Point = tuple[float, float]

CONTROL_D_MM = 6.0
START_SIDE_MM = 7.0
FINISH_D_MM = (5.0, 7.0)
FINISH_CLEAR_MM = 0.6  # least white between the finish circles
LEG_GAP_MM = 0.3
NUMBER_H_MM = 4.0
NUMBER_OFFSET_MM = 2.5  # from the circle edge to the number's centre
DOT_D_MM = 0.6
WAYPOINT_NAME_H_MM = 3.0
HALO_MM = 0.3
START_RADIUS_MM = START_SIDE_MM / sqrt(3)  # circumradius: the corner the leg leaves from


def _unit(dx: float, dy: float) -> Point:
    n = hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-12 else (0.0, 0.0)


def shorten_leg(a: Point, b: Point, ra: float, rb: float) -> tuple[Point, Point] | None:
    """The leg a→b with ``ra`` cut from its start and ``rb`` from its end."""
    d = hypot(b[0] - a[0], b[1] - a[1])
    if d <= ra + rb:
        return None
    ux, uy = (b[0] - a[0]) / d, (b[1] - a[1]) / d
    return (a[0] + ux * ra, a[1] + uy * ra), (b[0] - ux * rb, b[1] - uy * rb)


def course_legs(
    points: list[Point], r_start: float, r_control: float, r_finish: float, gap: float
) -> list[tuple[Point, Point]]:
    """Legs between consecutive points, each end stopped at its symbol + gap."""
    last = len(points) - 1

    def radius(i: int) -> float:
        return (r_start if i == 0 else r_finish if i == last else r_control) + gap

    legs = []
    for i in range(last):
        leg = shorten_leg(points[i], points[i + 1], radius(i), radius(i + 1))
        if leg:
            legs.append(leg)
    return legs


def finish_outer_radius(inner_r: float, outer_r: float, width: float, clear: float) -> float:
    """The outer finish circle's radius, moved out so a thick line still leaves
    ``clear`` between the two circles."""
    return max(outer_r, inner_r + width + clear)


def number_direction(prev: Point, p: Point, nxt: Point) -> Point:
    """Unit vector from ``p`` away from both of its legs."""
    a = _unit(prev[0] - p[0], prev[1] - p[1])
    b = _unit(nxt[0] - p[0], nxt[1] - p[1])
    ux, uy = a[0] + b[0], a[1] + b[1]
    if hypot(ux, uy) < 1e-9:
        tx, ty = _unit(nxt[0] - prev[0], nxt[1] - prev[1])
        if tx == 0 and ty == 0:
            return (0.0, 1.0)
        return (-ty, tx)  # left of the direction of travel
    return _unit(-ux, -uy)


def start_triangle(p: Point, toward: Point, side: float) -> list[Point]:
    """Equilateral triangle centred on ``p``, first corner pointing at ``toward``."""
    r = side / sqrt(3)
    dx, dy = toward[0] - p[0], toward[1] - p[1]
    theta = atan2(dy, dx) if hypot(dx, dy) > 1e-12 else pi / 2
    return [
        (p[0] + r * cos(theta + radians(k)), p[1] + r * sin(theta + radians(k)))
        for k in (0, 120, -120)
    ]
