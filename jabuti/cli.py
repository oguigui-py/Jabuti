"""Linha de comando: ``python -m jabuti [árvore] [--itol ARQ…]``, ``--version`` e ``--help``.

``--version`` e ``--help`` respondem sem carregar o Qt (rápidos e funcionam sem tela).
"""

from __future__ import annotations

import argparse
import sys

from jabuti import __version__
from jabuti.credits import CREDIT_AUTHOR, CREDIT_LAB

DESCRIPTION = ("Jabuti — visualizador offline de árvores filogenéticas de procariotos "
               "(Newick/.treefile, GFF3, metadados, anotações do iTOL).")
EPILOG = f"""exemplos:
  python -m jabuti
  python -m jabuti examples/paraburkholderia_40.treefile
  python -m jabuti meu_projeto.jabuti
  python -m jabuti arvore.treefile --itol cores.txt faixas.txt

{CREDIT_LAB} · {CREDIT_AUTHOR}"""


class _Formatter(argparse.RawDescriptionHelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):  # type: ignore[no-untyped-def]
        return super().add_usage(usage, actions, groups, prefix or "uso: ")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jabuti", description=DESCRIPTION, epilog=EPILOG, add_help=False,
                                formatter_class=_Formatter)
    p.add_argument("-h", "--help", action="help", help="mostra esta ajuda e sai")
    p.add_argument("tree", nargs="?", metavar="ÁRVORE", help="árvore Newick (.nwk, .treefile, .tre…) ou projeto (.jabuti, ou .zip com cópia dos dados)")
    p.add_argument("--itol", nargs="+", metavar="ARQ", default=[],
                   help="anotações do iTOL a importar depois de abrir a árvore")
    p.add_argument("--no-splash", action="store_true", help="abre direto, sem a tela de abertura")
    p.add_argument("--autoteste", metavar="PASTA",
                   help="confere o executável (assets, plugins do Qt, exportar, projeto) e grava o relatório em PASTA")
    p.add_argument("-V", "--version", action="version", version=f"Jabuti {__version__}",
                   help="mostra a versão e sai")
    p.usage = "jabuti [-h] [-V] [--no-splash] [ÁRVORE] [--itol ARQ …]"
    p._positionals.title = "argumentos"
    p._optionals.title = "opções"
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # macOS antigo passa "-psn_0_…" ao abrir pelo Finder: não é argumento do Jabuti
    argv = [a for a in argv if not a.startswith("-psn_")]
    args = build_parser().parse_args(argv)
    if args.autoteste:
        from jabuti.selftest import run_selftest

        return run_selftest(args.autoteste)
    from jabuti.app import run

    return run(args.tree, args.itol, splash=not args.no_splash)


if __name__ == "__main__":
    raise SystemExit(main())
