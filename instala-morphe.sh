#!/usr/bin/env bash
# instala-morphe.sh -- deixa o aplicativo Morphe pronto para as contas de um
# computador do laboratorio: /opt/morphe, as bibliotecas do Python, o atalho no
# menu e um teste da conta do aluno contra as placas.
#
# Os computadores so USAM as placas; quem as prepara (programa a FPGA, sobe o
# servidor) e a estacao, com o morphe-up.sh. Por isso aqui nao ha Quartus nem
# SSH: so o aplicativo, que fala com as placas pela rede. As placas vem do
# placas.conf versionado, entao nao ha lista para escrever a mao.
#
# Faz, na ordem, e pula o que ja estiver feito:
#   1. /opt/morphe: clona na branch principal, ou atualiza com git pull (sem
#      mexer em arquivo modificado a mao);
#   2. dono e permissoes: o dono e quem rodou o sudo (para atualizar sem sudo
#      depois); todas as contas leem; .morphe-estado aberto para escrita;
#   3. Python do sistema com tkinter, NumPy, Matplotlib e SciPy, e sem pacote
#      do "pip --user" do aluno escondendo os do sistema;
#   4. atalho "Morphe" no menu de aplicativos;
#   5. testa da conta do aluno: importa o aplicativo e pergunta as placas.
#
# Uso, numa conta com sudo:
#   sudo ./instala-morphe.sh                    # instala ou atualiza
#   sudo ./instala-morphe.sh --verificar        # so confere, nao muda nada
#   sudo ./instala-morphe.sh --aluno outraconta # conta do teste final
#   sudo ./instala-morphe.sh --origem <url ou pasta>   # de onde clonar
#
# Sem --origem: se o script roda de dentro de um clone, clona dele (rapido, sem
# rede) e aponta o /opt/morphe para o GitHub; senao, clona do GitHub.
# Pode ser rodado de novo quantas vezes quiser; na estacao, so atualiza.

set -euo pipefail

# MORPHE_DEST, MORPHE_ATALHO e MORPHE_SEM_APT existem so para testar o script
# fora de um computador do laboratorio; nao use.
DEST="${MORPHE_DEST:-/opt/morphe}"
RAMO="estagio/v1.1-1024pontos"
GITHUB="https://github.com/nicassiosantos/morphe.git"
ALUNO="alunopds"
ORIGEM=""
VERIFICAR=0
ATALHO="${MORPHE_ATALHO:-/usr/share/applications/morphe.desktop}"
ARGS="$*"
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Saida
# ---------------------------------------------------------------------------

if [[ -t 1 ]]; then
    VERDE=$'\033[32m'; VERM=$'\033[31m'; AMAR=$'\033[33m'; NEG=$'\033[1m'; FIM=$'\033[0m'
else
    VERDE=""; VERM=""; AMAR=""; NEG=""; FIM=""
fi

passo()  { printf '%s==>%s %s\n' "$NEG" "$FIM" "$*"; }
ok()     { printf '    %sok%s    %s\n' "$VERDE" "$FIM" "$*"; }
fiz()    { printf '    %sfeito%s %s\n' "$VERDE" "$FIM" "$*"; }
aviso()  { printf '    %saviso%s %s\n' "$AMAR" "$FIM" "$*"; }
falta()  { printf '    %sfalta%s %s\n' "$VERM" "$FIM" "$*"; FALTAS=$((FALTAS + 1)); }
erro()   { printf '%serro:%s %s\n' "$VERM" "$FIM" "$*" >&2; }

morrer() {
    erro "$1"
    shift
    for linha in "$@"; do printf '       %s\n' "$linha" >&2; done
    exit 1
}

FALTAS=0

