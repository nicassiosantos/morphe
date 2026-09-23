#!/usr/bin/env bash
# instala-quartus.sh -- deixa o Quartus Prime Lite 20.1 utilizavel por TODAS as contas
# de um computador do laboratorio: abrir a interface, compilar um projeto proprio e
# programar a FPGA pelo USB-Blaster ligado naquele computador.
#
# A versao e sempre a 20.1, a mesma que compilou o bitstream do Morphe. Por isso o
# Quartus NAO vem do instalador: e copiado inteiro da estacao LABPS-47723, onde ja
# mora em /opt/intelFPGA_lite/20.1 (ver PREPARACAO.md, "Tirando o coordenador do
# caminho critico").
#
# Faz, na ordem, e pula o que ja estiver feito:
#   1. procura os Quartus ja instalados; um 20.1 com Cyclone V fora das homes e usado
#      como esta, um dentro de uma home e copiado para /opt sem rede, e so sem nenhum
#      dos dois a copia vem da estacao (ou de um HD externo);
#   2. confere que o escolhido e mesmo a 20.1 e tem o Cyclone V;
#   3. libera a leitura para todas as contas;
#   4. regra udev do USB-Blaster, para qualquer conta enxergar o cabo;
#   5. libudev.so.0, que o jtagd do USB-Blaster II da DE1-SoC procura;
#   6. PATH em /etc/profile.d, com a 20.1 NA FRENTE de qualquer outra versao;
#   7. atalho "Quartus Prime Lite 20.1" no menu de aplicativos;
#   8. testa da conta do aluno: versao e cabo.
#
# Uso, numa conta com sudo (na estacao, a conta coordenador):
#   sudo ./instala-quartus.sh                               # copia da estacao
#   sudo ./instala-quartus.sh --origem coordenador@<ip>     # estacao em outro IP
#   sudo ./instala-quartus.sh --origem /media/hd/intelFPGA_lite   # de um HD externo
#   sudo ./instala-quartus.sh --aluno outraconta            # conta do teste final
#   sudo ./instala-quartus.sh --verificar                   # so confere, nao muda nada
#
# Na propria estacao ele nao copia nada (a 20.1 ja esta la) e faz so os passos 3 a 8.
# Com --verificar, o passo 1 mostra tudo o que ja esta instalado, sem mudar nada.
# Pode ser rodado de novo quantas vezes quiser.

set -euo pipefail

ORIGEM="coordenador@172.16.101.237"   # a estacao LABPS-47723, enp3s0f0 em 21/09/2026
ALUNO="alunopds"
VERIFICAR=0
ARGS="$*"

BASE="/opt/intelFPGA_lite"
DEST="$BASE/20.1"
PERFIL="/etc/profile.d/quartus.sh"
ATALHO="/usr/share/applications/quartus-20.1.desktop"
REGRA="/etc/udev/rules.d/51-usbblaster.rules"
LIBDIR="/lib/x86_64-linux-gnu"
ESPACO_GB=17   # a 20.1 da estacao ocupa 16 GB
# Existe enquanto uma copia esta em andamento. Se ela for interrompida, a proxima
# execucao nao confunde a pasta pela metade com uma instalacao e retoma o rsync.
INCOMPLETA=".instala-quartus-copia-incompleta"

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

# ---------------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
    case "$1" in
        --origem)    ORIGEM="${2:?--origem precisa de um valor}"; shift 2 ;;
        --aluno)     ALUNO="${2:?--aluno precisa de um valor}"; shift 2 ;;
        --verificar) VERIFICAR=1; shift ;;
        -h|--help)   sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)           morrer "opcao desconhecida: $1" "use --help para ver as opcoes" ;;
    esac
done

[[ $EUID -eq 0 ]] || morrer "rode com sudo:" "sudo $0 $ARGS"

# ---------------------------------------------------------------------------
# 0. O computador
# ---------------------------------------------------------------------------

passo "Computador: $(hostname)"
SISTEMA="$(. /etc/os-release 2>/dev/null && printf '%s' "${PRETTY_NAME:-desconhecido}")"
if [[ "$SISTEMA" == Ubuntu\ 22.04* ]]; then
    ok "$SISTEMA"
else
    aviso "$SISTEMA -- a estacao e Ubuntu 22.04; se o Quartus nao abrir, falta biblioteca"
fi
if id "$ALUNO" >/dev/null 2>&1; then
    ok "a conta $ALUNO existe"
else
    aviso "a conta $ALUNO nao existe neste computador; o teste final sera pulado"
fi

