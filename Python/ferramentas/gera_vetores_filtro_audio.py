#!/usr/bin/env python3
"""gera_vetores_filtro_audio.py -- vetores de teste para o tb_filtro_audio.v.

Projeta um filtro, roda o modelo em ponto fixo (iir_design.filtra_sos_fixo)
sobre amostras int16 como as do codec e grava o que o testbench le. O RTL
tem que reproduzir a saida bit a bit, amostra por amostra.

Casos:
    passa_baixas   Butterworth de ordem 8 (4 secoes), corte em 1 kHz
    passa_altas    Butterworth de ordem 6 (3 secoes), corte em 2 kHz
    passa_faixa    Butterworth de ordem 8 (8 secoes), 500 Hz a 3 kHz
    maximo         16 secoes (ordem 32 passa-baixas), o maximo do hardware
    direto         0 secoes: a saida e a propria entrada
    satura         ganho de 8 numa secao: a saida int16 gruda nos limites

Arquivos gravados em <destino>: fa_coef.hex (32 bits, 5 por secao, b0 b1 b2
a1 a2), fa_x.hex e fa_y.hex (16 bits), fa_n.txt (secoes e amostras).

Uso:
    python ferramentas/gera_vetores_filtro_audio.py <caso> <destino>
"""
from __future__ import annotations

import os
import sys

import numpy as np
from scipy import signal

import _caminho  # noqa: F401 -- poe Python/ no sys.path
import iir_design as iir

FS = 50e6 / 1024
N = 2000


def projeto(caso: str) -> np.ndarray:
    if caso == "passa_baixas":
        return signal.butter(8, 1000, "lowpass", fs=FS, output="sos")
    if caso == "passa_altas":
        return signal.butter(6, 2000, "highpass", fs=FS, output="sos")
    if caso == "passa_faixa":
        return signal.butter(8, [500, 3000], "bandpass", fs=FS, output="sos")
    if caso == "maximo":
        return signal.butter(32, 4000, "lowpass", fs=FS, output="sos")
    if caso == "direto":
        return np.zeros((0, 6))
    if caso == "satura":
        return np.array([[8.0, 0.0, 0.0, 1.0, 0.0, 0.0]])
    raise SystemExit(f"caso desconhecido: {caso}")


def entrada(caso: str) -> np.ndarray:
    rng = np.random.default_rng(1510)
    t = np.arange(N) / FS
    x = 0.4 * np.sin(2 * np.pi * 700 * t) + 0.3 * np.sin(2 * np.pi * 5000 * t) \
        + 0.1 * rng.uniform(-1, 1, N)
    if caso == "satura":
        x = 0.5 * np.sin(2 * np.pi * 300 * t)
    q = np.clip(np.round(x * 32768), -32768, 32767).astype(np.int64)
    q[5] = 32767                       # os dois extremos passam pelo filtro
    q[6] = -32768
    return q


def main() -> None:
    caso, destino = sys.argv[1], sys.argv[2]
    sos = projeto(caso)
    x = entrada(caso)
    if sos.shape[0]:
        coefs = iir.coeficientes_inteiros(sos, 16, 32)
        y = iir.filtra_sos_fixo(x / 32768.0, sos, 16, 32)
        yq = np.round(np.asarray(y) * 65536).astype(np.int64)    # exato: k/2^16
    else:
        coefs = []
        yq = x * 2
    y16 = np.clip((yq + 1) >> 1, -32768, 32767)

    def h32(v):
        return f"{int(v) & 0xFFFFFFFF:08x}"

    def h16(v):
        return f"{int(v) & 0xFFFF:04x}"

    with open(os.path.join(destino, "fa_coef.hex"), "w") as f:
        for sec in coefs:
            for v in sec:
                f.write(h32(v) + "\n")
        if not coefs:
            f.write("00000000\n")
    with open(os.path.join(destino, "fa_x.hex"), "w") as f:
        f.writelines(h16(v) + "\n" for v in x)
    with open(os.path.join(destino, "fa_y.hex"), "w") as f:
        f.writelines(h16(v) + "\n" for v in y16)
    with open(os.path.join(destino, "fa_n.txt"), "w") as f:
        f.write(f"{len(coefs)} {N}\n")
    satura = int(np.sum(np.abs(y16) >= 32767))
    print(f"{caso}: {len(coefs)} secoes, {N} amostras, {satura} na saturacao do int16")


if __name__ == "__main__":
    main()
