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

import socket
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

import morphe_theme as theme
from morphe_protocol import (
    TcpClient, ServerInfo, detect_subnets, discover_servers,
    build_ping_request, decode_ping_response,
)


class TcpConfigPanel(ttk.LabelFrame):
    def __init__(self, parent,
                 default_host: str = "192.168.1.10",
                 default_port: int = 5000):
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
        self.var_host = tk.StringVar(value=default_host)
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

        # Linha 5: banner informativo (Conectar + Autoconnect)
        theme.make_banner(
            self, kind="info",
            text=("Conectar valida o servidor informado (host/porta/timeout). "
                  "Autoconnect busca o primeiro servidor Morphe na LAN "
                  "(/24 nos octetos 101, 102 e 103 do /16 local)."),
        ).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10, 0))

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
        self.var_status.set(
            f"Conectado a {srv.ip}:{srv.port} — {srv.hostname} "
            f"(FFT N={srv.fft_n}, Conv N={srv.conv_n_max})"
        )
        self.lbl_status.configure(foreground=theme.COLORS["ok_fg"])

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

        subnets = detect_subnets((101, 102, 103))
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

    def _on_search_success(self, srv: ServerInfo):
        if self._success_handled:
            return
        self._success_handled = True
        self.var_host.set(srv.ip)
        self.var_port.set(str(srv.port))
        self._set_busy(False)
        self.var_status.set(
            f"Conectado a {srv.ip} — {srv.hostname} "
            f"(FFT N={srv.fft_n}, Conv N={srv.conv_n_max})"
        )
        self.lbl_status.configure(foreground=theme.COLORS["ok_fg"])

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