# apt-get install, com um "apt-get update" e nova tentativa se falhar: um
# computador que nunca atualizou a lista de pacotes nao acha nada.
instala_apt() {
    [[ -n "${MORPHE_SEM_APT:-}" ]] && return 1
    export DEBIAN_FRONTEND=noninteractive
    apt-get install -y "$@" >/dev/null 2>&1 && return 0
    apt-get update >/dev/null 2>&1 || true
    apt-get install -y "$@" >/dev/null 2>&1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --origem)    ORIGEM="${2:?--origem precisa de um valor}"; shift 2 ;;
        --aluno)     ALUNO="${2:?--aluno precisa de um valor}"; shift 2 ;;
        --verificar) VERIFICAR=1; shift ;;
        -h|--help)   sed -n '2,31p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)           morrer "opcao desconhecida: $1" "use --help para ver as opcoes" ;;
    esac
done

[[ $EUID -eq 0 ]] || morrer "rode com sudo:" "sudo $0 $ARGS"

# O dono do /opt/morphe e quem chamou o sudo: e ele quem vai fazer git pull
# depois, sem sudo -- como o coordenador na estacao.
DONO="${SUDO_USER:-root}"
como_dono() { if [[ "$DONO" == root ]]; then "$@"; else sudo -u "$DONO" -H "$@"; fi; }

# ---------------------------------------------------------------------------
# 0. O computador
# ---------------------------------------------------------------------------

passo "Computador: $(hostname)"
SISTEMA="$(. /etc/os-release 2>/dev/null && printf '%s' "${PRETTY_NAME:-desconhecido}")"
ok "$SISTEMA"
ok "dono do $DEST: $DONO"
TEM_ALUNO=0
if id "$ALUNO" >/dev/null 2>&1; then
    ok "a conta $ALUNO existe"
    TEM_ALUNO=1
else
    aviso "a conta $ALUNO nao existe neste computador; o teste final sera pulado"
fi
if ! command -v git >/dev/null; then
    if (( VERIFICAR )); then
        falta "o git nao esta instalado"
    else
        instala_apt git || morrer "nao consegui instalar o git (sem internet?)"
        fiz "git instalado"
    fi
fi

# ---------------------------------------------------------------------------
# 1. /opt/morphe
# ---------------------------------------------------------------------------

passo "Aplicativo em $DEST"
if [[ -d "$DEST/.git" ]]; then
    ramo="$(como_dono git -C "$DEST" branch --show-current 2>/dev/null || true)"
    modificados="$(como_dono git -C "$DEST" status --porcelain --untracked-files=no 2>/dev/null || true)"
    if [[ "$ramo" != "$RAMO" ]]; then
        falta "$DEST esta no ramo '${ramo:-?}', e nao em $RAMO -- troque com: git -C $DEST checkout $RAMO"
    elif [[ -n "$modificados" ]]; then
        falta "$DEST tem arquivos modificados a mao; o git pull nao vai sobrescreve-los:"
        printf '%s\n' "$modificados" | sed 's/^/             /'
    elif (( VERIFICAR )); then
        como_dono git -C "$DEST" fetch -q origin 2>/dev/null || aviso "sem acesso ao GitHub agora; nao deu para ver se ha versao nova"
        atras="$(como_dono git -C "$DEST" rev-list --count HEAD..origin/"$RAMO" 2>/dev/null || echo "?")"
        if [[ "$atras" == "0" ]]; then ok "atualizado ($(como_dono git -C "$DEST" log --oneline -1))"
        else falta "$atras commit(s) atras do GitHub; sem --verificar ele atualiza"; fi
    else
        antes="$(como_dono git -C "$DEST" rev-parse --short HEAD)"
        como_dono git -C "$DEST" pull -q --ff-only || morrer "o git pull falhou." "confira a rede e rode de novo"
        depois="$(como_dono git -C "$DEST" rev-parse --short HEAD)"
        if [[ "$antes" == "$depois" ]]; then ok "ja estava atualizado ($depois)"
        else fiz "atualizado: $antes -> $depois"; fi
    fi
elif [[ -e "$DEST" ]]; then
    falta "$DEST existe mas nao e um clone do git; mova-o para outro lugar e rode de novo"
elif (( VERIFICAR )); then
    falta "$DEST nao existe"
