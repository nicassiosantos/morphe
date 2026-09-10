"""
morphe_protocol.py
===================
Protocolo binário Morphe-TCP entre o host (Python) e a FPGA (DE1-SoC HPS+FPGA).

Todos os inteiros do cabeçalho são em **network byte order (big-endian)**.
Payload de amostras também é big-endian (coerente com htonl/htons no C do HPS).

Formato da REQUISIÇÃO
---------------------
Cabeçalho (16 bytes):
    magic    : uint32  = 0x4D52504D  ('MRPM' — Morphe Request Protocol Message)
    version  : uint16  = 1
    opcode   : uint16  = 1 (CONV) | 2 (FFT)
    dtype    : uint16  = 1 (int32) | 2 (float32)
    flags    : uint16  = 0  (reservado)
    n_x      : uint32  = comprimento do sinal primário
Para CONV acrescenta-se:
    n_h      : uint32  = comprimento do segundo sinal (impulso h[n])

Payload:
    CONV  -> n_x * sizeof(dtype) bytes de x, seguidos de n_h * sizeof(dtype) bytes de h
    FFT   -> n_x * sizeof(dtype) bytes de x   (n_x deve ser potência de 2)

Formato da RESPOSTA
-------------------
Cabeçalho (16 bytes):
    magic    : uint32 = 0x4D52504E  ('MRPN' — Morphe Response)
    version  : uint16 = 1
    opcode   : uint16 = (espelha o request)
    dtype    : uint16 = dtype da saída  (1 int32 | 2 float32)
    status   : uint16 = 0 OK; !=0 erro
    n_out    : uint32 = número de amostras de saída
    extra    : uint32 = para FFT: 0; para CONV: 0 (reservado)

Payload:
    CONV  -> n_out * sizeof(dtype) bytes do y[n]
    FFT   -> n_out valores COMPLEXOS em float32 intercalados (re, im): total 8*n_out bytes
             (o campo dtype da resposta FFT será sempre 2=float32)

Em erro (status != 0) o payload é a mensagem UTF-8 do erro (n_out = número de bytes).
"""
from __future__ import annotations

import socket
import struct
from dataclasses import dataclass

import numpy as np


# ---- constantes ------------------------------------------------------------

MAGIC_REQ  = 0x4D52504D   # 'MRPM'
MAGIC_RESP = 0x4D52504E   # 'MRPN'
VERSION    = 1

OP_CONV = 1
OP_FFT  = 2
OP_PING = 3   # descoberta de servico
OP_FIR  = 4   # filtro FIR (instancia separada do conv1d, mesmo Verilog)
OP_IFFT = 5   # transformada inversa: mesmo IP da FFT, bit inverse=1

DTYPE_INT32   = 1
DTYPE_FLOAT32 = 2

STATUS_OK = 0

DTYPE_NAMES = {DTYPE_INT32: "int32", DTYPE_FLOAT32: "float32"}
DTYPE_CODES = {"int32": DTYPE_INT32, "float32": DTYPE_FLOAT32}

# Parâmetros do Q15.16 usado pela conv1d da FPGA (interno — cliente/servidor
# convertem transparentemente, não aparece no protocolo)
Q1516_FRAC_BITS = 16
Q1516_SCALE = 1 << Q1516_FRAC_BITS


def _np_dtype_be(code: int) -> np.dtype:
    """Retorna o dtype numpy BIG-ENDIAN correspondente ao código."""
    if code == DTYPE_INT32:
        return np.dtype(">i4")
    if code == DTYPE_FLOAT32:
        return np.dtype(">f4")
    raise ValueError(f"dtype desconhecido: {code}")


# ---- serialização ---------------------------------------------------------

def pack_samples(x: np.ndarray, dtype_code: int) -> bytes:
    """Empacota um array numpy em bytes big-endian."""
    be = _np_dtype_be(dtype_code)
    if dtype_code == DTYPE_INT32:
        clipped = np.clip(np.round(x), np.iinfo(np.int32).min, np.iinfo(np.int32).max)
        arr = clipped.astype(be)
    else:
        arr = x.astype(be)
    return arr.tobytes()


