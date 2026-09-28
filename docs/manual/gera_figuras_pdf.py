#!/usr/bin/env python3
"""gera_figuras_pdf.py -- pre-compila as figuras TikZ do manual em PDF.

O Overleaf gratuito tem um prazo curto de compilacao, e os desenhos TikZ sao
o que mais pesa no manual: com todos eles, a compilacao estourava o prazo
(24/09/2026). O main.tex inclui figuras/pdf/<nome>.pdf quando ele existe
(macro \\figura) e so compila o TikZ quando nao existe.

O fonte continua sendo o figuras/<nome>.tex. Depois de mudar uma figura, rode
de novo, da pasta docs/manual:

    python3 gera_figuras_pdf.py              # todas
    python3 gera_figuras_pdf.py adc camadas  # so estas

Usa o pdflatex se estiver no PATH; senao, o tectonic (ou o executavel dado em
TECTONIC=/caminho/tectonic). Cada figura e compilada sozinha, numa pagina do
tamanho do desenho, com o mesmo preambulo do manual.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
FIGURAS = os.path.join(AQUI, "figuras")
SAIDA = os.path.join(FIGURAS, "pdf")

# Nao sao desenhos TikZ: o estilo e incluido por todos, a arvore e texto.
FORA = {"estilo", "arvore"}

# O mesmo preambulo do main.tex, no que as figuras usam.
MODELO = r"""\documentclass[11pt,border=1pt]{standalone}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[brazilian]{babel}
\usepackage{amsmath}
\usepackage{xcolor}
\usepackage{tikz}
\usetikzlibrary{positioning,arrows.meta,fit,backgrounds,calc,
                decorations.pathreplacing,shapes.geometric,matrix}
\input{figuras/estilo}
\newcommand{\arq}[1]{{\upshape\ttfamily\detokenize{#1}}}
\newcommand{\opt}[1]{{\upshape\ttfamily -{}-\detokenize{#1}}}
\begin{document}
\input{figuras/%s}
\end{document}
"""


def compilador() -> list[str]:
    if shutil.which("pdflatex"):
        return ["pdflatex", "-interaction=nonstopmode", "-halt-on-error"]
    tectonic = os.environ.get("TECTONIC") or shutil.which("tectonic")
    if tectonic:
        return [tectonic]
    sys.exit("erro: nem pdflatex nem tectonic encontrados (use TECTONIC=/caminho)")


def gera(nome: str, cmd: list[str]) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        fonte = os.path.join(AQUI, f"_figura_{nome}.tex")
        with open(fonte, "w", encoding="utf-8") as f:
            f.write(MODELO % nome)
        try:
            if os.path.basename(cmd[0]).startswith("pdflatex"):
                args = cmd + [f"-output-directory={tmp}", fonte]
            else:
                args = cmd + ["-o", tmp, fonte]
            r = subprocess.run(args, cwd=AQUI, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        finally:
            os.remove(fonte)
        pdf = os.path.join(tmp, f"_figura_{nome}.pdf")
        if r.returncode != 0 or not os.path.exists(pdf):
            print(f"  {nome}: FALHOU")
            print("\n".join((r.stdout + r.stderr).splitlines()[-15:]))
            return False
        shutil.copyfile(pdf, os.path.join(SAIDA, f"{nome}.pdf"))
        print(f"  {nome}: ok")
        return True


def main() -> int:
    todas = sorted(f[:-4] for f in os.listdir(FIGURAS)
                   if f.endswith(".tex") and f[:-4] not in FORA)
    pedidas = sys.argv[1:] or todas
    desconhecidas = [n for n in pedidas if n not in todas]
    if desconhecidas:
        sys.exit(f"erro: figuras desconhecidas: {', '.join(desconhecidas)}")
    os.makedirs(SAIDA, exist_ok=True)
    cmd = compilador()
    print(f"compilando {len(pedidas)} figura(s) com {os.path.basename(cmd[0])}")
    falhas = [n for n in pedidas if not gera(n, cmd)]
    if falhas:
        print(f"{len(falhas)} falha(s): {', '.join(falhas)}")
        return 1
    print(f"pronto: {SAIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
