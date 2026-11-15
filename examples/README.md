# Exemplos

`paraburkholderia_40.treefile` — árvore **sintética** (nomes e valores inventados) no formato do
IQ-TREE (`SH-aLRT/UFBoot`), com 40 folhas, para testar clados, colapso e estilos.
Não são dados reais.

`gff/*.gff3` — 22 GFF3 **sintéticos** (um por linhagem; o nome do arquivo é o fim do nome da
folha, ex.: `A00.gff3` ↔ `Paraburkholderia_xenovorans_A00`) com presença aleatória de genes
*nif*, *nod*, *hupL* e *acdS*. As outras 18 folhas ficam sem GFF de propósito (aparecem como “sem GFF”).

`metadata.tsv` — metadados **sintéticos** (espécie, habitat, simbionte, %GC) com a linhagem
como chave.

`traits.tsv` — características **sintéticas** por linhagem (tamanho do genoma em Mb, nº de
contigs com dois `NA`, contagens de CAZy por classe GH/GT/CE/AA/CBM/PL), para testar as colunas
de barras do painel Figura.

`cazy_counts.tsv` — matriz **sintética** genomas × 31 famílias CAZy (contagens inventadas),
para testar a matriz (heatmap externo) do painel Figura.

`itol/*.txt` — anotações **sintéticas** no formato do iTOL, com as folhas de
`paraburkholderia_40.treefile`: `tree_colors.txt` (TAB: faixas, ramos, rótulos), `labels.txt`
(COMMA, com aspas), `colorstrip.txt` (SPACE, com legenda) e `styles.txt` (DATASET_STYLE). Todos têm
comentários; `tree_colors.txt` e `colorstrip.txt` têm um ID de folha inexistente, que aparece em
“Problemas na leitura”.
