# Jabuti

Visualizador **offline** de árvores filogenéticas para genomas de procariotos (ex.: *Paraburkholderia*),
no estilo de um iTOL simplificado. App desktop em Python + PySide6 (macOS e Windows), sem servidor e sem internet.

**Já funciona:** GFF3 (heatmap de genes e contexto gênico), metadados TSV/CSV, abrir Newick / `.treefile` (IQ-TREE), resumo e suporte (bootstrap, `SH-aLRT/UFBoot`),
enraizamento midpoint, por folha ou no grupo selecionado, layouts retangular, circular (pontas
alinhadas no anel externo, estilo iTOL), leque, diagonal e não enraizado, colunas de dados
(barras, barras empilhadas, matriz), clados coloridos, estilos de linha, rótulos e símbolos, edição da árvore
(ladderize, girar, colapsar), presets JSON, zoom/pan, busca de folhas e exportação SVG / PDF / PNG / TIFF.
**Próximas fases:** anotações iTOL simples e builds `.app` / `.exe`.

## GFF3 e heatmap de genes (aba **GFF**)

- *Adicionar GFF3…* aceita vários arquivos (`.gff`, `.gff3`, também `.gz`; Prokka, Bakta, NCBI).
  O nome do arquivo é casado com a folha automaticamente (ignora maiúsculas e `_`/espaço/`.`/`-`,
  aceita prefixo ou sufixo único: `LB400.gff3` ↔ `Paraburkholderia_xenovorans_LB400`).
  O mapeamento é editável por linha (✓ automático, ✎ manual, ⚠ sem folha).
- A leitura roda em segundo plano: a janela continua respondendo, com barra de progresso e
  botão *Cancelar*. Erros e avisos aparecem em *Problemas na leitura*, sem travar. Arquivos já
  lidos não são relidos (cache por caminho, data de modificação e tamanho); *Recarregar* relê só
  os que mudaram. Buscas também ficam em cache: mudar o mapeamento ou o estilo não refaz buscas.
- *Buscar genes* por produto, nome/gene e/ou `locus_tag`, em texto ou regex. *Prévia* lista os
  genes encontrados; *Adicionar coluna* cria uma coluna do heatmap (ordem ajustável).
- O heatmap fica à direita dos rótulos no retangular e em anéis entre as pontas e os rótulos no
  circular. Folha sem GFF aparece como **sem GFF** (cinza), diferente de **ausente** (branco);
  clados colapsados com valores diferentes aparecem como “misto”. Cores, largura, nº de cópias,
  nomes das colunas e bordas ficam na seção *Heatmap de genes* do painel.
- **Contexto gênico** (layout retangular): na aba GFF, ligue *Mostrar vizinhos do gene âncora*,
  escolha a coluna âncora e ±N vizinhos. Cada genoma mostra o primeiro gene que casa com a
  âncora e seus vizinhos no mesmo contig, como setas proporcionais ao tamanho; a janela é
  espelhada para o âncora apontar sempre para a direita (alinha os genomas). Genes que casam
  com outras colunas usam a cor delas (paleta), os demais ficam cinza; nomes aparecem dentro
  das setas quando cabem. Largura e nomes ficam no painel (*Heatmap de genes*).

Exemplos sintéticos: `examples/gff/*.gff3` (22 genomas) para `examples/paraburkholderia_40.treefile`.

## Metadados (aba **Metadados**)

- *Abrir TSV/CSV…* (TAB, vírgula ou ponto e vírgula; com cabeçalho; uma linha por genoma).
  A coluna com o nome da folha é detectada automaticamente (pode trocar) e o casamento usa as
  mesmas regras tolerantes dos GFFs. O relatório lista folhas sem metadados e linhas sem folha.
- No painel, *Metadados e legenda*: **colorir por coluna** os rótulos e/ou os ramos (categorias
  com a paleta, mais frequentes primeiro; colunas numéricas em gradiente). A cor do metadado tem
  prioridade sobre a dos clados; um ramo interno só é colorido se todas as folhas abaixo dele
  concordam. **Faixas de cor**: marque colunas para desenhá-las ao lado da árvore (anéis no
  circular), antes do heatmap de genes. Valores ausentes (`NA`, vazio, `-`…) usam a cor “sem valor”.
