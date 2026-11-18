# Metodologia do Jabuti

| | |
|---|---|
| Programa | Jabuti — visualizador offline de árvores filogenéticas de procariotos |
| Versão | 0.1.0 (`jabuti.__version__`, em `jabuti/__init__.py`) |
| Commit de referência | `ea4b97c` (`git rev-parse --short HEAD`, 16/11/2026 11:42:03 −0300) |
| Data de geração deste documento | 18/11/2026 |

Este documento descreve o que o código do Jabuti faz, no commit indicado acima. Cada valor
padrão, fórmula, limiar ou ordem de operações foi lido do código-fonte, e o arquivo e a função
correspondentes aparecem entre crases. Quando um procedimento é heurístico, aproximado ou tem
limitação conhecida, isso é dito explicitamente. As marcas "[VERIFICAR NO CÓDIGO: …]" e
"[REFERÊNCIA A CONFIRMAR]" indicam pontos que não puderam ser confirmados com segurança.

Unidades: as coordenadas de desenho são "unidades de cena" do Qt; na exportação, uma unidade
de cena equivale a 1 pt (1/72 polegada). Os textos do programa chamam essa unidade de "px" ou
"pt"; aqui ela é chamada de **pt**.

---

## 0. Visão geral e fluxo de dados

O Jabuti é um programa de visualização. Ele não infere filogenias: lê uma árvore pronta
(Newick) e dados associados às folhas, calcula uma disposição geométrica (layout), desenha a
figura numa cena gráfica do Qt e exporta essa mesma cena em formatos vetoriais e matriciais.

O fluxo completo, da leitura do arquivo à figura final, é o seguinte:

```
 1. Leitura ─────────────────────────────────────────────────────────────────────────
    arquivo Newick ──► decode_text (UTF-8 → cp1252 → latin-1) ──► _validate (léxica)
                   ──► Bio.Phylo (Biopython) ──► _convert ──► Tree/Node (modelo próprio)
    TSV/CSV, GFF3, iTOL ──► leitura em thread (FileLoader) ──► tabelas, genomas, datasets

 2. Árvore enraizada (estado do usuário)
    Tree original ──► cópia ──► enraizamento (arquivo | ponto médio | folha | grupo)

 3. Edições de exibição (apply_edits, sempre sobre uma CÓPIA)
    ladderize ──► rotações ──► poda das folhas ocultas ──► ramos encurtados ("//")
    = display_tree  (+ conjunto de nós colapsados, resolvido por conjuntos de folhas)

 4. Anotações resolvidas na display_tree
    clados (MRCA de cada conjunto de folhas) · grupos de rótulos · cores de metadados
    · colunas (faixas, heatmap de genes, barras, empilhadas, matrizes)
    · efeitos iTOL (apply_itol) · nomes de exibição (display_names) · contexto gênico

 5. Layout geométrico (sem Qt)
    retangular / diagonal ── rectangular_layout
    circular / leque ─────── circular_layout + circular_geometry
    não enraizada ────────── unrooted_layout (equal-angle [+ equal daylight])
                             + place_labels (rótulos sem sobreposição)

 6. Desenho (TreeRenderer.render) numa QGraphicsScene
    ramos (agrupados por cor/espessura) → marcas "//" → colapsados → rótulos e fundos
    → trilhas/anéis → destaques → fundos de clado → nomes de clado → símbolos/suporte
    → barra de escala → legenda

 7. Saída
    a mesma QGraphicsScene da tela ──► SVG (QSvgGenerator) · PDF (QPdfWriter, 72 dpi)
                                   ──► PNG/TIFF (QImage na resolução pedida; TIFF com LZW)
    FigureSnapshot do último desenho ──► exportação iTOL (Newick + datasets + LEIAME.txt)
    estado completo ──► projeto .jabuti (JSON) · preset (JSON) · pilha de desfazer
```

A orquestração fica em `jabuti/views/main_window.py`: o método `MainWindow.generate` chama
`MainWindow._render_with`, que aplica as edições (`apply_edits`), monta as colunas
(`MainWindow.annotation_columns`), o contexto gênico (`MainWindow.context_tracks`), os efeitos
iTOL (`MainWindow.itol_effects`) e os nomes (`MainWindow.display_names`), e entrega tudo a
`TreeRenderer.render` (`jabuti/views/tree_renderer.py`). Depois de cada desenho é guardado um
`FigureSnapshot` (`MainWindow._make_snapshot`), usado pela exportação iTOL, e o estado é
registrado no histórico de desfazer (`UndoController.record`).

Os modelos (árvore, clados, layouts, regras de cor, colunas, iTOL, projeto) não dependem do Qt;
só os módulos em `jabuti/views/` e `jabuti/workers.py` usam Qt.

---

## 1. Ambiente e dependências

### 1.1 Versões fixadas

| Pacote | Versão fixada | Onde | Uso |
|---|---|---|---|
| Python | 3.14.3 (testado, segundo o comentário de `requirements.txt`); `requires-python = ">=3.11"` em `pyproject.toml`; 3.12 no CI | `requirements.txt`, `pyproject.toml`, `.github/workflows/build.yml` | interpretador |
| PySide6-Essentials | 6.12.0 | `requirements.txt` | Qt 6 (QtCore, QtGui, QtWidgets, QtSvg): interface, cena gráfica, fontes e métricas de texto, exportação SVG/PDF/PNG/TIFF |
| shiboken6 | 6.12.0 | `requirements.txt` | camada de ligação C++/Python do PySide6 |
| biopython | 1.88 | `requirements.txt` | leitura de Newick (`Bio.Phylo`, `Bio.Phylo.NewickIO`) |
| numpy | 2.5.4 | `requirements.txt` | nenhum módulo de `jabuti/`, `scripts/` ou `packaging/` o importa; está fixado porque o Biopython 1.88 o declara como dependência (conferido nos metadados do pacote instalado) |
| pytest | 9.2.0 | `requirements-dev.txt` | testes |
| pytest-qt | 4.5.0 | `requirements-dev.txt` | testes de interface (`qtbot`) |
| pyflakes | 4.1.0 | `requirements-dev.txt` | análise estática |
| pyinstaller | 6.22.3 | `requirements-dev.txt` | empacotamento |

O `pyproject.toml` declara faixas mínimas (`PySide6-Essentials>=6.6`, `biopython>=1.81`) e o
ponto de entrada gráfico `jabuti = "jabuti.cli:main"`; as versões exatas usadas no
desenvolvimento e no CI são as dos arquivos `requirements*.txt`. O ambiente de medição deste
documento confirmou Python 3.14.3, PySide6 6.12.0, Biopython 1.88 e numpy 2.5.4.

O `requirements.txt` instala só o pacote `PySide6-Essentials`, sem o `PySide6` completo, porque
o programa usa apenas QtCore, QtGui, QtWidgets e QtSvg. O PySide6 completo traria também
WebEngine, 3D etc.

### 1.2 Sistemas

- **macOS**: o pacote `.app` exige macOS 14 ou superior (`LSMinimumSystemVersion` em
  `packaging/jabuti.spec`, porque o Qt 6.12 exige macOS 14+) e é gerado para chip Apple (arm64),
  sem assinatura de desenvolvedor (README, seção Empacotamento).
- **Windows**: pasta `Jabuti/` com `Jabuti.exe` (PyInstaller, modo *onedir*, sem console).
- **Linux**: roda a partir do código-fonte (os caminhos de configuração e log de Linux estão em
  `jabuti/logs.py` e `jabuti/settings.py`), mas não há executável nem job de CI para Linux.

O CI (seção 13) testa macOS e Windows.

---

## 2. Leitura e representação da árvore

### 2.1 Decodificação do texto

Todo arquivo de texto do usuário (árvore, tabelas, iTOL, GFF3) passa por `decode_text`
(`jabuti/parsers/errors.py`), que tenta, em ordem, as codificações de `TEXT_ENCODINGS`:
`utf-8-sig` (UTF-8 com ou sem BOM), `cp1252` e `latin-1`. A primeira que decodificar sem erro é
usada. Quando o arquivo não era UTF-8, um aviso é gravado no log (`jabuti.leitura`) com o nome
do arquivo e a codificação usada. Como `latin-1` aceita qualquer sequência de bytes, a
decodificação nunca falha. A ordem resolve a ambiguidade a favor do UTF-8, mas um arquivo em
cp1252 que por acaso também seja UTF-8 válido é lido como UTF-8.

### 2.2 Validação léxica e leitura do Newick

`load_tree` → `parse_newick_string` (`jabuti/parsers/newick.py`):

1. Arquivo vazio gera erro.
2. `_validate` percorre o texto caractere a caractere:
   - pula nomes entre aspas simples, em que `''` é aspa escapada;
   - pula comentários `[...]`;
   - conta parênteses;
   - confere cada comprimento após `:` com a expressão regular `_NUM`
     (`^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$`).

   Os erros informam arquivo e linha. A validação devolve **somente a primeira árvore**, até o
   primeiro `;`. Sem `;` final, o texto é aceito e o `;` é acrescentado.
3. A árvore é interpretada por `Bio.Phylo.parse(..., "newick")` (Biopython). Erros do
   Biopython viram `TreeParseError`.
4. `_convert` converte o `Clade` do Biopython no modelo próprio (`Node`), de forma iterativa (sem
   recursão), para suportar árvores grandes.
5. Rejeições: árvore com menos de 2 folhas; folhas sem nome.

### 2.3 Modelo interno

`Node` (`jabuti/models/tree.py`) guarda:
- `name`;
- `length` (comprimento do ramo nó→pai, `None` se ausente);
- `supports` (lista de floats, referente ao ramo nó→pai);
- `children` (ordem do arquivo);
- `parent`.

`Tree` guarda a raiz, cujo `length` é sempre anulado, e o conjunto `broken` de nós com ramo
encurtado na exibição. As travessias pré-ordem e pós-ordem são iterativas. `Tree.copy` faz
cópia profunda iterativa: a recursão de `deepcopy` estoura a pilha em árvores grandes.

### 2.4 Rótulos de nós internos como suporte

Em `_convert`, para cada nó **interno**:
- se o Biopython reconheceu um valor numérico de confiança (`confidence`), ele vira
  `supports = [confidence]`;
- senão, se houver nome, `_split_supports` divide o nome por `/` e tenta converter cada parte em
  float. Se todas converterem, viram `supports` e o nome é apagado; se alguma falhar, o rótulo
  continua como nome do nó.

Exemplos verificados com o código atual:

| Entrada | `supports` | `name` |
|---|---|---|
| `(A,B)95` | `[95.0]` | `""` |
| `(A,B)0.95` | `[0.95]` | `""` |
| `(A,B)80.5/97` (IQ-TREE: SH-aLRT/UFBoot) | `[80.5, 97.0]` | `""` |
| `(A,B)lab` | `[]` | `"lab"` |

O valor de suporte usado em cada operação é escolhido por `support_value(values, index)`
(`jabuti/models/tree.py`):
- `index` 0 ou 1 escolhe o 1º ou o 2º valor;
- `-1` escolhe o último;
- `SUPPORT_ALL = 99` escolhe o mínimo (o menor valor precisa passar no limiar);
- índice fora do intervalo cai no último valor.

Na convenção do IQ-TREE, adotada pelo programa (`value_name` em `jabuti/models/support.py`), o
índice 0 é SH-aLRT e o 1 é UFBoot. Os valores não são normalizados: suportes em escala 0–1 e
0–100 são usados como estão, e cabe ao usuário escolher limiares compatíveis.

### 2.5 Árvores sem comprimento, politomias e nomes

- **Sem comprimentos**: `Node.length` fica `None`. Os layouts tratam a árvore como cladograma
  (seção 4.1), e `TreeSummary.describe` informa "Comprimentos de ramo: não".
- **Politomias**: suportadas em todo o modelo, porque `children` é uma lista de tamanho
  arbitrário. A detecção de clados por k pode devolver mais de k grupos numa politomia
  (seção 5.1).
- **Nomes com espaços e acentos**: nomes entre aspas simples são lidos pelo Biopython com
  espaços e acentos preservados (ex.: `'Esp ç a'`). O sublinhado **não** é convertido em
  espaço na leitura (`B_x` continua `B_x`); a conversão "_ → espaço" é uma regra opcional de
  **exibição** (seção 6.6).
- **Nomes duplicados**: não são rejeitados; `Tree.summary` lista os duplicados e
  `TreeSummary.describe` mostra um aviso. Como clados, grupos e edições são guardados por nome
  de folha, nomes duplicados tornam essas operações ambíguas (limitação, seção 14).

### 2.6 Escrita de Newick

`write_newick` (`jabuti/parsers/newick.py`) escreve a árvore de forma iterativa:
- os suportes dos nós internos saem como `a/b`, com inteiros sem `.0` (função `_num`);
- os nomes levam aspas simples quando contêm espaço ou pontuação (`_UNSAFE`), com `''` para a
  aspa;
- o argumento `lengths` substitui comprimentos por nó, o que é usado para devolver o comprimento
  original de ramos encurtados na exportação iTOL.

---

## 3. Manipulação da árvore

A tabela resume o que cada operação altera.

| Operação | Altera a árvore enraizada do usuário? | Onde |
|---|---|---|
| Enraizamento | Sim: substitui a árvore em uso por uma cópia reenraizada do original do arquivo; a escolha fica registrada como "rooting" no projeto e no histórico | `jabuti/views/tree_tab.py`, método `TreeTab.apply_rooting` |
| Ladderize, rotação, ocultar folhas, encurtar ramo | Não: aplicados a uma cópia a cada desenho | `apply_edits` em `jabuti/models/document.py` |
| Colapsar clado | Não: só a exibição | `collapsed_nodes` em `jabuti/models/document.py` |
| Cladograma | Não: só o cálculo de profundidades | `node_depths` em `jabuti/layout/rectangular.py` |