# ---------------------------------------------------------------------------
# 1 e 2. Um Quartus 20.1 utilizavel: o que ja existe, ou uma copia da estacao
# ---------------------------------------------------------------------------
# Antes de copiar 16 GB, procura o que ja esta instalado. Um 20.1 fora das homes
# serve como esta. Um 20.1 dentro de uma home NAO serve direto -- as homes sao 0750 e
# o aluno nao le (foi o bloqueio da estacao em 16/09) --, mas vira a origem de uma
# copia local para /opt, sem rede. So sem nenhum dos dois a copia vem da estacao.
#
# "Utilizavel" inclui o suporte ao Cyclone V: um Quartus sem ele programa a placa mas
# nao compila nada para a DE1-SoC.

tem_cyclonev() {
    local devinfo="$1/quartus/common/devinfo"
    [[ -d "$devinfo" ]] || return 0   # estrutura desconhecida: nao da para dizer que falta
    compgen -G "$devinfo/cyclonev*" >/dev/null
}

versao_de() { "$1/quartus/bin/quartus_sh" --version 2>/dev/null | grep -m1 'Version' || true; }

eh_desta_maquina() {
    local host="${1#*@}"
    [[ "$host" == "localhost" || "$host" == "127.0.0.1" ]] && return 0
    hostname -I 2>/dev/null | tr ' ' '\n' | grep -qxF "$host"
}

