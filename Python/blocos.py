"""
blocos.py -- processar na placa sinais maiores do que o hardware aceita.

O conv1d e a FFT da FPGA trabalham com no maximo 1024 amostras por vez
(CONV_N_MAX e FFT_N, em morphe_config). Um sinal lido de arquivo, ou vindo do
ADC, passa disso com facilidade. Este modulo divide o sinal em blocos, manda
cada bloco a placa pelo mesmo caminho que as janelas ja usam, e junta os
resultados:

  * convolucao por overlap-add: x e h sao cortados em pedacos de ate 1024
    amostras; cada par de pedacos vira uma convolucao na placa, e cada
    resultado e somado na posicao certa da saida. O resultado e exatamente a
    convolucao linear de x com h -- os blocos nao aproximam nada, so a
    quantizacao Q15.16 de cada bloco entra no erro, como numa operacao so;
  * espectrograma: a FFT de 1024 pontos da placa aplicada a quadros janelados
    e sobrepostos do sinal, que e a forma usual de ver o espectro de um sinal
    longo (STFT). O espectro medio dos quadros e o metodo de Welch.

As funcoes de bloco recebem a operacao de UM bloco como parametro
(`conv_bloco`, `fft_bloco`). Na placa, sao `ConvPlaca` e `FftPlaca`; nos
testes sem placa, `np.convolve` e `np.fft.fft` -- o que permite conferir a
montagem dos blocos separada do hardware.

Custo: cada bloco e uma requisicao, e a placa atende ~8 por segundo (medido em
22/09/2026, docs/GERENCIAMENTO-PLACAS.md). Uma convolucao de 5000 amostras por
um filtro de 67 coeficientes sao 5 requisicoes; 5 s de audio a 44,1 kHz sao
216, perto de meio minuto.
"""
from __future__ import annotations

import math
from typing import Callable, Optional

import numpy as np

import dsp_core as dsp
from morphe_protocol import (DTYPE_CODES, TcpClient, build_conv_request,
                             build_fft_request, decode_fft_response)

Progresso = Optional[Callable[[int, int], None]]


# ---------------------------------------------------------------------------
# Uma operacao na placa
# ---------------------------------------------------------------------------

class ConvPlaca:
    """Convolucao linear de ate CONV_N_MAX + CONV_N_MAX amostras na placa.

    E exatamente o que a janela de convolucao sempre fez: completa x e h com
    zeros ate o tamanho do hardware, converte para Q15.16, pede a placa e
    corta a saida em len(x) + len(h) - 1. `n_out` guarda quantas amostras a
    placa devolveu na ultima chamada (2047 com o hardware de 1024), que e o
    numero que diz se hardware, protocolo e servidor estao inteiros.
    """

    def __init__(self, client: TcpClient):
        self.client = client
        self.n_out = 0

    def __call__(self, x: np.ndarray, h: np.ndarray) -> np.ndarray:
        n = dsp.MAX_CONV_INPUT_SIZE
        x_q = dsp.float_to_q1516(dsp.pad_zeros_to(x, n))
        h_q = dsp.float_to_q1516(dsp.pad_zeros_to(h, n))
        req = build_conv_request(x_q.astype(np.float64), h_q.astype(np.float64),
                                 DTYPE_CODES["int32"])
        resp = self.client.request(req)
        if not resp.ok:
            raise RuntimeError(resp.payload.decode("utf-8", "replace"))
        util = len(x) + len(h) - 1
        if resp.n_out < util:
            raise RuntimeError(f"a placa devolveu {resp.n_out} amostras; "
                               f"eram necessarias {util}")
        self.n_out = int(resp.n_out)
        y_q = np.frombuffer(resp.payload, dtype=np.dtype(">i4"), count=resp.n_out)
        return dsp.q1516_to_float(y_q)[:util]


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
# Convolucao por overlap-add
# ---------------------------------------------------------------------------

def n_requisicoes_conv(nx: int, nh: int, n_max: int = dsp.MAX_CONV_INPUT_SIZE) -> int:
    """Quantas convolucoes na placa `conv_por_blocos` faz, no maximo."""
    return math.ceil(nx / n_max) * math.ceil(nh / n_max)


