"""Dicas (tooltips) dos controles menos óbvios, num lugar só.

Aplicadas pelo texto do botão a quem ainda não tem dica própria (as definidas junto do
widget têm prioridade). Termos e tom uniformes: frase curta, sem ponto final quando é uma.
"""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractButton, QWidget

TIPS: dict[str, str] = {
    # barra da tela
    "Buscar": "Busca folhas pelo nome (parte do nome basta). Atalho: Cmd/Ctrl+F",
    "−": "Reduzir (Cmd/Ctrl+−)",
    "+": "Ampliar (Cmd/Ctrl++)",
    "Ajustar": "Ajusta a figura à janela (Cmd/Ctrl+0)",
    # Árvore
    "Abrir árvore (Newick / .treefile)…": "Newick do IQ-TREE, RAxML, FastTree… Também dá para arrastar o arquivo para a janela",
    "Como no arquivo": "Mantém a raiz do arquivo",
    "Ponto médio (midpoint)": "Raiz no ponto médio do caminho mais longo entre duas folhas",
    "Por folha (outgroup):": "Raiz no ramo da folha escolhida (grupo externo)",
    "Aplicar enraizamento": "Reenraíza a árvore; clados manuais são mantidos pelo ancestral comum",
    # GFF
    "Adicionar GFF3…": "Um GFF3 por genoma; o nome do arquivo é usado para achar a folha",
    "Adicionar coluna": "Nova coluna do heatmap: um gene buscado pelo texto e pelo campo escolhidos",
    "produto": "Busca no campo product (descrição do gene)",
    "nome/gene": "Busca nos campos Name e gene",
    "locus_tag": "Busca no locus_tag",
    "regex": "Interpreta o texto como expressão regular",
    "Mostrar vizinhos do gene âncora": "Desenha os genes ao redor do gene escolhido, ao lado de cada folha (layout retangular)",
    "↑": "Move para cima (mais perto da árvore)",
    "↓": "Move para baixo (mais longe da árvore)",
    # Visualização
    "Gerar": "Redesenha a figura com as opções atuais (Cmd/Ctrl+R)",
    "Espelhar": "Inverte a árvore não enraizada da esquerda para a direita",
    "SVG": "Vetorial, editável no Inkscape/Illustrator",
    "PDF": "Vetorial, para artigos e impressão",
    "PNG": "Imagem na resolução (dpi) escolhida",
    "TIFF": "Imagem para revistas que pedem TIFF (dpi escolhido)",
    "Compressão LZW": "TIFF menor, sem perda de qualidade",
    # Metadados
    "Abrir tabela (TSV/CSV)…": "Uma linha por genoma, com cabeçalho; a primeira coluna que casa com as folhas é usada",
    # Estilo
    "Detectar": "Detecta clados pela linha de corte (distância à raiz)",
    "Mostrar linha de corte": "Mostra no desenho a linha usada para detectar os clados",
    "Okabe-Ito (daltônico)": "Paleta segura para daltonismo",
    "Espessura proporcional ao suporte": "Ramos mais grossos quanto maior o suporte do nó",
    "Usar a cor do clado": "Símbolos dos nós com a cor do clado",
    "Tamanho proporcional ao valor": "Símbolo maior quanto maior o suporte",
    "Automático": "Escolhe um comprimento redondo para a barra de escala",
    "Desfazer rotações": "Volta a ordem original dos filhos em todos os nós",
    "Expandir todos": "Desfaz todos os colapsos em triângulo",
    "Transparente (também no export)": "Sem cor de fundo, na tela e nos arquivos exportados",
    "Esquecer meu padrão": "Apaga o seu estilo padrão; o Jabuti volta a abrir com o de fábrica",
    "Unir fundos vizinhos": "Fundos de clados, rótulos e destaques encostados viram um bloco só",
    # Figura
    "Carregar tabela…": "Tabela numérica (TSV/CSV) para barras, empilhadas e matrizes",
    "Mapear automaticamente": "Casa de novo as linhas da tabela com as folhas pelo nome",
    "auto": "Usa o valor calculado a partir dos dados",
    "+ Matriz": "Matriz de valores (heatmap externo), uma coluna por característica",
    "Ocultar folhas selecionadas": "Remove as folhas do desenho (a árvore original não muda)",
    "Restaurar selecionadas": "Mostra de novo as folhas selecionadas na lista",
    "Restaurar todas": "Mostra de novo todas as folhas ocultas",
    "Nota na legenda:": "Texto na legenda explicando a marca // dos ramos encurtados",
    "Abreviar gênero (Cupriavidus → C.)": "Abrevia a primeira palavra do nome quando há espécie",
    "+ regra": "Nova substituição (expressão regular → texto)",
    "− regra": "Remove a substituição selecionada",
    "Destacar linhas da seleção": "Faixa de cor atrás de toda a linha das folhas selecionadas",
    "contorno": "Só o contorno da faixa, sem preenchimento",
    "Carregar arquivo…": "Lista de nomes de folhas, um por linha",
    "Criar clado": "Cria um clado com o ancestral comum das folhas da lista",
    "Copiar resumo": "Copia o resumo do suporte para a área de transferência",
    "Suporte em níveis (círculos nos nós)": "Círculo colorido em cada nó conforme a faixa de suporte (cortes abaixo)",
    "Níveis na legenda": "Lista os níveis de suporte (cores e cortes) na legenda",
    # Grupos de rótulos
    "Selecionar": "Seleciona no desenho as folhas que casam com o padrão",
    "Criar grupo": "Cria um grupo de destaque com as folhas que casam com o padrão",
    "Criar grupo da seleção": "Cria um grupo de destaque com as folhas selecionadas no desenho",
    "Mostrar grupos na legenda": "Inclui os grupos de destaque na legenda",
    "Limpar tudo": "Remove todos os grupos de destaque",
}


def apply_tooltips(root: QWidget) -> int:
    """Põe a dica nos botões de ``root`` que ainda não têm uma. Devolve quantos receberam."""
    n = 0
    for b in root.findChildren(QAbstractButton):
        tip = TIPS.get(b.text())
        if tip and not b.toolTip():
            b.setToolTip(tip)
            n += 1
    return n
