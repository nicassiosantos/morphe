#!/usr/bin/env bash
# atualizar.sh -- traz para este computador a versao mais nova do Morphe que
# esta no GitHub (git pull no /opt/morphe).
#
# Uso, de qualquer pasta, em qualquer conta com sudo (ou na conta dona):
#   /opt/morphe/atualizar.sh
#
# O git pull precisa rodar como a conta dona do /opt/morphe (quem rodou o
# instala-morphe.sh); o script descobre qual e e usa sudo so se precisar.
# Nunca sobrescreve arquivo modificado a mao: nesse caso para e diz qual e.
# Ao final mostra a versao de antes, a de agora e o que mudou.

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
DONO="$(stat -c %U "$DIR")"

como_dono() {
    if [ "$(id -un)" = "$DONO" ]; then
        "$@"
    else
        sudo -u "$DONO" "$@"
    fi
}

ANTES="$(como_dono git -C "$DIR" rev-parse --short HEAD)"
echo "Morphe em $DIR (dono: $DONO), versao atual $ANTES. Buscando a nova..."

if ! como_dono git -C "$DIR" pull -q --ff-only; then
    echo
    echo "ERRO: a atualizacao falhou. Causas comuns:"
    echo "  - sem rede ate o GitHub: confira a internet e rode de novo;"
    echo "  - arquivo modificado a mao no $DIR: veja qual com"
    echo "      git -C $DIR status"
    exit 1
fi

AGORA="$(como_dono git -C "$DIR" rev-parse --short HEAD)"
if [ "$ANTES" = "$AGORA" ]; then
    echo "Ja estava na versao mais nova ($AGORA). Nada a fazer."
else
    echo "Atualizado: $ANTES -> $AGORA. O que mudou:"
    como_dono git -C "$DIR" log --oneline --no-decorate "$ANTES..$AGORA" | sed 's/^/  /'
    echo "Quem estava com o Morphe aberto precisa fechar e abrir de novo."
fi
