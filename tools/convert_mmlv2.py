"""Record of the one-time import of MaRaSu/mmlv2 into fastmap's vector style.

NOTE: src/fastmap/vector/styles/maastokartta.json is fastmap's own style now and is
edited by hand. This script only documents how it was first derived from the upstream
MaRaSu/mmlv2 MapLibre style (at the commit in UPSTREAM_REF). Re-running it would discard
every edit made to the style since, so it refuses to overwrite an existing OUT file
unless --force is given.

Usage: uv run python tools/convert_mmlv2.py IN.json OUT.json [--force]
"""

import argparse
import json
import sys
from pathlib import Path

KEEP_SOURCES = {"mml_topo", "mml_ways", "mml_contours", "mml_buildings"}
TARGET_SOURCE = "mml"
TWIN_SUFFIX = " (ways)"
DROP_ID_PREFIXES = ("osm-",)
# mmlv2 hides MML footpaths because Trailmap shows OSM paths; fastmap has none.
FORCE_VISIBLE = {"mml-polku"}
UPSTREAM_REF = "MaRaSu/mmlv2@82b5ab0"
# Layer filters replaced outright. mmlv2's MML water fill leaves out sea (36211)
# because Trailmap fills the sea from OSM water, which fastmap drops; fastmap
# fills all MML water areas, sea included.
FILTERS = {
    "water-mml": ["==", "$type", "Polygon"],
}
# fastmap's palette where it differs from mmlv2 (colours of the user's reference
# print map): water areas, shorelines and streams, and fields.
PALETTE = {
    "#80ffff": "#6DCFF6",  # water fill (was cyan)
    "#0080ff": "#0071BC",  # shorelines and streams
    "#ffd980": "#FFD98F",  # fields
}


def _recolour(value):
    """``value`` with every PALETTE colour (any letter case) replaced."""
    if isinstance(value, str):
        return PALETTE.get(value.lower(), value)
    if isinstance(value, list):
        return [_recolour(v) for v in value]
    if isinstance(value, dict):
        return {k: _recolour(v) for k, v in value.items()}
    return value


# Draw-order fixes for print, applied in order as (layer, "before"|"after", anchor):
# swamps go under the contours (as on the printed Maastokartta), and the shoreline
# goes over the water and swamp fills, which otherwise cover half of it.
MOVES = (
    ("maasto_alue_vesi", "before", "maankaytto"),
    ("maasto_alue_vesi-suo-vaikea", "after", "maasto_alue_vesi"),
    ("vesisto_alue_reuna", "after", "water-mml"),
)


def _move(layers: list[dict], lid: str, where: str, anchor: str) -> None:
    layer = next(ly for ly in layers if ly["id"] == lid)
    layers.remove(layer)
    at = next(i for i, ly in enumerate(layers) if ly["id"] == anchor)
    layers.insert(at if where == "before" else at + 1, layer)


FORBIDDEN = ("api-key", "http://", "https://")


def convert(style: dict) -> dict:
    layers = style["layers"]
    ids = {layer["id"] for layer in layers}
    out_layers = []
    for layer in layers:
        lid = layer["id"]
        if lid.startswith(DROP_ID_PREFIXES):
            continue
        if lid.endswith(TWIN_SUFFIX) and lid[: -len(TWIN_SUFFIX)] in ids:
            continue
        if layer.get("type") != "background":
            if layer.get("source") not in KEEP_SOURCES:
                continue
            layer = {**layer, "source": TARGET_SOURCE}
        layer = {**layer, "paint": _recolour(layer.get("paint", {}))}
        if lid in FILTERS:
            layer = {**layer, "filter": FILTERS[lid]}
        if lid in FORCE_VISIBLE:
            layer = {**layer, "layout": {**layer.get("layout", {}), "visibility": "visible"}}
        out_layers.append(layer)
    for lid, where, anchor in MOVES:
        _move(out_layers, lid, where, anchor)
    return {
        "version": style.get("version", 8),
        "name": style.get("name", "maastokartta"),
        "metadata": {"fastmap:derived-from": UPSTREAM_REF},
        "sources": {TARGET_SOURCE: {"type": "vector"}},
        "layers": out_layers,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("IN")
    parser.add_argument("OUT")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing OUT (discards any hand edits made to it)",
    )
    args = parser.parse_args(argv)
    if Path(args.OUT).exists() and not args.force:
        print(
            f"error: {args.OUT} exists; the style is maintained by hand now and "
            "re-converting would discard its edits (use --force to overwrite anyway)",
            file=sys.stderr,
        )
        return 1
    with open(args.IN, encoding="utf-8") as f:
        text = json.dumps(convert(json.load(f)), indent=1, ensure_ascii=False) + "\n"
    for bad in FORBIDDEN:
        if bad in text:
            print(f"error: converted style contains forbidden text {bad!r}", file=sys.stderr)
            return 1
    with open(args.OUT, "w", encoding="utf-8") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
