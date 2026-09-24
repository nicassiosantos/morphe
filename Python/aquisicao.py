"""
aquisicao.py -- captura de sinais pelo ADC da DE1-SoC (LTC2308), sem Tk.

O hardware (Quartus/adc_captura.v) dispara cada conversao exatamente a cada
`divisor` ciclos de 50 MHz e guarda as amostras numa RAM de 32768 palavras;
o servidor (OP_ADC) dispara, espera e devolve os codigos. Aqui ficam as
contas do lado do cliente: a palavra de configuracao do conversor, a fs que
de fato sai do divisor inteiro, a conversao para volts, o voltimetro (media
de uma captura curta), as metricas de uma senoide e a gravacao em arquivo.

Faixas (DE1-SoC User Manual, 3.6.12; docs/ADC.md):
  simples      entrada contra o terra, 0 a 4,095 V, 1 mV por codigo
  diferencial  CH+ menos CH-, -2,048 a +2,047 V; cada pino continua
               precisando ficar entre 0 e 5 V -- tensao negativa num pino
               pode danificar o conversor, em qualquer modo.

A ultima captura fica em `ultima_captura()`: o tipo "Captura do ADC" do
signal_panel a oferece a todas as janelas, sem passar por arquivo.

Tamanho: ate 32768 amostras, a captura e unica (OP_ADC). Acima disso, ou sem
limite, e continua (OP_ADC_CONTINUO): o hardware grava sem parar na RAM como
buffer circular e o servidor manda blocos enquanto a captura segue, sem
buraco no tempo entre eles. O limite passa a ser a memoria do PC (~10 bytes
por amostra: 1 minuto a 200 kHz sao ~120 MB) e o servidor acompanhar -- se nao
acompanhar, a captura termina com termino = "perdeu", e o que veio ate ali
continua valido.
"""
from __future__ import annotations

import os
import socket
import struct
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

import dsp_core as dsp
from morphe_config import (ADC_CLK_HZ, ADC_DIV_MAX, ADC_DIV_MIN, ADC_LSB_V,
                           ADC_N_MAX)
from morphe_protocol import (ADC_BLOCO_FIM, ADC_BLOCO_PERDEU, ADC_BLOCO_SEGUE,
                             ADC_BLOCO_TIMEOUT, RESP_HEADER_SIZE, STATUS_OK,
                             TcpClient, build_adc_continuo_request,
                             build_adc_request, decode_adc_response,
                             parse_response_header)

MODO_SIMPLES = "simples"
MODO_DIFERENCIAL = "diferencial"

CANAIS_SIMPLES = [f"CH{i}" for i in range(8)]
PARES_DIFERENCIAIS = [f"CH{2 * p} − CH{2 * p + 1}" for p in range(4)]

FS_MIN = ADC_CLK_HZ / ADC_DIV_MAX     # 1 kHz
FS_MAX = ADC_CLK_HZ / ADC_DIV_MIN     # 200 kHz

# O voltimetro faz a media de 0,1 s: um numero inteiro de ciclos de 50 Hz e de
# 60 Hz, o que cancela o zumbido da rede na media.
VOLTIMETRO_N = 2000
VOLTIMETRO_FS = 20_000.0


def palavra_config(modo: str, canal: int) -> int:
    """Palavra de 6 bits do LTC2308: S/D O/S S1 S0 UNI SLP.

    modo simples:      canal 0..7, unipolar. O LTC2308 numera o canal como
                       {S1, S0, O/S} (tabela 1 da folha de dados; o IP do
                       University Program monta a palavra do mesmo jeito).
    modo diferencial:  canal = par 0..3 (CH0-CH1 .. CH6-CH7), bipolar, com o
                       canal par como entrada positiva: S1 S0 = par, O/S = 0.
    SLP fica sempre 0: dormir desliga a referencia, que leva 200 ms para voltar.
    """
    if modo == MODO_SIMPLES:
        if not 0 <= canal <= 7:
            raise ValueError("canal simples deve estar entre 0 e 7")
        s_d, o_s, s1, s0, uni = 1, canal & 1, (canal >> 2) & 1, (canal >> 1) & 1, 1
    elif modo == MODO_DIFERENCIAL:
        if not 0 <= canal <= 3:
            raise ValueError("par diferencial deve estar entre 0 e 3")
        s_d, o_s, s1, s0, uni = 0, 0, (canal >> 1) & 1, canal & 1, 0
    else:
        raise ValueError(f"modo desconhecido: {modo!r}")
    return (s_d << 5) | (o_s << 4) | (s1 << 3) | (s0 << 2) | (uni << 1)


