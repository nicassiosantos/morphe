#!/usr/bin/env python3
"""
testa_blocos -- confere o processamento por blocos (blocos.py) e a leitura de
sinais de arquivo (sinal_arquivo.py).

Sem argumentos, roda SEM placa: a operacao de um bloco e o np.convolve / o
np.fft.fft, e o que se confere e a montagem -- o overlap-add tem que dar a
convolucao linear exata, com x e h de qualquer tamanho, inclusive maiores que
o hardware; o espectrograma tem que dar a STFT feita a mao; e cada formato de
arquivo tem que voltar com as mesmas amostras e o mesmo fs.

Com --placa, roda contra o hardware:

  * convolucao de um sinal de 5000 amostras (duas senoides) por um passa-baixa
    de 67 coeficientes, em blocos, contra np.convolve em float64;
  * espectrograma de uma varredura de frequencia de 8192 amostras, com a FFT
    da placa, contra o mesmo espectrograma com np.fft.

    python3 ferramentas/testa_blocos.py
    python3 ferramentas/testa_blocos.py --placa 172.16.230.24

O criterio na placa e relacao sinal-erro, nao igualdade: cada bloco carrega a
quantizacao Q15.16 (convolucao) ou Q15.8 (FFT) da operacao unica, e so ela.
Referencia medida em 22/09/2026 para uma operacao so, 67 coeficientes: 71 dB.
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
import dsp_core as dsp
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


def passa_baixa(n_taps: int = 67, fc: float = 0.25) -> np.ndarray:
    """Sinc janelado com Hamming, fc em fracao de fs. Ganho unitario em DC."""
    m = np.arange(n_taps) - (n_taps - 1) / 2
    h = 2 * fc * np.sinc(2 * fc * m) * np.hamming(n_taps)
    return h / h.sum()


# ---------------------------------------------------------------------------
# Sem placa
# ---------------------------------------------------------------------------

def sem_placa() -> None:
    rng = np.random.default_rng(23)
    print("\n[1] overlap-add contra np.convolve (a operacao de bloco e o np.convolve)")
    for nx, nh in [(10, 5), (1024, 1024), (1025, 3), (5000, 67), (3000, 2500),
                   (1, 1), (4096, 1)]:
        x, h = rng.standard_normal(nx), rng.standard_normal(nh)
        chamadas = []

        def bloco(xb, hb):
            assert xb.size <= 1024 and hb.size <= 1024, "bloco maior que o hardware"
            chamadas.append(1)
            return np.convolve(xb, hb)

        y = blocos.conv_por_blocos(x, h, bloco)
        ref = np.convolve(x, h)
        erro = float(np.max(np.abs(y - ref)))
        esperadas = blocos.n_requisicoes_conv(nx, nh)
        confere(y.size == ref.size and erro < 1e-9 and len(chamadas) == esperadas,
                f"x={nx:5d} h={nh:5d}: {y.size} amostras, erro max {erro:.1e}, "
                f"{len(chamadas)} blocos (previstos {esperadas})")

    x = np.zeros(4096); x[3000] = 1.0
    chamadas = []
    y = blocos.conv_por_blocos(x, np.ones(8), lambda a, b: chamadas.append(1) or np.convolve(a, b))
    confere(len(chamadas) == 1 and y[3000:3008].sum() == 8,
            f"blocos todo zero nao vao a placa: 1 de 4 enviado ({len(chamadas)})")

    print("\n[2] espectrograma contra a STFT feita a mao (a FFT de bloco e o np.fft)")
    x = rng.standard_normal(5000)
    inicios, X = blocos.espectrograma(x, np.fft.fft, n_fft=1024, salto=512)
    w = np.hanning(1024)
    ok = True
    for q, s in enumerate(inicios):
        quadro = np.zeros(1024); pedaco = x[s:s + 1024]; quadro[:pedaco.size] = pedaco
        ok &= np.allclose(X[q], np.fft.fft(quadro * w))
    confere(ok and inicios[-1] + 1024 >= x.size and len(inicios) == 9,
            f"{len(inicios)} quadros de 1024 com salto 512 cobrem as 5000 amostras")
    _, X1 = blocos.espectrograma(np.ones(100), np.fft.fft)
    confere(X1.shape == (1, 1024), "sinal menor que um quadro vira um quadro so")

    print("\n[3] leitura de arquivo")
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

    print(f"\n[4] convolucao em blocos na placa {ip}")
    fs = 8000.0
    n = np.arange(5000)
    x = 0.8 * np.sin(2 * np.pi * 300 * n / fs) + 0.5 * np.sin(2 * np.pi * 3000 * n / fs)
    h = passa_baixa(67, fc=0.125)                          # corta em 1 kHz
    t0 = time.monotonic()
    y = blocos.conv_por_blocos(x, h, blocos.ConvPlaca(cli))
    seg = time.monotonic() - t0
    ref = np.convolve(x, h)
    s = snr_db(ref, y)
    confere(y.size == ref.size and s > 60,
            f"x=5000 h=67: {blocos.n_requisicoes_conv(5000, 67)} blocos em {seg:.2f} s, "
            f"relacao sinal-erro {s:.1f} dB (referencia de uma operacao: 71 dB)")
    miolo = y[200:4800]
    confere(np.max(np.abs(miolo)) < 0.9,
            f"o tom de 3 kHz foi filtrado: pico da saida {np.max(np.abs(miolo)):.3f} "
            f"(so o de 300 Hz, amplitude 0,8)")

    print(f"\n[5] espectrograma com a FFT da placa {ip}")
    N = 8192
    tt = np.arange(N) / fs
    chirp = np.sin(2 * np.pi * (100 * tt + (3500 - 100) / (2 * tt[-1]) * tt ** 2))
    t0 = time.monotonic()
    ini, Xp = blocos.espectrograma(chirp, blocos.FftPlaca(cli))
    seg = time.monotonic() - t0
    _, Xr = blocos.espectrograma(chirp, np.fft.fft)
    s = snr_db(Xr, Xp)
    confere(s > 50, f"{len(ini)} quadros em {seg:.2f} s, relacao sinal-erro {s:.1f} dB")
    picos_p = np.argmax(np.abs(Xp[:, :512]), axis=1)
    picos_r = np.argmax(np.abs(Xr[:, :512]), axis=1)
    confere(np.array_equal(picos_p, picos_r),
            "o pico de cada quadro cai no mesmo bin da referencia "
            f"({picos_p[0]} ... {picos_p[-1]}: a frequencia sobe, como a varredura)")


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
