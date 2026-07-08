"""fir_designer_window.py -- janela de projeto de filtros FIR.

Aberta como Toplevel a partir da janela principal do FIR. Permite ao
usuario projetar filtros pelos quatro tipos classicos (passa-baixa,
passa-alta, passa-banda, rejeita-banda) usando o metodo da janela,
visualizar resposta impulsiva e em frequencia em tempo real, e
aplicar diretamente na janela mae ou salvar como arquivo .txt.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Callable, Optional

import numpy as np

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import fir_design as fd
import dsp_core as dsp
import morphe_theme as theme
from plot_toolbar import PlotToolbar


# Mapeamento UI (PT) <-> internal (EN). UI usa portugues; logica usa
# os identificadores em ingles do fir_design.py.
_TYPE_UI_TO_INT = {
    "Passa-baixa":   "lowpass",
    "Passa-alta":    "highpass",
    "Passa-banda":   "bandpass",
    "Rejeita-banda": "bandstop",
}
_TYPE_INT_TO_UI = {v: k for k, v in _TYPE_UI_TO_INT.items()}

_WINDOW_UI_TO_INT = {
    "Retangular": "rectangular",
    "Hamming":    "hamming",
    "Hanning":    "hanning",
    "Blackman":   "blackman",
}
_WINDOW_INT_TO_UI = {v: k for k, v in _WINDOW_UI_TO_INT.items()}


# Cores de acao -- tk.Button (ttk ignora bg em alguns temas). Tons
# "tailwind" alinhados a paleta do tema e a janela FIR (verde aplicar /
# azul = primary salvar / roxo projetar), para harmonia entre as telas.
_BTN_APPLY_BG  = "#16a34a"   # green-600  "aplicar"
_BTN_SAVE_BG   = "#2563eb"   # blue-600 (= theme primary) "salvar"
_BTN_DESIGN_BG = "#7c3aed"   # violet-600 "projetar/recalcular"
_BTN_FG_LIGHT  = "white"


def _make_action_button(parent, text: str, bg: str,
                         command: Callable[[], None]) -> tk.Button:
    """Helper para criar tk.Button colorido em estilo consistente."""
    return tk.Button(
        parent, text=text,
        bg=bg, fg=_BTN_FG_LIGHT,
        activebackground=bg, activeforeground=_BTN_FG_LIGHT,
        bd=0, relief="flat",
        font=("TkDefaultFont", 9, "bold"),
        cursor="hand2",
        padx=8, pady=5,
        command=command,
    )


class FIRDesignerWindow(tk.Toplevel):
    """Toplevel para projetar filtros FIR.

    on_apply: callback que recebe (h_array, description_str, fs) quando
    o usuario clica em 'Aplicar a janela FIR'. A fs e propagada para
    que o sinal de entrada na janela FIR seja mantido coerente com o
    projeto do filtro (mesma taxa de amostragem). Tipicamente a janela
    mae encaminha para o CoefficientsLoader.
    """

    def __init__(self, master, on_apply: Callable[[np.ndarray, str], None]):
        super().__init__(master)
        self.title("Morphe — Projetar filtro FIR")
        self.geometry("1100x720")
        self.configure(bg=theme.COLORS["bg"])

        theme.setup_styles(self)

        self._on_apply = on_apply
        self.h: Optional[np.ndarray] = None
        self.description: str = ""
        self._dirty_after_id: Optional[str] = None

        # ---- Status bar (packed primeiro c/ side="bottom" p/ fixar embaixo)
        self.status = tk.StringVar(value="Pronto. Ajuste os parâmetros.")
        theme.make_status_bar(self, self.status).pack(side="bottom", fill="x")

        # ---- Layout ------------------------------------------------
        root = ttk.Frame(self, style="Main.TFrame", padding=8)
        root.pack(fill="both", expand=True)

        left = ttk.Frame(root, style="Main.TFrame")
        left.pack(side="left", fill="y", padx=(0, 8))
        right = ttk.Frame(root, style="Main.TFrame")
        right.pack(side="right", fill="both", expand=True)

        self._build_controls(left)
        self._build_actions(left)
        self._build_plots(right)

        # Projeto inicial automatico para nao comecar com tela vazia
        self.after(100, self._on_design)

    # ==================================================================
    # Construcao da UI
    # ==================================================================

    def _build_controls(self, parent):
        # Aviso explicativo (banner suave do tema; o ícone ⚠ substitui o "[!]")
        theme.make_banner(
            parent, kind="warn",
            text=("Projeto FIR pelo metodo da janela\n"
                  "- N (taps) deve ser IMPAR (3..127) para fase linear\n"
                  "- Cutoff deve ser < fs/2 (Nyquist)\n"
                  "- Hamming/Blackman: melhor stopband; Retangular: pior"),
            wraplength=320,
        ).pack(fill="x", pady=(0, 6))

        # Tipo de filtro
        type_box = ttk.LabelFrame(
            parent, text=" Tipo de filtro ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        type_box.pack(fill="x", pady=4)

        self.var_type = tk.StringVar(value="Passa-baixa")
        cb = ttk.Combobox(type_box, textvariable=self.var_type,
                          values=list(_TYPE_UI_TO_INT.keys()),
                          state="readonly", width=20)
        cb.pack(fill="x")
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_type_change())

        # Parametros gerais
        params = ttk.LabelFrame(
            parent, text=" Parametros ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        params.pack(fill="x", pady=4)

        # N (taps)
        ttk.Label(params, text="N (taps, IMPAR 3..127):",
                  style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.var_N = tk.StringVar(value="63")
        e = ttk.Entry(params, textvariable=self.var_N, width=8)
        e.grid(row=0, column=1, sticky="w", padx=4)
        e.bind("<KeyRelease>", lambda ev: self._schedule_redesign())

        # Taxa de amostragem
        ttk.Label(params, text="fs (Hz):", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 0))
        self.var_fs = tk.StringVar(value="200.0")
        e = ttk.Entry(params, textvariable=self.var_fs, width=12)
        e.grid(row=1, column=1, sticky="w", padx=4, pady=(4, 0))
        e.bind("<KeyRelease>", lambda ev: self._schedule_redesign())

        # Frequencia de corte 1
        self._lbl_fc1 = ttk.Label(params, text="fc (Hz):", style="Card.TLabel")
        self._lbl_fc1.grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.var_fc1 = tk.StringVar(value="50.0")
        e = ttk.Entry(params, textvariable=self.var_fc1, width=12)
        e.grid(row=2, column=1, sticky="w", padx=4, pady=(4, 0))
        e.bind("<KeyRelease>", lambda ev: self._schedule_redesign())

        # Frequencia de corte 2 (so para BP/BS)
        self._lbl_fc2 = ttk.Label(params, text="fc2 (Hz):", style="Card.TLabel")
        self.var_fc2 = tk.StringVar(value="80.0")
        self._entry_fc2 = ttk.Entry(params, textvariable=self.var_fc2, width=12)
        self._entry_fc2.bind("<KeyRelease>", lambda ev: self._schedule_redesign())
        # Posicionados/escondidos por _on_type_change

        # Tipo de janela
        ttk.Label(params, text="Janela:", style="Card.TLabel").grid(
            row=4, column=0, sticky="w", pady=(4, 0))
        self.var_window = tk.StringVar(value="Hamming")
        cb = ttk.Combobox(params, textvariable=self.var_window,
                          values=list(_WINDOW_UI_TO_INT.keys()),
                          state="readonly", width=12)
        cb.grid(row=4, column=1, sticky="w", padx=4, pady=(4, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self._schedule_redesign())

        # Inicializa visibilidade dos campos
        self._on_type_change()

    def _build_actions(self, parent):
        actions = ttk.LabelFrame(
            parent, text=" Acoes ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        actions.pack(fill="x", pady=4)

        _make_action_button(actions, "Recalcular projeto",
                             _BTN_DESIGN_BG, self._on_design).pack(
            fill="x", pady=2)

        self.btn_apply = _make_action_button(
            actions, "Aplicar a janela FIR",
            _BTN_APPLY_BG, self._on_apply_click)
        self.btn_apply.pack(fill="x", pady=2)
        self.btn_apply.configure(state="disabled")

        self.btn_save = _make_action_button(
            actions, "Salvar coeficientes (.txt)",
            _BTN_SAVE_BG, self._on_save_click)
        self.btn_save.pack(fill="x", pady=2)
        self.btn_save.configure(state="disabled")

        # Resumo do projeto atual
        summary = ttk.LabelFrame(
            parent, text=" Resumo ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        summary.pack(fill="x", pady=4)
        self.var_summary = tk.StringVar(value="(nenhum filtro projetado)")
        ttk.Label(summary, textvariable=self.var_summary,
                  style="Card.TLabel",
                  wraplength=320, justify="left",
                  font=("TkDefaultFont", 9)).pack(fill="x")

    def _build_plots(self, parent):
        self.fig = Figure(figsize=(7, 6), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        self.ax_h = self.fig.add_subplot(211)
        self.ax_H = self.fig.add_subplot(212)
        theme.draw_empty_axes(
            self.ax_h,
            "Resposta impulsiva h[n]\n(defina os parâmetros do filtro)")
        theme.draw_empty_axes(self.ax_H, "Resposta em frequência |H(f)|")

        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Ferramentas flutuantes (home/pan/zoom/salvar) no canto superior
        # direito — substituem a antiga toolbar cinza do rodapé.
        self.toolbar = PlotToolbar(self.canvas)

    # ==================================================================
    # Eventos
    # ==================================================================

    def _on_type_change(self):
        """Mostra/esconde fc2 conforme o tipo escolhido."""
        kind_int = _TYPE_UI_TO_INT[self.var_type.get()]
        is_band = kind_int in ("bandpass", "bandstop")
        if is_band:
            self._lbl_fc1.configure(text="fc1 (Hz):")
            self._lbl_fc2.grid(row=3, column=0, sticky="w", pady=(4, 0))
            self._entry_fc2.grid(row=3, column=1, sticky="w",
                                  padx=4, pady=(4, 0))
        else:
            self._lbl_fc1.configure(text="fc (Hz):")
            self._lbl_fc2.grid_forget()
            self._entry_fc2.grid_forget()
        self._schedule_redesign()

    def _schedule_redesign(self):
        """Debounce para reprojetar 200ms apos a ultima edicao."""
        if self._dirty_after_id is not None:
            try:
                self.after_cancel(self._dirty_after_id)
            except tk.TclError:
                pass
        self._dirty_after_id = self.after(200, self._on_design)

    def _on_design(self):
        self._dirty_after_id = None
        try:
            kind = _TYPE_UI_TO_INT[self.var_type.get()]
            window = _WINDOW_UI_TO_INT[self.var_window.get()]
            N = int(self.var_N.get())
            fs = float(self.var_fs.get())
            fc1 = float(self.var_fc1.get())
            fc2 = None
            if kind in ("bandpass", "bandstop"):
                fc2 = float(self.var_fc2.get())
            self.h = fd.design_filter(kind, N, fs, fc1, fc2, window)
            self.description = fd.describe_filter(kind, N, fs, fc1, fc2, window)
        except (ValueError, KeyError) as e:
            self.status.set(f"[!] {e}")
            self.var_summary.set("(parametros invalidos)")
            self.btn_apply.configure(state="disabled")
            self.btn_save.configure(state="disabled")
            return

        self.status.set(f"Projeto OK: {self.description}")
        self.var_summary.set(
            f"{self.description}\n\n"
            f"N taps:    {len(self.h)}\n"
            f"max |h|:   {float(np.max(np.abs(self.h))):.4g}\n"
            f"sum h:     {float(np.sum(self.h)):.4g}"
        )
        self.btn_apply.configure(state="normal")
        self.btn_save.configure(state="normal")
        self._redraw()

    def _redraw(self):
        if self.h is None:
            return

        # ---- h[n] ----
        self.ax_h.clear()
        n = np.arange(len(self.h))
        ml, sl, _ = self.ax_h.stem(n, self.h, basefmt=" ")
        ml.set_markersize(3); ml.set_color(dsp.COLOR_H)
        ml.set_markerfacecolor(dsp.COLOR_H); sl.set_color(dsp.COLOR_H)
        self.ax_h.set_title(f"Resposta impulsiva h[n]  (N={len(self.h)})",
                             fontsize=10)
        self.ax_h.set_xlabel("n"); self.ax_h.set_ylabel("h[n]")
        self.ax_h.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
        theme.style_plot_axes(self.ax_h)

        # ---- |H(f)| em dB ----
        self.ax_H.clear()
        try:
            fs = float(self.var_fs.get())
        except ValueError:
            fs = 1.0
        f, H = fd.frequency_response(self.h, fs=fs, n_freq=2048)
        mag_db = 20.0 * np.log10(np.abs(H) + 1e-12)
        self.ax_H.plot(f, mag_db, color=dsp.COLOR_H, linewidth=1.0)
        self.ax_H.axhline(-3, color="grey", linewidth=0.5,
                          linestyle="--", alpha=0.5)
        self.ax_H.axhline(-6, color="grey", linewidth=0.5,
                          linestyle=":",  alpha=0.5)

        # Marca cutoffs com linhas verticais leves
        try:
            fc1 = float(self.var_fc1.get())
            self.ax_H.axvline(fc1, color="#dc3545", linewidth=0.6,
                              linestyle="--", alpha=0.7,
                              label=f"fc={fc1:g} Hz")
            kind = _TYPE_UI_TO_INT.get(self.var_type.get())
            if kind in ("bandpass", "bandstop"):
                fc2 = float(self.var_fc2.get())
                self.ax_H.axvline(fc2, color="#dc3545", linewidth=0.6,
                                   linestyle="--", alpha=0.7,
                                   label=f"fc2={fc2:g} Hz")
            self.ax_H.legend(fontsize=8, loc="best")
        except (ValueError, KeyError):
            pass

        self.ax_H.set_title("Resposta em frequencia |H(f)| (dB)",
                             fontsize=10)
        self.ax_H.set_xlabel("f (Hz)"); self.ax_H.set_ylabel("|H(f)| (dB)")
        self.ax_H.set_ylim(-100, 5)
        theme.style_plot_axes(self.ax_H)

        self.fig.tight_layout()
        self.canvas.draw_idle()

    # ==================================================================
    # Acoes
    # ==================================================================

    def _on_apply_click(self):
        if self.h is None:
            return
        # Verifica saturacao Q15.16 (mesma checagem do loader)
        warn = dsp.q1516_range_warning(self.h)
        if warn:
            ok = messagebox.askokcancel(
                "Atencao - faixa Q15.16",
                f"{warn}\n\nDeseja aplicar mesmo assim?")
            if not ok:
                return
        # Le a fs do projeto para propagar ao sinal de entrada na janela
        # FIR (requisito: filtro e sinal devem usar a mesma fs).
        try:
            fs = float(self.var_fs.get())
        except ValueError:
            messagebox.showerror(
                "Erro ao aplicar",
                "Valor invalido em fs; recalcule o projeto.")
            return
        try:
            self._on_apply(self.h.copy(), self.description, fs)
        except Exception as e:
            messagebox.showerror("Erro ao aplicar", str(e))
            return
        self.status.set("Filtro aplicado a janela FIR.")

    def _on_save_click(self):
        if self.h is None:
            return
        # Sugere nome de arquivo baseado no tipo
        kind_int = _TYPE_UI_TO_INT.get(self.var_type.get(), "filter")
        default_name = f"fir_{kind_int}.txt"
        path = filedialog.asksaveasfilename(
            title="Salvar coeficientes do filtro FIR",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("Texto", "*.txt"), ("Coeficientes", "*.coef"),
                       ("Todos", "*.*")],
        )
        if not path:
            return
        try:
            fd.save_coefficients_txt(path, self.h, self.description)
        except OSError as e:
            messagebox.showerror("Erro ao salvar", str(e))
            return
        self.status.set(f"Coeficientes salvos: {os.path.basename(path)}")
        messagebox.showinfo("OK", f"Salvo em:\n{path}")
