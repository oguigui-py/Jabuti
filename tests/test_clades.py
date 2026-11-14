import pytest

from jabuti.models.clades import (
    Clade,
    CladeSet,
    assign_nodes,
    clades_by_distance,
    clades_by_k,
    clades_by_support,
    mrca,
    resolve_clades,
)
from jabuti.parsers.newick import load_tree, parse_newick_string

PAL = ["#111111", "#222222", "#333333"]

BIN = "((((A:1,B:1)95/99:1,C:2)60/80:1,(D:1,E:1)99/100:3)90/97:1,(F:1,(G:1,H:1)40/50:1)85/96:2);"


def _is_monophyletic(tree, group):
    node = mrca(tree, group)
    return frozenset(l.name for l in node.leaves()) == group


def _check_partition(tree, groups):
    names = tree.leaf_names()
    flat = [n for g in groups for n in g]
    assert len(flat) == len(set(flat)), "grupos não podem se sobrepor"
    assert all(_is_monophyletic(tree, g) for g in groups)
    return set(flat) == set(names)


@pytest.mark.parametrize("k", [1, 2, 3, 4, 5, 8])
def test_k_exact_on_binary_tree(k):
    t = parse_newick_string(BIN)
    groups = clades_by_k(t, k)
    assert len(groups) == k
    assert _check_partition(t, groups)  # cobre todas as folhas


def test_k_splits_nearest_root_first():
    t = parse_newick_string(BIN)
    assert set(clades_by_k(t, 2)) == {frozenset("ABCDE"), frozenset("FGH")}
    # próximo corte: nó (ABC,DE) a dist 1 da raiz, antes de (F,(GH)) a dist 2
    assert set(clades_by_k(t, 3)) == {frozenset("ABC"), frozenset("DE"), frozenset("FGH")}


def test_k_capped_at_leaf_count():
    t = parse_newick_string(BIN)
    assert len(clades_by_k(t, 999)) == 8


def test_k_polytomy_may_exceed(data_dir):
    t = load_tree(data_dir / "iqtree_ufboot.treefile")  # raiz com 3 filhos (não enraizada)
    groups = clades_by_k(t, 2)
    assert len(groups) == 3
    assert _check_partition(t, groups)


def test_k_order_follows_leaves():
    t = parse_newick_string(BIN)
    groups = clades_by_k(t, 4)
    order = t.leaf_names()
    firsts = [min(order.index(n) for n in g) for g in groups]
    assert firsts == sorted(firsts)


def test_support_maximal_ufboot():
    t = parse_newick_string(BIN)
    # UFBoot (índice 1) >= 95: (ABCDE)=97 e (FGH)=96 são maximais; aninhados não entram
    assert set(clades_by_support(t, 95, index=1)) == {frozenset("ABCDE"), frozenset("FGH")}


def test_support_index_matters():
    t = parse_newick_string(BIN)
    # SH-aLRT (índice 0) >= 95: (AB)=95 e (DE)=99
    assert set(clades_by_support(t, 95, index=0)) == {frozenset("AB"), frozenset("DE")}
    # "ambos >=" usa o menor valor
    assert set(clades_by_support(t, 95, index=99)) == {frozenset("AB"), frozenset("DE")}


def test_support_all_pass_threshold_and_no_overlap():
    t = load_tree("examples/paraburkholderia_40.treefile")
    groups = clades_by_support(t, 98, index=1)
    assert groups
    _check_partition(t, groups)
    for g in groups:
        node = mrca(t, g)
        assert node.supports[1] >= 98 and len(g) >= 2


def test_support_ignores_root_and_unsupported(data_dir):
    t = load_tree(data_dir / "small.nwk")  # sem suporte
    assert clades_by_support(t, 0) == []


def test_distance_cut():
    t = parse_newick_string(BIN)
    # profundidades: (ABCDE)=1, (ABC)=2, (AB)=3, (DE)=4, (FGH)=2, F=3, (GH)=3
    assert set(clades_by_distance(t, 1.5)) == {frozenset("ABC"), frozenset("DE"), frozenset("FGH")}
    assert set(clades_by_distance(t, 3.5)) == {
        frozenset("A"), frozenset("B"), frozenset("C"), frozenset("DE"),
        frozenset("G"), frozenset("H"),
    }  # o ramo de (DE) vai de 1 a 4 e cruza 3.5; F termina em 3 < 3.5 -> sem clado


def test_distance_leaves_before_cut_unassigned():
    t = parse_newick_string(BIN)
    groups = clades_by_distance(t, 3.5)
    assert all("F" not in g for g in groups)
    assert _check_partition(t, groups) is False  # nem todas as folhas cobertas


@pytest.mark.parametrize("d", [0, -1, 999])
def test_distance_out_of_range(d):
    assert clades_by_distance(parse_newick_string(BIN), d) == []


def test_resolve_and_assign_innermost_wins():
    t = parse_newick_string(BIN)
    outer = Clade("outer", frozenset("ABCDE"))
    inner = Clade("inner", frozenset("AB"), color="#ff0000")
    res = resolve_clades(t, [outer, inner], PAL)
    assert [r.valid for r in res] == [True, True]
    assert res[0].color == PAL[0] and res[1].color == "#ff0000"
    assign = assign_nodes(t, res)
    assert assign[t.find_leaf("A")].clade is inner
    assert assign[t.find_leaf("C")].clade is outer
    assert t.find_leaf("F") not in assign


def test_hidden_clade_not_assigned():
    t = parse_newick_string(BIN)
    c = Clade("x", frozenset("DE"), visible=False)
    assert assign_nodes(t, resolve_clades(t, [c], PAL)) == {}


def test_reroot_keeps_or_breaks_clade():
    t = parse_newick_string(BIN)
    keep = Clade("de", frozenset("DE"))
    broken = Clade("abcde", frozenset("ABCDE"))
    t.reroot_outgroup("A")
    res = resolve_clades(t, [keep, broken], PAL)
    assert res[0].valid
    assert not res[1].valid and "monofilético" in res[1].problem


def test_missing_leaves_invalid():
    t = parse_newick_string(BIN)
    (r,) = resolve_clades(t, [Clade("z", frozenset({"A", "ZZZ"}))], PAL)
    assert not r.valid and "ausente" in r.problem


def test_cladeset_auto_replaces_only_auto():
    cs = CladeSet()
    cs.add_manual(frozenset("AB"), "meu")
    cs.replace_auto([frozenset("DE"), frozenset("FGH")], "k")
    assert [c.name for c in cs.clades] == ["Clado 1", "Clado 2", "meu"]
    cs.replace_auto([frozenset("C")], "k")
    assert [c.name for c in cs.clades] == ["Clado 1", "meu"]
    cs.clear_auto()
    assert [c.name for c in cs.clades] == ["meu"]