- A legenda agrupa clados, grupos de rótulos, cor por metadado, faixas, heatmap e (no circular)
  a ordem dos anéis. **Incluir legenda na figura exportada** (desligado por padrão) desenha essa
  mesma legenda na figura, ao lado do desenho (direita ou esquerda, alinhada em cima ou embaixo),
  sem cobrir árvore, heatmap nem barra de escala; aparece também na tela e sai igual no
  SVG/PDF/PNG. A escolha vai para os presets.

Exemplo sintético: `examples/metadata.tsv` (chave = linhagem).

## Painel **Figura** (à esquerda)

Painel fixo na borda esquerda, com seções recolhíveis; o botão «/» recolhe o painel numa
faixa estreita e devolve o espaço ao desenho. **Tudo vem desligado**: sem nada ativado ali, o
desenho é exatamente o de antes. As opções vão para os presets (os dados carregados, não).

### Colunas de dados

- **Tabelas de dados** — *Carregar tabela…* lê TSV/CSV em segundo plano (a janela continua
  respondendo). A 1ª coluna é o nome do genoma/folha; `NA`, vazio, `-`… = sem dado. O
  casamento com as folhas é automático e editável na mesma tabela da aba GFF (✓ / ✎ / ⚠); o
  relatório lista as folhas sem dados. A tabela da aba **Metadados** também pode ser usada.
- **Barras** — *+ Barras* cria uma coluna de barras a partir de uma coluna numérica: cor única,
  por clado ou por metadado (a coluna de *Colorir por* do painel Estilo), valor ao lado da barra,
  linhas de referência tracejadas (ex.: `4; 8` — vírgula sem espaço é decimal), mínimo/máximo
  (automático = de 0, ou do menor valor negativo, até o maior) e largura. No retangular a coluna
  tem eixo com mínimo, referências e máximo; no circular as barras são radiais e as referências
  viram arcos tracejados. Folha sem dado mostra um traço curto; clado colapsado usa a média.
  As colunas entram depois das faixas de metadados e do heatmap de genes.
- **Barras empilhadas** — *+ Empilhadas* junta várias colunas numéricas (ex.: GH, GT, CE, AA,
  CBM, PL) numa barra, cada série com sua cor (clique na série e na amostra para trocar). Máximo
  automático = maior soma; série sem dado conta como 0; clado colapsado usa a média de cada série.
  A legenda ganha o grupo *Séries* com as cores.
- **Matriz (heatmap externo)** — carregue um TSV genomas × características (famílias CAZy,
  peptidases, funções do METABOLIC…) em *Tabelas de dados* e clique *+ Matriz*. Colunas: as N
  mais frequentes (soma nas folhas) ou escolhidas na lista, sempre em ordem natural
  (GH2, GH13, GT4…). Escala linear, `log(1 + x)` ou raiz; colormap (viridis, magma, cividis,
  Blues, Reds, Greens, YlOrRd, cinza); mínimo/máximo; valor dentro da célula (cor do texto
  contrasta com a célula); largura da célula; nomes das colunas a 0°, 45° ou 90° (no retangular;
  a 0°, se o nome não couber nem com fonte menor, é desenhado a 90° e a barra de status avisa).
  A legenda mostra uma **barra de cor** (também na figura exportada, como gradiente no SVG). No
  circular, cada característica é um anel, listado na legenda *Anéis*. Convive com o heatmap
  de genes (aba GFF) sem substituí-lo.
- **Escalas dos metadados numéricos** — para uma coluna numérica da aba Metadados (usada em
  faixas ou em *Colorir por*): *Colormap contínuo* (colormap, mínimo/máximo, barra de cor na
  legenda) ou *Por faixas* (pontos de corte como `5; 50; 200`, uma cor por faixa e rótulos
  automáticos ≤5, 6–50, 51–200, >200 com a contagem de folhas; com decimais: ≤a, a–b, >b).
  *Padrão* mantém o gradiente de antes. As legendas aparecem no painel e na figura exportada.
