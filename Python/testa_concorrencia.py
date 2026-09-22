#!/usr/bin/env python3
"""
testa_concorrencia -- varias requisicoes ao mesmo tempo, para saber o que a
                      infraestrutura aguenta HOJE.

O servidor da placa atende **uma conexao por vez** (laco accept/atende/close,
sem thread nem fork) e o `listen()` tem fila 4. O cliente abre e fecha uma
conexao **por operacao**. Disso decorre tudo que este teste mede:

  * dois clientes na MESMA placa nao tomam erro -- esperam na fila, e a
    latencia de cada um cresce com a fila. Medido em 22/09/2026 na placa 2:
    6 clientes simultaneos deram 5,1x a latencia de placa vazia, com zero
    falhas -- `listen(4)` no Linux guarda backlog+1 = 5 esperando, e o 6o e
    justamente o que esta sendo atendido;
  * o limite comeca no 7o cliente simultaneo, e no Linux ele NAO aparece como
    ECONNREFUSED: o kernel descarta o SYN calado e o cliente retransmite ~1 s
    depois. O sintoma e um pico de latencia, nao um erro -- ainda nao medido;
  * com duas placas, dividir os clientes entre elas e o que devolve a
    latencia de placa vazia.

O teste roda em duas fases: primeiro sozinho (uma requisicao por vez), para
ter a linha de base da placa vazia; depois com N clientes em paralelo. O
veredito compara as duas medianas -- se a fila serializa, a mediana com N
clientes na mesma placa fica perto de N vezes a de um sozinho.

Cada requisicao e verificada, nao so cronometrada: a convolucao usa
h = delta[n] (a saida tem que ser identica a entrada) e a FFT usa
x = delta[n] (o espectro tem que ser plano). Uma resposta trocada entre
conexoes concorrentes apareceria como erro de valor, nao como lentidao.

Uso tipico -- no laboratorio e no notebook AO MESMO TEMPO, cada um com sua
etiqueta, para ver as duas maquinas disputando as mesmas placas:

    python3 testa_concorrencia.py --clientes 3 --etiqueta lab
    python3 testa_concorrencia.py --clientes 3 --etiqueta notebook

Outros usos:

    python3 testa_concorrencia.py --modo mesma --clientes 8   # mede a fila
    python3 testa_concorrencia.py --modo dividir --clientes 4 # uma placa cada
    python3 testa_concorrencia.py --modo escolher --clientes 4  # como o app
    python3 testa_concorrencia.py --placas 172.16.230.24,172.16.230.52
"""
from __future__ import annotations

import argparse
import csv
import os
import platform
import socket
import statistics
import sys
import threading
import time
from dataclasses import dataclass

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dsp_core as dsp
from morphe_protocol import (
    DTYPE_INT32, TcpClient, build_conv_request, build_fft_request,
    build_ping_request, decode_conv_response, decode_fft_response,
    decode_ping_response, discover_servers, subredes_provaveis,
)
from tcp_panel import ler_placa_lembrada, ler_placas_conhecidas

PORTA_PADRAO = 5000


# ---------------------------------------------------------------------------
# Uma requisicao: o que foi pedido, quanto demorou, e se a resposta confere
# ---------------------------------------------------------------------------

@dataclass
class Resultado:
    cliente: int
    rodada: int
    placa: str
    op: str
    ms: float
    ok: bool
    erro: str = ""       # vazio quando ok
    classe: str = ""     # valor | recusada | timeout | rede | servidor


def _classifica(exc: BaseException) -> str:
    """A diferenca entre estes casos e o que o teste existe para mostrar."""
    if isinstance(exc, socket.timeout):
        return "timeout"
    if isinstance(exc, ConnectionRefusedError):
        return "recusada"     # fila do listen() cheia, ou servidor fora do ar
    if isinstance(exc, OSError):
        return "rede"
    return "erro"


def uma_conv(placa: str, porta: int, n: int, timeout: float) -> float:
    """Convolucao com h = delta[n]: y tem que ser identico a x."""
    x = np.linspace(-1.0, 1.0, n, dtype=np.float64)
    h = np.array([1.0], dtype=np.float64)
    x_q = dsp.float_to_q1516(x).astype(np.float64)
    h_q = dsp.float_to_q1516(h).astype(np.float64)
    req = build_conv_request(x_q, h_q, DTYPE_INT32)

    t0 = time.monotonic()
    resp = TcpClient(placa, porta, timeout=timeout).request(req)
    ms = (time.monotonic() - t0) * 1000.0

    if not resp.ok:
        raise RuntimeError(resp.payload.decode("utf-8", "replace"))
    y = dsp.q1516_to_float(decode_conv_response(resp))
    if y.size != n or not np.allclose(y, x, atol=1e-3):
        raise ValueError(f"CONV devolveu {y.size} amostras que nao batem com x")
    return ms


