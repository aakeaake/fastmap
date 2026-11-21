"""Convert the upstream MaRaSu/mmlv2 MapLibre style into fastmap's vector style.

Usage: uv run python tools/convert_mmlv2.py IN.json OUT.json
"""

import argparse
import json
import sys

KEEP_SOURCES = {"mml_topo", "mml_ways", "mml_contours", "mml_buildings"}
TARGET_SOURCE = "mml"
TWIN_SUFFIX = " (ways)"
DROP_ID_PREFIXES = ("osm-",)
# mmlv2 hides MML footpaths because Trailmap shows OSM paths; fastmap has none.
FORCE_VISIBLE = {"mml-polku"}
UPSTREAM_REF = "MaRaSu/mmlv2@82b5ab0"
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
        if lid in FORCE_VISIBLE:
            layer = {**layer, "layout": {**layer.get("layout", {}), "visibility": "visible"}}
        out_layers.append(layer)
    for lid, where, anchor in MOVES:
        _move(out_layers, lid, where, anchor)
    return {
        "version": style.get("version", 8),
        "name": style.get("name", "maastokartta"),
        "metadata": {"fastmap:source": UPSTREAM_REF},
        "sources": {TARGET_SOURCE: {"type": "vector"}},
        "layers": out_layers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("IN")
    parser.add_argument("OUT")
    args = parser.parse_args()
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
