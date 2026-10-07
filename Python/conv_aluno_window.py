"""
conv_aluno_window.py -- janela da CONVOLUCAO DO ALUNO: o mesmo x[n] e h[n]
vao para o conv_aluno.v (o modulo que o aluno escreve no roteiro da
convolucao, docs/roteiro-conv) e para o conv1d.v (a convolucao do Morphe),
e a janela compara as duas saidas amostra a amostra.

Reaproveita o que ja existe, como a janela da soma:
  - os dois sinais vem do SignalPanel;
  - o desenho e o _stem_signal da janela de convolucao;
  - Q15.16 e a volta sao as do dsp_core;
  - a placa e a do painel "Placas do laboratorio" (master.tcp_panel);
  - os pedidos vao numa thread, para a janela nao congelar.

O conv_aluno faz a conta do mesmo jeito do conv1d (produto em 64 bits, bits
[47:16], acumulador de 32 bits); por isso a comparacao e BIT A BIT. A mesma
conta em NumPy (conv_referencia) entra como terceira opiniao: se o aluno e o
conv1d discordam, ela diz qual dos dois errou.
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
from morphe_config import CONV_ALUNO_N_MAX
from morphe_protocol import (DTYPE_INT32, build_conv_aluno_request, build_conv_request,
                             decode_conv_aluno_response, decode_conv_response)
from plot_toolbar import PlotToolbar
from signal_panel import SignalPanel


def conv_referencia(x_q: np.ndarray, h_q: np.ndarray) -> np.ndarray:
    """A conta do conv1d em NumPy: cada produto em 64 bits, deslocado 16 bits
    para a direita (bits [47:16]), somado num acumulador de 32 bits que da a
    volta sem saturar."""
    x = np.asarray(x_q, dtype=np.int64)
    h = np.asarray(h_q, dtype=np.int64)
    y = np.zeros(x.size + h.size - 1, dtype=np.int64)
    for k in range(x.size):                       # uma coluna da tabela por vez
        y[k:k + h.size] += (x[k] * h) >> 16
    return ((y + 2**31) % 2**32) - 2**31          # de volta a 32 bits com sinal


class ConvAlunoWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Morphe — Convolução do aluno × conv1d (roteiro da convolução)")
        self.geometry("1240x900")
        self.configure(bg=theme.COLORS["bg"])
        theme.setup_styles(self)

        self.x_sig: Optional[dsp.Signal] = None
        self.h_sig: Optional[dsp.Signal] = None
        self.y_aluno: Optional[dsp.Signal] = None
        self.y_conv1d: Optional[dsp.Signal] = None
        self.dif: Optional[dsp.Signal] = None

        self.status = tk.StringVar(
            value="Gere x[n] e h[n] e clique em Comparar na FPGA.")
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
        self.x_panel = SignalPanel(parent, title="Sinal x[n]", on_generate=self._on_gen_x,
                                   default_N=32, default_type="Senóide",
                                   max_N=CONV_ALUNO_N_MAX)
        self.x_panel.pack(fill="x")
        self.h_panel = SignalPanel(parent, title="Resposta ao impulso h[n]",
                                   on_generate=self._on_gen_h, default_N=8,
                                   default_type="Degrau unitário", max_N=CONV_ALUNO_N_MAX)
        self.h_panel.pack(fill="x", pady=(8, 0))

        op = ttk.LabelFrame(parent, text=" Operação ", style="Card.TLabelframe",
                            padding=(14, 12, 14, 14))
        op.pack(fill="x", pady=(12, 0))
        ttk.Label(op, style="SectionHint.TLabel", wraplength=300, justify="left",
                  text=f"x e h com até {CONV_ALUNO_N_MAX} amostras, em Q15.16. "
                       "Os dois vão para o seu conv_aluno e para o conv1d do "
                       "Morphe; a saída tem nx + nh − 1 amostras.").pack(anchor="w", pady=(0, 8))
        self.btn = ttk.Button(op, text="Comparar na FPGA", style="Primary.TButton",
                              command=self._on_comparar)
        self.btn.pack(fill="x")

    def _build_plots(self, parent):
        self.fig = Figure(figsize=(7, 9), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        self.ax_x = self.fig.add_subplot(411)
        self.ax_h = self.fig.add_subplot(412)
        self.ax_y = self.fig.add_subplot(413)
        self.ax_d = self.fig.add_subplot(414)
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.toolbar = PlotToolbar(self.canvas)

    def _redraw(self):
        _stem_signal(self.ax_x, self.x_sig, "x[n]", dsp.COLOR_X)
        _stem_signal(self.ax_h, self.h_sig, "h[n]", dsp.COLOR_H)
        _stem_signal(self.ax_y, self.y_aluno, "y[n] do conv_aluno (haste)  ×  conv1d (×)",
                     dsp.COLOR_Y)
        if self.y_conv1d is not None:
            self.ax_y.plot(self.y_conv1d.n, self.y_conv1d.x, "x", color="black",
                           markersize=5, label="conv1d")
        _stem_signal(self.ax_d, self.dif,
                     "diferença conv_aluno − conv1d, em unidades de 1/65536", "tab:red")
        self.fig.tight_layout()
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    def _on_gen_x(self, panel: SignalPanel):
        try:
            self.x_sig = panel.build()
            self._limpa_saidas()
        except Exception as e:
            messagebox.showerror("Erro em x[n]", str(e))

    def _on_gen_h(self, panel: SignalPanel):
        try:
            self.h_sig = panel.build()
            self._limpa_saidas()
        except Exception as e:
            messagebox.showerror("Erro em h[n]", str(e))

    def _limpa_saidas(self):
        self.y_aluno = self.y_conv1d = self.dif = None
        self._redraw()

    def _on_comparar(self):
        if self.x_sig is None or self.h_sig is None:
            messagebox.showwarning("Atenção", "Gere x[n] e h[n] antes.")
            return
        try:
            client = self.master.tcp_panel.make_client()
        except Exception as e:
            messagebox.showerror("Configuração", str(e))
            return

        x_q = dsp.float_to_q1516(self.x_sig.x)
        h_q = dsp.float_to_q1516(self.h_sig.x)
        # a origem de y e a soma das origens (h comecando em n = -1 adianta y)
        n0 = int(self.x_sig.n[0]) + int(self.h_sig.n[0])

        self.btn.config(state="disabled")
        self.status.set(f"Enviando x ({x_q.size}) e h ({h_q.size}) ao conv_aluno e ao conv1d...")

        def worker():
            # os dois pedidos sao independentes: um erro no do aluno nao
            # impede de ver o do conv1d
            y_al, err_al, y_cv, err_cv = None, None, None, None
            try:
                resp = client.request(build_conv_aluno_request(x_q, h_q, DTYPE_INT32))
                y_al = decode_conv_aluno_response(resp)
            except Exception as e:
                err_al = e
            try:
                resp = client.request(build_conv_request(x_q, h_q, DTYPE_INT32))
                y_cv = decode_conv_response(resp).astype(np.int64)
            except Exception as e:
                err_cv = e
            self.after(0, lambda: self._on_resultado(x_q, h_q, n0, y_al, err_al, y_cv, err_cv))

        threading.Thread(target=worker, daemon=True).start()

    def _on_resultado(self, x_q, h_q, n0, y_al, err_al, y_cv, err_cv):
        self.btn.config(state="normal")
        ref = conv_referencia(x_q, h_q)
        n = np.arange(ref.size) + n0

        def sinal(y_q, desc):
            return dsp.Signal(n=n[:y_q.size], x=dsp.q1516_to_float(y_q), description=desc)

        self.y_aluno = sinal(y_al, f"{y_al.size} amostras") if y_al is not None else None
        self.y_conv1d = sinal(y_cv, "") if y_cv is not None else None
        self.dif = None
        if y_al is not None and y_cv is not None and y_al.size == y_cv.size:
            self.dif = dsp.Signal(n=n, x=(y_al - y_cv).astype(float),
                                  description=f"máx |dif| = {int(np.max(np.abs(y_al - y_cv)))}")
        self._redraw()

        if err_al is not None or err_cv is not None:
            msgs = []
            if err_al is not None:
                msgs.append(f"conv_aluno: {err_al}")
            if err_cv is not None:
                msgs.append(f"conv1d: {err_cv}")
            self.status.set("Erro — ver mensagem.")
            messagebox.showerror("Erro na comparação", "\n\n".join(msgs))
            return

        total = ref.size
        iguais = int(np.sum(y_al == y_cv))
        if iguais == total:
            self.status.set(f"OK: as {total} amostras do conv_aluno são iguais, bit a bit, "
                            "às do conv1d.")
            return
        al_ok = int(np.sum(y_al == ref))
        cv_ok = int(np.sum(y_cv == ref))
        primeira = int(np.argmax(y_al != y_cv))
        self.status.set(f"DIFERENTES: {iguais} de {total} amostras iguais. A primeira "
                        f"diferença é em n = {n[primeira]}. Contra a conta no NumPy: "
                        f"conv_aluno acerta {al_ok}, conv1d acerta {cv_ok}.")
