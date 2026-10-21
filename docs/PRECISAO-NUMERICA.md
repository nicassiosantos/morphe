# Precisão numérica do Morphe — fatos medidos

Consequências numéricas da FFT e do ADC neste hardware. Só o que foi medido ou lido
no código, com a fonte ao lado.

Medições da FFT: 10/09/2026, DE1-SoC. Medições do ADC: 24/09 e 07/10/2026.

---

## 1. O formato da FFT: Q15.8

| caminho | formato | passo | faixa | onde |
|---|---|---|---|---|
| FFT | **Q15.8** (24 bits) | 2⁻⁸ = 1/256 | ±32768 | `C/morphe_config.h`, `MORPHE_FFT_FRAC_BITS` |
| ADC | código de 12 bits | 1 mV | 0 a 4,095 V (simples), ±2,048 V (diferencial) | `C/morphe_config.h`, seção do ADC |

A FFT usa Q15.8 porque a SRAM entrega `sink_real[23:0]` ao IP da Altera: 24 bits,
sobram 8 fracionários depois do sinal e dos 15 inteiros.

Codificação: `q = round(v · 2^8)`, saturando na faixa. Python:
`dsp_core.fft_q1508_encode`.

---

## 2. A regra que governa tudo: 6,02 dB por bit

Erro de arredondamento uniforme em [-Δ/2, +Δ/2], variância Δ²/12.

Multiplicar o sinal por `s` antes de codificar e dividir por `s` depois faz o passo
efetivo virar Δ/s:

    ganho = 20·log10(s)        dobrar s = 6,02 dB = 1 bit

Exato, não aproximado: a DFT é linear, então `DFT(s·x)/s` é o mesmo valor matemático
com menos erro de quantização.

O ganho disponível é o que sobra de faixa não usada:

    ganho_max = 6,02 · log2( 32768 / max|entrada| )

**Consequência:** mandar um sinal de amplitude 3 numa faixa que vai a 32768 joga fora
~13 bits.

---

## 3. Medido na placa: varredura de escala na FFT

Mesmo sinal (pico 3,3), amplitudes diferentes, escala desfeita na volta, comparado
com `np.fft.fft`:

| escala | pico de x | SNR | ganho |
|---:|---:|---:|---:|
| 1 | 3,3 | 50,42 dB | — |
| 4 | 13,2 | 62,74 dB | +12,32 |
| 16 | 52,8 | 75,07 dB | +24,65 |
| 64 | 211,1 | 86,64 dB | +36,22 |
| 256 | 844,3 | 91,74 dB | +41,33 |
| 1024 | 3377,3 | 91,66 dB | +41,24 |
| 4096 | 13509,1 | 91,55 dB | +41,13 |

De 1 para 64 são 6 bits: teoria 36,12 dB, medido 36,22 dB. A fórmula fecha com o
hardware.

**Teto medido: ~92 dB.** Acima de escala 256 não ganha mais nada. Ali o limite deixa
de ser o Q15.8 da entrada e passa a ser a aritmética interna do IP (twiddles de 18
bits, saída de 24 com expoente compartilhado).

---

## 4. A normalização é opcional, e o padrão é ligada

A janela da FFT normaliza por padrão; a caixa "Normalizar entrada" desliga. Medido na
placa, mesmo sinal (pico 3,3): **50,42 dB** sem normalizar, **91,53 dB** normalizada
(escala 9737).

API: `build_fft_request(x, normalizar=True)` devolve `(payload, escala)`; o
`decode_fft_response(resp, escala)` desfaz. Desligar manda o sinal como está,
**inclusive com a saturação** acima de 32768.

---

## 5. Como o IP normaliza por dentro (Block Floating Point)

O IP da FFT é *Buffered Burst*, *Quad Output*, N=1024, entrada de 24 bits, twiddles de
18 (`Quartus/fft_core/fft_core.xml`).

A cada estágio radix-4 (5 estágios, 1024 = 4⁵) ele detecta crescimento, desloca as
1024 amostras **juntas** e acumula um expoente:

    y_real = y_raw · 2^(-exp)      um único exp para o bloco inteiro

Caminho do expoente:

    fft_wrapper.v       captura source_exp (6 bits) no source_sop
                        -> PIO fft_bfp_exponent
    morphe_server.c     bfp_scale   = ldexpf(1.0f, -bfp_exp)
                        total_scale = bfp_scale / 256

**Duas consequências:**

1. O BFP **não** recupera o que morreu na entrada. O que ficou abaixo de 1/512 já era
   zero antes de o IP existir. Por isso escalar a entrada ainda rende 6 dB por bit.
2. O expoente é **compartilhado** pelo bloco. Bins muito abaixo do pico carregam menos
   bits efetivos, porque o deslocamento foi ditado pelo maior. É isso, com os twiddles
   de 18 bits, que põe o teto em ~92 dB.

Normalização do cliente e BFP do IP resolvem problemas diferentes: a primeira
posiciona o sinal **antes** de virar 24 bits; o segundo evita overflow **durante** a
transformada. Nenhum substitui o outro.

---

## 6. FFT longa (quatro passos)

Um sinal de mais de 1024 amostras vira uma DFT de 1024·M pontos: M FFTs de 1024 na
placa, cada uma normalizada por conta própria, ligadas no PC em float64
(`Python/blocos.py`). A precisão é a das FFTs da placa; a montagem no PC não soma erro
visível. Medido: FFT de 8192 pontos de uma varredura, acima de 50 dB contra `np.fft`
(`ferramentas/testa_blocos.py --placa`).

---

## 7. O ADC

| medida | valor | condição |
|---|---|---|
| CH0 no terra | 0,0000 V (desvio 0,03 mV) | 24/09/2026 |
| CH0 no 3,3 V da placa | 3,3300 V (desvio 2,6 mV) | 24/09/2026 |
| senoide de 1 kHz, contínua 10 s a 200 kHz | SINAD 56,1 dB, **ENOB 9,03** | 07/10/2026, inclui o gerador |

12 bits ideais dariam ~74 dB. A diferença é ruído do conversor, da placa e do gerador.
Para medir só o ADC, a senoide tem que vir de uma fonte mais limpa que 9 bits.

**Consequência:** um sinal do ADC passa pela FFT da placa sem perder nada que o ADC
tenha medido — o piso da FFT (~92 dB) fica muito abaixo do piso do ADC (~56 dB).

---

## 8. Regras práticas

1. Antes de codificar em Q15.8, olhar `max|entrada| / 32768`. Se for muito menor que
   1, há bits sendo jogados fora — deixe a normalização ligada.
2. Não esperar mais que ~92 dB de SNR de nada que passe pelo IP da FFT.
3. Erro grande e sistemático = escala errada. Erro pequeno e espalhado = quantização,
   e é o piso esperado.
4. Para medir o ADC, use janela Blackman-Harris: com Hann, o vazamento mascara o
   conversor em ~53 dB.

---

## Onde reproduzir

    Python/ferramentas/testa_blocos.py --placa <ip>     FFT longa contra np.fft
    Python/ferramentas/testa_adc.py <ip> senoide        SINAD e ENOB do ADC