def unpack_samples(buf: bytes, n: int, dtype_code: int) -> np.ndarray:
    """Desempacota n amostras a partir de bytes big-endian -> numpy (host order)."""
    be = _np_dtype_be(dtype_code)
    arr = np.frombuffer(buf, dtype=be, count=n)
    # converte para native para o resto do app trabalhar confortavelmente
    native = ">f4" if dtype_code == DTYPE_FLOAT32 else ">i4"
    native_out = "<f8" if dtype_code == DTYPE_FLOAT32 else "<i8"
    # cast para float64/int64 pra facilitar manipulação downstream
    if dtype_code == DTYPE_FLOAT32:
        return arr.astype(np.float64)
    return arr.astype(np.int64)


def build_conv_request(x: np.ndarray, h: np.ndarray, dtype_code: int) -> bytes:
    hdr = struct.pack(
        ">IHHHHII",
        MAGIC_REQ, VERSION, OP_CONV, dtype_code, 0,
        len(x), len(h),
    )
    return hdr + pack_samples(x, dtype_code) + pack_samples(h, dtype_code)


def build_fir_request(x: np.ndarray, h: np.ndarray, dtype_code: int) -> bytes:
    """Constroi request FIR. Layout do payload e identico ao conv (mesmas
    SRAMs Q15.16, mesmos limites N <= 128), mas o opcode roteia para a
    instancia separada do conv1d na FPGA -- evita acoplar com o algoritmo
    de convolucao geral.
    """
    hdr = struct.pack(
        ">IHHHHII",
        MAGIC_REQ, VERSION, OP_FIR, dtype_code, 0,
        len(x), len(h),
    )
    return hdr + pack_samples(x, dtype_code) + pack_samples(h, dtype_code)


def escala_para_q1508(v: np.ndarray, folga: float = 0.98) -> float:
    """Fator que encosta o pico de `v` no teto do Q15.8, com folga.

    Base da normalizacao dos dois caminhos. Devolve 1.0 para entrada
    identicamente nula, que nao tem pico para encostar em nada.
    """
    import dsp_core as dsp
    v = np.asarray(v)
    pico = float(np.max(np.abs(np.concatenate([np.real(v).ravel(),
                                               np.imag(v).ravel()]))))
    if pico <= 0.0:
        return 1.0
    return folga * dsp.FFT_Q_MAX_FLOAT / pico


def build_fft_request(x_float: np.ndarray, *,
                      normalizar: bool = True,
                      scale: "float | None" = None) -> "tuple[bytes, float]":
    """Constroi request FFT. SEMPRE codifica em Q15.8.

    Devolve (payload, escala_usada). O chamador PRECISA passar a escala
    para decode_fft_response, que a desfaz.

    O formato Q15.8 e uma caracteristica do hardware FFT da Morphe, nao
    uma escolha do usuario. A codificacao ocorre no cliente, gerando um
    array int32 com 24 bits uteis e sign-extension nos 8 bits altos
    (formato esperado pela SRAM da FPGA, que usa num[23:0] e ignora os
    bits altos).

    `normalizar` (padrao True) multiplica x[n] para encostar no teto da
    faixa antes de quantizar, e a escala e desfeita na volta. A conta e
    exata -- a DFT e linear, entao DFT(s*x)/s = DFT(x) -- e o que muda e
    so o erro de quantizacao, que cai por s. Medido na placa: 6,02 dB por
    bit de faixa recuperado, ate o teto de ~92 dB do IP. Um sinal de
    amplitude 3 numa faixa que vai a 32768 desperdica ~13 bits.

    Com normalizar=False vale o comportamento antigo: x[n] vai como esta
    e valores fora de [-32768, +32767.996] SATURAM silenciosamente. Serve
    para reproduzir medidas antigas e para ver a diferenca na tela.

    `scale` fixa a escala na mao e ignora `normalizar`.

    Ver PRECISAO-NUMERICA.md para os numeros medidos.
    """
    # Importacao tardia para evitar ciclo entre dsp_core e morphe_protocol
    import dsp_core as dsp

    if scale is None:
        scale = escala_para_q1508(x_float) if normalizar else 1.0
    encoded = dsp.fft_q1508_encode(np.asarray(x_float) * scale)

    hdr = struct.pack(
        ">IHHHHII",
        MAGIC_REQ, VERSION, OP_FFT, DTYPE_INT32, 0,
        len(encoded), 0,
    )
    # encoded ja e int32; serializa em big-endian
    return hdr + encoded.astype(">i4").tobytes(), float(scale)


