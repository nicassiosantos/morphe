#!/usr/bin/env bash
# gera_proveniencia.sh -- reescreve o PROVENIENCIA.sha256 a partir do que
# esta no disco, registrando de onde veio.
#
# Rode na maquina onde o bitstream foi compilado E validado, logo depois
# da validacao:
#
#     ./gera_proveniencia.sh "morphe_ping 4/4; IFFT 0 falhas; Fmax 60,99 MHz"
#
# O argumento e a frase de validacao que entra no cabecalho. Sem ele o
# script se recusa a rodar: proveniencia sem validacao nao e proveniencia.
#
# Existe porque o arquivo ja venceu duas vezes por edicao manual (10/09 e
# 15/09). Conferir continua sendo:  sha256sum -c PROVENIENCIA.sha256
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$RAIZ"

VALIDADO="${1:-}"
if [[ -z "$VALIDADO" ]]; then
    echo "uso: $0 \"<como foi validado>\"" >&2
    exit 2
fi

# O conjunto inseparavel: RTL que vira bitstream, o bitstream, o mapa de
# enderecos que sai dele e o servidor que o usa. Mudou um, muda o hash.
ARQUIVOS=(
    Quartus/conv1d.v
    Quartus/fir_wrapper.v
    Quartus/fft_wrapper.v
    Quartus/iir_cascade.v
    Quartus/iir_biquad_mac.v
    Quartus/ghrd_top.v
    Quartus/soc_system.qsys
    Quartus/soc_system.sopcinfo
    Quartus/output_files/soc_system_time_limited.sof
    C/hps_0.h
    C/morphe_config.h
    C/morphe_server.c
    C/address_map_arm.h
)

SOF=Quartus/output_files/soc_system_time_limited.sof
BUILD="$(date -r "$SOF" '+%Y-%m-%d %H:%M')"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo desconhecido)"

{
    echo "# PROVENIENCIA -- sha256 do conjunto validado em hardware."
    echo "#"
    echo "# Origem  : $(hostname):$RAIZ"
    echo "# Commit  : $COMMIT"
    echo "# Coleta  : $(date '+%Y-%m-%dT%H:%M:%S%z')"
    echo "# Build   : Quartus Prime 20.1 Lite, $SOF de $BUILD"
    echo "# Validado: $VALIDADO"
    echo "#"
    echo "# Gerado por ./gera_proveniencia.sh -- nao edite a mao; rode de novo."
    echo "# Verificar:  sha256sum -c PROVENIENCIA.sha256"
    echo "#"
    sha256sum "${ARQUIVOS[@]}"
} > PROVENIENCIA.sha256

echo "PROVENIENCIA.sha256 regerado: ${#ARQUIVOS[@]} arquivos, commit $COMMIT"
sha256sum -c --quiet PROVENIENCIA.sha256 && echo "conferido."
