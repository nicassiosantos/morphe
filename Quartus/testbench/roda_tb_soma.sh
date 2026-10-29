#!/usr/bin/env bash
# roda_tb_soma.sh -- simula o soma_core.v com os casos da A6 do roteiro
# (docs/roteiro-modulo), antes de compilar. Nao precisa de placa.
#
#   bash Quartus/testbench/roda_tb_soma.sh
#
# Usa o Icarus Verilog (iverilog + vvp) se houver; senao, o ModelSim que vem
# com o Quartus 20.1 (vlog + vsim), que esta nas estacoes do laboratorio mas
# fora do PATH. Termina com TUDO OK.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # os testbenches
RTL="$(cd "$AQUI/.." && pwd)"                          # o RTL, em Quartus/
SIM="$(mktemp -d)"
trap 'rm -rf "$SIM"' EXIT

if command -v iverilog >/dev/null && command -v vvp >/dev/null; then
    iverilog -o "$SIM/tb.vvp" "$AQUI/tb_soma_core.v" "$RTL/soma_core.v"
    ( cd "$SIM" && vvp tb.vvp ) | tee "$SIM/saida.txt"
else
    MS=""
    for d in /opt/intelFPGA_lite/20.1/modelsim_ase/bin "$HOME/intelFPGA_lite/20.1/modelsim_ase/bin"; do
        [[ -x "$d/vsim" ]] && { MS="$d"; break; }
    done
    if [[ -z "$MS" ]]; then
        echo "nem o Icarus (iverilog) nem o ModelSim do Quartus 20.1 foram achados" >&2
        exit 1
    fi
    cd "$SIM"
    "$MS/vlib" work >/dev/null
    "$MS/vlog" -quiet "$RTL/soma_core.v" "$AQUI/tb_soma_core.v"
    "$MS/vsim" -c -quiet tb_soma_core -do "run -all; quit -f" \
        | sed -n 's/^# //p' | grep -E "^(ok|ERRO|TUDO|[0-9]+ ERRO)" | tee "$SIM/saida.txt"
fi
grep -q "TUDO OK" "$SIM/saida.txt"