As edições de exibição (`TreeEdits`) e os clados são guardados como **conjuntos de nomes de
folhas**, não como objetos `Node`. Assim sobrevivem a reenraizamentos e podem ser gravados em
JSON. `resolve_nodes` encontra o nó cujo conjunto de folhas é exatamente o pedido: o MRCA do
conjunto, desconsideradas as folhas ausentes. Conjuntos não monofiléticos são ignorados.

### 3.1 Enraizamento

Sempre parte de uma cópia da árvore original do arquivo (`TreeTab.apply_rooting`). Os quatro
modos são: raiz do arquivo, ponto médio, folha e grupo.

**Primitiva `Tree.reroot_at_edge(node, d)`**:
1. Coloca uma nova raiz sobre o ramo `node→pai`, a distância `d` de `node` (sem `d`, no meio
   do ramo), com $d$ limitado a $[0, \ell]$, em que $\ell$ é o comprimento do ramo.
2. As arestas no caminho até a raiz antiga são invertidas; cada nó invertido recebe o
   comprimento e os suportes do ramo que agora representa, de modo que os suportes acompanham
   as bipartições.
3. Os dois ramos da nova raiz recebem $d$ e $\ell - d$. Se o ramo original não tinha
   comprimento, ambos ficam sem comprimento.
4. A raiz antiga, se ficar com um único filho, é removida: o comprimento passa a ser a soma dos
   dois ramos e o suporte é herdado, se o filho não tiver.

**Ponto médio (`Tree.reroot_midpoint`)**, pelo método clássico de duas varreduras:
1. Se a árvore tem menos de 3 folhas, nada é feito.
2. $a$ = folha mais distante da primeira folha (`Tree._farthest_leaf`, busca em profundidade no
   grafo não dirigido, com comprimentos ausentes contados como 0).
3. $b$ = folha mais distante de $a$. Assim, $(a, b)$ é o par de folhas mais distantes (o
   diâmetro), para comprimentos não negativos.
4. $L$ = ancestral comum de $a$ e $b$; $d_a$ e $d_b$ = distâncias de $a$ e de $b$ até $L$;
   $h = (d_a + d_b)/2$.
5. Partindo da folha do lado mais longo (`a` se $d_a \ge d_b$, senão `b`), sobe-se acumulando
   comprimentos enquanto $\text{cum} + \ell(\text{nó}) < h$.
6. A raiz é colocada no ramo em que o ponto médio cai, a $h - \text{cum}$ do nó inferior.

Tratamento de empates e casos degenerados:
- **Folhas equidistantes**: `_farthest_leaf` só troca de candidata com distância
  estritamente maior, então vence a primeira encontrada na ordem da pilha de busca.
- **$d_a = d_b$**: parte de $a$.
- **Ramos de comprimento zero** que levem o percurso até $L$: nada é feito.
- **Comprimentos negativos**: entram na soma tal como estão, enquanto o layout os trata como 0
  (`max(length, 0)` em `node_depths`). O resultado do ponto médio nesse caso não é tratado
  especialmente [VERIFICAR NO CÓDIGO: não há validação de comprimentos negativos].

**Folha (`Tree.reroot_outgroup`)**: raiz no meio do ramo da folha escolhida.

**Grupo (`Tree.reroot_on_group`)**:
1. Valida que o grupo é um subconjunto próprio e não vazio das folhas.
2. Enraíza provisoriamente na primeira folha (em pré-ordem) **fora** do grupo, para que a
   bipartição não dependa da raiz atual.
3. Calcula o MRCA do grupo (`Tree._mrca`, pela interseção dos caminhos até a raiz).
4. Se o MRCA é filho direto da raiz, a raiz vai para o meio do ramo da raiz: os dois lados
   recebem metade da soma dos comprimentos, e o suporte do irmão é copiado se o nó não tiver.
   Caso contrário, `reroot_at_edge(MRCA)`.

Se o grupo não for monofilético, `Tree.group_extras` (aplicado a uma cópia) lista as folhas
extras que entrariam no clado. A interface (`TreeTab.confirm_extras`) pede confirmação antes de
prosseguir.

### 3.2 Ladderize

`ladderize` (`jabuti/models/document.py`) ordena os filhos de cada nó pelo número de folhas da
subárvore (`size`):
- `"asc"`: crescente, clados menores primeiro;
- `"desc"`: decrescente, `reverse=True`.

A ordenação do Python é estável, então filhos de mesmo tamanho mantêm a ordem do arquivo. O
padrão é `"none"`, a ordem do arquivo (`LADDERIZE`). A operação vale só para a exibição.

### 3.3 Rotação de nós

`TreeEdits.toggle_rotation` guarda o conjunto de folhas do nó; `apply_edits` inverte a ordem dos
filhos de cada nó resolvido (`node.children.reverse()`). Girar duas vezes o mesmo nó desfaz a
rotação. A rotação é aplicada depois do ladderize e vale só para a exibição.

### 3.4 Colapso de clados

`TreeEdits.collapse` guarda o conjunto de folhas. `collapsed_nodes` resolve os nós e mantém só
os colapsos mais externos: um colapso dentro de outro é ignorado.

No layout, um clado colapsado é uma "ponta" que ocupa `COLLAPSED_SLOTS = 2.0` posições
(`jabuti/layout/rectangular.py`) e é desenhado como um triângulo:
- **Retangular**: do nó até a profundidade da folha mais distante do clado
  (`collapsed_far`).
- **Circular**: o equivalente angular.
- **Não enraizada**: um leque de semiabertura entre 4° e 25°.

O triângulo tem a cor do ramo, com preenchimento de opacidade 0,35 (`TreeRenderer._collapsed_triangle`).
O rótulo é "nome do clado (n)" ou "n folhas" (`TreeRenderer._collapsed_label`).

Nas colunas, a cor de um clado colapsado é a cor comum a todas as folhas ou `MIXED_COLOR =
#b0b0b0` (`LeafColumn.color_for_group`). Os valores de barras são a média das folhas com dado
(`BarTrack.value_for`). Só a exibição é alterada.

### 3.5 Ocultar folhas (poda)

`prune` (`jabuti/models/document.py`) remove as folhas ocultas, in place sobre a cópia:
1. Marca em pós-ordem os nós que têm alguma folha mantida.
2. Remove os demais.
3. Funde nós que ficaram com um único filho: o comprimento resultante é a soma, e o suporte
   mantido é o do filho (a mesma bipartição após a poda) ou, na falta dele, o do pai.
4. Desce a raiz enquanto ela tiver um só filho.

`apply_edits` só poda se **pelo menos 2 folhas** continuarem visíveis; caso contrário, a poda não
é aplicada. As folhas ocultas não entram nos mínimos e máximos das escalas das colunas
(`MainWindow.annotation_columns`, função interna `visible`) nem no resumo de suporte. Só a
exibição é alterada.

### 3.6 Ramo encurtado ("//")

`ShortBranch(leaves, max_length)`. Em `apply_shortened`, se o comprimento do ramo resolvido for
maior que `max_length`, ele passa a ser exibido com `max(max_length, 0)` e o nó entra em
`Tree.broken`.

Comprimento inicial proposto (`MainWindow.shorten_branch`): o **maior comprimento entre os
demais ramos**. Se esse valor não for menor que o comprimento atual, propõe-se metade do
comprimento atual. O valor é arredondado a 6 casas e pode ser editado no painel.

A marca "//" (`TreeRenderer._break_mark`) é desenhada no ponto médio do ramo exibido:
- duas barras inclinadas, com tamanho $s = \max(0{,}55\,f, 4)$ (sendo $f$ o tamanho da fonte
  dos rótulos), lacuna $g = \max(0{,}35\,s,\ w + 1)$ ($w$ = espessura do ramo) e inclinação
  0,45;
- um quadrilátero na cor de fundo apaga o ramo entre as barras (só quando o fundo não é
  transparente).

A barra de escala continua refletindo a escala real dos demais ramos. O ramo encurtado deixa de
estar em escala, o que pode ser anotado na legenda pela opção `FigureConfig.break_legend`, texto
padrão "outgroup branch not to scale". A exportação iTOL escreve o comprimento original
(seção 8.2). Só a exibição é alterada.

### 3.7 Modo cladograma

`RenderStyle.use_lengths = False` (padrão `True`) faz `node_depths` ignorar os comprimentos
(seção 4.1). O modo também é usado automaticamente quando a árvore não tem nenhum comprimento.

### 3.8 Ordem de aplicação

`apply_edits`, sempre sobre uma cópia, aplica nesta ordem:
1. ladderize;
2. rotações;
3. poda das ocultas;
4. encurtamentos.

Os colapsos são resolvidos depois, sobre a árvore resultante, pelo próprio renderer.

---

## 4. Layouts geométricos

Notação:
- $n$ = número de folhas visíveis; $N$ = número total de posições ("slots"), em que cada folha
  conta 1 e cada clado colapsado conta 2;
- $f$ = tamanho da fonte dos rótulos (`LabelStyle.size`, padrão 10 pt);
- $\lambda$ = `leaf_spacing` (padrão 1,6);
- $W$ = `base_width` (padrão 600 pt); $\beta$ = `branch_scale` (padrão 1,0).

### 4.1 Profundidade dos nós e posições das pontas

**Profundidade** (`node_depths`, `jabuti/layout/rectangular.py`):
- **Com comprimentos**: $d(\text{raiz}) = 0$ e $d(v) = d(\text{pai}(v)) + \max(\ell_v, 0)$.
  Comprimentos ausentes contam como 0 e negativos são truncados em 0.
- **Cladograma**: $h(v) = 0$ para folhas e $h(v) = 1 + \max_c h(c)$ para nós internos. A
  profundidade é $d(v) = h(\text{raiz}) - h(v)$, de modo que todas as folhas ficam alinhadas na
  profundidade máxima.

**Posições** (`tip_slots`):
1. Percorre a árvore em pós-ordem, sem descer em nós colapsados.
2. A $i$-ésima ponta, com $s$ posições ($s = 1$ para folha, $s = 2$ para colapsado), tem centro
   $c = \text{cum} + (s-1)/2$ e faixa $[\text{cum} - 0{,}5,\ \text{cum} + s - 0{,}5]$, em que
   $\text{cum}$ é o total acumulado de posições.
3. O centro de um nó interno é a média dos centros do **primeiro e do último filho** (não de
   todos os filhos), e sua faixa vai do início da faixa do primeiro filho ao fim da do último.

Complexidade: $O(V)$ para profundidades e posições ($V$ = número de nós).
`collapsed_far` custa $O(\text{folhas do clado})$ por clado colapsado.

### 4.2 Retangular

`rectangular_layout` e `TreeRenderer._render_rectangular`:

$$x(v) = d(v)\cdot s_x,\qquad s_x = \frac{W\beta}{\max_v d(v)},\qquad y(v) = c(v)\cdot s_y,\qquad s_y = f\lambda .$$

Com os padrões: $s_y = 16$ pt por folha e a árvore com 600 pt de largura. Cada nó gera:
- um segmento horizontal de $(x(\text{pai}), y(v))$ a $(x(v), y(v))$;
- um conector vertical em $x(v)$, do primeiro ao último filho.

O rótulo começa em
$x(\text{folha}) + 0{,}5f + m/2 + p$, em que $m$ é o tamanho do símbolo da ponta (0 se não
houver) e $p$ é a margem interna do fundo do rótulo. A barra de escala (seção 4.7) só aparece
quando a árvore usa comprimentos. A complexidade do desenho é linear no número de itens.

### 4.3 Diagonal (inclinado)

Mesmas coordenadas do retangular (`LayoutKind.SLANTED`), mas cada ramo é um segmento direto de
$(x(\text{pai}), y(\text{pai}))$ a $(x(v), y(v))$, sem conector vertical
(`TreeRenderer._render_rectangular`, variável `slanted`). A marca "//" segue o ângulo do
segmento.

### 4.4 Circular

`circular_layout` e `circular_geometry` (`jabuti/layout/circular.py`) e
`TreeRenderer._render_circular`.

- **Ângulo**: $\theta(v) = c(v)\cdot\Delta$, com $\Delta = 2\pi/N$ (passo uniforme, inclusive
  entre a última e a primeira posição). O ângulo cresce no sentido horário, porque o eixo y da
  tela aponta para baixo, e $\theta = 0$ aponta para a direita.
- **Raio das pontas** (`outer_ring_radius`), única função que define esse raio:

  $$R_{\text{tip}} = \max\!\left(0{,}5\,W\beta,\ \frac{\lceil N\rceil\, f\lambda}{\alpha}\right),$$

  com $\alpha = 2\pi$ no círculo completo. O segundo termo garante um comprimento de arco de pelo
  menos $f\lambda$ por posição, de modo que os rótulos vizinhos não se sobreponham no anel.
- **Raio dos nós**: $r(v) = d(v)\cdot s_r$, com $s_r = R_{\text{tip}}/\max_v d(v)$.
- **Desenho dos ramos**: segmento radial de $r(\text{pai})$ a $r(v)$ no ângulo $\theta(v)$, e
  arco no raio $r(v)$ de $\theta(\text{primeiro filho})$ a $\theta(\text{último filho})$.
