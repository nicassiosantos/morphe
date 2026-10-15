"""
testa_codec.py -- valida o audio do codec na placa: captura, reproducao e
loopback (Python/audio.py, OP_AUDIO, Quartus/audio_buf.v).

Antes, na placa:  ./codec --entrada mic digital   (ou ./codec digital, LINE-in)
e a SW9 baixa. Ligacao: microfone no MIC-in (rosa), caixa de som na LINE-out
(verde).

Testes, na ordem:

  captura    10 blocos de 1024 quadros: chegam inteiros, em blocos de 1024, e
             o nivel de cada um e mostrado (fale ou sopre no microfone para
             ver subir). Depois 3 s seguidos (mais que a RAM): sem perda.
  reproduz   um tom de 440 Hz por 0,5 s (cabe na RAM) e uma escala de 4 notas
             por 4 s (maior que a RAM: o servidor reabastece enquanto toca).
             Confere que tocou tudo, sem falha de rede. Escute na caixa.
  loopback   liga o loopback no codec por --segundos (fale: sai na caixa), e
             depois "ambos": 2 s saindo na caixa E vindo para o computador.
  adc        com o loopback ligado, uma captura do ADC (LTC2308) ainda
             funciona -- o servidor pausa o loopback e o religa.
  vivo       filtragem ao vivo pelo IIR da placa (sem bitstream novo): 3 s
             de microfone por um passa-baixas de 1 kHz. A saida tem de bater
             BIT A BIT com o modelo (audio.modelo_ao_vivo) aplicado a entrada
             que a propria placa devolveu, chegar no ritmo do audio e a placa
             gastar menos que um bloco por bloco.

Uso:
    python testa_codec.py <host> [captura|reproduz|loopback|adc|vivo|tudo]
                          [--segundos 5] [--porta 5000]
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np

import _caminho  # noqa: F401 -- poe Python/ no sys.path
import aquisicao as aq
import audio
from morphe_protocol import TcpClient

falhas = 0


def confere(cond: bool, msg: str) -> None:
    global falhas
    print(("  ok     " if cond else "  FALHA  ") + msg)
    if not cond:
        falhas += 1


def teste_captura(c: TcpClient) -> None:
    print("\n[captura] 10 blocos de 1024 quadros (fale ou sopre no microfone)")
    t0 = time.monotonic()
    tamanhos, niveis = [], []
    for i, b in enumerate(audio.blocos(c, n_bloco=1024, n_total=10 * 1024)):
        tamanhos.append(b.shape)
        niveis.append(audio.nivel_dbfs(b))
        print(f"    bloco {i}: {b.shape}, nivel {niveis[-1]:6.1f} dBFS, "
              f"pico {int(np.max(np.abs(b.astype(np.int32))))}")
    dt = time.monotonic() - t0
    confere(len(tamanhos) == 10 and all(t == (1024, 2) for t in tamanhos),
            f"10 blocos de (1024, 2) em {dt:.2f} s")
    confere(all(n < -1.0 for n in niveis), "nenhum bloco saturado")

    print("\n[captura] 3 s seguidos (146 484 quadros, mais que os 32 768 da RAM)")
    n = int(3 * audio.FS)
    t0 = time.monotonic()
    x = audio.capturar(c, n)
    dt = time.monotonic() - t0
    confere(x.shape == (n, 2), f"{x.shape[0]} quadros em {dt:.2f} s (tempo real: 3,00 s)")
    confere(dt < 4.0, "a captura acompanhou o tempo real")
    print(f"    nivel {audio.nivel_dbfs(x):.1f} dBFS, frequencia dominante "
          f"{audio.freq_dominante(x):.0f} Hz")


def teste_reproduz(c: TcpClient) -> None:
    print("\n[reproduz] tom de 440 Hz por 0,5 s (escute)")
    t = np.arange(int(0.5 * audio.FS)) / audio.FS
    r = audio.reproduzir(c, 0.3 * np.sin(2 * np.pi * 440 * t))
    confere(r["termino"] == "completa" and r["quadros"] == t.size,
            f"{r['quadros']} quadros, termino {r['termino']}")

    print("\n[reproduz] escala do, mi, sol, do' por 4 s (mais que a RAM)")
    notas = [261.63, 329.63, 392.00, 523.25]
    t = np.arange(int(1.0 * audio.FS)) / audio.FS
    env = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.02)       # sem estalo
    sinal = np.concatenate([0.3 * env * np.sin(2 * np.pi * f * t) for f in notas])
    t0 = time.monotonic()
    r = audio.reproduzir(c, sinal)
    dt = time.monotonic() - t0
    confere(r["termino"] == "completa" and r["quadros"] == sinal.size,
            f"{r['quadros']} quadros em {dt:.2f} s, termino {r['termino']}")


def teste_loopback(c: TcpClient, segundos: float) -> None:
    print(f"\n[loopback] codec -> codec por {segundos:.0f} s (fale: sai na caixa)")
    audio.loopback(c, "codec")
    time.sleep(segundos)
    audio.loopback(c, "desligado")
    confere(True, "ligou e desligou")

    print("\n[loopback] ambos: 2 s saindo na caixa e vindo para o computador")
    x = audio.loopback(c, "ambos", n=int(2 * audio.FS))
    confere(x.shape == (int(2 * audio.FS), 2), f"{x.shape[0]} quadros recebidos")
    print(f"    nivel {audio.nivel_dbfs(x):.1f} dBFS")


def teste_adc(c: TcpClient) -> None:
    print("\n[adc] o ADC continua funcionando com o loopback ligado")
    audio.loopback(c, "codec")
    try:
        cap = aq.capturar(c, 1000, 10000.0, aq.MODO_SIMPLES, 0)
        confere(cap.codigos.size == 1000, f"ADC: {cap.codigos.size} amostras a 10 kHz")
        x = audio.capturar(c, 1024)
        confere(x.shape == (1024, 2), "audio depois do ADC: 1024 quadros")
    finally:
        audio.loopback(c, "desligado")


def teste_vivo(c: TcpClient) -> None:
    import threading
    from scipy import signal
    import blocos
    import iir_design as iir
    print("\n[vivo] 3 s filtrados ao vivo pelo IIR da placa (fale no microfone)")
    sos = iir.distribui_ganho(signal.butter(4, 1000, "lowpass", fs=audio.FS, output="sos"))
    coefs = iir.coeficientes_inteiros(sos, 16, 32)
    aq = blocos.aquecimento_iir(sos, 16)
    medidas: dict = {}
    parar = threading.Event()
    xs, ys = [], []
    t0 = time.monotonic()
    for b in audio.ao_vivo_filtrado(c, coefs, aq, 0, parar, medidas):
        xs.append(b[:, 0])
        ys.append(b[:, 1])
        if time.monotonic() - t0 > 3.0:
            parar.set()
    dt = time.monotonic() - t0
    x, y = np.concatenate(xs), np.concatenate(ys)
    ym = audio.modelo_ao_vivo(x, coefs, aq)
    dif = int(np.max(np.abs(y[:ym.size].astype(np.int64) - ym.astype(np.int64)))) if ym.size else -1
    util = 1024 - aq
    confere(dif == 0 and ym.size == y.size,
            f"{y.size} amostras, saida x modelo bit a bit: {dif} LSB de diferenca")
    confere(abs(y.size / audio.FS - dt) < 0.3,
            f"ritmo: {y.size / audio.FS:.2f} s de audio em {dt:.2f} s")
    pmax = medidas.get("placa_us_max", 0) / 1e3
    confere(0 < pmax < util / audio.FS * 1e3,
            f"placa: ate {pmax:.1f} ms por bloco de {util / audio.FS * 1e3:.1f} ms")
    print(f"    entrada {audio.nivel_dbfs(x):.1f} dBFS, saida {audio.nivel_dbfs(y):.1f} dBFS")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host")
    ap.add_argument("teste", nargs="?", default="tudo",
                    choices=["captura", "reproduz", "loopback", "adc", "vivo", "tudo"])
    ap.add_argument("--segundos", type=float, default=5.0)
    ap.add_argument("--porta", type=int, default=5000)
    a = ap.parse_args()
    c = TcpClient(a.host, a.porta, timeout=20.0)
    try:
        if a.teste in ("captura", "tudo"):
            teste_captura(c)
        if a.teste in ("reproduz", "tudo"):
            teste_reproduz(c)
        if a.teste in ("loopback", "tudo"):
            teste_loopback(c, a.segundos)
        if a.teste in ("adc", "tudo"):
            teste_adc(c)
        if a.teste in ("vivo", "tudo"):
            teste_vivo(c)
    except audio.AudioErro as e:
        confere(False, str(e))
    print(f"\n{'TUDO OK' if falhas == 0 else f'{falhas} FALHA(S)'}")
    return 0 if falhas == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
