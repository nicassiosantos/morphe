"""
estado_placas -- o que cada placa do laboratorio esta fazendo agora.

Pergunta a porta de estado (UDP, porta TCP + 1) de cada placa: livre ou
ocupada, qual operacao e ha quanto tempo, de qual computador, e quantos
computadores a usaram no ultimo minuto. Nao entra na fila das placas e nao
toca a FPGA: pode rodar a qualquer momento, com a turma usando.

    python3 ferramentas/estado_placas.py                 # as placas da lista
    python3 ferramentas/estado_placas.py 172.16.230.24   # so esta
    python3 ferramentas/estado_placas.py --seguir        # atualiza a cada 1 s

Sem argumentos, usa o placas.conf (versionado) e o .morphe-estado/placas.
Placa que nao responde: fora do ar, ou com servidor anterior a 28/09/2026
(sem a porta de estado) -- nesse caso o OP_PING diz qual das duas.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import sys
import time

import _caminho  # noqa: F401  (poe Python/ no caminho de importacao)
from morphe_protocol import (TcpClient, build_ping_request, consultar_estado,
                             decode_ping_response)
from tcp_panel import ler_placas_conhecidas


def linha(ip: str, porta: int) -> str:
    e = consultar_estado(ip, porta)
    if e is not None:
        extra = ""
        if e.ocupada and e.info.get("cliente"):
            extra = f"  [de {e.info['cliente']}]"
        return (f"{ip:<16} {e.hostname:<12} {e.descricao()}{extra}"
                f"  (atendeu {e.info.get('atendidas', '?')} operações)")
    try:
        info = decode_ping_response(
            TcpClient(ip, porta, timeout=2.0).request(build_ping_request()))
        return (f"{ip:<16} {info.get('hostname', '?'):<12} responde ao PING, mas não "
                f"na porta de estado (UDP {porta + 1}): servidor antigo "
                "(./morphe-up.sh --deploy) ou UDP bloqueado na rede")
    except Exception:
        return f"{ip:<16} {'?':<12} não responde (desligada, fora da rede, ou ocupada há mais de 2 s)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("placas", nargs="*", help="IPs; sem nada, placas.conf e .morphe-estado/placas")
    ap.add_argument("--porta", type=int, default=5000)
    ap.add_argument("--seguir", action="store_true", help="repete a cada 1 s (Ctrl+C sai)")
    a = ap.parse_args()
    ips = a.placas or ler_placas_conhecidas()
    if not ips:
        print("nenhuma placa: informe os IPs, ou rode o morphe-up.sh nesta instalação")
        return 2
    with cf.ThreadPoolExecutor(max_workers=len(ips)) as pool:
        while True:
            linhas = list(pool.map(lambda ip: linha(ip, a.porta), ips))
            if a.seguir:
                print("\033[2J\033[H" + time.strftime("%H:%M:%S"), flush=True)
            print("\n".join(linhas), flush=True)
            if not a.seguir:
                return 0
            try:
                time.sleep(1.0)
            except KeyboardInterrupt:
                return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
