import pytest

from jabuti.models.tree import Tree
from jabuti.parsers.newick import parse_newick_string


def leaf_dist(t: Tree, a: str, b: str) -> float:
    la, lb = t.find_leaf(a), t.find_leaf(b)
    anc_a = [la, *la.ancestors()]
    anc_b = [lb, *lb.ancestors()]
    lca = next(n for n in anc_a if n in anc_b)
    return sum(n.length or 0 for n in anc_a[: anc_a.index(lca)]) + sum(
        n.length or 0 for n in anc_b[: anc_b.index(lca)]
    )


def all_dists(t: Tree) -> dict:
    names = sorted(t.leaf_names())
    return {(a, b): leaf_dist(t, a, b) for a in names for b in names if a < b}


def check_structure(t: Tree) -> None:
    for n in t.root.traverse_preorder():
        for c in n.children:
            assert c.parent is n
    assert t.root.parent is None


def test_copy_is_independent(data_dir):
    from jabuti.parsers.newick import load_tree

    t = load_tree(data_dir / "iqtree_ufboot.treefile")
    c = t.copy()
    c.reroot_midpoint()
    assert all_dists(t) == pytest.approx(all_dists(c))
    assert t.root is not c.root


def test_outgroup_preserves_distances(data_dir):
    from jabuti.parsers.newick import load_tree

    t = load_tree(data_dir / "small.nwk")
    before = all_dists(t)
    t.reroot_outgroup("E")
    check_structure(t)
    assert len(t.root.children) == 2
    assert t.find_leaf("E").parent is t.root
    assert all_dists(t) == pytest.approx(before)
    assert sorted(t.leaf_names()) == ["A", "B", "C", "D", "E"]


def test_midpoint():
    # A e D são as folhas mais distantes: 1+1+5 = 7 -> meio a 3.5 de cada
    t = parse_newick_string("((A:1,B:1):1,(C:1,D:5):0);")
    before = all_dists(t)
    t.reroot_midpoint()
    check_structure(t)
    assert all_dists(t) == pytest.approx(before)
    a, d = t.find_leaf("A"), t.find_leaf("D")

    def to_root(n):
        return sum(x.length or 0 for x in [n, *n.ancestors()][:-1])

    assert to_root(a) == pytest.approx(3.5)
    assert to_root(d) == pytest.approx(3.5)


def _splits(t: Tree) -> dict:
    """Bipartição (lado sem a folha 'A') -> suportes; independe da raiz."""
    all_leaves = frozenset(t.leaf_names())
    out = {}
    for n in t.root.traverse_preorder():
        if n.is_leaf or not n.supports:
            continue
        side = frozenset(l.name for l in n.leaves())
        if "A" in side:
            side = all_leaves - side
        out[side] = tuple(n.supports)
    return out


@pytest.mark.parametrize("outgroup", ["A", "B", "C", "D", "E", "F"])
def test_reroot_keeps_supports_on_bipartitions(outgroup):
    t = parse_newick_string("(A:1,(B:1,(C:1,D:1)80/81:1)90/91:1,(E:1,F:1)70/71:1);")
    before = _splits(t)
    t.reroot_outgroup(outgroup)
    check_structure(t)
    assert _splits(t) == before


def test_midpoint_keeps_supports():
    t = parse_newick_string("(A:1,(B:1,(C:1,D:9)80:1)90:1,(E:1,F:1)70:1);")
    before = _splits(t)
    t.reroot_midpoint()
    assert _splits(t) == before


def test_outgroup_unknown_leaf(data_dir):
    from jabuti.parsers.newick import load_tree

    t = load_tree(data_dir / "small.nwk")
    with pytest.raises(ValueError):
        t.reroot_outgroup("ZZZ")
