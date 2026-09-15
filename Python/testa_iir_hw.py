#!/usr/bin/env python3
"""testa_iir_hw.py -- o bloco IIR da FPGA contra o modelo em ponto fixo.

Mesmo criterio do testbench (roda_tb_iir.sh): a saida da placa tem que
ser BIT A BIT igual ao iir_design.filtra_sos_fixo. Num filtro realimentado
"parecido" nao serve -- um LSB de diferenca numa amostra vira divergencia
permanente dali em diante.

Casos, em ordem de exigencia:

  1. impulso por uma secao: se isto falhar, nada mais importa
  2. cascata de 11 secoes (Butterworth de ordem 22, o pior caso do estudo)
     com 1024 amostras -- exercita a indexacao das secoes e a carga dos
     coeficientes
  3. a mesma cascata com 300 amostras -- o hardware processa sempre 1024;
     confere que o servidor completa com zeros e devolve so as 300
  4. saturacao provocada na ressonancia de uma secao: a flag `extra` tem
     que vir 1 e a saida tem que grudar no limite, igual ao modelo

Uso:
    python testa_iir_hw.py <host> [porta]
"""
from __future__ import annotations

import sys

import numpy as np

import iir_design as iir
import morphe_config as cfg
from morphe_protocol import TcpClient, build_iir_request, decode_iir_response

FRAC = cfg.IIR_FRAC_BITS
TOTAL = 32
ESCALA = 1 << FRAC


def q(v: np.ndarray) -> np.ndarray:
    """float -> inteiros Q15.16, o mesmo arredondamento do modelo."""
    return np.floor(np.asarray(v, dtype=np.float64) * ESCALA + 0.5).astype(np.int64)


def iir_fpga(client: TcpClient, x_q: np.ndarray, coefs) -> tuple[np.ndarray, bool]:
    return decode_iir_response(client.request(build_iir_request(x_q, coefs)))


def compara(nome: str, y_hw: np.ndarray, y_ref: np.ndarray) -> int:
    """Imprime o veredito e devolve 0 se bateu, 1 se nao."""
    if len(y_hw) != len(y_ref):
        print("   FALHOU: %d amostras voltaram, esperava %d" % (len(y_hw), len(y_ref)))
        return 1
    dif = np.nonzero(y_hw != y_ref)[0]
    if len(dif) == 0:
        print("   OK: %d amostras, bit a bit igual ao modelo" % len(y_ref))
        return 0
    i = int(dif[0])
    print("   FALHOU: %d de %d amostras diferentes; primeira em n=%d "
          "(placa %d, modelo %d)" % (len(dif), len(y_ref), i, y_hw[i], y_ref[i]))
    return 1


def sinal_generico(n_amostras: int) -> np.ndarray:
    """Impulso, degrau, senoide e ruido -- o mesmo do gera_vetores_iir."""
    rng = np.random.default_rng(20260915)
    n = np.arange(n_amostras)
    x = np.zeros(n_amostras)
    x[0] = 1.0
    x[16:48] = 0.75
    fim_seno = min(160, n_amostras)
    x[64:fim_seno] = 0.9 * np.sin(2 * np.pi * 11 * n[64:fim_seno] / 256)
    if n_amostras > 176:
        x[176:] = 0.4 * rng.normal(size=n_amostras - 176)
    return x


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else cfg.DEFAULT_PORT
    client = TcpClient(host, port, timeout=15.0)
    falhas = 0

    # Os dois filtros do testbench: a eliptica (poucas secoes) e o
    # Butterworth de ordem 22 (o mais duro do estudo).
    elip = iir.design_iir("ellip", 1000.0, 1500.0, 1.0, 40.0, 8000.0)
    elip.sos = iir.distribui_ganho(elip.sos)
    butt = iir.design_iir("butterworth", 200.0, 300.0, 0.1, 60.0, 8000.0)
    butt.sos = iir.distribui_ganho(butt.sos)

    # -- 1. impulso por uma secao -----------------------------------------
    print("1) impulso por uma secao da eliptica")
    raios = [float(np.max(np.abs(np.roots(s[3:6])))) for s in elip.sos]
    secao = elip.sos[int(np.argmax(raios)):int(np.argmax(raios)) + 1]
    coefs = iir.coeficientes_inteiros(secao, FRAC, TOTAL)
    x = np.zeros(64); x[0] = 1.0
    y_ref = q(iir.filtra_sos_fixo(x, secao, FRAC, TOTAL))
    try:
        y_hw, sat = iir_fpga(client, q(x), coefs)
    except Exception as e:
        print("   FALHOU:", e)
        return 1
    print("   coeficientes: b0=%d b1=%d b2=%d a1=%d a2=%d" % tuple(coefs[0]))
    print("   primeiras saidas: placa %s / modelo %s" % (y_hw[:4].tolist(), y_ref[:4].tolist()))
    falhas += compara("impulso", y_hw, y_ref)
    if sat:
        print("   FALHOU: saturou num impulso unitario")
        falhas += 1
    print()

    # -- 2. cascata completa, 1024 amostras ---------------------------------
    print("2) cascata de %d secoes, %d amostras" % (butt.n_secoes, cfg.IIR_N_MAX))
    coefs = iir.coeficientes_inteiros(butt.sos, FRAC, TOTAL)
    x = sinal_generico(cfg.IIR_N_MAX)
    y_ref = q(iir.filtra_sos_fixo(x, butt.sos, FRAC, TOTAL))
    y_hw, sat = iir_fpga(client, q(x), coefs)
    falhas += compara("cascata", y_hw, y_ref)
    if sat:
        print("   FALHOU: flag de saturacao ligada sem motivo")
        falhas += 1
    print()

    # -- 3. cascata com menos amostras que a memoria ------------------------
    print("3) a mesma cascata com 300 amostras (o hardware roda 1024)")
    x = sinal_generico(300)
    y_ref = q(iir.filtra_sos_fixo(x, butt.sos, FRAC, TOTAL))
    y_hw, sat = iir_fpga(client, q(x), coefs)
    falhas += compara("300", y_hw, y_ref)
    print()

    # -- 4. saturacao provocada ---------------------------------------------
    print("4) saturacao na ressonancia de uma secao")
    limite = float((1 << (TOTAL - 1)) - 1) / ESCALA
    f_eixo, H = iir.resposta_sos(secao, n_freq=4096, fs=8000.0)
    i_pico = int(np.argmax(np.abs(H)))
    ganho_pico = float(np.abs(H)[i_pico])
    f_ress = float(f_eixo[i_pico])
    amplitude = min(limite * 0.95, limite / ganho_pico * 1.5)
    n = np.arange(256)
    x = amplitude * np.sin(2 * np.pi * f_ress * n / 8000.0)
    coefs = iir.coeficientes_inteiros(secao, FRAC, TOTAL)
    y_ref = q(iir.filtra_sos_fixo(x, secao, FRAC, TOTAL))
    y_hw, sat = iir_fpga(client, q(x), coefs)
    print("   ressonancia em %.1f Hz, ganho %.3f, amplitude %.1f (limite %.1f)"
          % (f_ress, ganho_pico, amplitude, limite))
    falhas += compara("saturacao", y_hw, y_ref)
    grudou = int(np.max(np.abs(y_hw))) >= (1 << (TOTAL - 1)) - 1
    print("   flag extra = %d, saida encostou no limite: %s" % (int(sat), "sim" if grudou else "nao"))
    if not sat:
        print("   FALHOU: a placa nao sinalizou a saturacao")
        falhas += 1
    print()

    print("FALHAS: %d" % falhas)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
