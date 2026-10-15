#!/usr/bin/env bash
# roda_tb_conv.sh -- simula o conv1d.v (convolucao e FIR) contra a conta exata,
# com N = 16 e com N = 1024 (o tamanho da placa). Confere o arredondamento na
# saida, amostra a amostra, e mostra o erro que o truncamento antigo daria.
#
# Precisa de: Icarus Verilog (iverilog + vvp). Nao precisa de placa.
#
#   ./roda_tb_conv.sh
#
# Os memory_*_controller.v escrevem literais como 1'b_0, que o Quartus aceita e
# o Icarus nao: a simulacao usa copias com 1'b0, numa pasta temporaria. Os
# originais nao sao tocados. Leva perto de 1 minuto.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # os testbenches
RTL="$(cd "$AQUI/.." && pwd)"                          # o RTL, em Quartus/
SIM="$(mktemp -d)"
trap 'rm -rf "$SIM"' EXIT

for f in memory_read_controller.v memory_write_controller.v; do
    sed "s/'b_/'b/g" "$RTL/$f" > "$SIM/$f"
done

for n in 16 1024; do
    iverilog -g2012 -DN=$n -o "$SIM/tb_conv.vvp" "$AQUI/tb_conv1d.v" "$RTL/conv1d.v" \
        "$SIM/memory_read_controller.v" "$SIM/memory_write_controller.v"
    ( cd "$SIM" && vvp tb_conv.vvp ) | tee "$SIM/saida.txt"
    grep -q "TUDO OK" "$SIM/saida.txt"
done
