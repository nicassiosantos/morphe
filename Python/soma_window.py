"""
soma_window.py -- janela da SOMA: y[n] = a[n] + b[n] calculada na FPGA.

Modulo de exemplo do roteiro "Como adicionar um modulo ao Morphe"
(docs/roteiro-modulo). Mostra o minimo que uma janela nova precisa, sempre
reaproveitando o que ja existe:

  - os dois sinais vem do SignalPanel, o mesmo de todas as janelas;
  - o desenho e o _stem_signal da janela de convolucao;
  - a conversao para Q15.16 e a volta sao as do dsp_core;
  - a placa e a do painel "Placas do laboratorio" (master.tcp_panel);
  - o pedido vai em uma thread, para a janela nao congelar esperando a rede.

A referencia e a mesma conta em ponto fixo no NumPy, com a mesma saturacao
do soma.v: a comparacao com a FPGA tem de dar igualdade BIT A BIT.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

import numpy as np

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import dsp_core as dsp
import morphe_theme as theme
from conv_window import _stem_signal
from morphe_config import SOMA_N_MAX
from morphe_protocol import DTYPE_INT32, build_soma_request, decode_soma_response
from plot_toolbar import PlotToolbar
from signal_panel import SignalPanel


def soma_referencia(a_q: np.ndarray, b_q: np.ndarray) -> np.ndarray:
    """A conta do soma.v em NumPy: soma em 64 bits e satura na faixa de 32."""
    s = np.asarray(a_q, dtype=np.int64) + np.asarray(b_q, dtype=np.int64)
    return np.clip(s, dsp.Q_MIN, dsp.Q_MAX)


class SomaWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Morphe — Soma via FPGA (exemplo do roteiro)")
        self.geometry("1240x820")
        self.configure(bg=theme.COLORS["bg"])
        theme.setup_styles(self)

        self.a_sig: Optional[dsp.Signal] = None
        self.b_sig: Optional[dsp.Signal] = None
        self.y_sig: Optional[dsp.Signal] = None

        self.status = tk.StringVar(value="Gere a[n] e b[n] e clique em Somar na FPGA.")
        theme.make_status_bar(self, self.status).pack(side="bottom", fill="x")

        root = ttk.Frame(self, style="Main.TFrame", padding=12)
        root.pack(fill="both", expand=True)
        lado = ttk.Frame(root, style="Main.TFrame")
        lado.pack(side="left", fill="y", padx=(0, 12))
        self._build_sidebar(lado)
        area = ttk.Frame(root, style="Main.TFrame")
        area.pack(side="right", fill="both", expand=True)
        self._build_plots(area)
        self._redraw()

    # ------------------------------------------------------------------
    def _build_sidebar(self, parent):
        self.a_panel = SignalPanel(parent, title="Sinal a[n]", on_generate=self._on_gen_a,
                                   default_N=32, default_type="Senóide", max_N=SOMA_N_MAX)
        self.a_panel.pack(fill="x")
        self.b_panel = SignalPanel(parent, title="Sinal b[n]", on_generate=self._on_gen_b,
                                   default_N=32, default_type="Degrau unitário", max_N=SOMA_N_MAX)
        self.b_panel.pack(fill="x", pady=(8, 0))

        op = ttk.LabelFrame(parent, text=" Operação ", style="Card.TLabelframe",
                            padding=(14, 12, 14, 14))
        op.pack(fill="x", pady=(12, 0))
        ttk.Label(op, style="SectionHint.TLabel", wraplength=300, justify="left",
                  text=f"Até {SOMA_N_MAX} amostras, em Q15.16. Se os tamanhos forem "
                       "diferentes, o menor é completado com zeros.").pack(anchor="w", pady=(0, 8))
        self.btn = ttk.Button(op, text="Somar na FPGA", style="Primary.TButton",
                              command=self._on_somar)
        self.btn.pack(fill="x")

    def _build_plots(self, parent):
        self.fig = Figure(figsize=(7, 8), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        self.ax_a = self.fig.add_subplot(311)
        self.ax_b = self.fig.add_subplot(312)
        self.ax_y = self.fig.add_subplot(313)
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.toolbar = PlotToolbar(self.canvas)

    def _redraw(self):
        _stem_signal(self.ax_a, self.a_sig, "a[n]", dsp.COLOR_X)
        _stem_signal(self.ax_b, self.b_sig, "b[n]", dsp.COLOR_H)
        _stem_signal(self.ax_y, self.y_sig, "y[n] = a[n] + b[n] (FPGA)", dsp.COLOR_Y)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    def _on_gen_a(self, panel: SignalPanel):
        try:
            self.a_sig = panel.build()
            self._redraw()
        except Exception as e:
            messagebox.showerror("Erro em a[n]", str(e))

    def _on_gen_b(self, panel: SignalPanel):
        try:
            self.b_sig = panel.build()
            self._redraw()
        except Exception as e:
            messagebox.showerror("Erro em b[n]", str(e))

    def _on_somar(self):
        if self.a_sig is None or self.b_sig is None:
            messagebox.showwarning("Atenção", "Gere a[n] e b[n] antes.")
            return
        try:
            client = self.master.tcp_panel.make_client()
        except Exception as e:
            messagebox.showerror("Configuração", str(e))
            return

        # mesmo tamanho para os dois; o indice n vem de a[n]
        n = max(self.a_sig.x.size, self.b_sig.x.size)
        a_q = dsp.float_to_q1516(dsp.pad_zeros_to(self.a_sig.x, n))
        b_q = dsp.float_to_q1516(dsp.pad_zeros_to(self.b_sig.x, n))
        n0 = int(self.a_sig.n[0]) if self.a_sig.n.size else 0

        self.btn.config(state="disabled")
        self.status.set(f"Enviando {n} amostras de a e de b à FPGA...")

        def worker():
            try:
                resp = client.request(build_soma_request(a_q, b_q, DTYPE_INT32))
                y_q = decode_soma_response(resp)
                self.after(0, lambda: self._on_resultado(y_q, a_q, b_q, n0))
            except Exception as e:
                self.after(0, lambda err=e: self._on_erro(err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_resultado(self, y_q, a_q, b_q, n0):
        ref = soma_referencia(a_q, b_q)
        iguais = int(np.sum(y_q == ref))
        n = y_q.size
        self.y_sig = dsp.Signal(n=np.arange(n) + n0, x=dsp.q1516_to_float(y_q),
                                description=f"{n} amostras, Q15.16")
        self._redraw()
        self.btn.config(state="normal")
        if iguais == n:
            self.status.set(f"OK: as {n} amostras da FPGA são iguais, bit a bit, "
                            "à soma em ponto fixo feita no NumPy.")
        else:
            self.status.set(f"ATENÇÃO: só {iguais} de {n} amostras iguais à referência.")

    def _on_erro(self, err: Exception):
        self.btn.config(state="normal")
        self.status.set("Erro — ver mensagem.")
        messagebox.showerror("Erro na soma", str(err))
