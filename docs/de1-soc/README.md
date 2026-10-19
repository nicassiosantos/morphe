# Documentação da placa DE1-SoC (Terasic)

Manuais e folhas de dados oficiais da placa usada no laboratório. Tirados dos System CDs
da Terasic (<https://download.terasic.com/downloads/cd-rom/de1-soc/>) em 13/10/2026:
`DE1-SoC_v.5.1.3_HWrevF.revG_SystemCD.zip` e `DE1-SoC_v.6.0.0_HWrevH_SystemCD.zip`.

| arquivo | o que é |
|---|---|
| `DE1-SoC_User_manual_revH.pdf` | manual da placa, v3.0.1 (09/01/2022), revisão H do hardware |
| `DE1-SoC_User_manual_revF-G.pdf` | manual da placa, v2.0.4 (28/01/2019), revisões F e G |
| `WM8731.pdf` | codec de áudio (Wolfson, hoje Cirrus Logic) — idêntico nos dois CDs |
| `LTC2308.pdf` | ADC de 8 canais e 12 bits do conector de 2x5 — idêntico nos dois CDs |

## Qual é a placa do laboratório

**Terasic DE1-SoC**, com FPGA Cyclone V SoC **5CSEMA5F31C6N** (HPS ARM Cortex-A9 de dois
núcleos). As placas antes da revisão F tinham o ADC AD7928 e usam outro manual (o "revE").
Para não confundir com elas, olhe o chip do ADC.

| como reconhecer | rev. F/G | rev. H |
|---|---|---|
| ADC (chip ao lado do conector de 2x5) | LTC2308 | LTC2308 |
| conversor USB-serial (porta UART-to-USB) | FTDI FT232R (VID 0403) | Silicon Labs CP2105 (VID 10C4, PID EA70) |
| chave SW17 (JTAG: FPGA x RISC-V) | não tem | tem |
| memória flash QSPI | não tem | tem |

- **Placa 2** (`de1soc-02`, 172.16.230.52): **rev. H**. A serial dela aparece no Windows como
  CP2105 (VID 10C4, PID EA70), e esse chip só existe na rev. H.
- **Placa 1** (`de1soclinux`, 172.16.230.24): também é **rev. H**. A serial dela apareceu
  no Windows como CP2105 em 13/10/2026.

Para o Morphe as três revisões são iguais. FPGA, pinos, codec, ADC e HPS não mudaram, e a
seção 3.6.4 (codec) é a mesma nos dois manuais. A rev. H só acrescenta a SW17, a QSPI
e o CP2105.

## Onde está cada coisa no manual (rev. H)

- 3.1 e 3.2: chave SW10 (modo de configuração) e JTAG.
- 3.6.4: codec de áudio WM8731. 3.6.5: multiplexador de I2C.
- 3.6.12: ADC e conector de 2x5. 3.6.3: conectores GPIO de 2x20.
- 5.2: exemplo "Audio Recording and Playing". 5.3: "Karaoke Machine". 6.x: "I2C MUX test" (HPS).

## Codec de áudio WM8731: como funciona

O chip tem **dois conversores sigma-delta estéreo**: um ADC (entrada) e um DAC (saída).
Há três conectores P2 de 3,5 mm: **MIC-in** (o rosa, segundo o manual), **LINE-in** e
**LINE-out**. Funciona de 8 a 96 kHz, com palavras de 16, 20, 24 ou 32 bits. A SNR do ADC é de
90 dB (ponderação A) e a do DAC, de 100 dB. O fundo de escala da LINE-in é 1,0 V rms.

São duas interfaces separadas:

1. **Controle por I2C** (endereço de 7 bits `0x1A`, ou `0x34` com o bit de escrita). Cada
   escrita leva 16 bits: 7 de registrador e 9 de dado. Há 11 registradores, todos só de
   escrita: volumes (R0 a R3), caminho analógico (R4: MIC ou LINE, bypass, DAC ligado),
   caminho digital (R5: filtro passa-altas, de-ênfase, mute), alimentação (R6), formato da
   interface (R7: I2S, bits, mestre ou escravo), taxa de amostragem (R8), ativo (R9) e
   reset (R15).
2. **Dados por I2S**, nos pinos `AUD_BCLK` (relógio de bit), `AUD_ADCLRCK`/`AUD_DACLRCK`
   (relógio de quadro: diz se é o canal esquerdo ou o direito), `AUD_ADCDAT` (codec →
   FPGA) e `AUD_DACDAT` (FPGA → codec). Além disso, o codec precisa de um relógio-mestre
   em `AUD_XCK`, que a FPGA gera por PLL: 12,288 MHz (256·fs a 48 kHz) ou 18,432 MHz
   (384·fs, o valor do exemplo da Terasic).

**O I2C passa por um multiplexador.** O barramento do codec (e do decodificador de TV)
pode ser controlado pela FPGA (`FPGA_I2C_SCLK`/`FPGA_I2C_SDAT`, PIN_J12/PIN_K12) ou pelo
HPS (controlador I2C0). Quem escolhe é o pino `HPS_I2C_CONTROL`, o GPIO48 do HPS (bit 19 do
GPIO1). Com ele em 1, o HPS tem o barramento.

**Pinos (iguais em `Quartus/soc_system.qsf`):** AUD_ADCDAT K7, AUD_ADCLRCK K8, AUD_BCLK H7,
AUD_DACDAT J7, AUD_DACLRCK H8, AUD_XCK G7, FPGA_I2C_SCLK J12, FPGA_I2C_SDAT K12. A tabela
3-13 do manual sai embaralhada quando o PDF é convertido em texto. Para conferir, use a
figura do PDF ou o `.qsf`.

**Sequência de configuração do exemplo da Terasic** (`DE1_SoC_Audio/software/AUDIO.c`):
R15=0x000 (reset) → R9=0x000 (inativo) → R0/R1=0x017 (volume da LINE-in) →
R2/R3=0x05B (volume do fone) → R4=0x015 (MIC com ganho extra, DAC ligado) →
R5=0x000 (sem mute) → R7=0x042 (I2S, 16 bits, **codec mestre**) → R8=0x002 (normal,
BOSR=1, 48 kHz) → R9=0x001 (ativo).

### Diferenças em relação ao ADC LTC2308 que o Morphe já usa

| | LTC2308 (conector 2x5) | WM8731 (codec) |
|---|---|---|
| tipo | SAR, 12 bits, 8 canais | sigma-delta, até 24 bits, 2 canais |
| acoplamento | DC, de 0 a 4,096 V | **AC** (não mede tensão contínua) |
| filtro anti-aliasing | **não tem** | tem (filtro digital de dizimação) |
| taxa | qualquer, até 500 kHz | só as taxas fixas do chip, de 8 a 96 kHz |
| saída analógica | não tem | **tem** (DAC + LINE-out) |

### Etapas 1 e 2 (branch `estagio/v1.8-codec`, 13/10/2026; ainda sem teste na placa)

- `C/codec.c` (`make codec`): configura o codec pelo HPS. `./codec detecta`,
  `./codec bypass` (etapa 1, sem FPGA), `./codec digital` (etapa 2), `./codec desliga`.
- `Quartus/audio_i2s.v`: AUD_XCK = 12,5 MHz (fs = 48 828,125 Hz), recepção e envio
  I2S, com SW9 baixa = loopback LINE-in → FPGA → LINE-out e SW9 alta = tom de 1017 Hz.
  Simulado em `Quartus/testbench/tb_audio_i2s.v`: TUDO OK.

### Estado no Morphe antes das etapas (13/10/2026)

Os pinos do codec estão **declarados** no `Quartus/ghrd_top.v` (linhas 45 a 50 e 81 e 82)
e atribuídos no `.qsf`, mas **nada os usa**. O bitstream não tem PLL de áudio, nem
controlador I2S, nem FIFO, e não há opcode no servidor. O HPS já tem o I2C0 e o GPIO48
roteados no topo (`ghrd_top.v`, linhas 1077, 1078 e 1086). Então a **configuração** do codec
poderia ser feita pelo Linux da placa, sem recompilar. Já os **dados de áudio** só passam
pela FPGA e exigem RTL novo (PLL, I2S e memória ou FIFO), no mesmo molde da captura do ADC
(`Quartus/adc_captura.v`). Ver `docs/ADC.md`, etapa 3.
