"""
dsp_core.py — lógica pura (sem Tkinter).

Geração de sinais discretos, operações no tempo, quantização e I/O .mrph.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np


# =======================================================================
# Limites do hardware Morphe
#
# Estas constantes vivem em morphe_config.py (ponto unico de configuracao,
# espelhado em morphe_config.h no servidor C). Aqui apenas re-exportamos
# com nomes que o resto do codigo Python ja usa.
# =======================================================================

from morphe_config import FFT_N as MAX_FFT_INPUT_SIZE
from morphe_config import CONV_N_MAX as MAX_CONV_INPUT_SIZE


# =======================================================================
# Paleta de cores compartilhada entre as janelas (matplotlib)
# =======================================================================

COLOR_X     = "tab:blue"      # sinal de entrada x[n]
COLOR_H     = "tab:orange"    # filtro / impulso h[n]
COLOR_Y     = "tab:green"     # saída y[n] = x ∗ h
COLOR_MAG   = "tab:purple"    # |X[k]|
COLOR_PHASE = "tab:red"       # ∠X[k]


@dataclass
class Signal:
    n: np.ndarray
    x: np.ndarray
    fs: float = 1.0
    description: str = ""
    dtype_out: str = "float32"   # "int32" ou "float32"

    def copy(self) -> "Signal":
        return Signal(self.n.copy(), self.x.copy(), self.fs,
                      self.description, self.dtype_out)


# ---- geradores -----------------------------------------------------------
#
# Convenção: quando o ponto interessante (n0, n_start) cai em [0, N) o
# eixo n começa em 0 (comportamento padrão).  Caso n0 / n_start esteja fora
# desse intervalo (negativo ou maior que N), o eixo é deslocado para que
# o ponto fique visível em torno de 1/3 da janela — assim o usuário vê de
# fato a transição/impulso quando insere valores negativos.

def _choose_start(anchor: int, N: int) -> int:
    """Escolhe o início do eixo n para que `anchor` fique visível."""
    if 0 <= anchor < N:
        return 0
    return anchor - N // 3


def gen_unit_step(N: int, n0: int = 0) -> Signal:
    start = _choose_start(n0, N)
    n = np.arange(start, start + N, dtype=np.int64)
    x = (n >= n0).astype(np.float64)
    return Signal(n, x, description=f"Degrau u[n-{n0}], N={N}")


def gen_unit_impulse(N: int, n0: int = 0) -> Signal:
    start = _choose_start(n0, N)
    n = np.arange(start, start + N, dtype=np.int64)
    x = np.zeros(N, dtype=np.float64)
    if start <= n0 < start + N:
        x[n0 - start] = 1.0
    return Signal(n, x, description=f"Impulso δ[n-{n0}], N={N}")


def gen_sinusoid(N: int, A: float, f: float, fs: float, phase: float = 0.0) -> Signal:
    n = np.arange(N, dtype=np.int64)
    x = A * np.sin(2.0 * np.pi * f * n / fs + phase)
    return Signal(n, x, fs=fs,
                  description=f"Senóide A={A}, f={f}Hz, fs={fs}Hz, φ={phase}, N={N}")


def gen_exponential(N: int, A: float, alpha: float, mode: str = "discrete") -> Signal:
    n = np.arange(N, dtype=np.int64)
    if mode == "continuous":
        x = A * np.exp(alpha * n)
        desc = f"Exp A·exp(α·n), A={A}, α={alpha}, N={N}"
    else:
        x = A * np.power(float(alpha), n.astype(np.float64))
        desc = f"Exp A·α^n, A={A}, α={alpha}, N={N}"
    return Signal(n, x, description=desc)


def gen_rectangular(N: int, A: float, n_start: int, width: int) -> Signal:
    end = n_start + width
    if 0 <= n_start and end <= N:
        start = 0
    else:
        # centra o pulso aproximadamente em 1/3 da janela
        start = n_start - N // 3
    n = np.arange(start, start + N, dtype=np.int64)
    x = np.zeros(N, dtype=np.float64)
    mask = (n >= n_start) & (n < end)
    x[mask] = A
    return Signal(n, x,
                  description=f"Retangular A={A}, início={n_start}, largura={width}, N={N}")


# ---- operações no tempo --------------------------------------------------

def time_shift(sig: Signal, k: int) -> Signal:
    """y[n] = x[n - k] → o eixo n é deslocado de k unidades."""
    out = sig.copy()
    out.n = sig.n + int(k)
    out.description = f"{sig.description} | k={int(k):+d}"
    return out


def time_reverse(sig: Signal) -> Signal:
    """y[n] = x[-n] → eixo é invertido em torno da origem."""
    out = sig.copy()
    out.n = -sig.n[::-1]
    out.x = sig.x[::-1].copy()
    out.description = f"{sig.description} | x[-n]"
    return out


# ---- padding (zero-fill até o tamanho fixo do hardware) ------------------

def pad_zeros_to(x: np.ndarray, size: int) -> np.ndarray:
    """
    Estende `x` com zeros à direita até atingir `size`. Levanta ValueError
    se o sinal já for maior que o limite. Retorna float64.
    """
    arr = np.asarray(x, dtype=np.float64)
    n = arr.size
    if n > size:
        raise ValueError(
            f"Sinal de comprimento {n} excede o máximo de {size} amostras "
            "permitido pelo hardware."
        )
    if n == size:
        return arr.copy()
    out = np.zeros(size, dtype=np.float64)
    out[:n] = arr
    return out


# ---- quantização ---------------------------------------------------------

def quantize(x: np.ndarray, dtype_out: str) -> np.ndarray:
    if dtype_out == "int32":
        clipped = np.clip(np.round(x),
                          np.iinfo(np.int32).min, np.iinfo(np.int32).max)
        return clipped.astype(np.int32)
    if dtype_out == "float32":
        return x.astype(np.float32)
    raise ValueError(f"dtype_out invalido: {dtype_out}")


# =======================================================================
# Q15.8 -- formato fixed-point usado na FFT da FPGA.
#
#   bit layout (24 bits uteis, 32 bits transportados):
#     8 bits de sign-extension | 1 bit de sinal | 15 bits int | 8 bits frac
#                              ^ bit 23 (signal interno do Q15.8)
#
#   valor_float = valor_int24 / 2^8
#   valor_int24 = round(valor_float * 2^8)        [saturado nos limites]
#
#   range:      [-32768.0, +32767.99609375]
#   resolucao:  2^-8 = 0.00390625
#
# Transporte int32:
#   A FPGA usa apenas os 24 bits baixos (num[23:0] em Verilog). Os 8 bits
#   altos do int32 sao sign-extension do bit 23 (sinal interno do Q15.8):
#     - bit 23 = 0 -> bits 31..24 = 0x00 (positivo)
#     - bit 23 = 1 -> bits 31..24 = 0xFF (negativo)
#   Isso garante que: (int32_t) cast no servidor C ja produz valor numerico
#   correto sem precisar de manipulacao de bits manual.
# =======================================================================

from morphe_config import FFT_FRAC_BITS as _FFT_Q_FRAC_BITS

FFT_Q_FRAC_BITS = _FFT_Q_FRAC_BITS                 # = 8 (Q15.8)
FFT_Q_SCALE     = 1 << FFT_Q_FRAC_BITS             # = 256
FFT_Q_INT_BITS  = 24 - 1 - FFT_Q_FRAC_BITS         # = 15 bits inteiros + 1 sinal
FFT_Q_INT24_MAX = (1 << 23) - 1                    # = +8388607  (0x7FFFFF)
FFT_Q_INT24_MIN = -(1 << 23)                       # = -8388608  (0x800000 sign-ext)
FFT_Q_MAX_FLOAT = FFT_Q_INT24_MAX / FFT_Q_SCALE    # = +32767.99609375
FFT_Q_MIN_FLOAT = FFT_Q_INT24_MIN / FFT_Q_SCALE    # = -32768.0
FFT_Q_RESOLUTION = 1.0 / FFT_Q_SCALE               # = 0.00390625


def fft_q1508_encode(x: np.ndarray) -> np.ndarray:
    """Converte um array de floats em int32 no formato Q15.8 da FFT.

    O resultado tem:
      - bits 23..0 : valor Q15.8 (com sinal em complemento de dois no bit 23)
      - bits 31..24: sign-extension do bit 23 (8 copias)

    Em C, ler como `int32_t` ja da o valor numerico correto. Em Verilog,
    pegar `num[23:0]` da o valor Q15.8 que vai para a FFT.

    Valores fora da faixa [-32768.0, +32767.99609375] sao SATURADOS aos
    limites Q15.8 -- nao deixamos overflow silencioso.
    """
    x = np.asarray(x, dtype=np.float64)
    scaled = x * FFT_Q_SCALE
    # Saturacao nos limites do int24 com sinal
    clipped = np.clip(scaled, FFT_Q_INT24_MIN, FFT_Q_INT24_MAX)
    int24 = np.round(clipped).astype(np.int64)

    # Sign-extension dos bits 31..24 a partir do bit 23.
    # Truque: como int24 e int64 ja com valor matematicamente correto,
    # basta cast para int32 -- o cast preserva sinal e o numpy ajusta os
    # bits altos automaticamente para sign-extension (porque int24 com
    # sinal ja foi armazenado como int64 sinalizado). Ex.: -1 vira
    # 0xFFFFFFFF em int32, que e exatamente sign-extension de 0xFFFFFF.
    return int24.astype(np.int32)


def fft_q1508_decode(int24_arr: np.ndarray) -> np.ndarray:
    """Decodifica um array int32 (com sign-extension) em floats.

    Inverso de fft_q1508_encode. Usado se algum codigo no cliente Python
    precisar reler valores que ja foram serializados em Q15.8.
    """
    arr = np.asarray(int24_arr, dtype=np.int32).astype(np.float64)
    return arr / FFT_Q_SCALE


def fft_q1508_range_warning(x: np.ndarray) -> "str | None":
    """Retorna None se valores cabem em Q15.8, ou mensagem alertando
    sobre saturacao iminente."""
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return None
    mx = float(np.max(np.abs(x)))
    if mx > FFT_Q_MAX_FLOAT:
        return (
            f"Valores excedem a faixa Q15.8 [{FFT_Q_MIN_FLOAT:.1f}, "
            f"{FFT_Q_MAX_FLOAT:.4f}]. Maximo absoluto: {mx:.3f}. "
            "Havera saturacao na quantizacao."
        )
    return None


# ---- deteccao de picos (sem dependencia de scipy) ------------------------
#
# Usado pela janela de FFT para destacar os bins de maior magnitude.
# Algoritmo simples: um indice i e pico se x[i] > x[i-1] e x[i] > x[i+1]
# (estritamente). Aplicamos opcionalmente um threshold relativo ao maximo
# global, e retornamos os top-N picos ordenados por amplitude decrescente.

def find_peaks_simple(x: np.ndarray, *,
                      max_peaks: int = 5,
                      rel_threshold: float = 0.05,
                      min_distance: int = 1) -> np.ndarray:
    """
    Encontra picos locais em um vetor 1D.

    - rel_threshold: ignora picos com amplitude < rel_threshold * max(x).
    - min_distance: distancia minima entre picos (em amostras).
    - max_peaks: limita o numero de picos retornados (por amplitude).

    Retorna: array de indices dos picos, ordenados pelo indice (crescente).
    """
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    if n < 3:
        return np.array([], dtype=np.int64)

    # Picos locais estritos
    is_peak = (x[1:-1] > x[:-2]) & (x[1:-1] > x[2:])
    candidates = np.flatnonzero(is_peak) + 1  # +1 por causa do slice [1:-1]
    if candidates.size == 0:
        return np.array([], dtype=np.int64)

    # Threshold relativo
    abs_max = float(np.max(x))
    if abs_max > 0:
        thr = rel_threshold * abs_max
        candidates = candidates[x[candidates] >= thr]
    if candidates.size == 0:
        return np.array([], dtype=np.int64)

    # Ordena candidatos por amplitude decrescente, depois aplica
    # min_distance gulosamente (descarta candidatos vizinhos a um ja aceito).
    order = candidates[np.argsort(-x[candidates])]
    selected: list[int] = []
    for idx in order:
        if len(selected) >= max_peaks:
            break
        if all(abs(int(idx) - s) >= min_distance for s in selected):
            selected.append(int(idx))

    return np.array(sorted(selected), dtype=np.int64)


# =======================================================================
# Q15.16 — formato fixed-point usado na conv1d da FPGA.
#
#   bit layout (32 bits):
#     1 bit de sinal | 15 bits de parte inteira | 16 bits fracionários
#
#   valor_float = valor_int32 / 2^16
#   valor_int32 = round(valor_float * 2^16)   [saturado nos limites]
#
#   range: [-32768.0, +32767.999984741...]
#   resolução: 2^-16 ≈ 1.5259 × 10^-5
# =======================================================================

Q_FRAC_BITS = 16
Q_SCALE = 1 << Q_FRAC_BITS          # 65536
Q_MAX   = np.iinfo(np.int32).max    # 0x7FFFFFFF
Q_MIN   = np.iinfo(np.int32).min    # -0x80000000
Q_MAX_FLOAT = Q_MAX / Q_SCALE       # +32767.999984...
Q_MIN_FLOAT = Q_MIN / Q_SCALE       # -32768.0
Q_RESOLUTION = 1.0 / Q_SCALE        # ≈ 1.5259e-5


def float_to_q1516(x: np.ndarray) -> np.ndarray:
    """
    Converte um array de floats para int32 em formato Q15.16, com saturação.
    """
    x = np.asarray(x, dtype=np.float64)
    scaled = x * Q_SCALE
    clipped = np.clip(scaled, Q_MIN, Q_MAX)
    return np.round(clipped).astype(np.int32)


def q1516_to_float(x: np.ndarray) -> np.ndarray:
    """Converte int32 em Q15.16 de volta para float64."""
    return np.asarray(x, dtype=np.int64).astype(np.float64) / Q_SCALE


def q1516_range_warning(x: np.ndarray) -> str | None:
    """
    Retorna None se os valores cabem em Q15.16, ou uma mensagem explicando
    o overflow/saturação que vai acontecer.
    """
    x = np.asarray(x, dtype=np.float64)
    mx = float(np.max(np.abs(x))) if x.size else 0.0
    if mx > Q_MAX_FLOAT:
        return (f"Valores excedem a faixa Q15.16 [{Q_MIN_FLOAT:.1f}, "
                f"{Q_MAX_FLOAT:.1f}]. Máximo absoluto: {mx:.3f}. "
                "Haverá saturação.")
    return None


# ---- I/O ---------------------------------------------------------------

def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save_mrph(path: str, sig: Signal) -> None:
    """Salva um sinal real em formato .mrph (texto)."""
    if not path.lower().endswith(".mrph"):
        path += ".mrph"
    x_out = quantize(sig.x, sig.dtype_out)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# MORPHE SIGNAL FILE\n")
        f.write(f"# saved: {_timestamp()}\n")
        f.write(f"# type: {sig.dtype_out}\n")
        f.write(f"# length: {len(sig.n)}\n")
        f.write(f"# fs: {sig.fs}\n")
        f.write(f"# signal: {sig.description}\n")
        f.write("# columns: n value\n")
        if sig.dtype_out == "int32":
            for ni, xi in zip(sig.n, x_out):
                f.write(f"{int(ni)}\t{int(xi)}\n")
        else:
            for ni, xi in zip(sig.n, x_out):
                f.write(f"{int(ni)}\t{float(xi):.8e}\n")


def save_mrph_complex(path: str, n: np.ndarray, z: np.ndarray,
                      description: str = "", fs: float = 1.0) -> None:
    """Salva FFT (valores complexos) em .mrph — 3 colunas: k, re, im."""
    if not path.lower().endswith(".mrph"):
        path += ".mrph"
    with open(path, "w", encoding="utf-8") as f:
        f.write("# MORPHE SIGNAL FILE\n")
        f.write(f"# saved: {_timestamp()}\n")
        f.write("# type: complex_float32\n")
        f.write(f"# length: {len(n)}\n")
        f.write(f"# fs: {fs}\n")
        f.write(f"# signal: {description}\n")
        f.write("# columns: k real imag\n")
        for ki, zi in zip(n, z):
            f.write(f"{int(ki)}\t{zi.real:.8e}\t{zi.imag:.8e}\n")


# ---- Multi-section bundle ---------------------------------------------
#
# Salva varios sinais em UM unico arquivo .mrph, separados por
# blocos "## section: <nome>". Cada secao carrega seus proprios metadados
# e tabela de valores. O parser fica trivial: split em linhas comecadas
# por "## section:" e cada bloco e um mini-arquivo no formato classico.

def _write_section_header(f, name: str, kind: str, length: int,
                          fs: float, description: str, columns: str):
    f.write("\n")
    f.write(f"## section: {name}\n")
    f.write(f"# type: {kind}\n")
    f.write(f"# length: {length}\n")
    f.write(f"# fs: {fs}\n")
    f.write(f"# signal: {description}\n")
    f.write(f"# columns: {columns}\n")


def save_mrph_bundle(path: str, title: str, sections: list) -> None:
    """
    Salva multiplas secoes em um unico arquivo .mrph.

    sections: lista de dicts, cada um com:
        - "name":  str, nome curto da secao (ex.: "x", "h", "y", "X")
        - "kind":  "real" | "complex"
        - "n":     np.ndarray (eixo n ou k)
        - "data":  np.ndarray real (se kind="real") ou complex (se "complex")
        - "description": str (opcional)
        - "fs":    float (opcional, default 1.0)
        - "dtype_out": "float32" | "int32" (opcional, so para real)

    O cabecalho global vai uma vez no topo, depois cada secao tem o seu
    proprio sub-cabecalho. Formato aberto e legivel em qualquer editor.
    """
    if not path.lower().endswith(".mrph"):
        path += ".mrph"
    with open(path, "w", encoding="utf-8") as f:
        f.write("# MORPHE BUNDLE FILE\n")
        f.write(f"# saved: {_timestamp()}\n")
        f.write(f"# title: {title}\n")
        f.write(f"# sections: {len(sections)}\n")
        names = ", ".join(s.get("name", "?") for s in sections)
        f.write(f"# section_names: {names}\n")

        for sec in sections:
            name = sec["name"]
            kind = sec["kind"]
            n_arr = np.asarray(sec["n"])
            data = np.asarray(sec["data"])
            desc = sec.get("description", "")
            fs   = float(sec.get("fs", 1.0))

            if kind == "real":
                dtype_out = sec.get("dtype_out", "float32")
                x_out = quantize(data, dtype_out)
                _write_section_header(
                    f, name=name, kind=dtype_out,
                    length=len(n_arr), fs=fs,
                    description=desc, columns="n value",
                )
                if dtype_out == "int32":
                    for ni, xi in zip(n_arr, x_out):
                        f.write(f"{int(ni)}\t{int(xi)}\n")
                else:
                    for ni, xi in zip(n_arr, x_out):
                        f.write(f"{int(ni)}\t{float(xi):.8e}\n")

            elif kind == "complex":
                _write_section_header(
                    f, name=name, kind="complex_float32",
                    length=len(n_arr), fs=fs,
                    description=desc, columns="k real imag",
                )
                for ki, zi in zip(n_arr, data):
                    f.write(f"{int(ki)}\t{zi.real:.8e}\t{zi.imag:.8e}\n")
            else:
                raise ValueError(f"kind invalido: {kind!r}")

# =======================================================================
# Parser de bundle .mrph -- inverso de save_mrph_bundle()
# =======================================================================
#
# Le um arquivo .mrph e devolve uma estrutura de dicts compativel com o
# formato consumido pelo save_mrph_bundle(). Aceita line endings \r\n
# (Windows) ou \n (POSIX). Ignora linhas vazias e comentarios.
#
# Estrutura retornada:
#   {
#     "title":   str,
#     "saved":   str (timestamp como veio no arquivo),
#     "sections": [
#         { "name":  str,
#           "kind":  "real" | "complex",   # remapeado: complex_float32 -> complex
#           "type":  str,                  # tipo original do header (ex.: "float32")
#           "length": int,
#           "fs":    float,
#           "description": str,
#           "n":     ndarray (eixo n ou k),
#           "data":  ndarray (real ou complex64),
#         },
#         ...
#     ]
#   }
#
# Os tipos "real" sao salvos como float32 ou int32; aqui sempre devolvemos
# como float64 internamente para facilitar comparacoes. O tipo original
# fica preservado em sec["type"] caso alguem precise.

class MrphParseError(ValueError):
    """Erro de parse de arquivo .mrph -- mensagem inclui linha quando possivel."""


def parse_mrph_bundle(path: str) -> dict:
    """Le um arquivo .mrph (formato bundle multi-secao) e retorna um dict.

    Estrutura: vide modulo. Levanta MrphParseError em caso de formato invalido.
    """
    with open(path, "r", encoding="utf-8") as f:
        # splitlines() sem keepends absorve qualquer combinacao de \r\n e \n
        raw = f.read().splitlines()

    # ---- Cabecalho global ---------------------------------------------
    header: dict[str, str] = {}
    i = 0
    while i < len(raw):
        line = raw[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("## section:"):
            break
        if line.startswith("#"):
            # Linha de header global; aceita "# key: value" ou "# COMENTARIO"
            stripped = line.lstrip("#").strip()
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                header[key.strip()] = val.strip()
        i += 1

    # Validacao minima do header
    if "title" not in header:
        raise MrphParseError(
            f"{path}: cabecalho sem '# title:' -- nao parece um bundle Morphe."
        )

    # ---- Secoes -------------------------------------------------------
    sections: list[dict] = []
    while i < len(raw):
        line = raw[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("## section:"):
            sec, next_i = _parse_section(raw, i, path)
            sections.append(sec)
            i = next_i
        else:
            i += 1

    if not sections:
        raise MrphParseError(f"{path}: nenhuma secao encontrada.")

    return {
        "title":  header.get("title", ""),
        "saved":  header.get("saved", ""),
        "sections": sections,
    }


def _parse_section(lines: list[str], start: int, path: str) -> tuple[dict, int]:
    """Le uma secao a partir de lines[start] (linha '## section: NAME').

    Retorna (dict_secao, indice_da_linha_apos_secao).
    """
    header_line = lines[start].strip()
    name = header_line.split(":", 1)[1].strip()

    meta: dict[str, str] = {}
    i = start + 1
    # ---- Sub-cabecalho: linhas '# key: value' ate primeira linha de dados
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("## section:"):
            # Secao seguinte sem dados na atual? Aceita mas marca length=0
            break
        if line.startswith("#"):
            stripped = line.lstrip("#").strip()
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                meta[key.strip()] = val.strip()
            i += 1
            continue
        # Primeira linha sem "#" e o inicio dos dados
        break

    type_str = meta.get("type", "float32")
    try:
        length = int(meta.get("length", "0"))
    except ValueError as e:
        raise MrphParseError(
            f"{path} secao '{name}': length invalido: {meta.get('length')!r}"
        ) from e
    try:
        fs = float(meta.get("fs", "1.0"))
    except ValueError as e:
        raise MrphParseError(
            f"{path} secao '{name}': fs invalido: {meta.get('fs')!r}"
        ) from e
    description = meta.get("signal", "")

    # ---- Dados --------------------------------------------------------
    is_complex = type_str.startswith("complex")
    n_list: list[int] = []
    re_list: list[float] = []
    im_list: list[float] = []  # so usado se complex

    while i < len(lines):
        line = lines[i].rstrip()
        # Pode haver linha em branco entre secoes
        if not line.strip():
            i += 1
            continue
        if line.lstrip().startswith("##"):
            break  # proxima secao
        if line.lstrip().startswith("#"):
            # Comentario inline dentro dos dados? Pula.
            i += 1
            continue

        # Linha de dado: tab-separada
        cols = line.split("\t")
        try:
            if is_complex:
                if len(cols) < 3:
                    raise ValueError(
                        f"esperava 3 colunas (k real imag), achei {len(cols)}"
                    )
                n_list.append(int(cols[0]))
                re_list.append(float(cols[1]))
                im_list.append(float(cols[2]))
            else:
                if len(cols) < 2:
                    raise ValueError(
                        f"esperava 2 colunas (n value), achei {len(cols)}"
                    )
                n_list.append(int(cols[0]))
                re_list.append(float(cols[1]))
        except ValueError as e:
            raise MrphParseError(
                f"{path} secao '{name}', linha {i+1}: {e}"
            ) from e
        i += 1

    n_arr = np.asarray(n_list, dtype=np.int64)
    if is_complex:
        data = np.asarray(re_list, dtype=np.float64) + \
               1j * np.asarray(im_list, dtype=np.float64)
        kind = "complex"
    else:
        data = np.asarray(re_list, dtype=np.float64)
        kind = "real"

    # Sanidade: length declarado bate com o numero de amostras lidas?
    if length and length != len(n_arr):
        # Aviso silencioso -- mantemos o real e ignoramos o declarado.
        # Nao queremos abortar por causa de divergencia menor.
        pass

    return {
        "name":        name,
        "kind":        kind,
        "type":        type_str,
        "length":      len(n_arr),
        "fs":          fs,
        "description": description,
        "n":           n_arr,
        "data":        data,
    }, i


def section_by_name(bundle: dict, name: str) -> dict:
    """Atalho: busca uma secao do bundle pelo nome. Levanta KeyError se nao achar."""
    for sec in bundle["sections"]:
        if sec["name"] == name:
            return sec
    raise KeyError(
        f"Secao '{name}' nao encontrada no bundle. "
        f"Disponiveis: {[s['name'] for s in bundle['sections']]}"
    )


# =======================================================================
# Metricas de comparacao numerica
# =======================================================================
#
# Recebem dois arrays do mesmo tamanho (a, b), tratados como vetores
# em R^n ou C^n, e retornam dict com:
#   - max_abs_error  : maior |a[i] - b[i]|
#   - rms_error      : sqrt(mean(|a-b|^2))
#   - snr_db         : 20 * log10(||ref|| / ||a-b||)   (ref = b por convencao)
#   - max_rel_error  : maior |a[i]-b[i]|/|b[i]| ignorando b[i] proximo de zero
#   - max_rel_index  : indice onde max_rel_error ocorre
#
# Por convencao: 'a' e o resultado avaliado (tipico: FPGA), 'b' e a
# referencia (tipico: NumPy). SNR alto = FPGA proxima da referencia.

def compute_error_metrics(a: np.ndarray, b: np.ndarray, *,
                          rel_eps_factor: float = 1e-6) -> dict:
    """Calcula metricas de erro entre 'a' (avaliado) e 'b' (referencia).

    Funciona para arrays reais ou complexos -- usa np.abs() em ambos.

    rel_eps_factor: bins com |b| < rel_eps_factor * max(|b|) sao excluidos
    do calculo de erro relativo (evita divisao por ~0 dominar a metrica).
    """
    a = np.asarray(a)
    b = np.asarray(b)
    if a.shape != b.shape:
        raise ValueError(
            f"shapes diferentes: a={a.shape}, b={b.shape}"
        )

    diff = a - b
    abs_diff = np.abs(diff)
    abs_b = np.abs(b)

    n = a.size
    norm_b = float(np.sqrt(np.sum(abs_b ** 2)))
    norm_diff = float(np.sqrt(np.sum(abs_diff ** 2)))

    # SNR em dB (potencia de sinal sobre potencia de erro)
    if norm_diff < 1e-30 * max(norm_b, 1.0):
        snr_db = float("inf")
    elif norm_b < 1e-30:
        snr_db = float("-inf")
    else:
        snr_db = 20.0 * np.log10(norm_b / norm_diff)

    # Erro relativo: ignora bins onde b e ~zero (poluiriam a metrica)
    if abs_b.max() > 0:
        thr = rel_eps_factor * float(abs_b.max())
        mask = abs_b > thr
        if np.any(mask):
            rel = abs_diff[mask] / abs_b[mask]
            i_local = int(np.argmax(rel))
            i_global = int(np.flatnonzero(mask)[i_local])
            max_rel_error = float(rel[i_local])
            max_rel_index = i_global
        else:
            max_rel_error = float("nan")
            max_rel_index = -1
    else:
        max_rel_error = float("nan")
        max_rel_index = -1

    return {
        "n":              n,
        "max_abs_error":  float(abs_diff.max()) if n > 0 else 0.0,
        "rms_error":      float(np.sqrt(np.mean(abs_diff ** 2))) if n > 0 else 0.0,
        "snr_db":         snr_db,
        "max_rel_error":  max_rel_error,
        "max_rel_index":  max_rel_index,
        "norm_ref":       norm_b,
        "norm_diff":      norm_diff,
    }


# =======================================================================
# Recomputacao via NumPy (referencia matematica)
# =======================================================================
#
# Estas funcoes reproduzem em NumPy o que a FPGA deveria ter computado.
# A diferenca entre o resultado da FPGA (lido do .mrph) e estes valores
# e o erro do hardware (quantizacao Q15.8 / Q15.16, BFP, etc.).

def recompute_conv_numpy(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """Convolucao linear cheia: y[n] = sum_k x[k] * h[n-k].

    Usa np.convolve com mode='full' -- saida tem len(x)+len(h)-1 amostras.
    """
    return np.convolve(np.asarray(x, dtype=np.float64),
                       np.asarray(h, dtype=np.float64),
                       mode="full")


def recompute_fft_numpy(x: np.ndarray, n_fft: int) -> np.ndarray:
    """FFT direta de N pontos. Aplica zero-padding ate n_fft se necessario.

    A FPGA Morphe sempre faz FFT de N=1024 pontos com zero-padding interno;
    essa funcao reproduz isso para uma comparacao justa.
    """
    x = np.asarray(x, dtype=np.float64)
    if len(x) < n_fft:
        x_pad = np.zeros(n_fft, dtype=np.float64)
        x_pad[: len(x)] = x
    elif len(x) > n_fft:
        x_pad = x[: n_fft]
    else:
        x_pad = x
    return np.fft.fft(x_pad)
