# -*- coding: utf-8 -*-
"""Faz o servidor responder erro em vez de fechar a conexao calado.

Emite os status BAD_MAGIC, BAD_VERSION e BAD_OPCODE, que o protocolo ja
declarava e que o morphe_ping.py (teste 2) espera. Rode dentro de morphe/C.
"""
import io, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))

VELHO = """    if (magic != MORPHE_MAGIC_REQ) return;
    if (ver != MORPHE_VERSION) return;

    switch (opcode) {"""

NOVO = """    if (magic != MORPHE_MAGIC_REQ) {
        send_error(sock, opcode, MORPHE_STATUS_BAD_MAGIC, "magic invalido");
        return;
    }
    if (ver != MORPHE_VERSION) {
        send_error(sock, opcode, MORPHE_STATUS_BAD_VERSION, "versao de protocolo nao suportada");
        return;
    }

    switch (opcode) {"""

VELHO2 = """        case MORPHE_OP_PING: handle_ping(sock); break;
    }"""

NOVO2 = """        case MORPHE_OP_PING: handle_ping(sock); break;
        default:
            send_error(sock, opcode, MORPHE_STATUS_BAD_OPCODE, "opcode desconhecido");
            break;
    }"""

for nome in ("morphe_server.c", "morphe_server_handling_sigs.c"):
    p = os.path.join(BASE, nome)
    if not os.path.exists(p):
        print("ausente (ignorado):", nome)
        continue
    s = io.open(p, encoding="utf-8").read()
    for velho, novo in ((VELHO, NOVO), (VELHO2, NOVO2)):
        if novo in s:
            continue
        if velho not in s:
            print("NAO ENCONTRADO em %s" % nome)
            sys.exit(1)
        s = s.replace(velho, novo, 1)
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)
    print("ok:", nome)