passo "Quartus ja instalados neste computador"
QROOT=""      # o 20.1 que sera usado
EM_HOME=""    # um 20.1 dentro de uma home, para copiar localmente
while IFS= read -r qsh; do
    raiz="${qsh%/quartus/bin/quartus_sh}"
    v="$(versao_de "$raiz")"
    if [[ -e "$raiz/$INCOMPLETA" ]]; then
        aviso "$raiz: copia interrompida da outra vez -- sera retomada"
    elif [[ "$v" != *"Version 20.1"* ]]; then
        ok "$raiz: ${v:-versao ilegivel} -- outra versao, fica atras da 20.1 no PATH"
    elif ! tem_cyclonev "$raiz"; then
        aviso "$raiz: $v -- SEM suporte ao Cyclone V, nao serve para a DE1-SoC"
    elif [[ "$raiz" == /home/* || "$raiz" == /root/* ]]; then
        ok "$raiz: $v -- dentro de uma home, o aluno nao le; serve de origem da copia"
        [[ -n "$EM_HOME" ]] || EM_HOME="$raiz"
    else
        ok "$raiz: $v -- serve"
        # a de /opt/intelFPGA_lite ganha de qualquer outra, por ser a da estacao
        if [[ -z "$QROOT" || "$raiz" == "$DEST" ]]; then QROOT="$raiz"; fi
    fi
done < <(find /opt /usr/local /tools /home /root -maxdepth 6 \( -type f -o -type l \) -path '*/quartus/bin/quartus_sh' 2>/dev/null | sort -u)
[[ -n "$QROOT$EM_HOME" ]] || ok "nenhum Quartus 20.1 com Cyclone V"

passo "Quartus 20.1 que as contas vao usar"
if [[ -n "$QROOT" ]]; then
    ok "$QROOT (ja instalado, nada a copiar)"
elif [[ $VERIFICAR -eq 1 ]]; then
    if [[ -n "$EM_HOME" ]]; then
        falta "o 20.1 so existe em $EM_HOME, que o aluno nao le; sem --verificar ele e copiado para $DEST"
    else
        falta "nao ha Quartus 20.1 utilizavel; sem --verificar ele e copiado da estacao"
    fi
else
    if [[ -z "$EM_HOME" && ! -d "$ORIGEM" ]] && eh_desta_maquina "$ORIGEM"; then
        morrer "este computador E a estacao ($ORIGEM), e nao ha Quartus 20.1 utilizavel em $DEST." "Confira com: ls /opt/intelFPGA_lite"
    fi
    livre="$(df --output=avail -BG "$(dirname "$BASE")" | tail -1 | tr -dc '0-9')"
    [[ "$livre" -ge $ESPACO_GB ]] || morrer "so ha ${livre} GB livres em /opt; a copia precisa de ${ESPACO_GB} GB"

    command -v rsync >/dev/null || { aviso "instalando o rsync"; apt-get install -y rsync >/dev/null; }
    mkdir -p "$DEST"
    touch "$DEST/$INCOMPLETA"

    if [[ -n "$EM_HOME" ]]; then
        ok "copiando $EM_HOME para $DEST (local, sem rede)"
        rsync -a --info=progress2 "$EM_HOME/" "$DEST/"
    elif [[ -d "$ORIGEM" ]]; then
        # HD externo: aceita a pasta intelFPGA_lite ou a propria pasta 20.1
        if [[ -d "$ORIGEM/20.1/quartus" ]]; then FONTE="$ORIGEM/20.1/"
        elif [[ -d "$ORIGEM/quartus" ]];   then FONTE="$ORIGEM/"
        else morrer "$ORIGEM nao tem a pasta 20.1/quartus"; fi
        ok "copiando de $FONTE"
        rsync -a --info=progress2 "$FONTE" "$DEST/"
    else
        ok "copiando de $ORIGEM:$DEST (16 GB, alguns minutos)"
        aviso "a senha pedida e a da conta ${ORIGEM%@*} NA ESTACAO"
        rsync -a --info=progress2 -e "ssh -o StrictHostKeyChecking=accept-new" "$ORIGEM:$DEST/" "$DEST/" || morrer "a copia falhou." "Na estacao, confira o IP com: hostname -I" "e se o SSH esta no ar com: systemctl is-active ssh" "Depois rode de novo com: sudo $0 --origem coordenador@<ip>"
    fi
    rm -f "$DEST/$INCOMPLETA"
    fiz "copiado"
    QROOT="$DEST"
fi

if [[ -n "$QROOT" ]]; then
    v="$(versao_de "$QROOT")"
    [[ "$v" == *"Version 20.1"* ]] || morrer "$QROOT nao e o Quartus 20.1:" "${v:-quartus_sh --version nao respondeu}"
    tem_cyclonev "$QROOT" || morrer "$QROOT nao tem suporte ao Cyclone V"
    ok "$v"
fi
QBIN="$QROOT/quartus/bin"

# ---------------------------------------------------------------------------
# 3. Leitura para todas as contas
# ---------------------------------------------------------------------------

passo "Permissoes"
if [[ -n "$QROOT" ]]; then
    # Algum arquivo ou pasta que o aluno nao consiga ler (ou entrar)? Inclui as pastas
    # acima do QROOT: uma so sem o x dos outros tranca tudo o que esta dentro.
    trancado="$(find "$QROOT" \( -type d ! -perm -o=rx \) -o \( -type f ! -perm -o=r \) -print -quit 2>/dev/null)"
    d="$(dirname "$QROOT")"
    while [[ -z "$trancado" && "$d" != "/" ]]; do
        [[ "$(stat -c %A "$d")" == ????????x* || "$(stat -c %A "$d")" == ?????????x ]] || trancado="$d"
        d="$(dirname "$d")"
    done
    if [[ -z "$trancado" ]]; then
        ok "todas as contas leem $QROOT"
    elif [[ $VERIFICAR -eq 1 ]]; then
        falta "ha arquivos que o aluno nao le, por exemplo $trancado"
    else
        chmod -R a+rX "$QROOT"
        d="$(dirname "$QROOT")"
        while [[ "$d" != "/" ]]; do chmod a+x "$d"; d="$(dirname "$d")"; done
        fiz "chmod -R a+rX $QROOT"
    fi
fi

# ---------------------------------------------------------------------------
# 4. Regra udev do USB-Blaster
# ---------------------------------------------------------------------------

passo "Regra udev do USB-Blaster"
if grep -qs '09fb' /etc/udev/rules.d/*; then
    ok "ja existe: $(grep -ls '09fb' /etc/udev/rules.d/* | head -1)"
elif [[ $VERIFICAR -eq 1 ]]; then
    falta "nenhuma regra para o fabricante 09fb (Altera/Intel)"
else
    printf '%s\n' '# Qualquer conta usa o USB-Blaster (fabricante Altera/Intel). Escrito pelo instala-quartus.sh.' 'SUBSYSTEM=="usb", ATTR{idVendor}=="09fb", MODE="0666"' > "$REGRA"
    udevadm control --reload-rules
    udevadm trigger --subsystem-match=usb
    fiz "$REGRA -- cabos ja conectados: desconecte e reconecte"
fi

# ---------------------------------------------------------------------------
# 5. libudev.so.0
# ---------------------------------------------------------------------------

passo "libudev.so.0 (USB-Blaster II)"
if [[ -e "$LIBDIR/libudev.so.0" ]]; then
    ok "existe"
elif [[ ! -e "$LIBDIR/libudev.so.1" ]]; then
    aviso "nem libudev.so.0 nem libudev.so.1 em $LIBDIR; confira se o jtagconfig acha o cabo"
elif [[ $VERIFICAR -eq 1 ]]; then
    falta "$LIBDIR/libudev.so.0"
else
    ln -s "$LIBDIR/libudev.so.1" "$LIBDIR/libudev.so.0"
    fiz "link $LIBDIR/libudev.so.0 -> libudev.so.1"
fi

# ---------------------------------------------------------------------------
# 6. PATH para todas as contas
# ---------------------------------------------------------------------------
# Em /etc/profile.d e nao no ~/.bashrc: os terminais em ksh93 do laboratorio nao
# leem o ~/.bashrc. A 20.1 vai NA FRENTE para ganhar de outra versao instalada.

passo "PATH ($PERFIL)"
LINHA_PATH="export PATH=\"$QBIN:$QROOT/quartus/sopc_builder/bin:\$PATH\""
if [[ -z "$QROOT" ]]; then
    falta "sem Quartus 20.1, nao ha o que por no PATH"
elif grep -qsF "$LINHA_PATH" "$PERFIL"; then
    ok "ja configurado"
elif [[ $VERIFICAR -eq 1 ]]; then
    falta "$PERFIL nao poe a 20.1 no PATH"
else
    printf '%s\n' '# Quartus Prime Lite 20.1 para todas as contas. Escrito pelo instala-quartus.sh.' "$LINHA_PATH" > "$PERFIL"
    fiz "$PERFIL"
fi

# ---------------------------------------------------------------------------
# 7. Atalho no menu
# ---------------------------------------------------------------------------

passo "Atalho no menu ($ATALHO)"
if [[ -z "$QROOT" ]]; then
    falta "sem Quartus 20.1, nao ha atalho a criar"
elif grep -qsxF "Exec=$QBIN/quartus" "$ATALHO"; then
    ok "ja existe"
elif [[ $VERIFICAR -eq 1 ]]; then
    falta "o atalho \"Quartus Prime Lite 20.1\" para $QBIN/quartus"
else
    ICONE="$(find "$QROOT/quartus/adm" -maxdepth 1 -iname '*.png' 2>/dev/null | sort | head -1)"
    printf '%s\n' '[Desktop Entry]' 'Type=Application' 'Name=Quartus Prime Lite 20.1' "Exec=$QBIN/quartus" "Icon=${ICONE:-applications-engineering}" 'Terminal=false' 'Categories=Development;Electronics;' > "$ATALHO"
    fiz "\"Quartus Prime Lite 20.1\" no menu"
fi

# ---------------------------------------------------------------------------
# 8. Teste da conta do aluno
# ---------------------------------------------------------------------------
# bash -l le o /etc/profile, que le o /etc/profile.d -- e o mesmo PATH que o aluno
# vai ter depois de entrar. O jtagconfig roda como aluno, nunca como root: o jtagd
# que ele sobe fica dono do cabo.

if id "$ALUNO" >/dev/null 2>&1 && [[ -x "$QBIN/quartus_sh" ]]; then
    passo "Teste na conta $ALUNO"
    qual="$(sudo -u "$ALUNO" -H bash -lc 'command -v quartus_sh' || true)"
    versao_aluno="$(sudo -u "$ALUNO" -H bash -lc 'quartus_sh --version 2>/dev/null | grep -m1 Version' || true)"
    if [[ "$qual" != "$QBIN/quartus_sh" ]]; then
        falta "o aluno acha o quartus_sh em ${qual:-lugar nenhum}, e nao em $QBIN (sair e entrar de novo resolve so se o PATH ja estiver certo)"
    elif [[ "$versao_aluno" == *"Version 20.1"* ]]; then
        ok "quartus_sh: $qual -- $versao_aluno"
    else
        falta "o aluno nao acha o quartus_sh 20.1 no PATH (achou: ${versao_aluno:-nada})"
    fi

    # A primeira chamada as vezes volta sem cabo enquanto o jtagd sobe; a segunda acha.
    cabos="$(sudo -u "$ALUNO" -H bash -lc 'jtagconfig 2>&1' || true)"
    if ! grep -q '^[0-9])' <<<"$cabos"; then
        sleep 3
        cabos="$(sudo -u "$ALUNO" -H bash -lc 'jtagconfig 2>&1' || true)"
    fi
    if grep -q '^[0-9])' <<<"$cabos"; then
        while read -r linha; do ok "cabo: $linha"; done < <(grep '^[0-9])' <<<"$cabos")
    else
        aviso "nenhum cabo JTAG agora -- normal se nao ha placa ligada neste computador"
        aviso "com a placa ligada, na sessao do aluno: jtagconfig"
    fi
fi

# ---------------------------------------------------------------------------
# Resumo
# ---------------------------------------------------------------------------

echo
if [[ $FALTAS -gt 0 ]]; then
    erro "$FALTAS item(ns) faltando."
    [[ $VERIFICAR -eq 1 ]] && printf '       para corrigir: sudo %s\n' "$0" >&2
    exit 1
fi
passo "Pronto: o Quartus 20.1 esta disponivel para todas as contas de $(hostname)."
echo "    Quem estiver logado precisa ENCERRAR A SESSAO e entrar de novo para ter o PATH."
echo "    Programar a placa, da sessao do aluno:"
echo "      jtagconfig"
echo "      quartus_pgm -c \"DE-SoC [1-x]\" -m jtag -o \"p;arquivo.sof@2\""
