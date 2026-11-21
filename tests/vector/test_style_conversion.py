import json
from pathlib import Path

STYLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "fastmap"
    / "vector"
    / "styles"
    / "maastokartta.json"
)


def _style():
    return json.loads(STYLE_PATH.read_text(encoding="utf-8"))


def test_single_mml_source():
    style = _style()
    assert style["sources"] == {"mml": {"type": "vector"}}
    for layer in style["layers"]:
        if layer["type"] != "background":
            assert layer["source"] == "mml"


def test_no_twins_or_osm():
    for layer in _style()["layers"]:
        assert not layer["id"].endswith(" (ways)")
        assert not layer["id"].startswith("osm-")


def test_mml_paths_visible():
    layers = {layer["id"]: layer for layer in _style()["layers"]}
    assert layers["mml-polku"].get("layout", {}).get("visibility") != "none"


def test_no_urls_or_keys():
    text = STYLE_PATH.read_text(encoding="utf-8")
    for bad in ("api-key", "http://", "https://"):
        assert bad not in text


def test_layer_count_sane():
    assert 80 <= len(_style()["layers"]) <= 130


def _index():
    return {layer["id"]: i for i, layer in enumerate(_style()["layers"])}


def test_contours_draw_over_swamps():
    i = _index()
    for swamp in ("maasto_alue_vesi", "maasto_alue_vesi-suo-vaikea"):
        for contour in ("korkeus_viiva", "korkeus_viiva_pieni_zoom", "korkeus_apuviiva"):
            assert i[swamp] < i[contour], (swamp, contour)


def test_shoreline_draws_over_water_and_swamp_fills():
    i = _index()
    for fill in ("water-mml", "maasto_alue_vesi", "maasto_alue_vesi-suo-vaikea"):
        assert i[fill] < i["vesisto_alue_reuna"], fill