def conv_por_blocos(x: np.ndarray, h: np.ndarray,
                    conv_bloco: Callable[[np.ndarray, np.ndarray], np.ndarray],
                    n_max: int = dsp.MAX_CONV_INPUT_SIZE,
                    progresso: Progresso = None) -> np.ndarray:
    """y = x * h (convolucao linear, len(x) + len(h) - 1 amostras).

    x e h sao cortados em pedacos de ate `n_max`; `conv_bloco(xb, hb)` devolve
    a convolucao linear de um par de pedacos, e cada uma e somada em y a
    partir de i + j, as posicoes de inicio dos dois pedacos. Com x e h ate
    `n_max` e uma chamada so, identica a operacao unica de sempre.

    Pares em que um dos pedacos e todo zero nao vao a placa: contribuiriam
    zero. `progresso(feitos, total)` e chamado a cada par.
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    h = np.asarray(h, dtype=np.float64).ravel()
    if x.size == 0 or h.size == 0:
        raise ValueError("x e h precisam ter pelo menos uma amostra")

    y = np.zeros(x.size + h.size - 1, dtype=np.float64)
    inicios_x = range(0, x.size, n_max)
    inicios_h = range(0, h.size, n_max)
    total = len(inicios_x) * len(inicios_h)
    feitos = 0
    for i in inicios_x:
        xb = x[i:i + n_max]
        for j in inicios_h:
            hb = h[j:j + n_max]
            if xb.any() and hb.any():
                yb = np.asarray(conv_bloco(xb, hb), dtype=np.float64)
                if yb.size != xb.size + hb.size - 1:
                    raise RuntimeError(f"bloco devolveu {yb.size} amostras; "
                                       f"esperadas {xb.size + hb.size - 1}")
                y[i + j:i + j + yb.size] += yb
            feitos += 1
            if progresso is not None:
                progresso(feitos, total)
    return y


# ---------------------------------------------------------------------------
# Espectrograma (STFT) e espectro medio (Welch)
# ---------------------------------------------------------------------------

def janela(nome: str, n: int) -> np.ndarray:
    nome = nome.lower()
    if nome in ("hann", "hanning"):
        return np.hanning(n)
    if nome == "hamming":
        return np.hamming(n)
    if nome in ("retangular", "nenhuma", "boxcar"):
        return np.ones(n)
    raise ValueError(f"janela desconhecida: {nome}")


def espectrograma(x: np.ndarray,
                  fft_bloco: Callable[[np.ndarray], np.ndarray],
                  n_fft: int = dsp.MAX_FFT_INPUT_SIZE,
                  salto: Optional[int] = None,
                  nome_janela: str = "hann",
                  progresso: Progresso = None) -> tuple[np.ndarray, np.ndarray]:
    """FFT de quadros janelados de `x`. Devolve (inicios, X).

    `inicios[q]` e a amostra onde comeca o quadro q; `X[q]` sao os `n_fft`
    bins complexos da FFT dele. Os quadros andam de `salto` em `salto`
    amostras (padrao: metade do quadro, 50 % de sobreposicao, o usual com a
    janela de Hann). O ultimo quadro e completado com zeros, para nenhuma
    amostra do fim ficar de fora. Sinal menor que um quadro vira um quadro so.
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    if x.size == 0:
        raise ValueError("sinal vazio")
    salto = n_fft // 2 if salto is None else int(salto)
    if not 1 <= salto <= n_fft:
        raise ValueError(f"salto deve estar em [1, {n_fft}]")
    w = janela(nome_janela, n_fft)

    n_quadros = 1 + max(0, math.ceil((x.size - n_fft) / salto))
    inicios = np.arange(n_quadros, dtype=np.int64) * salto
    X = np.empty((n_quadros, n_fft), dtype=np.complex128)
    for q, s in enumerate(inicios):
        quadro = np.zeros(n_fft)
        pedaco = x[s:s + n_fft]
        quadro[:pedaco.size] = pedaco
        X[q] = fft_bloco(quadro * w)
        if progresso is not None:
            progresso(q + 1, n_quadros)
    return inicios, X


def espectro_medio(X: np.ndarray, nome_janela: str = "hann") -> np.ndarray:
    """Media de |X|^2 sobre os quadros (metodo de Welch), dividida pela
    energia da janela, sum(w^2).

    Serve para comparar picos entre si e contra uma referencia calculada do
    mesmo jeito; nao e uma densidade espectral calibrada em V^2/Hz."""
    w = janela(nome_janela, X.shape[1])
    return np.mean(np.abs(X) ** 2, axis=0) / np.sum(w ** 2)