- **Pontas alinhadas** (`RenderStyle.align_tips`, padrão `True`): os rótulos começam todos no
  mesmo raio (`CircGeometry.label_radius`), e uma linha-guia liga a ponta real do ramo ao anel
  externo $R_{\text{tip}}$ sempre que a diferença for maior que 0,5 pt. A linha-guia padrão
  (`GuideStyle`) é pontilhada (padrão de traço `[1, 2]`), cor `#a0a0a0`, espessura 0,6 e
  opacidade 1,0. Há também os tipos contínua, tracejada `[5, 3]`, pontos maiores e nenhuma
  (`guide_pen`).
- **Anéis de anotação** (`circular_geometry`):

  $$R_0 = R_{\text{tip}} + \tfrac{m}{2} + \big(0{,}5f + e\big)\quad\text{(só se houver anéis)},$$

  em que $e$ (`inner_extent`) só é diferente de zero quando as pontas **não** estão alinhadas.
  Nesse caso, $e$ é a largura do maior rótulo mais $0{,}5f$ mais a folga dos fundos, porque os
  rótulos ficam nas pontas e os anéis vêm depois deles. O $i$-ésimo anel ocupa
  $[R_0 + \sum_{j<i} w_j + g\,i,\ \ldots + w_i]$, com $g$ = `ring_gap` = 2,0 pt
  (`CircGeometry.ring_bounds`). Com pontas alinhadas, os rótulos começam em
  $R_{\text{fim dos anéis}} + 0{,}5f$.
- **Rótulos radiais** (`TreeRenderer._rotate_radial`): girados pelo ângulo $\theta$; na metade
  esquerda do círculo ($90° < \theta < 270°$) são invertidos em 180° e ancorados pela direita,
  para que fiquem legíveis.

Complexidade: $O(V)$.

### 4.5 Leque

Variante do circular (`LayoutKind.FAN`), com abertura $\alpha$ =
`FanStyle.angle` (padrão 180°, limitada a $[10°, 360°]$) e ângulo inicial `FanStyle.start`
(padrão 0° = direita, sentido horário). As posições das folhas preenchem exatamente o arco:

$$\theta(v) = \theta_0 + (c(v) + 0{,}5)\,\frac{\alpha}{N}.$$

O raio mínimo cresce na proporção $1/\alpha$ (`outer_ring_radius`). Com abertura ≥ 359,999° o
layout é tratado como círculo completo. Os títulos das colunas são desenhados no vão do leque
quando ele tem pelo menos 15° livres (`TreeRenderer._fan_headers`).

### 4.6 Não enraizado: equal-angle e equal daylight

`unrooted_layout` (`jabuti/layout/unrooted.py`).

**Equal-angle** (descrito no próprio módulo como o algoritmo de Felsenstein, *Inferring
Phylogenies*, cap. 34):
1. Peso: $w = 1$ para folhas, $w = 2$ para clados colapsados (`COLLAPSED_SLOTS`) e, para nós
   internos, $w(v) = \sum_c w(c)$.
2. A raiz fica na origem, com fatia angular $[0, 2\pi)$.
3. Em pré-ordem, a fatia $[a_0, a_1)$ de um nó é dividida entre os filhos, na ordem, em partes
   proporcionais ao peso: $\text{span}(c) = (a_1 - a_0)\, w(c)/w(v)$.
4. Cada filho é colocado a partir da posição do pai, na direção do meio da sua fatia
   $\mu_c$:

   $$\mathbf{p}(c) = \mathbf{p}(v) + \ell_c\,(\cos\mu_c, \sin\mu_c).$$

   Aqui $\ell_c = \max(\text{comprimento}, 0)$ quando a árvore tem comprimentos, e
   $\ell_c = 1$ no modo cladograma. Ou seja, no layout não enraizado o cladograma usa ramos
   unitários e as folhas **não** ficam alinhadas.

Como cada subárvore fica confinada à sua fatia, os ramos não se cruzam nessa etapa.

**Equal daylight** (opcional, `UnrootedStyle.daylight`, padrão desligado; `_equal_daylight`):
1. Só é aplicado se $n \le$ `MAX_DAYLIGHT_LEAVES` = 2000. Acima disso, o refinamento é omitido
   sem aviso.
2. Em cada uma das até `DAYLIGHT_PASSES` = 5 passadas, para cada nó interno visível $v$ (pré-ordem):
   1. Forma os grupos: a subárvore de cada filho visível e, se $v$ não for a raiz, o "resto"
      (todos os nós fora da subárvore de $v$).
   2. Para cada grupo com pontas, calcula os ângulos das pontas em volta de $v$, a direção
      média circular `ref` (via $\operatorname{atan2}(\sum\sin, \sum\cos)$) e o arco ocupado
      $[\text{ref} + \min(\text{rel}),\ \text{ref} + \max(\text{rel})]$, com os ângulos
      relativos levados a $(-\pi, \pi]$.
   3. Calcula o vão alvo $\text{gap} = (2\pi - \sum \text{arcos})/k$, em que $k$ é o número de
      grupos. Se $\text{gap} \le 0$, o nó é pulado.
   4. Ordena os arcos pelo início; o primeiro fica parado; cada grupo seguinte é girado
      rigidamente em volta de $v$ até começar em $\text{cur} + \text{gap}$, e
      $\text{cur}$ avança pela largura do arco.
3. Critério de parada: a maior rotação da passada é menor que $10^{-4}$ rad, ou foram feitas
   5 passadas.

Limitações do refinamento:
- É uma implementação própria e heurística. O código **não verifica cruzamentos** de ramos
  depois das rotações.
- A ordenação usa ângulos absolutos sem normalização, o que pode ordenar mal arcos que cruzam
  $\pm\pi$ [VERIFICAR NO CÓDIGO: efeito prático dessa ordenação em árvores reais].
- O grupo "resto", que contém a raiz, também pode ser girado.

**Transformação final** (`_transform`): espelhamento opcional ($y \to -y$,
`UnrootedStyle.mirror`) e rotação por `UnrootedStyle.rotation` graus. O desenho usa a escala
$s = (W\beta/2)/\max_v\lVert\mathbf{p}(v)\rVert$
(`TreeRenderer._render_unrooted`). Os rótulos seguem a direção do ramo da folha, com o mesmo
giro para legibilidade do circular.

**Complexidade**:
- equal-angle: $O(V)$;
- daylight: por passada, para cada nó interno, a construção do grupo "resto" percorre todos os
  nós, o que dá $O(V^2)$ por passada no pior caso;
- distância até a folha mais distante dos clados colapsados: $O(\text{folhas}\times\text{profundidade})$.

**Recursos que não se aplicam a este layout**, com aviso na barra de status:
- colunas de dados;
- faixas, fundos e nomes de clado (as cores dos clados valem nos ramos e rótulos);
- faixas `range` do iTOL;
- contexto gênico.

### 4.7 Barra de escala

`_nice_scale` escolhe o menor valor da forma $m\cdot 10^e$, com $m \in \{1, 2, 5, 10\}$, que
seja maior ou igual a $1/5$ da maior profundidade (ou raio, ou extensão). Um comprimento fixo
pode ser dado em `ScaleBarStyle.length`. A posição padrão é embaixo, à esquerda
(`TreeRenderer._scale_bar`).

---

## 5. Detecção e anotação de clados

Os clados são conjuntos de nomes de folhas (`Clade`, `jabuti/models/clades.py`). Os grupos
detectados automaticamente são devolvidos **na ordem das folhas**: `_ordered` ordena pelo menor
índice de folha, na pré-ordem da árvore enraizada, de modo que as cores seguem a volta da
árvore. Uma nova detecção substitui os clados automáticos e preserva os manuais
(`CladeSet.replace_auto`). Os nomes padrão são "Clado 1", "Clado 2"…

A detecção roda sobre a árvore enraizada (`StylePanel.detect`, em `jabuti/views/style_panel.py`),
sem as edições de exibição.

### 5.1 Por número k

`clades_by_k`:
1. Limita $k$ a $[1, n]$.
2. Começa com a lista de grupos contendo só a raiz.
3. Enquanto houver menos de $k$ grupos:
   1. dentre os grupos que têm filhos, escolhe o de **menor profundidade** $d$
      (`node_depths`, com ou sem comprimentos, conforme o modo);
   2. desempata pelo índice em pré-ordem;
   3. substitui o grupo escolhido pelos seus filhos.

É um corte por altura a partir da raiz. Numa politomia o resultado pode passar de $k$ (ex.:
raiz com 3 filhos e $k = 2$), e a interface informa isso. Os grupos podem ser folhas
isoladas.

Padrão: $k = 4$, intervalo 1–500 (`StylePanel`; `DEFAULT_DETECTION` em `jabuti/presets.py`).
Complexidade: $O(V)$ para as profundidades, mais $O(k\cdot|\text{grupos}|)$ para as escolhas,
mais $O(n)$ por grupo em `_ordered`.

### 5.2 Por suporte

`clades_by_support(tree, threshold, index, min_size=2)`:
1. Percorre a árvore de cima para baixo, a partir dos filhos da raiz (a raiz é excluída).
2. Um nó interno é aceito se:
   - tiver suportes;
   - `support_value(supports, index)` for maior ou igual ao limiar;
   - tiver pelo menos `min_size` = 2 folhas.
3. Um nó aceito vira clado e seus descendentes não são examinados (clados **maximais**, os mais
   próximos da raiz). Um nó não aceito tem os filhos examinados.

Padrão da interface: limiar 95, intervalo 0–100. O índice é "UFBoot (2º valor)" quando há dois
valores por nó (`DEFAULT_DETECTION["support_index"] = 1`). Também se pode escolher SH-aLRT
(índice 0) ou "ambos ≥" (índice 99, o mínimo dos valores). Com um só valor, o índice é −1.
Folhas que não estão em nenhum nó aceito ficam sem clado.

### 5.3 Por distância

`clades_by_distance(tree, D)` devolve os nós $v$ tais que

$$d(\text{pai}(v)) < D \le d(v),$$

ou seja, as subárvores cujo ramo **cruza** a distância $D$ da raiz. Inclui folhas cujo ramo
cruza o corte, que viram clados de uma folha. Folhas que terminam antes do corte ficam sem
clado. Com $D \le 0$, nenhum clado é devolvido.

Na interface, $D$ = profundidade máxima × posição do controle deslizante / 1000
(`StylePanel.cut_distance`, `SLIDER_STEPS = 1000`), com padrão em 1/3 da profundidade máxima.
O corte é desenhado como linha tracejada vermelha `#d62728`: vertical no retangular, círculo ou
arco no circular e leque (`TreeRenderer._cut_pen`).

### 5.4 Por lista de nomes

`clade_from_names`:
1. Casa os nomes exatos.
2. Casa os demais nomes pelo casamento tolerante `match_names` (seção 7.2).
3. Calcula o MRCA dos encontrados e devolve o conjunto completo de folhas do MRCA, os nomes não
   encontrados e as folhas **extras** que entraram por o grupo não ser monofilético.

### 5.5 Manual

Pelo menu de contexto de um nó, a opção "Definir como clado" (`MainWindow.build_node_menu`) chama
`CladeSet.add_manual`. Se o conjunto já existir, é convertido em manual.

### 5.6 Resolução na árvore desenhada

`resolve_clades`, a cada desenho, para cada clado:
1. Calcula o alvo: o conjunto de folhas do clado menos as folhas ocultas.
2. Marca o clado como inválido, com o motivo, nos casos:
   - todas as folhas ocultas;
   - folhas ausentes;
   - MRCA cujo conjunto de folhas difere do alvo ("não monofilético nesta raiz").

   Clados inválidos não são desenhados.

`assign_nodes` atribui a cada nó o clado do ancestral mais próximo que define um clado, de modo
que, em clados aninhados, vale o **mais interno**. Para dois clados no mesmo nó, vale o último
da lista.

### 5.7 Cores

A cor de um clado é a cor própria (`Clade.color`), se definida, ou `palette[i mod |palette|]`, em
que $i$ é a posição do clado na lista: os automáticos vêm primeiro, depois os manuais. As
paletas ficam em `PALETTES` (`jabuti/style.py`):

| Paleta | Cores | Origem |
|---|---|---|
| Tableau 10 (padrão) | 10 | paleta "Tableau 10" [REFERÊNCIA A CONFIRMAR: versão da paleta Tableau] |
| Set2 | 8 | ColorBrewer (Harrower e Brewer, 2003) |
| Paired | 12 | ColorBrewer |
| Okabe-Ito (daltônico) | 8 | Okabe e Ito [REFERÊNCIA A CONFIRMAR: "Color Universal Design", 2002/2008] |

Folhas e ramos fora de qualquer clado recebem a cor neutra `#8a8a8a`
(`CladeStyle.neutral_color`).

### 5.8 Regra de cor do ramo e do fundo

A precedência é única para a tela e para a exportação iTOL (`ColorRules`, em
`jabuti/models/color_rules.py`).

**Ramo que termina em $v$** (`ColorRules.edge_pen`):
1. estilo iTOL do ramo (cor, fator de espessura, tracejado);
2. cor de metadado do nó, se "colorir ramos" estiver ligado (`MetadataStyle.color_branches`,
   padrão desligado);
3. cor do clado do **pai**, se houver clados e `CladeStyle.color_branches` (padrão ligado);
   nós sem clado recebem a cor neutra;
4. cor padrão dos ramos, `#202020`.

**Conector (ou arco) que sai de $v$** (`ColorRules.node_pen`): a mesma ordem, usando o clado do
próprio $v$.

**Cor de metadado num nó interno** (`propagate_meta`): calculada em pós-ordem. O nó recebe a cor
comum a todos os filhos, quando todos a têm; senão fica sem cor.

**Espessura proporcional ao suporte** (`ColorRules.width`, opção `BranchStyle.width_by_support`,
padrão desligada):

