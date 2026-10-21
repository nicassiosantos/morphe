"""
blocos.py -- FFT na placa de sinais maiores do que o hardware aceita.

A FFT da FPGA trabalha com 1024 pontos por vez (FFT_N, em morphe_config). Um
sinal lido de arquivo, ou vindo do ADC, passa disso com facilidade. Este
modulo calcula uma DFT de 1024*M pontos pelo algoritmo de quatro passos: M
transformadas de 1024 na placa, ligadas no PC. Exata -- os blocos nao
aproximam nada, so a quantizacao Q15.8 de cada bloco entra no erro.

`fft_longa` recebe a FFT de UM bloco como parametro. Na placa, e `FftPlaca`;
nos testes sem placa, `np.fft.fft` -- o que permite conferir a montagem dos
blocos separada do hardware.

Custo: cada bloco e uma requisicao, e a placa atende ~8 por segundo (medido em
22/09/2026, docs/GERENCIAMENTO-PLACAS.md).
"""
from __future__ import annotations

import math
from typing import Callable, Optional

import numpy as np

import dsp_core as dsp
from morphe_protocol import TcpClient, build_fft_request, decode_fft_response

Progresso = Optional[Callable[[int, int], None]]


# ---------------------------------------------------------------------------
# Uma FFT na placa
# ---------------------------------------------------------------------------

class FftPlaca:
    """FFT de FFT_N pontos na placa, com a normalizacao da janela de FFT.

    O bloco e completado com zeros ate FFT_N. Com `normalizar` (o padrao da
    janela), cada bloco e escalado para encostar no teto do Q15.8 e a escala e
    desfeita na volta -- blocos de amplitudes diferentes nao perdem precisao
    uns pelos outros.
    """

    def __init__(self, client: TcpClient, normalizar: bool = True):
        self.client = client
        self.normalizar = normalizar

    def __call__(self, x: np.ndarray) -> np.ndarray:
        x = dsp.pad_zeros_to(x, dsp.MAX_FFT_INPUT_SIZE)
        req, escala = build_fft_request(x, normalizar=self.normalizar)
        return decode_fft_response(self.client.request(req), escala)


# ---------------------------------------------------------------------------
# FFT longa: o algoritmo de quatro passos
# ---------------------------------------------------------------------------
#
# Uma DFT de N = M * 1024 pontos se decompoe em DFTs de 1024 (na placa) e
# DFTs de M pontos (no PC), ligadas por fatores de giro -- e a decomposicao
# de Cooley-Tukey com N1 = M e N2 = 1024. Com n = n1 + M*n2 e k = 1024*k1 + k2:
#
#   X[1024*k1 + k2] = sum_{n1} W_M^(n1*k1) * W_N^(n1*k2) * FFT_1024{x[n1 + M*n2]}[k2]
#
# 1. a placa faz M FFTs de 1024 pontos, uma por subsequencia x[n1::M];
# 2. cada resultado e multiplicado pelos fatores de giro W_N^(n1*k2);
# 3. o PC faz 1024 DFTs de M pontos, uma por coluna k2;
# 4. a matriz resultante, lida por linhas, e o X[k] na ordem natural.
#
# Nao e aproximacao: e a mesma DFT, com a conta dividida. A precisao e a das
# FFTs de 1024 da placa (cada uma normalizada por conta propria) somada a do
# float64 do PC, que e desprezivel perto dela.


def n_fft_longa(n: int, n_bloco: int = dsp.MAX_FFT_INPUT_SIZE) -> int:
    """Tamanho da FFT de um sinal de n amostras: o multiplo de 1024 acima."""
    return max(1, math.ceil(n / n_bloco)) * n_bloco


def fft_longa(x: np.ndarray, fft_bloco: Callable[[np.ndarray], np.ndarray],
              n_bloco: int = dsp.MAX_FFT_INPUT_SIZE,
              progresso: Progresso = None) -> np.ndarray:
    """FFT de `x` completado com zeros ate o multiplo de `n_bloco` acima.
    Com x ate `n_bloco`, e uma FFT so, identica a de sempre."""
    x = np.asarray(x, dtype=np.float64).ravel()
    N = n_fft_longa(x.size, n_bloco)
    xp = np.zeros(N)
    xp[:x.size] = x
    M = N // n_bloco
    if M == 1:
        X = np.asarray(fft_bloco(xp))
        if progresso is not None:
            progresso(1, 1)
        return X
    A = np.empty((M, n_bloco), dtype=np.complex128)
    for n1 in range(M):
        A[n1] = fft_bloco(xp[n1::M])
        if progresso is not None:
            progresso(n1 + 1, M)
    giro = np.exp(-2j * np.pi * np.outer(np.arange(M), np.arange(n_bloco)) / N)
    return np.fft.fft(A * giro, axis=0).reshape(-1)
