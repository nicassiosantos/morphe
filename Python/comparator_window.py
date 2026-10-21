"""comparator_window.py — janela "Comparador Morphe".

Carrega um bundle .mrph de FFT, recomputa a transformada em NumPy sobre o
mesmo sinal de entrada e mostra a comparação numérica e visual contra o
resultado lido do bundle (resposta da FPGA).

Refatorado para consumir `morphe_theme`.
"""
from __future__ import annotations

import datetime as _dt
import os
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
from popout_helper import open_or_focus, refresh_all
from plot_toolbar import PlotToolbar


# Cores consistentes com o resto do app
_COLOR_INPUT  = dsp.COLOR_X     # azul — x[n]
_COLOR_FPGA   = dsp.COLOR_Y     # verde
_COLOR_PYTHON = "#dc2626"       # vermelho — referência NumPy
_COLOR_ERROR  = "#ea580c"       # laranja — erro pontual


def _attach_stem_format_coord(ax, n_arr: np.ndarray, x_arr: np.ndarray,
                               x_label: str = "n", y_label: str = "x",
                               value_fmt: str = "{:.4g}"):
    if n_arr.size == 0:
        return
    n_arr = np.asarray(n_arr, dtype=float)
    x_arr = np.asarray(x_arr)

    def fmt(xc, yc):
        i = int(np.argmin(np.abs(n_arr - xc)))
        n_i = int(n_arr[i])
        try:
            v_str = value_fmt.format(float(x_arr[i]))
        except (TypeError, ValueError):
            v_str = str(x_arr[i])
        return f"{x_label}={n_i},  {y_label}[{n_i}] = {v_str}"

    ax.format_coord = fmt


def _draw_discrete(ax, n, y, color, *, markersize_stem: int = 3, label=None):
    """Desenha uma sequência de tempo DISCRETO em `ax` como stem
    (haste + marcador), qualquer que seja o número de amostras."""
    n = np.asarray(n, dtype=float)
    y = np.asarray(y)
    ml, sl, _ = ax.stem(n, y, basefmt=" ", label=label)
    ml.set_markersize(markersize_stem)
    ml.set_color(color)
    ml.set_markerfacecolor(color)
    sl.set_color(color)


def _confere_bundle_fft(bundle: dict) -> None:
    """Recusa, com uma mensagem que diz o porquê, o que não é bundle de FFT."""
    title = bundle.get("title", "").lower()
    names = {s["name"] for s in bundle["sections"]}
    if names >= {"x", "X"}:
        return
    if "fft" in title and names >= {"x", "y_raw", "y"}:
        raise ValueError(
            "Este é um dump de depuração do servidor (seções x, y_raw, y). "
            "Para comparar, salve o bundle pela janela da FFT: ele traz as "
            "seções x e X.")
    raise ValueError(
        f"Este bundle não é de FFT. title={bundle.get('title')!r}, "
        f"sections={sorted(names)}. Esperado: as seções x e X, como a "
        "janela da FFT salva.")


class ComparatorWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Morphe — Comparador (.mrph FPGA × NumPy)")
        self.geometry("1180x820")
        self.configure(bg=theme.COLORS["bg"])

        theme.setup_styles(self)

        # Estado interno
        self.path: Optional[str] = None
        self.bundle: Optional[dict] = None
        self.metrics: Optional[dict] = None
        self.var_fft_mode = tk.StringVar(value="magnitude")
        self._popouts: dict = {}
        self._x_input = None
        self._n_input = None

        # Status bar
        self.status = tk.StringVar(value="Pronto. Abra um bundle .mrph.")
        theme.make_status_bar(self, self.status).pack(side="bottom", fill="x")

        root = ttk.Frame(self, style="Main.TFrame", padding=12)
        root.pack(fill="both", expand=True)

        sidebar = ttk.Frame(root, style="Main.TFrame")
        sidebar.pack(side="left", fill="y", padx=(0, 12))
        plot_area = ttk.Frame(root, style="Main.TFrame")
        plot_area.pack(side="right", fill="both", expand=True)

        self._build_controls(sidebar)
        self._build_metrics(sidebar)
        self._build_plot_area(plot_area)

    # ==================================================================

    def _build_controls(self, parent):
        # ── Card: Arquivo ──
        fbox = ttk.LabelFrame(
            parent, text=" Arquivo ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        fbox.pack(fill="x", pady=(0, 10))

        ttk.Label(fbox, text="Bundle .mrph",
                  style="Card.TLabel").pack(anchor="w", pady=(0, 4))
        self.var_path = tk.StringVar(value="(nenhum)")
        tk.Label(
            fbox, textvariable=self.var_path,
            background=theme.COLORS["card_bg"],
            foreground=theme.COLORS["text_muted"],
            font=("TkDefaultFont", 9),
            wraplength=300, justify="left", anchor="w",
        ).pack(fill="x", pady=(0, 8))

        # PRIMARY: abrir é a ação que inicia todo o fluxo
        ttk.Button(
            fbox, text="Abrir bundle .mrph…",
            style="Primary.TButton",
            command=self._on_open,
        ).pack(fill="x")

        # ── Card: Bundle carregado ──
        ibox = ttk.LabelFrame(
            parent, text=" Bundle carregado ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        ibox.pack(fill="x", pady=(0, 10))
        ibox.columnconfigure(0, minsize=85)
        ibox.columnconfigure(1, weight=1)

        self.var_type  = tk.StringVar(value="—")
        self.var_saved = tk.StringVar(value="—")
        self.var_descr = tk.StringVar(value="—")   # descrição de x[n]

        for i, (label, var, wrap) in enumerate([
            ("Tipo:",         self.var_type,  None),
            ("Salvo em:",     self.var_saved, None),
            ("Entrada x[n]:", self.var_descr, 220),
        ]):
            ttk.Label(ibox, text=label, style="Card.TLabel").grid(
                row=i, column=0, sticky="nw", pady=(0, 4))
            lbl_val = tk.Label(
                ibox, textvariable=var,
                background=theme.COLORS["card_bg"],
                foreground=theme.COLORS["text"],
                font=("TkDefaultFont", 9),
                anchor="w", justify="left",
            )
            if wrap:
                lbl_val.configure(wraplength=wrap)
            lbl_val.grid(row=i, column=1, sticky="w", pady=(0, 4))

        # ── Card: o que comparar ──
        mode_box = ttk.LabelFrame(
            parent, text=" FFT: comparar ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        mode_box.pack(fill="x", pady=(0, 10))
        for label, value in [("Magnitude |X[k]|", "magnitude"),
                             ("Parte real",       "real"),
                             ("Parte imag.",      "imag")]:
            ttk.Radiobutton(
                mode_box, text=label,
                variable=self.var_fft_mode, value=value,
                command=self._recompute_and_redraw,
                style="Card.TCheckbutton",
            ).pack(anchor="w")

        # ── Card: Ações ──
        abox = ttk.LabelFrame(
            parent, text=" Relatório ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        abox.pack(fill="x", pady=(0, 10))

        self.btn_export = ttk.Button(
            abox, text="Exportar relatório (.txt)",
            style="Secondary.TButton",
            command=self._on_export_report, state="disabled",
        )
        self.btn_export.pack(fill="x")

        # ── Banner informativo (colapsável, fechado por padrão) ──
        info_section = theme.CollapsibleSection(
            parent, title="Como interpretar as métricas",
            expanded=False,
        )
        info_section.pack(fill="x", pady=(0, 0))
        theme.make_banner(
            info_section.body, kind="info",
            text=("O comparador recomputa a FFT em NumPy sobre o mesmo "
                  "sinal de entrada e mede a diferença contra a resposta "
                  "da FPGA salva no bundle.\n\n"
                  "• SNR alto (>60 dB) indica bom hardware.\n"
                  "• Erro relativo alto pode sinalizar saturação Q15.8."),
            wraplength=300,
        ).pack(fill="x")

    def _build_metrics(self, parent):
        mbox = ttk.LabelFrame(
            parent, text=" Métricas (FPGA × NumPy) ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        mbox.pack(fill="x", pady=(10, 0))
        mbox.columnconfigure(0, minsize=130)
        mbox.columnconfigure(1, weight=1)

        self.var_m_n   = tk.StringVar(value="—")
        self.var_m_max = tk.StringVar(value="—")
        self.var_m_rms = tk.StringVar(value="—")
        self.var_m_snr = tk.StringVar(value="—")
        self.var_m_rel = tk.StringVar(value="—")

        rows = [
            ("Amostras (N)",  self.var_m_n),
            ("Erro abs. max", self.var_m_max),
            ("Erro RMS",      self.var_m_rms),
            ("SNR (dB)",      self.var_m_snr),
            ("Erro rel. max", self.var_m_rel),
        ]
        for i, (label, var) in enumerate(rows):
            ttk.Label(mbox, text=label, style="Card.TLabel").grid(
                row=i, column=0, sticky="w", pady=2)
            tk.Label(
                mbox, textvariable=var,
                background=theme.COLORS["card_bg"],
                foreground=theme.COLORS["text"],
                font=("TkDefaultFont", 9, "bold"),
                anchor="w",
            ).grid(row=i, column=1, sticky="w", padx=(8, 0), pady=2)

    def _build_plot_area(self, parent):
        header = theme.make_plot_header_bar(parent, items=[
            ("Entrada x[n]",        lambda: self._popout_one("input")),
            ("FPGA × NumPy",        lambda: self._popout_one("compare")),
            ("Erro (FPGA − NumPy)", lambda: self._popout_one("error")),
        ])
        header.pack(fill="x", pady=(0, 6))

        self.fig = Figure(figsize=(7, 6), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        self.ax_input   = self.fig.add_subplot(311)
        self.ax_compare = self.fig.add_subplot(312)
        self.ax_error   = self.fig.add_subplot(313)

        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Ferramentas flutuantes (home/pan/zoom/salvar) no canto superior
        # direito — substituem a antiga toolbar cinza do rodapé.
        self.toolbar = PlotToolbar(self.canvas)

        theme.draw_empty_axes(
            self.ax_input,
            "Abra um bundle .mrph para comparar\nFPGA × NumPy")
        theme.draw_empty_axes(self.ax_compare, "FPGA × NumPy")
        theme.draw_empty_axes(self.ax_error, "Erro = FPGA − NumPy")
        self.fig.tight_layout()
        self.canvas.draw_idle()

    # ==================================================================
    # Abertura de arquivo
    # ==================================================================

    def _on_open(self):
        path = filedialog.askopenfilename(
            title="Abrir bundle Morphe",
            filetypes=[("Morphe bundle", "*.mrph"),
                       ("Todos", "*.*")],
        )
        if not path:
            return
        self._load_path(path)

    def _load_path(self, path: str):
        try:
            bundle = dsp.parse_mrph_bundle(path)
            _confere_bundle_fft(bundle)
        except Exception as e:
            messagebox.showerror("Erro ao abrir bundle", str(e))
            return

        self.path = path
        self.bundle = bundle

        self.var_path.set(os.path.basename(path))
        # N do espectro salvo: 1024, ou o multiplo de 1024 de uma FFT longa.
        n_espectro = len(dsp.section_by_name(bundle, "X")["data"])
        self.var_type.set(f"FFT {n_espectro} pontos")
        self.var_saved.set(bundle.get("saved", "—"))
        self.var_descr.set(
            dsp.section_by_name(bundle, "x").get("description", "—"))

        self.btn_export.configure(state="normal")
        self.status.set(f"Carregado: {os.path.basename(path)}")

        self._recompute_and_redraw()

    # ==================================================================
    # Recomputação + plot
    # ==================================================================

    def _recompute_and_redraw(self):
        if self.bundle is None:
            return
        try:
            self._compute_fft()
        except Exception as e:
            messagebox.showerror("Erro na recomputação", str(e))
            return
        self._update_metrics_ui()
        self._redraw_plots()

    def _compute_fft(self):
        b = self.bundle
        x = dsp.section_by_name(b, "x")["data"]
        X_fpga = dsp.section_by_name(b, "X")["data"]
        # N sai do X[k] salvo, nao de uma constante: desde 23/09/2026 um sinal
        # maior que 1024 vira uma FFT de N = multiplo de 1024 acima (quatro
        # passos, blocos.fft_longa), e a referencia tem de ter o mesmo N. Com
        # 1024 fixo, o x era cortado nas primeiras 1024 amostras e a
        # comparacao parava em "shapes diferentes".
        X_python = dsp.recompute_fft_numpy(x, n_fft=len(X_fpga))

        mode = self.var_fft_mode.get()
        if mode == "magnitude":
            a = np.abs(X_fpga)
            b_ref = np.abs(X_python)
            self._cmp_label = "|X[k]|"
        elif mode == "real":
            a = X_fpga.real
            b_ref = X_python.real
            self._cmp_label = "Re{X[k]}"
        elif mode == "imag":
            a = X_fpga.imag
            b_ref = X_python.imag
            self._cmp_label = "Im{X[k]}"
        else:
            raise ValueError(f"modo FFT inválido: {mode!r}")

        self.metrics = dsp.compute_error_metrics(a, b_ref)

        self._x_input  = x
        self._n_input  = dsp.section_by_name(b, "x")["n"]
        self._n_output = np.arange(len(a), dtype=np.int64)
        self._y_fpga   = a
        self._y_python = b_ref
        self._error    = a - b_ref

    def _update_metrics_ui(self):
        m = self.metrics
        if m is None:
            return

        def fmt_g(x):
            if x is None or (isinstance(x, float) and np.isnan(x)):
                return "n/a"
            return f"{x:.6g}"

        self.var_m_n.set(str(m["n"]))
        self.var_m_max.set(fmt_g(m["max_abs_error"]))
        self.var_m_rms.set(fmt_g(m["rms_error"]))

        snr = m["snr_db"]
        if snr == float("inf"):
            self.var_m_snr.set("∞ (FPGA == NumPy)")
        elif snr == float("-inf"):
            self.var_m_snr.set("−∞ (referência ~zero)")
        else:
            self.var_m_snr.set(f"{snr:.2f} dB")

        rel = m["max_rel_error"]
        ridx = m["max_rel_index"]
        if np.isnan(rel) or ridx < 0:
            self.var_m_rel.set("n/a")
        else:
            self.var_m_rel.set(f"{rel:.4g}  (em k={ridx})")

    def _redraw_plots(self):
        # Subplot: entrada x[n]
        self.ax_input.clear()
        n = self._n_input
        x = self._x_input
        # x[n] é um sinal de tempo DISCRETO — nunca desenhar como linha
        # contínua, mesmo com N grande (ver _draw_discrete).
        _draw_discrete(self.ax_input, n, x, _COLOR_INPUT)
        self.ax_input.set_title(f"Sinal de entrada x[n]  (N={len(x)})", fontsize=9)
        self.ax_input.set_xlabel("n")
        self.ax_input.set_ylabel("x[n]")
        self.ax_input.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
        theme.style_plot_axes(self.ax_input)
        _attach_stem_format_coord(self.ax_input,
                                   np.asarray(n, dtype=float), x,
                                   x_label="n", y_label="x")

        # Subplot 2: FPGA × NumPy
        self.ax_compare.clear()
        n_out = self._n_output
        n_out_f = np.asarray(n_out, dtype=float)
        if len(n_out) >= 512:
            self.ax_compare.plot(n_out_f, self._y_fpga, color=_COLOR_FPGA,
                                 linewidth=1.0, label="FPGA")
            self.ax_compare.plot(n_out_f, self._y_python, color=_COLOR_PYTHON,
                                 linewidth=1.0, linestyle="--",
                                 label="NumPy (ref)")
        else:
            ml, sl, _ = self.ax_compare.stem(n_out_f, self._y_fpga,
                                              basefmt=" ", label="FPGA")
            ml.set_markersize(4)
            ml.set_color(_COLOR_FPGA)
            ml.set_markerfacecolor(_COLOR_FPGA)
            sl.set_color(_COLOR_FPGA)
            self.ax_compare.plot(n_out_f, self._y_python,
                                 color=_COLOR_PYTHON, linewidth=1.2,
                                 linestyle="--", marker="o", markersize=3,
                                 label="NumPy (ref)")
        self.ax_compare.set_title(
            f"Comparação: {self._cmp_label}", fontsize=9)
        self.ax_compare.set_xlabel("k")
        self.ax_compare.set_ylabel(self._cmp_label)
        self.ax_compare.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
        self.ax_compare.legend(fontsize=8, loc="best")
        theme.style_plot_axes(self.ax_compare)
        _attach_stem_format_coord(
            self.ax_compare, n_out_f, self._y_fpga,
            x_label="k", y_label="FPGA")

        # Subplot 3: erro
        self.ax_error.clear()
        if len(n_out) >= 512:
            self.ax_error.plot(n_out_f, self._error,
                               color=_COLOR_ERROR, linewidth=0.8)
        else:
            ml, sl, _ = self.ax_error.stem(n_out_f, self._error,
                                            basefmt=" ")
            ml.set_markersize(3)
            ml.set_color(_COLOR_ERROR)
            ml.set_markerfacecolor(_COLOR_ERROR)
            sl.set_color(_COLOR_ERROR)
        self.ax_error.set_title(
            f"Erro (FPGA − NumPy), max abs = "
            f"{self.metrics['max_abs_error']:.4g}",
            fontsize=9)
        self.ax_error.set_xlabel("k")
        self.ax_error.set_ylabel("erro")
        self.ax_error.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
        theme.style_plot_axes(self.ax_error)
        _attach_stem_format_coord(
            self.ax_error, n_out_f, self._error,
            x_label="k", y_label="erro")

        self.fig.tight_layout()
        self.canvas.draw_idle()
        refresh_all(self._popouts)

    # ==================================================================
    # Pop-outs por plot
    # ==================================================================

    def _popout_one(self, which: str):
        if self.bundle is None:
            messagebox.showwarning("Atenção", "Abra um bundle .mrph antes.")
            return

        n = np.asarray(self._n_input, dtype=float)
        nout = np.asarray(self._n_output, dtype=float)

        if which == "input":
            def draw(fig: Figure):
                ax = fig.add_subplot(111)
                _draw_discrete(ax, n, self._x_input, _COLOR_INPUT)
                ax.set_title(f"Sinal de entrada x[n]  (N={len(self._x_input)})")
                ax.set_xlabel("n")
                ax.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
                theme.style_plot_axes(ax)
            open_or_focus(self._popouts, key="one_input",
                          parent=self, title="Morphe — entrada x[n]",
                          draw_fn=draw, size="1000x600")
        elif which == "compare":
            def draw(fig: Figure):
                ax = fig.add_subplot(111)
                if len(nout) >= 512:
                    ax.plot(nout, self._y_fpga, color=_COLOR_FPGA,
                            linewidth=1.0, label="FPGA")
                    ax.plot(nout, self._y_python, color=_COLOR_PYTHON,
                            linewidth=1.0, linestyle="--", label="NumPy")
                else:
                    ml, sl, _ = ax.stem(nout, self._y_fpga, basefmt=" ",
                                         label="FPGA")
                    ml.set_color(_COLOR_FPGA); ml.set_markerfacecolor(_COLOR_FPGA)
                    ml.set_markersize(4); sl.set_color(_COLOR_FPGA)
                    ax.plot(nout, self._y_python, color=_COLOR_PYTHON,
                            linewidth=1.2, linestyle="--", marker="o",
                            markersize=3, label="NumPy")
                ax.set_title(f"Comparação: {self._cmp_label}")
                ax.set_xlabel("k")
                ax.set_ylabel(self._cmp_label); ax.legend(fontsize=8)
                ax.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
                theme.style_plot_axes(ax)
            open_or_focus(self._popouts, key="one_compare",
                          parent=self, title="Morphe — FPGA × NumPy",
                          draw_fn=draw, size="1000x600")
        elif which == "error":
            def draw(fig: Figure):
                ax = fig.add_subplot(111)
                if len(nout) >= 512:
                    ax.plot(nout, self._error, color=_COLOR_ERROR, linewidth=0.8)
                else:
                    ml, sl, _ = ax.stem(nout, self._error, basefmt=" ")
                    ml.set_color(_COLOR_ERROR); ml.set_markerfacecolor(_COLOR_ERROR)
                    ml.set_markersize(3); sl.set_color(_COLOR_ERROR)
                ax.set_title(f"Erro (FPGA − NumPy), max abs = "
                             f"{self.metrics['max_abs_error']:.4g}")
                ax.set_xlabel("k")
                ax.set_ylabel("erro")
                ax.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
                theme.style_plot_axes(ax)
            open_or_focus(self._popouts, key="one_error",
                          parent=self, title="Morphe — erro",
                          draw_fn=draw, size="1000x600")

    # ==================================================================
    # Relatório
    # ==================================================================

    def _on_export_report(self):
        if self.metrics is None or self.bundle is None:
            return

        base, _ = os.path.splitext(os.path.basename(self.path or "report"))
        default_name = f"{base}_report.txt"
        out_path = filedialog.asksaveasfilename(
            title="Exportar relatório",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("Texto", "*.txt"), ("Todos", "*.*")],
        )
        if not out_path:
            return

        try:
            self._write_report(out_path)
            self.status.set(f"Relatório salvo: {os.path.basename(out_path)}")
            messagebox.showinfo("Exportar", f"Relatório salvo em:\n{out_path}")
        except Exception as e:
            messagebox.showerror("Erro ao exportar", str(e))

    def _write_report(self, out_path: str):
        m = self.metrics
        b = self.bundle
        x_sec = dsp.section_by_name(b, "x")

        snr = m["snr_db"]
        if snr == float("inf"):
            snr_str = "infinito (FPGA idêntica a NumPy)"
        elif snr == float("-inf"):
            snr_str = "-inf (referência praticamente zero)"
        else:
            snr_str = f"{snr:.4f} dB"

        rel = m["max_rel_error"]
        rel_str = ("n/a" if np.isnan(rel)
                   else f"{rel:.6g} (em índice {m['max_rel_index']})")

        ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write("# RELATORIO DE COMPARACAO MORPHE\n")
            f.write(f"# gerado: {ts}\n")
            f.write(f"# bundle: {self.path}\n")
            f.write(f"# bundle_saved: {b.get('saved', '-')}\n")
            f.write(f"# bundle_title: {b.get('title', '-')}\n")
            f.write("# tipo: fft\n")
            f.write(f"# fft_mode: {self.var_fft_mode.get()}\n")
            f.write(f"# sinal_entrada: {x_sec.get('description', '-')}\n")
            f.write(f"# fs_entrada: {x_sec.get('fs', 1.0)}\n")
            f.write(f"# n_amostras_entrada: {len(x_sec['data'])}\n")
            f.write("\n")
            f.write("## METRICAS (FPGA vs NumPy)\n")
            f.write(f"n_amostras_comparadas:  {m['n']}\n")
            f.write(f"erro_abs_max:           {m['max_abs_error']:.10g}\n")
            f.write(f"erro_rms:               {m['rms_error']:.10g}\n")
            f.write(f"snr_db:                 {snr_str}\n")
            f.write(f"erro_rel_max:           {rel_str}\n")
            f.write(f"norma_referencia:       {m['norm_ref']:.10g}\n")
            f.write(f"norma_diferenca:        {m['norm_diff']:.10g}\n")
            f.write("\n")
            f.write("## ARRAYS (k  fpga  numpy  erro)\n")
            for i in range(len(self._n_output)):
                f.write(f"{int(self._n_output[i])}\t"
                        f"{float(self._y_fpga[i]):.8e}\t"
                        f"{float(self._y_python[i]):.8e}\t"
                        f"{float(self._error[i]):.8e}\n")
