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


def test_sea_is_filled_like_other_water():
    # mmlv2 leaves sea (36211) to Trailmap's OSM water layer, which fastmap drops;
    # the MML water fill must draw it.
    from fastmap.vector.expressions import EvalContext, filter_matches

    water = next(ly for ly in _style()["layers"] if ly["id"] == "water-mml")
    for kohdeluokka in (36200, 36211):  # lake, sea
        ctx = EvalContext({"kohdeluokka": kohdeluokka}, 13.5, "Polygon")
        assert filter_matches(water["filter"], ctx), kohdeluokka


def test_water_and_field_colours_follow_the_reference_map():
    layers = {ly["id"]: ly for ly in _style()["layers"]}
    assert layers["water-mml"]["paint"]["fill-color"] == "#6DCFF6"
    for lid in ("vesisto_alue_reuna", "vesisto_viiva"):
        assert layers[lid]["paint"]["line-color"] == "#0071BC"
    for lid in ("maankaytto", "maankaytto-asutus"):
        assert "#FFD98F" in json.dumps(layers[lid]["paint"]["fill-color"])
    text = STYLE_PATH.read_text(encoding="utf-8").lower()
    for old in ("#80ffff", "#0080ff", "#ffd980"):
        assert old not in text


def test_style_metadata_says_fastmap_owns_it():
    meta = _style()["metadata"]
    assert "fastmap" in meta["fastmap:style"] and "by hand" in meta["fastmap:style"]
    assert meta["fastmap:derived-from"] == "MaRaSu/mmlv2@82b5ab0"


def _converter():
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "tools" / "convert_mmlv2.py"
    spec = importlib.util.spec_from_file_location("convert_mmlv2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_script_refuses_to_overwrite_without_force(tmp_path, capsys):
    upstream = tmp_path / "in.json"
    upstream.write_text(json.dumps({"version": 8, "layers": []}), encoding="utf-8")
    out = tmp_path / "out.json"
    out.write_text("hand-edited", encoding="utf-8")
    convert = _converter()
    convert.convert = lambda style: {"layers": []}  # the guard is under test, not the import
    assert convert.main([str(upstream), str(out)]) == 1
    assert out.read_text(encoding="utf-8") == "hand-edited"
    assert "--force" in capsys.readouterr().err
    assert convert.main([str(upstream), str(out), "--force"]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["layers"] == []
