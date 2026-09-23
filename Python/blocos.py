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
  * FIR: o mesmo overlap-add, pela operacao FIR da placa;
  * FFT e IFFT longas: uma DFT de 1024*M pontos pelo algoritmo de quatro
    passos -- M transformadas de 1024 na placa, ligadas no PC. Exata;
  * IIR: blocos com aquecimento, porque a realimentacao nao se decompoe
    exatamente; ver a secao do IIR, abaixo;
  * espectrograma: a FFT de 1024 pontos da placa aplicada a quadros janelados
    e sobrepostos do sinal (STFT). O espectro medio dos quadros e o metodo de
    Welch.

As funcoes de bloco recebem a operacao de UM bloco como parametro. Na placa,
sao `ConvPlaca`, `FirPlaca`, `FftPlaca`, `IfftPlaca` e `IirPlaca`; nos testes
sem placa, `np.convolve`, `np.fft.fft` e o modelo em ponto fixo -- o que
permite conferir a montagem dos blocos separada do hardware.

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
from morphe_config import IIR_N_MAX
from morphe_protocol import (DTYPE_CODES, TcpClient, build_conv_request,
                             build_fft_request, build_fir_request,
                             build_ifft_request, build_iir_request,
                             decode_fft_response, decode_fir_response,
                             decode_ifft_response, decode_iir_response)

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


class FirPlaca(ConvPlaca):
    """O mesmo que ConvPlaca, pela operacao FIR: a segunda instancia do
    conv1d na FPGA (OP_FIR), com o mesmo formato Q15.16 e a mesma saida."""

    def __call__(self, x: np.ndarray, h: np.ndarray) -> np.ndarray:
        n = dsp.MAX_CONV_INPUT_SIZE
        x_q = dsp.float_to_q1516(dsp.pad_zeros_to(x, n))
        h_q = dsp.float_to_q1516(dsp.pad_zeros_to(h, n))
        resp = self.client.request(build_fir_request(x_q, h_q, DTYPE_CODES["int32"]))
        y_q = decode_fir_response(resp)
        util = len(x) + len(h) - 1
        if y_q.size < util:
            raise RuntimeError(f"a placa devolveu {y_q.size} amostras; "
                               f"eram necessarias {util}")
        self.n_out = int(y_q.size)
        return dsp.q1516_to_float(y_q.astype(np.int32))[:util]


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


class IfftPlaca:
    """IFFT de FFT_N pontos na placa (OP_IFFT, o mesmo IP com `inverse`),
    na convencao do np.fft.ifft -- com o 1/N."""

    def __init__(self, client: TcpClient, normalizar: bool = True):
        self.client = client
        self.normalizar = normalizar
        self.ultima_escala = 1.0     # a escala Q15.8 do ultimo bloco enviado

    def __call__(self, X: np.ndarray) -> np.ndarray:
        if len(X) != dsp.MAX_FFT_INPUT_SIZE:
            raise ValueError(f"a IFFT da placa e de {dsp.MAX_FFT_INPUT_SIZE} pontos; "
                             f"veio {len(X)}")
        req, escala = build_ifft_request(X, normalizar=self.normalizar)
        self.ultima_escala = escala
        return decode_ifft_response(self.client.request(req), escala)


class IirPlaca:
    """Uma execucao do bloco IIR da placa: ate IIR_N_MAX amostras, estado
    inicial zero. Recebe x em float, devolve (y em inteiros Q15.16, saturou)
    -- os inteiros, porque e neles que a placa e conferida bit a bit contra
    o modelo."""

    def __init__(self, client: TcpClient, coefs_q):
        self.client = client
        self.coefs_q = coefs_q

    def __call__(self, x: np.ndarray) -> tuple[np.ndarray, bool]:
        req = build_iir_request(q1516_iir(x), self.coefs_q, DTYPE_CODES["int32"])
        return decode_iir_response(self.client.request(req))


def q1516_iir(v: np.ndarray) -> np.ndarray:
    """float -> inteiros Q15.16 com o arredondamento do IIR, floor(v*2^16+0.5),
    saturado. E o mesmo `_q` da iir_window: dsp.float_to_q1516 usa np.round,
    que empata para o par, e num IIR um LSB de diferenca nao some."""
    lim = 1 << 31
    q = np.floor(np.asarray(v, dtype=np.float64) * 65536.0 + 0.5)
    return np.clip(q, -lim, lim - 1).astype(np.int64)


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
# FFT e IFFT longas: o algoritmo de quatro passos
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