else
    if [[ -z "$ORIGEM" ]]; then
        if git -C "$AQUI" rev-parse --git-dir >/dev/null 2>&1 && [[ "$AQUI" != "$DEST" ]]; then
            ORIGEM="$AQUI"
        else
            ORIGEM="$GITHUB"
        fi
    fi
    mkdir -p "$DEST"
    chown "$DONO" "$DEST"
    ok "clonando de $ORIGEM"
    como_dono git clone -q -b "$RAMO" "$ORIGEM" "$DEST" \
        || { rmdir "$DEST" 2>/dev/null || true; morrer "o git clone falhou." "confira a rede, ou use --origem <pasta de um clone>"; }
    # Clonado de uma pasta local: as proximas atualizacoes vem do GitHub.
    if [[ "$ORIGEM" != "$GITHUB" && -d "$ORIGEM" ]]; then
        como_dono git -C "$DEST" remote set-url origin "$GITHUB"
    fi
    fiz "$DEST em $(como_dono git -C "$DEST" log --oneline -1)"
fi

# ---------------------------------------------------------------------------
# 2. Dono e permissoes
# ---------------------------------------------------------------------------
# Todas as contas leem (nao ha nada secreto no repositorio). O .morphe-estado e
# aberto para escrita: o aplicativo guarda ali as placas que a varredura achar.

passo "Permissoes"
if [[ -d "$DEST" ]]; then
    trancado="$(find "$DEST" -path "$DEST/.morphe-estado" -prune -o \( \( -type d ! -perm -o=rx \) -o \( -type f ! -perm -o=r \) \) -print -quit 2>/dev/null)"
    estado_ok=0
    [[ -d "$DEST/.morphe-estado" && "$(stat -c %a "$DEST/.morphe-estado")" == 777 ]] && estado_ok=1
    if [[ -z "$trancado" && $estado_ok -eq 1 ]]; then
        ok "todas as contas leem $DEST; .morphe-estado aberto"
    elif (( VERIFICAR )); then
        [[ -z "$trancado" ]] || falta "ha arquivos que o aluno nao le, por exemplo $trancado"
        (( estado_ok )) || falta "$DEST/.morphe-estado nao existe ou nao e 777"
    else
        mkdir -p "$DEST/.morphe-estado"
        chown -R "$DONO" "$DEST"
        chmod -R a+rX "$DEST"
        chmod 777 "$DEST/.morphe-estado"
        find "$DEST/.morphe-estado" -type d -exec chmod 777 {} +
        find "$DEST/.morphe-estado" -type f -exec chmod 666 {} +
        fiz "todas as contas leem; .morphe-estado 777 (arquivos 666)"
    fi
fi

# ---------------------------------------------------------------------------
# 3. Python do sistema
# ---------------------------------------------------------------------------
# O aplicativo usa o python3 do sistema, sem ambiente virtual: o aluno nao pode
# instalar nada. A armadilha recorrente (17/09, 21/09, 23/09) e um NumPy ou
# Matplotlib do "pip install --user" do aluno, em ~/.local, escondendo os do
# sistema e quebrando o outro. Remove-se os DOIS juntos, nunca so um.

passo "Python do sistema"
PACOTES=(python3-tk python3-numpy python3-matplotlib python3-scipy)
faltando=()
for p in "${PACOTES[@]}"; do
    dpkg -s "$p" >/dev/null 2>&1 || faltando+=("$p")
