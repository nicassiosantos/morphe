"""tcp_panel.py — widget de configuração da conexão TCP.

Consome `morphe_theme` para estilos e helpers. A configuração TCP vive
na janela principal e é compartilhada por todas as janelas filhas
(FFT, Convolução, FIR). Estas chamam `master.tcp_panel.make_client()`
em vez de instanciar a própria.

Dois caminhos de conexão
────────────────────────
  - Conectar   : valida o servidor informado manualmente (host/porta/timeout)
                 com um handshake OP_PING e reporta hostname/FFT_N/Conv_N.
  - Autoconnect: varre a LAN e preenche host/porta com o primeiro servidor
                 Morphe encontrado.

Observação sobre o modelo de conexão
────────────────────────────────────
O protocolo Morphe é *sem conexão persistente*: cada operação (CONV/FFT/FIR)
abre um socket, envia, recebe e fecha (ver `TcpClient.request`). Por isso
"Conectar" aqui NÃO mantém um socket aberto — é uma verificação de
alcançabilidade/identidade do servidor (o mesmo OP_PING da descoberta),
para dar ao usuário confiança antes de abrir uma ferramenta. Também é por
isso que não há nada a "desconectar" ao fechar a GUI.
"""
from __future__ import annotations

import os
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from typing import List, Optional, Tuple

import morphe_theme as theme
from morphe_protocol import (
    TcpClient, ServerInfo, EstadoPlaca, consultar_estado, discover_servers,
    subredes_provaveis, build_ping_request, decode_ping_response,
)

# De quanto em quanto tempo o painel pergunta à placa conectada o que ela está
# fazendo (porta de estado, UDP: não entra na fila da placa).
ESTADO_INTERVALO_MS = 4000


# ======================================================================
# Placa lembrada — o mesmo arquivo que o morphe-up.sh escreve
# ======================================================================
# A versão 1.2 do plano tira do usuário a tarefa de saber o endereço da
# placa. O morphe-up.sh grava em .morphe-estado/placa a placa que acabou
# de preparar; o cliente lê dali e já abre conectado. Se o arquivo não
# existir (cliente em outra máquina, por exemplo), cai na busca pela LAN.


def _caminho_placa_lembrada() -> str:
    """<raiz do repositório>/.morphe-estado/placa — este módulo vive em Python/."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(raiz, ".morphe-estado", "placa")


def ler_placa_lembrada() -> Optional[str]:
    try:
        with open(_caminho_placa_lembrada(), encoding="utf-8") as f:
            ip = f.read().strip()
        return ip or None
    except OSError:
        return None


def _caminho_placas_conhecidas() -> str:
    """<raiz>/.morphe-estado/placas — todas as placas já preparadas."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(raiz, ".morphe-estado", "placas")


