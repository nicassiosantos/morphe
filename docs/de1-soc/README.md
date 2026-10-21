# Documentação da placa DE1-SoC (Terasic)

Manuais e folhas de dados oficiais da placa usada no laboratório. Tirados dos System CDs
da Terasic (<https://download.terasic.com/downloads/cd-rom/de1-soc/>) em 13/10/2026:
`DE1-SoC_v.5.1.3_HWrevF.revG_SystemCD.zip` e `DE1-SoC_v.6.0.0_HWrevH_SystemCD.zip`.

| arquivo | o que é |
|---|---|
| `DE1-SoC_User_manual_revH.pdf` | manual da placa, v3.0.1 (09/01/2022), revisão H do hardware |
| `DE1-SoC_User_manual_revF-G.pdf` | manual da placa, v2.0.4 (28/01/2019), revisões F e G |
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

Para o Morphe as três revisões são iguais. FPGA, pinos, ADC e HPS não mudaram, e a
seção 3.6.12 (ADC) é a mesma nos dois manuais. A rev. H só acrescenta a SW17, a QSPI
e o CP2105.

## Onde está cada coisa no manual (rev. H)

- 3.1 e 3.2: chave SW10 (modo de configuração) e JTAG.
- 3.6.12: ADC e conector de 2x5 (pinagem, faixa de tensão, pinos no FPGA).
- 3.6.3: conectores GPIO de 2x20 (o pino 29 dá 3,3 V, o 11 dá 5 V; 12 e 30 são terra).

## O ADC no Morphe

Como o conversor é usado, a pinagem do J15 conferida nas placas e as medidas estão em
`docs/ADC.md`.
