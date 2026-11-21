import pytest

from fastmap.vector.expressions import EvalContext, StyleError, filter_matches
from fastmap.vector.profiles import PROFILES
from fastmap.vector.style import (
    StyleLayer,
    load_style,
    scale_to_zoom,
    style_for,
)

CTX = EvalContext(props={}, zoom=13.0, geom_type="LineString")


def test_scale_to_zoom_values():
    assert scale_to_zoom(25000, 6_687_500) == pytest.approx(13.4, abs=0.05)
    assert scale_to_zoom(50000, 6_687_500) == pytest.approx(12.4, abs=0.05)
    # cos(lat) shrinks toward the pole, so Lapland gets a LOWER zoom
    assert scale_to_zoom(50000, 7_700_000) < 12.4 - 0.3


def test_load_style_and_override():
    assert len(load_style().layers) > 80
    style = load_style(overrides={"mml-polku": {"visibility": "none"}})
    layer = next(ly for ly in style.layers if ly.id == "mml-polku")
    assert not layer.visible_at(14)
    base = next(ly for ly in load_style().layers if ly.id == "mml-polku")
    assert base.visible_at(14)


def test_unknown_override_layer_raises():
    with pytest.raises(StyleError, match="nope"):
        load_style(overrides={"nope": {"visibility": "none"}})


def test_minzoom_maxzoom_defaults_and_visibility():
    ly = StyleLayer("a", "line", "x", 13, 24, None, {}, {})
    assert not ly.visible_at(12.4)
    assert ly.visible_at(13)
    assert not ly.visible_at(24)
    layers = {ly.id: ly for ly in load_style().layers}
    assert layers["background"].minzoom == 0 and layers["background"].maxzoom == 24


def test_get_literal_arrays_and_expressions():
    ly = StyleLayer(
        "a",
        "symbol",
        "x",
        0,
        24,
        None,
        {"line-dasharray": [2, 1], "line-width": ["step", ["zoom"], 1, 12, 3]},
        {"text-font": ["Noto Sans Regular"], "text-variable-anchor": ["top", "bottom"]},
    )
    assert ly.get("text-font", CTX) == ["Noto Sans Regular"]
    assert ly.get("text-variable-anchor", CTX) == ["top", "bottom"]
    assert ly.get("line-dasharray", CTX) == [2, 1]
    assert ly.get("line-width", CTX) == 3
    assert ly.get("missing", CTX, "d") == "d"


def test_profiles_and_style_for():
    assert set(PROFILES) == {25000, 50000}
    assert style_for(PROFILES[25000]) is style_for(PROFILES[25000])


@pytest.mark.parametrize("scale", [25000, 50000])
@pytest.mark.parametrize("northing", [6_630_000, 7_780_000])  # south coast, far north
def test_profiles_draw_contours_and_label_only_drawn_ones(scale, northing):
    from fastmap.vector.style import scale_to_zoom

    profile = PROFILES[scale]
    zoom = scale_to_zoom(scale, northing) + profile.zoom_offset
    layers = {ly.id: ly for ly in style_for(profile).layers}
    assert layers["korkeus_viiva"].visible_at(zoom)
    assert layers["korkeus-label"].visible_at(zoom)
    assert layers["korkeus_apuviiva"].visible_at(zoom) == (scale == 25000)


@pytest.mark.parametrize("scale", [25000, 50000])
def test_profiles_thin_halo_and_lighter_lines(scale):
    profile = PROFILES[scale]
    assert 2 * profile.px_mm * profile.halo_scale <= 0.1  # widest style halo, mm
    assert profile.px_mm < 0.28


def test_filter_override_is_anded_with_the_layer_filter():
    style = load_style(overrides={"nimisto": {"filter": ["==", ["get", "x"], 1]}})
    layer = next(ly for ly in style.layers if ly.id == "nimisto")
    base = {"teema": "Kulttuuri", "alaryhma": "Kylät", "laji": "Kylä"}
    match = filter_matches(layer.filter, EvalContext({**base, "x": 1}, 14.0, "Point"))
    miss = filter_matches(layer.filter, EvalContext({**base, "x": 2}, 14.0, "Point"))
    assert match and not miss


def test_50k_shows_only_names_tagged_for_50k_or_smaller_scales():
    style = style_for(PROFILES[50000])

    def shown(props):
        return any(
            ly.source_layer == "nimisto"
            and filter_matches(ly.filter, EvalContext(props, 13.5, "Point"))
            for ly in style.layers
        )

    lake = {"teema": "Vedet", "prioriteetti": 30, "nimi_fin": "X"}
    assert shown({**lake, "mittakaavarelevanssi": 50000})
    assert shown({**lake, "mittakaavarelevanssi": 250000})
    assert not shown({**lake, "mittakaavarelevanssi": 25000})
    church = {"teema": "Kulttuuri", "alaryhma": "X", "laji": "Kirkko"}
    assert not shown({**church, "mittakaavarelevanssi": 0})
    assert not shown(church)  # no relevance tag: a service point, not a map name
    park = {"teema": "Suojelu", "laji": "Kansallispuisto", "mittakaavarelevanssi": 25000}
    assert shown(park)  # national parks keep their names


def test_25k_keeps_all_names():
    style = style_for(PROFILES[25000])
    lake = {"teema": "Vedet", "prioriteetti": 30, "nimi_fin": "X", "mittakaavarelevanssi": 25000}
    assert any(
        ly.source_layer == "nimisto" and filter_matches(ly.filter, EvalContext(lake, 13.5, "Point"))
        for ly in style.layers
    )
