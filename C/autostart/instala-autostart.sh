#!/bin/sh
# instala-autostart.sh -- faz o morphe_server subir sozinho no boot da placa.
#
# Rode UMA VEZ POR PLACA, dentro da placa, como root:
#
#     scp -r C/autostart root@<ip>:morphe/
#     ssh root@<ip> 'cd morphe/autostart && sh instala-autostart.sh'
#
# Depois disso a placa sobe o servidor sozinha, e a descoberta pela rede passa a
# achar a placa sem ninguem precisar saber o IP -- que e o ponto da versao 1.2.
#
# Detecta systemd ou init.d sozinho; o Linux das DE1-SoC do laboratorio varia
# conforme a imagem gravada no cartao.
#
# Nao e preciso ter a FPGA programada para o servidor subir. No boot a FPGA
# carrega o bitstream de fabrica do cartao, e o servidor NAO PODE toca-la
# nesse estado: os PIOs do Morphe nao existem la, e um acesso a eles trava o
# barramento do HPS inteiro -- foi assim que a placa 2 sumiu da rede a cada
# boot em 17-21/09/2026. Por isso o servidor so acessa a FPGA depois que o
# morphe-up.sh, ao programar por JTAG, grava /var/run/morphe-fpga-preparada;
# ate la responde ao ping (com fpga_preparada=0) e recusa as operacoes com
# FPGA_NAO_PREPARADA. Servidor anterior a 21/09/2026 NAO pode ir no autostart.

set -eu

PORTA="${1:-5000}"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$DIR/morphe_server"

if [ ! -x "$BIN" ]; then
    echo "erro: nao achei o binario em $BIN" >&2
    echo "       compile antes: cd $DIR && make morphe_server" >&2
    exit 1
fi

if [ "$(id -u)" != "0" ]; then
    echo "erro: rode como root (o servidor mapeia /dev/mem)" >&2
    exit 1
fi

echo "==> binario: $BIN"
echo "==> porta:   $PORTA"

if command -v systemctl >/dev/null 2>&1 && [ -d /etc/systemd/system ]; then
    echo "==> init detectado: systemd"
    cat > /etc/systemd/system/morphe-server.service <<FIM
[Unit]
Description=Servidor Morphe (ponte entre o cliente e a FPGA)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart=$BIN $PORTA
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
FIM
    systemctl daemon-reload
    systemctl enable morphe-server.service
    systemctl restart morphe-server.service
    sleep 1
    systemctl --no-pager --lines=5 status morphe-server.service || true
else
    echo "==> init detectado: init.d"
    cat > /etc/init.d/morphe-server <<FIM
#!/bin/sh
### BEGIN INIT INFO
# Provides:          morphe-server
# Required-Start:    \$network \$remote_fs
# Required-Stop:     \$network \$remote_fs
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: Servidor Morphe
### END INIT INFO

DIR=$DIR
BIN=$BIN
PORTA=$PORTA
PIDFILE=/var/run/morphe-server.pid

case "\$1" in
  start)
    echo "Iniciando morphe-server"
    cd "\$DIR" || exit 1
    nohup "\$BIN" "\$PORTA" > "\$DIR/morphe_server.log" 2>&1 &
    echo \$! > "\$PIDFILE"
    ;;
  stop)
    echo "Parando morphe-server"
    [ -f "\$PIDFILE" ] && kill "\$(cat "\$PIDFILE")" 2>/dev/null
    rm -f "\$PIDFILE"
    pkill -f morphe_server 2>/dev/null || true
    ;;
  restart)
    "\$0" stop
    sleep 1
    "\$0" start
    ;;
  status)
    pgrep -f morphe_server > /dev/null && echo "no ar" || echo "parado"
    ;;
  *)
    echo "uso: \$0 {start|stop|restart|status}"
    exit 1
    ;;
esac
exit 0
FIM
    chmod +x /etc/init.d/morphe-server
    if command -v update-rc.d >/dev/null 2>&1; then
        update-rc.d morphe-server defaults
    elif command -v chkconfig >/dev/null 2>&1; then
        chkconfig --add morphe-server
    else
        echo "aviso: nem update-rc.d nem chkconfig; ligue o servico a mao" >&2
    fi
    /etc/init.d/morphe-server restart
    sleep 1
    /etc/init.d/morphe-server status
fi

echo
echo "Pronto. Confira depois de um reboot:"
echo "    ssh root@<ip> 'pgrep -f morphe_server'"
