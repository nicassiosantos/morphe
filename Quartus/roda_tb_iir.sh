#!/usr/bin/env bash
# roda_tb_iir.sh -- gera os vetores e simula o bloco IIR nos tres casos.
#
# Precisa de: Icarus Verilog (iverilog + vvp) e o venv do cliente Python.
#
#   ./roda_tb_iir.sh
#
# Casos:
#   normal      uma secao, sinal dentro da faixa      -> error_sat = 0
#   saturacao   uma secao, batendo na ressonancia     -> error_sat = 1
#   cascata     11 secoes (Butterworth de ordem 22)   -> o caso mais duro
#
# Em todos, a saida do RTL e comparada BIT A BIT com o modelo em Python
# (Python/iir_design.py, filtra_sos_fixo). Num filtro realimentado,
# divergir um LSB numa amostra e divergir para sempre a partir dali --
# entao "parecido" nao serve como criterio.
#
# Por que existe a copia higienizada: o memory_read_controller.v e o
# memory_write_controller.v usam a forma 1'b_0, com underscore logo depois
# do especificador de base. O Quartus aceita; o Icarus, nao -- nao e
# Verilog padrao. Esses dois arquivos fazem parte de um bitstream ja
# sintetizado e validado em hardware, entao NAO sao alterados aqui: a
# simulacao trabalha sobre copias corrigidas, em diretorio temporario.
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
cp "$AQUI/iir_sos.v" "$AQUI/iir_cascade.v" "$AQUI/iir_biquad_mac.v" \
   "$AQUI/tb_iir_sos.v" "$AQUI/tb_iir_cascade.v" "$SIM/"

MEM="$SIM/memory_read_controller.v $SIM/memory_write_controller.v"

iverilog -g2012 -o "$SIM/tb_sos.vvp" \
    "$SIM/tb_iir_sos.v" "$SIM/iir_sos.v" "$SIM/iir_biquad_mac.v" $MEM

iverilog -g2012 -o "$SIM/tb_casc.vvp" \
    "$SIM/tb_iir_cascade.v" "$SIM/iir_cascade.v" "$SIM/iir_biquad_mac.v" $MEM

falhou=0
for caso in normal saturacao cascata; do
    echo
    echo "###########################################################"
    echo "# CASO: $caso"
    echo "###########################################################"
    ( cd "$PY" && "$PYTHON" gera_vetores_iir.py "$caso" "$SIM" )

    if [ "$caso" = "cascata" ]; then
        VVP="tb_casc.vvp"
    else
        VVP="tb_sos.vvp"
    fi

    ( cd "$SIM" && vvp "$VVP" ) | tee "$SIM/saida_$caso.txt" || falhou=1
    grep -q "BIT A BIT IGUAL" "$SIM/saida_$caso.txt" || falhou=1
done

echo
if [ "$falhou" -eq 0 ]; then
    echo "TUDO OK: o RTL reproduz o modelo em Python bit a bit nos 3 casos."
else
    echo "FALHOU: ver a saida acima."
fi
exit "$falhou"
