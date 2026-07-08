#!/usr/bin/env python3
"""
morphe_ping — ferramenta de bring-up para validar a conexão com o Morphe
              server rodando no HPS.

Faz 4 testes em sequência, reportando claramente onde (se) falhou:

    1. TCP reachable         — consegue abrir conexão na porta?
    2. Protocolo responde    — servidor fala Morphe (magic 'MRPN')?
    3. Convolução impulso    — h = δ[n], x = qualquer → y == x?
    4. FFT impulso           — x = δ[n] → |X[k]| constante?

O teste 3 verifica o pipeline completo: Q15.16 encode, SRAMs, FSM da
conv1d, BFP (se aplicável), decode. Se só o 3 ou 4 falham, o problema
é no hardware; se 1 ou 2 falham, é rede/servidor.

Uso:
    morphe_ping <host> [porta]
    morphe_ping 192.168.1.10
    morphe_ping 127.0.0.1 5000
"""
from __future__ import annotations

import socket
import sys
import time
from typing import Callable

import numpy as np

# importa as peças do cliente
sys.path.insert(0, ".")
sys.path.insert(0, "./morphe_app")
try:
    import dsp_core as dsp
    from morphe_protocol import (
        TcpClient, build_conv_request, build_fft_request,
        decode_fft_response, DTYPE_INT32, DTYPE_FLOAT32,
    )
except ImportError:
    print("ERRO: não achei morphe_protocol.py / dsp_core.py no path.")
    print("Rode este script do diretório raiz do projeto,")
    print("ou de dentro de morphe_app/.")
    sys.exit(2)


# =============================================================================
# UI do terminal
# =============================================================================

BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str, hint: str = "") -> None:
    print(f"  {RED}✗{RESET} {msg}")
    if hint:
        print(f"    {DIM}{hint}{RESET}")


def step(num: int, title: str) -> None:
    print(f"\n{BOLD}[{num}] {title}{RESET}")


# =============================================================================
# Testes
# =============================================================================

def test_1_tcp_reachable(host: str, port: int) -> bool:
    step(1, "TCP reachable")
    try:
        with socket.create_connection((host, port), timeout=3) as s:
            s.close()
        ok(f"porta {port} em {host} aceita conexões")
        return True
    except socket.timeout:
        fail("timeout de 3s", "o host está na rede mas não responde na porta")
        return False
    except ConnectionRefusedError:
        fail("connection refused",
             f"servidor não está rodando em {host}:{port}? tente "
             f"'ssh <host> sudo ./morphe_server {port}'")
        return False
    except socket.gaierror as e:
        fail(f"não foi possível resolver '{host}': {e}",
             "verifique o IP/hostname")
        return False
    except OSError as e:
        fail(f"erro de rede: {e}")
        return False


def test_2_protocol_magic(host: str, port: int) -> bool:
    step(2, "Protocolo Morphe respondendo")
    try:
        # enviamos um request intencionalmente inválido (opcode desconhecido)
        # para provocar uma resposta com magic MRPN sem gastar o hardware
        import struct
        bad_req = struct.pack(
            ">IHHHHII",
            0x4D52504D,  # MRPM correto
            1,            # version
            99,           # opcode desconhecido (força erro)
            2,            # dtype float32
            0,            # flags
            0, 0,         # n_x=0, n_h=0
        )
        with socket.create_connection((host, port), timeout=3) as s:
            s.sendall(bad_req)
            hdr = b""
            while len(hdr) < 20:
                chunk = s.recv(20 - len(hdr))
                if not chunk:
                    break
                hdr += chunk
            if len(hdr) < 20:
                fail("servidor fechou a conexão sem responder",
                     "servidor pode ter crashado — cheque os logs")
                return False
            magic = int.from_bytes(hdr[:4], "big")
            if magic != 0x4D52504E:  # MRPN
                fail(f"magic de resposta inesperado: 0x{magic:08X}",
                     "o servidor rodando aí não é o Morphe server")
                return False
            status = int.from_bytes(hdr[10:12], "big")
            if status == 0:
                fail("esperava erro (opcode inválido), veio OK",
                     "protocolo inconsistente — versão errada?")
                return False
        ok(f"magic MRPN correto, status de erro bem-formado")
        return True
    except Exception as e:
        fail(f"exceção: {e}")
        return False


