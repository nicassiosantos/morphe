"""
testa_adc.py -- valida o ADC na placa, com os instrumentos do laboratorio.

Tres testes, na ordem em que se faz na bancada:

  basico   sem nada ligado: o servidor anuncia o ADC, as recusas funcionam
           e uma captura de cada tamanho volta inteira. Nao precisa de
           instrumento. Se isto falhar, o bitstream ou o servidor estao
           errados, e nao o sinal.

  tensao   voltimetro: le a entrada varias vezes e mostra media e desvio,
           para comparar com o multimetro na mesma entrada (uma pilha, um
           divisor resistivo na fonte de 5 V, um potenciometro).
           Esperado: diferenca de poucos mV e desvio de ~1 mV.

  senoide  gerador de funcoes com OFFSET DC (~2 V) e ate 4 Vpp: captura a
           varias fs e mede a frequencia, o nivel DC, o pico a pico, a SINAD
           e o ENOB. A frequencia medida confere a fs (se a fs estivesse
           errada, a frequencia sairia errada na mesma proporcao); o ENOB
           mede o conversor junto com o gerador -- o LTC2308 promete ~11,9.

  continuo com o mesmo gerador: captura continua, em blocos, de --segundos a
           200 kHz. Confere que chegou tudo, sem perda, e que nao ha buraco
           entre blocos: um buraco numa senoide vira salto na fronteira e
           derruba a SINAD da captura inteira.

Uso:
    python testa_adc.py <host> basico
    python testa_adc.py <host> tensao  [--canal 0] [--vezes 10]
    python testa_adc.py <host> senoide --f 1000 [--canal 0]
    python testa_adc.py <host> continuo --f 1000 [--segundos 10] [--canal 0]
    python testa_adc.py <host> canais     (diagnostico: 8 canais e 4 pares)
    (--porta 5000 em qualquer um)

CUIDADO com a ligacao: pino 1 do J15 e 5 V; cada entrada aceita de 0 a
4,096 V; tensao negativa pode danificar o conversor (docs/ADC.md).
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np

import _caminho  # noqa: F401 -- poe Python/ no sys.path
import aquisicao as aq
from morphe_config import ADC_N_MAX
from morphe_protocol import (STATUS_OK, TcpClient, build_adc_request,
                             build_ping_request, decode_ping_response)

falhas = 0


def confere(cond: bool, msg: str) -> None:
    global falhas
    print(("  ok     " if cond else "  FALHA  ") + msg)
    if not cond:
        falhas += 1


def basico(cli: TcpClient, canal: int) -> None:
    print("\n== basico (nada precisa estar ligado) ==")
    info = decode_ping_response(cli.request(build_ping_request()))
    confere(info.get("adc_n_max") == str(ADC_N_MAX),
            f"o servidor anuncia o ADC (adc_n_max={info.get('adc_n_max')}, "
            f"fs {info.get('adc_fs_min')}..{info.get('adc_fs_max')} Hz)")
    confere(info.get("fpga_preparada") == "1", "FPGA preparada pelo morphe-up")

    for n, div, cfg, nome in [(0, 1000, 0x22, "n = 0"), (ADC_N_MAX + 1, 1000, 0x22, "n acima do maximo"),
                              (10, 249, 0x22, "fs acima de 200 kHz"), (10, 1000, 0x23, "SLP = 1")]:
        r = cli.request(build_adc_request(n, div, cfg))
        confere(r.status != STATUS_OK, f"recusa {nome}")

    for n, fs in [(1, 10_000), (1000, 200_000), (ADC_N_MAX, 200_000), (100, 1_000)]:
        t0 = time.perf_counter()
        cap = aq.capturar(cli, n, fs, aq.MODO_SIMPLES, canal, guardar=False)
        dt = time.perf_counter() - t0
        confere(cap.codigos.size == n and cap.codigos.min() >= 0 and cap.codigos.max() <= 4095,
                f"{n} amostras a {fs} Hz: voltaram inteiras em {dt:.2f} s "
                f"(placa: {aq.duracao_s(n, cap.divisor):.3f} s); "
                f"faixa {cap.volts.min():.3f}..{cap.volts.max():.3f} V")

    # A pergunta que so a placa responde: o HPS acompanha a fs maxima?
    n = 2_000_000
    t0 = time.perf_counter()
    cap = aq.capturar_continuo(cli, n, 200_000, aq.MODO_SIMPLES, canal, guardar=False)
    dt = time.perf_counter() - t0
    confere(cap.termino == "completa" and cap.codigos.size == n,
            f"continua: {cap.codigos.size} de {n} amostras a 200 kHz em {dt:.1f} s "
            f"(10 s na placa), {len(cap.fronteiras)} blocos, termino '{cap.termino}'")


def tensao(cli: TcpClient, canal: int, vezes: int) -> None:
    print(f"\n== tensao em CH{canal} (compare com o multimetro) ==")
    medias = []
    for i in range(vezes):
        r = aq.ler_tensao(cli, aq.MODO_SIMPLES, canal)
        medias.append(r["media"])
        print(f"  {i + 1:2d}: {r['media']:.4f} V   desvio {r['desvio'] * 1e3:.2f} mV   "
              f"min {r['minimo']:.3f}  max {r['maximo']:.3f}"
              + ("   SATUROU" if r["saturou"] else ""))
    m = np.array(medias)
    print(f"  media das leituras: {m.mean():.4f} V; variacao entre leituras: "
          f"{np.ptp(m) * 1e3:.2f} mV")
    confere(np.ptp(m) < 0.005, "leituras estaveis (menos de 5 mV entre elas)")
    print("  -> anote a tensao do multimetro ao lado desta media no DIARIO")


def senoide(cli: TcpClient, canal: int, f: float) -> None:
    print(f"\n== senoide de {f:g} Hz em CH{canal} (gerador com offset DC) ==")
    print(f"  {'fs (Hz)':>12} {'f medida':>12} {'erro':>9} {'DC (V)':>8} {'Vpp':>7} "
          f"{'SINAD':>7} {'ENOB':>6}")
    for fs in (10_000, 48_000, 100_000, 200_000):
        if f >= fs / 2:
            print(f"  {fs:12g}   (pulado: {f:g} Hz acima de fs/2)")
            continue
        cap = aq.capturar(cli, 16384, fs, aq.MODO_SIMPLES, canal, guardar=False)
        m = aq.metricas(cap.volts, cap.fs)
        erro_ppm = (m["f_pico"] - f) / f * 1e6
        print(f"  {cap.fs:12.3f} {m['f_pico']:12.3f} {erro_ppm:7.0f}ppm {m['dc']:8.3f} "
              f"{m['vpp']:7.3f} {m['sinad_db']:6.1f}dB {m['enob']:6.2f}"
              + ("  SATUROU" if aq.saturou(cap) else ""))
        confere(abs(erro_ppm) < 1000, f"fs={cap.fs:g}: frequencia dentro de 0,1 % "
                "(o gerador e a referencia; erro grande = fs errada)")
        confere(not aq.saturou(cap), f"fs={cap.fs:g}: sem saturar (ajuste offset/amplitude)")
        confere(m["enob"] > 9.0, f"fs={cap.fs:g}: ENOB acima de 9 bits")


def continuo(cli: TcpClient, canal: int, f: float, segundos: float) -> None:
    fs = 200_000
    n = int(segundos * fs)
    print(f"\n== continuo: {segundos:g} s a 200 kHz, senoide de {f:g} Hz em CH{canal} ==")
    cap = aq.capturar_continuo(cli, n, fs, aq.MODO_SIMPLES, canal, guardar=False)
    confere(cap.termino == "completa" and cap.codigos.size == n,
            f"{cap.codigos.size} de {n} amostras, {len(cap.fronteiras)} blocos, "
            f"termino '{cap.termino}'")
    if cap.codigos.size < 1000:
        return
    m = aq.metricas(cap.volts, cap.fs)
    print(f"  captura inteira: f = {m['f_pico']:.3f} Hz, SINAD {m['sinad_db']:.1f} dB, "
          f"ENOB {m['enob']:.2f}")
    confere(abs(m["f_pico"] - f) / f < 1e-3, "frequencia certa na captura inteira")
    confere(m["enob"] > 9.0, "ENOB acima de 9 bits na captura inteira (um buraco derrubaria)")
    d = np.abs(np.diff(cap.codigos.astype(np.int64)))
    fr = np.array([i for i in cap.fronteiras if i > 0], dtype=np.int64)
    if fr.size:
        limite = float(np.percentile(d, 99.99)) + 3.0
        pior = float(d[fr - 1].max())
        confere(pior <= limite, f"sem salto nas {fr.size} fronteiras de bloco "
                f"(maior salto la: {pior:.0f} codigos; no sinal todo, 99,99 %: "
                f"{limite - 3:.0f})")


def canais(cli: TcpClient) -> None:
    """Diagnostico: le os 8 canais e os 4 pares e diz o que isso significa.

    Separa tres situacoes que parecem iguais na tela:
      - um canal ligado ao terra le ~0 V: e ele que esta no terra;
      - entrada solta le ~1,6 a 2,1 V: a entrada chaveada do LTC2308 puxa um
        pino solto para perto de REFCOMP/2 = 2,048 V (folha de dados, modelo
        da entrada com R_EQ e VREFCOMP/2), e a fuga de ate 1 uA o desloca;
      - a palavra de configuracao nao chega ao conversor: entao mudar canal e
        modo nao muda nada, e o par diferencial le o mesmo que o canal simples,
        em vez de ~0 V (dois pinos soltos parecidos se cancelam).
    """
    print("\n== diagnostico: os 8 canais e os 4 pares ==")
    simples = []
    for c in range(8):
        r = aq.ler_tensao(cli, aq.MODO_SIMPLES, c)
        simples.append(r["media"])
        print(f"  CH{c}  (pino {[2, 3, 4, 5, 6, 7, 8, 9][c]}): media {r['media']:.4f} V   "
              f"desvio {r['desvio'] * 1e3:6.2f} mV   min {r['minimo']:.3f}   max {r['maximo']:.3f}")
    difer = []
    for p in range(4):
        r = aq.ler_tensao(cli, aq.MODO_DIFERENCIAL, p)
        difer.append(r["media"])
        print(f"  {aq.PARES_DIFERENCIAIS[p]}: media {r['media']:+.4f} V   "
              f"desvio {r['desvio'] * 1e3:6.2f} mV")
    cap = aq.capturar(cli, 400, 20_000, aq.MODO_SIMPLES, 0, guardar=False)
    print("  CH0, primeiras 16 amostras a 20 kHz:", " ".join(f"{v:.3f}" for v in cap.volts[:16]))
    print("  CH0, ultimas 4:                       ", " ".join(f"{v:.3f}" for v in cap.volts[-4:]))

    print("\n  conclusao:")
    no_terra = [c for c, v in enumerate(simples) if v < 0.05]
    if no_terra:
        print(f"   - no terra: {', '.join(f'CH{c}' for c in no_terra)} -- a leitura do conversor funciona")
    else:
        print("   - nenhum canal no terra (~0 V): o jumper nao esta ligando um canal ao GND,")
        print("     ou a configuracao nao chega ao conversor (ver o item seguinte)")
    iguais = all(abs(d - s) < 0.2 for d, s in zip(difer, simples[0::2]))
    if iguais:
        print("   - os pares diferenciais leem o MESMO que os canais simples: a palavra de")
        print("     configuracao NAO esta chegando ao conversor (problema no controlador)")
    else:
        print("   - os pares diferenciais leem diferente dos canais simples: a palavra de")
        print("     configuracao chega ao conversor (canal e modo mudam a leitura)")
    soltos = [c for c, v in enumerate(simples) if 1.2 < v < 2.6]
    if soltos:
        print(f"   - leitura de entrada solta (1,2 a 2,6 V): {', '.join(f'CH{c}' for c in soltos)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("host")
    ap.add_argument("teste", choices=("basico", "tensao", "senoide", "continuo", "canais"))
    ap.add_argument("--porta", type=int, default=5000)
    ap.add_argument("--canal", type=int, default=0)
    ap.add_argument("--vezes", type=int, default=10)
    ap.add_argument("--f", type=float, default=1000.0, help="frequencia do gerador (Hz)")
    ap.add_argument("--segundos", type=float, default=10.0, help="duracao do teste continuo")
    a = ap.parse_args()
    cli = TcpClient(a.host, a.porta, timeout=10.0)
    if a.teste == "basico":
        basico(cli, a.canal)
    elif a.teste == "tensao":
        tensao(cli, a.canal, a.vezes)
    elif a.teste == "senoide":
        senoide(cli, a.canal, a.f)
    elif a.teste == "canais":
        canais(cli)
    else:
        continuo(cli, a.canal, a.f, a.segundos)
    print("\nTUDO OK" if falhas == 0 else f"\nFALHOU: {falhas} verificacao(oes)")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
