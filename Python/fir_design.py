"""fir_design.py -- projeto de filtros FIR pelo metodo da janela.

Implementacao 100% NumPy (sem scipy). Suporta os 4 tipos classicos:
passa-baixa (LP), passa-alta (HP), passa-banda (BP) e rejeita-banda (BS).

O metodo da janela funciona assim:
  1. Comecamos da resposta impulsiva ideal h_ideal[n] do filtro
     (sinc para LP, soma de sincs para BP, etc), centrada em m=(N-1)/2
  2. Multiplicamos por uma janela w[n] (Hamming, Hanning, Blackman, ou
     retangular) que reduz o ripple de Gibbs no dominio da frequencia
  3. Normalizamos para ganho unitario na banda passante

Limitacao: usamos apenas N IMPAR (>= 3). Filtros tipo I (simetricos com
N impar) tem fase linear e atraso de grupo inteiro, e a "construcao por
delta" da inversao espectral funciona limpa. Para N par seria preciso
tipo II/III/IV, com complicacoes que nao precisamos aqui.
"""
from __future__ import annotations

import numpy as np


WINDOW_KINDS = ("rectangular", "hamming", "hanning", "blackman")
"""Janelas suportadas. Ordem de qualidade crescente (atenuacao de stopband):
rectangular (-21 dB) < hanning (-44 dB) < hamming (-53 dB) < blackman (-74 dB),
em troca de transicao mais larga."""

FILTER_KINDS = ("lowpass", "highpass", "bandpass", "bandstop")


def get_window(N: int, kind: str) -> np.ndarray:
    """Retorna a janela de comprimento N do tipo solicitado."""
    if N <= 0:
        raise ValueError("N deve ser > 0")
    if kind not in WINDOW_KINDS:
        raise ValueError(f"janela desconhecida: {kind!r}")

    if N == 1:
        return np.ones(1)
    n = np.arange(N, dtype=np.float64)
    if kind == "rectangular":
        return np.ones(N)
    if kind == "hamming":
        return 0.54 - 0.46 * np.cos(2.0 * np.pi * n / (N - 1))
    if kind == "hanning":
        return 0.5 - 0.5 * np.cos(2.0 * np.pi * n / (N - 1))
    if kind == "blackman":
        return (0.42
                - 0.5  * np.cos(2.0 * np.pi * n / (N - 1))
                + 0.08 * np.cos(4.0 * np.pi * n / (N - 1)))
    raise ValueError(f"janela desconhecida: {kind!r}")


def _check_odd_N(N: int):
    if N < 3:
        raise ValueError(f"N={N} muito pequeno; minimo 3")
    if N % 2 == 0:
        raise ValueError(
            f"N={N} deve ser IMPAR para projeto tipo I "
            "(fase linear + inversao espectral limpa)"
        )


def design_lowpass(N: int, fc: float, fs: float,
                    window: str = "hamming") -> np.ndarray:
    """Projeta passa-baixa de N taps com cutoff fc Hz e taxa fs Hz."""
    _check_odd_N(N)
    if not (0 < fc < fs / 2):
        raise ValueError(
            f"fc={fc} deve estar em (0, fs/2) = (0, {fs/2})")

    m = (N - 1) / 2.0
    n = np.arange(N, dtype=np.float64)
    h_ideal = (2.0 * fc / fs) * np.sinc(2.0 * (fc / fs) * (n - m))
    w = get_window(N, window)
    h = h_ideal * w
    s = np.sum(h)
    if abs(s) > 1e-12:
        h = h / s
    return h


def design_highpass(N: int, fc: float, fs: float,
                     window: str = "hamming") -> np.ndarray:
    """Projeta passa-alta por inversao espectral do passa-baixa.

    h_hp[n] = delta[n - m] - h_lp[n]
    """
    _check_odd_N(N)
    if not (0 < fc < fs / 2):
        raise ValueError(
            f"fc={fc} deve estar em (0, fs/2) = (0, {fs/2})")

    h_lp = design_lowpass(N, fc, fs, window)
    m = (N - 1) // 2
    h_hp = -h_lp.copy()
    h_hp[m] += 1.0
    return h_hp


