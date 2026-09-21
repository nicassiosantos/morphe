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
#   ./morphe-up.sh --status             # o que esta no ar agora, placa a placa
#   ./morphe-up.sh --down               # encerra os tethers de TODAS as placas
#   ./morphe-up.sh --down --stop-server # e tambem para o servidor da placa
#
# Com mais de uma placa na estacao: o tether e por CABO JTAG, entao preparar uma
# placa NAO derruba a outra. O --cable diz qual, e o --status lista as duas.
#
# Roda da raiz do repositorio ou de qualquer lugar: ele se localiza sozinho.

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ESTADO="$RAIZ/.morphe-estado"
# Um tether por CABO JTAG, nao um por estacao. Com duas placas, preparar uma
# derrubava o tether da outra: o estado era um arquivo so. A chave e o nome do
# cabo, que e quem o quartus_pgm segura de fato.
DIR_TETHERS="$ESTADO/tethers"
CONF_PLACA="$ESTADO/placa"        # a ultima preparada -- e o que o cliente le
CONF_PLACAS="$ESTADO/placas"      # todas as ja preparadas, uma por linha

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
FPGA_PROGRAMADA=0   # vira 1 quando o quartus_pgm confirmar, nesta execucao
PARAR_SERVIDOR=0
ACAO=up

while [[ $# -gt 0 ]]; do
    case "$1" in
        --board|-b) PLACA="${2:-}"; shift 2 ;;
        --port|-p)  PORTA="${2:-}"; shift 2 ;;
        --cable|-c) CABO_PEDIDO="${2:-}"; shift 2 ;;
        --deploy)   FORCA_DEPLOY=1; shift ;;
        --skip-fpga) PULA_FPGA=1; shift ;;
        --down)     ACAO=down; shift ;;
        --stop-server) PARAR_SERVIDOR=1; shift ;;
        --status)   ACAO=status; shift ;;
        --setup-ssh) ACAO=setup-ssh; shift ;;
        -h|--help)  awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' \
                        "${BASH_SOURCE[0]}"; exit 0 ;;
        *)          morrer "opcao desconhecida: $1" "use --help" ;;
    esac
done

mkdir -p "$ESTADO" "$DIR_TETHERS"

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