def uma_fft(placa: str, porta: int, n: int, timeout: float) -> float:
    """FFT de um impulso: |X[k]| tem que ser plano."""
    x = np.zeros(n, dtype=np.float64)
    x[0] = 1.0
    req, escala = build_fft_request(x)

    t0 = time.monotonic()
    resp = TcpClient(placa, porta, timeout=timeout).request(req)
    ms = (time.monotonic() - t0) * 1000.0

    if not resp.ok:
        raise RuntimeError(resp.payload.decode("utf-8", "replace"))
    mag = np.abs(decode_fft_response(resp, escala))
    if mag.size != n:
        raise ValueError(f"FFT devolveu {mag.size} bins, esperava {n}")
    variacao = (mag.max() - mag.min()) / max(mag.mean(), 1e-12)
    if variacao > 0.05:
        raise ValueError(f"|X[k]| nao esta plano (variacao {variacao:.1%})")
    return ms


def sonda(placa: str, porta: int, timeout: float = 2.0) -> float:
    """Quanto o OP_PING demora -- e a mesma medida que o app usa para
    escolher a placa mais livre. Devolve ms, ou float('inf') se falhar."""
    try:
        t0 = time.monotonic()
        resp = TcpClient(placa, porta, timeout=timeout).request(build_ping_request())
        decode_ping_response(resp)
        return (time.monotonic() - t0) * 1000.0
    except Exception:
        return float("inf")


# ---------------------------------------------------------------------------
# Descobrir contra quais placas rodar
# ---------------------------------------------------------------------------

def resolver_placas(arg: str, porta: int) -> list[str]:
    if arg and arg != "auto":
        return [ip.strip() for ip in arg.split(",") if ip.strip()]

    # A lista do .morphe-estado/placas so existe na maquina que rodou o
    # morphe-up.sh. Num notebook ela vem vazia, e ai a varredura resolve --
    # mas ela para na PRIMEIRA placa que acha, entao para ver as duas de um
    # notebook o caminho honesto e passar --placas.
    conhecidas = ler_placas_conhecidas()
    if conhecidas:
        return conhecidas
    lembrada = ler_placa_lembrada()
    if lembrada:
        return [lembrada]

    print("nenhuma placa conhecida neste clone; varrendo a rede...", flush=True)
    achados = discover_servers(subredes_provaveis(None), port=porta,
                               stop_on_first=False)
    return [s.ip for s in achados]


def placas_preparadas(placas: list[str], porta: int) -> list[str]:
    """So entram no teste as placas com o bitstream do Morphe programado.
    Uma placa recem-ligada responde ao PING e recusa as operacoes."""
    prontas = []
    for ip in placas:
        # Duas tentativas, a segunda com folga: em 22/09/2026 uma placa que
        # estava no ar perdeu o primeiro PING de 3 s (estacao recem-ligada) e
        # ficou de fora do teste inteiro, o que so se percebeu depois.
        info = None
        for tentativa, tempo in enumerate((3.0, 8.0), start=1):
            try:
                resp = TcpClient(ip, porta, timeout=tempo).request(build_ping_request())
                info = decode_ping_response(resp)
                if tentativa > 1:
                    print(f"  ! {ip}: respondeu so na 2a tentativa "
                          f"(a primeira estourou em 3 s)")
                break
            except Exception as e:
                erro = e
        if info is None:
            print(f"  - {ip}: nao respondeu ao PING em 2 tentativas ({erro})")
            continue
        if info.get("fpga_preparada", "1") == "0":
            print(f"  - {ip}: no ar, mas a FPGA nao esta preparada "
                  f"(rode ./morphe-up.sh --board {ip})")
            continue
        print(f"  + {ip}: {info.get('hostname', '?')}, "
              f"versao {info.get('version', '?')}, "
              f"no ar ha {info.get('uptime_s', '?')} s")
        prontas.append(ip)
    return prontas


# ---------------------------------------------------------------------------
# As duas fases
# ---------------------------------------------------------------------------

