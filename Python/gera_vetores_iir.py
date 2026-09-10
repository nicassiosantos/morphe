#!/usr/bin/env python3
"""gera_vetores_iir.py -- vetores de teste para o tb_iir_sos.v.

Projeta um filtro, pega UMA secao, roda o modelo em ponto fixo e grava
tres arquivos hexadecimais que o testbench le. O RTL tem que reproduzir a
saida bit a bit.

A secao escolhida e a de polos mais externos -- a mais delicada da
cascata, a que primeiro sofre com arredondamento. Testar a secao facil
nao provaria nada.

Tres casos:

    normal      UMA secao, sinal dentro da faixa; error_sat fica em 0
    saturacao   UMA secao, sinal amplificado de proposito ate a saida
                estourar a faixa do Q15.16; error_sat fica em 1, e a
                saida gruda no limite em vez de dar wrap
    cascata     TODAS as secoes, e de proposito o filtro mais duro do
                estudo: Butterworth de ordem 22 em 11 secoes, o caso de
                pior dead band. Testar a cascata com duas secoes nao
                exerceria nem a indexacao das secoes nem a carga dos
                coeficientes.

O caso de saturacao existe porque saturar e um CAMINHO, nao um acidente:
num laco realimentado o wrap-around vira oscilacao sustentada, e o unico
jeito de saber que a saturacao funciona e provocar.

Uso:
    python gera_vetores_iir.py [normal|saturacao|cascata] [destino]

O destino padrao e ../Quartus, que e de onde o testbench le.
"""
from __future__ import annotations

import os
import sys

import numpy as np

import iir_design as iir


N_AMOSTRAS = 256
FRAC_BITS = 16
TOTAL_BITS = 32


def hexa(v: int, bits: int = 32) -> str:
    """Inteiro com sinal -> hexadecimal de `bits`, em complemento de dois."""
    return "%08x" % (int(v) & ((1 << bits) - 1))


def main() -> int:
    caso = "normal"
    args = [a for a in sys.argv[1:]]
    if args and args[0] in ("normal", "saturacao", "cascata"):
        caso = args.pop(0)
    destino = args[0] if args else \
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "Quartus")
    destino = os.path.abspath(destino)

    if caso == "cascata":
        # O pior caso do estudo: 11 secoes, polos em 0,988, dead band de
        # 118 LSB. Se o RTL bate com o modelo AQUI, bate em qualquer
        # filtro mais facil.
        proj = iir.design_iir("butterworth", 200.0, 300.0, 0.1, 60.0, 8000.0)
    else:
        # Eliptica: menos secoes para a mesma especificacao, e foi a que
        # saiu melhor no estudo de ponto fixo.
        proj = iir.design_iir("ellip", 1000.0, 1500.0, 1.0, 40.0, 8000.0)
    proj.sos = iir.distribui_ganho(proj.sos)

    print(proj.descricao())

    if caso == "cascata":
        secao = proj.sos                      # a cascata inteira
        print("cascata completa: %d secoes" % proj.n_secoes)
    else:
        # a secao mais critica: polos mais proximos do circulo
        raios = [float(np.max(np.abs(np.roots(sec[3:6]))))
                 for sec in proj.sos]
        i = int(np.argmax(raios))
        secao = proj.sos[i:i + 1]
        print("secao escolhida: %d de %d, polos em |p| = %.6f"
              % (i + 1, proj.n_secoes, raios[i]))

    coefs = iir.coeficientes_inteiros(secao, FRAC_BITS, TOTAL_BITS)
    for j, c in enumerate(coefs):
        print("  secao %d: b0=%d b1=%d b2=%d a1=%d a2=%d" % ((j,) + tuple(c)))

    # Entrada: impulso, degrau, senoide e ruido, para exercitar
    # transitorio, regime, ressonancia e o caminho de saturacao.
    rng = np.random.default_rng(20260910)
    n = np.arange(N_AMOSTRAS)
    x = np.zeros(N_AMOSTRAS)
    x[0] = 1.0
    x[16:48] = 0.75
    x[64:160] = 0.9 * np.sin(2 * np.pi * 11 * n[64:160] / N_AMOSTRAS)
    x[176:] = 0.4 * rng.normal(size=N_AMOSTRAS - 176)

    if caso == "saturacao":
        # Amplificar o sinal generico nao satura: esta secao ATENUA na
        # maior parte da banda, e a entrada estoura antes da saida. Para
        # exercitar a saturacao de verdade e preciso bater onde a secao
        # amplifica -- na ressonancia dela.
        limite = float((1 << (TOTAL_BITS - 1)) - 1) / (1 << FRAC_BITS)
        f_eixo, H = iir.resposta_sos(secao, n_freq=4096, fs=8000.0)
        i_pico = int(np.argmax(np.abs(H)))
        ganho_pico = float(np.abs(H)[i_pico])
        f_ress = float(f_eixo[i_pico])
        # 1,5 vezes o necessario: sobra para nao depender de arredondamento
        amplitude = min(limite * 0.95, limite / ganho_pico * 1.5)
        x = amplitude * np.sin(2 * np.pi * f_ress * n / 8000.0)
        print("ressonancia em %.1f Hz, ganho de pico %.4f" %
              (f_ress, ganho_pico))
        print("amplitude de entrada: %.1f  (limite %.1f)"
              % (amplitude, limite))

    y = iir.filtra_sos_fixo(x, secao, FRAC_BITS, TOTAL_BITS)

    escala = 1 << FRAC_BITS
    x_int = [int(np.floor(v * escala + 0.5)) for v in x]
    y_int = [int(np.floor(v * escala + 0.5)) for v in y]

    achatados = [c for linha in coefs for c in linha]
    arquivos = {
        "vetores_coef.hex": [hexa(c) for c in achatados],
        "vetores_nsec.hex": [hexa(len(coefs))],
        "vetores_x.hex":    [hexa(v) for v in x_int],
        "vetores_y.hex":    [hexa(v) for v in y_int],
    }
    for nome, linhas in arquivos.items():
        caminho = os.path.join(destino, nome)
        with open(caminho, "w", encoding="ascii") as f:
            f.write("\n".join(linhas) + "\n")
        print("gravado: %s  (%d linhas)" % (caminho, len(linhas)))

    limite = float((1 << (TOTAL_BITS - 1)) - 1) / (1 << FRAC_BITS)
    pico = float(np.max(np.abs(y)))
    print()
    print("caso        : %s" % caso)
    print("pico de |y| : %.6f   (limite do Q15.16: %.4f)" % (pico, limite))
    print("saturou     : %s  <- error_sat esperado no RTL"
          % ("SIM" if pico >= limite else "nao"))
    print()
    print("Rode o roda_tb_iir.sh no diretorio Quartus.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
