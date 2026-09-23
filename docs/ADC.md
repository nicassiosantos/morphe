# O ADC da DE1-SoC no Morphe

Levantamento de 23/09/2026, lido do código do projeto (`Quartus/ghrd_top.v` e o IP em
`Quartus/adcltc2308_controller/`). O que vem **do código** está dito como fato; o que
vem da **folha de dados ou do manual da placa** está marcado como *a conferir*.

## O que a placa tem

O conversor é o **LTC2308**: 12 bits, 8 canais, aproximação sucessiva, interface
serial (SPI) com quatro fios que chegam ao FPGA — `ADC_CONVST`, `ADC_SCLK`, `ADC_DIN`,
`ADC_DOUT` (`ghrd_top.v:39-42`). As entradas analógicas ficam num conector próprio da
placa. *A conferir no DE1-SoC User Manual: a pinagem do conector e a taxa máxima
(500 mil amostras/s pela folha de dados do LTC2308).*

## Como o controlador do projeto funciona

O projeto traz o **ADC Controller for DE-series Boards** do Intel University Program
(`altera_up_avalon_adc_mega`), gerado para `DE1-SoC`, revisão "F or newer", com dois
parâmetros que decidem tudo: `tsclk = 3` e `numch = 1`
(`adcltc2308_controller/synthesis/adcltc2308_controller.v:24-27`).

Ele **converte sem parar**, sozinho, sem ninguém pedir:

1. Para cada canal, envia ao LTC2308 uma palavra de configuração de 6 bits —
   `{S/D=1, O/S, S1, S0, UNI=1, SLP=0}` —, ou seja, **entrada simples (contra o terra) e
   unipolar**. Com a referência interna de 4,096 V, isso dá **0 a 4,095 V, 1 mV por
   passo** (*faixa a conferir no esquema da placa*). **Tensão negativa não é lida — e
   pode danificar a entrada.**
2. O relógio serial é o de 50 MHz dividido por `tsclk`: **~16,7 MHz**.
3. Entre uma conversão e a seguinte espera `tsclk × 32` ciclos, **1,92 µs**, o tempo
   de conversão do LTC2308.
4. Lê os 12 bits e passa ao canal seguinte, **do 0 até `numch`** — com `numch = 1`, só
   os canais **0 e 1**. Os outros seis saem sempre zero. Usar os oito exige gerar o IP
   de novo no Platform Designer com `numch = 7`.
5. Ao fim de cada volta, copia os resultados para as saídas `CH0`…`CH7` e recomeça.

As saídas são, portanto, **o último valor lido de cada canal**, atualizado a cada
~3 µs por canal (conta a partir do código: ~1 µs de transferência + 1,92 µs de
conversão; *a medir*). Com dois canais, cada um se renova a ~165 mil vezes por
segundo; com oito, a ~40 mil.

**Hoje nada disso está ligado.** A instância está comentada em `ghrd_top.v:571-591`, e
mesmo quando estava ativa só `CH0` ia a algum lugar (os LEDs). Não há caminho até o
processador, operação no protocolo nem nada no cliente.

## O que isso significa para capturar um sinal

Capturar a uma taxa `fs` com esse controlador seria pegar o "último valor" a cada
`1/fs`. O instante real da amostra fica incerto em até uma volta inteira da varredura
(~6 µs com dois canais, ~24 µs com oito), e essa incerteza vira ruído que cresce com a
frequência do sinal. Pela conta usual (erro ≈ 2π · f · Δt), um tom de **1 kHz** ficaria
com relação sinal-ruído de uns **40 dB**, e um de **5 kHz**, com uns **25 dB** — contra
os ~74 dB que 12 bits permitem. *Estimativa, a medir.*

**Consequência para o projeto:** o controlador do University Program serve para ler
tensões (etapa 1), mas **não para capturar sinais** (etapa 2). Para a captura, o certo é
um controlador próprio, pequeno, que dispare o `ADC_CONVST` exatamente a cada `1/fs`, a
partir do relógio de 50 MHz — incerteza de 20 ns em vez de microssegundos.

## Etapas

Cada uma é utilizável por si. A 1 e a 2 exigem compilar um bitstream novo; vão juntas,
numa compilação só, que também tira do projeto os dois arquivos listados e sem uso
(`fft_impulse_test.v`, `output_files/spiral_dft_top.v`).

| etapa | o que é | estado |
|---|---|---|
| 0 | sinal de arquivo (`.csv`, `.txt`, `.npy`, `.wav`) e processamento por blocos — convolução por overlap-add, espectrograma (`Python/blocos.py`, `Python/sinal_arquivo.py`) | **feita e validada na placa em 23/09** (convolução); espectrograma na biblioteca, falta a janela |
| 1 | ADC como voltímetro: reativar o controlador, levar `CH0`…`CH7` ao processador, uma operação no protocolo | guardada |
| 2 | captura a `fs` fixa: controlador próprio + memória de captura no FPGA, operação de captura, janela "Aquisição" que salva em arquivo e alimenta as outras janelas | guardada |
| 3 | codec de áudio WM8731 (entrada e saída de áudio) | opcional |

Memória livre no FPGA para a captura, pelo relatório da última compilação: 232 dos 397
blocos de RAM (~290 KB) — cabe um buffer de 32 a 64 mil amostras de 16 bits.

## Ideias que o ADC abre

- aula de amostragem e aliasing (a placa não tem filtro anti-aliasing antes do ADC);
- analisador de espectro com capturas repetidas;
- medir o próprio ADC (SNR, número efetivo de bits) com uma senoide;
- dois canais: correlação cruzada e estimativa de atraso;
- multitaxa: capturar rápido e dizimar com o FIR;
- com o codec: gravar, filtrar e **ouvir** o resultado; e ligar a saída de áudio na
  entrada do ADC para a plataforma se testar sem gerador de funções.
