# O ADC da DE1-SoC no Morphe

O que vem **do código** do projeto está dito como fato; o que vem da **folha de dados
ou do manual da placa** está indicado como tal.

## O que a placa tem

O conversor é o **LTC2308**: 12 bits, 8 canais, aproximação sucessiva, interface
serial (SPI) com quatro fios que chegam ao FPGA — `ADC_CONVST`, `ADC_SCLK`, `ADC_DIN`,
`ADC_DOUT` (`ghrd_top.v`). Taxa máxima do conversor: 500 mil amostras/s; o relógio
serial pode ir até 40 MHz.

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
Nas placas do laboratório o J15 aparece girado 180° em relação ao desenho do manual:
identifique os pinos com o multímetro (COM na carcaça da USB: 5 V = pino 1, 0 V =
pino 10).

**Tensão:** a faixa de medida é de **0 a 4,096 V** (referência interna, unipolar;
manual 3.6.12). O limite absoluto do conversor é **de −0,3 V a AVDD + 0,3 V**, com AVDD
= 5 V (folha de dados do LTC2309, a versão I²C do mesmo conversor, com a mesma
entrada analógica). O manual não mostra resistor nem diodo de proteção entre o
conector e o chip. Entre 4,096 V e ~5,3 V a leitura só satura; **abaixo de −0,3 V a
entrada pode ser danificada**. Por isso, no gerador de funções, usar offset DC ≈ 2 V
e amplitude ≤ 2 Vp (4 Vpp), e conferir no osciloscópio antes de ligar.

**Não há filtro anti-aliasing** entre o conector e o conversor: tudo o que chegar ao
pino acima de fs/2 rebate no espectro. Ver "Microfone", abaixo.

**Nome do pino:** a tabela 3-22 do manual chama o pino `PIN_AJ4` de `ADC_CS_N`,
herança das revisões antigas com outro conversor. No LTC2308 esse pino é o `CONVST`,
e o `.qsf` do projeto usa `ADC_CONVST` em `PIN_AJ4`. Os demais pinos batem com o
manual: DIN em AK4, DOUT em AK3, SCLK em AK2.

## Por que um controlador próprio

O controlador do Intel University Program (`altera_up_avalon_adc_mega`) converte em
varredura livre e entrega o **último valor** de cada canal, sem instante de
amostragem definido. Capturar a uma taxa `fs` com ele deixaria o instante real de cada
amostra incerto em até uma volta da varredura (~6 µs com dois canais), e essa
incerteza vira ruído que cresce com a frequência do sinal (erro ≈ 2π · f · Δt): uns
25 dB num tom de 5 kHz, contra os ~74 dB que 12 bits permitem. Por isso o projeto usa
o `adc_captura.v`, que dispara o `ADC_CONVST` exatamente a cada `1/fs`, a partir do
relógio de 50 MHz — incerteza de 20 ns.

## Como funciona

**Hardware: `Quartus/adc_captura.v`.** Um contador de período zera a cada `divisor`
ciclos de 50 MHz, e cada zero dispara uma conversão (subida do `CONVST`). O instante
de amostragem é essa borda. A cada período:

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
silencioso. A placa fica ocupada durante toda a captura.

**Proteção do barramento.** O servidor só usa o ADC se o `hps_0.h` com que foi
compilado tiver a RAM `adc_buf` e os PIOs, e se o timestamp do sysid lido na FPGA for
o do `hps_0.h`. Um bitstream diferente é recusado com mensagem, em vez de travar o
barramento do HPS. O PING informa `adc_n_max = 0` nesse caso.

**Cliente.** `aquisicao.py` concentra as contas: a palavra de configuração, a fs
real, os volts, o voltímetro (média de 0,1 s, que cancela o zumbido de 50 e 60 Hz),
as métricas (SINAD e ENOB com janela Blackman-Harris) e a gravação em .csv, .npy e
.wav. A janela `aquisicao_window.py` aparece no menu como "Aquisição (ADC da placa)".
A última captura vira o tipo **"Captura do ADC"** no painel de sinal da FFT e do
gerador. Para validar na placa com multímetro e gerador, use
`ferramentas/testa_adc.py`.

## Validado na placa

- CH0 no terra: 0,0000 V; CH0 no VCC3P3 (GPIO, pino 29): 3,3300 V; modo diferencial
  CH0−CH1 com a numeração de canais certa.
- Senoide de 1 kHz do gerador no CH0, captura contínua de 10 s a 200 kHz sem perda:
  f = 1000,013 Hz, SINAD 56,1 dB, **ENOB 9,03** (inclui o ruído do gerador).

## Microfone

O conector MIC da placa vai só ao codec de áudio, que esta versão não usa. Para
capturar som pelo ADC, use um módulo de microfone com amplificador (MAX4466 ou
MAX9814) alimentado em **3,3 V**:

| módulo | DE1-SoC |
|---|---|
| VCC | GPIO, pino 29 (3,3 V) |
| GND | J15, pino 10 |
| OUT | J15, pino 2 (CH0) |

Em silêncio a saída fica em ~1,65 V; com som, a onda oscila em torno disso. Ajuste o
ganho no trimpot até a onda não achatar perto de 0 ou de 3,3 V.

Como não há filtro anti-aliasing, capture a 200 kHz: o microfone e o amplificador
praticamente não entregam nada perto de 100 kHz, e quase nada rebate. Para chegar a
uma taxa menor, filtre no digital (passa-baixas abaixo da nova fs/2) e só então
descarte amostras.

## Ideias que o ADC abre

- aula de amostragem e aliasing (a placa não tem filtro anti-aliasing antes do ADC);
- medir o próprio ADC (SNR, número efetivo de bits) com uma senoide e a FFT;
- espectro de um sinal real: capturar e mandar para a janela da FFT;
- dois canais: correlação cruzada e estimativa de atraso.
