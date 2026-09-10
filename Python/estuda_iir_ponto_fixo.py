#!/usr/bin/env python3
"""estuda_iir_ponto_fixo.py -- passo 0 do bloco IIR em hardware.

Roda sem placa e sem Verilog. Responde tres perguntas, e a ordem
importa: se a primeira falhasse, as outras nao teriam sentido.

  1. Os polos continuam dentro do circulo unitario depois de quantizar?
  2. Os coeficientes do numerador sobrevivem ao passo do formato?
  3. A saida morre quando a entrada cala, ou o filtro trava num valor?

Uso:
    python estuda_iir_ponto_fixo.py
"""
from __future__ import annotations

import numpy as np

import iir_design as iir


#: Casos escolhidos para cobrir os quatro tipos, as tres aproximacoes e,
#: de proposito, dois filtros ESTREITOS (L4 e L5) -- que sao onde o ponto
#: fixo sofre.
CASOS = [
    ("L1", "butterworth", 1000.0,          1500.0,         1.0, 40.0),
    ("L2", "cheby1",      1000.0,          1500.0,         0.5, 40.0),
    ("L3", "cheby2",      1000.0,          1500.0,         1.0, 40.0),
    ("H1", "butterworth", 2000.0,          1200.0,         1.0, 40.0),
    ("H2", "cheby1",      2000.0,          1200.0,         0.5, 35.0),
    ("B1", "butterworth", (1200., 2400.),  (800., 3000.),  1.0, 35.0),
    ("S1", "butterworth", (800., 3000.),   (1200., 2400.), 1.0, 35.0),
    ("L4", "butterworth", 200.0,           300.0,          0.1, 60.0),
    ("L5", "cheby1",      50.0,            80.0,           0.1, 60.0),
]

FS = 8000.0
FORMATOS = [("Q15.16", 16), ("Q3.28", 28)]


def linha(c=" ", n=88):
    print(c * n)


def main() -> int:
    projetos = {}
    for cid, aprox, fp, fsb, dp, ds in CASOS:
        p = iir.design_iir(aprox, fp, fsb, dp, ds, FS)
        # Sem isto os coeficientes pequenos do numerador viram zero --
        # ver a tabela 3.
        p.sos = iir.distribui_ganho(p.sos)
        projetos[cid] = p

    linha("=")
    print("1) POLOS depois de quantizar")
    linha("=")
    print("%-4s %-12s %5s %4s %12s %12s %12s %12s"
          % ("caso", "aprox", "ordem", "sec", "raio float",
             "Q15.16", "Q3.28", "desloc Q15.16"))
    linha("-")
    for cid, p in projetos.items():
        a16 = iir.analisa_quantizacao(p.sos, 16)
        a28 = iir.analisa_quantizacao(p.sos, 28)
        print("%-4s %-12s %5d %4d %12.6f %12.6f %12.6f %12.2e"
              % (cid, p.aprox, p.ordem, p.n_secoes, a16["raio_antes"],
                 a16["raio_depois"], a28["raio_depois"],
                 a16["deslocamento_max"]))

    print()
    linha("=")
    print("2) NUMERADOR -- com o ganho distribuido entre as secoes")
    linha("=")
    print("%-4s %14s %22s" % ("caso", "menor |b|", "Q15.16"))
    linha("-")
    for cid, p in projetos.items():
        a = iir.analisa_quantizacao(p.sos, 16)
        print("%-4s %14.3e %22s"
              % (cid, a["menor_b"],
                 "ZEROU" if a["coef_zerou"] else "ok"))

    print()
    linha("=")
    print("3) NUMERADOR -- com todo o ganho na primeira secao")
    print("   (o jeito ingenuo de fatorar; e por isso que existe")
    print("    distribui_ganho())")
    linha("=")
    print("%-4s %14s %22s" % ("caso", "menor |b|", "Q15.16"))
    linha("-")
    for cid, aprox, fp, fsb, dp, ds in CASOS:
        p = iir.design_iir(aprox, fp, fsb, dp, ds, FS)   # sem distribuir
        a = iir.analisa_quantizacao(p.sos, 16)
        print("%-4s %14.3e %22s"
              % (cid, a["menor_b"],
                 "ZEROU" if a["coef_zerou"] else "ok"))

    print()
    linha("=")
    print("4) DEAD BAND -- a saida morre depois que a entrada cala?")
    linha("=")
    print("%-4s %-8s %14s %12s  %s"
          % ("caso", "formato", "residuo", "em LSB", "veredito"))
    linha("-")
    for cid in ("L1", "L2", "L4", "L5"):
        p = projetos[cid]
        for nome, fb in FORMATOS:
            r = iir.teste_ciclo_limite(p.sos, fb, n_silencio=20000)
            print("%-4s %-8s %14.6e %12.0f  %s"
                  % (cid, nome, r["residuo"], r["residuo_em_lsb"],
                     "TRAVA" if r["tem_ciclo"] else "morre (ok)"))

    print()
    linha("=")
    print("5) AS QUATRO APROXIMACOES na mesma especificacao")
    print("   (a eliptica so aparece com scipy instalado)")
    linha("=")
    print("%-9s %-12s %5s %4s %10s %10s %12s %8s"
          % ("spec", "aprox", "ordem", "sec", "raio", "desloc",
             "dead band", "em LSB"))
    linha("-")
    for nome, fp, fsb, dp, ds in [("largo", 1000., 1500., 1.0, 40.),
                                  ("medio", 400., 550., 0.5, 50.),
                                  ("estreito", 200., 300., 0.1, 60.)]:
        for ap in iir.APROXIMACOES:
            p_ = iir.design_iir(ap, fp, fsb, dp, ds, FS)
            p_.sos = iir.distribui_ganho(p_.sos)
            a = iir.analisa_quantizacao(p_.sos, 16)
            r = iir.teste_ciclo_limite(p_.sos, 16, n_silencio=8000)
            print("%-9s %-12s %5d %4d %10.6f %10.1e %12.3e %8.0f"
                  % (nome, ap, p_.ordem, p_.n_secoes, a["raio_antes"],
                     a["deslocamento_max"], r["residuo"],
                     r["residuo_em_lsb"]))
        print()

    print()
    linha("=")
    print("6) VEREDITO por caso, em Q15.16")
    linha("=")
    for cid, p in projetos.items():
        v = iir.verifica_viabilidade(p.sos, 16)
        print("%-4s  %-8s  %s" % (cid, v["veredito"].upper(),
                                  p.descricao()))
        for m in v["motivos"]:
            for i, pedaco in enumerate(_quebra(m, 74)):
                print("        %s" % pedaco)
    return 0


def _quebra(texto: str, largura: int):
    palavras, linha_atual, saida = texto.split(), "", []
    for w in palavras:
        if len(linha_atual) + len(w) + 1 > largura:
            saida.append(linha_atual)
            linha_atual = w
        else:
            linha_atual = (linha_atual + " " + w).strip()
    if linha_atual:
        saida.append(linha_atual)
    return saida


if __name__ == "__main__":
    raise SystemExit(main())
