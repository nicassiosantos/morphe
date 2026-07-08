"""
conv_window.py — janela para gerar dois sinais, enviá-los à FPGA por TCP
e exibir a convolução y[n] = x[n] * h[n] retornada.

Hardware: conv1d aceita até 128 amostras por entrada. Sinais menores são
zero-padded até 128. A configuração TCP é compartilhada com a janela
principal (master.tcp_panel).
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional

import numpy as np

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import dsp_core as dsp
import morphe_theme as theme
from signal_panel import SignalPanel
from morphe_protocol import build_conv_request, DTYPE_CODES
from popout_helper import open_or_focus, refresh_all
from plot_toolbar import PlotToolbar


# ----------------------------------------------------------------------
# Helpers de plot (inalterados — boa lógica reaproveitável)

def _attach_stem_format_coord(ax, n_arr: np.ndarray, x_arr: np.ndarray,
                               x_label: str = "n", y_label: str = "x"):
    if n_arr.size == 0:
        return
    n_arr = np.asarray(n_arr, dtype=float)
    x_arr = np.asarray(x_arr)

    def fmt(xc, yc):
        i = int(np.argmin(np.abs(n_arr - xc)))
        n_i = int(n_arr[i])
        try:
            v_str = f"{float(x_arr[i]):.4g}"
        except (TypeError, ValueError):
            v_str = str(x_arr[i])
        return f"{x_label}={n_i},  {y_label}[{n_i}] = {v_str}"

    ax.format_coord = fmt


def _stem_signal(ax, sig: Optional[dsp.Signal], title: str, color: str):
    ax.clear()
    if sig is None or sig.n.size == 0:
        theme.draw_empty_axes(ax, title)
        return
    n_plot = np.asarray(sig.n, dtype=float)
    ml, sl, _ = ax.stem(n_plot, sig.x, basefmt=" ")
    ml.set_markersize(4)
    ml.set_color(color)
    ml.set_markerfacecolor(color)
    sl.set_color(color)
    ax.set_title(f"{title}  —  {sig.description}", fontsize=9)
    ax.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
    n_min, n_max = float(n_plot.min()), float(n_plot.max())
    mx = max(1.0, 0.05 * (n_max - n_min))
    ax.set_xlim(n_min - mx, n_max + mx)
    if sig.x.size:
        x_min, x_max = float(np.min(sig.x)), float(np.max(sig.x))
        if x_min == x_max:
            x_min -= 0.5
            x_max += 0.5
        my = 0.1 * (x_max - x_min)
        ax.set_ylim(x_min - my, x_max + my)
    ax.set_xlabel("n")
    theme.style_plot_axes(ax)
    _attach_stem_format_coord(ax, n_plot, sig.x, x_label="n", y_label="x")


# ----------------------------------------------------------------------

class ConvolutionWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Morphe — Convolução via FPGA (TCP)")
        self.geometry("1320x840")
        self.configure(bg=theme.COLORS["bg"])

        theme.setup_styles(self)

        self.x_sig: Optional[dsp.Signal] = None
        self.h_sig: Optional[dsp.Signal] = None
        self.y_signal: Optional[dsp.Signal] = None
        self._popouts: dict = {}

        # Status bar
        self.status = tk.StringVar(value="Pronto.")
        theme.make_status_bar(self, self.status).pack(side="bottom", fill="x")

        root = ttk.Frame(self, style="Main.TFrame", padding=12)
        root.pack(fill="both", expand=True)

        sidebar = ttk.Frame(root, style="Main.TFrame")
        sidebar.pack(side="left", fill="y", padx=(0, 12))
        self._build_sidebar(sidebar)

        plot_area = ttk.Frame(root, style="Main.TFrame")
        plot_area.pack(side="right", fill="both", expand=True)
        self._build_plot_area(plot_area)

        self._redraw()

    # ------------------------------------------------------------------

    def _build_sidebar(self, parent: ttk.Frame):
        # ── Limitações: progressive disclosure ──
        hw_section = theme.CollapsibleSection(
            parent, title="Limitações da conv1d (FPGA)",
            expanded=False,
        )
        hw_section.pack(fill="x", pady=(0, 6))
        hw_text = (
            f"• Tamanho máximo: {dsp.MAX_CONV_INPUT_SIZE} amostras por sinal\n"
            f"• Sinais menores são zero-padded até {dsp.MAX_CONV_INPUT_SIZE}\n"
            f"• Faixa de valores (Q15.16): "
            f"[{dsp.Q_MIN_FLOAT:.1f}, {dsp.Q_MAX_FLOAT:.4f}]\n"
            f"• Resolução: 2⁻¹⁶ = {dsp.Q_RESOLUTION:.2e}"
        )
        theme.make_banner(
            hw_section.body, kind="warn", text=hw_text, wraplength=320,
        ).pack(fill="x")

        # ── Painéis dos dois sinais (max_N = 128) ──
        self.x_panel = SignalPanel(
            parent, title="Sinal x[n]",
            on_generate=self._on_gen_x,
            default_N=16,
            default_type="Retangular",
            max_N=dsp.MAX_CONV_INPUT_SIZE,
        )
        self.x_panel.pack(fill="x", pady=(6, 0))

        self.h_panel = SignalPanel(
            parent, title="Sinal h[n] (filtro/resposta)",
            on_generate=self._on_gen_h,
            default_N=8,
            default_type="Retangular",
            max_N=dsp.MAX_CONV_INPUT_SIZE,
        )
        self.h_panel.pack(fill="x", pady=(8, 0))

        # ── Operação & Exportação ──
        op = ttk.LabelFrame(
            parent, text=" Operação & Exportação ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        op.pack(fill="x", pady=(12, 0))
        op.columnconfigure(0, minsize=130)
        op.columnconfigure(1, weight=1)

        ttk.Label(op, text="Tipo de dado (gerador)",
                  style="Card.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6))
        self.dtype_var = tk.StringVar(value="float32")
        ttk.Combobox(op, textvariable=self.dtype_var,
                     values=["int32", "float32"], state="readonly").grid(
            row=0, column=1, sticky="ew", pady=(0, 6))

        ttk.Label(
            op,
            text="A conv1d da FPGA é Q15.16 nativa. "
                 "Valores fora da faixa serão saturados.",
            style="SectionHint.TLabel",
            wraplength=320,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 10))

        # PRIMARY: ação mais importante da tela
        self.btn_conv = ttk.Button(
            op, text="Convoluir na FPGA",
            style="Primary.TButton",
            command=self._on_convolve,
        )
        self.btn_conv.grid(row=2, column=0, columnspan=2, sticky="ew",
                           pady=(0, 4))

        # SECONDARY: exportação
        ttk.Button(
            op, text="Salvar tudo (x, h, y) em 1 arquivo .mrph",
            style="Secondary.TButton",
            command=self._on_save_all,
        ).grid(row=3, column=0, columnspan=2, sticky="ew")

        # "Visualizar em janela ampliada" removido — agora cada plot
        # tem seu próprio ⛶ no cabeçalho da área de plots.

    # ------------------------------------------------------------------

    def _build_plot_area(self, parent: ttk.Frame):
        # Cabeçalho com nome do plot + ícone ⛶ por plot.
        header = theme.make_plot_header_bar(
            parent,
            items=[
                ("x[n]",                  lambda: self._popout_one("x")),
                ("h[n]",                  lambda: self._popout_one("h")),
                ("y[n] = x[n] ∗ h[n]",    lambda: self._popout_one("y")),
            ],
        )
        header.pack(fill="x", pady=(0, 6))

        self.fig = Figure(figsize=(7, 8), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        self.ax_x = self.fig.add_subplot(311)
        self.ax_h = self.fig.add_subplot(312)
        self.ax_y = self.fig.add_subplot(313)

        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Ferramentas flutuantes (home/pan/zoom/salvar) no canto superior
        # direito — substituem a antiga toolbar cinza do rodapé.
        self.toolbar = PlotToolbar(self.canvas)

    # ------------------------------------------------------------------
    # Plots embutidos

    def _redraw(self):
        _stem_signal(self.ax_x, self.x_sig, "x[n]", dsp.COLOR_X)
        _stem_signal(self.ax_h, self.h_sig, "h[n]", dsp.COLOR_H)
        _stem_signal(self.ax_y, self.y_signal, "y[n] = x[n] * h[n]",
                     dsp.COLOR_Y)
        self.fig.tight_layout()
        self.canvas.draw_idle()
        refresh_all(self._popouts)

    # ------------------------------------------------------------------
    # Pop-outs reativos

    def _popout_one(self, which: str):
        if which == "x":
            title, color = "x[n]", dsp.COLOR_X
            getter = lambda: self.x_sig
        elif which == "h":
            title, color = "h[n]", dsp.COLOR_H
            getter = lambda: self.h_sig
        elif which == "y":
            title, color = "y[n] = x[n] * h[n]", dsp.COLOR_Y
            getter = lambda: self.y_signal
        else:
            return

        if getter() is None:
            messagebox.showwarning("Atenção", f"{title} ainda não foi gerado.")
            return

        def draw(fig: Figure):
            ax = fig.add_subplot(111)
            _stem_signal(ax, getter(), title, color)

        open_or_focus(self._popouts, key=f"one_{which}",
                      parent=self, title=f"Morphe — {title}",
                      draw_fn=draw, size="1000x600")

    # `_on_popout_all` removido: consolidação (sugestão 3 da UX review).

    # ------------------------------------------------------------------
    # Geração dos sinais

    def _on_gen_x(self, panel: SignalPanel):
        try:
            self.x_sig = panel.build()
            self._redraw()
            self.status.set(f"x[n]: {self.x_sig.description}")
        except Exception as e:
            messagebox.showerror("Erro em x[n]", str(e))

    def _on_gen_h(self, panel: SignalPanel):
        try:
            self.h_sig = panel.build()
            self._redraw()
            self.status.set(f"h[n]: {self.h_sig.description}")
        except Exception as e:
            messagebox.showerror("Erro em h[n]", str(e))

    # ------------------------------------------------------------------
    # Convolução na FPGA

    def _on_convolve(self):
        if self.x_sig is None or self.h_sig is None:
            messagebox.showwarning("Atenção", "Gere x[n] e h[n] antes.")
            return
        try:
            client = self.master.tcp_panel.make_client()
        except Exception as e:
            messagebox.showerror("Configuração", str(e))
            return

        for name, sig in (("x[n]", self.x_sig), ("h[n]", self.h_sig)):
            warn = dsp.q1516_range_warning(sig.x)
            if warn:
                if not messagebox.askyesno(
                    f"Aviso Q15.16 em {name}",
                    f"{warn}\n\nContinuar mesmo assim?",
                ):
                    return

        try:
            x_padded = dsp.pad_zeros_to(self.x_sig.x, dsp.MAX_CONV_INPUT_SIZE)
            h_padded = dsp.pad_zeros_to(self.h_sig.x, dsp.MAX_CONV_INPUT_SIZE)
        except ValueError as e:
            messagebox.showerror("Tamanho excedido", str(e))
            return

        nx_orig = int(self.x_sig.x.size)
        nh_orig = int(self.h_sig.x.size)
        n0_x = int(self.x_sig.n[0]) if self.x_sig.n.size else 0
        n0_h = int(self.h_sig.n[0]) if self.h_sig.n.size else 0

        self.btn_conv.config(state="disabled")
        self.status.set(
            f"Padding {nx_orig}→{dsp.MAX_CONV_INPUT_SIZE} e "
            f"{nh_orig}→{dsp.MAX_CONV_INPUT_SIZE}, enviando à FPGA..."
        )

        x_q = dsp.float_to_q1516(x_padded)
        h_q = dsp.float_to_q1516(h_padded)

        def worker():
            try:
                req = build_conv_request(
                    x_q.astype(np.float64), h_q.astype(np.float64),
                    DTYPE_CODES["int32"],
                )
                resp = client.request(req)
                if not resp.ok:
                    raise RuntimeError(resp.payload.decode("utf-8", "replace"))

                be = np.dtype(">i4")
                y_q = np.frombuffer(resp.payload, dtype=be, count=resp.n_out)
                y_full = dsp.q1516_to_float(y_q)

                n_useful = nx_orig + nh_orig - 1
                y = y_full[:n_useful]
                n = np.arange(n_useful, dtype=np.int64) + (n0_x + n0_h)

                result = dsp.Signal(
                    n=n, x=y,
                    description=(
                        f"y[n] = x ∗ h  (N útil={n_useful}, "
                        f"hardware: {dsp.MAX_CONV_INPUT_SIZE}+"
                        f"{dsp.MAX_CONV_INPUT_SIZE} → "
                        f"{len(y_full)} amostras Q15.16)"
                    ),
                    dtype_out=self.dtype_var.get(),
                )
                self.after(0, lambda: self._on_conv_done(result))
            except Exception as e:
                self.after(0, lambda err=e: self._on_conv_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_conv_done(self, result: dsp.Signal):
        self.y_signal = result
        self._redraw()
        self.btn_conv.config(state="normal")
        self.status.set(f"OK. {result.description}")

    def _on_conv_error(self, err: Exception):
        self.btn_conv.config(state="normal")
        messagebox.showerror("Erro na convolução", str(err))
        self.status.set("Erro — ver mensagem.")

    # ------------------------------------------------------------------
    # Save all (em UM único arquivo .mrph com 3 seções: x, h, y)

    def _on_save_all(self):
        if self.x_sig is None or self.h_sig is None:
            messagebox.showwarning(
                "Atenção", "Gere x[n] e h[n] antes de salvar.")
            return
        if self.y_signal is None:
            if not messagebox.askyesno(
                "y[n] não calculado",
                "y[n] ainda não foi calculado. Salvar somente x[n] e h[n]?",
            ):
                return

        try:
            path = filedialog.asksaveasfilename(
                title="Salvar todos os sinais em um único arquivo .mrph",
                defaultextension=".mrph",
                initialfile="conv_bundle.mrph",
                filetypes=[("Morphe", "*.mrph"), ("Todos", "*.*")],
            )
            if not path:
                return

            dtype_out = self.dtype_var.get()
            sections = [
                {
                    "name": "x", "kind": "real",
                    "n":    self.x_sig.n, "data": self.x_sig.x,
                    "description": f"x[n] - {self.x_sig.description}",
                    "fs":   self.x_sig.fs, "dtype_out": dtype_out,
                },
                {
                    "name": "h", "kind": "real",
                    "n":    self.h_sig.n, "data": self.h_sig.x,
                    "description": f"h[n] - {self.h_sig.description}",
                    "fs":   self.h_sig.fs, "dtype_out": dtype_out,
                },
            ]
            if self.y_signal is not None:
                sections.append({
                    "name": "y", "kind": "real",
                    "n":    self.y_signal.n, "data": self.y_signal.x,
                    "description": f"y[n] = x*h - {self.y_signal.description}",
                    "fs":   self.y_signal.fs, "dtype_out": dtype_out,
                })

            dsp.save_mrph_bundle(
                path, title="Morphe convolucao", sections=sections)
            messagebox.showinfo(
                "OK",
                f"Bundle salvo em:\n{path}\n\n"
                f"Seções: {', '.join(s['name'] for s in sections)}",
            )
            self.status.set(
                f"Bundle salvo ({len(sections)} seções): "
                f"{os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e))
