#!/usr/bin/env bash
# deploy.sh — envia o servidor pro HPS e compila lá.
#
# Uso:
#   ./deploy.sh <usuario@ip-do-hps>
#   ./deploy.sh root@192.168.1.10
#   ./deploy.sh root@192.168.1.10 /home/root/morphe   # destino customizado
#
# Requer chave SSH configurada ou vai pedir senha três vezes (scp, ssh make, ssh ls).
#
# Na maioria dos casos você quer o ./morphe-up.sh, que faz isto e mais o resto:
# programa a FPGA mantendo o tether da licença, reinicia o servidor na ordem
# certa e verifica antes de devolver o controle. Este script continua aqui para
# quando só se quer reenviar o código.

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Uso: $0 <usuario@host> [diretorio_remoto]"
    echo "Ex:  $0 root@192.168.1.10"
    exit 1
fi

TARGET="$1"
REMOTE_DIR="${2:-morphe}"

# O script vive na raiz do repositório, mas as fontes do servidor estão em C/.
# Antes ele fazia 'cd' para a raiz e procurava os arquivos ali, então só
# funcionava se alguém o copiasse para dentro de C/ — e copiar perde o bit de
# execução, o que dava 'Permission denied'. Agora ele acha C/ sozinho.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/C"

# Verifica que os arquivos necessários estão presentes.
# morphe_config.h é obrigatório: morphe_protocol.h faz #include dele, e sem
# ele a compilação na placa falha com "morphe_config.h: No such file or
# directory". Faltava nesta lista e no scp — era o bug conhecido do script.
REQUIRED=(morphe_server.c morphe_protocol.h morphe_config.h Makefile hps_0.h address_map_arm.h)
for f in "${REQUIRED[@]}"; do
    if [[ ! -f "$f" ]]; then
        echo "ERRO: arquivo faltando: $SCRIPT_DIR/C/$f"
        exit 1
    fi
done

echo "==> Criando diretório remoto $REMOTE_DIR em $TARGET"
ssh "$TARGET" "mkdir -p $REMOTE_DIR"

echo "==> Enviando arquivos..."
scp -q "${REQUIRED[@]}" "$TARGET:$REMOTE_DIR/"

echo "==> Compilando no HPS..."
ssh "$TARGET" "cd $REMOTE_DIR && make morphe_server"

echo "==> Build OK. Para rodar:"
echo "    ssh $TARGET"
echo "    cd $REMOTE_DIR && sudo ./morphe_server"
echo ""
echo "    ou, em uma linha:"
echo "    ssh -t $TARGET 'cd $REMOTE_DIR && sudo ./morphe_server'"
