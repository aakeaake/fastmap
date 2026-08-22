import pytest

from fastmap.services.print_layout import (
    Extent,
    actual_scale,
    clamp_extent_to_finland,
    content_area_mm,
    content_pixels,
    extent_for_center,
    format_scale_label,
    scale_bar_distance,
    snap_extent_to_scale,
    with_aspect,
)


def test_oriented_page_sizes():
    from fastmap.services.print_layout import oriented_page_mm

    assert oriented_page_mm("A4", "portrait") == (210.0, 297.0)
    assert oriented_page_mm("A4", "landscape") == (297.0, 210.0)
    assert oriented_page_mm("A3", "portrait") == (297.0, 420.0)


def test_content_area_mm():
    assert content_area_mm("A4", "portrait", 10) == (190.0, 277.0)


def test_content_pixels_a4_300dpi():
    w, h = content_pixels("A4", "portrait", 300, 10)
    assert (w, h) == (2244, 3272)  # 190mm & 277mm at 300 dpi


def test_extent_for_center_round_trip_scale():
    ext = extent_for_center(430000, 6668000, 20000, "A4", "portrait", 10)
    cw, _ = content_area_mm("A4", "portrait", 10)
    assert ext.width_m == pytest.approx(3800.0)
    assert ext.height_m == pytest.approx(5540.0)
    assert actual_scale(ext, cw) == 20000


def test_snap_extent_to_scale_keeps_center():
    raw = Extent(400000, 6600000, 410000, 6620000)
    snapped = snap_extent_to_scale(raw, 25000, "A4", "landscape", 10)
    assert snapped.center == pytest.approx(raw.center)
    # A4 landscape content: 277 x 190 mm -> 6925 x 4750 m at 1:25000
    assert snapped.width_m == pytest.approx(6925.0)
    assert snapped.height_m == pytest.approx(4750.0)


def test_with_aspect_keeps_width_and_center():
    raw = Extent(0, 6000000, 1000, 6050000)
    out = with_aspect(raw, 277 / 190)
    assert out.width_m == pytest.approx(1000.0)
    assert out.height_m == pytest.approx(1000 * 277 / 190)
    assert out.center == pytest.approx(raw.center)


def test_clamp_extent_keeps_size_inside_bounds():
    huge = Extent(1500000, 8300000, 1600000, 8400000)  # pokes outside
    clamped = clamp_extent_to_finland(huge)
    assert clamped.width_m == pytest.approx(huge.width_m)
    assert clamped.height_m == pytest.approx(huge.height_m)
    assert clamped.minx >= -548576
    assert clamped.maxy <= 8388608


def test_scale_bar_distance_fits_content():
    dist = scale_bar_distance(20000, 190.0)
    bar_mm = dist / 20000 * 1000
    assert bar_mm <= 190.0 * 0.4
    assert dist in (500, 1000)  # 76mm limit -> 1 km fits (50mm)

    dist_small = scale_bar_distance(500000, 190.0)
    assert dist_small == 20000  # 76 mm limit at 1:500000 -> largest fitting nice value


def test_format_scale_label():
    assert format_scale_label(20000) == "1 : 20 000"
    assert format_scale_label(1234567) == "1 : 1 234 567"
