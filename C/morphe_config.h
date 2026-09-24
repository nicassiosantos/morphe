/*
 * morphe_config.h -- limites e tamanhos do hardware Morphe (DE1-SoC).
 *
 * PONTO UNICO DE CONFIGURACAO. Espelhe qualquer mudanca aqui no
 * morphe_config.py do cliente Python para manter os dois lados
 * sincronizados.
 *
 * Esses valores refletem o tamanho REAL configurado no Qsys/Quartus:
 *
 *   - FFT IP core (Buffered Burst, N=1024 pontos)
 *     SRAMs xn_re, xn_imag, yn_re, yn_imag dimensionadas para
 *     MORPHE_FFT_N entradas de int32_t cada (= 4 KiB cada).
 *
 *     Hardware: cada palavra usa 24 bits uteis (Q15.8 com sinal,
 *     num[23:0] no Verilog). Os 8 bits altos sao sign-extension do
 *     bit 23 -- usados apenas para que leituras int32_t pelo HPS
 *     deem o valor decimal correto. O IP da FFT ignora bits[31:24].
 *
 *     Software: tudo e tratado como int32_t (com sinal). O cliente
 *     Python codifica/decodifica Q15.8 transparentemente antes de
 *     enviar pelo protocolo Morphe.
 *
 *   - Convolucao 1D: ate MORPHE_CONV_N_MAX amostras Q15.16 por entrada
 *     (x e h), com saida ate 2*N-1 = MORPHE_CONV_Y_MAX amostras.
 *
 * Se voce alterar qualquer numero abaixo, REGENERE hps_0.h a partir
 * do Qsys -- e atualize o morphe_config.py em sequencia.
 */
#ifndef MORPHE_CONFIG_H
#define MORPHE_CONFIG_H

/* ---- FFT --------------------------------------------------------------- */

/* Tamanho fixo da FFT no hardware (Buffered Burst). Deve ser potencia de 2. */
#define MORPHE_FFT_N            1024

/* Largura das amostras da FFT em bits, do ponto de vista do software
 * (C/Python e do protocolo de fio). Cada amostra ocupa um int32_t
 * com sinal -- 4 bytes por valor real, 4 bytes por valor imaginario.
 *
 * No hardware apenas os 24 bits baixos sao usados (formato Q15.8); os
 * 8 bits altos sao sign-extension do bit 23. A reducao para 24 bits
 * e responsabilidade da camada de codificacao no cliente Python. */
#define MORPHE_FFT_DATA_BITS    32

/* Numero de bits fracionarios do formato Q15.8 usado nas SRAMs da FFT.
 * O cliente Python codifica cada amostra real em Q15.8 (1 bit sinal +
 * 15 int + 8 frac = 24 bits uteis em int32_t com sign-extension) antes
 * de enviar. O servidor desfaz essa pre-escala dividindo a saida da
 * FFT por 2^MORPHE_FFT_FRAC_BITS = 256, alem de aplicar o fator BFP. */
#define MORPHE_FFT_FRAC_BITS    8

/* ---- Convolucao 1D ----------------------------------------------------- */

/* Numero maximo de amostras por entrada (x ou h) -- formato Q15.16. */
#define MORPHE_CONV_N_MAX       1024

/* Tamanho maximo do vetor de saida y[n] = x[n] * h[n]. */
#define MORPHE_CONV_Y_MAX       (2 * MORPHE_CONV_N_MAX - 1)  /* = 2047 */

/* Numero de bits fracionarios do formato Q15.16 usado pela conv1d.
 * 16 bits frac = escala de 2^16 = 65536. */
#define MORPHE_CONV_FRAC_BITS   16

/* ---- IIR (cascata de secoes de 2a ordem) ------------------------------- */

/* O iir_cascade processa SEMPRE MORPHE_IIR_N_MAX amostras (N_SAMPLES do
 * Verilog); o servidor completa com zeros o que o cliente nao mandou e
 * devolve so as n_x pedidas. */
#define MORPHE_IIR_N_MAX        1024

/* Secoes de 2a ordem por execucao: 1..MORPHE_IIR_SECOES_MAX (MAX_SECOES
 * do Verilog; o PIO iir_nsecoes tem 5 bits). Ordem maxima 32. */
#define MORPHE_IIR_SECOES_MAX   16

/* Palavras de coeficiente por secao na SRAM iir_coef: b0 b1 b2 a1 a2. */
#define MORPHE_IIR_COEF_POR_SECAO 5

/* Amostras E coeficientes em Q15.16, o mesmo formato da conv1d. */
#define MORPHE_IIR_FRAC_BITS    16

/* ---- ADC (LTC2308, captura a fs fixa pelo adc_captura.v) --------------- */

/* Amostras por captura: a RAM adc_buf tem 2^15 palavras de 32 bits
 * (ADDR_BITS do Verilog). */
#define MORPHE_ADC_N_MAX        32768

/* fs = MORPHE_ADC_CLK_HZ / divisor. O divisor minimo e o DIV_MIN do
 * Verilog (200 kHz); o maximo so limita a duracao (1 kHz: 32768 amostras
 * levam 33 s, e o servidor fica ocupado esse tempo todo). */
#define MORPHE_ADC_CLK_HZ       50000000
#define MORPHE_ADC_DIV_MIN      250
#define MORPHE_ADC_DIV_MAX      50000

/* Palavra de configuracao do LTC2308 (6 bits: S/D O/S S1 S0 UNI SLP). */
#define MORPHE_ADC_CFG_UNI      0x02U   /* 1 = unipolar, 0 = bipolar (compl. de 2) */
#define MORPHE_ADC_CFG_SLP      0x01U   /* sleep: recusado, a referencia leva 200 ms */
/* Bit 6 do PIO adc_config (fora da palavra do LTC2308): captura continua, com a
 * RAM como buffer circular. Quem o liga e o servidor, no OP_ADC_CONTINUO. */
#define MORPHE_ADC_CFG_CONTINUO 0x40U

/* ---- Rede -------------------------------------------------------------- */

/* Porta TCP padrao do servidor (cliente pode sobrescrever). */
#define MORPHE_DEFAULT_PORT     5000

#endif /* MORPHE_CONFIG_H */