$$w(v) = w_{\min} + (w_{\max} - w_{\min})\cdot\operatorname{clamp}\!\left(\frac{s(v)}{s_{\max}}, 0, 1\right),$$

arredondada a 2 casas, com $w_{\min} = 0{,}6$ e $w_{\max} = 3{,}5$. Aqui $s_{\max}$ é o maior
suporte (índice escolhido) da árvore. Nós sem suporte recebem $w_{\min}$. Desligada, a espessura
é uniforme (1,2).

**Fundo de clado** (`CladeStyle.background`, padrão desligado):
- Retangular: retângulo da posição do nó menos $0{,}25f$ até o fim das colunas, cobrindo a
  faixa vertical do clado.
- Circular e leque: setor de coroa de $r(v) - 0{,}25f$ até o raio externo ocupado.
- Opacidade padrão 0,18; camada `z = −2`, atrás dos ramos e rótulos.

Os fundos vizinhos são unidos (seção 6.3).

**Faixa de clados** (`CladeStyle.outer_strip`, padrão desligado, largura 12 pt): uma coluna ou
anel na cor do clado. **Nomes de clado** (`CladeStyle.show_names`): ao lado de um colchete no
retangular; no circular, em arco (`TreeRenderer._curved_text`) ou radial.

---

## 6. Rótulos e fundos

### 6.1 Grupos de rótulos

`LabelGroup` e `LabelGroupSet` (`jabuti/models/label_groups.py`) guardam nomes de folhas e um
estilo `LabelLook`: cor do texto, fundo, opacidade do fundo, negrito, itálico, fator de tamanho,
margem interna (2,0) e raio dos cantos (3,0).

Os grupos podem vir de três fontes:
- um clado;
- uma seleção;
- um padrão (`match_pattern`): texto simples ("contém", sem distinguir maiúsculas) ou
  expressão regular com `re.IGNORECASE`. Uma regex inválida gera mensagem clara.

Os campos `None` herdam da regra seguinte. Cada folha tem no máximo um grupo efetivo: em
conflito vale o **último grupo visível** da lista (`LabelGroupSet.effective`). Os grupos novos
recebem fundos sugeridos de `HIGHLIGHT_COLORS`, a primeira cor ainda não usada.

### 6.2 Precedência de cor, fonte e fundo do rótulo

`ColorRules.label_color` e `ColorRules.label_paint` aplicam a seguinte ordem.

**Cor do texto**:
1. grupo de rótulo;
2. cor de metadado, se `MetadataStyle.color_labels` (padrão ligado) e houver coluna "colorir
   por";
3. clado, se `CladeStyle.label_mode == "text"`;
4. padrão, `#202020`.

**Negrito, itálico e tamanho**: do grupo, se definidos; senão os do estilo. O padrão é itálico
(`LabelStyle.italic = True`, nomes de espécie) e não negrito.

**Fundo**:
1. fundo do grupo;
2. cor do clado com opacidade 0,35, no modo padrão `label_mode == "background"` (marca-texto);
3. sem fundo.

Os estilos de rótulo vindos do iTOL entram **abaixo** dos grupos do usuário
(`MainWindow._render_with`), e os do usuário vencem.

### 6.3 União de fundos adjacentes sem vão

`blocks` e `ordered_tips` (`jabuti/views/background_blocks.py`), usados por
`TreeRenderer._label_blocks`, `TreeRenderer._merged_label_bgs_rect` e
`TreeRenderer._merged_label_bgs_circ`. A opção é `RenderStyle.merge_backgrounds`, padrão ligada.

**Algoritmo de agrupamento**:
1. As pontas visíveis (folhas e clados colapsados) são ordenadas pela posição desenhada (início
   da faixa) em `TreeRenderer._tip_order`.
2. A chave de cada ponta é (cor do fundo, opacidade arredondada a 4 casas), ou `None` se ela não
   tem fundo.
3. Duas pontas seguidas se **encostam** se o fim da faixa de uma coincide com o início da
   outra, com tolerância $10^{-9}$ (`TreeRenderer._touching`). No círculo completo, a última e a
   primeira posição não satisfazem esse critério, então um bloco nunca atravessa a emenda de
   $0$/$2\pi$.
4. Pontas consecutivas que se encostam e têm a **mesma chave** formam um bloco. Uma ponta sem
   fundo, ou um colapsado sem fundo, encerra o bloco.
5. Um bloco que encosta em outro de **chave diferente** recebe as marcas `before`/`after`.

**Desenho de um bloco** como um único `QPainterPath` (regra de preenchimento *winding*), o que
evita emendas e opacidade dobrada nas sobreposições:
- **Retangular**: cada folha contribui um retângulo. As bordas entre folhas do mesmo bloco
  ("inner") vão até o limite da faixa da folha (meio do espaço entre folhas). Uma borda encostada
  num bloco de outra cor ("neighbor") avança `SEAM_OVERLAP` = 0,25 pt sob a divisa, para cobrir
  o meio pixel de antialiasing. As pontas externas do bloco ("outer") usam a altura do texto
  mais a margem, limitada a $s_y - 1$, com cantos arredondados.
- **Circular e leque**: entre folhas vizinhas o fundo é um setor de coroa (`annular_sector`), com
  bordas radiais nos limites angulares das faixas. A sobreposição "neighbor" é
  $0{,}25/r_{\text{in}}$ rad. As pontas externas usam o retângulo arredondado girado do próprio
  rótulo.
- Com cores **iguais**, há um único caminho e nenhum vão. Com cores **diferentes**, os blocos se
  encostam pelo meio do espaço, e o seguinte avança 0,25 pt sob a divisa.
- Translucidez: cada bloco é um item com opacidade única, então não há escurecimento nas
  junções.

**Fundos de clado e faixas `range`** são unidos por *union-find* (`TreeRenderer._clade_bg_groups`):
- clados encostados de mesma cor (comparação sem distinguir maiúsculas) formam um só caminho;
- encostados de cor diferente: o seguinte avança 0,25 pt (ou $0{,}25/r$ rad) sob a divisa;
- as faixas `range` do iTOL são ordenadas da maior para a menor, de modo que uma faixa contida em
  outra fique por cima.

Os **destaques de linha** (`RowHighlight`) usam o mesmo agrupamento
(`TreeRenderer._highlight_blocks`).

### 6.4 Borda externa comum dos fundos e folga

Todos os fundos de rótulo terminam na mesma coordenada, o que dá uma borda externa reta no
retangular e um arco contínuo no circular:

$$x_{\text{borda}} = \max(\text{fim dos textos}) + g,\qquad r_{\text{borda}} = \max(\text{raio de fim dos textos}) + g,$$

com $g$ = `CladeStyle.label_background_gap` = 4,0 pt (intervalo 0–40). O máximo inclui os rótulos
de clados colapsados. Cada fundo tem largura
$\max(x_{\text{borda}} - x_0,\ \text{largura do texto} + 2p)$.

Nos textos invertidos (metade esquerda do círculo), o fundo cresce para a esquerda a partir do
começo do rótulo (`TreeRenderer._bg_local_rect`). No circular, a altura do fundo é limitada pela
corda entre folhas vizinhas no raio interno: $2r\sin(\Delta\theta/2) - 1$, com mínimo 2. Sem
alinhamento das pontas, os anéis começam depois dessa borda (seção 4.4).

### 6.5 Contraste automático do texto

**Fórmula WCAG**, usada nos rótulos de folha (`readable_text`, `luminance`, `contrast_ratio` em
`jabuti/models/color_rules.py`):
1. A cor vista do fundo é a mistura com a cor de baixo (`blend`, sendo o fundo da figura ou
   branco):

   $$C = \alpha\,C_{\text{fundo}} + (1-\alpha)\,C_{\text{baixo}}.$$

2. A luminância relativa é a do WCAG:

   $$L = 0{,}2126R + 0{,}7152G + 0{,}0722B,$$

   com cada canal linearizado por $c/12{,}92$ se $c \le 0{,}04045$, senão
   $((c + 0{,}055)/1{,}055)^{2{,}4}$.
3. A razão de contraste é $(L_1 + 0{,}05)/(L_2 + 0{,}05)$.
4. O texto fica branco se o contraste do branco com $C$ for maior que o da cor padrão do texto.

A regra só é aplicada quando o texto está na cor padrão dos rótulos e o grupo não definiu cor de
texto (`ColorRules.label_paint`).

**Fórmula de luma**, uma regra diferente usada em dois lugares:
- números dentro das células do heatmap (`TreeRenderer._cell_text`);
- nomes dentro das setas do contexto gênico (`TreeRenderer._draw_context`).

Nesses casos o critério é $0{,}299R + 0{,}587G + 0{,}114B < 140$ (canais em 0–255), que dá texto
branco; senão o texto é `#202020`. As duas regras de contraste coexistem no código.

### 6.6 Nomes de exibição

`display_names` (`jabuti/models/display_names.py`) aplica, nesta ordem:
1. tabela de nomes, original → exibido (a tabela CSV do usuário vence o `LABELS` do iTOL);
2. "_" → espaço (opcional);
3. regras de expressão regular, em ordem (inválidas são relatadas e puladas);
4. abreviação do gênero: a regex `^([A-Z][a-z]{2,})([ _])(?=\S)` converte "Cupriavidus necator" em
   "C. necator";
5. prefixo das folhas marcadas, padrão "★ ".

O nome original continua sendo a identidade da folha em buscas, mapeamentos, clados e presets.

### 6.7 Ajuste automático de sobreposição na árvore não enraizada

`place_labels` (`jabuti/layout/label_placement.py`), chamado por
`TreeRenderer._unrooted_label_positions` quando `UnrootedStyle.avoid_overlap` está ligado
(padrão). Só o texto se move; folhas e ramos ficam onde estão.

**Entrada**: uma caixa por rótulo, com a posição da folha, a direção do ramo, o deslocamento até
o começo do texto, a largura (texto mais $2p$) e a altura, igual a
$\min(\text{altura} + 2p,\ \max(s_y, \text{altura}))$.

**Algoritmo**, guloso e determinístico:
1. Ordena os rótulos pelo ângulo polar da folha, depois pelo ângulo do ramo e depois pelo nome.
2. Para cada rótulo, na ordem, procura a primeira posição livre:
   1. **Ajustes pequenos**: para $k = 0, \ldots, 6$ (`RADIAL_STEPS`), deslocamento
      $o + k\,h/2$; para cada $k$, giros de $0, +4°, -4°, +8°, -8°, +12°, -12°$
      (`ROTATION_STEPS`). São até 49 candidatos.
   2. **Afastamento**, se nenhum ajuste pequeno serviu: para $k = 1, \ldots, 60$ (`FAR_STEPS`),
      deslocamento $o + (3 + k)\,h$ na direção original, com **linha-guia** até a folha.
   3. Se nada estiver livre, fica no último candidato tentado, marcado como não resolvido. A
      barra de status informa "N rótulo(s) sem lugar livre".
3. Uma posição aceita sem guia, mas afastada mais de $1{,}5h$ da original, também ganha
   linha-guia.

**Colisão**: dois retângulos orientados, cada um inflado por `GAP` = 0,5 pt, colidem se
nenhum eixo separador os separa (teorema do eixo separador, `rects_overlap`). Uma grade
espacial (`_Grid`), com célula de $\max(\text{maior largura}, h)/2$, limita as comparações aos
vizinhos.

**Linha-guia** (`TreeRenderer._label_guide`): cinza `#9a9a9a`, espessura 0,5, da folha até o
começo do texto.

**Limitações**:
- o resultado depende da ordem gulosa e não é ótimo;
- rótulos não resolvidos podem continuar sobrepostos;
- o algoritmo não evita sobreposição de rótulos com ramos, só entre rótulos.

Complexidade: até $49 + 60$ testes por rótulo, cada um contra os vizinhos na grade.

---

## 7. Dados associados

### 7.1 Metadados TSV/CSV

`parse_table_text` (`jabuti/parsers/metadata.py`):
- **Linhas**: ignora linhas vazias e linhas que começam com `#`.
- **Separador**:
  - extensões `.tsv`/`.tab` usam TAB;
  - senão, `csv.Sniffer` decide entre TAB, vírgula e ponto e vírgula, sobre as 20 primeiras
    linhas;
  - em caso de falha, vale o separador mais frequente no cabeçalho;
  - se nenhum estiver presente, é um erro.
- **Cabeçalho**: é obrigatório e precisa de pelo menos 2 colunas. Cabeçalhos vazios viram
  `coluna_i`, e repetidos recebem `_2`, `_3`…
- **Linhas com número errado de campos**: são completadas ou truncadas, com aviso. São
  registrados até 10 avisos.

**Valores ausentes** (`MISSING`, sem distinguir maiúsculas): vazio, `na`, `n/a`, `nan`, `none`,
`null`, `-`, `?`.

**Numérica ou categórica** (`column_is_numeric`): a coluna é numérica se tiver pelo menos 2
valores presentes, todos convertíveis em float (a vírgula decimal é aceita) e **mais de 2
valores distintos**. Colunas 0/1, ou com 2 valores, são tratadas como categóricas. Essa regra é
heurística. Para barras e matrizes, `DataSource.numeric_columns` aceita também colunas só de
números (`_all_numbers`), inclusive 0/1.

**Coluna-chave**: `guess_key_column` escolhe a coluna cujos valores casam com mais folhas
(empate: a primeira).

**Cores das colunas** (`metadata_colors` em `jabuti/models/annotations.py`):
- **Categóricas**: as categorias são ordenadas por frequência decrescente e depois pelo nome em
  minúsculas, e recebem as cores da paleta dos clados em ciclo. Se houver mais categorias que
  cores, a legenda avisa que as cores se repetem. A legenda mostra "categoria (n)".
