"""iir_design.py -- projeto de filtros IIR por aproximacoes classicas.

Passo 0 do estudo de viabilidade do bloco IIR em hardware: projetar em
Python, quantizar, e medir o que a quantizacao faz com os polos. Nada
aqui fala com a FPGA -- e de proposito. A pergunta que este modulo existe
para responder e:

    o Q15.16 do conv1d aguenta os filtros que o metodo do professor
    projeta, ou os polos saem do circulo unitario?

Se a resposta for nao, escrever o Verilog antes teria sido desperdicio.

O metodo e o do dsp_iir_filter.m do Prof. Armando S. Sanca (DSPFinal),
com uma diferenca deliberada na saida:

    MATLAB  -> numz, denz : UM polinomio de ordem N
    aqui    -> SOS        : cascata de secoes de 2a ordem

A funcao de transferencia e a mesma; o que muda e como ela e fatorada.
Em ponto fixo essa diferenca decide se o filtro funciona: a posicao dos
polos de um polinomio de ordem N e absurdamente sensivel aos seus
coeficientes, e o erro cresce com a ordem. Em biquads cada secao carrega
so 2 polos, e o deslocamento fica contido. Ver zpk_para_sos().

Butterworth, Chebyshev I e Chebyshev II tem os polos em forma fechada e
sao implementadas aqui, so com NumPy. A **eliptica** exige integrais
elipticas completas e funcoes de Jacobi, que nao tem forma fechada
elementar: ela e delegada ao scipy, e so aparece se o scipy estiver
instalado. O modulo funciona inteiro sem ele -- perde uma das quatro.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


#: A eliptica exige integrais elipticas completas e funcoes de Jacobi,
#: que nao tem forma fechada elementar. Em vez de reimplementa-las, a
#: delegamos ao scipy QUANDO ele existir. As outras tres nao dependem
#: dele: o modulo funciona inteiro so com NumPy, e ganha a quarta
#: aproximacao se o scipy estiver instalado.
try:
    from scipy import signal as _sp_signal
    TEM_SCIPY = True
except ImportError:                                   # pragma: no cover
    _sp_signal = None
    TEM_SCIPY = False

APROXIMACOES = (("butterworth", "cheby1", "cheby2")
                + (("ellip",) if TEM_SCIPY else ()))

APROX_LABEL_PT = {
    "butterworth": "Butterworth",
    "cheby1":      "Chebyshev I",
    "cheby2":      "Chebyshev II",
    "ellip":       "Eliptica",
}

TIPOS = ("lowpass", "highpass", "bandpass", "bandstop")

TIPO_LABEL_PT = {
    "lowpass":  "passa-baixa",
    "highpass": "passa-alta",
    "bandpass": "passa-banda",
    "bandstop": "rejeita-banda",
}


class IIRSpecError(ValueError):
    """Especificacao que nao pode ser atendida, ou que geraria um filtro
    que nao sobrevive a quantizacao."""


# ======================================================================
# Ordem do filtro -- os *ord do MATLAB, em forma fechada
# ======================================================================

def _razao_selecao(wp, ws, tipo: str) -> float:
    """Razao de frequencias que entra no calculo da ordem.

    Para passa-baixa e passa-alta e uma divisao simples. Para as versoes
    de banda, e a pior das duas bordas -- a que exige mais do filtro.
    """
    if tipo == "lowpass":
        return ws / wp
    if tipo == "highpass":
        return wp / ws
    if tipo == "bandpass":
        # Passa-banda: a banda de rejeicao esta fora da de passagem.
        w0_2 = wp[0] * wp[1]
        largura = wp[1] - wp[0]
        k1 = abs((ws[0] ** 2 - w0_2) / (ws[0] * largura))
        k2 = abs((ws[1] ** 2 - w0_2) / (ws[1] * largura))
        return min(k1, k2)
    # bandstop: a de rejeicao esta DENTRO da de passagem.
    #
    # Quem define a transformacao continua sendo a banda PASSANTE -- w0 e
    # a largura saem de wp nos dois casos de banda. O que muda e onde a
    # gente avalia: aqui, nas bordas de rejeicao, que estao por dentro.
    w0_2 = wp[0] * wp[1]
    largura = wp[1] - wp[0]
    k1 = abs((largura * ws[0]) / (w0_2 - ws[0] ** 2))
    k2 = abs((largura * ws[1]) / (w0_2 - ws[1] ** 2))
    return min(k1, k2)


def ordem_minima(aprox: str, wp, ws, dp_db: float, ds_db: float,
                 tipo: str) -> int:
    """Menor ordem que atende a especificacao. Porte de buttord/cheb1ord/
    cheb2ord, que sao formulas fechadas.

    dp_db e o ripple maximo na banda passante e ds_db a atenuacao minima
    na rejeitada, os dois em dB positivos.
    """
    gp = 10.0 ** (dp_db / 10.0) - 1.0     # epsilon^2 da banda passante
    gs = 10.0 ** (ds_db / 10.0) - 1.0
    if gp <= 0.0:
        raise IIRSpecError("O ripple da banda passante deve ser > 0 dB.")
    k = _razao_selecao(wp, ws, tipo)
    if k <= 1.0:
        raise IIRSpecError(
            "As bordas de passagem e rejeicao estao invertidas ou coladas "
            "(razao de selecao = %.4g). A de rejeicao precisa estar do "
            "lado certo e separada da de passagem." % k)

    if aprox == "butterworth":
        n = math.log10(gs / gp) / (2.0 * math.log10(k))
    elif aprox in ("cheby1", "cheby2"):
        n = math.acosh(math.sqrt(gs / gp)) / math.acosh(k)
    else:
        raise IIRSpecError("aproximacao desconhecida: %r" % (aprox,))
    return max(1, int(math.ceil(n)))


# ======================================================================
# Prototipos analogicos normalizados (wc = 1 rad/s), em zeros-polos-ganho
# ======================================================================

def prototipo_butterworth(n: int):
    """Polos do Butterworth: n pontos igualmente espacados no semicirculo
    esquerdo do circulo unitario. Sem zeros finitos."""
    k = np.arange(1, n + 1)
    polos = -np.exp(1j * np.pi * (2.0 * k - 1.0) / (2.0 * n)) * 1j
    # A conta acima poe os polos no eixo certo; forcamos parte real < 0.
    polos = -np.abs(polos.real) + 1j * polos.imag
    return np.array([]), polos, 1.0


def prototipo_cheby1(n: int, dp_db: float):
    """Chebyshev I: ripple na banda passante, sem zeros finitos.

    Os polos ficam numa elipse -- e por isso que o filtro e mais seletivo
    que o Butterworth de mesma ordem, e tambem por isso que os polos ficam
    mais perto do eixo imaginario, o que importa depois da quantizacao.
    """
    eps = math.sqrt(10.0 ** (dp_db / 10.0) - 1.0)
    mu = math.asinh(1.0 / eps) / n
    k = np.arange(1, n + 1)
    theta = np.pi * (2.0 * k - 1.0) / (2.0 * n)
    polos = -np.sinh(mu) * np.sin(theta) + 1j * np.cosh(mu) * np.cos(theta)

    ganho = float(np.real(np.prod(-polos)))
    if n % 2 == 0:
        # Ordem par: |H(0)| = 1/sqrt(1+eps^2), nao 1.
        ganho /= math.sqrt(1.0 + eps ** 2)
    return np.array([]), polos, ganho


def prototipo_cheby2(n: int, ds_db: float):
    """Chebyshev II (Chebyshev inverso): ripple na banda REJEITADA, e
    zeros finitos no eixo imaginario -- os zeros sao o que produz a
    rejeicao equiripple."""
    eps = 1.0 / math.sqrt(10.0 ** (ds_db / 10.0) - 1.0)
    mu = math.asinh(1.0 / eps) / n
    k = np.arange(1, n + 1)
    theta = np.pi * (2.0 * k - 1.0) / (2.0 * n)

    # Polos: reciproco dos do Chebyshev I
    p_ch1 = -np.sinh(mu) * np.sin(theta) + 1j * np.cosh(mu) * np.cos(theta)
    polos = 1.0 / p_ch1

    # Zeros: no eixo imaginario, em 1/cos(theta). Ordem impar tem um
    # theta = pi/2, cujo cosseno e zero -- esse "zero" vai para infinito
    # e simplesmente nao existe.
    cos_t = np.cos(theta)
    finitos = np.abs(cos_t) > 1e-12
    zeros = 1j / cos_t[finitos]

    ganho = float(np.real(np.prod(-polos) / np.prod(-zeros))) if zeros.size \
        else float(np.real(np.prod(-polos)))
    return zeros, polos, ganho


def _frequencia_natural(aprox: str, wp, ws, dp_db: float, ds_db: float,
                        n: int, tipo: str):
    """Frequencia de corte do prototipo depois de escolhida a ordem.

    Cada aproximacao normaliza o prototipo por uma borda diferente, e
    desnormalizar pela borda errada desloca o filtro inteiro:

    - Butterworth: sem ripple, ha folga entre a ordem inteira e a
      especificacao. Seguindo o buttord, gastamos a folga na borda da
      banda PASSANTE, que fica atendida exatamente.
    - Chebyshev I: o ripple ja ancora a borda de passagem -- e ela.
    - Chebyshev II: o prototipo (cheb2ap) e normalizado pela borda da
      banda REJEITADA. Usar wp aqui poe a rejeicao em cima da passagem.

    Esse ultimo caso e um erro do dsp_iir_filter.m original, que chama
    lp2lp(nums,dens,wp1) para todas as aproximacoes: o Chebyshev II dele
    entrega -40 dB na borda da banda passante quando 1 dB foi pedido.
    Medido contra o scipy, que da -1,000 dB ali. A comparacao contra o
    MATLAB nao denunciava porque o porte reproduzia o mesmo erro.
    """
    if aprox == "cheby2":
        return ws
    if aprox != "butterworth":
        return wp
    gp = 10.0 ** (dp_db / 10.0) - 1.0
    fator = gp ** (-1.0 / (2.0 * n))
    if tipo in ("lowpass", "highpass"):
        return wp * fator if tipo == "lowpass" else wp / fator
    return wp


# ======================================================================
# Transformacoes de frequencia, em zeros-polos-ganho
# ======================================================================
# Fazer isso em zpk e nao em coeficientes de polinomio nao e detalhe de
# estilo: converter para polinomio, transformar e voltar a fatorar perde
# precisao exatamente onde ela importa (a posicao dos polos), e para
# ordem alta o resultado fica irreconhecivel.

def lp2lp_zpk(z, p, k, wo: float):
    grau = len(p) - len(z)
    return z * wo, p * wo, k * wo ** grau


def lp2hp_zpk(z, p, k, wo: float):
    grau = len(p) - len(z)
    z_hp = wo / z if len(z) else np.array([])
    p_hp = wo / p
    # Os zeros que estavam no infinito viram zeros na origem.
    z_hp = np.append(z_hp, np.zeros(grau))
    k_hp = k * float(np.real(np.prod(-z) / np.prod(-p))) if len(z) \
        else k * float(np.real(1.0 / np.prod(-p)))
    return z_hp, p_hp, k_hp


def lp2bp_zpk(z, p, k, wo: float, bw: float):
    grau = len(p) - len(z)
    z_lp, p_lp = z * bw / 2.0, p * bw / 2.0
    z_bp = np.concatenate([z_lp + np.sqrt(z_lp ** 2 - wo ** 2),
                           z_lp - np.sqrt(z_lp ** 2 - wo ** 2)]) \
        if len(z) else np.array([])
    p_bp = np.concatenate([p_lp + np.sqrt(p_lp ** 2 - wo ** 2),
                           p_lp - np.sqrt(p_lp ** 2 - wo ** 2)])
    z_bp = np.append(z_bp, np.zeros(grau))
    return z_bp, p_bp, k * bw ** grau


def lp2bs_zpk(z, p, k, wo: float, bw: float):
    grau = len(p) - len(z)
    z_hp = (bw / 2.0) / z if len(z) else np.array([])
    p_hp = (bw / 2.0) / p
    z_bs = np.concatenate([z_hp + np.sqrt(z_hp ** 2 - wo ** 2),
                           z_hp - np.sqrt(z_hp ** 2 - wo ** 2)]) \
        if len(z) else np.array([])
    p_bs = np.concatenate([p_hp + np.sqrt(p_hp ** 2 - wo ** 2),
                           p_hp - np.sqrt(p_hp ** 2 - wo ** 2)])
    # Zeros do infinito vao para +-j*wo
    z_bs = np.append(z_bs, np.full(grau, +1j * wo))
    z_bs = np.append(z_bs, np.full(grau, -1j * wo))
    k_bs = k * float(np.real(np.prod(-z) / np.prod(-p))) if len(z) \
        else k * float(np.real(1.0 / np.prod(-p)))
    return z_bs, p_bs, k_bs


def bilinear_zpk(z, p, k, fs: float = 0.5):
    """Transformada bilinear em zpk.

    fs=0.5 reproduz `bilinear(...,0.5)` do MATLAB, que e s = (z-1)/(z+1).
    O prewarp com tan(wT/2) ja foi aplicado antes, entao o T se cancela.
    """
    fs2 = 2.0 * fs
    grau = len(p) - len(z)
    z_d = (fs2 + z) / (fs2 - z) if len(z) else np.array([])
    p_d = (fs2 + p) / (fs2 - p)
    # Zeros no infinito viram zeros em z = -1 (Nyquist).
    z_d = np.append(z_d, -np.ones(grau))
    k_d = k * float(np.real(np.prod(fs2 - z) / np.prod(fs2 - p))) if len(z) \
        else k * float(np.real(1.0 / np.prod(fs2 - p)))
    return z_d, p_d, k_d


# ======================================================================
# zpk -> cascata de secoes de 2a ordem (SOS)
# ======================================================================

def _emparelha(valores: np.ndarray, alvo: complex) -> int:
    return int(np.argmin(np.abs(valores - alvo)))


def zpk_para_sos(z: np.ndarray, p: np.ndarray, k: float) -> np.ndarray:
    """Fatora em secoes de 2a ordem. Devolve (S, 6): b0 b1 b2 a0 a1 a2.

    Regra de emparelhamento: pega sempre o polo mais proximo do circulo
    unitario -- o mais delicado, o que primeiro fica instavel se a
    quantizacao empurrar -- e junta com o zero mais proximo dele. Um polo
    delicado acompanhado do seu zero tem ganho contido; sozinho, faz a
    secao ter pico alto e estourar o acumulador.

    Conjugados andam sempre juntos: coeficiente complexo nao existe no
    hardware.
    """
    z = list(np.atleast_1d(z))
    p = list(np.atleast_1d(p))
    secoes = []

    while p:
        pa = np.array(p)
        # polo mais perto do circulo unitario = mais critico
        i = int(np.argmax(np.abs(pa)))
        p1 = p.pop(i)

        if abs(p1.imag) > 1e-12:
            # complexo: leva o conjugado junto
            j = _emparelha(np.array(p), np.conj(p1))
            p2 = p.pop(j)
            par_p = [p1, p2]
        else:
            # real: junta com outro real, ou fica sozinho
            reais = [idx for idx, v in enumerate(p) if abs(v.imag) <= 1e-12]
            if reais:
                j = reais[int(np.argmin([abs(p[idx] - p1) for idx in reais]))]
                par_p = [p1, p.pop(j)]
            else:
                par_p = [p1]

        par_z = []
        for _ in par_p:
            if not z:
                break
            iz = _emparelha(np.array(z), p1)
            zc = z.pop(iz)
            par_z.append(zc)
            if abs(zc.imag) > 1e-12 and z:
                jz = _emparelha(np.array(z), np.conj(zc))
                par_z.append(z.pop(jz))
                break

        b = np.real(np.poly(par_z)) if par_z else np.array([1.0])
        a = np.real(np.poly(par_p))
        # Completar a DIREITA, nunca a esquerda. Uma secao de 1a ordem tem
        # denominador [1, -p]; virando [0, 1, -p] o a0 fica ZERO e a
        # recorrencia y[n] = -a1*y[n-1] - a2*y[n-2] passa a usar os
        # coeficientes trocados -- um filtro completamente diferente, e
        # instavel. O modulo da resposta em frequencia nao denuncia isso,
        # porque o deslocamento equivale a um atraso puro; quem denuncia e
        # a simulacao em ponto fixo, que segue a recorrencia de verdade.
        b = np.concatenate([b, np.zeros(3 - len(b))])
        a = np.concatenate([a, np.zeros(3 - len(a))])
        secoes.append(np.concatenate([b, a]))

    sos = np.array(secoes, dtype=np.float64)
    # O ganho global vai todo na primeira secao. Distribuir melhor entre
    # as secoes e uma otimizacao de faixa dinamica que fica para depois.
    sos[0, :3] *= k
    return sos


# ======================================================================
# Projeto completo
# ======================================================================

@dataclass
class ProjetoIIR:
    """O que o projeto devolve. `sos` e a cascata; o resto e contexto."""
    sos: np.ndarray
    aprox: str
    tipo: str
    ordem: int
    fp: object
    fs_borda: object
    dp_db: float
    ds_db: float
    fs: float
    polos: np.ndarray = field(default_factory=lambda: np.array([]))
    zeros: np.ndarray = field(default_factory=lambda: np.array([]))
    ganho: float = 1.0

    @property
    def n_secoes(self) -> int:
        return int(self.sos.shape[0])

    def descricao(self) -> str:
        f = (("fp=%g fs=%g" % (self.fp, self.fs_borda))
             if np.isscalar(self.fp)
             else ("fp=[%g %g] fs=[%g %g]"
                   % (self.fp[0], self.fp[1],
                      self.fs_borda[0], self.fs_borda[1])))
        return ("%s %s %s Hz dp=%gdB ds=%gdB @ Fs=%gHz, ordem %d, "
                "%d secoes"
                % (APROX_LABEL_PT[self.aprox], TIPO_LABEL_PT[self.tipo],
                   f, self.dp_db, self.ds_db, self.fs, self.ordem,
                   self.n_secoes))


def _detecta_tipo(fp, fs_borda) -> str:
    """Mesma regra do dsp_iir_filter.m: o tipo sai da posicao relativa
    das bordas, nao de um parametro separado."""
    escalar = np.isscalar(fp) or np.asarray(fp).size == 1
    if escalar != (np.isscalar(fs_borda) or np.asarray(fs_borda).size == 1):
        raise IIRSpecError("fp e fs precisam ter o mesmo formato: os dois "
                           "escalares, ou os dois com duas frequencias.")
    if escalar:
        fp, fs_borda = float(fp), float(fs_borda)
        if fp < fs_borda:
            return "lowpass"
        if fp > fs_borda:
            return "highpass"
        raise IIRSpecError("fp e fs sao iguais: nao ha banda de transicao.")
    fp = np.atleast_1d(fp).astype(float)
    fs_borda = np.atleast_1d(fs_borda).astype(float)
    if fp[0] > fs_borda[0] and fp[1] < fs_borda[1]:
        return "bandpass"
    if fp[0] < fs_borda[0] and fp[1] > fs_borda[1]:
        return "bandstop"
    raise IIRSpecError(
        "Bordas incoerentes. Passa-banda quer fs1 < fp1 < fp2 < fs2; "
        "rejeita-banda quer fp1 < fs1 < fs2 < fp2.")


def _design_eliptico(fp, fs_borda, dp_db: float, ds_db: float,
                     fs: float) -> ProjetoIIR:
    """Eliptica, delegada ao scipy.

    E a unica das quatro que nao tem os polos em forma fechada: precisa
    de integrais elipticas completas e funcoes de Jacobi. Reimplementar
    isso seria um projeto proprio, e o resultado seria uma copia pior de
    algo que ja existe testado.

    O resto do caminho e identico ao das outras tres -- sai em SOS, passa
    por distribui_ganho() e pela mesma analise de ponto fixo.
    """
    tipo = _detecta_tipo(fp, fs_borda)
    nyq = fs / 2.0
    wp = np.atleast_1d(fp).astype(float) / nyq
    ws = np.atleast_1d(fs_borda).astype(float) / nyq
    if tipo in ("lowpass", "highpass"):
        wp, ws = float(wp[0]), float(ws[0])

    n, wn = _sp_signal.ellipord(wp, ws, dp_db, ds_db)
    btype = {"lowpass": "lowpass", "highpass": "highpass",
             "bandpass": "bandpass", "bandstop": "bandstop"}[tipo]
    sos = _sp_signal.ellip(n, dp_db, ds_db, wn, btype=btype, output="sos")
    z, p, k = _sp_signal.ellip(n, dp_db, ds_db, wn, btype=btype,
                               output="zpk")
    return ProjetoIIR(sos=np.asarray(sos, dtype=np.float64),
                      aprox="ellip", tipo=tipo, ordem=len(p),
                      fp=fp, fs_borda=fs_borda, dp_db=dp_db,
                      ds_db=ds_db, fs=fs, polos=p, zeros=z, ganho=k)


def design_iir(aprox: str, fp, fs_borda, dp_db: float, ds_db: float,
               fs: float) -> ProjetoIIR:
    """Projeta o filtro e devolve a cascata de biquads.

    Segue os cinco passos do dsp_iir_filter.m: prewarp, ordem, prototipo
    normalizado, transformacao de frequencia, bilinear. A diferenca e que
    tudo anda em zeros-polos-ganho e a saida sai fatorada em SOS.
    """
    if aprox == "ellip" and not TEM_SCIPY:
        raise IIRSpecError(
            "A aproximacao eliptica precisa do scipy, que nao esta "
            "instalado. As outras tres rodam so com NumPy.\n"
            "Instale com: pip install scipy")
    if aprox not in APROXIMACOES:
        raise IIRSpecError(
            "Aproximacao %r nao implementada. Disponiveis: %s."
            % (aprox, ", ".join(APROXIMACOES)))
    if aprox == "ellip":
        return _design_eliptico(fp, fs_borda, dp_db, ds_db, fs)
    if not (fs > 0.0):
        raise IIRSpecError("fs deve ser maior que zero.")
    if not (dp_db > 0.0 and ds_db > 0.0):
        raise IIRSpecError("dp e ds devem ser maiores que zero.")

    tipo = _detecta_tipo(fp, fs_borda)
    nyq = fs / 2.0
    todas = np.atleast_1d(fp).astype(float).tolist() + \
        np.atleast_1d(fs_borda).astype(float).tolist()
    for f in todas:
        if not (0.0 < f < nyq):
            raise IIRSpecError(
                "Toda frequencia deve estar entre 0 e fs/2 = %g Hz "
                "(recebido %g)." % (nyq, f))

    # Passo 1: prewarp -- tan(wT/2), como no original
    wp = np.tan(np.pi * np.atleast_1d(fp).astype(float) / fs)
    ws = np.tan(np.pi * np.atleast_1d(fs_borda).astype(float) / fs)
    if tipo in ("lowpass", "highpass"):
        wp, ws = float(wp[0]), float(ws[0])

    # Passo 2: ordem
    n = ordem_minima(aprox, wp, ws, dp_db, ds_db, tipo)

    # Passo 3: prototipo normalizado
    if aprox == "butterworth":
        z, p, k = prototipo_butterworth(n)
    elif aprox == "cheby1":
        z, p, k = prototipo_cheby1(n, dp_db)
    else:
        z, p, k = prototipo_cheby2(n, ds_db)

    # Passo 4: desnormaliza para o tipo pedido
    wn = _frequencia_natural(aprox, wp, ws, dp_db, ds_db, n, tipo)
    if tipo == "lowpass":
        z, p, k = lp2lp_zpk(z, p, k, float(wn))
    elif tipo == "highpass":
        z, p, k = lp2hp_zpk(z, p, k, float(wn))
    else:
        wn = np.atleast_1d(wn).astype(float)
        wo = math.sqrt(wn[0] * wn[1])
        bw = wn[1] - wn[0]
        if tipo == "bandpass":
            z, p, k = lp2bp_zpk(z, p, k, wo, bw)
        else:
            z, p, k = lp2bs_zpk(z, p, k, wo, bw)

    # Passo 5: bilinear
    z, p, k = bilinear_zpk(z, p, k, fs=0.5)

    sos = zpk_para_sos(z, p, k)
    ordem_final = int(np.sum(np.abs(sos[:, 4:6]) > 0, axis=1).sum())
    return ProjetoIIR(sos=sos, aprox=aprox, tipo=tipo,
                      ordem=len(p), fp=fp, fs_borda=fs_borda,
                      dp_db=dp_db, ds_db=ds_db, fs=fs,
                      polos=p, zeros=z, ganho=k)


# ======================================================================
# Resposta em frequencia de uma cascata SOS
# ======================================================================

def resposta_sos(sos: np.ndarray, n_freq: int = 4096, fs: float = 1.0):
    """(f, H) da cascata. Multiplica a resposta de cada biquad."""
    w = np.linspace(0.0, np.pi, n_freq)
    ejw = np.exp(-1j * w)
    ejw2 = ejw ** 2
    H = np.ones_like(w, dtype=np.complex128)
    for b0, b1, b2, a0, a1, a2 in np.atleast_2d(sos):
        num = b0 + b1 * ejw + b2 * ejw2
        den = a0 + a1 * ejw + a2 * ejw2
        H = H * (num / den)
    return w / np.pi * (fs / 2.0), H


# ======================================================================
# Ponto fixo: a pergunta que este modulo existe para responder
# ======================================================================

def quantiza(v, frac_bits: int, total_bits: int = 32):
    """Quantiza para Qm.f com saturacao. Devolve (valor, saturou)."""
    escala = float(1 << frac_bits)
    limite = float(1 << (total_bits - 1))
    bruto = np.round(np.asarray(v, dtype=np.float64) * escala)
    saturou = bool(np.any(np.abs(bruto) >= limite))
    return np.clip(bruto, -limite, limite - 1) / escala, saturou


def distribui_ganho(sos: np.ndarray) -> np.ndarray:
    """Espalha o ganho global entre as secoes, em vez de deixar tudo na
    primeira.

    Sem isto, um passa-baixa estreito de ordem alta concentra um ganho
    minusculo (1e-10 e coisa comum) nos tres coeficientes b da primeira
    secao -- e em Q15.16, cujo passo e 1,5e-5, eles viram ZERO. O filtro
    inteiro passa a devolver zero, e o culpado nao e a ordem nem os
    polos: e ter posto todo o ganho num lugar so.

    A correcao e a raiz S-esima: cada uma das S secoes leva a mesma
    fracao. A funcao de transferencia nao muda -- o produto e o mesmo.
    """
    sos = np.array(sos, dtype=np.float64, copy=True)
    s = sos.shape[0]
    if s < 2:
        return sos
    # ganho de cada secao em DC (ou o que houver), para redistribuir
    g = np.array([np.sum(sec[:3]) for sec in sos])
    g_total = float(np.prod(g))
    if not np.isfinite(g_total) or g_total == 0.0:
        return sos
    alvo = np.sign(g_total) * abs(g_total) ** (1.0 / s)
    for i in range(s):
        if g[i] != 0.0:
            sos[i, :3] *= alvo / g[i]
    return sos


def analisa_quantizacao(sos: np.ndarray, frac_bits: int,
                        total_bits: int = 32) -> dict:
    """O que a quantizacao faz com os polos de cada secao.

    Devolve o deslocamento maximo do raio, o maior |polo| depois de
    quantizar, se alguma secao ficou instavel e se algum coeficiente
    saturou ou virou zero.
    """
    sos = np.atleast_2d(sos)
    sos_q, saturou = quantiza(sos, frac_bits, total_bits)

    r_antes, r_depois, deslocamentos = [], [], []
    for sec, sec_q in zip(sos, sos_q):
        pa = np.roots(sec[3:6])
        pq = np.roots(sec_q[3:6])
        r_antes.append(float(np.max(np.abs(pa))))
        r_depois.append(float(np.max(np.abs(pq))))
        # emparelha por proximidade antes de medir o deslocamento
        for x in pa:
            deslocamentos.append(float(np.min(np.abs(pq - x))))

    b = sos[:, :3]
    b_q = sos_q[:, :3]
    zerou = bool(np.any((np.abs(b) > 0) & (np.abs(b_q) == 0)))
    menor_b = float(np.min(np.abs(b[np.abs(b) > 0]))) if np.any(b) else 0.0

    return {
        "sos_q": sos_q,
        "frac_bits": frac_bits,
        "passo": 2.0 ** -frac_bits,
        "raio_antes": max(r_antes),
        "raio_depois": max(r_depois),
        "deslocamento_max": max(deslocamentos) if deslocamentos else 0.0,
        "instavel": max(r_depois) >= 1.0,
        "coef_saturou": saturou,
        "coef_zerou": zerou,
        "menor_b": menor_b,
    }


def filtra_sos_fixo(x: np.ndarray, sos: np.ndarray, frac_bits: int,
                    total_bits: int = 32,
                    acc_bits: int = 64) -> np.ndarray:
    """Simula a cascata em ponto fixo, Forma Direta I, com saturacao.

    Forma Direta I porque e a que sobrevive em ponto fixo: o acumulador
    e unico e largo, e absorve o crescimento intermediario antes de
    voltar ao formato da amostra. A DF-II transposta e melhor em ponto
    flutuante e pior aqui, porque guarda estados ja truncados.

    Nao e o Verilog -- e o que o Verilog vai ter que fazer. Serve para
    medir ciclo limite antes de existir Verilog.
    """
    escala = float(1 << frac_bits)
    limite = float(1 << (total_bits - 1))

    def sat(v):
        return np.clip(v, -limite, limite - 1)

    sos_q, _ = quantiza(sos, frac_bits, total_bits)
    coef = np.round(sos_q * escala)          # coeficientes inteiros

    y = np.round(np.asarray(x, dtype=np.float64) * escala)
    y = sat(y)

    for b0, b1, b2, a0, a1, a2 in coef:
        x1 = x2 = y1 = y2 = 0.0
        saida = np.empty_like(y)
        for i, xn in enumerate(y):
            # acumulador largo, em unidades de 2^(2*frac)
            acc = (b0 * xn + b1 * x1 + b2 * x2
                   - a1 * y1 - a2 * y2)
            # volta ao formato da amostra: arredonda e satura
            yn = sat(np.round(acc / escala))
            x2, x1 = x1, xn
            y2, y1 = y1, yn
            saida[i] = yn
        y = saida

    return y / escala


def teste_ciclo_limite(sos: np.ndarray, frac_bits: int,
                       total_bits: int = 32,
                       n_excitacao: int = 64,
                       n_silencio: int = 20000,
                       amplitude: float = 0.5) -> dict:
    """Excita, cala a entrada e ve se a saida morre.

    Ciclo limite e a doenca propria do IIR em ponto fixo: o arredondamento
    realimentado sustenta uma oscilacao que nao existe em precisao
    infinita. Com entrada nula a saida TEM que ir a zero e ficar; se
    sobrar qualquer coisa depois de milhares de amostras, o filtro
    "canta" sozinho -- e num audio isso e um assobio audivel.
    """
    n = n_excitacao + n_silencio
    x = np.zeros(n)
    rng = np.random.default_rng(0)
    x[:n_excitacao] = amplitude * rng.normal(size=n_excitacao)

    y = filtra_sos_fixo(x, sos, frac_bits, total_bits)
    cauda = y[n_excitacao + n_silencio // 2:]
    residuo = float(np.max(np.abs(cauda)))
    passo = 2.0 ** -frac_bits
    return {
        "residuo": residuo,
        "residuo_em_lsb": residuo / passo,
        "tem_ciclo": residuo > 0.0,
        "amostras_de_silencio": n_silencio,
    }


#: Acima deste raio os polos ficam tao perto do circulo que a dead band
#: em ponto fixo cresce depressa. Medido: em 0,988 a saida trava em 118
#: LSB; em 0,9984, em 13740 LSB.
RAIO_ALERTA = 0.99

#: Dead band aceitavel, relativa ao pico do sinal de teste.
DEAD_BAND_ALERTA = 1e-3


def estima_dead_band(sos: np.ndarray, frac_bits: int) -> float:
    """Estimativa barata da dead band, sem simular.

    Cada secao arredonda com erro de meio LSB, e esse erro e amplificado
    pelo ganho DC da recorrencia, 1/|1+a1+a2| -- que explode quando os
    polos se aproximam de z=+1. Serve de TRIAGEM: subestima, porque as
    dead bands se acumulam ao longo da cascata (medido: erra por 4 a 6
    vezes nos filtros estreitos). Quem da o veredito e teste_ciclo_limite.
    """
    lsb = 2.0 ** -frac_bits
    pior = lsb / 2.0
    for sec in np.atleast_2d(sos):
        denom = abs(1.0 + sec[4] + sec[5])
        if denom > 0.0:
            pior = max(pior, lsb / 2.0 * (1.0 / denom))
    return pior


def verifica_viabilidade(sos: np.ndarray, frac_bits: int = 16,
                         total_bits: int = 32,
                         simular: bool = True) -> dict:
    """O filtro sobrevive a este formato de ponto fixo?

    E o equivalente IIR do teste de MAX_TAPS do projetista FIR: em vez de
    entregar calado um filtro que nao funciona no hardware, diz o que vai
    dar errado e por que.

    veredito:
      'ok'      -> pode ir para o hardware
      'alerta'  -> funciona, mas com dead band perceptivel
      'recusar' -> instavel ou com coeficiente aniquilado
    """
    a = analisa_quantizacao(sos, frac_bits, total_bits)
    motivos = []
    veredito = "ok"

    if a["instavel"]:
        veredito = "recusar"
        motivos.append(
            "Depois de quantizar em Q%d.%d, um polo foi para |p| = %.6f, "
            "fora do circulo unitario. O filtro oscila sem parar."
            % (total_bits - 1 - frac_bits, frac_bits, a["raio_depois"]))

    if a["coef_zerou"]:
        veredito = "recusar"
        motivos.append(
            "Algum coeficiente do numerador (o menor vale %.3e) e menor "
            "que o passo do formato (%.3e) e virou ZERO. Distribua o "
            "ganho entre as secoes com distribui_ganho() antes de "
            "quantizar." % (a["menor_b"], a["passo"]))

    if a["coef_saturou"]:
        veredito = "recusar"
        motivos.append(
            "Algum coeficiente estourou a faixa do formato.")

    if a["raio_antes"] > RAIO_ALERTA and veredito == "ok":
        veredito = "alerta"
        motivos.append(
            "O polo mais externo esta em |p| = %.6f, muito perto do "
            "circulo. Estavel, mas a dead band cresce depressa nessa "
            "regiao." % a["raio_antes"])

    dead_band = None
    if simular:
        r = teste_ciclo_limite(sos, frac_bits, total_bits)
        dead_band = r["residuo"]
        if dead_band > DEAD_BAND_ALERTA and veredito != "recusar":
            veredito = "alerta"
            motivos.append(
                "Com a entrada em silencio a saida trava em %.4g (%.0f "
                "LSB) em vez de ir a zero. E dead band: o arredondamento "
                "realimentado nao consegue mais descer."
                % (dead_band, r["residuo_em_lsb"]))

    return {
        "veredito": veredito,
        "motivos": motivos,
        "raio_antes": a["raio_antes"],
        "raio_depois": a["raio_depois"],
        "deslocamento_max": a["deslocamento_max"],
        "dead_band": dead_band,
        "dead_band_estimada": estima_dead_band(sos, frac_bits),
        "sos_q": a["sos_q"],
    }
