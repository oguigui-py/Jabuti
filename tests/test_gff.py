import pytest

from jabuti.parsers.gff import GeneQuery, GffParseError, find_genes, genome_name_from_path, neighbors, parse_gff3

D = "tests/data/gff"


def test_parse_prokka_with_fasta(data_dir):
    g = parse_gff3(data_dir / "gff" / "LB400.gff3")
    assert g.name == "LB400"
    assert g.warnings == []
    # CDS (5) + tRNA (1); genes com CDS filho não contam em dobro
    assert g.n_genes == 6
    nifh = g.genes[0]
    assert nifh.type == "CDS" and nifh.gene == "nifH" and nifh.locus_tag == "BXE_0001"  # herdado
    assert nifh.product == "nitrogenase iron protein NifH"


def test_url_decoding(data_dir):
    g = parse_gff3(data_dir / "gff" / "LB400.gff3")
    noda = next(f for f in g.genes if f.gene == "nodA")
    assert noda.product == "nodulation protein A, acyltransferase"
    assert noda.strand == "-"


def test_gzip_and_name(data_dir):
    g = parse_gff3(data_dir / "gff" / "STM815_copy.gff3.gz")
    assert g.name == "STM815_copy" and g.n_genes == 4


@pytest.mark.parametrize("fname, expected", [
    ("a.gff", "a"), ("a.gff3", "a"), ("a.gff3.gz", "a"), ("GCF_1.2_ASM.gff", "GCF_1.2_ASM"),
])
def test_genome_name(fname, expected):
    assert genome_name_from_path(fname) == expected


def test_partial_file_warns_with_line_numbers(data_dir):
    g = parse_gff3(data_dir / "gff" / "partial.gff3")
    assert g.n_genes == 1
    assert any("Linha 3" in w for w in g.warnings)
    assert any("Linha 4" in w for w in g.warnings)


@pytest.mark.parametrize("fname, fragment", [
    ("broken.gff3", "não ser GFF3"),
    ("nao_existe.gff3", "não encontrado"),
])
def test_errors(data_dir, fname, fragment):
    with pytest.raises(GffParseError) as exc:
        parse_gff3(data_dir / "gff" / fname)
    assert fragment in exc.value.user_message() and fname in exc.value.user_message()


def test_empty_file(tmp_path):
    p = tmp_path / "e.gff3"
    p.write_text("##gff-version 3\n", encoding="utf-8")
    with pytest.raises(GffParseError, match="Nenhuma feature"):
        parse_gff3(p)


def test_search_substring_fields(data_dir):
    g = parse_gff3(data_dir / "gff" / "STM815.gff3")
    assert len(find_genes(g, GeneQuery("nifH"))) == 2                      # nome do gene
    assert len(find_genes(g, GeneQuery("NITROGENASE"))) == 2               # produto, sem maiúsculas
    assert len(find_genes(g, GeneQuery("BPHY_0002", fields=("locus_tag",)))) == 1
    assert find_genes(g, GeneQuery("nifH", fields=("locus_tag",))) == []
    assert find_genes(g, GeneQuery("   ")) == []


def test_search_regex(data_dir):
    g = parse_gff3(data_dir / "gff" / "LB400.gff3")
    hits = find_genes(g, GeneQuery(r"^nif[DK]$", fields=("gene",), regex=True))
    assert sorted(f.gene for f in hits) == ["nifD", "nifK"]
    with pytest.raises(ValueError, match="regular inválida"):
        find_genes(g, GeneQuery("nif[", regex=True))


def test_neighbors(data_dir):
    g = parse_gff3(data_dir / "gff" / "LB400.gff3")
    nifd = next(f for f in g.genes if f.gene == "nifD")
    assert [f.gene or f.locus_tag for f in neighbors(g, nifd, 1)] == ["nifH", "nifD", "nifK"]
    first = g.genes[0]
    assert neighbors(g, first, 2)[0] is first


def test_neighbors_same_contig_only(data_dir):
    g = parse_gff3(data_dir / "gff" / "STM815.gff3")
    rrna = next(f for f in g.genes if f.type == "rRNA")
    assert neighbors(g, rrna, 5) == [rrna]