def executa(placa_de, ops, clientes: int, rodadas: int, porta: int,
            n: int, timeout: float, etiqueta: str) -> list[Resultado]:
    """Dispara clientes x rodadas requisicoes. `placa_de(cliente, rodada)`
    decide a placa de cada uma -- e o que separa os modos."""
    resultados: list[Resultado] = []
    trava = threading.Lock()
    largada = threading.Barrier(clientes)

    def trabalhador(c: int):
        # A barreira faz os clientes saírem juntos: sem ela, o primeiro
        # termina antes de o ultimo comecar e nao ha concorrencia nenhuma.
        largada.wait()
        for r in range(rodadas):
            placa = placa_de(c, r)
            op = ops[(c + r) % len(ops)]
            fn = uma_conv if op == "conv" else uma_fft
            try:
                ms = fn(placa, porta, n, timeout)
                res = Resultado(c, r, placa, op, ms, True)
            except Exception as e:
                classe = "valor" if isinstance(e, ValueError) else (
                    "servidor" if isinstance(e, RuntimeError) else _classifica(e))
                res = Resultado(c, r, placa, op, 0.0, False, str(e), classe)
            with trava:
                resultados.append(res)

    fios = [threading.Thread(target=trabalhador, args=(c,), daemon=True)
            for c in range(clientes)]
    t0 = time.monotonic()
    for f in fios:
        f.start()
    for f in fios:
        f.join()
    executa.segundos = time.monotonic() - t0
    return resultados


def resume(nome: str, res: list[Resultado]) -> dict:
    bons = [r.ms for r in res if r.ok]
    ruins = [r for r in res if not r.ok]
    d = {"nome": nome, "total": len(res), "ok": len(bons), "falhas": len(ruins)}
    if bons:
        bons_ord = sorted(bons)
        d["mediana"] = statistics.median(bons_ord)
        d["p95"] = bons_ord[min(len(bons_ord) - 1, int(0.95 * len(bons_ord)))]
        d["max"] = bons_ord[-1]
        d["min"] = bons_ord[0]
    return d