- **Numéricas, padrão**: gradiente linear de 5 paradas (`GRADIENT`, em estilo viridis), com
  $t = (v - v_{\min})/(v_{\max} - v_{\min})$; a legenda mostra mínimo, meio e máximo.
- **Numéricas com escala configurada** (`ColumnScale`):
  - "Colormap contínuo": `ColorScale` linear entre `vmin`/`vmax` (automáticos se ausentes), com
    um dos mapas de `COLORMAPS`;
  - "Por faixas": cortes crescentes $c_1 < \ldots < c_k$, em que $v \le c_1$ cai na faixa 0,
    $c_1 < v \le c_2$ na faixa 1, …, e $v > c_k$ na faixa $k$ (`bin_index`). As cores são as do
    usuário, completadas por paradas do mapa (`bin_colors`), e os rótulos ficam como "≤5, 6–50,
    >50" (`bin_labels`).

**Interpolação** (`gradient_color`): linear por partes em RGB entre paradas igualmente
espaçadas.

**Valores ausentes nas faixas**: a folha sem valor recebe a cor de "sem dado", `#d9d9d9`
(`MetadataStyle.missing_color`).

### 7.2 Casamento tolerante de nomes (arquivo ou linha ↔ folha)

`match_names` (`jabuti/parsers/names.py`) é usado por metadados, tabelas, GFF3, lista de clados e
IDs do iTOL. Mapeia cada chave a no máximo uma folha, sem repetir folhas, em quatro passos:
1. igualdade exata;
2. igualdade após `normalize`: minúsculas, aspas removidas, espaço, `.`, `-`, `/`, `|` e `:`
   viram `_`, e os `_` são colapsados;
3. **prefixo** nos limites de `_` (ex.: `GCF_000012345.1_ASM1v1_genomic` ↔ `GCF_000012345.1`);
4. **sufixo** nos limites de `_` (ex.: `LB400` ↔ `Paraburkholderia_xenovorans_LB400`).

Os passos 3 e 4 só aceitam um candidato **único** ainda livre. Com ambiguidade, a chave fica
sem folha. Prefixos e sufixos são indexados uma vez, então o custo cresce com o total de
caracteres e não com o produto chaves × folhas. É uma heurística, e o usuário pode corrigir o
mapeamento à mão (`LeafMapping.set`, em que cada folha aceita uma só linha).

### 7.3 Faixas, barras, barras empilhadas e matriz externa

Os modelos ficam em `jabuti/models/tracks.py` e `jabuti/models/annotations.py`. As trilhas são
desenhadas da árvore para fora, na ordem de "Ordem das colunas" (`order_keys`; trilhas novas vão
para o fim). São colunas no retangular e no diagonal, e anéis no circular e no leque. Não se
aplicam ao layout não enraizado.

- **Faixa de metadado** (`LeafColumn`, tipo "metadata"): uma célula colorida por folha, com
  largura padrão de 12 pt.
- **Barras** (`BarTrack`, criada por `bar_track`):
  - eixo linear (`auto_range`): $v_{\min} = \min(0, \text{valores})$, $v_{\max} = \max$, ou os
    limites do usuário;
  - fração $(v - v_{\min})/(v_{\max} - v_{\min})$ limitada a $[0, 1]$, com a barra partindo do
    zero quando ele está dentro do eixo;
  - escala log opcional (`log_range`): de uma potência de 10 abaixo do menor valor positivo até
    uma acima do maior, com fração
    $(\log_{10} v - \log_{10} v_{\min})/(\log_{10} v_{\max} - \log_{10} v_{\min})$;
    valores ≤ 0 ficam sem barra, com aviso;
  - linhas de referência tracejadas (`refs`) e valores opcionais;
  - cor única, por clado ou por metadado;
  - largura padrão de 80 pt;
  - num clado colapsado, a barra mostra a média das folhas com dado.
- **Barras empilhadas** (`StackedTrack`, criada por `stacked_track`): uma série por coluna
  numérica; o máximo automático é a **maior soma**; valores negativos contam como 0; uma série
  sem dado conta como 0, mas a folha sem nenhum dado fica sem barra; largura padrão de 100 pt.
- **Matriz** (`matrix_columns`), uma coluna por característica:
  - seleção "As N mais frequentes", padrão: as $N = 20$ de maior soma, com NA contando 0 e
    desempate em ordem natural (`natural_key`: GH2 < GH13);
  - ou seleção manual;
  - exibição sempre em ordem natural;
  - cor pelo `ColorScale` (linear, $\log(1+x)$ ou raiz quadrada) com o mapa viridis por padrão;
  - limites comuns a todas as colunas da matriz;
  - rotação do cabeçalho de 0°, 45° ou 90° (padrão 90°).

Os mapas de cores (`COLORMAPS`, `jabuti/models/colormaps.py`) são listas de paradas:
- `viridis`, `magma` e `cividis`, com 10 paradas;
- `Blues`, `Reds`, `Greens` e `YlOrRd`, com 9 paradas, do ColorBrewer;
- `cinza`, com 5 paradas.

Não há dependência de matplotlib. As paradas foram copiadas como valores fixos, e a interpolação
entre elas é linear em RGB. A curva resultante é, portanto, uma aproximação por partes dos mapas
originais.

### 7.4 GFF3 (Prokka, Bakta, NCBI)

`parse_gff3` (`jabuti/parsers/gff.py`), leitura própria sem dependências:
- **Arquivo**: aceita gzip, detectado pelos bytes `1f 8b`, e decodifica com `decode_text`.
- **Linhas**: ignora as vazias e as que começam com `#`; para em `##FASTA` ou numa linha que
  começa com `>`.
- **Colunas**: exige 9 colunas separadas por TAB. As linhas malformadas viram avisos com o número
  da linha (até `MAX_WARNINGS` = 20 avisos mais um contador). Início maior que o fim é invertido,
  com aviso. A fita vale `+`, `-` ou `.`.
- **Atributos**: pares `chave=valor` separados por `;`, decodificados como URL (`unquote`); o
  estilo GTF (`chave "valor"`) é tolerado.
- **Herança**: uma feature com `Parent` herda `locus_tag`, `gene`, `Name` e `product` do pai,
  quando não os tem (`_inherit_from_parents`). Só o primeiro `Parent` é usado.
- **Genes pesquisáveis** (`_searchable`): os tipos `CDS`, `tRNA`, `rRNA`, `tmRNA`, `ncRNA`,
  `misc_RNA`, `RNase_P_RNA` e `SRP_RNA`, mais `gene`/`pseudogene` **sem** filho desses tipos. Isso
  evita contar gene e CDS duas vezes. Os genes são ordenados por (seqid, início, fim).
- **Campos lidos**: `ID`, `Name`, `gene` (ou `gene_name`), `locus_tag` (ou `old_locus_tag`),
  `product`, `Parent`; os demais ficam disponíveis em `attributes`.

**Casamento arquivo ↔ folha**:
1. O nome do genoma é o nome do arquivo sem as extensões `.gz`, `.gff3`, `.gff` e `.gtf`
   (`genome_name_from_path`).
2. O mapeamento usa `match_names` (seção 7.2), preservando as correções manuais
   (`GffTab.auto_map`).

**Consulta** (`GeneQuery`, `find_genes`): o texto é procurado nos campos `product`, `name`,
`gene` e `locus_tag`. O modo "texto" faz busca por substring sem distinguir maiúsculas; o modo
regex usa `re.IGNORECASE`.

**Presença ou ausência** (`presence_matrix`, `presence_columns`): para cada consulta e cada folha
com GFF, conta-se o número de genes que casam:
- $\ge 1$ = presente, cor `#2b6cb0`;
- 0 = ausente, cor `#ffffff`;
- folha sem GFF mapeado = "sem dado", cor `#d9d9d9`.

O número de cópias pode ser escrito na célula quando passa de 1 (`HeatmapStyle.show_counts`). Os
resultados das buscas ficam em cache por (arquivo, data de modificação, tamanho, consulta)
(`GffTab.genes_for`).

**Contexto gênico** (`gene_context`, `jabuti/models/annotations.py`):
1. Âncora: o **primeiro** gene, na ordem (seqid, posição), que casa com a consulta escolhida em
   cada genoma.
2. Janela: a âncora e até $n$ genes de cada lado **no mesmo contig**, na ordem da lista de genes
   (`neighbors`). O padrão é $n = 3$, com intervalo 1–15.
3. Coordenadas relativas ao centro da âncora; se a âncora está na fita `-`, a janela é espelhada,
   para que a âncora aponte sempre para a direita.
4. Cada gene recebe a cor da primeira consulta que casa com ele (paleta dos clados, na ordem das
   consultas); os demais genes ficam cinza `#cfcfcf`.
5. Desenho (`TreeRenderer._draw_context`): setas com largura total de 360 pt (intervalo
   100–2000), escala $(\text{largura}/2)/\max|\text{coordenada}|$ em pb e altura de
   $0{,}7\,s_y$. A âncora tem contorno mais grosso.

O contexto só existe nos layouts retangular e diagonal (`MainWindow.context_tracks`).

### 7.5 Leitura assíncrona

`FileLoader` (`jabuti/workers.py`) lê os arquivos de GFF3 (`GffTab.load_files`), as tabelas do
painel Figura e as anotações iTOL. A árvore e a tabela da aba Metadados são lidas de forma
síncrona, na thread da interface: `TreeTab.load` e `MetadataTab.load` não usam `FileLoader`.

- A leitura roda numa `threading.Thread` (daemon). O código explica a escolha: destruir um
  `QThread` em execução aborta o processo, e a thread Python pode ser cancelada e aguardada com
  segurança.
- A thread de trabalho não cria objetos Qt e só emite sinais, entregues enfileirados à thread da
  interface.
- Os resultados saem em **lotes**, no máximo a cada 0,05 s (`BATCH_SECONDS`), com progresso.
- O cancelamento usa um `threading.Event`, que a leitura do GFF3 consulta a cada 2000 linhas
  (`CANCEL_CHECK_EVERY`).
- O erro de um arquivo não interrompe os demais nem derruba a thread; ele é registrado no log.
- Os genomas lidos ficam em cache por caminho resolvido, data de modificação e tamanho
  (`GffTab._cache`). Remover e readicionar um arquivo não o relê.

---

## 8. iTOL

### 8.1 Importação

**Leitura** (`parse_itol`, `jabuti/parsers/itol.py`):
1. A 1ª linha útil (que não é comentário `#`) é o tipo do dataset.
2. Depois vêm `SEPARATOR` (`TAB`, `SPACE` ou `COMMA`), as opções do cabeçalho, a linha `DATA` e
   as linhas de dados. Sem `SEPARATOR`, o separador é adivinhado nas 50 primeiras linhas de dados
   (TAB, depois vírgula, depois espaço), com aviso, exceto no `COLLAPSE`, cujo template oficial
   não tem essa linha.
3. As linhas do cabeçalho aceitam qualquer separador.
4. Aspas duplas agrupam campos; com `SPACE`, os campos de texto que sobram são juntados no último
   (`_tail`).
5. A leitura **nunca falha por uma linha**: opções desconhecidas, linhas malformadas e tipos não
   suportados viram avisos com o número da linha. Só um arquivo vazio, ilegível ou que não seja
   do iTOL gera erro (`ItolError`).
6. Cores aceitas (`parse_color`): `#rgb`, `#rrggbb`, `rgb()` e `rgba()`; a opacidade do `rgba` é
   preservada.

**Tipos suportados** (`SUPPORTED`): `TREE_COLORS`, `LABELS`, `DATASET_COLORSTRIP`,
`DATASET_STYLE`, `DATASET_SIMPLEBAR`, `DATASET_MULTIBAR`, `DATASET_HEATMAP`, `DATASET_BINARY`,
`DATASET_SYMBOL`, `DATASET_TEXT` e `COLLAPSE`.

**Tipos ignorados com aviso**, com o motivo em `UNSUPPORTED_WHY` quando há um específico:
`POPUP_INFO`, `DATASET_RANGE` (use o `range` do `TREE_COLORS`), `DATASET_ALIGNMENT`,
`DATASET_CONNECTION`, `DATASET_IMAGE`, `DATASET_GRADIENT`, `DATASET_PIECHART`, `DATASET_BOXPLOT`,
`DATASET_LINECHART`, `DATASET_DOMAINS`, `DATASET_EXTERNALSHAPE`, `DATASET_SPECTRUM` e qualquer
outro `DATASET_*`.

**Resolução de IDs** (`Resolver`, `jabuti/models/itol_apply.py`), sempre na árvore **desenhada**
(já reenraizada, ordenada e podada):
- **Nome de folha**: correspondência exata; senão, o nome de um nó interno; senão, o casamento
  tolerante `match_names`, contado em `ItolStats.tolerant`.
- **`A|B` ou `A---B`**: MRCA das folhas citadas. Folhas ocultas são desconsideradas; folhas
  ausentes invalidam a linha.
- **`CONTAINS==texto`**: cada folha cujo nome contém o texto.

Os efeitos são recalculados a cada desenho (`apply_itol`), na ordem da lista: em conflito, vence o
dataset seguinte. Nada é copiado para o estado do usuário: desligar ou remover um dataset desfaz o
efeito.

**Mapeamento de cada tipo ao modelo interno** (`_Builder`):

