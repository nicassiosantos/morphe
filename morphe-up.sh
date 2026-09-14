#!/usr/bin/env bash
# morphe-up.sh -- deixa uma placa DE1-SoC pronta para uso, em um comando.
#
# Faz, na ordem, tudo o que hoje e feito a mao:
#   1. acha o Quartus, mesmo que o PATH nao esteja configurado;
#   2. descobre o nome do cabo JTAG pelo jtagconfig (ele muda de porta para porta);
#   3. programa a FPGA e MANTEM O TETHER DA LICENCA VIVO em segundo plano;
#   4. acha a placa na rede, ou usa a que foi informada e guarda para a proxima vez;
#   5. envia e compila o servidor, se precisar;
#   6. (re)inicia o servidor -- sempre depois da FPGA, nunca antes;
#   7. verifica com o morphe_ping antes de devolver o controle.
#
# Uso:
#   ./morphe-up.sh                      # placa lembrada ou descoberta na rede
#   ./morphe-up.sh --board 172.16.103.226
#   ./morphe-up.sh --cable 'DE-SoC [1-2]'   # quando ha mais de uma placa na estacao
#   ./morphe-up.sh --deploy             # forca reenviar e recompilar o servidor
#   ./morphe-up.sh --skip-fpga          # so servidor, sem tocar na FPGA
#   ./morphe-up.sh --setup-ssh --board <ip>  # uma vez por placa: acaba com as senhas
#   ./morphe-up.sh --status             # o que esta no ar agora
#   ./morphe-up.sh --down               # derruba servidor e tether
#
# Roda da raiz do repositorio ou de qualquer lugar: ele se localiza sozinho.

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ESTADO="$RAIZ/.morphe-estado"
PID_TETHER="$ESTADO/tether.pid"
LOG_TETHER="$ESTADO/tether.log"
CONF_PLACA="$ESTADO/placa"

SOF="$RAIZ/Quartus/output_files/soc_system_time_limited.sof"
PORTA_PADRAO=5000
DIR_REMOTO=morphe
USUARIO_PLACA="${MORPHE_USER:-root}"

# Os seis arquivos que o servidor precisa. O morphe_config.h e o que o
# deploy.sh original esquecia, e sem ele a compilacao na placa falha.
FONTES_SERVIDOR=(
    morphe_server.c
    morphe_protocol.h
    morphe_config.h
    hps_0.h
    address_map_arm.h
    Makefile
)

# ---------------------------------------------------------------------------
# Saida
# ---------------------------------------------------------------------------

if [[ -t 1 ]]; then
    VERDE=$'\033[32m'; VERM=$'\033[31m'; AMAR=$'\033[33m'; NEG=$'\033[1m'; FIM=$'\033[0m'
else
    VERDE=""; VERM=""; AMAR=""; NEG=""; FIM=""
fi

passo()  { printf '%s==>%s %s\n' "$NEG" "$FIM" "$*"; }
ok()     { printf '    %sok%s   %s\n' "$VERDE" "$FIM" "$*"; }
aviso()  { printf '    %saviso%s %s\n' "$AMAR" "$FIM" "$*"; }
erro()   { printf '%serro:%s %s\n' "$VERM" "$FIM" "$*" >&2; }

morrer() {
    erro "$1"
    shift
    for linha in "$@"; do printf '       %s\n' "$linha" >&2; done
    exit 1
}

# ---------------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------------

PLACA=""
PORTA="$PORTA_PADRAO"
CABO_PEDIDO=""
FORCA_DEPLOY=0
PULA_FPGA=0
ACAO=up

while [[ $# -gt 0 ]]; do
    case "$1" in
        --board|-b) PLACA="${2:-}"; shift 2 ;;
        --port|-p)  PORTA="${2:-}"; shift 2 ;;
        --cable|-c) CABO_PEDIDO="${2:-}"; shift 2 ;;
        --deploy)   FORCA_DEPLOY=1; shift ;;
        --skip-fpga) PULA_FPGA=1; shift ;;
        --down)     ACAO=down; shift ;;
        --status)   ACAO=status; shift ;;
        --setup-ssh) ACAO=setup-ssh; shift ;;
        -h|--help)  awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' \
                        "${BASH_SOURCE[0]}"; exit 0 ;;
        *)          morrer "opcao desconhecida: $1" "use --help" ;;
    esac
done

mkdir -p "$ESTADO"

# ---------------------------------------------------------------------------
# Python do cliente
# ---------------------------------------------------------------------------