def build_ifft_request(X: np.ndarray,
                       scale: "float | None" = None, *,
                       normalizar: bool = True) -> "tuple[bytes, float]":
    """Constroi request IFFT a partir de um espectro complexo.

    Devolve (payload, escala_usada). O chamador PRECISA dividir a resposta
    pela escala devolvida -- veja decode_ifft_response.

    Por que a escala existe: o fio da FFT e Q15.8, que satura em +-32768 e
    tem so 8 bits fracionarios. Um X[k] pode ser ate N vezes maior que o
    x[n] que o gerou, e ao mesmo tempo os bins pequenos precisam dos bits
    de baixo. Mandar o espectro cru perde os dois lados. Entao o cliente
    faz o proprio ponto flutuante de bloco: normaliza X para ocupar a
    faixa inteira do Q15.8, manda, e desfaz a escala na volta. Como a
    transformada e linear, isso e exato -- nao e aproximacao.

    Com scale=None e normalizar=True (o padrao) a escala e calculada para
    encostar em FFT_Q_MAX_FLOAT com folga de 2%. Com normalizar=False a
    escala e 1.0 e o espectro vai como esta -- util para ver o efeito na
    tela, e nada mais. Passe `scale` para fixar o valor na mao.
    """
    import dsp_core as dsp

    X = np.asarray(X, dtype=np.complex128)
    if scale is None:
        scale = escala_para_q1508(X) if normalizar else 1.0

    re = dsp.fft_q1508_encode(X.real * scale)
    im = dsp.fft_q1508_encode(X.imag * scale)

    inter = np.empty(2 * len(X), dtype=np.int32)
    inter[0::2] = re
    inter[1::2] = im

    hdr = struct.pack(
        ">IHHHHII",
        MAGIC_REQ, VERSION, OP_IFFT, DTYPE_INT32, 0,
        len(X), 0,
    )
    return hdr + inter.astype(">i4").tobytes(), float(scale)


def build_ping_request() -> bytes:
    """Request de descoberta -- so cabecalho, sem payload.
    dtype=0 (ignorado para PING), n_x=n_h=0."""
    return struct.pack(
        ">IHHHHII",
        MAGIC_REQ, VERSION, OP_PING, 0, 0,
        0, 0,
    )


@dataclass
class Response:
    opcode: int
    dtype_code: int
    status: int
    n_out: int
    payload: bytes

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK


def parse_response_header(hdr: bytes) -> tuple[int, int, int, int, int]:
    if len(hdr) != 20:
        raise ValueError(f"cabeçalho de resposta deve ter 20 bytes, veio {len(hdr)}")
    magic, version, opcode, dtype_code, status, n_out, _extra = struct.unpack(
        ">IHHHHII", hdr
    )
    if magic != MAGIC_RESP:
        raise ValueError(f"magic de resposta inválido: 0x{magic:08X}")
    if version != VERSION:
        raise ValueError(f"versão incompatível: {version}")
    return opcode, dtype_code, status, n_out, _extra


RESP_HEADER_SIZE = 20


# ---- cliente TCP ----------------------------------------------------------

