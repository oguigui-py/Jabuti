# Jabuti

Visualizador **offline** de árvores filogenéticas para genomas de procariotos (ex.: *Paraburkholderia*),
no estilo de um iTOL simplificado. App desktop em Python + PySide6 (macOS e Windows), sem servidor e sem internet.

**Já funciona:** GFF3 (heatmap de genes e contexto gênico), metadados TSV/CSV, abrir Newick / `.treefile` (IQ-TREE), resumo e suporte (bootstrap, `SH-aLRT/UFBoot`),
enraizamento midpoint ou por folha, layouts retangular e circular (pontas alinhadas no anel
externo, estilo iTOL), clados coloridos, estilos de linha, rótulos e símbolos, edição da árvore
(ladderize, girar, colapsar), presets JSON, zoom/pan, busca de folhas e exportação SVG / PDF / PNG.
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

Exemplo sintético: `examples/traits.tsv` (tamanho do genoma, nº de contigs com `NA` e
contagens de CAZy por classe).

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
