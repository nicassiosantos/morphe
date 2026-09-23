#!/usr/bin/env bash
# deploy.sh — envia o servidor pro HPS e compila lá.
#
# Uso:
#   ./deploy.sh <usuario@ip-do-hps>
#   ./deploy.sh root@192.168.1.10
#   ./deploy.sh root@192.168.1.10 /home/root/morphe   # destino customizado
#
# Requer chave SSH configurada ou vai pedir senha três vezes (scp, ssh make, ssh ls).

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Uso: $0 <usuario@host> [diretorio_remoto]"
    echo "Ex:  $0 root@192.168.1.10"
    exit 1
fi

TARGET="$1"
REMOTE_DIR="${2:-morphe}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Verifica que os arquivos necessários estão presentes
REQUIRED=(morphe_server.c morphe_protocol.h Makefile hps_0.h address_map_arm.h)
for f in "${REQUIRED[@]}"; do
    if [[ ! -f "$f" ]]; then
        echo "ERRO: arquivo faltando: $f"
        echo "  (rode este script de dentro de hps_server/)"
        exit 1
    fi
done

echo "==> Criando diretório remoto $REMOTE_DIR em $TARGET"
ssh "$TARGET" "mkdir -p $REMOTE_DIR"

echo "==> Enviando arquivos..."
scp -q morphe_server.c morphe_protocol.h Makefile hps_0.h address_map_arm.h \
    "$TARGET:$REMOTE_DIR/"

echo "==> Compilando no HPS..."
ssh "$TARGET" "cd $REMOTE_DIR && make morphe_server"

echo "==> Build OK. Para rodar:"
echo "    ssh $TARGET"
echo "    cd $REMOTE_DIR && sudo ./morphe_server"
echo ""
echo "    ou, em uma linha:"
echo "    ssh -t $TARGET 'cd $REMOTE_DIR && sudo ./morphe_server'"
