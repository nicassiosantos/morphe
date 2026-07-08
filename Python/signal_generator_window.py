"""signal_generator_window.py — janela do gerador original (Toplevel).

Refatorado para consumir o design system de `morphe_theme`.
"""
from __future__ import annotations

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
from plot_toolbar import PlotToolbar


# Mensagem do estado vazio (antes de qualquer sinal ser gerado).
_EMPTY_PROMPT = ("Configure os parâmetros ao lado e clique em Gerar\n"
                 "para visualizar o sinal")


class SignalGeneratorWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Morphe — Gerador de Sinais")
        self.geometry("1100x720")
        self.configure(bg=theme.COLORS["bg"])

        theme.setup_styles(self)

        self.current: Optional[dsp.Signal] = None

        # Barra de status no rodapé (packed antes do resto para fixar embaixo)
        self.status = tk.StringVar(value="Pronto.")
        theme.make_status_bar(self, self.status).pack(side="bottom", fill="x")

        root = ttk.Frame(self, style="Main.TFrame", padding=12)
        root.pack(fill="both", expand=True)

        left = ttk.Frame(root, style="Main.TFrame")
        left.pack(side="left", fill="y", padx=(0, 12))
        right = ttk.Frame(root, style="Main.TFrame")
        right.pack(side="right", fill="both", expand=True)

        # ── Painel de geração ──
        self.gen_panel = SignalPanel(left, title="Gerar sinal",
                                     on_generate=self._on_generate,
                                     default_N=64,
                                     default_type="Degrau unitário")
        self.gen_panel.pack(fill="x", pady=(0, 12))

        # ── Operações no tempo ──
        ops = ttk.LabelFrame(
            left, text=" Operações no tempo ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        ops.pack(fill="x", pady=(0, 12))
        ops.columnconfigure(0, minsize=110)
        ops.columnconfigure(1, weight=1)

        ttk.Label(ops, text="Deslocamento k", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6))
        self.var_shift = tk.StringVar(value="0")
        ttk.Entry(ops, textvariable=self.var_shift).grid(
            row=0, column=1, sticky="ew", pady=(0, 6))

        ttk.Button(
            ops, text="Aplicar deslocamento",
            style="Secondary.TButton",
            command=self._on_shift,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 4))

        ttk.Button(
            ops, text="Inverter no tempo  (x[−n])",
            style="Secondary.TButton",
            command=self._on_reverse,
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(
            ops,
            text="k pode ser negativo (adianta o sinal). y[n] = x[n − k].",
            style="SectionHint.TLabel",
            wraplength=320,
        ).grid(row=3, column=0, columnspan=2, sticky="w")

        # ── Exportação ──
        out = ttk.LabelFrame(
            left, text=" Exportação (.mrph) ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        out.pack(fill="x")
        out.columnconfigure(0, minsize=110)
        out.columnconfigure(1, weight=1)

        ttk.Label(out, text="Tipo de dado", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6))
        self.dtype_var = tk.StringVar(value="float32")
        ttk.Combobox(out, textvariable=self.dtype_var,
                     values=["int32", "float32"], state="readonly").grid(
            row=0, column=1, sticky="ew", pady=(0, 6))

        # "Salvar" é a ação que completa o fluxo do gerador → Primary
        ttk.Button(
            out, text="Salvar como .mrph",
            style="Primary.TButton",
            command=self._on_save,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        # ── Plot ──
        self.fig = Figure(figsize=(6, 5), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        self.ax = self.fig.add_subplot(111)
        self._reset_plot("Sem sinal gerado")

        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Ferramentas flutuantes (home/pan/zoom/salvar) no canto superior
        # direito do gráfico — substituem a antiga toolbar cinza do rodapé.
        self.toolbar = PlotToolbar(self.canvas)

    # ------------------------------------------------------------------

    def _reset_plot(self, title: str = ""):
        # Estado vazio: sem grade/eixos/ticks, apenas o prompt suave
        # centralizado sobre a tela cinza clara.
        theme.draw_empty_axes(self.ax, _EMPTY_PROMPT)

    def _plot(self):
        self.ax.clear()
        s = self.current
        if s is not None:
            n_plot = np.asarray(s.n, dtype=float)
            ml, sl, _ = self.ax.stem(n_plot, s.x, basefmt=" ")
            ml.set_markersize(4)
            ml.set_color(dsp.COLOR_X)
            ml.set_markerfacecolor(dsp.COLOR_X)
            sl.set_color(dsp.COLOR_X)
            self.ax.set_title(s.description, fontsize=9)
            self.ax.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
            self.ax.set_xlabel("n")
            self.ax.set_ylabel("x[n]")
            theme.style_plot_axes(self.ax)
            n_min, n_max = float(n_plot.min()), float(n_plot.max())
            margin_x = max(1.0, 0.05 * (n_max - n_min))
            self.ax.set_xlim(n_min - margin_x, n_max + margin_x)
            x_min, x_max = float(np.min(s.x)), float(np.max(s.x))
            if x_min == x_max:
                x_min -= 0.5
                x_max += 0.5
            margin_y = 0.1 * (x_max - x_min)
            self.ax.set_ylim(x_min - margin_y, x_max + margin_y)
            self._attach_format_coord(n_plot, s.x)
        else:
            self._reset_plot("Sem sinal gerado")
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _attach_format_coord(self, n_arr: np.ndarray, x_arr: np.ndarray):
        n_arr = np.asarray(n_arr, dtype=float)
        x_arr = np.asarray(x_arr)

        def fmt(xc, yc):
            i = int(np.argmin(np.abs(n_arr - xc)))
            n_i = int(n_arr[i])
            try:
                v_str = f"{float(x_arr[i]):.4g}"
            except (TypeError, ValueError):
                v_str = str(x_arr[i])
            return f"n={n_i},  x[{n_i}] = {v_str}"

        self.ax.format_coord = fmt

    # ------------------------------------------------------------------

    def _on_generate(self, panel: SignalPanel):
        try:
            self.current = panel.build()
            self.current.dtype_out = self.dtype_var.get()
            self._plot()
            self.status.set(self.current.description)
        except Exception as e:
            messagebox.showerror("Erro na geração", str(e))

    def _need(self) -> bool:
        if self.current is None:
            messagebox.showwarning("Atenção", "Gere um sinal primeiro.")
            return False
        return True

    def _on_shift(self):
        if not self._need():
            return
        try:
            k = int(self.var_shift.get())
            self.current = dsp.time_shift(self.current, k)
            self._plot()
            self.status.set(f"Deslocado k={k:+d}.")
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def _on_reverse(self):
        if not self._need():
            return
        self.current = dsp.time_reverse(self.current)
        self._plot()
        self.status.set("Invertido (x[−n]).")

    def _on_save(self):
        if not self._need():
            return
        try:
            self.current.dtype_out = self.dtype_var.get()
            path = filedialog.asksaveasfilename(
                title="Salvar .mrph",
                defaultextension=".mrph",
                filetypes=[("Morphe", "*.mrph"), ("Todos", "*.*")],
            )
            if not path:
                return
            dsp.save_mrph(path, self.current)
            self.status.set(f"Salvo em {path}")
            messagebox.showinfo("OK", f"Salvo:\n{path}")
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e))
