import json

import pytest

from jabuti.models.clades import Clade, CladeSet
from jabuti.models.document import TreeEdits
from jabuti.presets import (
    DEFAULT_DETECTION,
    PresetError,
    load_preset,
    preset_from_dict,
    preset_to_dict,
    save_preset,
    style_from_dict,
    style_to_dict,
)
from jabuti.style import (
    BranchStyle,
    CladeStyle,
    GuideStyle,
    LabelStyle,
    LayoutKind,
    RenderStyle,
    ScaleBarStyle,
    SupportStyle,
    SymbolStyle,
)


def custom_style() -> RenderStyle:
    return RenderStyle(
        layout=LayoutKind.CIRCULAR, branch_scale=1.5, leaf_spacing=2.0, use_lengths=False, align_tips=False,
        branch=BranchStyle(width=2.0, color="#112233", cap="round", width_by_support=True, min_width=0.3, max_width=5),
        guide=GuideStyle(kind="bigdots", color="#445566", width=1.1, opacity=0.4),
        label=LabelStyle(family="Courier", size=12, bold=True, italic=False, color="#778899", show=False),
        support=SupportStyle(mode="symbols", index=0, threshold=80, symbol_size=9, size_by_value=True, color="#aabbcc"),
        symbols=SymbolStyle(shape="diamond", size=7, color="#ddeeff", use_clade_color=False),
        scale_bar=ScaleBarStyle(show=False, position="top-right", length=0.05),
        clades=CladeStyle(palette="Set2", color_branches=False, label_mode="none", background=True,
                          background_alpha=0.3, outer_strip=True, strip_width=20, show_names=True,
                          name_mode="radial", neutral_color="#123123"),
        background=None,
    )


def test_style_round_trip():
    st = custom_style()
    warnings: list[str] = []
    again = style_from_dict(json.loads(json.dumps(style_to_dict(st))), warnings)
    assert warnings == []
    assert again == st


def test_cut_distance_not_saved():
    st = RenderStyle(clades=CladeStyle(cut_distance=0.5))
    d = style_to_dict(st)
    assert "cut_distance" not in d["clades"]
    assert style_from_dict(d).clades.cut_distance is None


def test_unknown_keys_ignored_silently():
    d = style_to_dict(RenderStyle())
    d["nao_existe"] = 1
    d["label"]["outra"] = "x"
    warnings: list[str] = []
    assert style_from_dict(d, warnings) == RenderStyle()
    assert warnings == []


@pytest.mark.parametrize("path, value", [
    (("layout",), "triangular"),
    (("label", "size"), "grande"),
    (("label", "italic"), "sim"),
    (("branch", "color"), "vermelho"),
    (("guide", "kind"), "zigue-zague"),
    (("support", "index"), 7),
    (("clades", "palette"), "Inexistente"),
    (("branch", "width"), -1),
    (("label",), "não é objeto"),
])
def test_invalid_values_warn_and_keep_default(path, value):
    d = style_to_dict(RenderStyle())
    target = d
    for k in path[:-1]:
        target = target[k]
    target[path[-1]] = value
    warnings: list[str] = []
    assert style_from_dict(d, warnings) == RenderStyle()
    assert len(warnings) == 1 and path[-1] in warnings[0]


def test_full_preset_round_trip(tmp_path):
    cs = CladeSet([Clade("A", frozenset({"x", "y"}), "#ff0000", True, "manual"),
                   Clade("B", frozenset({"z"}), None, False, "auto")], auto_mode="k")
    edits = TreeEdits("desc", [frozenset({"x", "y"})], [frozenset({"z", "w"})])
    det = {"mode": "support", "k": 7, "support_threshold": 90.0, "support_index": 0,
           "distance_fraction": 0.5, "show_cut": False}
    p = save_preset(tmp_path / "p.json", preset_to_dict(custom_style(), cs, edits, det))
    loaded = load_preset(p)
    assert loaded.warnings == []
    assert loaded.style == custom_style()
    assert loaded.detection == det
    assert loaded.clade_set.clades == cs.clades and loaded.clade_set.auto_mode == "k"
    assert loaded.edits == edits


def test_style_only_preset_has_no_clades_or_edits():
    loaded = preset_from_dict(preset_to_dict(RenderStyle()))
    assert loaded.clade_set is None and loaded.edits is None
    assert loaded.detection == DEFAULT_DETECTION


def test_bad_clades_and_edits_warn():
    data = preset_to_dict(RenderStyle())
    data["clades"] = [{"name": "ok", "leaves": ["a"]}, {"name": "sem folhas"}, 5,
                      {"leaves": ["b"], "color": "azul"}]
    data["edits"] = {"ladderize": "lado", "rotations": [["a"], [1, 2]], "collapsed": "x"}
    loaded = preset_from_dict(data)
    assert [c.name for c in loaded.clade_set.clades] == ["ok", "Clado 4"]
    assert loaded.clade_set.clades[1].color is None
    assert loaded.edits.ladderize == "none" and loaded.edits.rotations == [frozenset("a")]
    assert len(loaded.warnings) == 6


def test_newer_version_warns(tmp_path):
    data = preset_to_dict(RenderStyle())
    data["version"] = 99
    assert "versão mais nova" in preset_from_dict(data).warnings[0]


def test_invalid_json_is_error(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"style": {,}', encoding="utf-8")
    with pytest.raises(PresetError) as exc:
        load_preset(p)
    assert "JSON inválido" in exc.value.user_message() and "bad.json" in exc.value.user_message()


def test_non_object_json_is_error(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(PresetError):
        load_preset(p)
