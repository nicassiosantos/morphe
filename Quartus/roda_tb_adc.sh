#!/usr/bin/env bash
# roda_tb_adc.sh -- simula o controlador de captura do ADC (adc_captura.v)
# contra o modelo do LTC2308 do tb_adc_captura.v.
#
# Precisa de: Icarus Verilog (iverilog + vvp). Nao precisa de placa.
#
#   ./roda_tb_adc.sh
#
# Casos: fs maxima (200 kHz), 50 kHz, 1 kHz, divisor abaixo do minimo,
# n = 0, a RAM cheia (32768 amostras) e o modo continuo com a RAM dando a
# volta (a 200 kHz e a 50 kHz, parado no meio de um quadro). Em todos,
# confere o periodo exato entre conversoes, o canal de cada conversao, a
# ordem dos bits e as restricoes de tempo do LTC2308; no continuo, tambem a
# coerencia do contador a cada amostra. Leva perto de 1 minuto.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM="$(mktemp -d)"
trap 'rm -rf "$SIM"' EXIT

iverilog -g2012 -o "$SIM/tb_adc.vvp" "$AQUI/tb_adc_captura.v" "$AQUI/adc_captura.v"
( cd "$SIM" && vvp tb_adc.vvp ) | tee "$SIM/saida.txt"
grep -q "TUDO OK" "$SIM/saida.txt"
