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

import math

import numpy as np

from morphe_config import CONV_N_MAX


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


# =========================================================================
# Projeto POR ESPECIFICACAO -- metodo do Prof. Armando S. Sanca
# =========================================================================
#
# Porte do dsp_fir_filter.m (DSPFinal). A diferenca em relacao as funcoes
# acima e de filosofia: la voce escolhe N e a janela; aqui voce declara o
# que o filtro precisa fazer e o algoritmo decide.
#
# Entradas:
#   fp  = borda da banda passante (Hz); par (f1, f2) para BP/BS
#   df  = largura da banda de transicao (Hz)
#   dp  = ripple maximo na banda passante (dB)
#   ds  = atenuacao minima na banda rejeitada (dB)
#   fs  = taxa de amostragem (Hz)
#
# Duas adaptacoes a realidade da FPGA, ausentes no MATLAB original:
#   1. N nunca passa de CONV_N_MAX. Quando a especificacao exige mais, a
#      funcao RECUSA e informa o df minimo viavel -- nao trunca calado.
#   2. achieved_specs() mede o que o filtro entrega DEPOIS da quantizacao
#      Q15.16, que e o piso real de atenuacao deste hardware.
#
# Aqui NAO ha normalizacao por sum(h): seguimos o professor, cujo h_D ja
# nasce com o ganho certo. As funcoes design_lowpass e cia., acima,
# normalizam -- e por isso continuam existindo, para o modo avancado.

#: Numero maximo de taps que o hardware aceita. CONV_N_MAX e o tamanho da
#: memoria; o filtro precisa de comprimento IMPAR, dai o ajuste.
MAX_TAPS: int = CONV_N_MAX - 1 if CONV_N_MAX % 2 == 0 else CONV_N_MAX

#: Tabela de decisao do dsp_fir_filter.m: para cada janela, o ripple de
#: banda passante e a atenuacao de stopband que ela consegue, e a constante
#: k da relacao N = k / df_normalizado.
#:
#: A escolha e a primeira linha cuja performance atende as duas exigencias,
#: da janela mais barata (menos taps) para a mais cara.
WINDOW_SPEC_TABLE: tuple = (
    # (janela,        ripple dB,  atenuacao dB,  k)
    ("rectangular",     0.7416,        21.0,    0.9),
    ("hanning",         0.0546,        44.0,    3.1),
    ("hamming",         0.0194,        53.0,    3.3),
    ("blackman",        0.0017,        74.0,    5.5),
)

#: A janela de Kaiser cobre o que a tabela fixa nao alcanca.
KAISER_MIN_RIPPLE_DB: float = 0.000275
KAISER_MAX_ATTEN_DB: float = 90.0

#: Nomes em portugues, para a interface.
WINDOW_LABEL_PT = {
    "rectangular": "Retangular",
    "hanning":     "Hanning",
    "hamming":     "Hamming",
    "blackman":    "Blackman",
    "kaiser":      "Kaiser",
}


class SpecError(ValueError):
    """Especificacao que nao pode ser atendida.

    Ou porque nenhuma janela alcanca os valores pedidos, ou porque o N
    resultante nao cabe no hardware. A mensagem sempre diz qual dos dois.
    """


def _bessel_i0(a: float) -> float:
    """Funcao de Bessel modificada de ordem zero, I0(a).

    Serie truncada em 30 termos, como no Bessel() do MATLAB original.
    """
    b = 1.0
    for k in range(1, 30):
        b += (((a / 2.0) ** k) / math.factorial(k)) ** 2
    return b


def kaiser_beta(atten_db: float) -> float:
    """Parametro beta da janela de Kaiser (determina_b do original)."""
    if 21.0 < atten_db < 50.0:
        return 0.5842 * (atten_db - 21.0) ** 0.4 + 0.07886 * (atten_db - 21.0)
    if atten_db >= 50.0:
        return 0.1102 * (atten_db - 8.7)
    return 0.0