- **Ordem das colunas** — lista com todas as trilhas (faixa de clados, faixas de metadados,
  heatmap de genes como um bloco, barras, empilhadas e matrizes), da árvore para fora (anéis:
  de dentro para fora). Arraste (ou ↑/↓) para reordenar e desmarque para ocultar — a legenda
  da trilha oculta some junto. Trilhas novas entram no fim; a ordem vai para os presets.

Exemplos sintéticos: `examples/traits.tsv` (tamanho do genoma, nº de contigs com `NA` e
contagens de CAZy por classe) e `examples/cazy_counts.tsv` (matriz de 31 famílias CAZy).

### Enraizamento e poda

- **Enraizar no grupo selecionado** — selecione folhas (Cmd/Shift+clique nos nomes ou pela
  busca) e use o botão do painel, o clique direito ou *No grupo selecionado* na aba Árvore. A
  raiz vai para o ramo do ancestral comum (calculado sem depender da raiz atual); se o grupo não
  for monofilético, uma confirmação lista as folhas extras que entram. Os suportes acompanham as
  bipartições, como nos outros enraizamentos.
- **Ocultar folhas** — *Ocultar folhas selecionadas* (ou clique direito → *Ocultar*) tira as
  folhas do desenho e das colunas de dados (mínimos/máximos automáticos também passam a
  ignorá-las) e junta os ramos que ficam com um só filho, somando os comprimentos. A lista de
  ocultas tem *Restaurar selecionadas* e *Restaurar todas*; o arquivo original não muda e pelo
  menos 2 folhas continuam visíveis. Clados, colapsos e grupos de rótulo ignoram as ocultas.
- **Ramo encurtado** — clique direito numa folha ou nó → *Encurtar este ramo*. O ramo passa a
  ser desenhado com o comprimento escolhido no painel (inicialmente o maior dos outros ramos) e
  ganha a marca **//** (em todos os layouts). *Nota na legenda* acrescenta “outgroup branch not
  to scale” (texto editável). A barra de escala continua valendo para os demais ramos.

Folhas ocultas e ramos encurtados vão para os presets, junto com clados e colapsos.

### Nomes e destaques

- **Nomes de exibição** — só mudam o texto desenhado; buscas (que também aceitam o nome
  exibido), mapeamentos, seleção e presets continuam usando o nome original. Aplicados nesta
  ordem: *Tabela de nomes…* (CSV/TSV com cabeçalho: nome original, nome exibido; lida em
  segundo plano, com aviso dos nomes que não estão na árvore) → *Trocar “_” por espaço* →
  substituições por regex (procurar/trocar, em ordem; regras inválidas são avisadas e
  ignoradas) → *Abreviar gênero* (Cupriavidus necator → C. necator) → prefixo/símbolo (★) das
  folhas marcadas com *Marcar seleção*. As regras e as folhas marcadas vão para os presets; a
  tabela de nomes (dados), não.
- **Destaque de linha inteira** — *Destacar linhas da seleção* desenha uma faixa translúcida
  com contorno que atravessa o rótulo e todas as colunas (no circular, um setor até o último
  anel/rótulo), atrás de tudo. Folhas vizinhas formam uma única faixa. Cor, opacidade,
  contorno (cor e espessura) e espessura da faixa são ajustáveis por destaque.
- **Clado a partir de lista** — cole nomes (um por linha; só a 1ª coluna conta) ou carregue
  um arquivo, dê nome e cor e clique *Criar clado*. Os nomes são casados com as mesmas regras
  tolerantes dos GFFs (os não encontrados são listados); o clado é o ancestral comum. Se o
  grupo não for monofilético, uma confirmação lista as folhas extras.

### Suporte e resumo

- **Suporte em níveis** — círculos nos nós coloridos por faixas (padrão: ≥95 verde, 70–94
  amarelo, <70 vermelho), com o valor escolhido (UFBoot ou SH-aLRT, na convenção
  `SH-aLRT/UFBoot` do IQ-TREE), pontos de corte e cores editáveis, tamanho e legenda dos
  níveis. Combina com os números de suporte do painel Estilo.
