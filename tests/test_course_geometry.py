from math import isclose, sqrt

from fastmap.services.course_geometry import (
    course_legs,
    finish_outer_radius,
    number_direction,
    shorten_leg,
    start_triangle,
)


def close(p, q):
    return isclose(p[0], q[0], abs_tol=1e-9) and isclose(p[1], q[1], abs_tol=1e-9)


def test_shorten_leg():
    a, b = shorten_leg((0, 0), (10, 0), 1, 2)
    assert close(a, (1, 0)) and close(b, (8, 0))


def test_shorten_leg_too_short_is_none():
    assert shorten_leg((0, 0), (3, 0), 1, 2) is None
    assert shorten_leg((5, 5), (5, 5), 1, 1) is None  # start == finish


def test_course_legs_uses_start_control_finish_radii_plus_gap():
    legs = course_legs(
        [(0, 0), (100, 0), (100, 100)], r_start=4, r_control=3, r_finish=3.5, gap=0.5
    )
    assert len(legs) == 2
    assert close(legs[0][0], (4.5, 0)) and close(legs[0][1], (96.5, 0))
    assert close(legs[1][0], (100, 3.5)) and close(legs[1][1], (100, 96))


def test_course_legs_skips_too_short_leg():
    legs = course_legs([(0, 0), (1, 0), (100, 0)], r_start=4, r_control=3, r_finish=3.5, gap=0)
    assert len(legs) == 1
    assert close(legs[0][0], (4, 0))


def test_number_direction_points_away_from_both_legs():
    d = number_direction((-1, 0), (0, 0), (0, 1))
    assert close(d, (1 / sqrt(2), -1 / sqrt(2)))


def test_number_direction_straight_through_goes_left():
    assert close(number_direction((-1, 0), (0, 0), (1, 0)), (0, 1))


def test_number_direction_same_points_is_finite():
    d = number_direction((0, 0), (0, 0), (0, 0))
    assert isclose(d[0] ** 2 + d[1] ** 2, 1)


def test_start_triangle_points_at_first_control():
    t = start_triangle((0, 0), (10, 0), side=sqrt(3))  # circumradius 1
    assert close(t[0], (1, 0))
    assert close(t[1], (-0.5, sqrt(3) / 2)) and close(t[2], (-0.5, -sqrt(3) / 2))


def test_finish_outer_radius_keeps_a_clear_gap():
    assert isclose(finish_outer_radius(2.5, 3.5, width=0.35, clear=0.6), 3.5)  # thin: as drawn
    assert isclose(finish_outer_radius(2.5, 3.5, width=1.1, clear=0.6), 4.2)  # thick: moves out
