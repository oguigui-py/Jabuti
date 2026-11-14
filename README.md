# Jabuti

Visualizador **offline** de árvores filogenéticas para genomas de procariotos (ex.: *Paraburkholderia*),
no estilo de um iTOL simplificado. App desktop em Python + PySide6 (macOS e Windows), sem servidor e sem internet.

**Já funciona:** abrir Newick / `.treefile` (IQ-TREE), resumo e suporte (bootstrap, `SH-aLRT/UFBoot`),
enraizamento midpoint ou por folha, layouts retangular e circular (pontas alinhadas no anel
externo, estilo iTOL), clados coloridos, estilos de linha, rótulos e símbolos, edição da árvore
(ladderize, girar, colapsar), presets JSON, zoom/pan, busca de folhas e exportação SVG / PDF / PNG.
**Próximas fases:** GFF3 + busca de genes (heatmap de presença/ausência), metadados TSV/CSV,
anotações iTOL simples e builds `.app` / `.exe`.

## GFF3 e heatmap de genes (aba **GFF**)

- *Adicionar GFF3…* aceita vários arquivos (`.gff`, `.gff3`, também `.gz`; Prokka, Bakta, NCBI).
  O nome do arquivo é casado com a folha automaticamente (ignora maiúsculas e `_`/espaço/`.`/`-`,
  aceita prefixo ou sufixo único: `LB400.gff3` ↔ `Paraburkholderia_xenovorans_LB400`).
  O mapeamento é editável por linha (✓ automático, ✎ manual, ⚠ sem folha).
- *Buscar genes* por produto, nome/gene e/ou `locus_tag`, em texto ou regex. *Prévia* lista os
  genes encontrados; *Adicionar coluna* cria uma coluna do heatmap (ordem ajustável).
- O heatmap fica à direita dos rótulos no retangular e em anéis entre as pontas e os rótulos no
  circular. Folha sem GFF aparece como **sem GFF** (cinza), diferente de **ausente** (branco);
  clados colapsados com valores diferentes aparecem como “misto”. Cores, largura, nº de cópias,
  nomes das colunas e bordas ficam na seção *Heatmap de genes* do painel.

Exemplos sintéticos: `examples/gff/*.gff3` (22 genomas) para `examples/paraburkholderia_40.treefile`.

## Personalização (painel **Estilo**, à direita)

Seções recolhíveis; tudo atualiza o desenho na hora e sai igual no SVG/PDF/PNG.

- **Clados e paleta** — detecção automática por *número de clados (k)*, *suporte mínimo*
  (UFBoot, SH-aLRT ou ambos), *distância da raiz* (slider com linha de corte) ou *manual*
  (clique direito num nó → “Definir como clado”). Cada clado recebe uma cor da paleta; trocar
  a paleta recolore, e clicar na amostra do clado escolhe uma cor própria. A cor pode ir para
  ramos, rótulos, faixa de fundo translúcida e faixa externa (anel no circular, coluna no
  retangular), com nome do clado opcional (curvo ou radial no circular). Lista com renomear
  (duplo clique), ocultar e remover; folhas fora de clados usam a cor neutra.
  Clados manuais sobrevivem a reenraizamentos (⚠ se deixarem de ser monofiléticos).
  Em árvores não enraizadas (raiz com 3 filhos) o k pode ser ultrapassado no menor corte possível.
- **Ramos** — cor padrão, espessura, ponta reta ou arredondada e, opcionalmente, espessura
  proporcional ao suporte (mín./máx.; usa o valor escolhido em *Símbolos e suporte*).
- **Ligações folha → anel** (circular alinhado) — contínua, tracejada, pontilhada com pontos
  pequenos ou maiores, ou nenhuma; cor, espessura e opacidade.
- **Rótulos** — mostrar/ocultar, fonte (padrão do sistema ou qualquer família instalada),
  tamanho, negrito e itálico (ligado por padrão, para nomes de espécie).
- **Símbolos e suporte** — símbolo nas pontas (círculo, quadrado, losango ou nenhum; tamanho;
  cor fixa ou do clado). Suporte dos nós como números (com limiar para ocultar) ou como
  símbolos: círculo cheio se ≥ limiar e vazado abaixo, com tamanho opcionalmente proporcional
  ao valor. Escolha do valor: UFBoot, SH-aLRT ou ambos.
- **Barra de escala** — mostrar/ocultar, canto (4 posições) e comprimento automático ou fixo.
- **Árvore e fundo** — ladderize (crescente/decrescente), desfazer rotações, expandir todos;
  fundo em cor ou transparente (o PNG sai com transparência; na tela aparece um xadrez).
  Clique direito num nó: *girar nó* (inverter filhos), *colapsar em triângulo* (com nome do
  clado e nº de folhas) ou *expandir*. Rotações e colapsos também sobrevivem a reenraizamentos.
- **Presets** — *Salvar/Carregar preset* grava todas as configurações visuais em JSON, inclusive
  clados (por nomes de folhas), parâmetros de detecção, ladderize, rotações e colapsos.
  *Salvar como meu padrão* guarda só estilo e detecção, aplicados ao abrir o app;
  *Restaurar padrão* volta ao padrão de fábrica do estilo sem apagar clados nem edições.
  Opções desconhecidas são ignoradas e valores inválidos geram aviso (o padrão é mantido);
  clados com folhas que não existem na árvore aberta aparecem com ⚠.

A aba **Visualização** fica com layout, comprimentos/cladograma, alinhamento no anel,
escala dos ramos, espaço entre folhas e exportação.

Exemplo para testar: `python -m jabuti examples/paraburkholderia_40.treefile` (árvore sintética).

## Ambiente (Conda)

```bash
conda env create -f environment.yml
conda activate jabuti
```

## Rodar

```bash
python -m jabuti                    # ou: python -m jabuti minha_arvore.treefile
QT_QPA_PLATFORM=offscreen pytest    # testes
```
