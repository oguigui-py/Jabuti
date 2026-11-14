import math

from jabuti.layout.circular import circular_layout
from jabuti.layout.rectangular import rectangular_layout
from jabuti.parsers.newick import load_tree


def test_rectangular(data_dir):
    t = load_tree(data_dir / "small.nwk")
    lay = rectangular_layout(t)
    ys = [lay.pos[l][1] for l in lay.leaf_order]
    assert ys == [0, 1, 2, 3, 4]
    assert lay.pos[t.root] == (0.0, 2.25)  # média do 1º e último filho
    assert lay.max_x == 0.6
    # nó interno no meio dos filhos
    for n in t.root.traverse_preorder():
        if n.children:
            assert lay.pos[n][1] == (lay.pos[n.children[0]][1] + lay.pos[n.children[-1]][1]) / 2
            assert all(lay.pos[c][0] >= lay.pos[n][0] for c in n.children)


def test_cladogram_aligns_leaves(data_dir):
    t = load_tree(data_dir / "nolengths.nwk")
    lay = rectangular_layout(t)
    assert not lay.uses_lengths
    assert {lay.pos[l][0] for l in lay.leaf_order} == {lay.max_x}


def test_circular(data_dir):
    t = load_tree(data_dir / "iqtree_ufboot.treefile")
    lay = circular_layout(t)
    angles = [lay.pos[l][1] for l in lay.leaf_order]
    assert len(set(angles)) == len(angles)
    assert all(0 <= a < 2 * math.pi for a in angles)
    assert angles == sorted(angles)
    assert lay.pos[t.root][0] == 0


def test_circular_even_spacing_including_wraparound(data_dir):
    t = load_tree(data_dir / "iqtree_ufboot.treefile")
    lay = circular_layout(t)
    angles = [lay.pos[l][1] for l in lay.leaf_order]
    gaps = [b - a for a, b in zip(angles, angles[1:])] + [2 * math.pi - angles[-1] + angles[0]]
    assert max(gaps) - min(gaps) < 1e-9


def test_partial_fan(data_dir):
    t = load_tree(data_dir / "small.nwk")
    lay = circular_layout(t, arc_degrees=180)
    angles = [lay.pos[l][1] for l in lay.leaf_order]
    assert angles[0] == 0 and math.isclose(angles[-1], math.pi)