| Tipo | Campos lidos | Modelo interno |
|---|---|---|
| `TREE_COLORS` | `ID, tipo, cor[, estilo/rótulo, fator]` | `range` → `RangeBackground` (fundo atrás do clado, com legenda pelos rótulos); `clade` → `BranchLook` no ramo e em toda a subárvore; `branch` → só no ramo; `label` → `LabelLook` (cor, negrito/itálico, fator de tamanho); `label_background` → fundo do rótulo |
| `LABELS` | `ID, rótulo` | nomes de exibição; nós internos são ignorados com aviso |
| `DATASET_COLORSTRIP` | `ID, cor[, rótulo]`; `STRIP_WIDTH`, `SHOW_STRIP_LABELS`, `LEGEND_*`, `COLOR_BRANCHES` | `LeafColumn` "metadata"; `COLOR_BRANCHES` colore o ramo de cada folha e dos nós cujos descendentes têm todos a mesma cor |
| `DATASET_STYLE` | `ID, branch/label, node/clade, cor, fator, estilo[, fundo]` | `BranchLook` ou `LabelLook` |
| `DATASET_SIMPLEBAR` | `ID, valor`; `COLOR`, `WIDTH` (máx. 600), `MARGIN`, `SHOW_VALUE`, `LOG_SCALE`, `DATASET_SCALE` | `BarTrack`; os valores de `DATASET_SCALE` viram linhas de referência |
| `DATASET_MULTIBAR` | `ID, v1, v2…` (`X` = sem dado); `FIELD_COLORS`, `FIELD_LABELS`, `WIDTH`, `MARGIN` | `StackedTrack` com legenda das séries |
| `DATASET_HEATMAP` | `ID, v1…`; `FIELD_LABELS`, `COLOR_MIN/MID/MAX/NAN`, `USE_MID_COLOR`, `USER_MIN/MID/MAX_VALUE`, `STRIP_WIDTH`, `SHOW_VALUES` | uma `LeafColumn` "matrix" por campo; legenda em barra de cor |
| `DATASET_BINARY` | `ID, 1/0/-1…`; `FIELD_SHAPES` (1–6), `FIELD_COLORS`, `FIELD_LABELS` | `LeafColumn` "binary": `1` = forma cheia, `0` = vazada, `-1` ou ausente = nada |
| `DATASET_SYMBOL` | `ID, símbolo, tamanho, cor, preenchido, posição`; `MAXIMUM_SIZE` (padrão 50) | posição 0–1 → `BranchMark` sobre o ramo (0 = pai, 1 = nó); posição negativa → coluna externa (−1, −2… são colunas separadas); símbolos 1–12 (`shape_path`) |
| `DATASET_TEXT` | `ID, texto, posição, cor, estilo, fator, rotação`; `SIZE_FACTOR` | posição −1 → coluna de texto; 0–1 → `BranchMark` de texto; tags HTML são removidas |
| `COLLAPSE` | `ID` | conjuntos de folhas que entram nos colapsos normais ao importar ou religar (`collapse_sets`, `MainWindow._itol_collapse`) |

Valores padrão do heatmap quando as opções faltam (`HEATMAP_DEFAULTS`):
`COLOR_MIN = #ff0000`, `COLOR_MID = #ffffff`, `COLOR_MAX = #0000ff` e `COLOR_NAN = #d9d9d9`.

A cor do heatmap é linear entre mínimo e máximo, ou linear de cada lado de `USER_MID_VALUE` com
`USE_MID_COLOR`. Sem `USER_*`, os limites são o menor e o maior valor.

**O que é lido e ignorado, com aviso quando relevante**:
- `BAR_ZERO` diferente de 0 (as barras partem do zero);
- `LOG_SCALE`, `SIDE_STACKED` e `ALIGN_FIELDS` no `DATASET_MULTIBAR`;
- opções de posição e borda (`LEGEND_POSITION_X`, `BORDER_WIDTH` etc.);
- `WIDTH` acima de 600 pt, reduzido com aviso;
- nomes de nós internos em `LABELS` e estilos de rótulo de nó interno (o Jabuti não desenha nomes
  de nós internos);
- o 7º campo (rótulo) do `DATASET_SYMBOL`.

A rotação do `DATASET_TEXT` vale só para textos sobre os ramos.

**Textos sobre ramos** (`branch_text_pose`, `TreeRenderer._draw_marks`):
- orientação padrão "ao longo do ramo", sempre de pé (ângulo levado a $(-90°, 90°]$); também há
  "tangente" e "horizontal";
- distância mínima de 2,0 pt do ramo, aumentada pela metade do maior símbolo do mesmo ramo que o
  texto cobriria (`symbol_clearance`);
- halo claro opcional (padrão ligado): contorno na cor do fundo com opacidade 0,85.

### 8.2 Exportação

`plan_export` e `write_export` (`jabuti/exporters/itol_export.py`) trabalham sobre o
`FigureSnapshot` do último desenho: antes de exportar, `MainWindow.export_itol` redesenha. As cores
de ramos e rótulos vêm do mesmo `ColorRules` da tela. Todos os arquivos usam `SEPARATOR TAB`.

**Arquivos gerados**, nesta ordem (`_Planner.run`), com nomes `NN_<tipo>.txt`:
1. **`arvore.nwk`** (`write_newick`): raiz, ordem e poda atuais; suportes `a/b`; comprimento
   **original** dos ramos encurtados.
2. **`TREE_COLORS`**:
   - `range` para os fundos de clado (opacidade mínima de 0,05) e as faixas `range` importadas;
   - `clade`/`branch` para os ramos;
   - `label` e `label_background` para os rótulos.

   Os ramos (`_Planner._branches`) são percorridos em pré-ordem: um `clade` é emitido quando o
   conector de um nó difere do herdado, e um `branch` corrige o ramo que ficou diferente. Assim,
   reler o arquivo reproduz o desenho. A espessura sai como fator relativo à espessura base do
   ramo.
3. **`DATASET_STYLE`**: negrito, itálico e fator de tamanho dos rótulos diferentes do padrão.
4. **`LABELS`**: só as folhas cujo nome exibido difere do original.
5. **Colunas**, na ordem da figura:
   - faixas → `DATASET_COLORSTRIP`, com legenda;
   - faixa de clados → `DATASET_COLORSTRIP`;
   - barras → `DATASET_SIMPLEBAR` (`WIDTH`, `DATASET_SCALE`, `LOG_SCALE`);
   - empilhadas → `DATASET_MULTIBAR`;
   - matrizes e heatmaps → `DATASET_HEATMAP`;
   - heatmap de genes → `DATASET_BINARY`, com quadrados;
   - presença/ausência → `DATASET_BINARY`;
   - símbolos → `DATASET_SYMBOL` (posições −1, −2…);
   - textos → `DATASET_TEXT`.
6. **Marcas sobre ramos**: `DATASET_SYMBOL` e `DATASET_TEXT`, com IDs `primeira|última` folha
   (`node_id`).
7. **`COLLAPSE`**.
8. **`LEIAME.txt`** (`_Planner.readme`): como subir os arquivos no iTOL, a lista de arquivos com o
   número de linhas, o que não foi exportado e os avisos de aproximação.

A gravação é feita numa pasta ou num `.zip` (deflate) com uma pasta interna.

**O que não é exportável**, listado no `LEIAME.txt`:
- layout, ângulos e rotação;
- fonte, tamanho e espaçamento dos rótulos, e espessura base dos ramos;
- legenda da figura e sua posição, barra de escala e títulos das colunas;
- linhas-guia, símbolos nas pontas e números de suporte (o suporte está no Newick);
- folhas ocultas (removidas da árvore) e a marca "//".

Também entram como aviso: contexto gênico, faixas de destaque de linha e cores por nível de
suporte (`MainWindow._make_snapshot`).

**Aproximações de cor e escala**:
- **Mapas com mais de 3 paradas ou escala não linear**: exportados como gradiente mínimo/meio/
  máximo linear, em que as cores do mapa nos valores mínimo, médio e máximo viram `COLOR_MIN`,
  `COLOR_MID` e `COLOR_MAX` (`ValueRamp`, com `exact = False`, e aviso).
- **Faixas com escala contínua**: viram uma cor por folha, sem barra de cor.
- **Barras com cor por clado ou metadado**: viram cor única (o `SIMPLEBAR` tem uma só cor).
- **Mínimo das barras**: não é exportado (o iTOL parte do 0).
- **Heatmap de genes**: o número de cópias e a cor de "ausente" se perdem.
- **Séries sem dado nas empilhadas**: saem como 0.

---

## 9. Estilo, presets e projetos

### 9.1 Projeto `.jabuti`

`jabuti/project.py`:
- **Formato**: JSON UTF-8 com `"format": "jabuti-project"` e `"version": 2` (`PROJECT_FORMAT`,
  `PROJECT_VERSION`).
- **Conteúdo**:
  - `tree`: arquivo e enraizamento (`{"mode": "file"|"midpoint"|"outgroup"|"group", …}`);
  - `metadata`, `tables`, `names`, `itol.files` e `gff.files`;
  - `view`: o mesmo conteúdo de um preset completo, com estilo, clados, edições da árvore, grupos
    de rótulos e detecção.
- **Migrações** (`MIGRATIONS`, `migrate`):
  - 0 → 1: `tree_file` vira `tree.file` e `preset` vira `view`;
  - 1 → 2: as duas caixas antigas de cor de clado nos nomes viram `clades.label_mode`
    (`migrate_style_dict` em `jabuti/presets.py`);
  - versão mais nova que a suportada: erro com mensagem pedindo atualização;
  - formato diferente ou sem árvore: erro.
- **Caminhos** (`file_ref`, `resolve_ref`): cada arquivo é gravado como
  `{"rel": …, "abs": …, "name": …}`. Ao abrir, tenta-se primeiro o caminho relativo à pasta do
  projeto e depois o absoluto, então mover a pasta inteira funciona. Em discos diferentes no
  Windows não há caminho relativo.
- **Gravação atômica** (`write_project`): escreve num `.tmp` e depois chama `os.replace`.
- **Pacote com cópia dos dados** (`write_bundle`): um `.zip` com `<nome>.jabuti` e uma pasta
  `dados/`, sem nenhum caminho absoluto.
  - **Limites** (`plan_bundle`): GFF3 nunca entra; arquivos acima de 20 MB (`BUNDLE_MAX_BYTES`)
    ficam de fora e guardam só o nome; nomes repetidos recebem `_2`, `_3`…
  - **Extração** (`extract_bundle`): recusa entradas que sairiam da pasta de destino (proteção
    contra *zip slip*).

### 9.2 Presets JSON

`jabuti/presets.py`, `PRESET_VERSION = 1`. O preset guarda todas as opções visuais
(`RenderStyle`), a detecção, os clados, as edições da árvore e os grupos de rótulos.

Na leitura (`preset_from_dict`, `_from_dict`, `_coerce`):
- chaves desconhecidas são ignoradas;
- valores inválidos geram aviso e mantêm o padrão;
- só um JSON ilegível é erro.

Validações:
- cores no formato `#rrggbb` (`_HEX`);
- opções de lista fixa (`CHOICES`, `INT_CHOICES`);
- floats não negativos, salvo os de `SIGNED`.

`CladeStyle.cut_distance` não entra no preset (`SKIP`). Os arquivos iTOL não entram no preset, só
os ajustes de cada dataset (`ItolPref`, pela chave `itol:<DATASET_LABEL>`).

### 9.3 Desfazer e refazer

`jabuti/views/undo.py`, com `QUndoStack` e limite `UNDO_LIMIT` = 100 passos. Cada entrada guarda
dois estados compactos (`DocState`), nunca uma cópia da árvore:
- o preset completo em JSON com chaves ordenadas;
- o enraizamento em JSON;
- o estado das anotações iTOL (referência ao dataset lido, visibilidade, título, cores e
  rótulos).

**Registro**: o estado é capturado depois de cada desenho (`UndoController.record`). O redesenho ao
vivo tem atraso de 120 ms (`MainWindow`, `_live_timer.setInterval(120)`). Se o estado mudou, vira
um comando cujo nome é derivado da diferença entre os estados (`describe`).

**Mesclagem**: comandos seguidos com o **mesmo nome**, em menos de `MERGE_SECONDS` = 1,5 s, se
juntam. Isso vale só para ajustes contínuos (`MERGEABLE`: deslizadores, caixas numéricas, cores
de estilo). Ações discretas nunca se juntam: estrutura, enraizamento, clados, grupos, layout e
anotações. Uma mesclagem que volta ao estado inicial torna o comando obsoleto.

**Restauração** (`UndoController.apply`): reaplica o enraizamento, as anotações iTOL e o preset, e
redesenha.

---

## 10. Exportação de figuras

`jabuti/views/export.py`. A exportação usa **a mesma `QGraphicsScene` exibida na tela**
(`MainWindow.export` usa `canvas.tree_scene`, o mesmo objeto passado ao `TreeRenderer`), via
`QGraphicsScene.render`, com antialiasing de geometria e de texto.

A área exportada é o `sceneRect`: o retângulo envolvente de todos os itens mais 30 pt de margem
(`TreeRenderer.render`). Os únicos itens retirados temporariamente são os destaques de busca e a
seleção (`_hidden_highlights`). Por isso o conteúdo exportado coincide com o da tela. Diferenças
possíveis vêm só do rasterizador de cada formato: antialiasing e mapeamento de fontes no SVG/PDF.

| Formato | Como é gerado | Padrões |
|---|---|---|
| SVG | `QSvgGenerator`, tamanho e *viewBox* (`setViewBox`) iguais à área da cena | título "Jabuti tree" |
| PDF | `QPdfWriter` a 72 dpi, de modo que 1 unidade de cena = 1 pt; página do tamanho exato da cena, sem margens | vetorial |
| PNG | `QImage` ARGB32 com escala $\text{dpi}/72$, fundo transparente (a cena pinta o fundo, se houver) e dpi gravado nos metadados | 300 dpi (intervalo 72–1200) |
| TIFF | mesma imagem, gravada por `QImageWriter` com compressão 1 = LZW | 600 dpi (intervalo 72–2400), LZW ligado |

