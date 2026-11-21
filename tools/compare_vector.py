"""Render raster and vector PDFs of the same sheet and write side-by-side PNGs.

Used to calibrate ``fastmap.vector.profiles``. Needs MML_API_KEY
(``set -a; . ./.env; set +a``) and ``pdftoppm`` (poppler-utils).

    uv run python tools/compare_vector.py --scale 25000
    uv run python tools/compare_vector.py --scale 50000 --reference ref.webp --crop-mm 85 64

For each place it writes ``<place>-<scale>-{vector,raster}.pdf``, the full pages at
90 dpi side by side (``-page.png``) and a crop at the map centre side by side
(``-crop.png``). With ``--reference`` the right-hand panels are the reference image
(scaled to the crop's height) instead of the raster map, and no raster PDF is made.
Outputs go to a fresh temporary directory unless ``--out`` is given; never commit them.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

from fastmap.services.mml_source import VECTOR_LAYER
from fastmap.services.pdf_generator import generate_pdf
from fastmap.services.print_layout import (
    FOOTER_MM,
    content_area_mm,
    extent_for_center,
    oriented_page_mm,
)

PLACES: dict[str, tuple[float, float]] = {
    "nuuksio": (371500.0, 6687500.0),
    "saana": (253000.0, 7676000.0),
    "jyvaskyla": (435000.0, 6902000.0),
}
MARGIN_MM = 7.0
PAGE_DPI = 90
CROP_DPI = 600
CROP_MM = (38.0, 30.0)
HEADER_PX = 28
GAP_PX = 12


def map_center_mm(paper: str, orientation: str, margin_mm: float = MARGIN_MM):
    """Centre of the map area, in mm from the page's top-left corner."""
    page_w, page_h = oriented_page_mm(paper, orientation)
    cont_w, cont_h = content_area_mm(paper, orientation, margin_mm)
    bottom = margin_mm + FOOTER_MM  # map bottom edge, from the page bottom
    return margin_mm + cont_w / 2, page_h - (bottom + cont_h / 2)


def crop_box_px(
    paper: str, orientation: str, crop_mm: tuple[float, float], dpi: int
) -> tuple[int, int, int, int]:
    """(x, y, w, h) in pixels at ``dpi`` of a crop_mm patch centred on the map."""
    cx, cy = map_center_mm(paper, orientation)
    w, h = crop_mm
    px = dpi / 25.4
    return round((cx - w / 2) * px), round((cy - h / 2) * px), round(w * px), round(h * px)


def rasterise(pdf: Path, png: Path, dpi: int, box: tuple[int, int, int, int] | None = None):
    """Rasterise page 1 of ``pdf`` to ``png`` with pdftoppm (optionally cropped)."""
    cmd = ["pdftoppm", "-png", "-singlefile", "-r", str(dpi)]
    if box is not None:
        x, y, w, h = box
        cmd += ["-x", str(x), "-y", str(y), "-W", str(w), "-H", str(h)]
    subprocess.run([*cmd, str(pdf), str(png.with_suffix(""))], check=True)
    return png


def side_by_side(left: Image.Image, right: Image.Image, titles: tuple[str, str]) -> Image.Image:
    """``left`` and ``right`` (scaled to the left's height) with a title above each."""
    left = left.convert("RGB")
    right = right.convert("RGB")
    if right.height != left.height:
        w = round(right.width * left.height / right.height)
        right = right.resize((w, left.height), Image.LANCZOS)
    out = Image.new(
        "RGB", (left.width + GAP_PX + right.width, left.height + HEADER_PX), (255, 255, 255)
    )
    out.paste(left, (0, HEADER_PX))
    out.paste(right, (left.width + GAP_PX, HEADER_PX))
    draw = ImageDraw.Draw(out)
    draw.text((4, 6), titles[0], fill=(0, 0, 0))
    draw.text((left.width + GAP_PX + 4, 6), titles[1], fill=(0, 0, 0))
    return out


def _render(center, scale, paper, orientation, layer, path: Path) -> float:
    extent = extent_for_center(*center, scale, paper, orientation, MARGIN_MM)
    t0 = time.perf_counter()
    generate_pdf(
        extent,
        paper_size=paper,
        orientation=orientation,
        layer=layer,
        margin_mm=MARGIN_MM,
        out_pdf_path=str(path),
    )
    return time.perf_counter() - t0


def compare_place(
    name: str,
    center: tuple[float, float],
    *,
    scale: int,
    paper: str,
    orientation: str,
    out: Path,
    reference: Path | None,
    crop_mm: tuple[float, float],
    crop_dpi: int,
) -> list[Path]:
    """Render one place; return the side-by-side PNGs written."""
    stem = f"{name}-{scale}"
    vec_pdf = out / f"{stem}-vector.pdf"
    seconds = _render(center, scale, paper, orientation, VECTOR_LAYER, vec_pdf)
    size_mb = vec_pdf.stat().st_size / 1e6
    print(f"{stem}: vector {paper} {orientation} {seconds:.1f} s, {size_mb:.1f} MB")
    box = crop_box_px(paper, orientation, crop_mm, crop_dpi)
    vec_page = rasterise(vec_pdf, out / f"{stem}-vector-page.png", PAGE_DPI)
    vec_crop = rasterise(vec_pdf, out / f"{stem}-vector-crop.png", crop_dpi, box)
    written = []
    if reference is None:
        ras_pdf = out / f"{stem}-raster.pdf"
        _render(center, scale, paper, orientation, "maastokartta", ras_pdf)
        ras_page = rasterise(ras_pdf, out / f"{stem}-raster-page.png", PAGE_DPI)
        ras_crop = rasterise(ras_pdf, out / f"{stem}-raster-crop.png", crop_dpi, box)
        pairs = [("page", vec_page, ras_page), ("crop", vec_crop, ras_crop)]
        other = "raster maastokartta"
    else:
        pairs = [("crop", vec_crop, reference)]
        other = f"reference {reference.name}"
    for kind, mine, theirs in pairs:
        png = out / f"{stem}-{kind}.png"
        with Image.open(mine) as a, Image.open(theirs) as b:
            title = f"vector 1:{scale} {name}"
            side_by_side(a, b, (title, other)).save(png)
        written.append(png)
    return written


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--scale", type=int, choices=(25000, 50000), required=True)
    p.add_argument("--at", nargs=2, type=float, metavar=("E", "N"), help="one place only")
    p.add_argument("--paper", choices=("A4", "A3"), default="A4")
    p.add_argument("--orientation", choices=("portrait", "landscape"), default="portrait")
    p.add_argument("--out", type=Path, help="output directory (default: a new temp dir)")
    p.add_argument("--reference", type=Path, help="reference image for the right panels")
    p.add_argument("--crop-mm", nargs=2, type=float, metavar=("W", "H"), default=CROP_MM)
    p.add_argument("--crop-dpi", type=int, default=CROP_DPI)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = args.out or Path(tempfile.mkdtemp(prefix="compare_vector_"))
    out.mkdir(parents=True, exist_ok=True)
    places = {"at": tuple(args.at)} if args.at else PLACES
    for name, center in places.items():
        for png in compare_place(
            name,
            center,
            scale=args.scale,
            paper=args.paper,
            orientation=args.orientation,
            out=out,
            reference=args.reference,
            crop_mm=tuple(args.crop_mm),
            crop_dpi=args.crop_dpi,
        ):
            print(png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