- **Resumo da árvore** — folhas, nós internos e nós por faixa de suporte (UFBoot ≥95, 70–94,
  <70; SH-aLRT ≥80, <80; e os dois juntos), contados na árvore desenhada; *Copiar resumo* leva
  o texto para a área de transferência.
- **TIFF** — na aba Visualização (ou *Arquivo → Exportar TIFF…*): 600 dpi com compressão LZW
  por padrão (DPI e compressão ajustáveis), igual ao PNG. Imagens acima de 30000 px por lado
  ou ~2 GB na memória são recusadas com mensagem pedindo DPI menor (ou SVG/PDF).

### Anotações iTOL

Arquivos de anotação no formato do [iTOL](https://itol.embl.de/help.cgi) entram pelo botão
*Importar anotação iTOL…* (seção **Anotações iTOL** do painel Figura, vários arquivos de uma vez)
ou arrastando os arquivos para a janela. Um arquivo cuja 1ª linha útil é um tipo do iTOL vira
anotação; os outros continuam abrindo como árvore. A leitura roda em segundo plano.

- **Formato** — 1ª linha útil = tipo; `SEPARATOR TAB|SPACE|COMMA`; opções do cabeçalho; `DATA`;
  linhas de dados. Linhas com `#` são comentários; espaços extras e campos entre aspas são aceitos.
- **IDs** — nome de folha; `A|B` (ou `A---B`) = ancestral comum das folhas; `CONTAINS==texto` =
  cada folha cujo nome contém o texto. Os IDs são resolvidos na árvore desenhada, então seguem
  reenraizamento, ladderize e poda.
- **Problemas** — folhas ausentes, linhas malformadas e opções desconhecidas não interrompem a
  leitura: são contadas na lista e descritas em *Problemas na leitura* (`arquivo:linha → motivo`),
  com um resumo na barra de status. Um arquivo ilegível ou que não é do iTOL abre uma mensagem
  de erro com arquivo e linha.
- **Lista** — cada dataset (nome = `DATASET_LABEL` ou nome do arquivo) pode ser desligado sem ser
  removido, ou removido (✕). Arrastar na lista muda a prioridade: em conflito vale o de baixo.
  As faixas de cor entram na lista *Ordem das colunas*, como as outras colunas. Ao selecionar um
  dataset dá para editar o título e, para cada cor do arquivo, a cor usada e o texto da legenda.
- **Presets** — os arquivos são dados e não vão para o preset; o título, a visibilidade e as cores
  editadas vão (pela chave `itol:<DATASET_LABEL>`) e voltam quando o mesmo dataset é importado.
- **Prioridade** — os grupos de rótulos criados por você vencem os estilos de rótulo do iTOL, e a
  tabela de nomes (CSV) vence o `LABELS`.

| Tipo | O que vira no Jabuti |
|---|---|
| `TREE_COLORS` | `range` → faixa de fundo atrás do clado (com legenda pelos rótulos); `clade` → cor, espessura e tracejado do ramo e de tudo abaixo; `branch` → só aquele ramo; `label` → cor, negrito/itálico e tamanho do rótulo; `label_background` → fundo do rótulo |
| `LABELS` | nomes de exibição das folhas |
| `DATASET_COLORSTRIP` | faixa de cor (coluna ou anel), com `STRIP_WIDTH`, `SHOW_STRIP_LABELS`, legenda de `LEGEND_TITLE/COLORS/LABELS` (ou dos rótulos dos dados) e `COLOR_BRANCHES` |
| `DATASET_STYLE` | `branch` / `label`, para `node` ou `clade`: cor, fator de espessura ou de tamanho, `dashed` ou estilo do texto e cor de fundo do rótulo |
| `DATASET_SIMPLEBAR` | coluna de barras (`COLOR`, `WIDTH`, `MARGIN`, `SHOW_VALUE`; os valores de `DATASET_SCALE` viram linhas de referência no eixo) |
| `DATASET_MULTIBAR` | barras empilhadas (`FIELD_COLORS`, `FIELD_LABELS`, `WIDTH`, `MARGIN`), com legenda das séries; `X` = sem dado na série |
| `DATASET_HEATMAP` | matriz externa, uma coluna por campo (`FIELD_LABELS`): gradiente `COLOR_MIN` → `COLOR_MAX` ou com `USE_MID_COLOR`/`COLOR_MID`, limites `USER_MIN/MID/MAX_VALUE`, `X` = sem dado (`COLOR_NAN`), `STRIP_WIDTH` = largura da célula, `SHOW_VALUES`; legenda em barra de cor |
| `DATASET_BINARY` | colunas de presença/ausência: `1` = forma cheia, `0` = vazada, `-1` = nada; `FIELD_SHAPES` 1 quadrado, 2 círculo, 3 estrela, 4 triângulo p/ direita, 5 triângulo p/ esquerda, 6 "check"; `FIELD_COLORS` (padrão `COLOR`) e `FIELD_LABELS` |

As colunas importadas funcionam em todos os layouts com colunas (retangular, diagonal, circular,
leque), entram em *Ordem das colunas* (arrastar, ocultar), na legenda e na exportação
SVG/PDF/PNG/TIFF. Ao selecionar o dataset, as cores de cada campo (e as do gradiente do heatmap)
e os nomes dos campos podem ser editados.

Ainda **ignorados** (aparecem na lista com aviso): `DATASET_SYMBOL`, `DATASET_TEXT`, `COLLAPSE`
(próxima etapa) e `POPUP_INFO`, `DATASET_RANGE`, `DATASET_PIECHART`, `DATASET_ALIGNMENT`,
`DATASET_CONNECTION`, entre outros.

**Aproximações** em relação ao iTOL:
- **Cores:** `#rgb`, `#rrggbb`, `rgb()` e `rgba()`. A opacidade do `rgba` vale nos fundos (faixas `range` e fundo de rótulo).
- **IDs:**
  - nomes de nós internos são procurados na árvore, mas `LABELS` e estilos de rótulo de nó interno são ignorados (o Jabuti não desenha nomes de nós internos);
  - `label` do `TREE_COLORS` num nó interno vale para todas as folhas do clado;
  - em `A|B`, folhas ocultas são desconsideradas;
  - um nome que não bate exatamente é casado pelas regras tolerantes dos GFFs, e o relatório conta esses casos.
- **Separadores:** com `SEPARATOR SPACE`, um texto com espaços pode vir entre aspas; sem aspas, os campos que sobram são juntados no último campo de texto (rótulo, legenda). As linhas do cabeçalho aceitam qualquer separador (o template oficial do colorstrip mistura vírgula e espaço).
- **Faixas `range`:**
  - são desenhadas como o fundo de clado (da base do clado até o fim das colunas), com a maior por baixo quando uma está dentro de outra;
  - não aparecem na árvore não enraizada.
- **Opções do iTOL sem efeito:** de posição e borda (ex.: `LEGEND_POSITION_X`, `BORDER_WIDTH`, `MARGIN`) são lidas e ignoradas.
- **`STRIP_WIDTH`:** é usado como largura da coluna, em pontos.
- **Barras (`SIMPLEBAR`, `MULTIBAR`):**
  - `WIDTH` vale em pontos, até 600 (o padrão do iTOL, 1000, é reduzido com aviso);
  - as barras partem sempre do 0, então um `BAR_ZERO` diferente de 0 só gera aviso;
  - `LOG_SCALE`, `SIDE_STACKED` e `ALIGN_FIELDS` são ignorados com aviso;
  - no `SIMPLEBAR`, uma linha com valor não numérico (inclusive `X`) é ignorada;
  - dos itens de `DATASET_SCALE` (`valor-rótulo-cor-…`), só o valor é usado.
- **Heatmap:**
  - a escala é linear de cada lado do `USER_MID_VALUE`;
  - sem `USER_*`, os limites são o menor e o maior valor;
  - a legenda omite o rótulo do meio quando ele fica perto das pontas.
- **Presença/ausência:**
  - a legenda mostra quadrados de cor, sem as formas;
  - num clado colapsado, a forma sai cheia se alguma folha tem 1.
- **IDs de nó interno nas colunas:** um ID `A|B` em barras, heatmap ou presença/ausência vale para todas as folhas do clado.

## Personalização (painel **Estilo**, à direita)

Seções recolhíveis; tudo atualiza o desenho na hora e sai igual no SVG/PDF/PNG.

- **Clados e paleta** — detecção automática por *número de clados (k)*, *suporte mínimo*
  (UFBoot, SH-aLRT ou ambos), *distância da raiz* (slider com linha de corte) ou *manual*
  (clique direito num nó → “Definir como clado”). Cada clado recebe uma cor da paleta; trocar
  a paleta recolore, e clicar na amostra do clado escolhe uma cor própria. A cor pode ir para
  ramos, rótulos (texto), rótulos (fundo, estilo marca-texto, com opacidade própria), faixa de
  fundo translúcida e faixa externa (anel no circular, coluna no retangular) — opções
  independentes e combináveis —, com nome do clado opcional (curvo ou radial no circular).
  O botão **Aa** na lista cria um grupo de rótulos com as folhas do clado. Lista com renomear
  (duplo clique), ocultar e remover; folhas fora de clados usam a cor neutra.
  Clados manuais sobrevivem a reenraizamentos (⚠ se deixarem de ser monofiléticos).
  Em árvores não enraizadas (raiz com 3 filhos) o k pode ser ultrapassado no menor corte possível.
- **Ramos** — cor padrão, espessura, ponta reta ou arredondada e, opcionalmente, espessura
  proporcional ao suporte (mín./máx.; usa o valor escolhido em *Símbolos e suporte*).
- **Ligações folha → anel** (circular alinhado) — contínua, tracejada, pontilhada com pontos
  pequenos ou maiores, ou nenhuma; cor, espessura e opacidade.
- **Rótulos** — mostrar/ocultar, fonte (padrão do sistema ou qualquer família instalada),
  tamanho, negrito e itálico (ligado por padrão, para nomes de espécie).
  **Grupos de destaque**: estilo próprio só para os nomes de algumas folhas, sem mexer nos
  ramos — cor do texto, fundo colorido (marca-texto) com opacidade, margem interna e cantos
  arredondados, negrito, itálico e tamanho relativo. Campos deixados vazios herdam a cor de
  metadados/clado/padrão. Três jeitos de criar um grupo:
  - *por clado*: botão **Aa** na lista de clados;
  - *por seleção*: Cmd/Ctrl+clique nos nomes (alterna), Shift+clique (intervalo, também no
    circular), clique simples (só aquela folha), Esc ou clique no vazio (limpa); a busca
    (Cmd+F) também seleciona os resultados. Clique direito → *Estilizar rótulos selecionados*
    (fundo, cor do texto, negrito ou *Criar grupo*) ou o botão *Criar grupo da seleção*;
  - *por padrão de texto*: texto simples (“contém”) ou regex (ex.: `xenovorans`, `^LB400`),
    com a contagem de folhas que casam antes de aplicar.

  Cada folha fica em um único grupo efetivo: em conflito vale o criado por último (a coluna
  *Folhas* mostra “valendo/total”, e selecionar uma folha diz na barra de status qual grupo
  vale). Lista com origem, renomear, amostras de texto/fundo, ver, remover e *Limpar tudo*;
  opção de mostrar os grupos na legenda. Os fundos giram junto com o texto no circular
  (inclusive na metade invertida), nunca invadem as folhas vizinhas e empurram heatmap e
  anéis para fora; seguem as folhas após reenraizar, ladderize e colapsar. A seleção (contorno
  azul) não vai para o arquivo exportado.
- **Símbolos e suporte** — símbolo nas pontas (círculo, quadrado, losango ou nenhum; tamanho;
  cor fixa ou do clado). Suporte dos nós como números (com limiar para ocultar) ou como
  símbolos: círculo cheio se ≥ limiar e vazado abaixo, com tamanho opcionalmente proporcional
  ao valor. Escolha do valor: UFBoot, SH-aLRT ou ambos.
- **Barra de escala** — mostrar/ocultar, canto (4 posições) e comprimento automático ou fixo.
- **Árvore e fundo** — ladderize (crescente/decrescente), desfazer rotações, expandir todos;
  fundo em cor ou transparente (o PNG sai com transparência; na tela aparece um xadrez).
  **Unir fundos vizinhos** (ligado por padrão): fundos de clados, de rótulos e destaques de linha
  de grupos encostados viram um bloco contínuo quando têm a mesma cor (um caminho só, sem
  emenda e sem opacidade dobrada) e, com cores diferentes, se encontram no ponto médio entre a
  última folha de um e a primeira do outro, sem vão branco (no circular e no leque, bordas
  radiais no ângulo médio). Entre as linhas de um bloco o fundo ocupa todo o espaço; cantos
  arredondados só nas pontas externas. Grupos separados por folhas sem fundo, ou por um clado
  colapsado, continuam separados. Com fundos translúcidos de cores diferentes, a divisa ganha um
  filete de 0,25 pt da mistura das duas cores (cobre o antialiasing; nunca fica branca).
  Desmarque para o espaçamento antigo.
  Clique direito num nó: *girar nó* (inverter filhos), *colapsar em triângulo* (com nome do
  clado e nº de folhas) ou *expandir*. Rotações e colapsos também sobrevivem a reenraizamentos.
- **Presets** — *Salvar/Carregar preset* grava todas as configurações visuais em JSON, inclusive
  clados e grupos de rótulos (por nomes de folhas), parâmetros de detecção, ladderize,
  rotações e colapsos. Folhas de grupos de rótulo que não existem na árvore aberta são
  ignoradas, com a contagem na barra de status.
  *Salvar como meu padrão* guarda só estilo e detecção, aplicados ao abrir o app;
  *Restaurar padrão* volta ao padrão de fábrica do estilo sem apagar clados nem edições.
  Opções desconhecidas são ignoradas e valores inválidos geram aviso (o padrão é mantido);
  clados com folhas que não existem na árvore aberta aparecem com ⚠.

A aba **Visualização** fica com layout, comprimentos/cladograma, alinhamento no anel,
escala dos ramos, espaço entre folhas e exportação.

### Layouts

- **Retangular** e **Circular** — como antes.
- **Leque** — o circular com *ângulo* total (30°–350°, ex.: 180° ou 270°) e *início* (direção da
  primeira folha) ajustáveis. As faixas das folhas preenchem exatamente o arco, então anéis,
  clados e destaques não invadem o vão; o raio cresce quando o arco diminui, para os rótulos
  não se sobreporem. Os nomes das colunas/anéis aparecem no vão, um por anel.
- **Diagonal** — ramos inclinados, do nó pai direto ao filho; colunas à direita, clados,
  rótulos, suporte, colapso e contexto gênico como no retangular.
- **Não enraizada** — algoritmo *equal-angle* (Felsenstein), com refinamento *daylight*
  opcional (iguala os vãos entre subárvores; desativado acima de 2000 folhas), comprimentos de
  ramo proporcionais, rótulos na direção do ramo (invertidos à esquerda para leitura),
  *girar* e *espelhar*. Cores de clados (ramos e rótulos), grupos de rótulos, suporte (números,
  símbolos e níveis), colapso (leque triangular), ramo encurtado e barra de escala funcionam;
  colunas de dados, faixa/fundo/nome de clado e alinhar pontas não se aplicam (os controles
  ficam desativados com uma dica, e a barra de status avisa). Com ramos internos muito curtos
  os rótulos podem se encostar: aumente a *Escala dos ramos* ou ligue o *daylight*.

Todos respeitam reenraizamento, ladderize, colapso, folhas ocultas, ramo encurtado e a
exportação SVG/PDF/PNG/TIFF.

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

Ao abrir, uma tela de abertura (logo do LGEM sobre um fundo animado discreto)
aparece por ~3 s enquanto a janela principal é montada; clique ou qualquer tecla
pula. Um arquivo de árvore passado na linha de comando é carregado logo depois.
Para desativar a abertura: `JABUTI_NO_SPLASH=1 python -m jabuti` (os testes e o
modo `offscreen` já a desativam).

Assets (imagens) ficam em `jabuti/assets/` e são localizados por
`jabuti.resources.asset_path`, que funciona rodando do código ou empacotado com
PyInstaller (incluir `datas=[("jabuti/assets", "jabuti/assets")]` no spec).
