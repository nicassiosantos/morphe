# -*- coding: utf-8 -*-
"""Corrige o opcode FIR ausente e o limite da memoria fir_yn. Rode dentro de morphe/C."""
import io, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
PING = '#define MORPHE_OP_PING     3U   /* descoberta de servico */\n'
ASSERT = '_Static_assert(FIR_YN_SPAN      >= MORPHE_CONV_%s * (int)sizeof(int32_t), "Erro");'
GUARDA = 'if (n_out > %s) return send_error(sock, MORPHE_OP_FIR, MORPHE_STATUS_BAD_SIZE, "FIR: sa\u00edda %s");'

EDICOES = {
    "morphe_protocol.h": [
        (PING, PING + '#define MORPHE_OP_FIR      4U   /* filtro FIR (igual ao OP_FIR=4 do cliente) */\n'),
    ],
    "morphe_server.c": [
        ('\n_Static_assert(FFT_XN_RE_SPAN',
         '\n/* Saida maxima do FIR: a memoria fir_yn do hardware tem 512 B = 128 amostras. */\n'
         '#define MORPHE_FIR_Y_MAX  ((int)(FIR_YN_SPAN / sizeof(int32_t)))\n'
         '\n_Static_assert(FFT_XN_RE_SPAN'),
        (ASSERT % "Y_MAX",
         '/* fir_yn nao comporta MORPHE_CONV_Y_MAX; o limite real vale em handle_fir(). */\n'
         + ASSERT % "N_MAX"),
        (GUARDA % ("MORPHE_CONV_Y_MAX", "> 255"),
         GUARDA % ("(uint32_t) MORPHE_FIR_Y_MAX",
                   "acima da mem\u00f3ria fir_yn (128 amostras)")),
    ],
}
EDICOES["morphe_server_handling_sigs.c"] = EDICOES["morphe_server.c"]

for nome, pares in EDICOES.items():
    p = os.path.join(BASE, nome)
    if not os.path.exists(p):
        print("ausente (ignorado):", nome)
        continue
    s = io.open(p, encoding="utf-8").read()
    for velho, novo in pares:
        if novo in s:
            continue
        if velho not in s:
            print("NAO ENCONTRADO em %s: %s..." % (nome, velho.strip()[:60]))
            sys.exit(1)
        s = s.replace(velho, novo, 1)
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)
    print("ok:", nome)
