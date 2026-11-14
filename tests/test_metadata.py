import pytest

from jabuti.parsers.metadata import (
    MetadataParseError,
    column_is_numeric,
    guess_key_column,
    load_metadata,
    match_table,
    parse_table_text,
)
from jabuti.parsers.names import match_names, normalize
from jabuti.parsers.newick import load_tree


def test_tsv(data_dir):
    t = load_metadata(data_dir / "meta.tsv")
    assert t.delimiter == "\t"
    assert t.columns == ["genome", "species", "origin", "gc"]
    assert len(t.rows) == 6 and t.warnings == []


def test_semicolon_csv(data_dir):
    t = load_metadata(data_dir / "meta_semicolon.csv")
    assert t.delimiter == ";" and t.columns == ["id", "habitat", "n"]
    assert t.rows[1]["habitat"] == ""


def test_match_with_tolerant_names(data_dir):
    tree = load_tree(data_dir / "iqtree_ufboot.treefile")
    t = load_metadata(data_dir / "meta.tsv")
    m = match_table(t, "genome", tree.leaf_names())
    assert len(m.by_leaf) == 5
    assert m.by_leaf["Paraburkholderia tropica Ppe8"]["origin"] == "rhizosphere"
    assert m.leaves_without == ["Burkholderia_cenocepacia_J2315"]
    assert m.unused_keys == ["EXTRA_GENOME"]


def test_match_hyphen_vs_underscore(data_dir):
    tree = load_tree(data_dir / "iqtree_ufboot.treefile")
    t = load_metadata(data_dir / "meta_semicolon.csv")
    m = match_table(t, "id", tree.leaf_names())
    assert "Paraburkholderia_xenovorans_LB400" in m.by_leaf


def test_guess_key_column(data_dir):
    tree = load_tree(data_dir / "iqtree_ufboot.treefile")
    t = parse_table_text("species\tgenome\nA\tParaburkholderia_xenovorans_LB400\nB\tBurkholderia_cepacia_ATCC25416\n")
    assert guess_key_column(t, tree.leaf_names()) == "genome"


def test_ragged_rows_warn():
    t = parse_table_text("a,b,c\n1,2\n3,4,5,6\n")
    assert len(t.warnings) == 2 and t.rows[0]["c"] == ""


def test_duplicate_columns_renamed():
    t = parse_table_text("id\tx\tx\n1\t2\t3\n")
    assert t.columns == ["id", "x", "x_2"] and t.warnings


@pytest.mark.parametrize("text, fragment", [
    ("", "vazio"),
    ("apenas_uma_coluna\nvalor\n", "separador"),
    ("a\tb\n", "só tem cabeçalho"),
])
def test_errors(text, fragment):
    with pytest.raises(MetadataParseError, match=fragment):
        parse_table_text(text)


def test_numeric_detection():
    assert column_is_numeric(["62.6", "63,9", "NA", "66.7"])
    assert not column_is_numeric(["soil", "62"])
    assert not column_is_numeric(["0", "1", "1", "0"])  # binário vira categoria


@pytest.mark.parametrize("raw, norm", [
    ("Paraburkholderia tropica Ppe8", "paraburkholderia_tropica_ppe8"),
    ("Para-burk.LB400", "para_burk_lb400"),
    ("'Quoted Name'", "quoted_name"),
])
def test_normalize(raw, norm):
    assert normalize(raw) == norm


def test_match_names_prefix():
    leaves = ["GCF_000012345.1", "GCF_000099999.1", "strainA", "strainA_2"]
    m = match_names(["GCF_000012345.1_ASM1v1_genomic", "strainA_x"], leaves)
    assert m == {"GCF_000012345.1_ASM1v1_genomic": "GCF_000012345.1", "strainA_x": "strainA"}


def test_match_names_ambiguous_prefix_is_not_matched():
    assert match_names(["strain"], ["strain_1", "strain_2"]) == {}


def test_match_names_exact_wins_and_no_leaf_reuse():
    m = match_names(["A", "a"], ["A"])
    assert m == {"A": "A"}


def test_match_names_suffix():
    leaves = ["Paraburkholderia_xenovorans_LB400", "Paraburkholderia_phymatum_STM815", "X_1", "Y_1"]
    m = match_names(["LB400", "STM815", "1"], leaves)
    assert m == {"LB400": "Paraburkholderia_xenovorans_LB400", "STM815": "Paraburkholderia_phymatum_STM815"}
