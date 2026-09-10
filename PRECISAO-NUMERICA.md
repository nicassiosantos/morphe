# Precisão numérica do Morphe — fatos medidos

Consequências numéricas das operações neste hardware. Só o que foi medido
ou lido no código, com a fonte ao lado. Versão curta e direta; uma versão
detalhada virá depois.

Última medição: 10/09/2026, DE1-SoC, bitstream `soc_system_time_limited.sof`.

---

## 1. Existem DOIS formatos de ponto fixo, em caminhos diferentes

| caminho | formato | passo | faixa | onde |
|---|---|---|---|---|
| FFT e IFFT | **Q15.8** (24 bits) | 2⁻⁸ = 1/256 | ±32768 | `morphe_config.h:51` |
| conv1d e FIR | **Q15.16** (32 bits) | 2⁻¹⁶ ≈ 1,5e-5 | ±32768 | `morphe_config.h:63` |

Não confundir. A FFT usa Q15.8 porque a SRAM entrega `sink_real[23:0]` ao
IP da Altera: 24 bits, sobram 8 fracionários depois do sinal e dos 15
inteiros. O conv1d é multiplicador próprio e usa 32 bits.

Codificação: `q = round(v · 2^frac)`, saturando na faixa.
Python: `dsp_core.fft_q1508_encode` e `dsp_core.float_to_q1516`.

---

## 2. A regra que governa tudo: 6,02 dB por bit

Erro de arredondamento uniforme em [-Δ/2, +Δ/2], variância Δ²/12.

Multiplicar o sinal por `s` antes de codificar e dividir por `s` depois
faz o passo efetivo virar Δ/s:

    ganho = 20·log10(s)        dobrar s = 6,02 dB = 1 bit

Exato, não aproximado: DFT e IDFT são lineares, então `IDFT(s·X)/s` é o
mesmo valor matemático com menos erro de quantização.

O ganho disponível é o que sobra de faixa não usada:

    ganho_max = 6,02 · log2( 32768 / max|entrada| )

**Consequência:** mandar um sinal de amplitude 3 numa faixa que vai a
32768 joga fora ~13 bits.

---

## 3. Medido na placa: varredura de escala na FFT direta

Mesmo sinal (pico 3,3), amplitudes diferentes, escala desfeita na volta,
comparado com `np.fft.fft`:

| escala | pico de x | SNR | ganho |
|---:|---:|---:|---:|
| 1 | 3,3 | 50,42 dB | — |
| 4 | 13,2 | 62,74 dB | +12,32 |
| 16 | 52,8 | 75,07 dB | +24,65 |
| 64 | 211,1 | 86,64 dB | +36,22 |
| 256 | 844,3 | 91,74 dB | +41,33 |
| 1024 | 3377,3 | 91,66 dB | +41,24 |
| 4096 | 13509,1 | 91,55 dB | +41,13 |

De 1 para 64 são 6 bits: teoria 36,12 dB, medido 36,22 dB. A fórmula
fecha com o hardware.

**Teto medido: ~92 dB.** Acima de escala 256 não ganha mais nada. Ali o
limite deixa de ser o Q15.8 da entrada e passa a ser a aritmética interna
do IP (twiddles de 18 bits, saída de 24 com expoente compartilhado).

**Consequência:** normalizar a entrada da FFT rende ~41 dB neste caso,
não os 80 dB que a conta dos 13 bits sugeriria. O teto do IP corta antes.

---

## 4. O que hoje normaliza e o que não normaliza

| operação | normaliza a entrada? | SNR medido |
|---|---|---|
| FFT direta | **não** — manda x[n] como está | 43,9 a 50,4 dB |
| IFFT | sim, em `build_ifft_request` | 92 a 94,4 dB |

A IFFT normaliza porque o espectro é o caso pior:

    |X[k]| ≤ Σ|x[n]| ≤ N · max|x|        N=1024 -> +60,2 dB

O mesmo sinal que cabe folgado no tempo pode ser 1024 vezes maior na
frequência. E ao mesmo tempo os bins pequenos caem abaixo de Δ/2 = 1/512
e viram **exatamente zero**. Satura em cima, some embaixo.

Sem normalizar, um espectro 1e-4 vezes menor volta com erro 2,7e-03; com
ela, 5,9e-08.

Quando o espectro já é grande a normalização rende pouco: com pico 1280,
só +1,5 dB. Ela é decisiva para espectros pequenos.

