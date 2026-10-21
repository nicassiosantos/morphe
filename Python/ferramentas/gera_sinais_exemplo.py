#!/usr/bin/env python3
"""
gera_sinais_exemplo -- escreve em exemplos/sinais/ os arquivos para testar o
tipo "Arquivo" e a FFT longa (quatro passos) na janela da FFT.

    python3 ferramentas/gera_sinais_exemplo.py

O caso: um sinal de 1 s a 8 kHz com dois tons, 300 Hz e 3 kHz. Sao 8000
amostras, mais que o hardware aceita de uma vez (1024): a janela calcula uma
FFT de 8192 pontos com 8 FFTs da placa.

Arquivos:
  duas_senoides_8k.wav   x[n], 8000 amostras, 16 bits, fs = 8000 Hz
  duas_senoides_8k.csv   o mesmo x[n] em texto, colunas t e x (3000 amostras)
"""
from __future__ import annotations

import os

import numpy as np
from scipy.io import wavfile

FS = 8000
DESTINO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "..", "exemplos", "sinais")


def duas_senoides(n_amostras: int) -> np.ndarray:
    t = np.arange(n_amostras) / FS
    return 0.5 * np.sin(2 * np.pi * 300 * t) + 0.3 * np.sin(2 * np.pi * 3000 * t)


def main() -> None:
    os.makedirs(DESTINO, exist_ok=True)
    caminho = lambda nome: os.path.join(DESTINO, nome)

    x = duas_senoides(FS)
    wavfile.write(caminho("duas_senoides_8k.wav"), FS,
                  np.round(x * 32767).astype(np.int16))

    x_curto = duas_senoides(3000)
    with open(caminho("duas_senoides_8k.csv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("t,x\n")
        for i, v in enumerate(x_curto):
            f.write(f"{i / FS:.6f},{v:.6f}\n")

    for nome in sorted(os.listdir(DESTINO)):
        print(f"  {nome}  ({os.path.getsize(caminho(nome))} bytes)")


if __name__ == "__main__":
    main()
