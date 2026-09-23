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
    da placa, contra o mesmo espectrograma com np.fft;
  * FFT de 8192 pontos em quatro passos (8 FFTs da placa) contra np.fft, e a
    volta pela IFFT longa da placa;
  * a mesma convolucao pela operacao FIR;
  * IIR por blocos (Butterworth de 4a ordem): placa e modelo nos mesmos
    blocos tem de bater bit a bit.

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
from sinal_arquivo import carregar_espectro, carregar_sinal

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

    print("\n[2b] FFT e IFFT longas em quatro passos (blocos de 1024 com np.fft)")
    for N in (1024, 1500, 4096, 5000, 8192):
        x = rng.standard_normal(N)
        X = blocos.fft_longa(x, np.fft.fft)
        ref = np.fft.fft(np.r_[x, np.zeros(X.size - N)])
        xr = blocos.ifft_longa(X, np.fft.ifft)
        erro = float(np.max(np.abs(X - ref)) / np.max(np.abs(ref)))
        volta = float(np.max(np.abs(xr[:N] - x)))
        confere(X.size == blocos.n_fft_longa(N) and erro < 1e-12 and volta < 1e-12,
                f"N={N:5d}: FFT de {X.size} pontos, erro relativo {erro:.1e}; "
                f"ida e volta {volta:.1e}")
    try:
        blocos.ifft_longa(np.ones(1500), np.fft.ifft)
        confere(False, "espectro de 1500 bins deveria ser recusado")
    except ValueError:
        confere(True, "espectro que nao e multiplo de 1024 e recusado")

    print("\n[2c] IIR por blocos com aquecimento (modelo em ponto fixo)")
    import iir_design as iir
    from scipy import signal
    n = np.arange(8000)
    x = 0.5 * np.sin(2 * np.pi * 300 * n / 8000) + 0.3 * np.sin(2 * np.pi * 3000 * n / 8000)
    for nome, sos, tolerancia in [
            ("Butterworth 4a ordem, 1 kHz", signal.butter(4, 1000, fs=8000, output="sos"), 0),
            ("Butterworth 2a ordem, 100 Hz", signal.butter(2, 100, fs=8000, output="sos"), 16)]:
        aq = blocos.aquecimento_iir(sos)
        modelo = lambda seg, sos=sos: (blocos.q1516_iir(iir.filtra_sos_fixo(seg, sos, 16, 32)), False)
        yb, _ = blocos.iir_por_blocos(x, modelo, aq)
        cont = blocos.q1516_iir(iir.filtra_sos_fixo(x, sos, 16, 32))
        d = int(np.max(np.abs(yb - cont)))
        confere(d <= tolerancia,
                f"{nome}: aquecimento {aq}, blocos x filtro continuo {d} LSB "
                f"(tolerado {tolerancia}: ponto fixo nao converge sempre bit a bit)")
    curto = x[:700]
    modelo = lambda seg: (blocos.q1516_iir(iir.filtra_sos_fixo(seg, sos, 16, 32)), False)
    chamadas = []
    y1, _ = blocos.iir_por_blocos(curto, lambda s: chamadas.append(1) or modelo(s), 100)
    confere(len(chamadas) == 1 and np.array_equal(
        y1, blocos.q1516_iir(iir.filtra_sos_fixo(curto, sos, 16, 32))),
        "sinal ate 1024 amostras: uma execucao so, igual a de sempre")

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

        Xc = rng.standard_normal(2048) + 1j * rng.standard_normal(2048)
        np.save(os.path.join(d, "X.npy"), Xc)
        with open(os.path.join(d, "X.csv"), "w", encoding="utf-8") as f:
            f.write("re,im\n" + "\n".join(f"{z.real:.17g},{z.imag:.17g}" for z in Xc))
        confere(np.allclose(carregar_espectro(os.path.join(d, "X.npy")), Xc)
                and np.allclose(carregar_espectro(os.path.join(d, "X.csv")), Xc),
                "espectro complexo de 2048 bins em .npy e em .csv (re, im)")

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

    print(f"\n[6] FFT e IFFT longas (quatro passos) na placa {ip}")
    t0 = time.monotonic()
    X = blocos.fft_longa(chirp, blocos.FftPlaca(cli))
    seg = time.monotonic() - t0
    s = snr_db(np.fft.fft(chirp), X)
    confere(X.size == 8192 and s > 50,
            f"FFT de 8192 pontos: 8 FFTs da placa em {seg:.2f} s, {s:.1f} dB contra np.fft")
    t0 = time.monotonic()
    xr = blocos.ifft_longa(X, blocos.IfftPlaca(cli))
    seg = time.monotonic() - t0
    s = snr_db(chirp, np.real(xr))
    confere(s > 50, f"IFFT de 8192 pontos: 8 IFFTs da placa em {seg:.2f} s; "
                    f"ida e volta pela placa, {s:.1f} dB")

    print(f"\n[7] FIR por blocos na placa {ip} (operacao FIR, nao a convolucao)")
    t0 = time.monotonic()
    y = blocos.conv_por_blocos(x, h, blocos.FirPlaca(cli))
    seg = time.monotonic() - t0
    s = snr_db(np.convolve(x, h), y)
    confere(s > 60, f"x=5000 h=67 pela operacao FIR: 5 blocos em {seg:.2f} s, {s:.1f} dB")

    print(f"\n[8] IIR por blocos na placa {ip}")
    import iir_design as iir
    from scipy import signal
    sos = signal.butter(4, 1000, fs=fs, output="sos")
    coefs = iir.coeficientes_inteiros(sos, 16, 32)
    aq = blocos.aquecimento_iir(sos)
    modelo = lambda seg_: (blocos.q1516_iir(iir.filtra_sos_fixo(seg_, sos, 16, 32)), False)
    t0 = time.monotonic()
    y_hw, sat = blocos.iir_por_blocos(x, blocos.IirPlaca(cli, coefs), aq)
    seg = time.monotonic() - t0
    y_mod, _ = blocos.iir_por_blocos(x, modelo, aq)
    dif = int(np.count_nonzero(y_hw != y_mod))
    confere(dif == 0 and not sat,
            f"Butterworth 4a ordem em 1 kHz, 5000 amostras: aquecimento {aq}, "
            f"{seg:.2f} s; placa x modelo nos mesmos blocos: {dif} amostras diferentes")


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
