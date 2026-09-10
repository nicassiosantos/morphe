"""morphe_config.py -- limites e tamanhos do hardware Morphe.

Espelho do morphe_config.h em C. Centraliza limites e tamanhos do
hardware da FPGA Morphe (DE1-SoC) para que cliente Python e servidor C
permanecam sincronizados.

Mude APENAS este arquivo (e morphe_config.h em C, em paralelo) ao
reconfigurar o hardware -- o restante do codigo importa daqui.
"""
from __future__ import annotations

# ---- FFT -----------------------------------------------------------------

#: Tamanho fixo da FFT no hardware (Buffered Burst). Deve ser potencia de 2.
FFT_N: int = 1024

#: Largura util dos dados nas SRAMs da FFT, em bits (com sinal).
#: Os 24 bits baixos sao usados pela FPGA (num[23:0] em Verilog); os 8 bits
#: altos sao sign-extension para que o transporte int32 entre cliente
#: Python e servidor C carregue valor matematicamente correto.
FFT_DATA_BITS: int = 24

#: Bits fracionarios do formato Q15.8 (1 sinal + 15 inteiros + 8 fracionarios).
#: Fator de escala: valor_int24 = round(valor_float * 2^FFT_FRAC_BITS).
#: Faixa: [-32768.0, +32767.99609375]; resolucao: 2^-8 = 0.00390625.
FFT_FRAC_BITS: int = 8

#: Ganho residual da transformada INVERSA no hardware -- MEDIDO NA PLACA.
#:
#: O IP da FFT (Buffered Burst, ponto flutuante de bloco) devolve o
#: expoente BFP, que o servidor ja aplica. O que sobra e a convencao do
#: proprio IP quanto ao fator 1/N da IDFT. Medido em 10/09/2026 com o
#: testa_bit_inverse.py na DE1-SoC: mandando um x[n] real com o bit
#: inverse ligado, o que voltou tem a MESMA magnitude da DFT
#: (|Y|/|DFT(x)| = 1.00031) e casa com conj(DFT(x)) a 3.1e-04.
#:
#: Para x real a IDFT matematica vale conj(DFT(x))/N, ou seja, teria
#: magnitude N vezes menor. Como nao tem, o IP NAO aplica o 1/N: ele
#: calcula a inversa nao normalizada. O cliente aplica o fator aqui.
IFFT_HW_GAIN: float = 1.0 / FFT_N

# ---- Convolucao 1D --------------------------------------------------------

#: Numero maximo de amostras por entrada (x ou h) -- formato Q15.16.
CONV_N_MAX: int = 1024

#: Tamanho maximo do vetor de saida y[n] = x[n] * h[n].
CONV_Y_MAX: int = 2 * CONV_N_MAX - 1  # = 2047

# ---- Rede ----------------------------------------------------------------

#: Porta TCP padrao do servidor (cliente pode sobrescrever).
DEFAULT_PORT: int = 5000


# ---- Sanidade ------------------------------------------------------------
# Estas asserts pegam configuracoes inconsistentes na hora do import.

assert FFT_N > 0 and (FFT_N & (FFT_N - 1)) == 0, \
    "FFT_N deve ser potencia de 2"
assert FFT_DATA_BITS in (8, 16, 24, 32), \
    "FFT_DATA_BITS suportados: 8, 16, 24, 32"
assert 0 <= FFT_FRAC_BITS < FFT_DATA_BITS, \
    "FFT_FRAC_BITS deve ser >= 0 e < FFT_DATA_BITS"
assert CONV_N_MAX > 0, "CONV_N_MAX deve ser > 0"