def _half_window(kind: str, M: int, N: float,
                 beta: float = None) -> np.ndarray:
    """Metade direita da janela, para n = 1..M.

    O valor central w(0) = 1 fica implicito: todas as janelas da tabela
    valem exatamente 1 em n=0, e o professor multiplica so h_D(n) para
    n != 0. `N` e o comprimento vindo da formula, nao o numero de taps.
    """
    n = np.arange(1, M + 1, dtype=np.float64)
    if kind == "rectangular":
        return np.ones(M, dtype=np.float64)
    if kind == "hanning":
        return 0.5 + 0.5 * np.cos(2.0 * np.pi * n / N)
    if kind == "hamming":
        return 0.54 + 0.46 * np.cos(2.0 * np.pi * n / N)
    if kind == "blackman":
        return (0.42
                + 0.5 * np.cos(2.0 * np.pi * n / (N - 1.0))
                + 0.08 * np.cos(4.0 * np.pi * n / (N - 1.0)))
    if kind == "kaiser":
        if beta is None:
            raise ValueError("janela de Kaiser exige beta")
        denom = _bessel_i0(beta)
        arg = np.clip(1.0 - (2.0 * n / (N - 1.0)) ** 2, 0.0, None)
        return np.array([_bessel_i0(beta * math.sqrt(v)) / denom
                         for v in arg], dtype=np.float64)
    raise ValueError("janela desconhecida: %r" % (kind,))


def _taps_from_N(n_ceil: int):
    """Porte de longitud(): devolve (M, numero de taps).

    M e quantos coeficientes existem de cada lado do centro; o filtro tem
    2M+1 taps, sempre IMPAR. N par vira N+1 taps; N impar vira N taps.
    """
    M = n_ceil // 2
    return M, 2 * M + 1


def select_window(dp_db: float, ds_db: float, df_norm: float) -> dict:
    """Escolhe a janela e calcula N (passo 1 do metodo).

    df_norm e a largura de transicao normalizada (df / fs). Devolve a
    janela escolhida, beta (so Kaiser), o N da formula, o N usado na
    expressao da janela, M e o numero de taps.
    """
    if not (df_norm > 0.0):
        raise SpecError("A largura de transicao deve ser maior que zero.")
    if not (dp_db > 0.0 and ds_db > 0.0):
        raise SpecError("Ripple e atenuacao devem ser maiores que zero.")

    for kind, dp_min, ds_max, k in WINDOW_SPEC_TABLE:
        if dp_db >= dp_min and ds_db <= ds_max:
            n_ceil = int(math.ceil(k / df_norm))
            M, taps = _taps_from_N(n_ceil)
            return {
                "window": kind, "beta": None,
                "N_formula": n_ceil, "N_window": float(n_ceil),
                "M": M, "taps": taps,
                "k": k, "ripple_tabela": dp_min, "atten_tabela": ds_max,
            }

    if dp_db >= KAISER_MIN_RIPPLE_DB and ds_db <= KAISER_MAX_ATTEN_DB:
        dp_lin = 10.0 ** (dp_db / 20.0) - 1.0
        ds_lin = 10.0 ** (-ds_db / 20.0)
        d = min(dp_lin, ds_lin)
        atten = -20.0 * math.log10(d)
        n_exact = (atten - 7.95) / (14.36 * df_norm)
        n_ceil = int(math.ceil(n_exact))
        M, taps = _taps_from_N(n_ceil)
        return {
            "window": "kaiser", "beta": kaiser_beta(atten),
            "N_formula": n_ceil, "N_window": n_exact,
            "M": M, "taps": taps,
            "k": (atten - 7.95) / 14.36,
            "ripple_tabela": None, "atten_tabela": atten,
        }

    raise SpecError(
        "Nenhuma janela atende ripple %g dB com atenuacao %g dB. "
        "O limite do metodo e %g dB de atenuacao (janela de Kaiser)."
        % (dp_db, ds_db, KAISER_MAX_ATTEN_DB))


def min_transition_width(dp_db: float, ds_db: float, fs: float,
                         max_taps: int = MAX_TAPS) -> float:
    """Menor largura de transicao (Hz) que ainda cabe em max_taps.

    Serve para dizer ao usuario o que ele PODE pedir, em vez de so
    recusar. Depende da janela, que por sua vez depende de dp e ds.
    """
    sel = select_window(dp_db, ds_db, 0.01)   # df so para escolher a janela
    return sel["k"] / float(max_taps) * fs