class TcpClient:
    """Cliente simples: abre conexão, envia request, lê response e fecha."""

    def __init__(self, host: str, port: int, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def _send_all(self, sock: socket.socket, data: bytes) -> None:
        view = memoryview(data)
        total = 0
        while total < len(view):
            n = sock.send(view[total:])
            if n == 0:
                raise ConnectionError("conexão fechada durante send")
            total += n

    def _recv_exact(self, sock: socket.socket, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError(
                    f"conexão fechada esperando {n} bytes (recebeu {len(buf)})"
                )
            buf.extend(chunk)
        return bytes(buf)

    def request(self, payload: bytes) -> Response:
        """Envia um request completo e retorna a Response."""
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
            # Nagle costuma atrapalhar mensagens curtas em DSP; desliga.
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._send_all(s, payload)

            hdr = self._recv_exact(s, RESP_HEADER_SIZE)
            opcode, dtype_code, status, n_out, _ = parse_response_header(hdr)

            # tamanho do payload depende da operação
            if status != STATUS_OK:
                body_size = n_out  # mensagem de erro em bytes
            elif opcode in (OP_FFT, OP_IFFT):
                body_size = n_out * 8  # float32 complex = 8 bytes por amostra
            elif opcode == OP_PING:
                body_size = n_out  # PING: n_out e o tamanho em bytes do texto
            else:
                body_size = n_out * (4 if dtype_code in (DTYPE_INT32, DTYPE_FLOAT32) else 0)

            body = self._recv_exact(s, body_size) if body_size > 0 else b""

        return Response(opcode=opcode, dtype_code=dtype_code,
                        status=status, n_out=n_out, payload=body)


# ---- decodificadores de alto nível ----------------------------------------

def decode_conv_response(resp: Response) -> np.ndarray:
    if not resp.ok:
        raise RuntimeError(f"erro do servidor: {resp.payload.decode('utf-8', 'replace')}")
    if resp.opcode != OP_CONV:
        raise ValueError(f"esperado opcode CONV, veio {resp.opcode}")
    be = _np_dtype_be(resp.dtype_code)
    arr = np.frombuffer(resp.payload, dtype=be, count=resp.n_out)
    return arr.astype(np.float64)


def decode_fir_response(resp: Response) -> np.ndarray:
    """Decodifica resposta do FIR. Formato identico ao da conv (a saida
    e um vetor real Q15.16), mas validamos opcode separadamente para
    nao cruzar tubulacoes."""
    if not resp.ok:
        raise RuntimeError(f"erro do servidor: {resp.payload.decode('utf-8', 'replace')}")
    if resp.opcode != OP_FIR:
        raise ValueError(f"esperado opcode FIR, veio {resp.opcode}")
    be = _np_dtype_be(resp.dtype_code)
    arr = np.frombuffer(resp.payload, dtype=be, count=resp.n_out)
    return arr.astype(np.float64)


def decode_fft_response(resp: Response, scale: float = 1.0) -> np.ndarray:
    """Decodifica X[k] e desfaz a escala usada no request.

    `scale` e o segundo valor devolvido por build_fft_request. O padrao
    1.0 cobre quem nao normalizou.
    """
    if not resp.ok:
        raise RuntimeError(f"erro do servidor: {resp.payload.decode('utf-8', 'replace')}")
    if resp.opcode != OP_FFT:
        raise ValueError(f"esperado opcode FFT, veio {resp.opcode}")
    if scale == 0.0:
        raise ValueError("escala zero: o request nao pode ser desfeito")
    interleaved = np.frombuffer(resp.payload, dtype=">f4", count=2 * resp.n_out)
    interleaved = interleaved.astype(np.float32)
    re = interleaved[0::2].astype(np.float64)
    im = interleaved[1::2].astype(np.float64)
    return (re + 1j * im) / scale


def decode_ifft_response(resp: Response, scale: float) -> np.ndarray:
    """Decodifica a resposta da IFFT e desfaz a escala do request.

    `scale` e o segundo valor devolvido por build_ifft_request. O fator
    IFFT_HW_GAIN vem do morphe_config e cobre a convencao do IP quanto ao
    1/N -- ver a nota la. O resultado e complexo: para uma entrada
    hermitiana a parte imaginaria e residuo de quantizacao, e serve como
    medida de erro.
    """
    from morphe_config import IFFT_HW_GAIN

    if not resp.ok:
        raise RuntimeError(f"erro do servidor: {resp.payload.decode('utf-8', 'replace')}")
    if resp.opcode != OP_IFFT:
        raise ValueError(f"esperado opcode IFFT, veio {resp.opcode}")
    if scale == 0.0:
        raise ValueError("escala zero: o request nao pode ser desfeito")

    interleaved = np.frombuffer(resp.payload, dtype=">f4", count=2 * resp.n_out)
    interleaved = interleaved.astype(np.float32)
    re = interleaved[0::2].astype(np.float64)
    im = interleaved[1::2].astype(np.float64)
    return (re + 1j * im) * (IFFT_HW_GAIN / scale)


# ---- descoberta de servidores na rede local -------------------------------
#
# A funcao discover_servers() faz um TCP-scan paralelo nas sub-redes /24
# informadas, e em cada IP que aceitar conexao envia um OP_PING. Quem
# responder com magic correto e payload "service=morphe" e listado.
#
# Tambem ha helpers para descobrir o IP local (truque do socket UDP "fantasma")
# e montar a lista de sub-redes baseada no /16 detectado.

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import field
from typing import Callable, Iterable


def decode_ping_response(resp: Response) -> dict:
    """Le a resposta de OP_PING e retorna um dict com os metadados.

    Levanta RuntimeError em status != OK ou em payload mal-formado.
    """
    if not resp.ok:
        raise RuntimeError(
            f"erro do servidor: {resp.payload.decode('utf-8', 'replace')}")
    if resp.opcode != OP_PING:
        raise ValueError(f"esperado opcode PING, veio {resp.opcode}")
    text = resp.payload.decode("utf-8", "replace")
    info: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, val = line.partition("=")
        info[key.strip()] = val.strip()
    if info.get("service") != "morphe":
        raise RuntimeError(
            f"resposta nao identifica servico morphe: service={info.get('service')!r}"
        )
    return info


@dataclass
class ServerInfo:
    """Resultado de uma descoberta bem-sucedida."""
    ip: str
    port: int
    info: dict   # chaves: service, version, hostname, fft_n, ...

    @property
    def hostname(self) -> str:
        return self.info.get("hostname", "?")

    @property
    def fft_n(self) -> str:
        return self.info.get("fft_n", "?")

    @property
    def conv_n_max(self) -> str:
        return self.info.get("conv_n_max", "?")

    @property
    def version(self) -> str:
        return self.info.get("version", "?")


def get_local_ip() -> str | None:
    """Descobre o IP da interface ativa abrindo um socket UDP "fantasma".

    Nao envia nenhum pacote (UDP nao requer handshake); o sistema operacional
    decide qual rota seria usada para alcancar o destino e o socket fica
    bound nesse IP. Funciona offline.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            return ip if ip and ip != "0.0.0.0" else None
    except OSError:
        return None


def detect_subnets(third_octets: Iterable[int] = (101, 102, 103),
                   fallback_prefix: str = "172.16") -> list[str]:
    """Detecta o /16 da interface local e devolve uma lista de /24 com os
    terceiros octetos especificados.

    Exemplo: se a interface local for 172.16.50.7, retorna
        ['172.16.101.0/24', '172.16.102.0/24', '172.16.103.0/24']

    Se nao conseguir detectar, usa fallback_prefix.
    """
    ip = get_local_ip()
    if ip is None:
        prefix = fallback_prefix
    else:
        parts = ip.split(".")
        if len(parts) >= 2:
            prefix = f"{parts[0]}.{parts[1]}"
        else:
            prefix = fallback_prefix
    return [f"{prefix}.{int(o)}.0/24" for o in third_octets]


def _enum_ips(subnet: str) -> list[str]:
    """Expande um /24 em uma lista de 254 IPs (.1 a .254). Aceita 'a.b.c.0/24'
    ou 'a.b.c.0' (sem mascara, assume /24). Para outras mascaras, retorna []."""
    if "/" in subnet:
        net, _, mask = subnet.partition("/")
        if mask.strip() != "24":
            return []
    else:
        net = subnet
    parts = net.split(".")
    if len(parts) != 4:
        return []
    base = ".".join(parts[:3])
    return [f"{base}.{i}" for i in range(1, 255)]


def _try_ping(ip: str, port: int, connect_timeout: float,
              read_timeout: float) -> ServerInfo | None:
    """Tenta uma conexao TCP+OP_PING contra um host. Retorna ServerInfo
    se for um servidor Morphe; None caso contrario. Nao levanta excecoes."""
    try:
        with socket.create_connection((ip, port),
                                      timeout=connect_timeout) as s:
            s.settimeout(read_timeout)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.sendall(build_ping_request())

            # Le os 20 bytes de header
            hdr = b""
            while len(hdr) < RESP_HEADER_SIZE:
                chunk = s.recv(RESP_HEADER_SIZE - len(hdr))
                if not chunk:
                    return None
                hdr += chunk

            try:
                opcode, dtype_code, status, n_out, _ = parse_response_header(hdr)
            except ValueError:
                return None  # nao e Morphe

            if status != STATUS_OK or opcode != OP_PING:
                return None

            # Le payload (texto)
            body = b""
            while len(body) < n_out:
                chunk = s.recv(n_out - len(body))
                if not chunk:
                    return None
                body += chunk

            resp = Response(opcode=opcode, dtype_code=dtype_code,
                            status=status, n_out=n_out, payload=body)
            try:
                info = decode_ping_response(resp)
            except (RuntimeError, ValueError):
                return None
            return ServerInfo(ip=ip, port=port, info=info)

    except (OSError, socket.timeout):
        return None


def discover_servers(
    subnets: Iterable[str],
    port: int = 5000,
    connect_timeout: float = 0.3,
    read_timeout: float = 0.5,
    max_workers: int = 64,
    on_found: Callable[[ServerInfo], None] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
    stop_on_first: bool = False,
) -> list[ServerInfo]:
    """Faz scan TCP+PING em paralelo nas sub-redes informadas.

    Parametros:
        subnets: iteravel de strings 'a.b.c.0/24' (a mascara e exigida).
        port: porta TCP do servidor (default 5000).
        connect_timeout: timeout do TCP connect, em segundos.
        read_timeout: timeout para receber a resposta do PING.
        max_workers: quantidade de threads paralelas no pool.
        on_found: callback opcional, chamado de dentro do worker quando
            um servidor e encontrado. NAO use para tocar Tk diretamente
            (use Tk.after no chamador).
        on_progress: callback opcional (done, total) chamado a cada IP
            verificado. Mesmo cuidado com Tk.
        cancel_event: se setado, novos workers param de submeter trabalho
            e a funcao retorna assim que os jobs em curso terminam.
        stop_on_first: se True, retorna no primeiro servidor encontrado
            e cancela os demais futuros pendentes (modo "autoconnect").

    Retorna lista de ServerInfo encontrados.
    """
    targets: list[str] = []
    for sub in subnets:
        targets.extend(_enum_ips(sub))
    total = len(targets)
    found: list[ServerInfo] = []
    done = 0

    if total == 0:
        return found

    cancel_event = cancel_event or threading.Event()

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_to_ip = {}
        for ip in targets:
            if cancel_event.is_set():
                break
            fut = ex.submit(_try_ping, ip, port, connect_timeout, read_timeout)
            future_to_ip[fut] = ip

        for fut in as_completed(future_to_ip):
            done += 1
            if on_progress is not None:
                try:
                    on_progress(done, total)
                except Exception:
                    pass
            if cancel_event.is_set():
                # nao processa o resultado, apenas conta; futuros pendentes
                # vao terminar pelo timeout naturalmente
                continue
            try:
                result = fut.result()
            except Exception:
                result = None
            if result is not None:
                found.append(result)
                if on_found is not None:
                    try:
                        on_found(result)
                    except Exception:
                        pass
                if stop_on_first:
                    # Cancela futuros que ainda nao iniciaram. Os que ja
                    # estao rodando vao terminar rapido pelo timeout.
                    cancel_event.set()
                    for f in future_to_ip:
                        if not f.running() and not f.done():
                            f.cancel()
                    break

    return found