def design_bandpass(N: int, fc1: float, fc2: float, fs: float,
                     window: str = "hamming") -> np.ndarray:
    """Projeta passa-banda como diferenca de dois passa-baixas."""
    _check_odd_N(N)
    if not (0 < fc1 < fc2 < fs / 2):
        raise ValueError(
            f"fc1={fc1} e fc2={fc2} devem satisfazer "
            f"0 < fc1 < fc2 < fs/2 = {fs/2}")

    h_lp1 = design_lowpass(N, fc1, fs, window)
    h_lp2 = design_lowpass(N, fc2, fs, window)
    return h_lp2 - h_lp1


def design_bandstop(N: int, fc1: float, fc2: float, fs: float,
                     window: str = "hamming") -> np.ndarray:
    """Projeta rejeita-banda como soma de passa-baixa + passa-alta."""
    _check_odd_N(N)
    if not (0 < fc1 < fc2 < fs / 2):
        raise ValueError(
            f"fc1={fc1} e fc2={fc2} devem satisfazer "
            f"0 < fc1 < fc2 < fs/2 = {fs/2}")

    h_lp = design_lowpass(N,  fc1, fs, window)
    h_hp = design_highpass(N, fc2, fs, window)
    return h_lp + h_hp


def design_filter(kind: str, N: int, fs: float,
                   fc1: float, fc2: float = None,
                   window: str = "hamming") -> np.ndarray:
    """Despacho generico. fc2 e ignorado para LP/HP."""
    if kind == "lowpass":
        return design_lowpass(N, fc1, fs, window)
    if kind == "highpass":
        return design_highpass(N, fc1, fs, window)
    if kind == "bandpass":
        if fc2 is None:
            raise ValueError("bandpass exige fc2")
        return design_bandpass(N, fc1, fc2, fs, window)
    if kind == "bandstop":
        if fc2 is None:
            raise ValueError("bandstop exige fc2")
        return design_bandstop(N, fc1, fc2, fs, window)
    raise ValueError(f"tipo de filtro desconhecido: {kind!r}")


def frequency_response(h: np.ndarray, fs: float = 1.0,
                        n_freq: int = 2048) -> tuple[np.ndarray, np.ndarray]:
    """Calcula a resposta em frequencia complexa H(f) via FFT zero-padded.

    Retorna (f_array, H_complex) com f no intervalo [0, fs/2] (DFT real).
    """
    H = np.fft.rfft(h, n=n_freq)
    f = np.fft.rfftfreq(n_freq, d=1.0 / fs)
    return f, H


def describe_filter(kind: str, N: int, fs: float,
                     fc1: float, fc2: float = None,
                     window: str = "hamming") -> str:
    """Gera descricao textual de uma linha. Formato compativel com o
    cabecalho '#' dos arquivos .txt esperado pelo parser do Morphe."""
    pt = {
        "lowpass":  "passa-baixa",
        "highpass": "passa-alta",
        "bandpass": "passa-banda",
        "bandstop": "rejeita-banda",
    }.get(kind, kind)
    win_pt = {
        "rectangular": "Retangular",
        "hamming":     "Hamming",
        "hanning":     "Hanning",
        "blackman":    "Blackman",
    }.get(window, window)
    if kind in ("bandpass", "bandstop"):
        return (f"{pt} Fc1={fc1:g}Hz Fc2={fc2:g}Hz @ Fs={fs:g}Hz, "
                f"N={N}, {win_pt}")
    return f"{pt} Fc={fc1:g}Hz @ Fs={fs:g}Hz, N={N}, {win_pt}"


def save_coefficients_txt(path: str, h: np.ndarray,
                           description: str = None) -> None:
    """Salva coeficientes em formato compativel com o parser do Morphe."""
    if not path.lower().endswith((".txt", ".coef")):
        path += ".txt"
    with open(path, "w", encoding="utf-8") as f:
        if description:
            f.write(f"# {description}\n")
        f.write(" ".join(f"{v:.10f}" for v in h))
        f.write("\n")
