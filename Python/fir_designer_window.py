"""fir_designer_window.py -- janela de projeto de filtros FIR.

Aberta como Toplevel a partir da janela principal do FIR. Tem dois modos:

  Por especificacao (padrao)
      Voce declara o que o filtro precisa fazer -- borda da banda passante,
      largura de transicao, ripple e atenuacao -- e o programa escolhe a
      janela e calcula quantos taps sao necessarios. E o metodo do
      dsp_fir_filter.m do Prof. Armando S. Sanca, portado em fir_design.py.

  Avancado
      Voce escolhe N e a janela na mao, como na versao anterior desta tela.

O modo por especificacao mostra tambem o que o filtro entrega DEPOIS da
quantizacao Q15.16 da FPGA, que costuma ser diferente do que a tabela de
janelas promete.
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

_MODE_SPEC = "spec"
_MODE_ADV = "avancado"

#: Acima disto o grafico de h[n] vira linha em vez de stem -- com 1023
#: taps o stem fica ilegivel e lento.
_STEM_LIMIT = 128


# Cores de acao -- tk.Button (ttk ignora bg em alguns temas). Tons
# "tailwind" alinhados a paleta do tema e a janela FIR (verde aplicar /
# azul = primary salvar / roxo projetar), para harmonia entre as telas.
_BTN_APPLY_BG  = "#16a34a"   # green-600  "aplicar"
_BTN_SAVE_BG   = "#2563eb"   # blue-600 (= theme primary) "salvar"
_BTN_DESIGN_BG = "#7c3aed"   # violet-600 "projetar/recalcular"
_BTN_FG_LIGHT  = "white"

_COLOR_IDEAL = "tab:blue"
_COLOR_WIN   = "tab:purple"
_COLOR_QUANT = "tab:red"


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
        self.geometry("1180x760")
        self.configure(bg=theme.COLORS["bg"])

        theme.setup_styles(self)

        self._on_apply = on_apply
        self.h: Optional[np.ndarray] = None
        self.report: Optional[dict] = None
        self.measured: Optional[dict] = None
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

        self._on_mode_change()

        # Projeto inicial automatico para nao comecar com tela vazia
        self.after(100, self._on_design)

    # ==================================================================
    # Construcao da UI
    # ==================================================================

    def _build_controls(self, parent):
        self._banner = theme.make_banner(
            parent, kind="warn", text="", wraplength=330)
        self._banner.pack(fill="x", pady=(0, 6))
        # make_banner devolve um Frame com dois Labels: o icone e, depois,
        # o texto. Guardamos o SEGUNDO para poder trocar o texto quando o
        # modo muda -- pegar o primeiro sobrescreveria o icone.
        labels = [c for c in self._banner.winfo_children()
                  if isinstance(c, (tk.Label, ttk.Label))]
        self._banner_label = labels[-1] if labels else None

        # ---- Modo de projeto
        mode_box = ttk.LabelFrame(
            parent, text=" Modo de projeto ",
            style="Card.TLabelframe", padding=(14, 10, 14, 12))
        mode_box.pack(fill="x", pady=4)

        self.var_mode = tk.StringVar(value=_MODE_SPEC)
        ttk.Radiobutton(
            mode_box, text="Por especificação (o programa escolhe N e janela)",
            variable=self.var_mode, value=_MODE_SPEC,
            command=self._on_mode_change).pack(anchor="w")
        ttk.Radiobutton(
            mode_box, text="Avançado (eu escolho N e a janela)",
            variable=self.var_mode, value=_MODE_ADV,
            command=self._on_mode_change).pack(anchor="w")

        # ---- Tipo de filtro
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

        # ---- Taxa de amostragem (comum aos dois modos)
        common = ttk.LabelFrame(
            parent, text=" Amostragem ",
            style="Card.TLabelframe", padding=(14, 10, 14, 12))
        common.pack(fill="x", pady=4)
        ttk.Label(common, text="fs (Hz):", style="Card.TLabel").grid(
            row=0, column=0, sticky="w")
        self.var_fs = tk.StringVar(value="200.0")
        e = ttk.Entry(common, textvariable=self.var_fs, width=12)
        e.grid(row=0, column=1, sticky="w", padx=4)
        e.bind("<KeyRelease>", lambda ev: self._schedule_redesign())

        self._build_spec_frame(parent)
        self._build_adv_frame(parent)

    def _build_spec_frame(self, parent):
        """Campos do modo por especificacao."""
        self.frm_spec = ttk.LabelFrame(
            parent, text=" Especificação do filtro ",
            style="Card.TLabelframe", padding=(14, 12, 14, 14))

        f = self.frm_spec
        self._lbl_fp1 = ttk.Label(f, text="fp (Hz):", style="Card.TLabel")
        self._lbl_fp1.grid(row=0, column=0, sticky="w")
        self.var_fp1 = tk.StringVar(value="50.0")
        e = ttk.Entry(f, textvariable=self.var_fp1, width=12)
        e.grid(row=0, column=1, sticky="w", padx=4)
        e.bind("<KeyRelease>", lambda ev: self._schedule_redesign())

        self._lbl_fp2 = ttk.Label(f, text="fp2 (Hz):", style="Card.TLabel")
        self.var_fp2 = tk.StringVar(value="80.0")
        self._entry_fp2 = ttk.Entry(f, textvariable=self.var_fp2, width=12)
        self._entry_fp2.bind("<KeyRelease>",
                             lambda ev: self._schedule_redesign())

        ttk.Label(f, text="Δf transição (Hz):", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", pady=(4, 0))
        self.var_df = tk.StringVar(value="10.0")
        e = ttk.Entry(f, textvariable=self.var_df, width=12)
        e.grid(row=2, column=1, sticky="w", padx=4, pady=(4, 0))
        e.bind("<KeyRelease>", lambda ev: self._schedule_redesign())

        ttk.Label(f, text="δp ripple (dB):", style="Card.TLabel").grid(
            row=3, column=0, sticky="w", pady=(4, 0))
        self.var_dp = tk.StringVar(value="0.1")
        e = ttk.Entry(f, textvariable=self.var_dp, width=12)
        e.grid(row=3, column=1, sticky="w", padx=4, pady=(4, 0))
        e.bind("<KeyRelease>", lambda ev: self._schedule_redesign())

        ttk.Label(f, text="δs atenuação (dB):", style="Card.TLabel").grid(
            row=4, column=0, sticky="w", pady=(4, 0))
        self.var_ds = tk.StringVar(value="50.0")
        e = ttk.Entry(f, textvariable=self.var_ds, width=12)
        e.grid(row=4, column=1, sticky="w", padx=4, pady=(4, 0))
        e.bind("<KeyRelease>", lambda ev: self._schedule_redesign())

    def _build_adv_frame(self, parent):
        """Campos do modo avancado -- os mesmos da versao anterior."""
        self.frm_adv = ttk.LabelFrame(
            parent, text=" Parâmetros ",
            style="Card.TLabelframe", padding=(14, 12, 14, 14))

        f = self.frm_adv
        ttk.Label(f, text="N (taps, ÍMPAR 3..%d):" % fd.MAX_TAPS,
                  style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.var_N = tk.StringVar(value="63")
        e = ttk.Entry(f, textvariable=self.var_N, width=8)
        e.grid(row=0, column=1, sticky="w", padx=4)
        e.bind("<KeyRelease>", lambda ev: self._schedule_redesign())

        self._lbl_fc1 = ttk.Label(f, text="fc (Hz):", style="Card.TLabel")
        self._lbl_fc1.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.var_fc1 = tk.StringVar(value="50.0")
        e = ttk.Entry(f, textvariable=self.var_fc1, width=12)
        e.grid(row=1, column=1, sticky="w", padx=4, pady=(4, 0))
        e.bind("<KeyRelease>", lambda ev: self._schedule_redesign())

        self._lbl_fc2 = ttk.Label(f, text="fc2 (Hz):", style="Card.TLabel")
        self.var_fc2 = tk.StringVar(value="80.0")
        self._entry_fc2 = ttk.Entry(f, textvariable=self.var_fc2, width=12)
        self._entry_fc2.bind("<KeyRelease>",
                             lambda ev: self._schedule_redesign())

        ttk.Label(f, text="Janela:", style="Card.TLabel").grid(
            row=3, column=0, sticky="w", pady=(4, 0))
        self.var_window = tk.StringVar(value="Hamming")
        cb = ttk.Combobox(f, textvariable=self.var_window,
                          values=list(_WINDOW_UI_TO_INT.keys()),
                          state="readonly", width=12)
        cb.grid(row=3, column=1, sticky="w", padx=4, pady=(4, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self._schedule_redesign())

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
        summary.pack(fill="both", expand=True, pady=4)
        self.var_summary = tk.StringVar(value="(nenhum filtro projetado)")
        ttk.Label(summary, textvariable=self.var_summary,
                  style="Card.TLabel",
                  wraplength=330, justify="left",
                  font=("TkDefaultFont", 9)).pack(fill="x", anchor="w")

    def _build_plots(self, parent):
        self.fig = Figure(figsize=(7.6, 6.4), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Ferramentas flutuantes (home/pan/zoom/salvar) no canto superior
        # direito — substituem a antiga toolbar cinza do rodapé.
        self.toolbar = PlotToolbar(self.canvas)
        self._layout_axes()

    def _layout_axes(self):
        """(Re)cria os eixos conforme o modo.

        No modo por especificacao a figura espelha a do MATLAB original:
        janela, filtro ideal e filtro real lado a lado, e a resposta em
        frequencia ocupando a largura inteira embaixo.
        """
        self.fig.clear()
        if self.var_mode.get() == _MODE_SPEC:
            self.ax_w  = self.fig.add_subplot(2, 3, 1)
            self.ax_hd = self.fig.add_subplot(2, 3, 2)
            self.ax_h  = self.fig.add_subplot(2, 3, 3)
            self.ax_H  = self.fig.add_subplot(2, 1, 2)
            theme.draw_empty_axes(self.ax_w,  "Janela w(n)")
            theme.draw_empty_axes(self.ax_hd, "Filtro ideal h_D(n)")
            theme.draw_empty_axes(self.ax_h,  "Filtro real h(n)")
        else:
            self.ax_w = None
            self.ax_hd = None
            self.ax_h = self.fig.add_subplot(2, 1, 1)
            self.ax_H = self.fig.add_subplot(2, 1, 2)
            theme.draw_empty_axes(
                self.ax_h,
                "Resposta impulsiva h[n]\n(defina os parâmetros do filtro)")
        theme.draw_empty_axes(self.ax_H, "Resposta em frequência |H(f)|")
        self.fig.tight_layout()
        self.canvas.draw_idle()

    # ==================================================================
    # Eventos
    # ==================================================================

    def _set_banner(self, text: str):
        if self._banner_label is not None:
            try:
                self._banner_label.configure(text=text)
            except tk.TclError:
                pass

    def _on_mode_change(self):
        spec = self.var_mode.get() == _MODE_SPEC
        if spec:
            self.frm_adv.pack_forget()
            self.frm_spec.pack(fill="x", pady=4, before=None)
            self._set_banner(
                "Projeto por especificação (método da janela)\n"
                "• Você declara o desempenho; o programa escolhe a janela\n"
                "  e calcula N — método do Prof. Armando S. Sanca\n"
                "• δs máximo do método: 90 dB (janela de Kaiser)\n"
                "• N nunca passa de %d taps: acima disso a especificação\n"
                "  é recusada, com o Δf mínimo viável" % fd.MAX_TAPS)
        else:
            self.frm_spec.pack_forget()
            self.frm_adv.pack(fill="x", pady=4)
            self._set_banner(
                "Projeto FIR pelo método da janela\n"
                "• N (taps) deve ser ÍMPAR (3..%d) para fase linear\n"
                "• Cutoff deve ser < fs/2 (Nyquist)\n"
                "• Hamming/Blackman: melhor stopband; Retangular: pior"
                % fd.MAX_TAPS)
        self._on_type_change()
        self._layout_axes()

    def _on_type_change(self):
        """Mostra/esconde o segundo campo de frequência conforme o tipo."""
        kind_int = _TYPE_UI_TO_INT[self.var_type.get()]
        is_band = kind_int in ("bandpass", "bandstop")

        # --- modo especificacao
        if is_band:
            if kind_int == "bandpass":
                self._lbl_fp1.configure(text="fp1 passante (Hz):")
                self._lbl_fp2.configure(text="fp2 passante (Hz):")
            else:
                self._lbl_fp1.configure(text="fp1 borda inf. (Hz):")
                self._lbl_fp2.configure(text="fp2 borda sup. (Hz):")
            self._lbl_fp2.grid(row=1, column=0, sticky="w", pady=(4, 0))
            self._entry_fp2.grid(row=1, column=1, sticky="w",
                                 padx=4, pady=(4, 0))
        else:
            self._lbl_fp1.configure(text="fp (Hz):")
            self._lbl_fp2.grid_forget()
            self._entry_fp2.grid_forget()

        # --- modo avancado
        if is_band:
            self._lbl_fc1.configure(text="fc1 (Hz):")
            self._lbl_fc2.grid(row=2, column=0, sticky="w", pady=(4, 0))
            self._entry_fc2.grid(row=2, column=1, sticky="w",
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

    def _fail(self, msg: str, summary: str = None):
        self.status.set("[!] " + msg.splitlines()[0])
        self.var_summary.set(summary if summary is not None else msg)
        self.btn_apply.configure(state="disabled")
        self.btn_save.configure(state="disabled")
        self.h = None
        self.report = None
        self.measured = None

    def _on_design(self):
        self._dirty_after_id = None
        if self.var_mode.get() == _MODE_SPEC:
            self._design_spec()
        else:
            self._design_adv()

    # ---- modo por especificacao --------------------------------------

    def _design_spec(self):
        kind = _TYPE_UI_TO_INT[self.var_type.get()]
        try:
            fs = float(self.var_fs.get())
            df = float(self.var_df.get())
            dp = float(self.var_dp.get())
            ds = float(self.var_ds.get())
            if kind in ("bandpass", "bandstop"):
                fp = (float(self.var_fp1.get()), float(self.var_fp2.get()))
            else:
                fp = float(self.var_fp1.get())
        except ValueError:
            self._fail("Valor numérico inválido em algum campo.")
            return

        try:
            h, report = fd.design_from_spec(kind, fp, df, dp, ds, fs)
        except fd.SpecError as e:
            self._fail(str(e))
            return

        measured = fd.achieved_specs(h, report)
        measured_float = fd.achieved_specs(h, report, quantize=False)

        self.h = h
        self.report = report
        self.measured = measured
        self.description = fd.describe_from_spec(report)

        beta_txt = ("" if report["beta"] is None
                    else "  (β = %.4f)" % report["beta"])
        if report["fc2_efetiva"] is None:
            fc_txt = "fc efetiva:   %.4g Hz" % report["fc1_efetiva"]
        else:
            fc_txt = ("fc efetivas:  %.4g e %.4g Hz"
                      % (report["fc1_efetiva"], report["fc2_efetiva"]))

        self.status.set("Projeto OK: " + self.description)
        self.var_summary.set(
            "Janela escolhida: %s%s\n"
            "N taps:       %d   (fórmula deu N=%d)\n"
            "%s\n"
            "\n"
            "         pedido    float    Q15.16\n"
            "δs (dB)  %-8.4g  %-7.1f  %-7.1f\n"
            "δp (dB)  %-8.4g  %-7.4f  %-7.4f\n"
            "\n"
            "max |h|:  %.6g\n"
            "sum h:    %.6g"
            % (report["window_pt"], beta_txt,
               report["taps"], report["N_formula"],
               fc_txt,
               report["ds_db"], measured_float["atten_db"],
               measured["atten_db"],
               report["dp_db"], measured_float["ripple_db"],
               measured["ripple_db"],
               float(np.max(np.abs(h))), float(np.sum(h)))
        )
        self.btn_apply.configure(state="normal")
        self.btn_save.configure(state="normal")
        self._redraw_spec()

    # ---- modo avancado -----------------------------------------------

    def _design_adv(self):
        try:
            kind = _TYPE_UI_TO_INT[self.var_type.get()]
            window = _WINDOW_UI_TO_INT[self.var_window.get()]
            N = int(self.var_N.get())
            if N > fd.MAX_TAPS:
                raise ValueError(
                    "N=%d acima do limite do hardware (%d taps)"
                    % (N, fd.MAX_TAPS))
            fs = float(self.var_fs.get())
            fc1 = float(self.var_fc1.get())
            fc2 = None
            if kind in ("bandpass", "bandstop"):
                fc2 = float(self.var_fc2.get())
            self.h = fd.design_filter(kind, N, fs, fc1, fc2, window)
            self.description = fd.describe_filter(kind, N, fs, fc1, fc2,
                                                   window)
        except (ValueError, KeyError) as e:
            self._fail(str(e), "Não foi possível projetar: " + str(e))
            return

        self.report = None
        self.measured = None
        self.status.set("Projeto OK: " + self.description)
        self.var_summary.set(
            "%s\n\n"
            "N taps:    %d\n"
            "max |h|:   %.4g\n"
            "sum h:     %.4g"
            % (self.description, len(self.h),
               float(np.max(np.abs(self.h))), float(np.sum(self.h)))
        )
        self.btn_apply.configure(state="normal")
        self.btn_save.configure(state="normal")
        self._redraw_adv()

    # ==================================================================
    # Desenho
    # ==================================================================

    def _plot_taps(self, ax, y, color, title, ylabel):
        """Desenha coeficientes: stem para N pequeno, linha para N grande."""
        ax.clear()
        n = np.arange(len(y))
        if len(y) <= _STEM_LIMIT:
            ml, sl, _ = ax.stem(n, y, basefmt=" ")
            ml.set_markersize(3)
            ml.set_color(color)
            ml.set_markerfacecolor(color)
            sl.set_color(color)
        else:
            ax.plot(n, y, color=color, linewidth=0.9)
        ax.set_title(title, fontsize=9)
        ax.set_xlabel("n", fontsize=8)
        ax.set_ylabel(ylabel, fontsize=8)
        ax.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
        ax.tick_params(labelsize=7)
        theme.style_plot_axes(ax)

    def _redraw_spec(self):
        if self.h is None or self.report is None:
            return
        r = self.report
        m = self.measured

        self._plot_taps(self.ax_w, r["window_full"], _COLOR_WIN,
                        "Janela w(n) — %s" % r["window_pt"], "w(n)")
        self._plot_taps(self.ax_hd, r["h_ideal"], _COLOR_IDEAL,
                        "Filtro ideal h$_D$(n)", "h$_D$(n)")
        self._plot_taps(self.ax_h, self.h, dsp.COLOR_H,
                        "Filtro real h(n) = h$_D$·w   (N=%d)" % r["taps"],
                        "h(n)")

        # ---- |H(f)| em dB: float x quantizado, com a especificacao
        ax = self.ax_H
        ax.clear()
        f_lin, H_lin = fd.frequency_response(self.h, fs=r["fs"], n_freq=4096)
        db_float = 20.0 * np.log10(np.abs(H_lin) + 1e-18)
        ax.plot(f_lin, db_float, color=dsp.COLOR_H, linewidth=1.0,
                label="coeficientes float")
        ax.plot(m["f"], m["db"], color=_COLOR_QUANT, linewidth=0.9,
                alpha=0.85, linestyle="--", label="após Q15.16 (FPGA)")

        # atenuacao pedida
        ax.axhline(-r["ds_db"], color="grey", linewidth=0.7, linestyle=":",
                   label="δs pedido = %g dB" % r["ds_db"])

        # bandas de transicao sombreadas
        for lo, hi in self._transition_bands(r):
            ax.axvspan(lo, hi, color="grey", alpha=0.12)

        ax.set_title("Resposta em frequência |H(f)| (dB)", fontsize=10)
        ax.set_xlabel("f (Hz)")
        ax.set_ylabel("|H(f)| (dB)")
        ax.set_xlim(0, r["fs"] / 2.0)
        ax.set_ylim(max(-120, -(r["ds_db"] + 45)), 5)
        ax.legend(fontsize=7, loc="upper right")
        theme.style_plot_axes(ax)

        self.fig.tight_layout()
        self.canvas.draw_idle()

    @staticmethod
    def _transition_bands(r: dict):
        """Faixas [inicio, fim] das bandas de transicao, para sombrear."""
        kind, f1, f2, df = r["kind"], r["fp1"], r["fp2"], r["df"]
        if kind == "lowpass":
            return [(f1, f1 + df)]
        if kind == "highpass":
            return [(f1 - df, f1)]
        if kind == "bandpass":
            return [(f1 - df, f1), (f2, f2 + df)]
        return [(f1, f1 + df), (f2 - df, f2)]   # bandstop

    def _redraw_adv(self):
        if self.h is None:
            return

        self._plot_taps(self.ax_h, self.h, dsp.COLOR_H,
                        "Resposta impulsiva h[n]  (N=%d)" % len(self.h),
                        "h[n]")

        ax = self.ax_H
        ax.clear()
        try:
            fs = float(self.var_fs.get())
        except ValueError:
            fs = 1.0
        f, H = fd.frequency_response(self.h, fs=fs, n_freq=2048)
        mag_db = 20.0 * np.log10(np.abs(H) + 1e-12)
        ax.plot(f, mag_db, color=dsp.COLOR_H, linewidth=1.0)
        ax.axhline(-3, color="grey", linewidth=0.5,
                   linestyle="--", alpha=0.5)
        ax.axhline(-6, color="grey", linewidth=0.5,
                   linestyle=":",  alpha=0.5)

        # Marca cutoffs com linhas verticais leves
        try:
            fc1 = float(self.var_fc1.get())
            ax.axvline(fc1, color="#dc3545", linewidth=0.6,
                       linestyle="--", alpha=0.7, label="fc=%g Hz" % fc1)
            kind = _TYPE_UI_TO_INT.get(self.var_type.get())
            if kind in ("bandpass", "bandstop"):
                fc2 = float(self.var_fc2.get())
                ax.axvline(fc2, color="#dc3545", linewidth=0.6,
                           linestyle="--", alpha=0.7, label="fc2=%g Hz" % fc2)
            ax.legend(fontsize=8, loc="best")
        except (ValueError, KeyError):
            pass

        ax.set_title("Resposta em frequencia |H(f)| (dB)", fontsize=10)
        ax.set_xlabel("f (Hz)")
        ax.set_ylabel("|H(f)| (dB)")
        ax.set_ylim(-100, 5)
        theme.style_plot_axes(ax)

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
