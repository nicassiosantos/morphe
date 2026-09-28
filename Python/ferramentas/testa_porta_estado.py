"""
testa_porta_estado -- confere a porta de estado (UDP 5001) numa placa de verdade.

    python3 ferramentas/testa_porta_estado.py 172.16.230.24

O que confere, em ordem:
  1. a placa responde na porta de estado, livre e preparada;
  2. durante uma captura continua do ADC de 3 s, a porta de estado responde NA
     HORA "ocupada / captura contínua do ADC", com o tempo andando e este
     computador como cliente -- enquanto um OP_PING, no mesmo momento, fica
     esperando na fila (era isso que o cliente nao sabia distinguir);
  3. terminada a captura, a placa volta a "livre" e conta a operacao.

Se a placa nao tiver o ADC, o passo 2 usa convolucoes seguidas no lugar
da captura (mais curtas, mas o suficiente para ver "ocupada").
"""
from __future__ import annotations

import socket
import sys
import threading
import time

import numpy as np

import _caminho  # noqa: F401
import aquisicao as aq
from morphe_protocol import (DTYPE_CODES, TcpClient, build_conv_request,
                             build_ping_request, consultar_estado,
                             decode_ping_response)

falhas: list[str] = []


def confere(cond: bool, msg: str) -> None:
    print(("ok    " if cond else "FALHA ") + msg, flush=True)
    if not cond:
        falhas.append(msg)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ip = sys.argv[1]
    porta = int(sys.argv[2]) if len(sys.argv) > 2 else 5000

    # 1. em repouso
    e = consultar_estado(ip, porta, timeout=1.0)
    if e is None:
        print(f"FALHA a placa {ip} não respondeu na porta de estado (UDP {porta + 1}).")
        try:
            TcpClient(ip, porta, timeout=3).request(build_ping_request())
            print("      Mas respondeu ao PING: o servidor é o antigo (rode "
                  "./morphe-up.sh --deploy) ou a rede bloqueia UDP.")
        except Exception:
            print("      E também não respondeu ao PING: a placa está fora do ar.")
        return 1
    confere(True, f"responde: {e.hostname}, {e.descricao()}")
    confere(e.preparada, "FPGA preparada")
    if e.ocupada:
        print("aviso  a placa já está ocupada por outro computador; o teste espera "
              "ela ficar livre")
        for _ in range(60):
            time.sleep(1)
            e = consultar_estado(ip, porta)
            if e is not None and not e.ocupada:
                break
    atendidas0 = int(e.info.get("atendidas", "0"))
    confere(e.rtt_s < 0.2, f"resposta em {e.rtt_s * 1000:.1f} ms")

    # 2. ocupada
    info = decode_ping_response(TcpClient(ip, porta, timeout=5).request(build_ping_request()))
    tem_adc = int(info.get("adc_n_max", "0")) > 0
    cliente = TcpClient(ip, porta, timeout=10)
    parar = threading.Event()
    if tem_adc:
        esperado = "captura contínua do ADC"
        trabalho = threading.Thread(target=lambda: aq.capturar_continuo(
            cliente, 0, 20000, aq.MODO_SIMPLES, 0, parar=parar,
            guardar=False, acumular=False), daemon=True)
    else:
        esperado = "convolução"
        x = np.zeros(1024, dtype=np.int32)
        req = build_conv_request(x, x, DTYPE_CODES["int32"])

        def convolucoes():
            while not parar.is_set():
                cliente.request(req)
        trabalho = threading.Thread(target=convolucoes, daemon=True)
    trabalho.start()
    time.sleep(1.5)
    e = consultar_estado(ip, porta)
    confere(e is not None and e.ocupada and e.operacao == esperado,
            f"durante: {e.descricao() if e else 'sem resposta'}")
    if e is not None and tem_adc:
        confere(1.0 <= e.ha_s <= 3.0, f"tempo andando: há {e.ha_s:.1f} s")
    if e is not None:
        meu_ip = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        meu_ip.connect((ip, porta))
        confere(e.info.get("cliente") == meu_ip.getsockname()[0],
                f"cliente = {e.info.get('cliente')} (este computador)")
        meu_ip.close()
        confere(e.rtt_s < 0.2, f"resposta imediata mesmo ocupada ({e.rtt_s * 1000:.1f} ms)")
    if tem_adc:
        t0 = time.monotonic()
        try:
            TcpClient(ip, porta, timeout=1.0).request(build_ping_request())
            confere(False, "o PING deveria esperar na fila durante a captura")
        except Exception:
            confere(True, f"o PING espera na fila ({time.monotonic() - t0:.1f} s sem "
                          "resposta), a porta de estado não")
    time.sleep(1.5)
    parar.set()
    trabalho.join(timeout=10)

    # 3. livre de novo
    time.sleep(0.5)
    e = consultar_estado(ip, porta)
    confere(e is not None and not e.ocupada, f"depois: {e.descricao() if e else '?'}")
    if e is not None:
        confere(int(e.info.get("atendidas", "0")) > atendidas0,
                f"operações atendidas: {atendidas0} -> {e.info.get('atendidas')}")
        confere(e.clientes_recentes >= 1, f"computadores no último minuto: {e.clientes_recentes}")
    print("TUDO OK" if not falhas else f"{len(falhas)} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
