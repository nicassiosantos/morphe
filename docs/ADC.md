# O ADC da DE1-SoC no Morphe

Levantamento de 23/09/2026, lido do código do projeto (`Quartus/ghrd_top.v` e o IP em
`Quartus/adcltc2308_controller/`). O que vem **do código** está dito como fato; o que
vem da **folha de dados ou do manual da placa** está marcado como *a conferir*.

## O que a placa tem

O conversor é o **LTC2308**: 12 bits, 8 canais, aproximação sucessiva, interface
serial (SPI) com quatro fios que chegam ao FPGA — `ADC_CONVST`, `ADC_SCLK`, `ADC_DIN`,
`ADC_DOUT` (`ghrd_top.v:39-42`). Taxa máxima: 500 mil amostras/s; o relógio serial
pode ir até 40 MHz.

**Conector J15 (2x5), conferido no DE1-SoC User Manual, seção 3.6.12 e fig. 5-20
(rev. de 28/01/2019):**

| pino | sinal | pino | sinal |
|---|---|---|---|
| 1 | **VCC5 (5 V)** | 2 | ADC_IN0 |
| 3 | ADC_IN1 | 4 | ADC_IN2 |
| 5 | ADC_IN3 | 6 | ADC_IN4 |
| 7 | ADC_IN5 | 8 | ADC_IN6 |
| 9 | ADC_IN7 | 10 | **GND** |

O pino 1 fica no canto marcado (ilhota quadrada). Ele fornece 5 V; ligá-lo por
engano a um canal satura a leitura, e ligá-lo ao terra põe a alimentação em curto.

**Tensão:** a faixa de medida é de **0 a 4,096 V** (referência interna, unipolar;
manual 3.6.12). O limite absoluto do conversor é **de −0,3 V a AVDD + 0,3 V**, com AVDD
= 5 V. Os valores vêm da folha de dados do LTC2309, a versão I²C do mesmo conversor,
com a mesma entrada analógica. O manual não mostra resistor nem diodo de proteção
entre o conector e o chip. Entre 4,096 V e ~5,3 V a leitura só satura; **abaixo de
−0,3 V a entrada pode ser danificada**. Por isso, no gerador de funções, usar offset
DC ≈ 2 V e amplitude ≤ 2 Vp (4 Vpp), e conferir no osciloscópio antes de ligar.

**Nome do pino:** a tabela 3-22 do manual chama o pino `PIN_AJ4` de `ADC_CS_N`,
herança das revisões antigas com outro conversor. No LTC2308 esse pino é o `CONVST`,
e o `.qsf` do projeto já usa `ADC_CONVST` em `PIN_AJ4`. Os demais pinos batem com o
manual: DIN em AK4, DOUT em AK3, SCLK em AK2.

## Como o controlador do projeto funciona

O projeto traz o **ADC Controller for DE-series Boards** do Intel University Program
(`altera_up_avalon_adc_mega`), gerado para `DE1-SoC`, revisão "F or newer", com dois
parâmetros que decidem tudo: `tsclk = 3` e `numch = 1`
(`adcltc2308_controller/synthesis/adcltc2308_controller.v:24-27`).

Ele **converte sem parar**, sozinho, sem ninguém pedir:

1. Para cada canal, envia ao LTC2308 uma palavra de configuração de 6 bits —
   `{S/D=1, O/S, S1, S0, UNI=1, SLP=0}` —, ou seja, **entrada simples (contra o terra) e
   unipolar**. Com a referência interna de 4,096 V, isso dá **0 a 4,095 V, 1 mV por
   passo** (confirmado no manual da placa). **Tensão negativa não é lida — e
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

Esse IP nunca foi ligado no Morphe: a instância ficava comentada no `ghrd_top.v`, e
só `CH0` ia a algum lugar (os LEDs). Em 24/09/2026 ela foi substituída pelo
controlador próprio descrito abaixo.

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
| 0 | sinal de arquivo (`.csv`, `.txt`, `.npy`, `.wav`) e processamento por blocos em todas as janelas — convolução e FIR por overlap-add, FFT e IFFT longas em quatro passos, IIR com aquecimento (`Python/blocos.py`, `Python/sinal_arquivo.py`) | **feita e validada na placa em 23/09**; a janela de espectrograma existe mas está fora do menu (comentada no `morphe_app.py`) |
| 1 | ADC como voltímetro: média de 0,1 s de captura, na janela "Aquisição" | **escrita e verificada em simulação (24/09); falta compilar e validar na placa** |
| 2 | captura a `fs` fixa: controlador próprio + memória de captura no FPGA, `OP_ADC`, janela "Aquisição" que salva em arquivo e alimenta as outras janelas | **escrita e verificada em simulação (24/09); falta compilar e validar na placa** |
| 3 | codec de áudio WM8731 (entrada e saída de áudio) | opcional |

