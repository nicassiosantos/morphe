"""
q1516.py — Conversão entre Q15.16, inteiro e float.

Formato Q15.16
──────────────
Ponto fixo com sinal em 32 bits:

    ┌─┬───────────────┬────────────────────┐
    │S│  15 bits int  │  16 bits fracionários │
    └─┴───────────────┴────────────────────┘
     31              16 15                  0

    • 1 bit de sinal (complemento de 2)
    • 15 bits para a parte inteira
    • 16 bits para a parte fracionária

    Range:      [-32768.0, +32767.999984...]
    Resolução:  2⁻¹⁶ ≈ 1.5259 × 10⁻⁵

Convenções
──────────
    Valores Q15.16 são armazenados como `int` (Python) ou `np.int32` (numpy).
    O significado posicional dos bits é uniforme — o bit N vale 2^(N-16).

Arredondamento
──────────────
    As funções `*_to_q1516` usam arredondamento truncado (em direção ao zero)
    por padrão, compatível com o cast (int32_t) do C. As variantes com sufixo
    `_round` usam arredondamento para o mais próximo (round-half-to-even),
    que reduz o erro médio de quantização.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray


# ─── Constantes do formato ────────────────────────────────────────────────────

FRAC_BITS: int = 16
"""Número de bits fracionários do formato Q15.16."""

SCALE: int = 1 << FRAC_BITS
"""Fator de escala 2^16 = 65536."""

INT32_MAX: int = 0x7FFFFFFF
"""Maior inteiro com sinal de 32 bits (2147483647)."""

INT32_MIN: int = -0x80000000
"""Menor inteiro com sinal de 32 bits (-2147483648)."""

Q1516_MAX_FLOAT: float = INT32_MAX / SCALE
"""Maior valor representável em Q15.16 como float (≈ 32767.99998)."""

Q1516_MIN_FLOAT: float = INT32_MIN / SCALE
"""Menor valor representável em Q15.16 como float (-32768.0)."""

Q1516_RESOLUTION: float = 1.0 / SCALE
"""Menor incremento representável em Q15.16 (≈ 1.5259e-5)."""


# ─── Exceções ─────────────────────────────────────────────────────────────────

class Q1516OverflowError(OverflowError):
    """Exceção lançada quando um valor excede o range de Q15.16."""
    pass


# ─── Conversões escalares ─────────────────────────────────────────────────────

def int_to_q1516(val: int) -> int:
    """
    Converte inteiro com sinal para Q15.16.

    A conversão equivale a um shift left de 16 bits — o valor é exato, sem
    erro de quantização, pois inteiros cabem perfeitamente na parte inteira
    do formato.

    Parameters
    ----------
    val : int
        Inteiro com sinal no range [-32768, 32767].

    Returns
    -------
    int
        Valor codificado em Q15.16 como inteiro de 32 bits com sinal.

    Raises
    ------
    Q1516OverflowError
        Se `val` estiver fora do range representável.

    Examples
    --------
    >>> hex(int_to_q1516(1))
    '0x10000'
    >>> hex(int_to_q1516(-1) & 0xFFFFFFFF)
    '0xffff0000'
    """
    result = val << FRAC_BITS
    if result > INT32_MAX or result < INT32_MIN:
        raise Q1516OverflowError(
            f"Valor {val} fora do range Q15.16 [-32768, 32767]"
        )
    return result


def float_to_q1516(val: float, *, round_nearest: bool = False) -> int:
    """
    Converte float para Q15.16.

    Multiplica o valor pelo fator de escala 2^16 e converte para inteiro.
    Por padrão trunca (compatível com cast `(int32_t)` do C); passe
    `round_nearest=True` para arredondar ao mais próximo.

    Parameters
    ----------
    val : float
        Valor real no range [-32768.0, +32767.99998].
    round_nearest : bool, optional
        Se True, arredonda para o inteiro mais próximo. Se False (padrão),
        trunca em direção ao zero.

    Returns
    -------
    int
        Valor codificado em Q15.16 como inteiro de 32 bits com sinal.

    Raises
    ------
    Q1516OverflowError
        Se `val` estiver fora do range representável.

    Examples
    --------
    >>> hex(float_to_q1516(1.75))
    '0x1c000'
    >>> hex(float_to_q1516(0.5))
    '0x8000'
    """
    scaled = val * SCALE
    result = round(scaled) if round_nearest else int(scaled)
    if result > INT32_MAX or result < INT32_MIN:
        raise Q1516OverflowError(
            f"Valor {val} fora do range Q15.16 "
            f"[{Q1516_MIN_FLOAT}, {Q1516_MAX_FLOAT}]"
        )
    return result


def q1516_to_int(val: int) -> int:
    """
    Converte Q15.16 para inteiro com sinal, descartando a parte fracionária.

    Equivale a um shift right aritmético de 16 bits. O arredondamento é
    em direção a -∞ (floor), consistente com o operador `>>` do Python.

    Parameters
    ----------
    val : int
        Valor Q15.16 (inteiro de 32 bits com sinal).

    Returns
    -------
    int
        Parte inteira do valor, no range [-32768, 32767].

    Examples
    --------
    >>> q1516_to_int(0x1C000)   # 1.75 → 1
    1
    >>> q1516_to_int(-0x18000)  # -1.5 → -2 (floor)
    -2
    """
    return val >> FRAC_BITS


def q1516_to_float(val: int) -> float:
    """
    Converte Q15.16 para float.

    Divide o valor pelo fator de escala 2^16. A operação é exata em IEEE 754
    quando o valor cabe em 24 bits significativos (os 23 da mantissa do
    float32 mais o bit implícito) — caso contrário há perda dos bits menos
    significativos.

    Parameters
    ----------
    val : int
        Valor Q15.16 (inteiro de 32 bits com sinal).

    Returns
    -------
    float
        Valor real correspondente.

    Examples
    --------
    >>> q1516_to_float(0x1C000)
    1.75
    >>> q1516_to_float(0x8000)
    0.5
    """
    return val / SCALE


# ─── Conversões em batch (numpy) ──────────────────────────────────────────────

def int_array_to_q1516(arr: ArrayLike) -> NDArray[np.int32]:
    """
    Converte array de inteiros para Q15.16.

    Versão vetorizada de `int_to_q1516` para uso com arrays numpy.
    Útil no pipeline de processamento de amostras do ADC.

    Parameters
    ----------
    arr : array_like
        Array de inteiros no range [-32768, 32767].

    Returns
    -------
    ndarray of int32
        Array de valores Q15.16.

    Raises
    ------
    Q1516OverflowError
        Se algum elemento estiver fora do range.

    Examples
    --------
    >>> int_array_to_q1516([1, 2, -1]).tolist()
    [65536, 131072, -65536]
    """
    # Promove para int64 antes do shift para detectar overflow com segurança
    wide = np.asarray(arr, dtype=np.int64) << FRAC_BITS
    if np.any(wide > INT32_MAX) or np.any(wide < INT32_MIN):
        raise Q1516OverflowError("Um ou mais valores excedem o range Q15.16")
    return wide.astype(np.int32)


def float_array_to_q1516(
    arr: ArrayLike, *, round_nearest: bool = False
) -> NDArray[np.int32]:
    """
    Converte array de floats para Q15.16.

    Versão vetorizada de `float_to_q1516`.

    Parameters
    ----------
    arr : array_like
        Array de valores reais no range [-32768.0, +32767.99998].
    round_nearest : bool, optional
        Se True, arredonda ao mais próximo. Se False (padrão), trunca.

    Returns
    -------
    ndarray of int32
        Array de valores Q15.16.

    Raises
    ------
    Q1516OverflowError
        Se algum elemento estiver fora do range.

    Examples
    --------
    >>> float_array_to_q1516([1.0, 0.5, -1.0]).tolist()
    [65536, 32768, -65536]
    """
    scaled = np.asarray(arr, dtype=np.float64) * SCALE
    wide = np.round(scaled).astype(np.int64) if round_nearest \
                                             else scaled.astype(np.int64)
    if np.any(wide > INT32_MAX) or np.any(wide < INT32_MIN):
        raise Q1516OverflowError("Um ou mais valores excedem o range Q15.16")
    return wide.astype(np.int32)


def q1516_array_to_float(arr: ArrayLike) -> NDArray[np.float32]:
    """
    Converte array de Q15.16 para float.

    Versão vetorizada de `q1516_to_float`. Retorna `float32` para manter
    compacidade; use `.astype(np.float64)` se precisar de precisão dupla.

    Parameters
    ----------
    arr : array_like
        Array de valores Q15.16 (int32).

    Returns
    -------
    ndarray of float32
        Array de valores reais.

    Examples
    --------
    >>> q1516_array_to_float([65536, 32768, -65536]).tolist()
    [1.0, 0.5, -1.0]
    """
    return np.asarray(arr, dtype=np.int32).astype(np.float32) / SCALE


def q1516_array_to_int(arr: ArrayLike) -> NDArray[np.int32]:
    """
    Converte array de Q15.16 para inteiros, descartando a parte fracionária.

    Versão vetorizada de `q1516_to_int`. Usa shift right aritmético
    (floor em direção a -∞).

    Parameters
    ----------
    arr : array_like
        Array de valores Q15.16 (int32).

    Returns
    -------
    ndarray of int32
        Array de partes inteiras.

    Examples
    --------
    >>> q1516_array_to_int([0x1C000, -0x18000]).tolist()
    [1, -2]
    """
    return np.asarray(arr, dtype=np.int32) >> FRAC_BITS


# ─── Utilitários ──────────────────────────────────────────────────────────────

def q1516_to_hex(val: int) -> str:
    """
    Formata um valor Q15.16 como string hexadecimal de 32 bits.

    Lida corretamente com valores negativos (complemento de 2).

    Parameters
    ----------
    val : int
        Valor Q15.16.

    Returns
    -------
    str
        Representação hex no formato '0xXXXXXXXX' (8 dígitos, maiúsculas).

    Examples
    --------
    >>> q1516_to_hex(float_to_q1516(1.75))
    '0x0001C000'
    >>> q1516_to_hex(float_to_q1516(-1.0))
    '0xFFFF0000'
    """
    return f"0x{val & 0xFFFFFFFF:08X}"


def quantization_error(val: float) -> float:
    """
    Calcula o erro absoluto ao representar um float em Q15.16.

    Útil para avaliar se a resolução do formato é adequada para um
    determinado sinal.

    Parameters
    ----------
    val : float
        Valor real a avaliar.

    Returns
    -------
    float
        Erro absoluto |val - q1516_to_float(float_to_q1516(val))|.

    Examples
    --------
    >>> quantization_error(0.5)     # potência de 2 → exato
    0.0
    >>> quantization_error(0.1) < 2e-5
    True
    """
    return abs(val - q1516_to_float(float_to_q1516(val)))
