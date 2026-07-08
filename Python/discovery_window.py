"""discovery_window.py -- janela de descoberta de servidores Morphe na LAN.

Faz scan TCP+OP_PING nas tres sub-redes /24 que o usuario especificar
(default: terceiros octetos 101, 102, 103 do /16 detectado). O scan roda
em uma thread separada para nao travar a UI; resultados sao publicados
de volta na thread Tk via .after().
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, Optional

from morphe_protocol import (
    ServerInfo, detect_subnets, discover_servers, get_local_ip,
)


class DiscoveryWindow(tk.Toplevel):
    """Janela de busca. Recebe um callback `on_pick(ip, port)` que e
    chamado quando o usuario clica em "Usar este" sobre um resultado."""

    def __init__(self, master, on_pick: Callable[[str, int], None],
                 default_port: int = 5000):
        super().__init__(master)
        self.title("Morphe - Buscar servidores na rede")
        self.geometry("780x520")

        self._on_pick = on_pick
        self._scan_thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()

        # ---- Cabecalho de instrucao ------------------------------------
        info = tk.Label(
            self,
            text=(
                "Buscar servidores Morphe na rede local.\n"
                "Cliente e servidor precisam estar na mesma LAN. O scan "
                "verifica os tres /24 indicados, na ordem -- terceiros "
                "octetos por padrao 101, 102, 103."
            ),
            background="#fff3cd", foreground="#664d03",
            relief="solid", borderwidth=1,
            padx=10, pady=6, justify="left",
            font=("TkDefaultFont", 9),
        )
        info.pack(fill="x", padx=10, pady=(10, 6))

        # ---- Configuracao da busca -------------------------------------
        cfg = ttk.LabelFrame(self, text="Configuracao", padding=8)
        cfg.pack(fill="x", padx=10, pady=4)

        # Prefixo /16
        ttk.Label(cfg, text="Prefixo da rede (a.b):").grid(
            row=0, column=0, sticky="w")
        self.var_prefix = tk.StringVar(value="172.16")
        ttk.Entry(cfg, textvariable=self.var_prefix, width=12).grid(
            row=0, column=1, sticky="w", padx=4)

        ttk.Button(cfg, text="Detectar do PC",
                   command=self._on_detect).grid(
            row=0, column=2, sticky="w", padx=(8, 0))

        local_ip = get_local_ip()
        local_lbl = (f"IP local detectado: {local_ip}"
                     if local_ip else
                     "Nao foi possivel detectar IP local automaticamente.")
        ttk.Label(cfg, text=local_lbl, foreground="#666").grid(
            row=0, column=3, sticky="w", padx=(8, 0))

        # Terceiros octetos
        ttk.Label(cfg, text="Terceiros octetos (separados por virgula):").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.var_octets = tk.StringVar(value="101, 102, 103")
        ttk.Entry(cfg, textvariable=self.var_octets, width=24).grid(
            row=1, column=2, columnspan=2, sticky="w", padx=4, pady=(6, 0))

        # Porta + timeout
        ttk.Label(cfg, text="Porta:").grid(row=2, column=0, sticky="w",
                                           pady=(6, 0))
        self.var_port = tk.StringVar(value=str(default_port))
        ttk.Entry(cfg, textvariable=self.var_port, width=8).grid(
            row=2, column=1, sticky="w", padx=4, pady=(6, 0))

        ttk.Label(cfg, text="Timeout por host (s):").grid(
            row=2, column=2, sticky="w", pady=(6, 0))
        self.var_timeout = tk.StringVar(value="0.3")
        ttk.Entry(cfg, textvariable=self.var_timeout, width=8).grid(
            row=2, column=3, sticky="w", padx=4, pady=(6, 0))

        # ---- Botoes de acao --------------------------------------------
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(4, 0))

        self.btn_start = ttk.Button(
            btns, text="Iniciar busca", command=self._on_start_scan)
        self.btn_start.pack(side="left", padx=(0, 4))

        self.btn_cancel = ttk.Button(
            btns, text="Cancelar", command=self._on_cancel,
            state="disabled")
        self.btn_cancel.pack(side="left", padx=(0, 4))

        self.btn_use = ttk.Button(
            btns, text="Usar este", command=self._on_use,
            state="disabled")
        self.btn_use.pack(side="right")

        # ---- Resultados (Treeview) -------------------------------------
        cols = ("ip", "hostname", "version", "fft_n", "conv_n", "uptime")
        self.tree = ttk.Treeview(self, columns=cols, show="headings",
                                 height=10)
        self.tree.heading("ip",       text="IP")
        self.tree.heading("hostname", text="Hostname")
        self.tree.heading("version",  text="Ver.")
        self.tree.heading("fft_n",    text="FFT N")
        self.tree.heading("conv_n",   text="Conv N max")
        self.tree.heading("uptime",   text="Uptime (s)")
        self.tree.column("ip",       width=130, anchor="w")
        self.tree.column("hostname", width=200, anchor="w")
        self.tree.column("version",  width=60,  anchor="center")
        self.tree.column("fft_n",    width=80,  anchor="center")
        self.tree.column("conv_n",   width=100, anchor="center")
        self.tree.column("uptime",   width=100, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(8, 4))
        self.tree.bind("<<TreeviewSelect>>", self._on_select_change)
        self.tree.bind("<Double-1>", lambda e: self._on_use())

        # ---- Status bar + progress -------------------------------------
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=(0, 8))
        self.var_status = tk.StringVar(value="Pronto.")
        ttk.Label(bar, textvariable=self.var_status,
                  relief="sunken", anchor="w").pack(side="left",
                                                    fill="x", expand=True)
        self.progress = ttk.Progressbar(bar, mode="determinate", length=200)
        self.progress.pack(side="right", padx=(8, 0))

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------

    def _on_detect(self):
        """Detecta o /16 do PC e preenche o campo de prefixo."""
        ip = get_local_ip()
        if ip is None:
            messagebox.showwarning(
                "Detectar",
                "Nao foi possivel detectar IP local. Verifique a conexao.")
            return
        parts = ip.split(".")
        if len(parts) >= 2:
            self.var_prefix.set(f"{parts[0]}.{parts[1]}")
            self.var_status.set(f"Prefixo detectado a partir de {ip}.")

    def _parse_subnets(self) -> list[str]:
        prefix = self.var_prefix.get().strip()
        if prefix.count(".") != 1 or not all(
                p.isdigit() and 0 <= int(p) <= 255 for p in prefix.split(".")):
            raise ValueError(
                "Prefixo invalido. Use o formato 'a.b' (ex.: 172.16).")
        octets_raw = self.var_octets.get().replace(";", ",").split(",")
        octets: list[int] = []
        for o in octets_raw:
            o = o.strip()
            if not o:
                continue
            if not o.isdigit() or not (0 <= int(o) <= 255):
                raise ValueError(
                    f"Octeto invalido: {o!r}. Use numeros entre 0 e 255.")
            octets.append(int(o))
        if not octets:
            raise ValueError("Informe ao menos um terceiro octeto.")
        return [f"{prefix}.{o}.0/24" for o in octets]

    # ------------------------------------------------------------------

    def _on_start_scan(self):
        if self._scan_thread is not None and self._scan_thread.is_alive():
            return
        try:
            subnets = self._parse_subnets()
            port = int(self.var_port.get())
            timeout = float(self.var_timeout.get())
            if not (0 < port <= 65535):
                raise ValueError("Porta fora da faixa.")
            if not (0.05 <= timeout <= 5.0):
                raise ValueError("Timeout deve estar entre 0.05 e 5.0 s.")
        except ValueError as e:
            messagebox.showerror("Configuracao invalida", str(e))
            return

        # Limpa estado da UI
        for it in self.tree.get_children():
            self.tree.delete(it)
        self.btn_use.configure(state="disabled")
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.progress["value"] = 0
        self.var_status.set(
            f"Buscando em {len(subnets)} sub-rede(s): "
            + ", ".join(subnets) + " ...")
        self._cancel_event = threading.Event()

        def on_found(srv: ServerInfo):
            # Roda no worker -- agenda na thread Tk
            self.after(0, self._add_row, srv)

        def on_progress(done: int, total: int):
            self.after(0, self._update_progress, done, total)

        def run():
            try:
                discover_servers(
                    subnets=subnets, port=port,
                    connect_timeout=timeout, read_timeout=max(timeout, 0.5),
                    max_workers=64,
                    on_found=on_found, on_progress=on_progress,
                    cancel_event=self._cancel_event,
                )
            finally:
                self.after(0, self._scan_done)

        self._scan_thread = threading.Thread(target=run, daemon=True)
        self._scan_thread.start()

    def _on_cancel(self):
        if self._scan_thread is not None and self._scan_thread.is_alive():
            self._cancel_event.set()
            self.var_status.set("Cancelando ...")

    def _scan_done(self):
        self.btn_start.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        n = len(self.tree.get_children())
        cancelled = self._cancel_event.is_set()
        suffix = " (cancelado)" if cancelled else ""
        if n == 0:
            self.var_status.set(f"Busca concluida -- nenhum servidor "
                                f"encontrado{suffix}.")
        else:
            self.var_status.set(
                f"Busca concluida -- {n} servidor(es) encontrado(s)"
                f"{suffix}.")

    # ------------------------------------------------------------------

    def _add_row(self, srv: ServerInfo):
        self.tree.insert("", "end", values=(
            srv.ip,
            srv.hostname,
            srv.version,
            srv.fft_n,
            srv.conv_n_max,
            srv.info.get("uptime_s", "?"),
        ))

    def _update_progress(self, done: int, total: int):
        if total > 0:
            self.progress["maximum"] = total
            self.progress["value"] = done
            self.var_status.set(
                f"Verificando {done}/{total} hosts..."
            )

    def _on_select_change(self, _e=None):
        sel = self.tree.selection()
        self.btn_use.configure(state="normal" if sel else "disabled")

    def _on_use(self):
        sel = self.tree.selection()
        if not sel:
            return
        item = self.tree.item(sel[0])
        ip = item["values"][0]
        try:
            port = int(self.var_port.get())
        except ValueError:
            port = 5000
        try:
            self._on_pick(str(ip), port)
        except Exception as e:
            messagebox.showerror("Erro", str(e))
            return
        self.destroy()

    def _on_close(self):
        if self._scan_thread is not None and self._scan_thread.is_alive():
            self._cancel_event.set()
        self.destroy()