O voltímetro não usa hardware separado. Ele é uma captura curta (2000 amostras a
20 kHz) cuja média cancela o zumbido da rede, porque 0,1 s tem um número inteiro de
ciclos de 50 Hz e de 60 Hz. Assim, as etapas 1 e 2 usam o mesmo caminho e a mesma
compilação. O passo a passo da estação está em `docs/COMPILAR-ADC.md`.

Memória livre no FPGA para a captura, pelo relatório da última compilação: 232 dos 397
blocos de RAM (~290 KB) — cabe um buffer de 32 a 64 mil amostras de 16 bits.

## Como ficou implementado (24/09/2026)

**Hardware: `Quartus/adc_captura.v`.** Um contador de período zera a cada `divisor`
ciclos de 50 MHz, e cada zero dispara uma conversão (subida do `CONVST`). O instante
de amostragem é essa borda, sem varredura. A cada período acontece:

- `CONVST` fica alto por 96 ciclos (1,92 µs, acima do tempo máximo de conversão);
- o SCLK roda a 12,5 MHz: 12 pulsos leem B11..B0 do SDO, e nos seis primeiros sai
  pelo SDI a palavra de configuração;
- a amostra vai para a RAM `adc_buf`, com 32768 palavras.

O primeiro quadro de cada captura é descartado, porque a palavra de configuração vale
para a conversão seguinte. As convenções do barramento serial são as mesmas do IP do
University Program (SCLK parado em 0, SDI muda na descida e SDO é lido antes da
subida). A fs máxima é 200 kHz (`DIV_MIN` = 250): o quadro ocupa ~150 ciclos, e o
resto garante o tempo de aquisição.

| parâmetro | valor |
|---|---|
| fs | 50 MHz / divisor, de 1 kHz a 200 kHz; exata quando o divisor é inteiro (44,1 kHz vira 44 091,7 Hz) |
| amostras por captura | 1 a 32768 de uma vez; acima disso, ou sem limite, captura contínua em blocos |
| modos oferecidos | simples (CH0..CH7, 0 a 4,095 V) e diferencial (pares CH0−CH1..CH6−CH7, ±2,048 V) |
| resolução | 1 mV por código nos dois modos |

**Protocolo: `OP_ADC` = 7, só cabeçalho.** `n_x` = amostras, `n_h` = divisor e
`flags` = palavra de configuração. A resposta traz os códigos em int32 (com o sinal
já estendido no modo bipolar), e `extra` = divisor usado.

**Captura contínua: `OP_ADC_CONTINUO` = 8.** É para sinais maiores que a RAM ou
sem limite (`n_x` = 0, até o cliente parar). O bit 6 do PIO `adc_config` faz a RAM
virar um buffer circular. O PIO `adc_contador` diz quantas amostras já estão nela
e vale 0 em repouso. O servidor copia as novas e manda blocos
`[n, estado, n × int32]` enquanto a captura segue. Os blocos são contínuos no
tempo: nada para entre um e outro. Se o servidor não acompanhar (mais de 164 ms de
atraso a 200 kHz), a captura termina com o estado "perdeu", nunca com buraco
silencioso. A placa fica ocupada durante toda a captura. Detalhes em
`docs/COMPILAR-ADC.md`.

**Cliente.** `aquisicao.py` concentra as contas: a palavra de configuração, a fs
real, os volts, o voltímetro, as métricas (SINAD e ENOB com janela Blackman-Harris) e
a gravação em .csv, .npy e .wav. A janela `aquisicao_window.py` aparece no menu como
"Aquisição (ADC da placa)". A última captura vira o tipo **"Captura do ADC"** no
painel de sinal de todas as janelas. Para validar na placa com multímetro e gerador,
use `ferramentas/testa_adc.py`.

## Ideias que o ADC abre

- aula de amostragem e aliasing (a placa não tem filtro anti-aliasing antes do ADC);
- analisador de espectro com capturas repetidas;
- medir o próprio ADC (SNR, número efetivo de bits) com uma senoide;
- dois canais: correlação cruzada e estimativa de atraso;
- multitaxa: capturar rápido e dizimar com o FIR;
- com o codec: gravar, filtrar e **ouvir** o resultado; e ligar a saída de áudio na
  entrada do ADC para a plataforma se testar sem gerador de funções.
