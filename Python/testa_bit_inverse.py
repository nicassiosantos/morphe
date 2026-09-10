#!/usr/bin/env python3
"""testa_bit_inverse.py -- o bit `inverse` do IP da FFT esta vivo na placa?

Este e o teste que vem ANTES de qualquer coisa. Ele nao usa o OP_IFFT nem
o payload complexo: manda um sinal REAL pelo caminho da FFT que ja
funciona, com o servidor iniciado assim:

    MORPHE_FFT_INVERSE=1 sudo -E ./morphe_server

Nesse modo o servidor liga o bit `inverse` no OP_FFT (e so nele; e um
diagnostico, nao a operacao normal).

Por que isso responde a pergunta: para x[n] REAL,

    IDFT(x)[k] = conj(DFT(x)[k]) / N        (ou sem o /N, conforme o IP)

ou seja, a parte real fica igual e a imaginaria troca de sinal em bloco.
Se o bit estiver morto no bitstream, o resultado sai identico ao da FFT
direta e o teste diz isso com todas as letras.

De quebra, a razao entre as magnitudes mede o fator 1/N -- que e o numero
que vai para IFFT_HW_GAIN no morphe_config.py.

Uso:
    python testa_bit_inverse.py <host> [porta]
"""
from __future__ import annotations

import sys

import numpy as np

import dsp_core as dsp
import morphe_config as cfg
from morphe_protocol import (
    TcpClient, build_fft_request, decode_fft_response,
)


def roda(client: TcpClient, x: np.ndarray) -> np.ndarray:
    resp = client.request(build_fft_request(x))
    return decode_fft_response(resp)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else cfg.DEFAULT_PORT

    client = TcpClient(host, port, timeout=15.0)

    # Sinal real, sem simetria acidental: duas senoides e um degrau leve.
    n = np.arange(cfg.FFT_N)
    x = (10.0 * np.sin(2 * np.pi * 7 * n / cfg.FFT_N)
         + 4.0 * np.cos(2 * np.pi * 23 * n / cfg.FFT_N)
         + 0.5)

    print("Mandando o mesmo x[n] real e olhando o que volta.")
    print("Rode este script DUAS vezes: uma com o servidor normal,")
    print("outra com MORPHE_FFT_INVERSE=1 no ambiente dele.\n")

    Y = roda(client, x)

    # Tres hipoteses, todas escritas em termos da mesma referencia. Para
    # x REAL vale IDFT(x) = conj(DFT(x))/N, entao a inversa normalizada e
    # a nao normalizada diferem por um fator N -- e e exatamente esse
    # fator que precisamos descobrir.
    N = len(x)
    X_ref = np.fft.fft(x)
    hipoteses = {
        "DFT direta (bit morto)":            X_ref,
        "IDFT normalizada (IP aplica 1/N)":  np.conj(X_ref) / N,
        "IDFT sem normalizar (IP nao aplica 1/N)": np.conj(X_ref),
    }

    # Erro relativo ao pico de CADA hipotese: sem isso a hipotese de
    # menor amplitude ganharia sozinha, so por ser pequena.
    erros = {nome: float(np.max(np.abs(Y - ref)) / np.max(np.abs(ref)))
             for nome, ref in hipoteses.items()}
    for nome, e in erros.items():
        print("erro relativo contra %-42s %.4e" % (nome, e))
    print("razao de magnitude |Y| / |DFT(x)|:  %.6g"
          % float(np.max(np.abs(Y)) / np.max(np.abs(X_ref))))
    print()

    vencedora = min(erros, key=erros.get)
    segunda = sorted(erros.values())[1]
    if erros[vencedora] > 0.01 or erros[vencedora] > segunda / 10.0:
        print("=> INDEFINIDO. Nenhuma hipotese se destacou.")
        print("   Provavel problema de escala ou de Q15.8 -- confira antes")
        print("   se a FFT normal fecha com o NumPy.")
    elif vencedora.startswith("DFT direta"):
        print("=> DIRETA. O que voltou e a FFT comum.")
        print("   Ou o servidor nao esta com MORPHE_FFT_INVERSE=1, ou o bit")
        print("   nao chega ao IP neste bitstream. Confira o log do servidor:")
        print("   ele avisa na subida quando o diagnostico esta ligado.")
    else:
        print("=> INVERSA. O bit `inverse` esta vivo neste bitstream.")
        print("   A parte imaginaria voltou conjugada, que e a IDFT de um")
        print("   sinal real.")
        if "sem normalizar" in vencedora:
            print("   O IP NAO aplica o 1/N -- a saida e N vezes a IDFT.")
            print("   IFFT_HW_GAIN = 1.0 / FFT_N  (= %.10g)" % (1.0 / N))
        else:
            print("   O IP JA aplica o 1/N.")
            print("   IFFT_HW_GAIN = 1.0")

    aviso = dsp.fft_q1508_range_warning(x)
    if aviso:
        print("\nAviso de faixa no envio: " + aviso)
    return 0


if __name__ == "__main__":
    sys.exit(main())