**Pendência conhecida:** aplicar o mesmo padrão à FFT direta. É o que
explica a diferença de ~50 dB entre as duas travessias.

---

## 5. Como o IP normaliza por dentro (Block Floating Point)

O IP da FFT é *Buffered Burst*, *Quad Output*, N=1024, entrada de 24 bits,
twiddles de 18 (`Quartus/fft_core/fft_core.xml`).

A cada estágio radix-4 (5 estágios, 1024 = 4⁵) ele detecta crescimento,
desloca as 1024 amostras **juntas** e acumula um expoente:

    y_real = y_raw · 2^(-exp)      um único exp para o bloco inteiro

Caminho do expoente:

    fft_wrapper.v:178   captura source_exp (6 bits) no source_sop
                        -> PIO fft_bfp_exponent
    morphe_server.c     bfp_scale   = ldexpf(1.0f, -bfp_exp)
                        total_scale = bfp_scale / 256

**Duas consequências:**

1. O BFP **não** recupera o que morreu na entrada. O que ficou abaixo de
   1/512 já era zero antes de o IP existir. Por isso escalar a entrada
   ainda rende 6 dB por bit.
2. O expoente é **compartilhado** pelo bloco. Bins muito abaixo do pico
   carregam menos bits efetivos, porque o deslocamento foi ditado pelo
   maior. É isso, com os twiddles de 18 bits, que põe o teto em ~92 dB.

Normalização do cliente e BFP do IP resolvem problemas diferentes: a
primeira posiciona o sinal **antes** de virar 24 bits; o segundo evita
overflow **durante** a transformada. Nenhum substitui o outro.

---

## 6. A IFFT não aplica o 1/N

O IP entrega a inversa **não normalizada**: a saída é N vezes a IDFT
matemática. O cliente aplica o fator.

    IFFT_HW_GAIN = 1.0 / FFT_N      morphe_config.py

Medido: mandando x[n] real com `inverse=1`, o que volta tem a MESMA
magnitude da DFT (|Y|/|DFT(x)| = 1,00031). Como para x real vale
IDFT(x) = conj(DFT(x))/N, a ausência do fator N é a prova.

Confirmado por um terceiro caminho: o `idft.m` do Prof. Sanca (DSPFinal)
usa a convenção com 1/N, igual ao NumPy, e bate com a FPGA a 2,5e-05.

---

## 7. Erros medidos, para referência rápida

| medida | valor | condição |
|---|---|---|
| ida e volta FFT→IFFT | 9,5e-04 relativo | piso do Q15.8 do espectro |
| IFFT isolada x NumPy | 2,5e-05 (94,4 dB) | espectro de arquivo |
| FFT isolada x NumPy | 5,0e-03 (43,9 dB) | sem normalizar a entrada |
| `idft.m` x `np.fft.ifft` | 7,9e-14 | ambos em double |
| vazamento imaginário, IFFT de espectro hermitiano | 0 exato | vs 2,5e-13 do idft.m |
| coeficientes FIR, float x Q15.16 | ≤ 7,6e-06 | metade do passo 1,5e-5 |

**Consequência:** o erro do ida e volta nunca vai a zero. O piso é o
Q15.8 do espectro, ordem de 1e-3 relativo. Não adianta procurar bug ali.

---

## 8. Regras práticas

1. Antes de codificar em Q15.8, olhar `max|entrada| / 32768`. Se for
   muito menor que 1, há bits sendo jogados fora.
2. Normalizar sempre que a operação seguinte for linear — a escala se
   desfaz exatamente. Guardar a escala e desfazê-la na volta.
3. Não esperar mais que ~92 dB de SNR de nada que passe pelo IP da FFT.
4. Um espectro **não** pode ser preenchido com zeros como um sinal no
   tempo: isso mudaria o sinal que ele representa. Por isso a IFFT recusa
   N ≠ 1024 em vez de fazer padding.
5. Erro grande e sistemático = escala errada. Erro pequeno e espalhado =
   quantização, e é o piso esperado.

---

## Onde reproduzir

    Python/testa_bit_inverse.py      <ip>    bit inverse + convenção 1/N
    Python/testa_ifft_roundtrip.py   <ip>    ida e volta, 3 verificações

Ver também `RESSALVAS.md` item 17 (histórico da IFFT) e item 13 (tempo de
resposta como indicador de saúde do core).
