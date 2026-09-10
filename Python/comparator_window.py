"""comparator_window.py — janela "Comparador Morphe".

Carrega um bundle .mrph (conv ou FFT), recomputa o algoritmo em NumPy
sobre o mesmo sinal de entrada, e mostra a comparação numérica e visual
contra o resultado lido do bundle (resposta da FPGA).

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
_COLOR_H      = dsp.COLOR_H     # laranja — h[n] (2º operando da convolução)
_COLOR_FPGA   = dsp.COLOR_Y     # verde
_COLOR_PYTHON = "#dc2626"       # vermelho — referência NumPy
_COLOR_ERROR  = "#ea580c"       # laranja — erro pontual

_BUNDLE_CONV = "conv"
_BUNDLE_FFT  = "fft"
_BUNDLE_FIR  = "fir"
_BUNDLE_IFFT = "ifft"


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


def _detect_bundle_type(bundle: dict) -> str:
    title = bundle.get("title", "").lower()
    names = {s["name"] for s in bundle["sections"]}
    # FIR é checado ANTES de conv: ambos têm sections {x, h, y} idênticas,
    # a única distinção é o title ("Morphe FIR" vs "Morphe convolucao").
    if "fir" in title:
        return _BUNDLE_FIR
    if "conv" in title or names == {"x", "h", "y"}:
        return _BUNDLE_CONV
    # ATENÇÃO à ordem: "ifft" contém "fft". Sem este teste antes, um bundle
    # de IFFT entraria como FFT direta e seria comparado contra np.fft.fft
    # — calado e errado.
    if "ifft" in title:
        if names >= {"X", "x_ifft"}:
            return _BUNDLE_IFFT
        raise ValueError(
            "Este parece um dump de debug da IFFT do servidor (sections "
            "x, y_raw, y). O comparador não sabe recomputá-lo: o espectro "
            "do dump já passou pela escala do cliente.\n\n"
            "Para comparar a IFFT, salve o bundle pela tela da IFFT ou "
            "pela tela da FFT depois de rodar a volta ao tempo — os dois "
            "trazem as seções X e x_ifft."
        )
    if "fft" in title or names == {"x", "X"}:
        return _BUNDLE_FFT
    raise ValueError(
        f"Não foi possível identificar o tipo do bundle. "
        f"title={bundle.get('title')!r}, sections={sorted(names)}. "
        "Esperado: 'Morphe convolucao', 'Morphe FFT' ou 'Morphe FIR'."
    )


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
        self.bundle_type: Optional[str] = None
        self.metrics: Optional[dict] = None
        self.var_fft_mode = tk.StringVar(value="magnitude")
        self._popouts: dict = {}
        # Entradas do bundle: x[n] sempre existe; h[n] existe em conv/FIR
        # (o segundo operando da convolução) e é None para FFT.
        self._x_input = None
        self._n_input = None
        self._h_input = None
        self._n_h_input = None

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

        self.var_type    = tk.StringVar(value="—")
        self.var_saved   = tk.StringVar(value="—")
        self.var_descr   = tk.StringVar(value="—")   # descrição de x[n]
        self.var_descr_h = tk.StringVar(value="—")   # descrição de h[n]

        # Tipo, Salvo em e x[n] são sempre exibidos; a linha de h[n] é
        # criada mas só aparece em bundles conv/FIR — guardo referências
        # para grid()/grid_remove().
        self._h_row_widgets = []
        for i, (label, var, wrap) in enumerate([
            ("Tipo:",         self.var_type,    None),
            ("Salvo em:",     self.var_saved,   None),
            ("Entrada x[n]:", self.var_descr,   220),
            ("Filtro h[n]:",  self.var_descr_h, 220),
        ]):
            lbl_name = ttk.Label(ibox, text=label, style="Card.TLabel")
            lbl_name.grid(row=i, column=0, sticky="nw", pady=(0, 4))
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
            if label == "Filtro h[n]:":
                self._h_row_widgets = [lbl_name, lbl_val]

        # h[n] começa oculto (só conv/FIR o exibem).
        for w in self._h_row_widgets:
            w.grid_remove()

        # ── Card: FFT modo (oculto até carregar bundle FFT) ──
        self.fft_mode_box = ttk.LabelFrame(
            parent, text=" FFT: comparar ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        for label, value in [("Magnitude |X[k]|", "magnitude"),
                             ("Parte real",       "real"),
                             ("Parte imag.",      "imag")]:
            ttk.Radiobutton(
                self.fft_mode_box, text=label,
                variable=self.var_fft_mode, value=value,
                command=self._on_fft_mode_change,
                style="Card.TCheckbutton",
            ).pack(anchor="w")

        # A volta ao tempo só existe se o bundle tiver a seção x_ifft, isto
        # é, se a IFFT foi rodada na FPGA antes de salvar. O botão aparece
        # em _load_bundle e some quando o bundle não tem.
        self.rb_ifft = ttk.Radiobutton(
            self.fft_mode_box, text="x[n] reconstruído (IFFT)",
            variable=self.var_fft_mode, value="ifft",
            command=self._on_fft_mode_change,
            style="Card.TCheckbutton",
        )

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

        # "Visualização ampliada" removida — consolidada nos ⛶ do header.

        # ── Banner informativo (colapsável, fechado por padrão) ──
        info_section = theme.CollapsibleSection(
            parent, title="Como interpretar as métricas",
            expanded=False,
        )
        info_section.pack(fill="x", pady=(0, 0))
        theme.make_banner(
            info_section.body, kind="info",
            text=("O comparador recomputa o algoritmo em NumPy sobre o "
                  "mesmo sinal de entrada e mede a diferença contra a "
                  "resposta da FPGA salva no bundle.\n\n"
                  "• SNR alto (>60 dB) indica bom hardware.\n"
                  "• Erro relativo alto pode sinalizar saturação "
                  "Q15.8 / Q15.16."),
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
            ("Amostras (N)",     self.var_m_n),
            ("Erro abs. max",    self.var_m_max),
            ("Erro RMS",         self.var_m_rms),
            ("SNR (dB)",         self.var_m_snr),
            ("Erro rel. max",    self.var_m_rel),
        ]
        for i, (label, var) in enumerate(rows):
            ttk.Label(mbox, text=label,
                      style="Card.TLabel").grid(
                row=i, column=0, sticky="w", pady=2)
            tk.Label(
                mbox, textvariable=var,
                background=theme.COLORS["card_bg"],
                foreground=theme.COLORS["text"],
                font=("TkDefaultFont", 9, "bold"),
                anchor="w",
            ).grid(row=i, column=1, sticky="w", padx=(8, 0), pady=2)

    def _build_plot_area(self, parent):
        # O cabeçalho (nomes dos plots + ícones ⛶) é reconstruído conforme o
        # tipo de bundle, então mora num container fixo que fica sempre no
        # topo do empacotamento.
        self._header_holder = ttk.Frame(parent, style="Main.TFrame")
        self._header_holder.pack(fill="x", pady=(0, 6))
        self._header = None

        self.fig = Figure(figsize=(7, 6), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])

        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Ferramentas flutuantes (home/pan/zoom/salvar) no canto superior
        # direito — substituem a antiga toolbar cinza do rodapé.
        self.toolbar = PlotToolbar(self.canvas)

        # Layout inicial (sem bundle): 3 subplots com prompt de "vazio".
        self._rebuild_layout(has_h=False, initial=True)

    def _rebuild_layout(self, has_h: bool, *, initial: bool = False):
        """(Re)cria os subplots conforme o tipo de bundle.

        Convolução/FIR têm DOIS operandos de entrada, então x[n] e h[n]
        ganham subplots próprios (4 no total: x, h, comparação, erro). A
        FFT não tem 2º operando → 3 subplots (x, comparação, erro).
        """
        self.fig.clear()
        if has_h:
            self.ax_input   = self.fig.add_subplot(411)
            self.ax_h       = self.fig.add_subplot(412)
            self.ax_compare = self.fig.add_subplot(413)
            self.ax_error   = self.fig.add_subplot(414)
        else:
            self.ax_input   = self.fig.add_subplot(311)
            self.ax_h       = None
            self.ax_compare = self.fig.add_subplot(312)
            self.ax_error   = self.fig.add_subplot(313)

        self._rebuild_header(has_h)

        if initial:
            theme.draw_empty_axes(
                self.ax_input,
                "Abra um bundle .mrph para comparar\nFPGA × NumPy")
            theme.draw_empty_axes(self.ax_compare, "FPGA × NumPy")
            theme.draw_empty_axes(self.ax_error, "Erro = FPGA − NumPy")
            self.fig.tight_layout()
            self.canvas.draw_idle()

    def _rebuild_header(self, has_h: bool):
        """Recria a barra de cabeçalho com um item de pop-out por subplot."""
        if self._header is not None:
            self._header.destroy()
        items = [("Entrada x[n]", lambda: self._popout_one("input"))]
        if has_h:
            items.append(("Filtro h[n]", lambda: self._popout_one("h")))
        items += [
            ("FPGA × NumPy",        lambda: self._popout_one("compare")),
            ("Erro (FPGA − NumPy)", lambda: self._popout_one("error")),
        ]
        self._header = theme.make_plot_header_bar(self._header_holder,
                                                  items=items)
        self._header.pack(fill="x")

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
            btype = _detect_bundle_type(bundle)
        except Exception as e:
            messagebox.showerror("Erro ao abrir bundle", str(e))
            return

        self.path = path
        self.bundle = bundle
        self.bundle_type = btype

        # (Re)monta os subplots: conv/FIR têm subplot próprio para h[n].
        self._rebuild_layout(has_h=(btype in (_BUNDLE_CONV, _BUNDLE_FIR)))

        self.var_path.set(os.path.basename(path))
        type_label = {
            _BUNDLE_CONV: "Convolução 1D",
            _BUNDLE_FFT:  "FFT 1024 pontos",
            _BUNDLE_IFFT: "IFFT 1024 pontos",
            _BUNDLE_FIR:  "Filtro FIR",
        }.get(btype, btype)
        self.var_type.set(type_label)
        self.var_saved.set(bundle.get("saved", "—"))
        # A entrada de um bundle de IFFT pura e o espectro, nao um x[n]:
        # ela vem da tela da IFFT, que carrega X[k] de arquivo e nunca viu
        # o sinal original.
        entrada = "X" if btype == _BUNDLE_IFFT else "x"
        self.var_descr.set(
            dsp.section_by_name(bundle, entrada).get("description", "—"))

        # h[n] só existe em conv/FIR — mostra a linha e sua descrição;
        # em FFT a linha fica oculta.
        if btype in (_BUNDLE_CONV, _BUNDLE_FIR):
            h_sec = dsp.section_by_name(bundle, "h")
            self.var_descr_h.set(h_sec.get("description", "—"))
            for w in self._h_row_widgets:
                w.grid()
        else:
            for w in self._h_row_widgets:
                w.grid_remove()

        if btype == _BUNDLE_FFT:
            self.fft_mode_box.pack(fill="x", pady=(0, 10))
            tem_ifft = any(sec["name"] == "x_ifft"
                           for sec in bundle["sections"])
            if tem_ifft:
                self.rb_ifft.pack(anchor="w")
            else:
                self.rb_ifft.pack_forget()
                if self.var_fft_mode.get() == "ifft":
                    self.var_fft_mode.set("magnitude")
        else:
            self.fft_mode_box.pack_forget()

        self.btn_export.configure(state="normal")
        self.status.set(f"Carregado: {os.path.basename(path)}")

        self._recompute_and_redraw()

    def _on_fft_mode_change(self):
        if self.bundle_type == _BUNDLE_FFT:
            self._recompute_and_redraw()

    # ==================================================================
    # Recomputação + plot
    # ==================================================================

    def _recompute_and_redraw(self):
        if self.bundle is None or self.bundle_type is None:
            return
        try:
            if self.bundle_type == _BUNDLE_CONV:
                self._compute_conv()
            elif self.bundle_type == _BUNDLE_FIR:
                self._compute_fir()
            elif self.bundle_type == _BUNDLE_IFFT:
                self._compute_ifft()
            else:
                self._compute_fft()
        except Exception as e:
            messagebox.showerror("Erro na recomputação", str(e))
            return
        self._update_metrics_ui()
        self._redraw_plots()

    def _compute_conv(self):
        b = self.bundle
        x = dsp.section_by_name(b, "x")["data"]
        h = dsp.section_by_name(b, "h")["data"]
        y_fpga = dsp.section_by_name(b, "y")["data"]

        y_python_full = dsp.recompute_conv_numpy(x, h)

        n_compare = min(len(y_python_full), len(y_fpga))
        y_python = y_python_full[:n_compare]
        y_fpga_cmp = y_fpga[:n_compare]

        self.metrics = dsp.compute_error_metrics(y_fpga_cmp, y_python)

        self._x_input  = x
        self._n_input  = dsp.section_by_name(b, "x")["n"]
        self._h_input  = h
        self._n_h_input = dsp.section_by_name(b, "h")["n"]
        self._n_output = np.arange(n_compare, dtype=np.int64)
        self._y_fpga   = y_fpga_cmp
        self._y_python = y_python
        self._error    = y_fpga_cmp - y_python
        self._is_complex_compare = False
        self._cmp_label = "y[n]"

    def _compute_fir(self):
        """Comparação FIR (FPGA × NumPy).

        O FIR é matematicamente uma convolução linear cheia entre o sinal
        de entrada x[n] e os coeficientes do filtro h[n] -- reutiliza o
        mesmo cálculo de _compute_conv (np.convolve em modo 'full' via
        dsp.recompute_conv_numpy) e só ajusta o rótulo de comparação
        para sinalizar a semântica de filtro na UI e no relatório.

        Se a FPGA emitir menos amostras que len(x)+len(h)-1 (típico em
        FIR streaming, onde a saída tem o mesmo tamanho que x), a lógica
        de truncamento por `n_compare = min(...)` herdada de _compute_conv
        compara apenas o overlap -- e os primeiros len(x) bins de
        np.convolve(x, h, full) coincidem exatamente com a saída de um
        FIR streaming causal, então a comparação é matematicamente correta.
        """
        self._compute_conv()
        self._cmp_label = "y[n] (FIR)"

    def _compute_fft(self):
        b = self.bundle
        x = dsp.section_by_name(b, "x")["data"]
        X_fpga = dsp.section_by_name(b, "X")["data"]
        X_python = dsp.recompute_fft_numpy(x, n_fft=1024)

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
        elif mode == "ifft":
            # Volta ao tempo: compara o x[n] que a FPGA reconstruiu com o
            # que o NumPy tira do MESMO X[k] lido do bundle. Assim o que
            # se mede e so a IFFT -- o erro da ida ja esta nos dois lados.
            a = np.real(dsp.section_by_name(b, "x_ifft")["data"])
            b_ref = np.real(np.fft.ifft(X_fpga))
            self._cmp_label = "x[n] reconstruído (IFFT)"
        else:
            raise ValueError(f"modo FFT inválido: {mode!r}")

        self.metrics = dsp.compute_error_metrics(a, b_ref)

        self._x_input  = x
        self._n_input  = dsp.section_by_name(b, "x")["n"]
        self._h_input  = None          # FFT não tem 2º operando h[n]
        self._n_h_input = None
        self._n_output = np.arange(len(a), dtype=np.int64)
        self._y_fpga   = a
        self._y_python = b_ref
        self._error    = a - b_ref
        self._is_complex_compare = False

    def _rotulos_entrada(self):
        """(titulo, rotulo x, rotulo y) do subplot de entrada.

        Numa IFFT a entrada e o espectro, nao um sinal no tempo.
        """
        if self.bundle_type == _BUNDLE_IFFT:
            return "Espectro de entrada |X[k]|", "k", "|X[k]|"
        return "Sinal de entrada x[n]", "n", "x[n]"

    def _eixo_x_label(self) -> str:
        """Rotulo do eixo horizontal da comparacao.

        Bundle de FFT indexa em k -- menos no modo IFFT, em que o que
        esta na tela ja voltou para o dominio do tempo.
        """
        if self.bundle_type == _BUNDLE_IFFT:
            return "n"
        if self.bundle_type != _BUNDLE_FFT:
            return "n"
        return "n" if self.var_fft_mode.get() == "ifft" else "k"

    def _compute_ifft(self):
        """Bundle de IFFT pura: so o espectro e o que a FPGA devolveu.

        Aqui a comparacao mede a inversa ISOLADA -- diferente do modo
        'ifft' de um bundle de FFT, onde o X[k] ja carrega o erro da ida.
        """
        b = self.bundle
        X = np.asarray(dsp.section_by_name(b, "X")["data"],
                       dtype=np.complex128)
        x_fpga = np.real(np.asarray(
            dsp.section_by_name(b, "x_ifft")["data"]))
        x_python = np.real(np.fft.ifft(X))

        self.metrics = dsp.compute_error_metrics(x_fpga, x_python)
        self._cmp_label = "x[n] = IFFT(X)"

        # O "sinal de entrada" desta comparacao e o espectro: mostramos a
        # magnitude dele no primeiro subplot.
        self._x_input  = np.abs(X)
        self._n_input  = np.arange(len(X), dtype=np.int64)
        self._h_input  = None
        self._n_h_input = None
        self._n_output = np.arange(len(x_fpga), dtype=np.int64)
        self._y_fpga   = x_fpga
        self._y_python = x_python
        self._error    = x_fpga - x_python
        self._is_complex_compare = False

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
        ent_titulo, ent_x, ent_y = self._rotulos_entrada()
        self.ax_input.set_title(f"{ent_titulo}  (N={len(x)})", fontsize=9)
        self.ax_input.set_xlabel(ent_x)
        self.ax_input.set_ylabel(ent_y)
        self.ax_input.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
        theme.style_plot_axes(self.ax_input)
        _attach_stem_format_coord(self.ax_input,
                                   np.asarray(n, dtype=float), x,
                                   x_label="n", y_label="x")

        # Subplot dedicado a h[n] — só existe em conv/FIR (a FFT não tem
        # 2º operando). Antes o h[n] ficava oculto; agora tem plot próprio.
        if self.ax_h is not None and self._h_input is not None:
            self.ax_h.clear()
            nh = np.asarray(self._n_h_input, dtype=float)
            _draw_discrete(self.ax_h, nh, self._h_input, _COLOR_H)
            self.ax_h.set_title(
                f"Filtro / resposta h[n]  (N={len(self._h_input)})",
                fontsize=9)
            self.ax_h.set_xlabel("n")
            self.ax_h.set_ylabel("h[n]")
            self.ax_h.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
            theme.style_plot_axes(self.ax_h)
            _attach_stem_format_coord(self.ax_h, nh, self._h_input,
                                       x_label="n", y_label="h")

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
        self.ax_compare.set_xlabel(self._eixo_x_label())
        self.ax_compare.set_ylabel(self._cmp_label)
        self.ax_compare.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
        self.ax_compare.legend(fontsize=8, loc="best")
        theme.style_plot_axes(self.ax_compare)
        _attach_stem_format_coord(
            self.ax_compare, n_out_f, self._y_fpga,
            x_label=self._eixo_x_label(),
            y_label="FPGA")

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
        self.ax_error.set_xlabel(self._eixo_x_label())
        self.ax_error.set_ylabel("erro")
        self.ax_error.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
        theme.style_plot_axes(self.ax_error)
        _attach_stem_format_coord(
            self.ax_error, n_out_f, self._error,
            x_label=self._eixo_x_label(),
            y_label="erro")

        self.fig.tight_layout()
        self.canvas.draw_idle()
        refresh_all(self._popouts)

    # ==================================================================
    # Pop-outs por plot (substitui o "Visualização ampliada" único)
    # ==================================================================

    def _popout_one(self, which: str):
        if self.bundle is None:
            messagebox.showwarning("Atenção", "Abra um bundle .mrph antes.")
            return

        # Lazy imports do estado já calculado por _redraw_plots
        n = np.asarray(self._n_input, dtype=float)
        nout = np.asarray(self._n_output, dtype=float)

        if which == "input":
            def draw(fig: Figure):
                ax = fig.add_subplot(111)
                _draw_discrete(ax, n, self._x_input, _COLOR_INPUT)
                ent_titulo, _, _ = self._rotulos_entrada()
                ax.set_title(f"{ent_titulo}  (N={len(self._x_input)})")
                ax.set_xlabel("n")
                ax.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
                theme.style_plot_axes(ax)
            open_or_focus(self._popouts, key="one_input",
                          parent=self, title="Morphe — entrada x[n]",
                          draw_fn=draw, size="1000x600")
        elif which == "h":
            def draw(fig: Figure):
                ax = fig.add_subplot(111)
                if self._h_input is None:
                    theme.draw_empty_axes(ax, "h[n] (não disponível)")
                    return
                nh = np.asarray(self._n_h_input, dtype=float)
                _draw_discrete(ax, nh, self._h_input, _COLOR_H)
                ax.set_title(
                    f"Filtro / resposta h[n]  (N={len(self._h_input)})")
                ax.set_xlabel("n")
                ax.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
                theme.style_plot_axes(ax)
            open_or_focus(self._popouts, key="one_h",
                          parent=self, title="Morphe — h[n]",
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
                ax.set_xlabel(self._eixo_x_label())
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
                ax.set_xlabel(self._eixo_x_label())
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
            f.write(f"# tipo: {self.bundle_type}\n")
            if self.bundle_type == _BUNDLE_FFT:
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
            f.write("## ARRAYS (n  fpga  numpy  erro)\n")
            for i in range(len(self._n_output)):
                f.write(f"{int(self._n_output[i])}\t"
                        f"{float(self._y_fpga[i]):.8e}\t"
                        f"{float(self._y_python[i]):.8e}\t"
                        f"{float(self._error[i]):.8e}\n")
