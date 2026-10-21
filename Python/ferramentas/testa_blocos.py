#!/usr/bin/env python3
"""
testa_blocos -- confere a FFT longa em quatro passos (blocos.py) e a leitura
de sinais de arquivo (sinal_arquivo.py).

Sem argumentos, roda SEM placa: a FFT de um bloco e o np.fft.fft, e o que se
confere e a montagem -- os quatro passos tem que dar a DFT exata de N pontos,
com N maior que o hardware; e cada formato de arquivo tem que voltar com as
mesmas amostras e o mesmo fs.

Com --placa, roda contra o hardware: FFT de 8192 pontos de uma varredura de
frequencia em quatro passos (8 FFTs da placa) contra np.fft.

    python3 ferramentas/testa_blocos.py
    python3 ferramentas/testa_blocos.py --placa 172.16.230.24

O criterio na placa e relacao sinal-erro, nao igualdade: cada bloco carrega a
quantizacao Q15.8 da FFT unica, e so ela.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

import numpy as np

import _caminho  # noqa: F401 -- poe Python/ no sys.path
import blocos
from morphe_config import DEFAULT_PORT
from morphe_protocol import TcpClient
from sinal_arquivo import carregar_sinal

FALHAS: list[str] = []


def confere(cond: bool, texto: str) -> None:
    print(f"  {'OK   ' if cond else 'FALHA'} {texto}")
    if not cond:
        FALHAS.append(texto)


def snr_db(ref: np.ndarray, obt: np.ndarray) -> float:
    erro = np.sum(np.abs(ref - obt) ** 2)
    return float("inf") if erro == 0 else 10 * np.log10(np.sum(np.abs(ref) ** 2) / erro)


# ---------------------------------------------------------------------------
# Sem placa
# ---------------------------------------------------------------------------

def sem_placa() -> None:
    rng = np.random.default_rng(23)
    print("\n[1] FFT longa em quatro passos (blocos de 1024 com np.fft)")
    for N in (1024, 1500, 4096, 5000, 8192):
        x = rng.standard_normal(N)
        chamadas = []
        X = blocos.fft_longa(x, lambda b: chamadas.append(1) or np.fft.fft(b))
        ref = np.fft.fft(np.r_[x, np.zeros(X.size - N)])
        erro = float(np.max(np.abs(X - ref)) / np.max(np.abs(ref)))
        confere(X.size == blocos.n_fft_longa(N) and len(chamadas) == X.size // 1024
                and erro < 1e-12,
                f"N={N:5d}: FFT de {X.size} pontos em {len(chamadas)} blocos, "
                f"erro relativo {erro:.1e}")

    print("\n[2] leitura de sinais de arquivo")
    with tempfile.TemporaryDirectory() as d:
        v = np.array([0.5, -1.25, 3.0, 0.0, 2.5])
        casos = {
            "uma_coluna.csv": "x\n" + "\n".join(f"{a}" for a in v),
            "indice.txt": "\n".join(f"{i}\t{a}" for i, a in enumerate(v)),
            "tempo.csv": "t,x\n" + "\n".join(f"{i / 8000},{a}" for i, a in enumerate(v)),
            "planilha.csv": "amostra;valor\n" + "\n".join(
                f"{i};{str(a).replace('.', ',')}" for i, a in enumerate(v)),
        }
        fs_esperado = {"tempo.csv": 8000.0}
        for nome, texto in casos.items():
            caminho = os.path.join(d, nome)
            with open(caminho, "w", encoding="utf-8") as f:
                f.write(texto)
            sig = carregar_sinal(caminho)
            confere(np.allclose(sig.x, v) and abs(sig.fs - fs_esperado.get(nome, 1.0)) < 1e-6,
                    f"{nome}: {sig.x.size} amostras, fs={sig.fs:g}")

        np.save(os.path.join(d, "v.npy"), v)
        sig = carregar_sinal(os.path.join(d, "v.npy"))
        confere(np.allclose(sig.x, v), "v.npy")

        from scipy.io import wavfile
        pcm = (np.sin(2 * np.pi * 440 * np.arange(800) / 8000) * 16000).astype(np.int16)
        wavfile.write(os.path.join(d, "a.wav"), 8000, np.column_stack([pcm, -pcm]))
        sig = carregar_sinal(os.path.join(d, "a.wav"))
        confere(sig.fs == 8000 and sig.x.size == 800 and np.allclose(sig.x, pcm / 32768),
                "a.wav estereo de 16 bits: primeiro canal, fs=8000, em [-1, 1)")

        for nome, texto in {"tres_colunas.csv": "1,2,3\n4,5,6",
                            "vazio.txt": "cabecalho\n"}.items():
            caminho = os.path.join(d, nome)
            with open(caminho, "w", encoding="utf-8") as f:
                f.write(texto)
            try:
                carregar_sinal(caminho)
                confere(False, f"{nome} deveria ser recusado")
            except ValueError as e:
                confere(True, f"{nome} recusado: {e}")


# ---------------------------------------------------------------------------
# Com placa
# ---------------------------------------------------------------------------

def com_placa(ip: str, porta: int) -> None:
    cli = TcpClient(ip, porta, timeout=15.0)

    print(f"\n[3] FFT longa (quatro passos) na placa {ip}")
    fs, N = 8000.0, 8192
    tt = np.arange(N) / fs
    chirp = np.sin(2 * np.pi * (100 * tt + (3500 - 100) / (2 * tt[-1]) * tt ** 2))
    t0 = time.monotonic()
    X = blocos.fft_longa(chirp, blocos.FftPlaca(cli))
    seg = time.monotonic() - t0
    s = snr_db(np.fft.fft(chirp), X)
    confere(X.size == 8192 and s > 50,
            f"FFT de 8192 pontos: 8 FFTs da placa em {seg:.2f} s, {s:.1f} dB contra np.fft")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--placa", help="IP da placa; sem ele, so os testes sem placa")
    ap.add_argument("--porta", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()

    print("=== testa_blocos")
    sem_placa()
    if args.placa:
        com_placa(args.placa, args.porta)
    print(f"\n{'FALHAS: ' + str(len(FALHAS)) if FALHAS else 'TUDO OK'}")
    return 1 if FALHAS else 0


if __name__ == "__main__":
    sys.exit(main())
