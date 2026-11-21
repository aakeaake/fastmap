import json
from pathlib import Path

import pytest

from fastmap.vector.expressions import (
    EvalContext,
    StyleError,
    evaluate,
    filter_matches,
    validate,
    validate_property,
)

STYLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "fastmap"
    / "vector"
    / "styles"
    / "maastokartta.json"
)


def ctx(props=None, zoom=13.0, geom="Polygon"):
    return EvalContext(props=props or {}, zoom=zoom, geom_type=geom)


def test_match_with_list_label():
    e = ["match", ["get", "k"], [1, 2], "a", 3, "b", "c"]
    assert evaluate(e, ctx({"k": 2})) == "a"
    assert evaluate(e, ctx({"k": 3})) == "b"
    assert evaluate(e, ctx({"k": 9})) == "c"


def test_interpolate_exponential():
    e = ["interpolate", ["exponential", 1.55], ["zoom"], 6, 1, 20, 20]
    expected = 1 + 19 * (1.55**7 - 1) / (1.55**14 - 1)
    assert evaluate(e, ctx(zoom=13)) == pytest.approx(expected)
    assert evaluate(e, ctx(zoom=2)) == 1
    assert evaluate(e, ctx(zoom=30)) == 20


def test_interpolate_linear_nested_output():
    e = ["interpolate", ["linear"], ["zoom"], 10, 0, 12, ["get", "v"]]
    assert evaluate(e, ctx({"v": 10}, zoom=11)) == pytest.approx(5)


def test_step():
    e = ["step", ["zoom"], "fine", 14.5, "coarse"]
    assert evaluate(e, ctx(zoom=13.4)) == "fine"
    assert evaluate(e, ctx(zoom=14.5)) == "coarse"


def test_coalesce():
    e = ["coalesce", ["get", "nimi_fin"], ["get", "nimi_swe"]]
    assert evaluate(e, ctx({"nimi_swe": "Helsingfors"})) == "Helsingfors"


def test_modulo():
    assert evaluate(["%", ["get", "korkeusarvo"], 20], ctx({"korkeusarvo": 120})) == 0


def test_to_string_round():
    e = [
        "to-string",
        ["round", ["coalesce", ["/", ["get", "korkeusarvo"], 1000], ["get", "korkeus"]]],
    ]
    # Brief said "72", but 72.5 rounds half-up to 73 (MapLibre/JS Math.round).
    assert evaluate(e, ctx({"korkeusarvo": 72500})) == "73"
    assert evaluate(e, ctx({"korkeusarvo": 72400})) == "72"
    assert evaluate(e, ctx({"korkeus": 7})) == "7"


def test_number_format():
    e = ["number-format", 72.54, {"min-fraction-digits": 1, "max-fraction-digits": 1}]
    assert evaluate(e, ctx()) == "72.5"


def test_geometry_type():
    e = ["==", ["geometry-type"], "Polygon"]
    assert evaluate(e, ctx(geom="Polygon")) is True
    assert evaluate(e, ctx(geom="LineString")) is False


def test_legacy_filters():
    c = ctx({"kohdeluokka": 32431, "teksti": "x", "tasosijainti": 0})
    assert filter_matches(["==", "kohdeluokka", 32431], c)
    assert not filter_matches(["==", "kohdeluokka", 1], c)
    assert filter_matches(["in", "kohdeluokka", 32431, 2], c)
    assert not filter_matches(["in", "kohdeluokka", 1, 2], c)
    assert filter_matches(["!in", "kohdeluokka", 1, 2], c)
    assert filter_matches(["has", "teksti"], c)
    assert not filter_matches(["has", "missing"], c)
    assert filter_matches(["all", ["<", "tasosijainti", 1]], c)
    assert not filter_matches(["all", ["<", "tasosijainti", 0]], c)
    assert filter_matches(["any", ["==", "kohdeluokka", 1], ["has", "teksti"]], c)
    assert filter_matches(["none", ["==", "kohdeluokka", 1]], c)
    assert filter_matches(None, c)


def test_expression_in():
    e = ["in", ["get", "k"], ["literal", [1, 2]]]
    assert filter_matches(e, ctx({"k": 2}))
    assert not filter_matches(e, ctx({"k": 5}))


def test_legacy_stops_function():
    fn = {"base": 1, "stops": [[14, 0.4], [16, 1]]}
    assert evaluate(fn, ctx(zoom=15)) == pytest.approx(0.7)
    assert evaluate(fn, ctx(zoom=10)) == 0.4
    assert evaluate({"stops": [[0, False], [9, True]]}, ctx(zoom=10)) is True


def test_validate_unknown_operator():
    with pytest.raises(StyleError, match="foo"):
        validate(["foo", 1])


def test_all_style_expressions_validate():
    style = json.loads(STYLE_PATH.read_text(encoding="utf-8"))
    n = 0
    for layer in style["layers"]:
        validate(layer.get("filter"))
        for section in ("paint", "layout"):
            for key, value in layer.get(section, {}).items():
                validate_property(key, value)
                n += 1
    assert n > 100