**Limites das imagens matriciais** (`_raster`): no máximo 30.000 px por lado (`MAX_SIDE`) e cerca
de 2 GB de memória (`MAX_BYTES`, 4 bytes por pixel). Acima disso, a exportação é recusada com a
sugestão de reduzir o dpi ou usar SVG/PDF.

**Legenda** (`TreeRenderer._draw_legend`, opção `LegendStyle.in_figure`, padrão desligada): é
desenhada como itens da própria cena, **fora** do retângulo da árvore e das colunas, num dos quatro
cantos laterais (padrão: à direita, em cima). As seções são:
- os clados; no modo marca-texto, a amostra mostra a cor vista, já misturada com o fundo;
- os grupos de cada coluna;
- os níveis de suporte;
- a nota do ramo encurtado.

Em escalas contínuas, a legenda é uma barra de gradiente com marcas: os extremos aparecem sempre,
e as intermediárias só se não encostarem em outra. As amostras usam a forma real do símbolo
(1–12) quando a coluna tem forma; senão, um quadrado.

**Exportação em lote** (`jabuti/exporters/batch.py`, `jabuti/views/batch_export.py`):
- **Itens**: produto cartesiano layout × preset × formato, em ordem, com nomes únicos pelo modelo
  `{projeto}_{layout}_{preset}.{ext}`, validado por `check_template` e com `_2`, `_3`… em caso de
  repetição.
- **Desenho**: cada item é desenhado numa cena própria (`MainWindow.render_to_scene`), sem tocar
  na tela.
- **Estilo**: o preset muda só o visual (`visual_style`). Colunas, iTOL, nomes, colunas de
  metadados usadas e o modo de comprimentos continuam os do projeto.

---

## 11. Desempenho

**Medição**: `scripts/bench.py` foi executado neste trabalho com
`python scripts/bench.py 500 1000 2000 --export`. Ele grava apenas numa pasta temporária, inclusive
configuração e log (`JABUTI_CONFIG_DIR`), e o repositório permaneceu inalterado.

**Máquina**: Apple M4, 16 GB de RAM, macOS 26.6.2, Python 3.14.3, PySide6 6.12.0, plataforma Qt
`offscreen`, em 18/11/2026.

**Entrada**: árvores aleatórias com semente fixa (`random_newick`), faixa de metadado, cor de ramos
por metadado, uma coluna de barras e legenda na figura. O PNG foi gerado a 150 dpi.

| Folhas | Layout | Desenho (s) | Itens na cena | SVG (s) | PNG 150 dpi (s) |
|---:|---|---:|---:|---:|---:|
| 500 | retangular | 0,02 | 526 | 0,01 | 0,71 |
| 500 | circular | 0,05 | 527 | 0,01 | 1,74 |
| 500 | leque | 0,02 | 529 | 0,01 | 3,19 |
| 500 | diagonal | 0,02 | 526 | 0,01 | 0,80 |
| 500 | não enraizada | 0,16 | 958 | 0,01 | 0,44 |
| 1000 | retangular | 0,04 | 1026 | 0,02 | recusado (> 30.000 px) |
| 1000 | circular | 0,04 | 1027 | 0,02 | 7,14 |
| 1000 | leque | 0,08 | 1029 | 0,02 | 12,47 |
| 1000 | diagonal | 0,06 | 1026 | 0,02 | recusado (> 30.000 px) |
| 1000 | não enraizada | 0,36 | 1946 | 0,02 | 1,01 |
| 2000 | retangular | 0,09 | 2026 | 0,04 | recusado (> 30.000 px) |
| 2000 | circular | 0,17 | 2027 | 0,05 | 30,63 |
| 2000 | leque | 0,10 | 2029 | 0,05 | recusado (> 30.000 px) |
| 2000 | diagonal | 0,06 | 2026 | 0,03 | recusado (> 30.000 px) |
| 2000 | não enraizada | 0,83 | 3955 | 0,05 | 2,39 |

"Recusado" significa que a imagem passaria de 30.000 px de lado a 150 dpi: o bench registra
"grande", e o programa pede um dpi menor ou SVG/PDF. O layout não enraizado é o mais lento, porque
inclui o posicionamento de rótulos sem sobreposição (ligado por padrão). O daylight está desligado
nesse bench. O custo das imagens matriciais cresce com o número de pixels.

**Estratégias de desempenho presentes no código**:
- travessias e cópias iterativas, que evitam recursão em árvores grandes (`Tree.copy`, `_convert`);
- segmentos de ramo agrupados por (cor, espessura, tracejado) em poucos `QGraphicsPathItem`
  (`_EdgeBatch`), e células agrupadas por cor (`TreeRenderer._flush_cells`);
- leitura de GFF3, tabelas e iTOL em segundo plano, com lotes e cancelamento (seção 7.5);
- caches de genomas lidos e de buscas (`GffTab._cache`, `GffTab.genes_for`);
- casamento de nomes indexado por prefixo e sufixo (`match_names`);
- grade espacial no posicionamento de rótulos (`_Grid`);
- daylight limitado a 2.000 folhas e 5 passadas;
- redesenho ao vivo com atraso de 120 ms, que agrupa mudanças rápidas.

---

## 12. Verificação e qualidade

**Suíte de testes**: executada neste trabalho com
`QT_QPA_PLATFORM=offscreen pytest -q -rs` (Python 3.14.3, macOS). O resultado foi **759 testes
aprovados, 0 falhas, 0 pulados, em 45,2 s**. São 44 arquivos `tests/test_*.py`, com 596 funções de
teste; os 759 casos incluem as parametrizações. 33 arquivos usam `qtbot` (pytest-qt).

Os tipos de teste são:
- **Unitários de modelo, sem Qt**: árvore, enraizamento, poda, ladderize, clados, layouts,
  posicionamento de rótulos, nomes, metadados, GFF3, trilhas, iTOL (leitura, aplicação e
  exportação), projeto, presets, lote e codificação. Exemplos: `tests/test_tree.py`,
  `tests/test_layout.py`, `tests/test_label_placement.py`, `tests/test_itol_export.py`.
- **Regressão visual de cena** (`tests/test_scene_regression.py` e `tests/scene_baseline.py`):
  - a assinatura de cada item da cena inclui tipo, marca, retângulo arredondado, z, texto,
    negrito/itálico, cores de pincel e caneta, espessura e estilo da caneta;
  - ela é comparada com `tests/data/scene_baseline.json` com tolerância de 1,5 unidade;
  - o teste é **pulado** se a métrica de uma fonte de referência diferir da gravada, porque a
    geometria depende das fontes do sistema.

  Na execução deste trabalho o teste rodou, sem ser pulado.
- **Interface com pytest-qt**: janela principal, menus, abrir arquivos, desfazer, presets na
  interface, exportação etc. Exemplos: `tests/test_gui_smoke.py`, `tests/test_undo.py`. A fixture
  automática de `tests/conftest.py` impede que diálogos modais travem a suíte.
- **Empacotamento** (`tests/test_packaging.py`): ícones `.ico`/`.icns`, coerência do spec do
  PyInstaller, workflow do GitHub, roteiro de build e autoteste a partir do código.
- **Codificação** (`tests/test_encoding.py`): arquivos em cp1252 e saída do terminal em UTF-8 com
  padrão cp1252 simulado.

**Autoteste do executável** (`jabuti/selftest.py`, `run_selftest`, chamado por
`Jabuti --autoteste PASTA`). Numa pasta com acento e espaço no nome ("autoteste ção"), confere:
- assets, ícone, README e exemplos empacotados;
- os plugins do Qt para PNG, TIFF e SVG;
- a abertura da árvore de exemplo (40 folhas), a detecção de clados e o desenho;
- a exportação nos 4 formatos (cada arquivo com mais de 1.000 bytes);
- salvar e reabrir um projeto `.jabuti`, com o mesmo número de clados.

O autoteste grava `autoteste.txt` e sai com código 0 ou 1.

**Análise estática**: `pyflakes` sobre `jabuti`, `tests`, `scripts` e
`packaging/jabuti_main.py`, sem nenhum aviso nesta execução.

**Reprodutibilidade e determinismo**:
- Os algoritmos de layout, detecção de clados, posicionamento de rótulos (ordenação com desempate
  por nome) e união de fundos são determinísticos: a mesma entrada dá a mesma saída. Não usam
  números aleatórios. O `random` só aparece em `scripts/bench.py`, com semente fixa.
- O resultado depende da ordem dos filhos no arquivo Newick (desempates e ladderize estável) e das
  **fontes instaladas**, porque a largura dos rótulos define posições e raios. A mesma figura em
  máquinas com fontes diferentes pode ter geometria ligeiramente diferente.
- O estado completo de uma figura é reprodutível a partir do projeto `.jabuti`.
- As dependências têm versões fixadas (seção 1).

---

## 13. Empacotamento e distribuição

**PyInstaller** (`packaging/jabuti.spec`, versão 6.22.3):
- **Ponto de entrada**: `packaging/jabuti_main.py`.
- **Dados incluídos**: `jabuti/assets`, `README.md` e `examples/`.
- **Import oculto**: `Bio.Phylo.NewickIO`, importado tardiamente.
- **Exclusões**: módulos não usados do Qt e da biblioteca padrão (lista `excludes`), e binários e
  plugins de imagem não usados (função `_keep`).
- **macOS**: `BUNDLE` com identificador `br.ufv.lgem.jabuti`, versão de `jabuti.__version__`,
  suporte a alta resolução e modo escuro, e tipos de arquivo registrados: projeto `.jabuti` como
  dono e árvores Newick como visualizador. Os arquivos chegam por `QFileOpenEvent`, sem
  `argv_emulation`.
- **Windows**: pasta *onedir* com `Jabuti.exe`, sem console, com o ícone `.ico`.

**Ícones** (`scripts/make_icons.py`): gerados a partir do PNG de 1024 px:
- `.ico` com 7 tamanhos (16 a 256), gravados como PNG;
- `.icns` com 16, 32, 128, 256 e 512 em 1x e 2x, por `iconutil`, com a margem do macOS
  (`MAC_GRID` = 824/1024).

**Build local no macOS** (`scripts/build_macos.sh`):
1. PyInstaller;
2. autoteste do `.app`;
3. `codesign --verify --deep`;
4. `Jabuti-macOS.zip` por `ditto` (preserva o bundle);
5. `Jabuti-macOS.dmg` por `hdiutil`, que é opcional e pode falhar sem interromper o roteiro.

**GitHub Actions** (`.github/workflows/build.yml`):
- **Disparo**: manual (`workflow_dispatch`) ou por tag `v*`. Python 3.12.
- **Job macOS** (`macos-latest`, limite de 40 min):
  1. dependências;
  2. `scripts/build_macos.sh`, que gera o `.app` e roda o autoteste;
  3. envio dos artefatos `.zip` e `.dmg`;
  4. pyflakes e pytest, com limite de 20 min e `faulthandler_timeout=120`.
- **Job Windows** (`windows-latest`, plataforma Qt `windows` em vez de `offscreen`, porque no
  offscreen o Windows não encontra fontes):
  1. PyInstaller;
  2. `Jabuti-Windows.zip`;
  3. envio do artefato;
  4. verificação de que o `.exe` tem o ícone do Jabuti (cor do pixel do topo);
  5. autoteste do `.exe` numa pasta com acento;
  6. pyflakes e pytest.
- **Ordem**: no workflow atual, o empacotamento e o envio do artefato vêm **antes** dos testes,
  que rodam mesmo se o empacotamento falhar (`if: ${{ !cancelled() }}`). Uma falha nos testes
  marca o job como falho, mas não impede que o artefato seja gerado.
- **Job Release**: só em tag `v*`, depois dos dois jobs; anexa os arquivos a uma Release do
  GitHub.

---

## 14. Limitações conhecidas e o que o programa não faz

**Escopo**:
- O Jabuti não infere filogenias, não faz alinhamento de sequências, não estima comprimentos de
  ramo nem suportes, e não faz nenhum teste estatístico. Ele desenha uma árvore já inferida e os
  dados fornecidos.
- Os valores de suporte são exibidos e usados como limiares tal como estão no arquivo, sem
  normalização de escala (0–1 ou 0–100).
- O enraizamento no ponto médio é geométrico e não é um teste de hipótese de raiz. Não há
  validação de comprimentos de ramo negativos.

**Algoritmos heurísticos**:
- **Detecção de clados**: k, suporte e distância são cortes geométricos ou de limiar, não
  delimitação de espécies ou OTUs. Numa politomia, "k" pode dar mais de k grupos.
- **Casamento de nomes** (`match_names`): é heurístico. Prefixo e sufixo só valem quando são
  únicos, e nomes muito parecidos podem ficar sem mapeamento ou, em casos raros, ser mapeados
  para a folha errada. O usuário deve conferir os mapeamentos.
- **Tipo das colunas de metadados**: a regra "mais de 2 valores distintos" pode classificar como
  categórica uma coluna numérica com poucos valores.
- **Equal daylight**: limitado a 2.000 folhas (acima disso é omitido sem aviso) e 5 passadas,
  sem verificação de cruzamentos. No layout não enraizado, o cladograma usa ramos unitários.
- **Rótulos sem sobreposição**: algoritmo guloso, sem garantia de solução; os rótulos não
  resolvidos são apenas contados. Não evita sobreposição de rótulos com ramos.