def test_3_conv_impulse(host: str, port: int) -> bool:
    step(3, "Convolução com impulso (h = δ[n])")
    try:
        client = TcpClient(host, port, timeout=5)
        # qualquer x; h é um impulso unitário → y deve ser == x (com um shift de 0)
        x = np.array([1.5, -2.25, 0.5, 3.75, -1.0], dtype=np.float64)
        h = np.array([1.0], dtype=np.float64)
        x_q = dsp.float_to_q1516(x).astype(np.float64)
        h_q = dsp.float_to_q1516(h).astype(np.float64)
        req = build_conv_request(x_q, h_q, DTYPE_INT32)
        t0 = time.monotonic()
        resp = client.request(req)
        dt_ms = (time.monotonic() - t0) * 1000
        if not resp.ok:
            fail(f"servidor retornou erro: {resp.payload.decode('utf-8', 'replace')}",
                 "pode ser limite de tamanho ou timeout da FPGA")
            return False
        y_q = np.frombuffer(resp.payload, dtype=">i4", count=resp.n_out)
        y = dsp.q1516_to_float(y_q)
        err = np.max(np.abs(y - x))
        if err > 1e-3:
            fail(f"y != x, erro máximo = {err:.4e}",
                 "conv1d produziu resultado inconsistente — "
                 "hardware ou FSM com bug?")
            print(f"    x = {x}")
            print(f"    y = {y}")
            return False
        ok(f"y == x (erro {err:.2e}), resposta em {dt_ms:.1f} ms")
        return True
    except Exception as e:
        fail(f"exceção: {e}")
        return False


def test_4_fft_impulse(host: str, port: int) -> bool:
    step(4, "FFT com impulso (x = δ[n] → |X[k]| constante)")
    try:
        client = TcpClient(host, port, timeout=5)
        x = np.zeros(64, dtype=np.float64)
        x[0] = 0.5  # impulso (amplitude 0.5 para caber confortavelmente em Q1.7)
        req = build_fft_request(x, DTYPE_FLOAT32)
        t0 = time.monotonic()
        resp = client.request(req)
        dt_ms = (time.monotonic() - t0) * 1000
        if not resp.ok:
            fail(f"servidor retornou erro: {resp.payload.decode('utf-8', 'replace')}")
            return False
        X = decode_fft_response(resp)
        mag = np.abs(X)
        # espectro do impulso deve ser plano (magnitude constante = amplitude)
        spread = (np.max(mag) - np.min(mag)) / max(np.mean(mag), 1e-9)
        if spread > 0.2:  # > 20% de variação entre bins é suspeito
            fail(f"espectro do impulso não é plano: "
                 f"min={np.min(mag):.3f}, max={np.max(mag):.3f}",
                 "possíveis causas: BFP exponent com sinal trocado, "
                 "janela aplicada por engano, bug no FFT wrapper")
            return False
        ok(f"|X[k]| plano (variação {spread*100:.1f}%), "
           f"magnitude ~ {np.mean(mag):.3f}, resposta em {dt_ms:.1f} ms")
        return True
    except Exception as e:
        fail(f"exceção: {e}")
        return False


# =============================================================================
# main
# =============================================================================

def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 1

    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000

    print(f"{BOLD}Morphe ping → {host}:{port}{RESET}")

    tests: list[Callable[[str, int], bool]] = [
        test_1_tcp_reachable,
        test_2_protocol_magic,
        test_3_conv_impulse,
        test_4_fft_impulse,
    ]

    results = []
    for t in tests:
        passed = t(host, port)
        results.append(passed)
        if not passed:
            # se um teste mais básico falha, os seguintes provavelmente
            # vão falhar pelas mesmas razões — abortamos
            print(f"\n{YELLOW}Abortando — conserte o problema acima antes de continuar.{RESET}")
            break

    n_ok = sum(results)
    n_total = len(tests)
    print()
    if all(results):
        print(f"{GREEN}{BOLD}✓ Todos os {n_total} testes passaram. "
              f"Morphe está operacional.{RESET}")
        return 0
    else:
        print(f"{RED}{BOLD}✗ {n_ok}/{n_total} testes passaram.{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
