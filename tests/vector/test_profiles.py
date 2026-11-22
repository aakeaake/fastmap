import json

import pytest

from fastmap.vector.expressions import StyleError
from fastmap.vector.profiles import PROFILES, PROFILES_PATH, load_profiles
from fastmap.vector.style import load_style


def _raw():
    return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))


def _load(tmp_path, raw):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return load_profiles(path)


def test_profiles_json_loads_and_validates():
    profiles = load_profiles()
    assert profiles == PROFILES
    assert set(profiles) == {25000, 50000}
    for scale, p in profiles.items():
        assert p.scale == scale and isinstance(p.tile_level, int) and p.px_mm > 0


def test_every_override_names_a_style_layer():
    ids = {ly.id for ly in load_style().layers}
    for p in PROFILES.values():
        assert set(p.overrides) <= ids, set(p.overrides) - ids


def test_notes_are_ignored_and_explain_every_override():
    raw = _raw()
    for key, profile in raw.items():
        if key in ("note", "notes"):
            continue
        assert profile["notes"]
        for lid, ov in profile["overrides"].items():
            assert ov.get("note"), (key, lid)
            assert "note" not in PROFILES[int(key)].overrides[lid]


@pytest.mark.parametrize(
    "where",
    ["profile", "override", "notes"],
)
def test_unknown_key_is_rejected(tmp_path, where):
    raw = _raw()
    profile = raw["25000"]
    if where == "profile":
        profile["px_size"] = 0.1
    elif where == "override":
        profile["overrides"]["mml-vedenpinta"]["min_zoom"] = 12
    else:
        profile["notes"]["pxmm"] = "typo"
    with pytest.raises(StyleError, match="unknown key"):
        _load(tmp_path, raw)


def test_missing_and_mistyped_values_are_rejected(tmp_path):
    raw = _raw()
    del raw["50000"]["tile_level"]
    with pytest.raises(StyleError, match="missing"):
        _load(tmp_path, raw)
    raw = _raw()
    raw["25000"]["overrides"]["vesisto_alue_reuna"]["line-width-scale"] = "0.6"
    with pytest.raises(StyleError, match="number"):
        _load(tmp_path, raw)
