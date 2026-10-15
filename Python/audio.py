"""Audio do codec WM8731 da placa: captura, reproducao e loopback.

O caminho e: conector P2 -> codec -> FPGA (audio_i2s.v) -> RAM adc_buf
(audio_buf.v) -> servidor (OP_AUDIO) -> este modulo, e o inverso para tocar.
A taxa e fixa: FS = 50 MHz / 1024 = 48 828,125 Hz, 16 bits, estereo.

Antes de usar, o codec precisa estar configurado na placa (C/codec.c):

    ./codec digital                  entrada pela LINE-in (azul)
    ./codec --entrada mic digital    entrada pelo MIC-in (rosa), +20 dB

e a chave SW9 da placa baixa (alta = tom de teste de 1017 Hz, que tem
prioridade sobre tudo). Sem o codec configurado nao ha relogio de audio, e o
servidor responde com uma mensagem dizendo isso.

As amostras sao int16 em arrays (N, 2): coluna 0 = esquerdo, 1 = direito.

    from morphe_protocol import TcpClient
    import audio
    c = TcpClient("172.16.230.24", 5000)
    for bloco in audio.blocos(c, n_bloco=1024, n_total=48828):   # 1 s
        ...                                                     # (1024, 2)
    audio.reproduzir(c, np.sin(2*np.pi*440*np.arange(48828)/audio.FS) * 0.3)
    audio.loopback(c, "codec")        # entrada -> saida, ate desligar
    x = audio.loopback(c, "ambos", n=48828)   # ouve e devolve ao computador
    audio.loopback(c, "desligado")
"""

from __future__ import annotations

import socket
import struct
import threading
from typing import Iterator, Optional

import numpy as np

from morphe_protocol import (ADC_BLOCO_FIM, ADC_BLOCO_PERDEU, ADC_BLOCO_SEGUE,
                             ADC_BLOCO_TIMEOUT, AUDIO_CAPTURA, AUDIO_LOOPBACK,
                             AUDIO_REPRODUZ, DTYPE_INT32, MAGIC_REQ, OP_AUDIO,
                             RESP_HEADER_SIZE, STATUS_OK, VERSION, TcpClient,
                             parse_response_header)

FS = 50e6 / 1024             # 48 828,125 Hz
DIVISOR = 1024               # o "extra" da resposta da captura: fs = 50 MHz / extra
N_RAM = 32768                # quadros que cabem na RAM da placa (0,67 s)

_TERMINOS = {ADC_BLOCO_FIM: "completa", ADC_BLOCO_PERDEU: "perdeu",
             ADC_BLOCO_TIMEOUT: "timeout"}


class AudioErro(RuntimeError):
    pass


# ---- protocolo ---------------------------------------------------------------

def _pedido(sub: int, n_x: int, n_h: int) -> bytes:
    return struct.pack(">IHHHHII", MAGIC_REQ, VERSION, OP_AUDIO, DTYPE_INT32,
                       sub, int(n_x), int(n_h))