def _normalize_fp(kind: str, fp):
    """Valida fp e devolve (f1, f2). f2 e None em LP/HP."""
    if kind in ("bandpass", "bandstop"):
        try:
            f1, f2 = float(fp[0]), float(fp[1])
        except (TypeError, IndexError, ValueError):
            raise SpecError(
                "Passa-banda e rejeita-banda exigem duas frequencias.")
        if f2 < f1:
            f1, f2 = f2, f1
        return f1, f2
    return float(fp), None


def design_from_spec(kind: str, fp, df: float, dp_db: float, ds_db: float,
                     fs: float):
    """Projeta um FIR a partir da especificacao. Porte do dsp_fir_filter.m.

    Devolve (h, relatorio). O relatorio traz a janela escolhida, o numero
    de taps, as frequencias de corte efetivas (centradas na transicao), a
    janela completa e o filtro ideal sem janela -- tudo o que a interface
    precisa para reproduzir as tres figuras do MATLAB.

    Levanta SpecError quando a especificacao nao cabe no hardware.
    """
    if kind not in FILTER_KINDS:
        raise SpecError("tipo de filtro desconhecido: %r" % (kind,))
    if not (fs > 0.0):
        raise SpecError("fs deve ser maior que zero.")
    if not (df > 0.0):
        raise SpecError("A largura de transicao df deve ser maior que zero.")

    f1, f2 = _normalize_fp(kind, fp)
    nyq = fs / 2.0
    if kind in ("bandpass", "bandstop"):
        if not (0.0 < f1 < f2 < nyq):
            raise SpecError(
                "E preciso 0 < f1 < f2 < fs/2 = %g Hz "
                "(recebido f1=%g, f2=%g)." % (nyq, f1, f2))
    else:
        if not (0.0 < f1 < nyq):
            raise SpecError(
                "fp=%g Hz deve estar entre 0 e fs/2 = %g Hz." % (f1, nyq))

    df_norm = df / fs
    sel = select_window(dp_db, ds_db, df_norm)

    if sel["taps"] > MAX_TAPS:
        df_min = min_transition_width(dp_db, ds_db, fs)
        raise SpecError(
            "Esta especificacao exige %d taps, e o hardware aceita no "
            "maximo %d.\n"
            "Com janela %s, a transicao minima viavel e df = %.4g Hz "
            "(voce pediu %g Hz).\n"
            "Alternativas: alargar df, reduzir a atenuacao exigida, "
            "ou aumentar fs."
            % (sel["taps"], MAX_TAPS, WINDOW_LABEL_PT[sel["window"]],
               df_min, df))

    M, Nw = sel["M"], sel["N_window"]
    w_half = _half_window(sel["window"], M, Nw, sel["beta"])
    n = np.arange(1, M + 1, dtype=np.float64)

    # Passo 2: resposta ideal h_D(n), com o corte centrado na transicao.
    if kind == "lowpass":
        c1 = f1 / fs + df_norm / 2.0
        c2 = None
        h0 = 2.0 * c1
        hd = 2.0 * c1 * np.sinc(2.0 * c1 * n)
    elif kind == "highpass":
        c1 = f1 / fs - df_norm / 2.0
        c2 = None
        h0 = 1.0 - 2.0 * c1
        hd = -2.0 * c1 * np.sinc(2.0 * c1 * n)
    elif kind == "bandpass":
        c1 = f1 / fs - df_norm / 2.0
        c2 = f2 / fs + df_norm / 2.0
        h0 = 2.0 * (c2 - c1)
        hd = (2.0 * c2 * np.sinc(2.0 * c2 * n)
              - 2.0 * c1 * np.sinc(2.0 * c1 * n))
    else:  # bandstop
        c1 = f1 / fs + df_norm / 2.0
        c2 = f2 / fs - df_norm / 2.0
        h0 = 1.0 - 2.0 * (c2 - c1)
        hd = (2.0 * c1 * np.sinc(2.0 * c1 * n)
              - 2.0 * c2 * np.sinc(2.0 * c2 * n))

    h_half = hd * w_half
    h = np.concatenate([h_half[::-1], [h0], h_half])
    h_ideal = np.concatenate([hd[::-1], [h0], hd])
    w_full = np.concatenate([w_half[::-1], [1.0], w_half])

    report = {
        "kind": kind,
        "window": sel["window"],
        "window_pt": WINDOW_LABEL_PT[sel["window"]],
        "beta": sel["beta"],
        "taps": len(h),
        "N_formula": sel["N_formula"],
        "fp1": f1, "fp2": f2,
        "df": df, "dp_db": dp_db, "ds_db": ds_db, "fs": fs,
        "fc1_efetiva": c1 * fs,
        "fc2_efetiva": None if c2 is None else c2 * fs,
        "atten_tabela": sel["atten_tabela"],
        "ripple_tabela": sel["ripple_tabela"],
        "h_ideal": h_ideal,
        "window_full": w_full,
    }
    return h, report


