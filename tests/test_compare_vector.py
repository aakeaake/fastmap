import importlib.util
from pathlib import Path

import pytest
from PIL import Image

_PATH = Path(__file__).resolve().parent.parent / "tools" / "compare_vector.py"
_spec = importlib.util.spec_from_file_location("compare_vector", _PATH)
cv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cv)


def test_map_center_and_crop_box():
    # A4 portrait, 7 mm margins, 3 mm footer: map 196 x 280 mm, its bottom 10 mm up
    cx, cy = cv.map_center_mm("A4", "portrait")
    assert (cx, cy) == pytest.approx((105.0, 297 - (10 + 140)))
    x, y, w, h = cv.crop_box_px("A4", "portrait", (38, 30), 254)  # 10 px/mm
    assert (w, h) == (380, 300)
    assert (x + w / 2, y + h / 2) == pytest.approx((1050, 1470), abs=1)


def test_side_by_side_scales_right_panel_to_left_height():
    left = Image.new("RGB", (100, 80), (255, 0, 0))
    right = Image.new("RGB", (50, 20), (0, 0, 255))
    out = cv.side_by_side(left, right, ("a", "b"))
    assert out.size == (100 + cv.GAP_PX + 200, 80 + cv.HEADER_PX)
    assert out.getpixel((50, cv.HEADER_PX + 40)) == (255, 0, 0)
    assert out.getpixel((100 + cv.GAP_PX + 100, cv.HEADER_PX + 40)) == (0, 0, 255)


def test_defaults_out_to_none_and_three_places():
    args = cv.parse_args(["--scale", "50000"])
    assert args.out is None and args.at is None and args.paper == "A4"
    assert set(cv.PLACES) == {"nuuksio", "saana", "jyvaskyla"}
