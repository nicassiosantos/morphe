#!/usr/bin/env python3
"""testa_ifft_roundtrip.py -- x -> FFT -> IFFT -> x, medido contra o NumPy.

Valida o caminho OP_IFFT inteiro: payload complexo, bit `inverse`, escala
do espectro no cliente e o desfazer da escala na volta.

Faz tres coisas, em ordem de exigencia:

  1. IFFT de um espectro conhecido (delta em k=0 -> constante no tempo).
     Se isto falhar, nada mais importa.
  2. Ida e volta: manda x, recebe X da FPGA, manda X de volta, compara o
     que voltou com o x original.
  3. Mede o ganho residual do hardware e diz o que por em IFFT_HW_GAIN.

O erro do item 2 NAO vai a zero: o espectro trafega em Q15.8, com 8 bits
fracionarios. O piso esperado e da ordem de 1e-3 relativo, nao 1e-7.

Uso:
    python testa_ifft_roundtrip.py <host> [porta]
"""
from __future__ import annotations

import sys

import numpy as np

import morphe_config as cfg
from morphe_protocol import (
    TcpClient, build_fft_request, decode_fft_response,
    build_ifft_request, decode_ifft_response,
)


def ifft_fpga(client: TcpClient, X: np.ndarray) -> np.ndarray:
    req, escala = build_ifft_request(X)
    resp = client.request(req)
    return decode_ifft_response(resp, escala)


def erro_rel(a: np.ndarray, b: np.ndarray) -> float:
    pico = float(np.max(np.abs(b)))
    if pico == 0.0:
        return float(np.max(np.abs(a)))
    return float(np.max(np.abs(a - b)) / pico)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else cfg.DEFAULT_PORT

    client = TcpClient(host, port, timeout=15.0)
    N = cfg.FFT_N
    falhas = 0

    # -- 1. espectro conhecido: X[0] = A, resto zero -> x[n] = A/N ---------
    print("1) IFFT de um delta espectral")
    A = 1000.0
    X = np.zeros(N, dtype=np.complex128)
    X[0] = A
    x_hw = ifft_fpga(client, X)
    x_ref = np.fft.ifft(X)

    e = erro_rel(x_hw.real, x_ref.real)
    print("   esperado (NumPy): constante %.6g" % x_ref.real[0])
    print("   veio da FPGA:     media %.6g, desvio %.3e"
          % (float(np.mean(x_hw.real)), float(np.std(x_hw.real))))
    print("   erro relativo:    %.4e" % e)
    if e > 0.05:
        print("   FALHOU. Se a media veio %.6g vezes o esperado, o fator e"
              % (float(np.mean(x_hw.real)) / x_ref.real[0]
                 if x_ref.real[0] else float("nan")))
        print("   o 1/N do IP: ajuste IFFT_HW_GAIN no morphe_config.py.")
        falhas += 1
    else:
        print("   OK")
    print()

    # -- 2. ida e volta ----------------------------------------------------
    print("2) x -> FFT(FPGA) -> IFFT(FPGA) -> x")
    n = np.arange(N)
    x = (10.0 * np.sin(2 * np.pi * 7 * n / N)
         + 4.0 * np.cos(2 * np.pi * 23 * n / N))

    req_fft, esc_fft = build_fft_request(x)
    X_hw = decode_fft_response(client.request(req_fft), esc_fft)
    x_volta = ifft_fpga(client, X_hw)

    e_re = erro_rel(x_volta.real, x)
    vaz = float(np.max(np.abs(x_volta.imag)) / np.max(np.abs(x)))
    print("   erro relativo na parte real:  %.4e" % e_re)
    print("   vazamento na imaginaria:      %.4e" % vaz)
    print("   (a entrada era real, entao a imaginaria mede so o ruido de")
    print("    quantizacao acumulado nas duas travessias)")
    if e_re > 0.05:
        print("   FALHOU")
        falhas += 1
    else:
        print("   OK")
    print()

    # -- 3. ganho residual -------------------------------------------------
    print("3) ganho residual do hardware")
    X_ref = np.fft.fft(x)
    x_ref_volta = np.fft.ifft(X_ref).real
    escala_medida = float(np.dot(x_volta.real, x_ref_volta)
                          / np.dot(x_ref_volta, x_ref_volta))
    print("   x_fpga / x_numpy (minimos quadrados): %.8g" % escala_medida)
    if abs(escala_medida - 1.0) < 0.02:
        print("   IFFT_HW_GAIN = %.6g esta correto." % cfg.IFFT_HW_GAIN)
    else:
        print("   Corrija: IFFT_HW_GAIN = %.10g"
              % (cfg.IFFT_HW_GAIN / escala_medida))
        print("   (o valor atual e %.6g)" % cfg.IFFT_HW_GAIN)
        falhas += 1

    print()
    print("FALHAS: %d" % falhas)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
