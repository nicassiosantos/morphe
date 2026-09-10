#!/usr/bin/env bash
# roda_tb_iir.sh -- gera os vetores e simula o biquad nos dois casos.
#
# Precisa de: Icarus Verilog (iverilog + vvp) e o venv do cliente Python.
#
#   ./roda_tb_iir.sh
#
# Por que existe a copia higienizada: o memory_read_controller.v e o
# memory_write_controller.v usam a forma 1'b_0, com underscore logo
# depois do especificador de base. O Quartus aceita; o Icarus, nao --
# nao e Verilog padrao. Esses dois arquivos fazem parte de um bitstream
# ja sintetizado e validado em hardware, entao NAO sao alterados aqui:
# a simulacao trabalha sobre copias corrigidas, em diretorio temporario.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$AQUI/../Python"
SIM="$(mktemp -d)"
trap 'rm -rf "$SIM"' EXIT

if [ -x "$PY/.venv/Scripts/python.exe" ]; then
    PYTHON="$PY/.venv/Scripts/python.exe"      # Windows
elif [ -x "$PY/.venv/bin/python" ]; then
    PYTHON="$PY/.venv/bin/python"              # Linux
else
    PYTHON="python3"
fi

for f in memory_read_controller.v memory_write_controller.v; do
    sed "s/'b_/'b/g" "$AQUI/$f" > "$SIM/$f"
done
cp "$AQUI/iir_sos.v" "$AQUI/tb_iir_sos.v" "$SIM/"

iverilog -g2012 -o "$SIM/tb.vvp" \
    "$SIM/tb_iir_sos.v" "$SIM/iir_sos.v" \
    "$SIM/memory_read_controller.v" "$SIM/memory_write_controller.v"

falhou=0
for caso in normal saturacao; do
    echo
    echo "###########################################################"
    echo "# CASO: $caso"
    echo "###########################################################"
    ( cd "$PY" && "$PYTHON" gera_vetores_iir.py "$caso" "$SIM" )
    if ! ( cd "$SIM" && vvp tb.vvp ) | tee "$SIM/saida_$caso.txt"; then
        falhou=1
    fi
    if ! grep -q "BIT A BIT IGUAL" "$SIM/saida_$caso.txt"; then
        falhou=1
    fi
done

echo
if [ "$falhou" -eq 0 ]; then
    echo "TUDO OK: o RTL reproduz o modelo em Python bit a bit nos dois casos."
else
    echo "FALHOU: ver a saida acima."
fi
exit "$falhou"