def _recv_exato(s: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        pedaco = s.recv(n - len(buf))
        if not pedaco:
            raise ConnectionError(f"conexao fechada esperando {n} bytes")
        buf.extend(pedaco)
    return bytes(buf)


def _cabecalho(s: socket.socket) -> tuple[int, int]:
    """Le o cabecalho da resposta; devolve (n_out, extra) ou levanta o erro do
    servidor com a mensagem dele."""
    _op, _dt, status, n_out, extra = parse_response_header(_recv_exato(s, RESP_HEADER_SIZE))
    if status != STATUS_OK:
        msg = _recv_exato(s, n_out).decode("utf-8", "replace") if n_out else ""
        raise AudioErro(f"erro do servidor: {msg or 'status %d' % status}")
    return n_out, extra


def _conecta(client: TcpClient) -> socket.socket:
    s = socket.create_connection((client.host, client.port),
                                 timeout=max(client.timeout, 10.0))
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s


def palavras_para_estereo(w: np.ndarray) -> np.ndarray:
    """Palavras da RAM {dir[31:16], esq[15:0]} -> int16 (N, 2)."""
    w = np.asarray(w, dtype=np.uint32)
    esq = (w & 0xFFFF).astype(np.uint16).view(np.int16)
    dir_ = (w >> 16).astype(np.uint16).view(np.int16)
    return np.stack([esq, dir_], axis=1)


def estereo_para_palavras(x: np.ndarray) -> np.ndarray:
    """int16 (N, 2) -> palavras {dir, esq} em uint32."""
    x = np.asarray(x, dtype=np.int16)
    esq = x[:, 0].view(np.uint16).astype(np.uint32)
    dir_ = x[:, 1].view(np.uint16).astype(np.uint32)
    return (dir_ << 16) | esq


def para_int16(sinal: np.ndarray, fs: float = FS, ganho: float = 1.0) -> np.ndarray:
    """Qualquer sinal -> int16 (N, 2) a FS.

    float: escala de -1 a +1 (fora disso satura); inteiro: ja em LSB de 16
    bits. Mono (N,) vai para os dois canais. Com fs diferente de FS o sinal e
    reamostrado por interpolacao linear (suficiente para ouvir; para medir,
    gere o sinal ja em FS).
    """
    x = np.asarray(sinal)
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    if x.ndim != 2 or x.shape[1] != 2:
        raise ValueError("o sinal deve ser (N,) ou (N, 2)")
    if np.issubdtype(x.dtype, np.floating):
        x = x.astype(np.float64) * ganho * 32767.0
    else:
        x = x.astype(np.float64) * ganho
    if fs != FS and x.shape[0] > 1:
        t_novo = np.arange(int(round(x.shape[0] * FS / fs))) / FS
        t_velho = np.arange(x.shape[0]) / fs
        x = np.stack([np.interp(t_novo, t_velho, x[:, c]) for c in (0, 1)], axis=1)
    return np.clip(np.round(x), -32768, 32767).astype(np.int16)


# ---- captura -------------------------------------------------------------------

def _captura(client: TcpClient, n_total: int, loopback: bool,
             parar: Optional[threading.Event]) -> Iterator[np.ndarray]:
    """Os blocos como o servidor os manda (tamanho variavel), em int16 (k, 2).
    Termina no bloco final; levanta AudioErro se o hardware nao acompanhou."""
    if n_total < 0:
        raise ValueError("n_total deve ser >= 0 (0 = ate `parar`)")
    with _conecta(client) as s:
        s.sendall(_pedido(AUDIO_CAPTURA, n_total, 1 if loopback else 0))
        _n, extra = _cabecalho(s)
        if extra != DIVISOR:
            raise AudioErro(f"a placa respondeu fs = 50 MHz / {extra}; esperava / {DIVISOR}")
        pediu = False
        while True:
            if parar is not None and parar.is_set() and not pediu:
                s.sendall(b"P")
                pediu = True
            k, est = struct.unpack(">II", _recv_exato(s, 8))
            if k:
                w = np.frombuffer(_recv_exato(s, 4 * k), dtype=">u4")
                yield palavras_para_estereo(w)
            if est != ADC_BLOCO_SEGUE:
                if est in (ADC_BLOCO_PERDEU, ADC_BLOCO_TIMEOUT):
                    raise AudioErro(f"a captura terminou com {_TERMINOS[est]}: o servidor "
                                    "nao acompanhou ou o audio parou")
                return


def blocos(client: TcpClient, n_bloco: int = 1024, n_total: int = 0,
           loopback: bool = False,
           parar: Optional[threading.Event] = None) -> Iterator[np.ndarray]:
    """Captura do codec em blocos de `n_bloco` quadros, int16 (n_bloco, 2).

    Os blocos sao contiguos no tempo: o hardware grava sem parar e o servidor
    so copia. n_total = 0 segue ate `parar` ser acionado (o ultimo bloco
    incompleto e descartado); com n_total > 0 termina sozinha, e o ultimo
    bloco pode ser menor. `loopback=True` tambem toca a entrada na LINE-out
    enquanto captura.
    """
    if n_bloco < 1:
        raise ValueError("n_bloco deve ser >= 1")
    resto = np.zeros((0, 2), np.int16)
    for b in _captura(client, n_total, loopback, parar):
        resto = np.concatenate([resto, b]) if resto.size else b
        while resto.shape[0] >= n_bloco:
            yield resto[:n_bloco]
            resto = resto[n_bloco:]
    if n_total and resto.shape[0]:
        yield resto


def capturar(client: TcpClient, n: int, loopback: bool = False) -> np.ndarray:
    """n quadros do codec, int16 (n, 2). n = FS da 1 s."""
    if n < 1:
        raise ValueError("n deve ser >= 1")
    partes = list(_captura(client, n, loopback, None))
    x = np.concatenate(partes) if partes else np.zeros((0, 2), np.int16)
    if x.shape[0] != n:
        raise AudioErro(f"chegaram {x.shape[0]} quadros; pedi {n}")
    return x


# ---- reproducao ----------------------------------------------------------------

def reproduzir(client: TcpClient, sinal: np.ndarray, fs: float = FS,
               ganho: float = 1.0) -> dict:
    """Toca um sinal do computador pela LINE-out do codec.

    `sinal`: float de -1 a +1 ou inteiros de 16 bits, mono (N,) ou (N, 2), a
    `fs` (reamostrado para FS se for outra). Volta quando acabou de tocar.
    Ate N_RAM quadros (0,67 s) o sinal vai inteiro para a RAM; acima disso o
    servidor reabastece a RAM enquanto toca, e a duracao so e limitada pela
    rede. Devolve {"quadros", "segundos", "termino"}; termino "falhou" quer
    dizer que a rede atrasou e houve um trecho com som errado.
    """
    x = para_int16(sinal, fs, ganho)
    n = x.shape[0]
    if n < 1:
        raise ValueError("sinal vazio")
    w = estereo_para_palavras(x).astype(">u4").tobytes()
    with _conecta(client) as s:
        s.settimeout(n / FS + 15.0)
        s.sendall(_pedido(AUDIO_REPRODUZ, n, 0))
        # Os dados vao numa thread: o servidor pode responder com erro antes
        # de ler tudo, e o sendall nao pode prender a leitura da resposta.
        erro: list = []

        def envia():
            try:
                s.sendall(w)
            except OSError as e:
                erro.append(e)
        th = threading.Thread(target=envia, daemon=True)
        th.start()
        n_out, extra = _cabecalho(s)
        th.join(timeout=5.0)
    termino = {ADC_BLOCO_FIM: "completa", ADC_BLOCO_PERDEU: "falhou",
               ADC_BLOCO_TIMEOUT: "timeout"}.get(extra, "?")
    return {"quadros": n_out, "segundos": n_out / FS, "termino": termino}


# ---- loopback --------------------------------------------------------------------

def loopback_codec(client: TcpClient, ligar: bool = True) -> bool:
    """Liga (ou desliga) o loopback no hardware: a entrada do codec sai na
    LINE-out, passando pela FPGA, ate ser desligado. Fica ligado entre
    conexoes; uma captura ou reproducao o pausa e ele volta no fim."""
    with _conecta(client) as s:
        s.sendall(_pedido(AUDIO_LOOPBACK, 0, 1 if ligar else 0))
        _n, extra = _cabecalho(s)
    return bool(extra)


def loopback(client: TcpClient, destino: str = "codec", n: int = int(FS)):
    """Pega o som pela entrada do codec e o devolve.

    destino:
      "codec"       sai pela LINE-out da placa, ate chamar com "desligado";
                    volta None;
      "computador"  vem para o computador: n quadros, int16 (n, 2);
      "ambos"       os dois ao mesmo tempo, por n quadros: sai na LINE-out e
                    volta int16 (n, 2);
      "desligado"   desliga o loopback do codec; volta None.
    """
    if destino == "codec":
        loopback_codec(client, True)
        return None
    if destino == "desligado":
        loopback_codec(client, False)
        return None
    if destino == "computador":
        return capturar(client, n, loopback=False)
    if destino == "ambos":
        return capturar(client, n, loopback=True)
    raise ValueError('destino deve ser "codec", "computador", "ambos" ou "desligado"')


# ---- medidas simples -----------------------------------------------------------------

def nivel_dbfs(x: np.ndarray) -> float:
    """Nivel RMS em dBFS, com 0 dBFS = RMS de 32768 (fundo de escala)."""
    x = np.asarray(x, dtype=np.float64)
    rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
    return 20.0 * np.log10(max(rms, 1e-9) / 32768.0)


def freq_dominante(x: np.ndarray, fs: float = FS) -> float:
    """Frequencia do maior pico (fora do DC) de um canal, com janela de Hann."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 2:
        x = x[:, 0]
    if x.size < 8:
        return float("nan")
    X = np.abs(np.fft.rfft((x - x.mean()) * np.hanning(x.size)))
    X[:3] = 0.0
    return float(np.argmax(X) * fs / x.size)