done
if (( ${#faltando[@]} == 0 )); then
    ok "tkinter, NumPy, Matplotlib e SciPy instalados"
elif (( VERIFICAR )); then
    falta "pacotes: ${faltando[*]}"
else
    if instala_apt "${faltando[@]}"; then
        fiz "instalados: ${faltando[*]}"
    else
        falta "nao consegui instalar ${faltando[*]} (sem internet?); rode de novo depois"
    fi
fi

if (( TEM_ALUNO )); then
    onde="$(sudo -u "$ALUNO" -H python3 -c 'import numpy, matplotlib; print(numpy.__file__); print(matplotlib.__file__)' 2>&1 || true)"
    if grep -q '/\.local/' <<<"$onde"; then
        falta "o $ALUNO tem NumPy/Matplotlib do pip --user escondendo os do sistema:"
        printf '             %s\n' $onde
        printf '             na conta dele: python3 -m pip uninstall -y matplotlib numpy\n'
    elif grep -q '/usr/lib/python3' <<<"$onde"; then
        ok "o $ALUNO usa o NumPy e o Matplotlib do sistema"
    else
        falta "o python3 do $ALUNO nao importa NumPy e Matplotlib:"
        printf '%s\n' "$onde" | tail -3 | sed 's/^/             /'
    fi
fi

# ---------------------------------------------------------------------------
# 4. Atalho no menu
# ---------------------------------------------------------------------------

passo "Atalho no menu ($ATALHO)"
# O formato .desktop nao aceita aspas simples nem && no Exec; a pasta de
# trabalho vem do Path.
EXEC="python3 $DEST/Python/morphe_app.py"
if grep -qsxF "Exec=$EXEC" "$ATALHO"; then
    ok "ja existe"
elif (( VERIFICAR )); then
    falta "o atalho \"Morphe\" no menu"
else
    ICONE="$(find "$DEST" -maxdepth 3 -iname '*morphe*.png' 2>/dev/null | sort | head -1)"
    printf '%s\n' '[Desktop Entry]' 'Type=Application' 'Name=Morphe' \
        'Comment=Processamento digital de sinais na FPGA da DE1-SoC' \
        "Exec=$EXEC" "Path=$DEST/Python" "Icon=${ICONE:-applications-science}" \
        'Terminal=false' 'Categories=Education;Science;Engineering;' > "$ATALHO"
    chmod 644 "$ATALHO"
    command -v update-desktop-database >/dev/null && update-desktop-database /usr/share/applications 2>/dev/null || true
    fiz "\"Morphe\" no menu de aplicativos"
fi

# ---------------------------------------------------------------------------
# 5. Teste da conta do aluno
# ---------------------------------------------------------------------------
# Importa os modulos do aplicativo (sem abrir janela) e pergunta as placas pela
# porta de estado, com a lista do placas.conf -- o mesmo caminho do aplicativo.

if (( TEM_ALUNO )) && [[ -d "$DEST/Python" ]]; then
    passo "Teste na conta $ALUNO"
    imp="$(cd "$DEST/Python" && sudo -u "$ALUNO" -H python3 -c 'import tcp_panel, morphe_protocol, aquisicao, blocos; print("ok")' 2>&1 | tail -1 || true)"
    if [[ "$imp" == ok ]]; then
        ok "os modulos do aplicativo importam"
    else
        falta "o aplicativo nao importa na conta do aluno: $imp"
    fi
fi
if (( TEM_ALUNO )) && [[ "${imp:-}" == ok ]]; then
    placas="$(cd "$DEST/Python" && sudo -u "$ALUNO" -H python3 ferramentas/estado_placas.py 2>&1 || true)"
    if [[ -n "$placas" ]]; then
        while IFS= read -r l; do
            if [[ "$l" == *livre* || "$l" == *ocupada* ]]; then ok "$l"; else aviso "$l"; fi
        done <<<"$placas"
    fi
    grep -q 'livre\|ocupada' <<<"$placas" \
        || aviso "nenhuma placa respondeu: estao ligadas e preparadas (morphe-up.sh na estacao)?"
fi

# ---------------------------------------------------------------------------
# Resumo
# ---------------------------------------------------------------------------

echo
if (( FALTAS > 0 )); then
    erro "$FALTAS item(ns) faltando."
    (( VERIFICAR )) && printf '       para corrigir: sudo %s\n' "$0" >&2
    exit 1
fi
passo "Pronto: o Morphe esta instalado em $(hostname)."
echo "    Abrir: menu de aplicativos -> Morphe, ou:"
echo "      cd $DEST/Python && python3 morphe_app.py"
echo "    Atualizar depois (conta $DONO, sem sudo):"
echo "      git -C $DEST pull"
