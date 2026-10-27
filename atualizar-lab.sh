#!/usr/bin/env bash
# atualizar-lab.sh -- atualiza o Morphe (git pull no /opt/morphe) de TODOS os
# computadores do laboratorio, por SSH, a partir de um computador so.
#
# A lista dos computadores fica em computadores.conf, na mesma pasta.
#
# Uso:
#   ./atualizar-lab.sh                 atualiza todos os da lista
#   ./atualizar-lab.sh --status        so mostra a versao de cada um
#   ./atualizar-lab.sh --preparar      UMA VEZ: cria a chave SSH e a copia para
#                                      cada computador (pede a senha de cada um)
#   ./atualizar-lab.sh --so IP         so um computador (pode repetir)
#   ./atualizar-lab.sh --usuario NOME  conta do SSH (padrao: coordenador)
#   ./atualizar-lab.sh --ramo RAMO     troca o /opt/morphe de cada um para RAMO
#                                      (ex.: estagio/adc-fft) e atualiza; recusa
#                                      se houver arquivo mexido a mao
#
# O --status e o --ramo tambem conferem, em cada computador, o que o aplicativo
# precisa para gravar a FPGA pelo USB: Quartus 20.1 e a regra udev do USB-Blaster.
#
# Antes da primeira vez, em cada computador (uma vez, na frente dele):
#   sudo apt install -y openssh-server
#   sudo systemctl enable --now ssh
#
# O git pull roda como a conta dona do /opt/morphe de cada computador (quem
# rodou o instala-morphe.sh). Se a conta do SSH for a dona, nao precisa de
# sudo; se nao for, precisa de sudo sem senha -- senao o computador aparece
# como "sem permissao" no resumo. Nunca sobrescreve arquivo modificado a mao.

set -uo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LISTA="$DIR/computadores.conf"
CHAVE="$HOME/.ssh/id_morphe_lab"
USUARIO="coordenador"
MODO="atualizar"
RAMO_NOVO=""
SO=()

while [ $# -gt 0 ]; do
    case "$1" in
        --status)   MODO="status" ;;
        --preparar) MODO="preparar" ;;
        --so)       shift; SO+=("${1:?--so precisa de um IP ou nome}") ;;
        --usuario)  shift; USUARIO="${1:?--usuario precisa de um nome}" ;;
        --ramo)     shift; RAMO_NOVO="${1:?--ramo precisa do nome do ramo}"; MODO="ramo" ;;
        -h|--help)  sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Opcao desconhecida: $1 (veja --help)"; exit 2 ;;
    esac
    shift
done

# --- a lista ------------------------------------------------------------------

[ -f "$LISTA" ] || { echo "ERRO: nao achei $LISTA"; exit 1; }