achar_python() {
    local candidatos=(
        "$RAIZ/Python/.venv/bin/python"
        "$RAIZ/Python/.venv/Scripts/python.exe"
    )
    for p in "${candidatos[@]}"; do
        [[ -x "$p" ]] && { printf '%s' "$p"; return 0; }
    done
    command -v python3 2>/dev/null && return 0
    command -v python  2>/dev/null && return 0
    return 1
}

# ---------------------------------------------------------------------------
# 1. Quartus
# ---------------------------------------------------------------------------
# O PATH do Quartus mora no ~/.bashrc, que os terminais em ksh93 da estacao nao
# leem. Em vez de exigir que o usuario saiba disso, procuramos as ferramentas.

achar_quartus() {
    if command -v quartus_pgm >/dev/null 2>&1 && command -v jtagconfig >/dev/null 2>&1; then
        return 0
    fi
    local bases=(
        "${QUARTUS_ROOTDIR:-}"
        "$HOME"/intelFPGA_lite/*/quartus
        "$HOME"/intelFPGA_lite/*/qprogrammer
        /opt/intelFPGA_lite/*/quartus
        /opt/intelFPGA_lite/*/qprogrammer
        "$HOME"/intelFPGA/*/quartus
    )
    for base in "${bases[@]}"; do
        [[ -n "$base" && -x "$base/bin/quartus_pgm" ]] || continue
        export QUARTUS_ROOTDIR="$base"
        export PATH="$base/bin:$PATH"
        return 0
    done
    return 1
}

# ---------------------------------------------------------------------------
# 2. Cabo JTAG
# ---------------------------------------------------------------------------
# O nome vem como "1) DE-SoC [1-2]" e o indice muda conforme a porta USB.
# Nunca chutar: sempre ler do jtagconfig.

# Publica em CABO, e nao no stdout, de proposito: chamada dentro de $(...) o
# 'exit' do morrer sairia so da subshell e o script seguiria com o cabo vazio.
CABO=""

achar_cabo() {
    local saida
    saida="$(jtagconfig 2>&1 || true)"

    # O jtagconfig desenha uma barra de progresso, volta ao inicio da linha com
    # \r e escreve o resultado por cima. No terminal isso some; no buffer, a
    # linha vira "<barra>\r1) DE-SoC [1-2]" e um ^[0-9] nunca casa. Trocar cada
    # \r por quebra de linha deixa o nome do cabo sozinho na sua linha.
    local limpa
    limpa="$(printf '%s\n' "$saida" | tr '\r' '\n')"

    local cabos=()
    while IFS= read -r c; do
        [[ -n "$c" ]] && cabos+=("$c")
    done < <(printf '%s\n' "$limpa" | sed -n 's/^[[:space:]]*[0-9]\{1,\}) \(.*[^[:space:]]\)[[:space:]]*$/\1/p')

    if (( ${#cabos[@]} == 0 )); then
        erro "o jtagconfig nao enxergou nenhum cabo."
        printf '%s\n' "$limpa" | sed 's/^/       /' >&2
        morrer "sem cabo JTAG, nao da para programar a FPGA." \
               "confira o cabo: e o mini-USB AO LADO DO BOTAO DE POWER," \
               "nao o USB-to-UART que fica logo ao lado." \
               "se o cabo esta certo, faltam as regras udev (INSTALACAO.md 4.2)."
    fi

    # Mais de um cabo = mais de uma placa nesta estacao. Escolher sozinho seria
    # programar a placa errada sem avisar.
    if [[ -n "$CABO_PEDIDO" ]]; then
        local achou=""
        for c in "${cabos[@]}"; do
            [[ "$c" == "$CABO_PEDIDO" ]] && achou="$c"
        done
        [[ -n "$achou" ]] || morrer "o cabo '$CABO_PEDIDO' nao esta na lista do jtagconfig." \
            "cabos vistos: ${cabos[*]}"
        CABO="$achou"
        return 0
    fi

    if (( ${#cabos[@]} > 1 )); then
        erro "ha mais de um cabo JTAG nesta estacao:"
        for c in "${cabos[@]}"; do printf '       %s\n' "$c" >&2; done
        morrer "escolha qual placa programar." \
               "use: ./morphe-up.sh --cable '${cabos[0]}' --board <ip>"
    fi

    CABO="${cabos[0]}"
}

# ---------------------------------------------------------------------------
# 3. Programar a FPGA, mantendo o tether da licenca
# ---------------------------------------------------------------------------
# O quartus_pgm nao devolve o prompt: imprime "Please enter i for info and q to
# quit:" e fica aberto. ESSE processo aberto e o tether da licenca de avaliacao
# do IP da FFT -- enquanto ele vive, nao ha limite de tempo; quando morre,
# comeca a contagem de 1 hora e a FFT passa a devolver zeros.
#
# Por isso o processo vai para segundo plano com um stdin que nunca fecha
# ("sleep infinity |"), em sessao propria (setsid), e o PGID fica guardado para
# o --down. Um deploy.sh que programasse e retornasse mataria a FFT em 1 h.

tether_vivo() {
    [[ -f "$PID_TETHER" ]] || return 1
    local pgid; pgid="$(cat "$PID_TETHER" 2>/dev/null || true)"
    [[ -n "$pgid" ]] || return 1
    kill -0 "-$pgid" 2>/dev/null
}

derrubar_tether() {
    if tether_vivo; then
        local pgid; pgid="$(cat "$PID_TETHER")"
        kill -TERM "-$pgid" 2>/dev/null || true
        sleep 1
        kill -KILL "-$pgid" 2>/dev/null || true
        ok "tether encerrado (a FFT passa a ter 1 h de vida)"
    fi
    rm -f "$PID_TETHER"
}

programar_fpga() {
    [[ -f "$SOF" ]] || morrer "bitstream nao encontrado: $SOF" \
        "confira que o clone esta completo (sha256sum -c PROVENIENCIA.sha256)."

    achar_quartus || morrer "nao achei o quartus_pgm." \
        "procurei no PATH, em \$QUARTUS_ROOTDIR e nas instalacoes usuais." \
        "se o Quartus esta em outro lugar, exporte QUARTUS_ROOTDIR e rode de novo."
    ok "quartus em ${QUARTUS_ROOTDIR:-$(dirname "$(command -v quartus_pgm)")}"

    if tether_vivo; then
        aviso "ja existe um tether vivo; reprogramando e substituindo"
        derrubar_tether
    fi

    achar_cabo
    ok "cabo JTAG: $CABO"

    command -v setsid >/dev/null 2>&1 || morrer "preciso do setsid (util-linux)." \
        "sem ele nao da para manter o tether da licenca vivo em segundo plano."

    # O @2 e a posicao da FPGA na cadeia JTAG; a posicao 1 e o HPS.
    # Sem ele a programacao falha.
    passo "programando a FPGA"
    : > "$LOG_TETHER"
    rm -f "$PID_TETHER"
    # O proprio processo grava o PGID: sob setsid ele e lider de sessao, entao
    # seu $$ e o PGID do grupo inteiro (o bash, o sleep e o quartus_pgm). Ler o
    # PGID aqui fora, do PID devolvido por $!, nao serve -- o setsid pode ter
    # forkado e esse PID ja ter morrido.
    setsid bash -c "echo \$\$ > '$PID_TETHER'; sleep infinity | quartus_pgm -m jtag -c '$CABO' -o 'p;$SOF@2' >> '$LOG_TETHER' 2>&1" &

    local limite=60
    while (( limite-- > 0 )); do
        if grep -q "Configuration succeeded" "$LOG_TETHER" 2>/dev/null; then
            ok "Configuration succeeded"
            if tether_vivo; then
                ok "tether da licenca vivo em segundo plano (PGID $(cat "$PID_TETHER"))"
            else
                aviso "o tether nao ficou vivo -- a FFT tem 1 h a partir de agora"
            fi
            return 0
        fi
        # So o formato de erro do Quartus ("Error (209042): ...") no inicio da
        # linha. Um 'grep -i error' solto casa com "0 errors" e aborta uma
        # programacao que deu certo. O tr desfaz o \r da barra de progresso,
        # que senao deixaria o "Error" no meio da linha e fora do ^.
        if tr '\r' '\n' < "$LOG_TETHER" 2>/dev/null | grep -qE "^Error"; then
            erro "o quartus_pgm falhou:"
            tr '\r' '\n' < "$LOG_TETHER" | sed 's/^/       /' >&2
            derrubar_tether
            morrer "programacao da FPGA falhou." \
                   "se for 'Application SLD HUB CLIENT ... is using the target device'," \
                   "feche o Signal Tap ou outro Quartus aberto e tente de novo."
        fi
        sleep 1
    done
    derrubar_tether
    morrer "tempo esgotado esperando 'Configuration succeeded'." \
           "veja o log em $LOG_TETHER"
}

# ---------------------------------------------------------------------------
# 4. Achar a placa
# ---------------------------------------------------------------------------
# Ordem: --board, $MORPHE_BOARD, a placa lembrada da ultima vez, descoberta na
# rede. A descoberta so acha uma placa cujo servidor ja esteja no ar -- o que
# passa a ser o caso sempre, depois que o autostart de boot estiver instalado
# (C/autostart/). Uma vez informada, a placa fica lembrada em .morphe-estado/.

resolver_placa() {
    if [[ -n "$PLACA" ]]; then
        printf '%s' "$PLACA"; return 0
    fi
    if [[ -n "${MORPHE_BOARD:-}" ]]; then
        printf '%s' "$MORPHE_BOARD"; return 0
    fi

    local lembrada=""
    [[ -f "$CONF_PLACA" ]] && lembrada="$(cat "$CONF_PLACA")"

    local py; py="$(achar_python || true)"
    if [[ -n "$py" ]]; then
        local achada
        # A busca comeca pelo /24 da placa lembrada: elas trocam de IP por DHCP
        # e ja apareceram fora dos 101/102/103 historicos.
        achada="$(cd "$RAIZ/Python" && MORPHE_LEMBRADA="$lembrada" "$py" -c "
import os, sys
try:
    from morphe_protocol import subredes_provaveis, discover_servers
except Exception:
    sys.exit(1)
lembrada = os.environ.get('MORPHE_LEMBRADA') or None
achados = discover_servers(subredes_provaveis(lembrada), port=$PORTA,
                           stop_on_first=True)
if achados:
    print(achados[0].ip)
" 2>/dev/null || true)"
        if [[ -n "$achada" ]]; then
            printf '%s' "$achada"; return 0
        fi
    fi

    if [[ -n "$lembrada" ]]; then
        printf '%s' "$lembrada"; return 0
    fi
    return 1
}

# ---------------------------------------------------------------------------
# 5. Servidor: enviar, compilar, (re)iniciar
# ---------------------------------------------------------------------------

# accept-new aceita a chave de uma placa nunca vista, mas continua recusando
# uma chave que MUDOU. Sem isso, cada IP novo do DHCP para o fluxo com a
# pergunta "authenticity of host can't be established" -- e as placas trocam de
# IP com frequencia.
SSH_OPTS=(-o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)

ssh_placa() { ssh "${SSH_OPTS[@]}" "$USUARIO_PLACA@$ALVO" "$@"; }

# O erro cru do ssh ("No route to host") nao diz o que fazer, e a v1.2 existe
# justamente para isso. A checagem tambem separa dois casos que se parecem: a
# placa sem energia e a placa ligada mas fora da rede -- se o JTAG acabou de
# enxergar o SOCVHPS, energia tem.
verificar_alcance() {
    passo "conferindo o caminho ate a placa"
    if ping -c 1 -W 3 "$ALVO" >/dev/null 2>&1; then
        ok "a placa responde em $ALVO"
        return 0
    fi
    # ICMP as vezes e bloqueado; a porta do SSH e a que interessa de verdade.
    if command -v nc >/dev/null 2>&1 && nc -z -w 4 "$ALVO" 22 >/dev/null 2>&1; then
        ok "porta 22 aberta em $ALVO (o ping esta bloqueado, sem problema)"
        return 0
    fi

    erro "nao ha caminho de rede ate $ALVO."
    if (( ! PULA_FPGA )); then
        printf '       %s\n' \
            "a placa TEM energia -- o JTAG acabou de enxerga-la. E so a rede." >&2
    fi
    printf '       %s\n' \
        "confira, nesta ordem:" \
        "  1. o cabo de rede da placa, e o LED do conector" \
        "  2. o IP atual, pelo console serial: screen /dev/ttyUSB0 115200 -> ip addr" \
        "     (o que serve e o 172.16.x.x da eth0; os 192.168.x.123 sao de fabrica)" \
        "  3. se o IP mudou, rode de novo com --skip-fpga --board <ip-novo>" \
        "     -- assim voce nao reprograma a FPGA nem reinicia a licenca" >&2
    if tether_vivo; then
        printf '       %s\n' \
            "o tether continua vivo (PGID $(cat "$PID_TETHER")): a FFT nao esta" \
            "perdendo tempo enquanto voce resolve a rede." >&2
    fi
    exit 1
}

enviar_servidor() {
    passo "enviando e compilando o servidor em $ALVO"
    ssh_placa "mkdir -p $DIR_REMOTO"
    ( cd "$RAIZ/C" && scp -q "${SSH_OPTS[@]}" "${FONTES_SERVIDOR[@]}" "$USUARIO_PLACA@$ALVO:$DIR_REMOTO/" )
    # Nunca 'make clean' aqui: RESSALVAS item 9.
    ssh_placa "cd $DIR_REMOTO && make morphe_server"
    ok "servidor compilado na placa"
}

reiniciar_servidor() {
    # Sempre DEPOIS de programar a FPGA. Um servidor que subiu antes da
    # programacao responde aos testes 1 e 2 do ping e da FPGA_TIMEOUT nos
    # testes 3 e 4 -- o sintoma mais confuso da plataforma.
    passo "(re)iniciando o servidor"

    # pkill/pgrep -x casam o NOME do processo; -f casaria a linha de comando
    # inteira -- inclusive a do proprio shell remoto, que carrega a string
    # "morphe_server" neste comando. Com -f, o pkill matava o shell que o
    # executava e o pgrep dava positivo sem servidor nenhum.
    #
    # 'sudo' so quando nao se entrou como root: as imagens minimas das placas
    # nem sempre tem sudo instalado, e o servidor precisa e de /dev/mem.
    local remoto="cd $DIR_REMOTO || exit 1
pkill -x morphe_server || true
sleep 1
if [ \"\$(id -u)\" = 0 ]; then SU=; else SU=sudo; fi
nohup \$SU ./morphe_server $PORTA > morphe_server.log 2>&1 &
sleep 2
pgrep -x morphe_server > /dev/null"

    if ssh_placa "$remoto"; then
        ok "servidor no ar na porta $PORTA"
        return 0
    fi

    erro "o servidor nao subiu em $ALVO."
    ssh_placa "tail -n 20 $DIR_REMOTO/morphe_server.log 2>/dev/null" 2>/dev/null \
        | sed 's/^/       /' >&2 || true
    morrer "sem servidor, nao ha o que verificar." \
           "se o log acima estiver vazio, tente na mao para ver a mensagem:" \
           "  ssh $USUARIO_PLACA@$ALVO 'cd $DIR_REMOTO && ./morphe_server $PORTA'"
}

# ---------------------------------------------------------------------------
# 6. Verificacao
# ---------------------------------------------------------------------------

verificar() {
    local py; py="$(achar_python || true)"
    [[ -n "$py" ]] || { aviso "sem Python utilizavel; pulando a verificacao"; return 0; }

    passo "verificando a plataforma (morphe_ping)"
    # Rodar de dentro de Python/ porque o morphe_ping faz sys.path.insert(0, ".")
    if ( cd "$RAIZ/Python" && "$py" ../Quartus/morphe_ping.py "$ALVO" "$PORTA" ); then
        ok "os quatro testes passaram"
        return 0
    fi
    erro "o morphe_ping falhou."
    printf '       %s\n' \
        "1 e 2 falham .............. rede ou servidor" \
        "3 e 4 dao FPGA_TIMEOUT .... FPGA nao programada, ou servidor antes dela" \
        "4 passa e 3 falha ......... hps_0.h desatualizado (rode gen_hps_header.py)" >&2
    return 1
}

# ---------------------------------------------------------------------------
# Acoes
# ---------------------------------------------------------------------------

acao_status() {
    if tether_vivo; then
        ok "tether da licenca vivo (PGID $(cat "$PID_TETHER")) -- FFT sem limite de tempo"
    else
        aviso "tether ausente -- se a FPGA foi programada ha mais de 1 h, a FFT devolve zeros"
    fi
    if [[ -f "$CONF_PLACA" ]]; then
        local ip; ip="$(cat "$CONF_PLACA")"
        printf '    placa lembrada: %s\n' "$ip"
        if ssh -o BatchMode=yes -o ConnectTimeout=5 "$USUARIO_PLACA@$ip" \
               "pgrep -x morphe_server > /dev/null" 2>/dev/null; then
            ok "servidor no ar em $ip"
        else
            aviso "servidor nao responde em $ip (ou o SSH pediu senha)"
        fi
    else
        aviso "nenhuma placa lembrada ainda"
    fi
}

# Uma vez por placa: instala a chave publica da estacao na placa, e a partir
# dai nenhum passo pede senha. Sem isto, um unico morphe-up.sh pede senha tres
# vezes (scp, make, start) -- o que ja desmonta a promessa de "um comando".
acao_setup_ssh() {
    ALVO="$(resolver_placa || true)"
    [[ -n "${ALVO:-}" ]] || morrer "nao sei em qual placa instalar a chave." \
        "use: ./morphe-up.sh --setup-ssh --board <ip>"
    ok "placa: $ALVO"

    mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"

    local chave="$HOME/.ssh/id_ed25519"
    if [[ -f "$chave" ]]; then
        ok "chave ja existe: $chave"
    elif [[ -f "$HOME/.ssh/id_rsa" ]]; then
        chave="$HOME/.ssh/id_rsa"
        ok "chave ja existe: $chave"
    else
        passo "criando uma chave SSH sem frase secreta"
        ssh-keygen -t ed25519 -N "" -f "$chave" -C "morphe@$(hostname)" >/dev/null
        ok "criada: $chave"
    fi

    passo "instalando a chave na placa -- esta e a ultima vez que pede senha"
    if command -v ssh-copy-id >/dev/null 2>&1; then
        ssh-copy-id -o StrictHostKeyChecking=accept-new \
                    -i "$chave.pub" "$USUARIO_PLACA@$ALVO"
    else
        ssh "${SSH_OPTS[@]}" "$USUARIO_PLACA@$ALVO" \
            "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys" \
            < "$chave.pub"
    fi

    if ssh -o BatchMode=yes -o ConnectTimeout=8 "$USUARIO_PLACA@$ALVO" true 2>/dev/null; then
        ok "pronto: $USUARIO_PLACA@$ALVO entra sem senha"
        printf '%s' "$ALVO" > "$CONF_PLACA"
    else
        morrer "a chave foi enviada, mas o login sem senha ainda nao funciona." \
               "na placa, confira /etc/ssh/sshd_config:" \
               "  PubkeyAuthentication yes" \
               "  PermitRootLogin yes            (se estiver entrando como root)" \
               "e reinicie com /etc/init.d/ssh restart"
    fi
}

acao_down() {
    if [[ -f "$CONF_PLACA" ]]; then
        local ip; ip="$(cat "$CONF_PLACA")"
        passo "parando o servidor em $ip"
        ssh "${SSH_OPTS[@]}" "$USUARIO_PLACA@$ip" "pkill -x morphe_server || true" || \
            aviso "nao consegui falar com a placa; siga assim mesmo"
    fi
    passo "encerrando o tether"
    derrubar_tether
    ok "pronto"
}

acao_up() {
    passo "preparando a plataforma Morphe"

    if (( PULA_FPGA )); then
        aviso "--skip-fpga: a FPGA nao sera tocada"
        tether_vivo || aviso "e nao ha tether vivo; a FFT pode estar fora do prazo"
    else
        programar_fpga
    fi

    ALVO="$(resolver_placa || true)"
    if [[ -z "${ALVO:-}" ]]; then
        morrer "nao achei a placa." \
               "na primeira vez, informe uma vez so: ./morphe-up.sh --board <ip>" \
               "o IP util e o 172.16.x.x da eth0; os 192.168.x.123 sao aliases de fabrica." \
               "depois disso ela fica lembrada, e com o autostart de boot instalado" \
               "(C/autostart/) a descoberta pela rede passa a bastar."
    fi
    ok "placa: $ALVO"
    verificar_alcance
    printf '%s' "$ALVO" > "$CONF_PLACA"

    local tem_binario=1
    ssh -o ConnectTimeout=8 "$USUARIO_PLACA@$ALVO" \
        "test -x $DIR_REMOTO/morphe_server" 2>/dev/null || tem_binario=0

    if (( FORCA_DEPLOY )) || (( ! tem_binario )); then
        enviar_servidor
    else
        ok "servidor ja compilado na placa (use --deploy para reenviar)"
    fi

    reiniciar_servidor
    verificar || exit 1

    printf '\n%sPlataforma pronta.%s  placa %s, porta %s\n' "$NEG" "$FIM" "$ALVO" "$PORTA"
    printf 'Abra o cliente:  cd Python && ./.venv/bin/python morphe_app.py\n'
    printf 'Ao terminar:     ./morphe-up.sh --down\n'
}

case "$ACAO" in
    up)        acao_up ;;
    down)      acao_down ;;
    status)    acao_status ;;
    setup-ssh) acao_setup_ssh ;;
esac
