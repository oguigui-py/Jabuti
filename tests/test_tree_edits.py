import math

import pytest

from jabuti.layout.circular import circular_layout
from jabuti.layout.rectangular import rectangular_layout, visible_nodes
from jabuti.models.document import TreeEdits, apply_edits, collapsed_nodes, ladderize, resolve_nodes
from jabuti.parsers.newick import parse_newick_string

T = "((A:1,(B:1,C:1):1):1,(D:1,(E:1,(F:1,G:1):1):1):1,H:1);"


def tip_names(tree):
    return tree.leaf_names()


def test_ladderize_asc_desc():
    t = parse_newick_string(T)
    ladderize(t, "asc")
    assert [len(c.leaves()) for c in t.root.children] == [1, 3, 4]
    assert tip_names(t)[0] == "H"
    ladderize(t, "desc")
    assert [len(c.leaves()) for c in t.root.children] == [4, 3, 1]
    assert tip_names(t)[-1] == "H"


def test_ladderize_keeps_topology():
    t = parse_newick_string(T)
    before = {frozenset(l.name for l in n.leaves()) for n in t.root.traverse_preorder()}
    ladderize(t, "desc")
    after = {frozenset(l.name for l in n.leaves()) for n in t.root.traverse_preorder()}
    assert before == after


def test_apply_edits_does_not_touch_original():
    t = parse_newick_string(T)
    order = tip_names(t)
    out = apply_edits(t, TreeEdits(ladderize="desc", rotations=[frozenset("BC")]))
    assert tip_names(t) == order
    assert tip_names(out) != order


def test_rotation_toggle():
    t = parse_newick_string(T)
    e = TreeEdits()
    e.toggle_rotation(frozenset("ABC"))
    assert tip_names(apply_edits(t, e))[:3] == ["B", "C", "A"]
    e.toggle_rotation(frozenset("ABC"))  # girar de novo desfaz
    assert tip_names(apply_edits(t, e)) == tip_names(t)


def test_rotation_after_ladderize():
    t = parse_newick_string(T)
    e = TreeEdits(ladderize="asc", rotations=[frozenset("ABCDEFGH")])
    assert [len(c.leaves()) for c in apply_edits(t, e).root.children] == [4, 3, 1]


def test_edits_survive_reroot():
    t = parse_newick_string(T)
    t.reroot_outgroup("H")
    e = TreeEdits(rotations=[frozenset("BC")], collapsed=[frozenset("EFG")])
    out = apply_edits(t, e)
    assert len(resolve_nodes(out, e.rotations)) == 1
    assert len(collapsed_nodes(out, e)) == 1


def test_collapsed_nested_and_invalid_ignored():
    t = parse_newick_string(T)
    e = TreeEdits(collapsed=[frozenset("DEFG"), frozenset("FG"), frozenset("AD")])
    (node,) = collapsed_nodes(t, e)
    assert {l.name for l in node.leaves()} == set("DEFG")


def test_rectangular_collapsed_layout():
    t = parse_newick_string(T)
    col = collapsed_nodes(t, TreeEdits(collapsed=[frozenset("DEFG")]))
    lay = rectangular_layout(t, collapsed=col)
    (node,) = col
    assert [l.name for l in lay.leaf_order] == ["A", "B", "C", "H"]
    assert lay.n_slots == 3 + 2 + 1
    assert all(n not in lay.pos for n in node.traverse_preorder() if n is not node)
    assert lay.pos[node][1] == pytest.approx(3.5)        # centro das 2 posições (3 e 4)
    assert lay.span[node] == (2.5, 4.5)
    assert lay.pos[t.find_leaf("H")][1] == 5
    assert lay.collapsed[node] == pytest.approx(4.0)     # F/G: 1+1+1+1 da raiz
    assert node in visible_nodes(t, col)


def test_circular_collapsed_layout():
    t = parse_newick_string(T)
    col = collapsed_nodes(t, TreeEdits(collapsed=[frozenset("DEFG")]))
    lay = circular_layout(t, collapsed=col)
    step = 2 * math.pi / 6
    (node,) = col
    a, b = lay.span[node]
    assert b - a == pytest.approx(2 * step)
    assert lay.pos[node][1] == pytest.approx((a + b) / 2)


def test_no_collapse_unchanged():
    t = parse_newick_string(T)
    lay = rectangular_layout(t)
    assert [lay.pos[l][1] for l in lay.leaf_order] == list(range(8))
    assert lay.span[t.root] == (-0.5, 7.5)
