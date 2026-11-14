import pytest

from jabuti.parsers.errors import TreeParseError
from jabuti.parsers.newick import load_tree, parse_newick_string


def test_small_tree(data_dir):
    t = load_tree(data_dir / "small.nwk")
    assert sorted(t.leaf_names()) == ["A", "B", "C", "D", "E"]
    s = t.summary()
    assert s.n_leaves == 5
    assert s.has_lengths
    assert not s.has_support
    assert t.find_leaf("E").length == pytest.approx(0.6)


def test_iqtree_shalrt_ufboot(data_dir):
    t = load_tree(data_dir / "iqtree_ufboot.treefile")
    s = t.summary()
    assert s.n_leaves == 6
    assert s.has_support and s.support_values_per_node == 2
    supports = sorted(tuple(n.supports) for n in t.root.traverse_preorder() if n.supports)
    assert supports == [(87.2, 95.0), (98.7, 100.0), (100.0, 100.0)]
    # rótulos de suporte não viram nomes de nós internos
    assert all(not n.name for n in t.root.traverse_preorder() if not n.is_leaf)
    assert "Paraburkholderia tropica Ppe8" in t.leaf_names()


def test_single_bootstrap(data_dir):
    t = load_tree(data_dir / "bootstrap.nwk")
    assert t.summary().support_values_per_node == 1
    assert sorted(n.supports[0] for n in t.root.traverse_preorder() if n.supports) == [45, 90]


def test_no_lengths(data_dir):
    s = load_tree(data_dir / "nolengths.nwk").summary()
    assert s.n_leaves == 5 and not s.has_lengths


def test_multiple_trees_takes_first():
    t = parse_newick_string("(A,B);\n(C,D,E);\n")
    assert t.leaf_names() == ["A", "B"]


def test_missing_semicolon_ok():
    assert len(parse_newick_string("(A:1,B:2)").leaves()) == 2


def test_duplicate_names_reported():
    assert parse_newick_string("(A,A,B);").summary().duplicate_leaf_names == ["A"]


@pytest.mark.parametrize(
    "fname, fragment",
    [
        ("malformed_parens.nwk", "Parênteses"),
        ("malformed_length.nwk", "Comprimento de ramo inválido"),
        ("empty.nwk", "vazio"),
        ("not_newick.txt", "não parece Newick"),
        ("does_not_exist.nwk", "não encontrado"),
    ],
)
def test_errors(data_dir, fname, fragment):
    with pytest.raises(TreeParseError) as exc:
        load_tree(data_dir / fname)
    assert fragment in exc.value.user_message()
    assert fname in exc.value.user_message()


def test_error_has_line_number(data_dir):
    with pytest.raises(TreeParseError) as exc:
        load_tree(data_dir / "malformed_length.nwk")
    assert exc.value.line == 2