# "DE-SoC [1-3]" vira "DE-SoC_1-3_": nome de arquivo, sem colchete nem espaco.
chave_cabo() { printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'; }

pid_tether_de() { printf '%s/%s.pid' "$DIR_TETHERS" "$(chave_cabo "$1")"; }
log_tether_de() { printf '%s/%s.log' "$DIR_TETHERS" "$(chave_cabo "$1")"; }

# O nome do cabo com os colchetes, guardado ao lado do PID: a chave serve para
# nomear arquivo, mas quem le a tela quer ver "DE-SoC [1-2]".
nome_do_cabo() {
    local arq="${1%.pid}.cabo"
    [[ -f "$arq" ]] && cat "$arq" || basename "${1%.pid}"
}

_pgid_vivo() {
    local arq="$1" pgid
    [[ -f "$arq" ]] || return 1
    pgid="$(cat "$arq" 2>/dev/null || true)"
    [[ -n "$pgid" ]] || return 1
    # pgrep, e nao 'kill -0': o tether pode ser de OUTRA conta (o coordenador
    # preparou, o aluno veio depois), e 'kill -0' num processo alheio falha
    # com EPERM -- igualzinho a um processo morto. O script achava o cabo
    # livre, subia um segundo quartus_pgm e o Quartus recusava o cabo ocupado.
    pgrep -g "$pgid" >/dev/null 2>&1
}

# Dono do grupo de processos, para a mensagem de quem derruba o que nao e seu.
_dono_pgid() { ps -o user= -g "$1" 2>/dev/null | head -1; }

# Ecoa "<cabo> <pgid>" de cada tether vivo, um por linha. E a base do --status.
tethers_vivos() {
    local arq
    for arq in "$DIR_TETHERS"/*.pid; do
        [[ -e "$arq" ]] || continue
        _pgid_vivo "$arq" || continue
        printf '%s %s\n' "$(nome_do_cabo "$arq")" "$(cat "$arq")"
    done
}

# Sem argumento: existe ALGUM tether vivo? Com o nome de um cabo: aquele.
tether_vivo() {
    if [[ -n "${1:-}" ]]; then
        _pgid_vivo "$(pid_tether_de "$1")"
    else
        [[ -n "$(tethers_vivos)" ]]
    fi
}

_derrubar_arquivo() {
    local arq="$1"
    if _pgid_vivo "$arq"; then
        local pgid; pgid="$(cat "$arq")"
        kill -TERM "-$pgid" 2>/dev/null || true
        sleep 1
        kill -KILL "-$pgid" 2>/dev/null || true
        if _pgid_vivo "$arq"; then
            morrer "o tether de $(nome_do_cabo "$arq") pertence a conta '$(_dono_pgid "$pgid")' e esta conta nao pode encerra-lo."                    "ou essa conta roda ./morphe-up.sh --down (ou --cable so do outro cabo),"                    "ou, se a placa dela ja esta preparada, use-a como esta: o cliente a acha sozinho."
        fi
        ok "tether encerrado em $(nome_do_cabo "$arq") (a FFT dessa placa passa a ter 1 h)"
    fi
    rm -f "$arq" "${arq%.pid}.cabo"
}

# Sem argumento derruba TODOS -- e o que o --down quer. Com o nome de um cabo,
# so o daquele cabo, para nao matar a placa do colega ao preparar a sua.
derrubar_tether() {
    if [[ -n "${1:-}" ]]; then
        _derrubar_arquivo "$(pid_tether_de "$1")"
        return 0
    fi
    local arq
    for arq in "$DIR_TETHERS"/*.pid; do
        [[ -e "$arq" ]] || continue
        _derrubar_arquivo "$arq"
    done
}

# O IP mais recente manda no cliente; a lista guarda todas as placas ja
# preparadas, que e o que uma escolha automatica vai precisar ler.
lembrar_placa() {
    local ip="$1"
    printf '%s' "$ip" > "$CONF_PLACA"
    local atuais=""
    [[ -f "$CONF_PLACAS" ]] && atuais="$(grep -v -x -F "$ip" "$CONF_PLACAS" || true)"
    { [[ -n "$atuais" ]] && printf '%s\n' "$atuais"; printf '%s\n' "$ip"; } > "$CONF_PLACAS"
}

programar_fpga() {
    [[ -f "$SOF" ]] || morrer "bitstream nao encontrado: $SOF" \
        "confira que o clone esta completo (sha256sum -c PROVENIENCIA.sha256)."

    achar_quartus || morrer "nao achei o quartus_pgm." \
        "procurei no PATH, em \$QUARTUS_ROOTDIR e nas instalacoes usuais." \
        "se o Quartus esta em outro lugar, exporte QUARTUS_ROOTDIR e rode de novo."
    ok "quartus em ${QUARTUS_ROOTDIR:-$(dirname "$(command -v quartus_pgm)")}"

    # O cabo primeiro: e ele que diz QUAL tether substituir. Antes isto vinha
    # antes de saber o cabo, e por isso derrubava o tether de qualquer placa.
    achar_cabo
    ok "cabo JTAG: $CABO"

    local pid_t log_t
    pid_t="$(pid_tether_de "$CABO")"
    log_t="$(log_tether_de "$CABO")"

    if tether_vivo "$CABO"; then
        aviso "ja existe um tether NESTE cabo; reprogramando e substituindo"
        derrubar_tether "$CABO"
    fi

    local outros; outros="$(tethers_vivos | wc -l)"
    if (( outros > 0 )); then
        ok "$outros tether(s) de outras placas seguem vivos, intocados"
    fi

    command -v setsid >/dev/null 2>&1 || morrer "preciso do setsid (util-linux)." \
        "sem ele nao da para manter o tether da licenca vivo em segundo plano."

    # O @2 e a posicao da FPGA na cadeia JTAG; a posicao 1 e o HPS.
    # Sem ele a programacao falha.
    passo "programando a FPGA"
    : > "$log_t"
    rm -f "$pid_t"
    printf '%s' "$CABO" > "${pid_t%.pid}.cabo"
    # O proprio processo grava o PGID: sob setsid ele e lider de sessao, entao
    # seu $$ e o PGID do grupo inteiro (o bash, o sleep e o quartus_pgm). Ler o
    # PGID aqui fora, do PID devolvido por $!, nao serve -- o setsid pode ter
    # forkado e esse PID ja ter morrido.
    setsid bash -c "echo \$\$ > '$pid_t'; sleep infinity | quartus_pgm -m jtag -c '$CABO' -o 'p;$SOF@2' >> '$log_t' 2>&1" &

    local limite=60
    while (( limite-- > 0 )); do
        if grep -q "Configuration succeeded" "$log_t" 2>/dev/null; then
            ok "Configuration succeeded"
            FPGA_PROGRAMADA=1
            if tether_vivo "$CABO"; then
                ok "tether da licenca vivo em segundo plano (PGID $(cat "$pid_t"))"
            else
                aviso "o tether nao ficou vivo -- a FFT tem 1 h a partir de agora"
            fi
            return 0
        fi
        # So o formato de erro do Quartus ("Error (209042): ...") no inicio da
        # linha. Um 'grep -i error' solto casa com "0 errors" e aborta uma
        # programacao que deu certo. O tr desfaz o \r da barra de progresso,
        # que senao deixaria o "Error" no meio da linha e fora do ^.
        if tr '\r' '\n' < "$log_t" 2>/dev/null | grep -qE "^Error"; then
            erro "o quartus_pgm falhou:"
            tr '\r' '\n' < "$log_t" | sed 's/^/       /' >&2
            derrubar_tether "$CABO"
            morrer "programacao da FPGA falhou." \
                   "se for 'Application SLD HUB CLIENT ... is using the target device'," \
                   "feche o Signal Tap ou outro Quartus aberto e tente de novo."
        fi
        sleep 1
    done
    derrubar_tether "$CABO"
    morrer "tempo esgotado esperando 'Configuration succeeded'." \
           "veja o log em $log_t"
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

# Chave propria para as placas, separada da chave pessoal de quem usa a estacao.
CHAVE_MORPHE="${MORPHE_KEY:-$HOME/.ssh/id_rsa_morphe}"

montar_ssh_opts() {
    # As placas rodam OpenSSH 6.0 (Debian 7): nao conhecem ed25519, que so
    # existe a partir do 6.5, e assinam apenas com ssh-rsa/SHA-1. A estacao
    # roda OpenSSH 8.9, que desabilitou ssh-rsa por padrao desde a 8.8. Sem
    # reabilitar aqui, a chave RSA e gerada, instalada na placa e nunca usada
    # -- que e exatamente o sintoma de "a chave foi enviada mas ainda pede
    # senha". A opcao so entra se o ssh local a reconhecer.
    if ssh -G -o PubkeyAcceptedKeyTypes=+ssh-rsa localhost >/dev/null 2>&1; then
        SSH_OPTS+=(-o PubkeyAcceptedKeyTypes=+ssh-rsa)
    fi
    # IdentitiesOnly evita que o agente ofereca antes a chave pessoal (ed25519,
    # que a placa recusa) e gaste as tentativas de autenticacao.
    if [[ -f "$CHAVE_MORPHE" ]]; then
        SSH_OPTS+=(-i "$CHAVE_MORPHE" -o IdentitiesOnly=yes)
    fi
}

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
            "o tether continua vivo: a FFT nao esta" \
            "perdendo tempo enquanto voce resolve a rede." >&2
    fi
    exit 1
}

# Impressao digital das fontes do servidor. O RESSALVAS item 1 diz que
# bitstream, hps_0.h e morphe_server sao um conjunto inseparavel; "o binario
# existe na placa" nunca provou que ele corresponde a estas fontes. Como o
# hps_0.h esta entre os arquivos medidos, e o bitstream vem deste mesmo clone,
# a impressao bater significa que o conjunto esta consistente.
impressao_fontes() {
    ( cd "$RAIZ/C" && cat "${FONTES_SERVIDOR[@]}" | sha256sum | cut -d' ' -f1 )
}

servidor_confere() {
    local aqui la
    aqui="$(impressao_fontes)"
    la="$(ssh_placa "cat $DIR_REMOTO/.fontes.sha256 2>/dev/null; test -x $DIR_REMOTO/morphe_server" 2>/dev/null || true)"
    [[ -n "$la" && "$la" == "$aqui" ]]
}

enviar_servidor() {
    passo "enviando e compilando o servidor em $ALVO"
    ssh_placa "mkdir -p $DIR_REMOTO"
    ( cd "$RAIZ/C" && scp -q "${SSH_OPTS[@]}" "${FONTES_SERVIDOR[@]}" "$USUARIO_PLACA@$ALVO:$DIR_REMOTO/" )
    # -B: recompila SEMPRE. A placa nao tem RTC e acorda em 1970; um binario
    # datado de 2026 e "do futuro" para o make, que responde "up to date" e
    # nao toca nele -- e a impressao digital abaixo passaria a atestar um
    # binario que nao corresponde as fontes. Visto em 15/09/2026: o hps_0.h
    # novo foi enviado e o servidor continuou o antigo.
    # Nunca 'make clean' aqui: RESSALVAS item 9.
    ssh_placa "cd $DIR_REMOTO && make -B morphe_server"
    # A marca so e gravada depois do build dar certo.
    ssh_placa "printf '%s' '$(impressao_fontes)' > $DIR_REMOTO/.fontes.sha256"
    ok "servidor compilado na placa"
}

reiniciar_servidor() {
    # Sempre DEPOIS de programar a FPGA, e e aqui que a placa fica sabendo
    # disso: a marca /var/run/morphe-fpga-preparada. Sem ela o servidor recusa
    # toda operacao com FPGA_NAO_PREPARADA em vez de tocar a FPGA -- porque
    # uma placa recem-ligada carrega o bitstream de fabrica, em que os PIOs
    # do Morphe nao existem, e um acesso a eles trava o barramento do HPS
    # inteiro (placa 2, 21/09/2026: sumiu da rede a cada boot por causa do
    # autostart). A marca vive em tmpfs e some no reboot, junto com o
    # bitstream. So e criada se ESTA execucao programou a FPGA; com
    # --skip-fpga vale a que ja estiver la, se estiver.
    passo "(re)iniciando o servidor"

    if (( FPGA_PROGRAMADA )); then
        ssh_placa "if [ \"\$(id -u)\" = 0 ]; then SU=; else SU=sudo; fi; \$SU touch /var/run/morphe-fpga-preparada" \
            && ok "placa marcada como preparada (/var/run/morphe-fpga-preparada)" \
            || aviso "nao consegui gravar a marca de FPGA preparada; as operacoes serao recusadas"
    fi

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

    # O log da placa e a unica testemunha do que o servidor viu. Sem guardar
    # isto na hora, uma falha intermitente -- que na proxima execucao pode nao
    # se repetir -- fica sem evidencia nenhuma.
    local diario="$ESTADO/falha-$(date +%Y%m%d_%H%M%S).log"
    {
        printf 'placa %s porta %s\n' "$ALVO" "$PORTA"
        printf 'tethers vivos:\n%s\n' "$(tethers_vivos || echo '  nenhum')"
        printf -- '--- morphe_server.log (ultimas 40 linhas) ---\n'
        ssh_placa "tail -n 40 $DIR_REMOTO/morphe_server.log 2>/dev/null" 2>/dev/null || true
    } > "$diario"
    aviso "log da placa guardado em $diario"

    printf '       %s\n' \
        "1 e 2 falham ................ rede ou servidor" \
        "3 e 4 dao FPGA_TIMEOUT ...... FPGA nao programada, ou servidor antes dela" \
        "4 passa e 3 falha ........... hps_0.h desatualizado (gen_hps_header.py)" \
        "'Connection reset by peer' .. o servidor MORREU no meio da operacao." \
        "   quase sempre e binario da placa fora de sincronia com o bitstream" \
        "   -- por exemplo, servidor de 128 pontos contra FFT de 1024." \
        "   tente: ./morphe-up.sh --deploy --skip-fpga --board $ALVO" >&2
    return 1
}

# ---------------------------------------------------------------------------
# Acoes
# ---------------------------------------------------------------------------

acao_status() {
    if tether_vivo; then
        local linha
        while IFS= read -r linha; do
            [[ -n "$linha" ]] || continue
            ok "tether vivo em ${linha% *} (PGID ${linha##* }) -- FFT sem limite de tempo"
        done <<< "$(tethers_vivos)"
    else
        aviso "tether ausente -- se a FPGA foi programada ha mais de 1 h, a FFT devolve zeros"
    fi

    if [[ -f "$CONF_PLACAS" ]]; then
        local n; n="$(grep -c . "$CONF_PLACAS" || true)"
        (( n > 1 )) && printf '    placas conhecidas: %s\n' "$(tr '\n' ' ' < "$CONF_PLACAS")"
    fi
    if [[ -f "$CONF_PLACA" ]]; then
        local ip; ip="$(cat "$CONF_PLACA")"
        printf '    placa lembrada: %s\n' "$ip"
        if ssh "${SSH_OPTS[@]}" -o BatchMode=yes "$USUARIO_PLACA@$ip" \
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

    # RSA, e nao ed25519, de proposito: o sshd 6.0 das placas e anterior ao
    # 6.5, que foi quando o ed25519 apareceu. Uma chave ed25519 e aceita pelo
    # ssh-copy-id, gravada no authorized_keys e simplesmente ignorada na hora
    # de autenticar -- sem mensagem de erro, so a senha pedida de novo.
    if [[ -f "$CHAVE_MORPHE" ]]; then
        ok "chave ja existe: $CHAVE_MORPHE"
    else
        passo "criando uma chave RSA sem frase secreta (a placa nao le ed25519)"
        ssh-keygen -t rsa -b 4096 -N "" -f "$CHAVE_MORPHE" \
                   -C "morphe@$(hostname)" >/dev/null
        ok "criada: $CHAVE_MORPHE"
        SSH_OPTS+=(-i "$CHAVE_MORPHE" -o IdentitiesOnly=yes)
    fi

    passo "instalando a chave na placa -- esta e a ultima vez que pede senha"
    local opcoes=(-o StrictHostKeyChecking=accept-new)
    if ssh -G -o PubkeyAcceptedKeyTypes=+ssh-rsa localhost >/dev/null 2>&1; then
        opcoes+=(-o PubkeyAcceptedKeyTypes=+ssh-rsa)
    fi

    if command -v ssh-copy-id >/dev/null 2>&1; then
        ssh-copy-id "${opcoes[@]}" -i "$CHAVE_MORPHE.pub" "$USUARIO_PLACA@$ALVO"
    else
        ssh "${opcoes[@]}" "$USUARIO_PLACA@$ALVO" \
            "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys" \
            < "$CHAVE_MORPHE.pub"
    fi

    if ssh "${SSH_OPTS[@]}" -o BatchMode=yes "$USUARIO_PLACA@$ALVO" true 2>/dev/null; then
        ok "pronto: $USUARIO_PLACA@$ALVO entra sem senha"
        escrever_bloco_ssh_config "$ALVO"
        lembrar_placa "$ALVO"
        return 0
    fi

    erro "a chave foi enviada, mas o login sem senha ainda nao funciona."
    printf '       %s\n' "o que o ssh diz da negociacao:" >&2
    ssh "${SSH_OPTS[@]}" -v -o BatchMode=yes "$USUARIO_PLACA@$ALVO" true 2>&1 \
        | grep -E "remote software version|Offering|Authentications that can continue|no mutual" \
        | sed 's/^/       /' >&2 || true
    morrer "restam tres suspeitos, nesta ordem de probabilidade:" \
           "  1. permissoes: ~/.ssh precisa ser 700 e authorized_keys 600" \
           "  2. /etc/ssh/sshd_config: PubkeyAuthentication yes, PermitRootLogin yes" \
           "     e o usuario listado em AllowUsers, se a diretiva existir" \
           "  3. o home do usuario gravavel por grupo, que o StrictModes recusa" \
           "depois de mexer, reinicie com /etc/init.d/ssh restart"
}

# O morphe-up.sh entra sem senha porque passa a chave e o +ssh-rsa em cada
# chamada; um 'ssh root@placa' ou 'scp' digitado a mao nao passa nada disso e
# volta a pedir senha -- o OpenSSH 8.9 da estacao nem oferece a chave RSA por
# padrao. Este bloco no ~/.ssh/config da conta faz o ssh avulso usar o mesmo
# caminho. Um bloco por placa, entre marcas, para o --setup-ssh de novo (IP
# novo do DHCP, ou chave nova) substituir o antigo em vez de acumular.
escrever_bloco_ssh_config() {
    local ip="$1" cfg="$HOME/.ssh/config" tmp
    local ini="# >>> morphe $ip (escrito por morphe-up.sh --setup-ssh)"
    local fim="# <<< morphe $ip"
    tmp="$(mktemp)"
    if [[ -f "$cfg" ]]; then
        awk -v ini="$ini" -v fim="$fim" \
            '$0 == ini {pula=1} !pula {print} $0 == fim {pula=0}' "$cfg" > "$tmp"
    fi
    {
        # Uma linha em branco antes, se o arquivo nao terminar com uma.
        [[ -s "$tmp" ]] && [[ -n "$(tail -c1 "$tmp")" ]] && printf '\n'
        printf '%s\n' "$ini"
        printf 'Host %s\n' "$ip"
        printf '    User %s\n' "$USUARIO_PLACA"
        printf '    IdentityFile %s\n' "$CHAVE_MORPHE"
        printf '    IdentitiesOnly yes\n'
        if ssh -G -o PubkeyAcceptedKeyTypes=+ssh-rsa localhost >/dev/null 2>&1; then
            printf '    PubkeyAcceptedKeyTypes +ssh-rsa\n'
        fi
        printf '    StrictHostKeyChecking accept-new\n'
        printf '%s\n' "$fim"
    } >> "$tmp"
    mv "$tmp" "$cfg" && chmod 600 "$cfg"
    ok "bloco 'Host $ip' escrito em $cfg: ssh e scp avulsos entram sem senha"
}

# Existe servico de boot instalado nesta placa? Muda o que o --down deve fazer.
# Ecoa "systemd", "initd" ou nada.
tipo_de_servico() {
    ssh "${SSH_OPTS[@]}" -o BatchMode=yes "$USUARIO_PLACA@$1" \
        "if [ -f /etc/systemd/system/morphe-server.service ]; then echo systemd; \
         elif [ -f /etc/init.d/morphe-server ]; then echo initd; fi" 2>/dev/null || true
}

acao_down() {
    # O tether some sempre: ele segura uma licenca do Quartus, e e o unico
    # recurso que faz diferenca guardar quando ninguem esta usando a placa.
    passo "encerrando o tether"
    derrubar_tether

    [[ -f "$CONF_PLACA" ]] || { ok "pronto"; return 0; }
    local ip; ip="$(cat "$CONF_PLACA")"
    local servico; servico="$(tipo_de_servico "$ip")"

    if [[ -n "$servico" && $PARAR_SERVIDOR -eq 0 ]]; then
        # Com autostart instalado, derrubar o servidor e inutil e enganoso: no
        # systemd o Restart=always o traz de volta em segundos, e num init.d
        # ele fica morto ate o proximo boot -- e a placa some da descoberta,
        # que e justamente o que o autostart existe para garantir.
        ok "servidor mantido no ar em $ip (servico de boot: $servico)"
        printf '       %s\n' \
            "e assim que deve ser: e o que mantem a placa visivel na rede." \
            "para parar mesmo assim: ./morphe-up.sh --down --stop-server"
        ok "pronto"
        return 0
    fi

    passo "parando o servidor em $ip"
    if [[ -n "$servico" ]]; then
        # Pelo gerenciador, senao ele reinicia sozinho.
        ssh "${SSH_OPTS[@]}" "$USUARIO_PLACA@$ip" \
            "if [ '$servico' = systemd ]; then systemctl stop morphe-server; \
             else /etc/init.d/morphe-server stop; fi" \
            || aviso "nao consegui parar pelo servico"
        aviso "o servidor volta no proximo boot da placa"
    else
        ssh "${SSH_OPTS[@]}" "$USUARIO_PLACA@$ip" "pkill -x morphe_server || true" \
            || aviso "nao consegui falar com a placa; siga assim mesmo"
    fi
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
    lembrar_placa "$ALVO"

    if (( FORCA_DEPLOY )); then
        enviar_servidor
    elif servidor_confere; then
        ok "o servidor da placa confere com as fontes deste clone"
    else
        aviso "o servidor da placa nao confere com as fontes deste clone -- reenviando"
        enviar_servidor
    fi

    reiniciar_servidor
    verificar || exit 1

    printf '\n%sPlataforma pronta.%s  placa %s, porta %s\n' "$NEG" "$FIM" "$ALVO" "$PORTA"
    # O interpretador tem de ser o que o achar_python devolveu, nao um
    # ".venv/bin/python" fixo: numa instalacao de turma (/opt/morphe) o venv
    # nao existe e quem roda e o python3 do sistema. Mandar o usuario para um
    # caminho que nao existe desfaz a promessa de "um comando".
    local py_cliente; py_cliente="$(achar_python || true)"
    if [[ -n "$py_cliente" ]]; then
        printf 'Abra o cliente:  cd %s/Python && %s morphe_app.py\n' "$RAIZ" "$py_cliente"
    else
        aviso "nenhum Python encontrado para o cliente"
    fi
    printf 'Ao terminar:     ./morphe-up.sh --down\n'
}

# Depois que todas as funcoes existem, e antes de qualquer ssh.
montar_ssh_opts

case "$ACAO" in
    up)        acao_up ;;
    down)      acao_down ;;
    status)    acao_status ;;
    setup-ssh) acao_setup_ssh ;;
esac
