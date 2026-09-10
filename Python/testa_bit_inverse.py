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

    X_ref = np.fft.fft(x)                    # DFT de referencia, no PC
    dif_direta  = np.max(np.abs(Y - X_ref)) / np.max(np.abs(X_ref))
    dif_conj    = np.max(np.abs(Y - np.conj(X_ref))) / np.max(np.abs(X_ref))

    # Escala: quanto a magnitude que voltou difere da DFT do NumPy.
    razao = float(np.max(np.abs(Y)) / np.max(np.abs(X_ref)))

    print("erro relativo contra DFT(x):        %.4e" % dif_direta)
    print("erro relativo contra conj(DFT(x)):  %.4e" % dif_conj)
    print("razao de magnitude |Y| / |DFT(x)|:  %.6g" % razao)
    print()

    if dif_conj < dif_direta / 10.0:
        print("=> INVERSA. O bit `inverse` esta vivo neste bitstream.")
        print("   A parte imaginaria voltou conjugada, que e a IDFT de um")
        print("   sinal real.")
        if abs(razao - 1.0) < 0.05:
            print("   O IP JA aplica o 1/N: deixe IFFT_HW_GAIN = 1.0")
        else:
            print("   Fator residual medido: %.6g" % razao)
            print("   Ponha IFFT_HW_GAIN = %.10g no morphe_config.py"
                  % (1.0 / razao))
    elif dif_direta < dif_conj / 10.0:
        print("=> DIRETA. O que voltou e a FFT comum.")
        print("   Ou o servidor nao esta com MORPHE_FFT_INVERSE=1, ou o bit")
        print("   nao chega ao IP neste bitstream. Confira o log do servidor:")
        print("   ele avisa na subida quando o diagnostico esta ligado.")
    else:
        print("=> INDEFINIDO. Nenhuma das duas hipoteses ficou clara.")
        print("   Provavel problema de escala ou de Q15.8 -- confira antes")
        print("   se a FFT normal fecha com o NumPy.")

    aviso = dsp.fft_q1508_range_warning(x)
    if aviso:
        print("\nAviso de faixa no envio: " + aviso)
    return 0


if __name__ == "__main__":
    sys.exit(main())
