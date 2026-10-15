#!/usr/bin/env bash
# roda_tb_filtro_audio.sh -- simula o filtro em tempo real do audio
# (filtro_audio.v) contra o modelo em ponto fixo do Python, bit a bit.
#
# Precisa de: Icarus Verilog (iverilog + vvp) e Python 3 com numpy e scipy.
# Nao precisa de placa.
#
#   ./roda_tb_filtro_audio.sh
#
# Casos: passa-baixas, passa-altas, passa-faixa, 16 secoes (o maximo),
# 0 secoes (passa direto) e saturacao da saida int16.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # os testbenches
RTL="$(cd "$AQUI/.." && pwd)"                          # o RTL, em Quartus/
PY="$(cd "$RTL/../Python" && pwd)"
SIM="$(mktemp -d)"
trap 'rm -rf "$SIM"' EXIT
PYTHON="${PYTHON:-python3}"

falhas=0
for caso in passa_baixas passa_altas passa_faixa maximo direto satura; do
    "$PYTHON" "$PY/ferramentas/gera_vetores_filtro_audio.py" "$caso" "$SIM" > "$SIM/gera.txt"
    read -r nsec namostras < "$SIM/fa_n.txt"
    iverilog -g2012 -DNSEC="$nsec" -DNAMOSTRAS="$namostras" -o "$SIM/tb.vvp" \
        "$AQUI/tb_filtro_audio.v" "$RTL/filtro_audio.v" "$RTL/iir_biquad_mac.v"
    printf '%-13s ' "$caso:"
    ( cd "$SIM" && vvp -n tb.vvp ) | grep -E "TUDO OK|FALHOU|ERRO" | tee "$SIM/saida.txt"
    grep -q "TUDO OK" "$SIM/saida.txt" || falhas=$((falhas + 1))
done
(( falhas == 0 )) && echo "TODOS OS CASOS OK" || { echo "$falhas caso(s) falharam"; exit 1; }