def ifft_longa(X: np.ndarray, ifft_bloco: Callable[[np.ndarray], np.ndarray],
               n_bloco: int = dsp.MAX_FFT_INPUT_SIZE,
               progresso: Progresso = None) -> np.ndarray:
    """IFFT de um espectro de N = M * `n_bloco` pontos (convencao do
    np.fft.ifft, com 1/N). Um espectro nao pode ser completado com zeros
    como um sinal no tempo -- mudaria o sinal que ele representa --, entao N
    tem de ser multiplo de `n_bloco`.

    Pela mesma decomposicao da fft_longa, com k = k1 + M*k2 e
    n = 1024*n1 + n2: a placa faz M IFFTs de 1024, uma por subsequencia
    X[k1::M]; cada uma e girada por W_N^(-k1*n2); o PC faz as IDFTs de M
    pontos por coluna. Os fatores 1/1024 (placa) e 1/M (PC) dao o 1/N."""
    X = np.asarray(X, dtype=np.complex128).ravel()
    N = X.size
    if N == 0 or N % n_bloco:
        raise ValueError(f"a IFFT longa precisa de um multiplo de {n_bloco} "
                         f"pontos; o espectro tem {N}")
    M = N // n_bloco
    if M == 1:
        x = np.asarray(ifft_bloco(X))
        if progresso is not None:
            progresso(1, 1)
        return x
    I = np.empty((M, n_bloco), dtype=np.complex128)
    for k1 in range(M):
        I[k1] = ifft_bloco(X[k1::M])
        if progresso is not None:
            progresso(k1 + 1, M)
    giro = np.exp(2j * np.pi * np.outer(np.arange(M), np.arange(n_bloco)) / N)
    return np.fft.ifft(I * giro, axis=0).reshape(-1)


# ---------------------------------------------------------------------------
# IIR por blocos, com aquecimento
# ---------------------------------------------------------------------------
#
# O IIR e realimentado: a saida em n depende de TODA a entrada anterior, e o
# bloco da placa sempre comeca com estado zero. Nao existe decomposicao exata
# como o overlap-add. O que se faz e o usual: cada bloco comeca `aquecimento`
# amostras antes do trecho que interessa, e essas primeiras saidas sao
# descartadas. Se o aquecimento for longo o bastante para o transitorio do
# estado zero morrer -- |polo|^aquecimento abaixo de meio LSB --, o trecho
# guardado coincide com o do filtro rodando sem parar.
#
# Para a conferencia bit a bit da janela continuar valendo, o modelo em
# Python roda com os MESMOS blocos: placa e modelo tem de bater exatamente.
# O quanto os blocos se afastam do filtro continuo e medido a parte.


def aquecimento_iir(sos: np.ndarray, frac_bits: int = 16) -> int:
    """Amostras de aquecimento para o transitorio de estado zero cair abaixo
    de meio LSB do Q15.16, pelo polo de maior modulo, com folga de 50 % e de
    8 amostras por secao (polos repetidos decaem como n^k * |p|^n)."""
    sos = np.atleast_2d(np.asarray(sos, dtype=np.float64))
    p_max = 0.0
    for sec in sos:
        a = sec[3:6] if sec.size == 6 else np.r_[1.0, sec[3:5]]
        raizes = np.roots(a) if np.any(a[1:] != 0) else np.array([0.0])
        p_max = max(p_max, float(np.max(np.abs(raizes))) if raizes.size else 0.0)
    if p_max >= 1.0:
        raise ValueError(f"filtro instavel ou no limite: polo de modulo {p_max:.6f}")
    if p_max == 0.0:
        return 8 * sos.shape[0]                         # so zeros: FIR
    tolerancia = 2.0 ** -(frac_bits + 1)
    base = math.log(tolerancia) / math.log(p_max)
    return int(math.ceil(1.5 * base)) + 8 * sos.shape[0]


def iir_por_blocos(x: np.ndarray,
                   iir_bloco: Callable[[np.ndarray], tuple[np.ndarray, bool]],
                   aquecimento: int,
                   n_max: int = IIR_N_MAX,
                   progresso: Progresso = None) -> tuple[np.ndarray, bool]:
    """Filtra `x` em blocos de ate `n_max`. Devolve (y em inteiros, saturou).

    O primeiro bloco vai sem aquecimento (o estado zero e a verdade no
    inicio do sinal) e guarda as `n_max` saidas; os seguintes comecam
    `aquecimento` amostras antes e guardam `n_max - aquecimento`. Com x ate
    `n_max`, e uma execucao so, identica a de sempre."""
    x = np.asarray(x, dtype=np.float64).ravel()
    if x.size <= n_max:
        y, sat = iir_bloco(x)
        if progresso is not None:
            progresso(1, 1)
        return np.asarray(y, dtype=np.int64), bool(sat)
    util = n_max - aquecimento
    if util < n_max // 8:
        raise ValueError(
            f"o filtro precisa de {aquecimento} amostras de aquecimento, e o bloco "
            f"tem {n_max}: sobraria pouco ou nada por bloco. Os polos estao perto "
            f"demais do circulo unitario para processar este sinal por blocos.")
    total = 1 + math.ceil((x.size - n_max) / util)
    y = np.empty(x.size, dtype=np.int64)
    yb, saturou = iir_bloco(x[:n_max])
    y[:n_max] = yb
    s = n_max
    feitos = 1
    if progresso is not None:
        progresso(feitos, total)
    while s < x.size:
        seg = x[s - aquecimento:s + util]
        yb, sat = iir_bloco(seg)
        yb = np.asarray(yb, dtype=np.int64)
        guarda = yb[aquecimento:]
        y[s:s + guarda.size] = guarda
        saturou |= bool(sat)
        s += util
        feitos += 1
        if progresso is not None:
            progresso(feitos, total)
    return y, saturou


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