def _caminho_placas_laboratorio() -> str:
    """<raiz>/placas.conf — a lista versionada, igual em todo computador."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(raiz, "placas.conf")


def ler_placas_laboratorio() -> List[str]:
    """Os IPs do placas.conf: o primeiro campo de cada linha que não é
    comentário. Linha que não começa com um IPv4 é ignorada."""
    ips: List[str] = []
    try:
        with open(_caminho_placas_laboratorio(), encoding="utf-8") as f:
            for linha in f:
                campo = linha.split("#", 1)[0].split()
                if not campo:
                    continue
                partes = campo[0].split(".")
                if len(partes) == 4 and all(p.isdigit() and int(p) < 256 for p in partes):
                    ips.append(campo[0])
    except OSError:
        pass
    return ips


def ler_placas_conhecidas() -> List[str]:
    """Todas as placas que este computador conhece, sem repetir.

    Três fontes, nesta ordem:
      - .morphe-estado/placas, que o morphe-up.sh acumula na máquina onde
        roda (a estação);
      - a placa "lembrada": num clone que só rodou antes desta lista
        existir, ela é a única que há;
      - placas.conf, versionado: é o que faz um computador recém-instalado
        achar as placas sem varrer a rede (desde 28/09/2026).
    """
    ips: List[str] = []
    try:
        with open(_caminho_placas_conhecidas(), encoding="utf-8") as f:
            ips = [l.strip() for l in f if l.strip()]
    except OSError:
        pass
    lembrada = ler_placa_lembrada()
    for ip in ([lembrada] if lembrada else []) + ler_placas_laboratorio():
        if ip not in ips:
            ips.append(ip)
    return ips


def gravar_placa_lembrada(ip: str) -> None:
    """Melhor esforço: um clone somente-leitura não é motivo para falhar."""
    try:
        caminho = _caminho_placa_lembrada()
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(ip)
    except OSError:
        pass


class TcpConfigPanel(ttk.LabelFrame):
    def __init__(self, parent,
                 default_host: str = "192.168.1.10",
                 default_port: int = 5000,
                 autoconectar: bool = False):
        # Garante que os estilos do tema existem mesmo se este painel
        # for instanciado fora do hub principal.
        theme.setup_styles(parent)

        super().__init__(
            parent,
            text=" Conexão FPGA (TCP) ",
            style="Card.TLabelframe",
            padding=(18, 14, 18, 16),
        )

        # Threads de trabalho (autoconnect e conexão manual). Mantidas
        # separadas, mas mutuamente exclusivas via _busy().
        self._search_thread: Optional[threading.Thread] = None
        self._connect_thread: Optional[threading.Thread] = None
        self._cancel_event: Optional[threading.Event] = None
        self._success_handled = False

        # Grid de duas colunas: labels (largura fixa) + inputs (cresce)
        self.columnconfigure(0, weight=0, minsize=110)
        self.columnconfigure(1, weight=1)

        # Linha 0: Host
        ttk.Label(self, text="Host", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6))
        # A placa preparada pelo morphe-up.sh tem precedência sobre o
        # default fixo — que, no laboratório, nunca é o endereço certo.
        conhecidas = ler_placas_conhecidas()
        self.var_host = tk.StringVar(value=ler_placa_lembrada()
                                     or (conhecidas[0] if conhecidas else default_host))
        ttk.Entry(self, textvariable=self.var_host).grid(
            row=0, column=1, sticky="ew", pady=(0, 6))

        # Linha 1: Porta
        ttk.Label(self, text="Porta", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, 6))
        self.var_port = tk.StringVar(value=str(default_port))
        ttk.Entry(self, textvariable=self.var_port).grid(
            row=1, column=1, sticky="ew", pady=(0, 6))

        # Linha 2: Timeout
        ttk.Label(self, text="Timeout (s)", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", pady=(0, 8))
        self.var_timeout = tk.StringVar(value="10")
        ttk.Entry(self, textvariable=self.var_timeout).grid(
            row=2, column=1, sticky="ew", pady=(0, 8))

        # Linha 3: botões de conexão (Conectar + Autoconnect), à direita.
        # Um sub-frame encosta o par na margem direita da coluna de inputs.
        btn_row = ttk.Frame(self, style="Card.TFrame")
        btn_row.grid(row=3, column=0, columnspan=2, sticky="e", pady=(2, 4))

        # "Conectar" é a ação primária quando o usuário já sabe o IP →
        # estilo outline (primário leve, combina com o card branco).
        self.btn_connect = ttk.Button(
            btn_row, text="Conectar",
            style="Outline.TButton",
            command=self._on_connect,
        )
        self.btn_connect.pack(side="left", padx=(0, 8))

        # "Autoconnect" é o caminho de descoberta → ação neutra (secondary).
        self.btn_autoconnect = ttk.Button(
            btn_row, text="Autoconnect",
            style="Secondary.TButton",
            command=self._on_autoconnect,
        )
        self.btn_autoconnect.pack(side="left")

        # Linha 4: status (autoconnect e conexão manual escrevem aqui)
        self.var_status = tk.StringVar(value="")
        self.lbl_status = tk.Label(
            self, textvariable=self.var_status,
            background=theme.COLORS["card_bg"],
            foreground=theme.COLORS["info_fg"],
            font=("TkDefaultFont", 9, "italic"),
            justify="left", anchor="w",
        )
        self.lbl_status.grid(row=4, column=0, columnspan=2,
                             sticky="w", pady=(4, 0))

        # Linha 5: o que a placa conectada está fazendo agora (porta de estado).
        # Fica vazia com servidor anterior a 28/09/2026, que não tem a porta.
        self.var_estado = tk.StringVar(value="")
        tk.Label(
            self, textvariable=self.var_estado,
            background=theme.COLORS["card_bg"],
            foreground=theme.COLORS["text_muted"],
            font=("TkDefaultFont", 9),
            justify="left", anchor="w",
        ).grid(row=5, column=0, columnspan=2, sticky="w")
        self._estado_agendado = False

        # Linha 6: banner informativo (Conectar + Autoconnect)
        theme.make_banner(
            self, kind="info",
            text=("A placa é procurada sozinha ao abrir. Conectar valida um "
                  "servidor informado à mão; Autoconnect refaz a busca — "
                  "primeiro o /24 da última placa usada, depois o da estação, "
                  "depois os /24 históricos do laboratório."),
        ).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        if autoconectar:
            # Depois que a janela existe, para o status já ter onde aparecer.
            self.after(200, self._conectar_automaticamente)

    # ==================================================================
    # Conexão automática ao abrir (versão 1.2)
    # ==================================================================

    def _conectar_automaticamente(self):
        """Conecta sozinho, sem o usuário clicar em nada e sem diálogos.

        Tenta primeiro a placa lembrada — um handshake só, instantâneo — e
        só cai na varredura da LAN se ela não responder. Falhar aqui não é
        erro: o painel continua utilizável à mão, e quem está sem placa
        (gerador de sinais, comparação, projeto de FIR) não leva um pop-up
        na cara ao abrir o programa.
        """
        if self._busy():
            return

        lembrada = ler_placa_lembrada()
        try:
            porta = int(self.var_port.get())
        except ValueError:
            porta = 5000

        self._set_busy(True)
        self.var_status.set("Procurando a placa...")
        self.lbl_status.configure(foreground=theme.COLORS["info_fg"])
        self._cancel_event = threading.Event()
        self._success_handled = False

        conhecidas = ler_placas_conhecidas()

        def run():
            # Com mais de uma placa preparada nesta estação, escolher sozinho
            # a menos ocupada: o servidor atende um cliente por vez, então o
            # tempo do handshake é uma medida direta de fila. O aluno não
            # precisa saber que existem duas placas, nem qual é a dele.
            if len(conhecidas) > 1:
                livre = self._escolher_placa_livre(conhecidas, porta)
                if livre is not None:
                    srv, quantas, outras = livre
                    self.after(0, self._on_search_success, srv, quantas, outras)
                    return
            elif conhecidas:
                srv = self._sondar(conhecidas[0], porta)
                if srv is not None and srv.preparada:
                    self.after(0, self._on_search_success, srv)
                    return
            try:
                achados = discover_servers(
                    subnets=subredes_provaveis(lembrada or (conhecidas[0] if conhecidas else None)), port=porta,
                    connect_timeout=0.3, read_timeout=0.5, max_workers=64,
                    cancel_event=self._cancel_event, stop_on_first=True,
                )
            except Exception:
                achados = []
            achados = [a for a in achados if a.preparada]
            if achados:
                self.after(0, self._on_search_success, achados[0])
            else:
                self.after(0, self._autoconexao_sem_placa, lembrada)

        self._search_thread = threading.Thread(target=run, daemon=True)
        self._search_thread.start()

    @classmethod
    def _escolher_placa_livre(cls, ips: List[str], porta: int
                              ) -> Optional[Tuple[ServerInfo, int, str]]:
        """Escolhe a placa para este computador. Devolve (placa, quantas
        responderam, uma linha sobre as outras) ou None.

        Com a porta de estado (servidor de 28/09/2026 em diante), cada placa
        diz na hora se está livre e quantos computadores a usaram no último
        minuto. Fica-se com a livre e menos usada: isso divide a turma entre
        as placas, em vez de todos caírem na que respondeu primeiro. Sem a
        porta de estado em nenhuma, vale o método antigo, abaixo.
        """
        import concurrent.futures as cf

        with cf.ThreadPoolExecutor(max_workers=max(2, len(ips))) as pool:
            estados = [e for e in pool.map(lambda ip: consultar_estado(ip, porta), ips)
                       if e is not None]
        candidatas = sorted((e for e in estados if e.preparada),
                            key=lambda e: (e.ocupada, e.clientes_recentes, e.rtt_s))
        for escolhida in candidatas:
            srv = cls._sondar(escolhida.ip, porta)
            if srv is not None and srv.preparada:
                outras = "; ".join(f"{e.ip}: {e.descricao()}"
                                   for e in estados if e.ip != escolhida.ip)
                return (srv, len(estados), outras)
        antigo = cls._escolher_pelo_ping(ips, porta)
        return None if antigo is None else (antigo[0], antigo[1], "")

    @classmethod
    def _escolher_pelo_ping(cls, ips: List[str], porta: int
                            ) -> Optional[Tuple[ServerInfo, int]]:
        """Método antigo: sonda todas em paralelo e devolve a que respondeu
        mais rápido.

        Por que o tempo do OP_PING mede ocupação: o servidor da placa é um
        laço accept/atende/fecha sem thread nenhuma, então um cliente no
        meio de uma convolução de ~200 ms segura o próximo na fila do
        listen(). Uma placa livre responde em milissegundos; uma ocupada
        responde depois de terminar o que está fazendo.

        Não é alocação de verdade — dois alunos que abram o cliente no
        mesmo instante ainda podem cair na mesma placa. Isso é a v1.4. O
        que isto resolve é o caso comum, e sem nenhum serviço novo.

        Devolve (placa escolhida, quantas responderam) ou None.
        """
        import concurrent.futures as cf

        def sondar_cronometrado(ip: str) -> Optional[Tuple[float, ServerInfo]]:
            t0 = time.monotonic()
            srv = cls._sondar(ip, porta)
            if srv is None:
                return None
            return (time.monotonic() - t0, srv)

        respostas: List[Tuple[float, ServerInfo]] = []
        with cf.ThreadPoolExecutor(max_workers=max(2, len(ips))) as pool:
            for r in pool.map(sondar_cronometrado, ips):
                if r is not None:
                    respostas.append(r)

        # Uma placa recém-ligada responde ao PING mas ainda tem o bitstream
        # de fábrica; escolhê-la travaria o HPS dela na primeira operação.
        respostas = [r for r in respostas if r[1].preparada]
        if not respostas:
            return None
        respostas.sort(key=lambda r: r[0])
        return (respostas[0][1], len(respostas))

    @staticmethod
    def _sondar(host: str, porta: int) -> Optional[ServerInfo]:
        """Um OP_PING contra um host conhecido. Devolve None em vez de levantar."""
        try:
            resp = TcpClient(host, porta, timeout=2.0).request(build_ping_request())
            return ServerInfo(ip=host, port=porta,
                              info=decode_ping_response(resp))
        except Exception:
            return None

    def _autoconexao_sem_placa(self, lembrada: Optional[str]):
        self._set_busy(False)
        if lembrada:
            self.var_status.set(
                f"A placa {lembrada} não respondeu ou ainda não foi preparada, "
                "e nenhuma outra foi encontrada. Rode ./morphe-up.sh ou informe o host."
            )
        else:
            self.var_status.set(
                "Nenhuma placa encontrada na rede. Rode ./morphe-up.sh, "
                "ou use as ferramentas que não precisam de placa."
            )
        self.lbl_status.configure(foreground=theme.COLORS["text_muted"])

    # ==================================================================
    # Guarda de exclusão mútua
    # ==================================================================

    def _busy(self) -> bool:
        """True se autoconnect OU conexão manual estiver em andamento."""
        for t in (self._search_thread, self._connect_thread):
            if t is not None and t.is_alive():
                return True
        return False

    # ==================================================================
    # Conexão manual: handshake OP_PING contra o host informado
    # ==================================================================

    def _on_connect(self):
        if self._busy():
            return

        # Validação síncrona dos campos (reusa make_client, que já checa
        # host/porta/timeout). Erros de campo não vão para a thread.
        try:
            client = self.make_client()
        except ValueError as e:
            messagebox.showerror("Configuração", str(e))
            return

        self._set_connect_busy(True)
        self.var_status.set(f"Conectando a {client.host}:{client.port}...")
        self.lbl_status.configure(foreground=theme.COLORS["info_fg"])

        def run():
            try:
                resp = client.request(build_ping_request())
                info = decode_ping_response(resp)  # valida service=morphe
                srv = ServerInfo(ip=client.host, port=client.port, info=info)
            except Exception as e:  # classificado no handler da thread Tk
                self.after(0, self._on_connect_error,
                           client.host, client.port, e)
                return
            self.after(0, self._on_connect_success, srv)

        self._connect_thread = threading.Thread(target=run, daemon=True)
        self._connect_thread.start()

    def _on_connect_success(self, srv: ServerInfo):
        self._set_connect_busy(False)
        gravar_placa_lembrada(srv.ip)
        self.var_status.set(
            f"Conectado a {srv.ip}:{srv.port} — {srv.hostname} "
            f"(FFT N={srv.fft_n}, Conv N={srv.conv_n_max})"
        )
        self.lbl_status.configure(foreground=theme.COLORS["ok_fg"])
        self._agenda_estado()

    def _on_connect_error(self, host: str, port, e: Exception):
        self._set_connect_busy(False)
        self.var_status.set(f"Falha ao conectar em {host}:{port}.")
        self.lbl_status.configure(foreground=theme.COLORS["danger"])
        messagebox.showerror(
            "Conectar", self._describe_connect_error(host, port, e))

    @staticmethod
    def _describe_connect_error(host: str, port, e: Exception) -> str:
        """Traduz a exceção do handshake em mensagem acionável.

        A ordem dos testes importa: `socket.timeout` e
        `ConnectionRefusedError` são subclasses de `OSError`, então precisam
        vir antes do caso genérico.
        """
        if isinstance(e, (socket.timeout, TimeoutError)):
            return (f"Tempo esgotado ao conectar em {host}:{port}.\n\n"
                    "O host pode estar fora do ar, em outra rede, ou o "
                    "timeout é curto demais. Confira o IP e, se preciso, "
                    "aumente o timeout.")
        if isinstance(e, ConnectionRefusedError):
            return (f"Conexão recusada por {host}:{port}.\n\n"
                    "Existe um host nesse IP, mas nada escutando na porta — "
                    "o servidor Morphe provavelmente não está rodando, ou a "
                    "porta está errada.")
        if isinstance(e, RuntimeError):
            # Respondeu, porém com status de erro ou sem service=morphe.
            return (f"{host}:{port} respondeu, mas não se identificou como "
                    f"servidor Morphe.\n\nDetalhe: {e}")
        if isinstance(e, ValueError):
            # magic/opcode/versão inesperados em parse_response_header.
            return (f"{host}:{port} respondeu, mas fora do protocolo Morphe "
                    "(cabeçalho ou opcode inesperado). Provavelmente é outro "
                    "serviço nessa porta.")
        if isinstance(e, OSError):
            return (f"Não foi possível conectar em {host}:{port}.\n\n"
                    f"Detalhe: {e}")
        return f"Falha ao conectar em {host}:{port}.\n\nDetalhe: {e}"

    # ==================================================================
    # Autoconnect: fluxo plug-and-play em background
    # ==================================================================

    def _on_autoconnect(self):
        if self._busy():
            return

        # Comeca pelo /24 da placa lembrada: as placas trocam de IP por DHCP
        # e ja foram vistas fora dos 101/102/103.
        conhecidas = ler_placas_conhecidas()
        subnets = subredes_provaveis(ler_placa_lembrada() or (conhecidas[0] if conhecidas else None))
        port = 5000  # constante do hardware

        self._set_busy(True)
        self.var_status.set("Buscando servidor Morphe na LAN...")
        self.lbl_status.configure(foreground=theme.COLORS["info_fg"])
        self._cancel_event = threading.Event()
        self._success_handled = False

        def on_found(srv: ServerInfo):
            self.after(0, self._on_search_success, srv)

        def run():
            try:
                discover_servers(
                    subnets=subnets, port=port,
                    connect_timeout=0.3, read_timeout=0.5,
                    max_workers=64,
                    on_found=on_found,
                    cancel_event=self._cancel_event,
                    stop_on_first=True,
                )
            except Exception as e:
                self.after(0, self._on_search_error, str(e))
                return
            if not self._success_handled:
                if self._cancel_event.is_set():
                    self.after(0, self._on_search_cancelled)
                else:
                    self.after(0, self._on_search_not_found)

        self._search_thread = threading.Thread(target=run, daemon=True)
        self._search_thread.start()

    def _on_search_success(self, srv: ServerInfo, entre: int = 1, outras: str = ""):
        if self._success_handled:
            return
        self._success_handled = True
        self.var_host.set(srv.ip)
        self.var_port.set(str(srv.port))
        # Escolha automática entre várias placas NÃO reescreve a placa
        # lembrada: ela é do morphe-up.sh, e sobrescrevê-la faria os
        # clientes se empurrarem de uma placa para a outra.
        if entre <= 1:
            gravar_placa_lembrada(srv.ip)
        self._set_busy(False)
        sufixo = f" — a mais livre entre {entre} placas" if entre > 1 else ""
        if outras:
            sufixo += f"\nOutras placas: {outras}"
        self.var_status.set(
            f"Conectado a {srv.ip} — {srv.hostname} "
            f"(FFT N={srv.fft_n}, Conv N={srv.conv_n_max}){sufixo}"
        )
        self.lbl_status.configure(foreground=theme.COLORS["ok_fg"])
        self._agenda_estado()

    # ==================================================================
    # Estado da placa conectada, de tempos em tempos (porta de estado)
    # ==================================================================

    def _agenda_estado(self):
        if not self._estado_agendado:
            self._estado_agendado = True
            self.after(200, self._atualiza_estado)

    def _atualiza_estado(self):
        """Pergunta à placa conectada o que ela está fazendo e mostra numa
        linha. Em outra thread: um UDP sem resposta leva meio segundo."""
        if not self.winfo_exists():
            return
        host = self.var_host.get().strip()
        try:
            porta = int(self.var_port.get())
        except ValueError:
            porta = 5000

        def run():
            e = consultar_estado(host, porta) if host else None
            try:
                self.after(0, self._mostra_estado, host, e)
            except RuntimeError:        # a janela fechou
                pass

        threading.Thread(target=run, daemon=True).start()
        self.after(ESTADO_INTERVALO_MS, self._atualiza_estado)

    def _mostra_estado(self, host: str, e: Optional[EstadoPlaca]):
        if e is None:
            # servidor antigo, ou placa fora do ar: nada a dizer aqui
            self.var_estado.set("")
            return
        self.var_estado.set(f"Placa {host} agora: {e.descricao()}")

    def estado_placa(self, timeout: float = 0.5) -> Optional[EstadoPlaca]:
        """Para as janelas explicarem uma espera: o que a placa conectada está
        fazendo agora (None se ela não tem a porta de estado)."""
        try:
            return consultar_estado(self.var_host.get().strip(),
                                    int(self.var_port.get()), timeout)
        except ValueError:
            return None

    def _on_search_not_found(self):
        self._set_busy(False)
        self.var_status.set("")
        messagebox.showerror(
            "Autoconnect",
            "Nenhum servidor Morphe foi encontrado na rede local.\n\n"
            "Possíveis causas:\n"
            "- O servidor não está rodando no DE1-SoC\n"
            "- Cliente e servidor estão em redes diferentes\n"
            "- O servidor está em sub-rede fora de 101/102/103\n\n"
            "Verifique se o servidor está ativo no DE1-SoC e informe "
            "host e porta manualmente."
        )

    def _on_search_error(self, msg: str):
        self._set_busy(False)
        self.var_status.set("")
        messagebox.showerror("Autoconnect — erro", msg)

    def _on_search_cancelled(self):
        self._set_busy(False)
        self.var_status.set("Busca cancelada.")
        self.lbl_status.configure(foreground=theme.COLORS["text_muted"])

    # ==================================================================
    # Estados de "ocupado" dos botões (ambos se desabilitam mutuamente)
    # ==================================================================

    def _buttons_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.btn_connect.configure(state=state)
        self.btn_autoconnect.configure(state=state)

    def _set_busy(self, busy: bool):
        """Autoconnect em progresso: trava ambos, rotula o Autoconnect."""
        self._buttons_enabled(not busy)
        self.btn_autoconnect.configure(
            text="Buscando..." if busy else "Autoconnect")
        if not busy:
            self.btn_connect.configure(text="Conectar")

    def _set_connect_busy(self, busy: bool):
        """Conexão manual em progresso: trava ambos, rotula o Conectar."""
        self._buttons_enabled(not busy)
        self.btn_connect.configure(
            text="Conectando..." if busy else "Conectar")
        if not busy:
            self.btn_autoconnect.configure(text="Autoconnect")

    # ==================================================================
    # API pública usada pelas janelas filhas
    # ==================================================================

    def make_client(self):
        host = self.var_host.get().strip()
        try:
            port = int(self.var_port.get())
            timeout = float(self.var_timeout.get())
        except ValueError as e:
            raise ValueError("Porta e timeout devem ser numéricos") from e
        if not host:
            raise ValueError("Host vazio")
        return TcpClient(host, port, timeout=timeout)