def divisor_para(fs: float) -> int:
    """Divisor inteiro mais proximo de 50 MHz / fs, dentro da faixa."""
    if not FS_MIN <= fs <= FS_MAX:
        raise ValueError(f"fs deve estar entre {FS_MIN:g} e {FS_MAX:g} Hz")
    return int(min(max(round(ADC_CLK_HZ / fs), ADC_DIV_MIN), ADC_DIV_MAX))


def fs_de(divisor: int) -> float:
    """A fs que o hardware usa de fato: 50 MHz / divisor, exata."""
    return ADC_CLK_HZ / divisor


def duracao_s(n: int, divisor: int) -> float:
    """Quanto a captura leva na placa (n+1 quadros; o primeiro e descartado)."""
    return (n + 1) * divisor / ADC_CLK_HZ


@dataclass
class Captura:
    codigos: np.ndarray       # inteiros do conversor
    volts: np.ndarray         # codigos * 1 mV
    fs: float                 # exata: 50 MHz / divisor
    divisor: int
    modo: str
    canal: int                # canal (simples) ou par (diferencial)
    # "completa"; na continua tambem "parada" (o usuario parou), "perdeu"
    # (o servidor nao acompanhou), "timeout" (o hardware parou) ou "conexao"
    # (a conexao caiu no meio)
    termino: str = "completa"
    # na continua, onde cada bloco do servidor comecou (indices de amostra)
    fronteiras: list = field(default_factory=list)

    @property
    def nome_entrada(self) -> str:
        if self.modo == MODO_SIMPLES:
            return CANAIS_SIMPLES[self.canal]
        return PARES_DIFERENCIAIS[self.canal]

    def como_signal(self) -> dsp.Signal:
        desc = (f"ADC {self.nome_entrada} ({self.volts.size} amostras, "
                f"fs={self.fs:g} Hz)")
        return dsp.Signal(n=np.arange(self.volts.size, dtype=np.int64),
                          x=self.volts.astype(np.float64), fs=self.fs,
                          description=desc)


_ULTIMA: Optional[Captura] = None


def ultima_captura() -> Optional[Captura]:
    return _ULTIMA


def capturar(client: TcpClient, n: int, fs: float, modo: str, canal: int,
             guardar: bool = True) -> Captura:
    """Captura n amostras a (aproximadamente) fs. A fs exata fica na Captura.

    Usa um cliente com o timeout alargado pela duracao da captura: a 1 kHz,
    32768 amostras levam 33 s, e o padrao do painel TCP e 10 s.
    """
    global _ULTIMA
    if not 1 <= n <= ADC_N_MAX:
        raise ValueError(f"amostras deve estar entre 1 e {ADC_N_MAX}")
    divisor = divisor_para(fs)
    cfg = palavra_config(modo, canal)
    espera = duracao_s(n, divisor) + 10.0
    c = TcpClient(client.host, client.port, timeout=max(client.timeout, espera))
    codigos, div_usado = decode_adc_response(c.request(build_adc_request(n, divisor, cfg)))
    if codigos.size != n:
        raise RuntimeError(f"a placa devolveu {codigos.size} amostras; pedi {n}")
    if div_usado != divisor:
        raise RuntimeError(f"a placa usou divisor {div_usado}; pedi {divisor}")
    cap = Captura(codigos=codigos, volts=codigos * ADC_LSB_V, fs=fs_de(divisor),
                  divisor=divisor, modo=modo, canal=canal)
    if guardar:
        _ULTIMA = cap
    return cap


_TERMINOS = {ADC_BLOCO_FIM: "completa", ADC_BLOCO_PERDEU: "perdeu",
             ADC_BLOCO_TIMEOUT: "timeout", "conexao": "conexao"}