def _bands(kind: str, f1: float, f2, df: float, f: np.ndarray):
    """Mascaras booleanas das bandas passante e rejeitada, para medicao."""
    if kind == "lowpass":
        return f <= f1, f >= (f1 + df)
    if kind == "highpass":
        return f >= f1, f <= (f1 - df)
    if kind == "bandpass":
        return ((f >= f1) & (f <= f2),
                (f <= (f1 - df)) | (f >= (f2 + df)))
    # bandstop: f1 e f2 sao as bordas das DUAS bandas passantes, e a
    # transicao fica para dentro -- [f1, f1+df] e [f2-df, f2].
    return ((f <= f1) | (f >= f2),
            (f >= (f1 + df)) & (f <= (f2 - df)))


def achieved_specs(h: np.ndarray, report: dict, n_freq: int = 4096,
                   quantize: bool = True) -> dict:
    """Mede o que o filtro REALMENTE entrega.

    Com quantize=True (padrao) os coeficientes passam antes por Q15.16,
    que e o formato em que eles chegam a FPGA. E essa medida, e nao a
    tabela de janelas, que diz a atenuacao possivel neste hardware: com
    16 bits fracionarios existe um piso que nenhuma janela vence.

    Devolve ripple da banda passante e atenuacao da rejeitada, em dB,
    mais os coeficientes quantizados e a resposta em frequencia deles.
    """
    hq = h
    if quantize:
        import dsp_core as _dsp
        hq = _dsp.q1516_to_float(_dsp.float_to_q1516(h))

    fs = report["fs"]
    f, H = frequency_response(hq, fs=fs, n_freq=n_freq)
    db = 20.0 * np.log10(np.abs(H) + 1e-18)

    pass_mask, stop_mask = _bands(report["kind"], report["fp1"],
                                  report["fp2"], report["df"], f)
    ripple = (float(np.max(np.abs(db[pass_mask])))
              if pass_mask.any() else float("nan"))
    atten = (float(-np.max(db[stop_mask]))
             if stop_mask.any() else float("nan"))
    return {"ripple_db": ripple, "atten_db": atten,
            "h_quant": hq, "f": f, "db": db}


def describe_from_spec(report: dict) -> str:
    """Descricao de uma linha, no formato do cabecalho '#' dos .txt."""
    pt = {"lowpass": "passa-baixa", "highpass": "passa-alta",
          "bandpass": "passa-banda",
          "bandstop": "rejeita-banda"}[report["kind"]]
    if report["fp2"] is not None:
        freqs = "fp1=%gHz fp2=%gHz" % (report["fp1"], report["fp2"])
    else:
        freqs = "fp=%gHz" % (report["fp1"],)
    return ("%s %s df=%gHz dp=%gdB ds=%gdB @ Fs=%gHz, N=%d, %s"
            % (pt, freqs, report["df"], report["dp_db"], report["ds_db"],
               report["fs"], report["taps"], report["window_pt"]))