ALVOS=()
while read -r alvo _; do
    case "$alvo" in ''|\#*) continue ;; esac
    [[ "$alvo" == *@* ]] || alvo="$USUARIO@$alvo"
    if [ ${#SO[@]} -gt 0 ]; then
        achou=0
        for s in "${SO[@]}"; do [ "${alvo#*@}" = "$s" ] && achou=1; done
        [ $achou = 1 ] || continue
    fi
    ALVOS+=("$alvo")
done < "$LISTA"

if [ ${#ALVOS[@]} -eq 0 ]; then
    echo "Nenhum computador para atualizar. Ponha os IPs em $LISTA"
    echo "(um por linha; para descobrir o IP, rode 'hostname -I' em cada um)."
    exit 1
fi

# --- preparar: chave SSH -------------------------------------------------------

if [ "$MODO" = "preparar" ]; then
    if [ ! -f "$CHAVE" ]; then
        mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
        ssh-keygen -t ed25519 -N "" -C "morphe-lab $(id -un)@$(hostname)" -f "$CHAVE" -q
        echo "Chave criada: $CHAVE"
    else
        echo "Chave ja existe: $CHAVE"
    fi
    FALHOU=()
    for alvo in "${ALVOS[@]}"; do
        echo
        echo "=== $alvo: copiando a chave (digite a senha da conta ${alvo%@*} desse computador)"
        if ssh-copy-id -i "$CHAVE.pub" -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new "$alvo"; then
            echo "    ok"
        else
            FALHOU+=("$alvo")
        fi
    done
    echo
    if [ ${#FALHOU[@]} -eq 0 ]; then
        echo "Pronto: todos os ${#ALVOS[@]} computadores aceitam a chave. Agora: ./atualizar-lab.sh"
    else
        echo "Falharam (SSH desligado? senha errada? IP errado?):"
        printf '  %s\n' "${FALHOU[@]}"
        exit 1
    fi
    exit 0
fi

# --- o que roda em cada computador ----------------------------------------------
# Vai pela entrada padrao do ssh (bash -s), entao nao precisa de nada instalado
# la alem do /opt/morphe. A ultima linha e sempre "RESULTADO ...", que o resumo le.

REMOTO='
D=/opt/morphe
MODO="$1"
if [ ! -d "$D/.git" ]; then echo "RESULTADO sem_morphe"; exit 0; fi
DONO=$(stat -c %U "$D")
if [ "$(id -un)" = "$DONO" ]; then
    run() { "$@"; }
else
    run() { sudo -n -u "$DONO" -H "$@"; }
fi
ANTES=$(run git -C "$D" rev-parse --short HEAD 2>/dev/null) || { echo "RESULTADO sem_permissao $DONO"; exit 0; }
RAMO=$(run git -C "$D" rev-parse --abbrev-ref HEAD)
MEXIDOS=$(run git -C "$D" status --porcelain --untracked-files=no | wc -l)
# O aplicativo grava a FPGA pelo USB deste computador: sem Quartus 20.1 ou sem
# a regra udev, ele abre mas a placa fica "nao preparada".
if [ "$MODO" != atualizar ]; then
    [ -x /opt/intelFPGA_lite/20.1/quartus/bin/quartus_pgm ] \
        || echo "    AVISO: sem Quartus 20.1 (rodar o instala-quartus.sh nele)"
    grep -qs 09fb /etc/udev/rules.d/* \
        || echo "    AVISO: sem a regra udev do USB-Blaster (rodar o instala-quartus.sh nele)"
fi
if [ "$MODO" = status ]; then
    echo "RESULTADO status $ANTES $RAMO $MEXIDOS"
    exit 0
fi
if [ "$MODO" = ramo ] && [ "$RAMO" != "$3" ]; then
    if [ "$MEXIDOS" != 0 ]; then
        run git -C "$D" status --short --untracked-files=no | sed "s/^/    /"
        echo "RESULTADO mexido $ANTES $MEXIDOS"
        exit 0
    fi
    if ! SAIDA=$(run git -C "$D" fetch -q origin "+refs/heads/$3:refs/remotes/origin/$3" 2>&1); then
        echo "$SAIDA" | sed "s/^/    /"
        echo "RESULTADO sem_ramo $3"
        exit 0
    fi
    if run git -C "$D" rev-parse -q --verify "refs/heads/$3" > /dev/null; then
        SAIDA=$(run git -C "$D" checkout -q "$3" 2>&1)
    else
        SAIDA=$(run git -C "$D" checkout -q -b "$3" --track "origin/$3" 2>&1)
    fi || { echo "$SAIDA" | sed "s/^/    /"; echo "RESULTADO falhou $ANTES"; exit 0; }
    echo "    ramo trocado: $RAMO -> $3"
    ORIGINAL=$ANTES   # o resumo mostra de onde saiu; a lista do que mudou, so o ramo novo
    ANTES=$(run git -C "$D" rev-parse --short HEAD)
fi
if ! SAIDA=$(run git -C "$D" pull -q --ff-only 2>&1); then
    echo "$SAIDA" | sed "s/^/    /"
    echo "RESULTADO falhou $ANTES"
    exit 0
fi
if [ -n "${2:-}" ]; then
    printf "%s" "$2" | base64 -d | run tee "$D/placas.local.conf" > /dev/null \
        && echo "    placas.local.conf copiado da estacao"
fi
AGORA=$(run git -C "$D" rev-parse --short HEAD)
if [ "$ANTES" != "$AGORA" ]; then
    run git -C "$D" log --oneline --no-decorate "$ANTES..$AGORA" | sed "s/^/    /"
fi
echo "RESULTADO ok ${ORIGINAL:-$ANTES} $AGORA"
'

# O placas.local.conf daqui (as placas acrescentadas sem commit) vai junto, em
# base64 como argumento: chega igual em todos e e gravado pela conta dona.
LOCAL_B64=""
[ -f "$DIR/placas.local.conf" ] && LOCAL_B64="$(base64 -w0 "$DIR/placas.local.conf")"

SSH_OPCOES=(-o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new)
[ -f "$CHAVE" ] && SSH_OPCOES+=(-i "$CHAVE")

# A versao do GitHub de cada ramo, para o --status dizer quem esta atrasado.
# Cada computador e comparado com o ramo em que ELE esta, nao com o daqui.
declare -A NOVA_DO_RAMO=()
nova_de() {   # poe em NOVA a versao do GitHub do ramo $1 (sem subshell: guarda o cache)
    if [ -z "${NOVA_DO_RAMO[$1]+x}" ]; then
        NOVA_DO_RAMO[$1]=$(git -C "$DIR" ls-remote origin "refs/heads/$1" 2>/dev/null | cut -c1-7)
    fi
    NOVA="${NOVA_DO_RAMO[$1]}"
}
[ "$MODO" = ramo ] && echo "Trocando cada computador para o ramo $RAMO_NOVO"

RESUMO=()
ERROS=0
for alvo in "${ALVOS[@]}"; do
    echo "=== ${alvo#*@}"
    SAIDA=$(ssh "${SSH_OPCOES[@]}" "$alvo" bash -s -- "$MODO" "$LOCAL_B64" "$RAMO_NOVO" <<< "$REMOTO" 2>&1)
    CODIGO=$?
    echo "$SAIDA" | grep -v '^RESULTADO ' | grep -v '^Warning: Permanently added'
    set -- $(echo "$SAIDA" | grep '^RESULTADO ' | tail -1)
    shift 2>/dev/null
    case "${1:-}" in
        ok)
            if [ "$2" = "$3" ]; then linha="ja estava em $3"; else linha="atualizado $2 -> $3"; fi ;;
        status)
            linha="em $2 (ramo $3)"
            nova_de "$3"
            [ -n "$NOVA" ] && [ "$2" != "$NOVA" ] && linha="$linha  <-- ATRASADO (GitHub: $NOVA)"
            [ "$4" != 0 ] && linha="$linha  ($4 arquivo(s) mexido(s) a mao)" ;;
        mexido)
            linha="NAO TROCOU DE RAMO: $3 arquivo(s) mexido(s) a mao (lista acima)"; ERROS=$((ERROS+1)) ;;
        sem_ramo)
            linha="NAO TROCOU: o ramo $2 nao existe no GitHub (veja a mensagem acima)"; ERROS=$((ERROS+1)) ;;
        falhou)
            linha="FALHOU no git pull (em $2; veja a mensagem acima)"; ERROS=$((ERROS+1)) ;;
        sem_permissao)
            linha="SEM PERMISSAO: o dono do /opt/morphe e $2; use --usuario $2"; ERROS=$((ERROS+1)) ;;
        sem_morphe)
            linha="NAO TEM /opt/morphe (rodar o instala-morphe.sh nele)"; ERROS=$((ERROS+1)) ;;
        *)
            ERROS=$((ERROS+1))
            if [ $CODIGO = 255 ]; then
                if echo "$SAIDA" | grep -q 'Permission denied'; then
                    linha="SSH RECUSOU A CHAVE (rodar ./atualizar-lab.sh --preparar)"
                else
                    linha="SEM SSH (desligado, sem openssh-server ou IP errado)"
                fi
            else
                linha="ERRO inesperado (codigo $CODIGO)"
            fi ;;
    esac
    echo "    -> $linha"
    RESUMO+=("$(printf '%-18s %s' "${alvo#*@}" "$linha")")
done

echo
echo "=== Resumo (${#ALVOS[@]} computadores, $ERROS com problema)"
printf '  %s\n' "${RESUMO[@]}"
if [ "$MODO" = atualizar ] || [ "$MODO" = ramo ]; then
    echo
    echo "Este computador nao entra na lista; para ele: $DIR/atualizar.sh"
    echo "Quem estava com o Morphe aberto precisa fechar e abrir de novo."
fi
[ $ERROS = 0 ]
