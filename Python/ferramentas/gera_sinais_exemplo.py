#!/usr/bin/env python3
"""
gera_sinais_exemplo -- escreve em exemplos/sinais/ os arquivos para testar o
tipo "Arquivo" e o processamento por blocos na janela de convolucao.

    python3 ferramentas/gera_sinais_exemplo.py

O caso: um sinal de 1 s a 8 kHz com dois tons, 300 Hz e 3 kHz, passando por
um passa-baixa de 67 coeficientes com corte em 1 kHz. Sao 8000 amostras, mais
que o hardware aceita de uma vez (1024): a janela divide em 8 blocos. Na saida,
o tom de 3 kHz some e o de 300 Hz passa com a mesma amplitude.

Arquivos:
  duas_senoides_8k.wav   x[n], 8000 amostras, 16 bits, fs = 8000 Hz
  duas_senoides_8k.csv   o mesmo x[n] em texto, colunas t e x (3000 amostras)
  passa_baixa_1k.csv     h[n], 67 coeficientes, uma coluna
  impulso_atrasado.txt   h[n] = delta[n - 2000]: a saida e x atrasado 2000
                         amostras, e h tambem passa de 1024 (vira 2 blocos)
  espectro_8192.npy      X[k] = FFT de 8192 pontos do .wav (complexo), para a
                         janela da IFFT: volta ao sinal por 8 IFFTs da placa
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


def passa_baixa(n_taps: int = 67, fc_hz: float = 1000.0) -> np.ndarray:
    """Sinc janelado com Hamming, ganho unitario em DC."""
    fc = fc_hz / FS
    m = np.arange(n_taps) - (n_taps - 1) / 2
    h = 2 * fc * np.sinc(2 * fc * m) * np.hamming(n_taps)
    return h / h.sum()


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

    np.savetxt(caminho("passa_baixa_1k.csv"), passa_baixa(), fmt="%.9f",
               header="h[n]: passa-baixa, 67 coeficientes, corte 1 kHz a fs 8 kHz")

    d = np.zeros(2001)
    d[2000] = 1.0
    np.savetxt(caminho("impulso_atrasado.txt"), d, fmt="%g")

    X = np.fft.fft(np.r_[x, np.zeros(8192 - x.size)])
    np.save(caminho("espectro_8192.npy"), X)

    for nome in sorted(os.listdir(DESTINO)):
        print(f"  {nome}  ({os.path.getsize(caminho(nome))} bytes)")


if __name__ == "__main__":
    main()