def imprime(d: dict) -> None:
    if d["ok"]:
        print(f"  {d['nome']:<28} {d['ok']:>4} ok  "
              f"mediana {d['mediana']:7.1f} ms   p95 {d['p95']:7.1f} ms   "
              f"max {d['max']:7.1f} ms")
    else:
        print(f"  {d['nome']:<28} {d['ok']:>4} ok")
    if d["falhas"]:
        print(f"  {'':<28} {d['falhas']:>4} FALHAS")


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Mede o que a infraestrutura das placas aguenta com "
                    "varias requisicoes ao mesmo tempo.")
    ap.add_argument("--placas", default="auto",
                    help="IPs separados por virgula, ou 'auto' (padrao): le o "
                         ".morphe-estado/placas e, se vazio, varre a rede")
    ap.add_argument("--porta", type=int, default=PORTA_PADRAO)
    ap.add_argument("--clientes", type=int, default=4,
                    help="quantas requisicoes simultaneas (padrao 4)")
    ap.add_argument("--rodadas", type=int, default=8,
                    help="quantas requisicoes cada cliente faz (padrao 8)")
    ap.add_argument("--modo", choices=("dividir", "mesma", "escolher"),
                    default="dividir",
                    help="dividir: um cliente por placa, em rodizio (padrao); "
                         "mesma: todos na primeira placa, para medir a fila; "
                         "escolher: cada requisicao sonda e vai na mais livre, "
                         "como o app faz ao conectar")
    ap.add_argument("--n", type=int, default=1024,
                    help="tamanho do sinal (padrao 1024)")
    ap.add_argument("--timeout", type=float, default=15.0,
                    help="timeout de cada requisicao, em segundos (padrao 15)")
    ap.add_argument("--etiqueta", default=platform.node(),
                    help="nome desta maquina na saida (padrao: hostname)")
    ap.add_argument("--csv", default="",
                    help="grava uma linha por requisicao neste arquivo")
    ap.add_argument("--sem-linha-de-base", action="store_true",
                    help="pula a fase sozinho (util quando outra maquina ja "
                         "esta martelando as placas)")
    args = ap.parse_args()

    print(f"=== testa_concorrencia  [{args.etiqueta}]  {time.strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"placas conhecidas: procurando...")
    placas = resolver_placas(args.placas, args.porta)
    if not placas:
        print("nenhuma placa encontrada. Rode ./morphe-up.sh, ou passe --placas <ip>.")
        return 1
    placas = placas_preparadas(placas, args.porta)
    if not placas:
        print("nenhuma placa preparada. Rode ./morphe-up.sh --board <ip>.")
        return 1
    if args.modo == "mesma":
        placas = placas[:1]

    print(f"\nmodo {args.modo} | {len(placas)} placa(s) | {args.clientes} clientes "
          f"| {args.rodadas} rodadas | N={args.n}")

    ops = ["conv", "fft"]

    # ---- fase 1: uma de cada vez, para ter a linha de base --------------
    base = {}
    if not args.sem_linha_de_base:
        print("\n[1] sozinho -- uma requisicao por vez, placa vazia")
        for ip in placas:
            res = executa(lambda c, r, ip=ip: ip, ops, 1, max(4, args.rodadas // 2),
                          args.porta, args.n, args.timeout, args.etiqueta)
            d = resume(f"{ip} sozinho", res)
            imprime(d)
            convs = [r.ms for r in res if r.ok and r.op == "conv"]
            base[ip] = statistics.median(convs) if convs else None

    # ---- fase 2: todos juntos -------------------------------------------
    print(f"\n[2] concorrente -- {args.clientes} requisicoes ao mesmo tempo")
    if args.modo == "escolher":
        def placa_de(c, r):
            # Mesma regra do app: sonda todas e fica com a que respondeu
            # mais rapido. Aqui isso acontece a cada requisicao, o que e
            # mais agressivo do que o app (que escolhe uma vez, ao abrir).
            return min(placas, key=lambda ip: sonda(ip, args.porta))
    else:
        def placa_de(c, r):
            return placas[(c + r) % len(placas)]

    res = executa(placa_de, ops, args.clientes, args.rodadas,
                  args.porta, args.n, args.timeout, args.etiqueta)
    segundos = executa.segundos

    geral = resume("todos os clientes", res)
    imprime(geral)
    for ip in placas:
        so_dela = [r for r in res if r.placa == ip]
        if so_dela:
            imprime(resume(f"  {ip}", so_dela))

    # ---- o que isso significa -------------------------------------------
    print(f"\n=== resumo  [{args.etiqueta}]")
    print(f"  {geral['ok']}/{geral['total']} requisicoes completas em {segundos:.1f} s "
          f"({geral['ok'] / max(segundos, 1e-9):.1f} req/s no total)")

    falhas = [r for r in res if not r.ok]
    if falhas:
        por_classe: dict[str, int] = {}
        for r in falhas:
            por_classe[r.classe] = por_classe.get(r.classe, 0) + 1
        print("  FALHAS por tipo:")
        for classe, quantas in sorted(por_classe.items(), key=lambda kv: -kv[1]):
            exemplo = next(r.erro for r in falhas if r.classe == classe)
            print(f"    {classe:<9} {quantas:>4}   ex.: {exemplo[:80]}")
        if por_classe.get("recusada"):
            print("    'recusada' e a fila do listen(4) estourando: mais de 4 "
                  "conexoes esperando na mesma placa.")
        if por_classe.get("valor"):
            print("    'valor' e GRAVE: resposta que nao corresponde ao pedido. "
                  "Anote e me traga -- nao deveria acontecer.")
    else:
        print("  nenhuma falha, e toda resposta conferiu com o esperado.")

    # So as convolucoes entram na razao: comparar a mediana de uma mistura de
    # conv (~215 ms) com a de outra mistura, com proporcao diferente de fft
    # (~21 ms), da numero sem significado -- e foi o que a primeira versao
    # imprimiu ("0.3x") quando calhou de cair uma fft de cada lado.
    for ip in placas:
        b = base.get(ip)
        convs = [r.ms for r in res if r.placa == ip and r.ok and r.op == "conv"]
        if b and convs:
            razao = statistics.median(convs) / b
            por_placa = args.clientes / len(placas) if args.modo != "mesma" else args.clientes
            print(f"  {ip}: conv mediana {statistics.median(convs):.1f} ms contra "
                  f"{b:.1f} ms sozinho -- {razao:.1f}x, com ~{por_placa:.1f} "
                  f"cliente(s) por placa desta maquina")
    print("  A fila serializa: com k clientes na mesma placa, espere ~k vezes a "
          "latencia de placa vazia. Nao e defeito -- e o servidor de um cliente "
          "por vez. Ver docs/GERENCIAMENTO-PLACAS.md.")
    print("  Se outra maquina estiver testando ao mesmo tempo, os clientes dela "
          "entram na mesma fila e nao aparecem nesta conta: some os clientes "
          "das duas antes de comparar.")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["etiqueta", "cliente", "rodada", "placa", "op", "ms",
                        "ok", "classe", "erro"])
            for r in res:
                w.writerow([args.etiqueta, r.cliente, r.rodada, r.placa, r.op,
                            f"{r.ms:.3f}", int(r.ok), r.classe, r.erro])
        print(f"\n  csv: {args.csv}")

    return 0 if not falhas else 2


if __name__ == "__main__":
    sys.exit(main())