- **Centro dos nós internos**: nos layouts retangular e circular, é a média do primeiro e do
  último filho, e não de todos os filhos.

**Recursos por layout**:
- **Árvore não enraizada**: não tem colunas, fundos, faixas e nomes de clado, faixas `range` nem
  contexto gênico.
- **Contexto gênico**: só nos layouts retangular e diagonal. A âncora é o primeiro gene que casa
  com a consulta, e outras cópias são ignoradas.

**Identidade das folhas**: nomes de folha duplicados são aceitos com aviso, mas tornam ambíguos
clados, grupos, edições e mapeamentos, que se baseiam em nomes.

**Exportação iTOL**: aproximada nos pontos listados na seção 8.2 (mapas de cor, barras, genes,
séries vazias, marca "//", folhas ocultas, layout). A importação iTOL ignora vários tipos e
opções, todos listados com aviso.

**Cores**:
- Os mapas de cores são aproximações por paradas fixas, com interpolação linear em RGB.
- Coexistem duas regras de contraste de texto: WCAG nos rótulos e luma simples nas células e no
  contexto gênico.

**Dependência das fontes**: a geometria depende das fontes do sistema. No Windows com a plataforma
`offscreen` não há fontes, e por isso o CI usa a plataforma `windows`.

**Árvores grandes**: o desenho é rápido até 2.000 folhas (seção 11). PNG e TIFF de figuras grandes
são lentos e recusados acima de 30.000 px por lado. Não foram feitas medições acima de 2.000
folhas neste trabalho.

**Plataformas**:
- O CI testa macOS e Windows; Linux não tem executável nem CI.
- O `.app` é só para arm64 e não é assinado; o Gatekeeper pede confirmação na primeira abertura.
- O repositório não registra teste manual do executável no Windows; ele é verificado pelo
  autoteste no CI.

**Documentação**: o README (seção "Aproximações em relação ao iTOL") diz que, na
presença/ausência e nos símbolos, "a legenda mostra quadrados de cor, sem as formas". O código
atual desenha a forma real na legenda (`TreeRenderer._draw_legend`, `LegendGroup.shape_at`). Vale
o comportamento do código.

---

## 15. Parâmetros padrão

Os valores padrão vêm das *dataclasses* em `jabuti/style.py`. Os intervalos são os aceitos pelos
controles da interface, em `jabuti/views/style_panel.py`, `jabuti/views/viz_tab.py` e
`jabuti/views/gff_tab.py`. "—" indica intervalo não definido por controle numérico (escolha em
lista ou caixa de seleção) ou não verificado.

| Parâmetro | Padrão | Intervalo | Definido em |
|---|---|---|---|
| Layout | retangular | retangular, diagonal, circular, leque, não enraizada | `RenderStyle.layout` (`jabuti/style.py`) |
| Usar comprimentos de ramo | sim | sim/não (cladograma) | `RenderStyle.use_lengths` |
| Largura base da árvore | 600 pt | — | `RenderStyle.base_width` |
| Escala dos ramos | 1,0 (100%) | 10–1000% | `RenderStyle.branch_scale`; controle em `VizTab` (`jabuti/views/viz_tab.py`) |
| Espaçamento entre folhas | 1,6 × fonte | 1,0–5,0 | `RenderStyle.leaf_spacing`; controle em `VizTab` |
| Alinhar pontas (circular) | sim | — | `RenderStyle.align_tips` |
| Fundo da figura | `#ffffff` | cor ou transparente | `RenderStyle.background` |
| Unir fundos vizinhos | sim | — | `RenderStyle.merge_backgrounds` |
| Espessura dos ramos | 1,2 | 0,2–10 | `BranchStyle.width` |
| Cor dos ramos | `#202020` | — | `BranchStyle.color` |
| Ponta dos ramos | reta (`flat`) | reta, arredondada | `BranchStyle.cap` |
| Espessura por suporte | não | — | `BranchStyle.width_by_support` |
| Espessura mín./máx. por suporte | 0,6 / 3,5 | 0,1–10 / 0,2–20 | `BranchStyle.min_width`, `max_width` |
| Linha-guia | pontilhada, `#a0a0a0`, 0,6, opacidade 100% | espessura 0,1–6; opacidade 5–100% | `GuideStyle` |
| Fonte dos rótulos | sistema, 10 pt, itálico, `#202020` | tamanho 2–48 | `LabelStyle` |
| Símbolo na ponta | nenhum, 6 pt, cor do clado | tamanho 1–30 | `SymbolStyle` |
| Suporte | não mostrar; índice −1; limiar 0; símbolo 6 pt; `#555555` | limiar 0–100; símbolo 1–30 | `SupportStyle` |
| Níveis de suporte | desligado; cortes 95 / 70; cores `#2f9e44`, `#f2c94c`, `#e03131`; 6 pt | — | `SupportLevels` |
| Barra de escala | visível, embaixo à esquerda, automática | comprimento 0,0001–10⁶ | `ScaleBarStyle` |
| Legenda na figura | não; à direita, em cima | — | `LegendStyle` |
| Paleta dos clados | Tableau 10 | Tableau 10, Set2, Paired, Okabe-Ito | `CladeStyle.palette` |
| Colorir ramos pelo clado | sim | — | `CladeStyle.color_branches` |
| Cor do clado nos nomes | fundo (marca-texto) | fundo, texto, nenhum | `CladeStyle.label_mode` |
| Opacidade do fundo dos nomes | 0,35 | 5–100% | `CladeStyle.label_background_alpha` |
| Folga da borda comum dos fundos | 4,0 pt | 0–40 | `CladeStyle.label_background_gap` |
| Fundo atrás do clado | não; opacidade 0,18 | 5–100% | `CladeStyle.background`, `background_alpha` |
| Faixa de clados | não; 12 pt | 2–80 | `CladeStyle.outer_strip`, `strip_width` |
| Nomes dos clados | não; curvos (circular) | curvo, radial | `CladeStyle.show_names`, `name_mode` |
| Cor neutra | `#8a8a8a` | — | `CladeStyle.neutral_color` |
| Detecção | k = 4; suporte ≥ 95 (UFBoot); distância = 1/3 da profundidade máxima | k 1–500; suporte 0–100; distância 0–1000 passos | `DEFAULT_DETECTION` (`jabuti/presets.py`), `StylePanel` |
| Tamanho mínimo do clado por suporte | 2 folhas | — | `clades_by_support` (`jabuti/models/clades.py`) |
| Heatmap de genes | presente `#2b6cb0`, ausente `#ffffff`, sem dado `#d9d9d9`; célula 1,0 × espaço; contagens não; cabeçalhos sim; bordas sim | célula 0,3–5 | `HeatmapStyle` |
| Contexto gênico | 360 pt; seta 0,7 × espaço; nomes sim; ±3 genes | 100–2000 pt; 1–15 genes | `ContextStyle`, `GffTab` (`jabuti/views/gff_tab.py`) |
| Metadados | colorir rótulos sim; ramos não; faixa 12 pt; sem dado `#d9d9d9` | faixa 2–80 | `MetadataStyle` |
| Barras | cor única `#4e79a7`; 80 pt; eixo automático; linear | — | `BarSpec` |
| Barras empilhadas | 100 pt; máximo = maior soma | — | `StackedSpec` |
| Matriz | 20 mais frequentes; linear; viridis; cabeçalho 90°; célula 1,0 | rotação 0, 45, 90 | `MatrixSpec` |
| Regras de nomes | "_" → espaço não; abreviar gênero não; prefixo "★ " | — | `NameRules` |
| Leque | 180°; início 0° | abertura 30°–350° na interface (o layout aceita 10°–360°); início 0°–359° | `FanStyle`, `circular_layout`, `VizTab` |
| Não enraizada | rotação 0°; sem espelhar; daylight não; evitar sobreposição sim | rotação 0°–359° | `UnrootedStyle`, `VizTab` |
| Daylight | 5 passadas; até 2.000 folhas; parada < 10⁻⁴ rad | — | `DAYLIGHT_PASSES`, `MAX_DAYLIGHT_LEAVES` (`jabuti/layout/unrooted.py`) |
| Rótulos sem sobreposição | 6 passos radiais (h/2); giros ±4°, ±8°, ±12°; 60 passos longos; folga 0,5 pt | — | `jabuti/layout/label_placement.py` |
| Textos nos ramos | ao longo do ramo; 2,0 pt; halo sim | — | `BranchTextStyle` |
| Nota do ramo encurtado | não; "outgroup branch not to scale" | — | `FigureConfig.break_legend`, `break_legend_text` |
| PNG | 300 dpi | 72–1200 | `VizTab` (`jabuti/views/viz_tab.py`) |
| TIFF | 600 dpi, LZW | 72–2400 | `VizTab` |
| Limite de imagem | 30.000 px por lado; ~2 GB | — | `MAX_SIDE`, `MAX_BYTES` (`jabuti/views/export.py`) |
| Desfazer | 100 passos; mescla em 1,5 s | — | `UNDO_LIMIT`, `MERGE_SECONDS` (`jabuti/views/undo.py`) |
| Pacote de projeto | arquivos até 20 MB; sem GFF3 | — | `BUNDLE_MAX_BYTES` (`jabuti/project.py`) |
| Avisos de GFF3 | 20 por arquivo | — | `MAX_WARNINGS` (`jabuti/parsers/gff.py`) |
| Largura máx. de barras importadas do iTOL | 600 pt | — | `MAX_WIDTH` (`jabuti/models/itol_apply.py`) |
| Arquivos recentes | 10 | — | `MAX_RECENT` (`jabuti/settings.py`) |

---

## 16. Referências

Só são citadas fontes que o código implementa ou adota explicitamente.

1. **Felsenstein, J. (2004).** *Inferring Phylogenies*. Sunderland, MA: Sinauer Associates.
   Algoritmo *equal-angle* e refinamento *equal daylight* para árvores não enraizadas; o próprio
   módulo `jabuti/layout/unrooted.py` cita o cap. 34 [REFERÊNCIA A CONFIRMAR: número exato do
   capítulo e das páginas].
2. **Ponto médio (midpoint rooting)**: método clássico de enraizar no ponto médio do caminho mais
   longo entre duas folhas, implementado em `Tree.reroot_midpoint`
   [REFERÊNCIA A CONFIRMAR: referência primária do método, frequentemente atribuído a Farris, 1972].
3. **Formato Newick**: Felsenstein, J. *et al.* "The Newick tree format", especificação informal
   adotada em 1986 [REFERÊNCIA A CONFIRMAR: URL e data da especificação de referência].
4. **iTOL**: Letunic, I. e Bork, P. Interactive Tree Of Life (iTOL). Formatos de anotação em
   https://itol.embl.de/help.cgi, citado em `jabuti/parsers/itol.py`
   [REFERÊNCIA A CONFIRMAR: artigo e versão do iTOL a citar, ex. *Nucleic Acids Research*, 2024].
5. **IQ-TREE**: convenção dos rótulos de suporte `SH-aLRT/UFBoot` e dos arquivos `.treefile`
   [REFERÊNCIA A CONFIRMAR: Minh, B. Q. *et al.* (2020), IQ-TREE 2, *Molecular Biology and
   Evolution*].
6. **Biopython**: Cock, P. J. A. *et al.* (2009). Biopython: freely available Python tools for
   computational molecular biology and bioinformatics. *Bioinformatics*, 25(11), 1422–1423.
   Módulo `Bio.Phylo`: Talevich, E. *et al.* (2012), *BMC Bioinformatics*, 13, 209
   [REFERÊNCIA A CONFIRMAR: conferir volume e páginas].
7. **Qt / PySide6**: The Qt Company. Qt 6 e Qt for Python (PySide6) 6.12
   [REFERÊNCIA A CONFIRMAR: forma de citação de software preferida].
8. **GFF3**: Sequence Ontology Project, "Generic Feature Format Version 3"
   [REFERÊNCIA A CONFIRMAR: versão da especificação]. Os anotadores citados no código (Prokka,
   Bakta e NCBI PGAP) são fontes dos arquivos, não algoritmos implementados.
9. **Viridis, magma e cividis**: mapas de cores perceptualmente uniformes (van der Walt e Smith,
   matplotlib; cividis: Nuñez, Anderton e Renslow, 2018, *PLoS ONE*)
   [REFERÊNCIA A CONFIRMAR: citações exatas].
10. **ColorBrewer** (Set2, Paired, Blues, Reds, Greens, YlOrRd): Harrower, M. e Brewer, C. A.
    (2003). ColorBrewer.org: an online tool for selecting colour schemes for maps. *The
    Cartographic Journal*, 40(1), 27–37.
11. **Tableau 10**: paleta categórica da Tableau Software [REFERÊNCIA A CONFIRMAR].
12. **Okabe-Ito**: Okabe, M. e Ito, K. *Color Universal Design (CUD)* [REFERÊNCIA A CONFIRMAR: ano
    e forma de publicação].
13. **WCAG 2.x**: W3C. *Web Content Accessibility Guidelines*. Definição de luminância relativa e
    razão de contraste usadas em `jabuti/models/color_rules.py` [REFERÊNCIA A CONFIRMAR: versão
    2.0 (2008) ou 2.1 (2018)].
14. **Teorema do eixo separador**: usado na detecção de colisão de rótulos
    (`jabuti/layout/label_placement.py`) [REFERÊNCIA A CONFIRMAR: referência de geometria
    computacional, ex. Gottschalk, Lin e Manocha, 1996].
15. **PyInstaller**: PyInstaller Development Team, versão 6.22.3 [REFERÊNCIA A CONFIRMAR].
