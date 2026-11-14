# Jabuti

Visualizador **offline** de árvores filogenéticas para genomas de procariotos (ex.: *Paraburkholderia*),
no estilo de um iTOL simplificado. App desktop em Python + PySide6 (macOS e Windows), sem servidor e sem internet.

**Já funciona:** abrir Newick / `.treefile` (IQ-TREE), resumo e suporte (bootstrap, `SH-aLRT/UFBoot`),
enraizamento midpoint ou por folha, layouts retangular e circular (pontas alinhadas no anel
externo, estilo iTOL), painel fixo de cores, zoom/pan, busca de folhas e exportação SVG / PDF / PNG.
**Próximas fases:** GFF3 + busca de genes (heatmap de presença/ausência), metadados TSV/CSV,
anotações iTOL simples e builds `.app` / `.exe`.

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