def _recv_exato(s: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        pedaco = s.recv(n - len(buf))
        if not pedaco:
            raise ConnectionError(f"conexao fechada esperando {n} bytes")
        buf.extend(pedaco)
    return bytes(buf)


def capturar_continuo(client: TcpClient, n: int, fs: float, modo: str, canal: int,
                      parar: Optional[threading.Event] = None,
                      ao_bloco: Optional[Callable[[int, np.ndarray], None]] = None,
                      guardar: bool = True) -> Captura:
    """Captura continua, em blocos, sem o limite da RAM da placa.

    n = 0: sem limite, ate `parar` ser acionado. Com n > 0 termina sozinha em
    n amostras (e `parar` interrompe antes). `ao_bloco(total, bloco)` e
    chamado a cada bloco recebido (na thread de quem chamou), para a tela
    acompanhar.

    Nunca devolve buraco silencioso: se o servidor nao acompanhou, a captura
    termina com termino = "perdeu" e contem so a parte continua anterior.
    """
    global _ULTIMA
    if n < 0:
        raise ValueError("amostras deve ser >= 0 (0 = sem limite)")
    divisor = divisor_para(fs)
    cfg = palavra_config(modo, canal)
    blocos: list[np.ndarray] = []
    fronteiras: list[int] = []
    total = 0
    pediu_parada = False
    estado = None
    with socket.create_connection((client.host, client.port),
                                  timeout=max(client.timeout, 10.0)) as s:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.sendall(build_adc_continuo_request(n, divisor, cfg))
        op, _dt, status, n_out, extra = parse_response_header(_recv_exato(s, RESP_HEADER_SIZE))
        if status != STATUS_OK:
            msg = _recv_exato(s, n_out).decode("utf-8", "replace") if n_out else ""
            raise RuntimeError(f"erro do servidor: {msg}")
        if extra != divisor:
            raise RuntimeError(f"a placa usou divisor {extra}; pedi {divisor}")
        try:
            while True:
                if parar is not None and parar.is_set() and not pediu_parada:
                    s.sendall(b"P")             # pedido de parada: 1 byte qualquer
                    pediu_parada = True
                k, est = struct.unpack(">II", _recv_exato(s, 8))
                if k:
                    bloco = np.frombuffer(_recv_exato(s, 4 * k), dtype=">i4").astype(np.int16)
                    fronteiras.append(total)
                    blocos.append(bloco)
                    total += k
                    if ao_bloco is not None:
                        ao_bloco(total, bloco)
                if est != ADC_BLOCO_SEGUE:
                    estado = est
                    break
        except (ConnectionError, OSError):
            # A conexao caiu no meio (o servidor desiste de um cliente que nao
            # le por 5 s). Os blocos inteiros ja recebidos sao continuos e
            # valem; o que falta e so o fim.
            if not blocos:
                raise
            estado = "conexao"
    codigos = (np.concatenate(blocos) if blocos else np.zeros(0, np.int16)).astype(np.int16)
    termino = _TERMINOS.get(estado, "?")
    if termino == "completa" and pediu_parada and (n == 0 or total < n):
        termino = "parada"
    cap = Captura(codigos=codigos, volts=codigos * ADC_LSB_V, fs=fs_de(divisor),
                  divisor=divisor, modo=modo, canal=canal, termino=termino,
                  fronteiras=fronteiras)
    if guardar and codigos.size:
        _ULTIMA = cap
    return cap


def ler_tensao(client: TcpClient, modo: str, canal: int) -> dict:
    """Voltimetro: media de 0,1 s de amostras (2000 a 20 kHz).

    Nao substitui a ultima captura: ler a tensao nao deve apagar o sinal que
    as outras janelas estao usando.
    """
    cap = capturar(client, VOLTIMETRO_N, VOLTIMETRO_FS, modo, canal, guardar=False)
    v = cap.volts
    return {"media": float(np.mean(v)), "desvio": float(np.std(v)),
            "minimo": float(np.min(v)), "maximo": float(np.max(v)),
            "n": int(v.size), "saturou": bool(saturou(cap))}


def saturou(cap: Captura) -> bool:
    """True se alguma amostra bateu no limite da faixa (codigo extremo)."""
    if cap.modo == MODO_SIMPLES:
        return bool(np.any(cap.codigos <= 0) or np.any(cap.codigos >= 4095))
    return bool(np.any(cap.codigos <= -2048) or np.any(cap.codigos >= 2047))


def janela_bh(n: int) -> np.ndarray:
    """Blackman-Harris de 4 termos (lobulos laterais abaixo de -92 dB)."""
    k = np.arange(n) * (2.0 * np.pi / n)
    return (0.35875 - 0.48829 * np.cos(k) + 0.14128 * np.cos(2 * k)
            - 0.01168 * np.cos(3 * k))


def metricas(x: np.ndarray, fs: float) -> dict:
    """Numeros de uma captura: nivel DC, pico a pico, RMS da parte AC e,
    supondo que o sinal e uma senoide, a frequencia dela e a SINAD/ENOB.

    A SINAD sai do espectro com a janela de Blackman-Harris de 4 termos: a
    potencia da senoide sao os bins em volta do pico; ruido e distorcao, todo
    o resto menos os bins do nivel DC. ENOB = (SINAD - 1,76) / 6,02. A janela
    importa: a de Hann vaza uns -55 dB para fora do lobulo principal e
    esconderia os ~74 dB de um conversor de 12 bits; a de Blackman-Harris
    vaza abaixo de -92 dB. Com uma senoide limpa de gerador
    ocupando boa parte da faixa, e a medida do proprio ADC (o LTC2308
    promete ~73 dB, ENOB ~11,9).
    """
    x = np.asarray(x, dtype=np.float64)
    dc = float(np.mean(x))
    ac = x - dc
    out = {"dc": dc, "vpp": float(np.ptp(x)), "rms_ac": float(np.sqrt(np.mean(ac ** 2))),
           "f_pico": float("nan"), "sinad_db": float("nan"), "enob": float("nan")}
    if x.size < 64 or out["rms_ac"] == 0.0:
        return out
    w = janela_bh(x.size)
    P = np.abs(np.fft.rfft(ac * w)) ** 2
    viz = 6                                   # meia largura do lobulo (4 bins), com folga
    P[:viz] = 0.0                             # o que sobrou de DC depois da janela
    k0 = int(np.argmax(P))
    lo, hi = max(k0 - viz, 0), min(k0 + viz + 1, P.size)
    p_sinal = float(np.sum(P[lo:hi]))
    p_resto = float(np.sum(P) - p_sinal)
    # frequencia pelo centroide do lobulo: melhor que o bin inteiro
    kk = np.arange(lo, hi)
    out["f_pico"] = float(np.sum(kk * P[lo:hi]) / p_sinal * fs / x.size)
    if p_resto > 0.0:
        sinad = 10.0 * np.log10(p_sinal / p_resto)
        out["sinad_db"] = float(sinad)
        out["enob"] = float((sinad - 1.76) / 6.02)
    return out


TIPOS_SALVAR = [("Texto: tempo e tensão (.csv)", "*.csv"),
                ("NumPy: tempo e tensão (.npy)", "*.npy"),
                ("Áudio float32 (.wav)", "*.wav")]


def salvar(cap: Captura, caminho: str) -> str:
    """Grava a captura num formato que o sinal_arquivo le de volta.

    .csv / .npy  duas colunas, tempo (s) e tensao (V); a fs e recuperada do
                 passo do tempo.
    .wav         float32 em volts. O .wav so guarda fs inteira: se 50 MHz /
                 divisor nao for inteiro, grava arredondada e avisa no retorno.
    Devolve um texto curto sobre o que foi gravado.
    """
    ext = os.path.splitext(caminho)[1].lower()
    t = np.arange(cap.volts.size) / cap.fs
    if ext == ".csv":
        with open(caminho, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"# ADC DE1-SoC, entrada {cap.nome_entrada}, modo {cap.modo}, "
                    f"fs = {cap.fs:.6f} Hz (divisor {cap.divisor})\n")
            f.write("tempo_s,tensao_V\n")
            for ti, vi in zip(t, cap.volts):
                f.write(f"{ti:.9f},{vi:.3f}\n")
        return f"{cap.volts.size} amostras em {os.path.basename(caminho)}"
    if ext == ".npy":
        np.save(caminho, np.column_stack([t, cap.volts]))
        return f"{cap.volts.size} amostras em {os.path.basename(caminho)}"
    if ext == ".wav":
        from scipy.io import wavfile
        fs_int = int(round(cap.fs))
        wavfile.write(caminho, fs_int, cap.volts.astype(np.float32))
        msg = f"{cap.volts.size} amostras em {os.path.basename(caminho)}"
        if fs_int != cap.fs:
            msg += f" (fs gravada como {fs_int} Hz; a real e {cap.fs:.3f} Hz)"
        return msg
    raise ValueError(f"formato nao suportado: '{ext}'. Use .csv, .npy ou .wav.")
