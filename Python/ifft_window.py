"""ifft_window.py -- janela da IFFT com espectro vindo de arquivo.

A IFFT tambem existe dentro da janela da FFT, como "voltar ao tempo" do
X[k] que acabou de ser calculado. Esta janela e o caminho independente:
o espectro entra de um arquivo .mrph, sem precisar rodar a FFT antes.

Serve para tres coisas que a outra nao faz:

  - Reprocessar um X[k] guardado semanas atras, ou gerado em outro lugar
    (NumPy, MATLAB), sem depender do sinal original.
  - Testar a IFFT sozinha, isolada do erro que a FFT direta introduz --
    que e maior, porque a FFT manda x[n] sem aproveitar a faixa do Q15.8.
  - Comparar a inversa da FPGA contra o NumPy num espectro qualquer, e
    nao so no que a propria FPGA produziu.

O que o hardware faz e o mesmo nos dois caminhos: OP_IFFT, bit `inverse`
ligado no IP, espectro normalizado para a faixa do Q15.8 na ida e escala
desfeita na volta.
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
import morphe_config as cfg
import morphe_theme as theme
from morphe_protocol import build_ifft_request, decode_ifft_response
from plot_toolbar import PlotToolbar
from popout_helper import open_or_focus, refresh_all


_COLOR_NUMPY = "#dc2626"   # vermelho -- referencia calculada no PC


def _plot_espectro(ax, X: Optional[np.ndarray], fs: float):
    ax.clear()
    if X is None:
        theme.draw_empty_axes(ax, "|X[k]| — abra um arquivo com o espectro")
        return
    k = np.arange(len(X))
    ax.plot(k, np.abs(X), color=dsp.COLOR_MAG, linewidth=0.9)
    ax.set_title("Espectro de entrada  |X[k]|   (N=%d)" % len(X), fontsize=9)
    ax.set_xlabel("k")
    ax.set_ylabel("|X[k]|")
    theme.style_plot_axes(ax)


def _plot_reconstruido(ax, x_hw: Optional[np.ndarray],
                       x_ref: Optional[np.ndarray], n_uteis: Optional[int]):
    """Sinal reconstruido pela FPGA, sozinho no seu proprio eixo."""
    ax.clear()
    if x_hw is None:
        theme.draw_empty_axes(ax, "x[n] reconstruído — rode a IFFT na FPGA")
        return
    n = np.arange(len(x_hw))
    ax.plot(n, np.real(x_hw), color=dsp.COLOR_Y, linewidth=1.0,
            label="IFFT na FPGA")
    if x_ref is not None:
        ax.plot(n, np.real(x_ref), color=_COLOR_NUMPY, linewidth=0.9,
                linestyle="--", alpha=0.8, label="np.fft.ifft (ref)")
    titulo = "x[n] reconstruído  (N=%d)" % len(x_hw)
    if n_uteis is not None and n_uteis < len(x_hw):
        ax.axvline(n_uteis - 0.5, color=theme.COLORS["axis"], linewidth=0.8,
                   linestyle=":", alpha=0.7)
        titulo += "   — a linha marca onde acaba o sinal e começa o padding"
    ax.set_title(titulo, fontsize=9)
    ax.set_xlabel("n")
    ax.set_ylabel("x[n]")
    ax.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
    ax.legend(fontsize=7, loc="upper right")
    theme.style_plot_axes(ax)


def _plot_erro(ax, x_hw: Optional[np.ndarray], x_ref: Optional[np.ndarray]):
    ax.clear()
    if x_hw is None or x_ref is None:
        theme.draw_empty_axes(ax, "Erro FPGA − NumPy")
        return
    err = np.real(x_hw) - np.real(x_ref)
    n = np.arange(len(err))
    ax.plot(n, err, color="#ea580c", linewidth=0.8)
    ax.set_title("Erro  (FPGA − NumPy),  max abs = %.4g"
                 % float(np.max(np.abs(err))), fontsize=9)
    ax.set_xlabel("n")
    ax.set_ylabel("erro")
    ax.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
    theme.style_plot_axes(ax)


class IFFTWindow(tk.Toplevel):
    """IFFT na FPGA a partir de um espectro lido de arquivo."""

    def __init__(self, master):
        super().__init__(master)
        self.title("Morphe — IFFT (espectro de arquivo → FPGA)")
        self.configure(bg=theme.COLORS["bg"])
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry("%dx%d" % (min(1180, sw - 80), min(860, sh - 80)))
        self.minsize(900, 560)

        theme.setup_styles(self)

        self.X: Optional[np.ndarray] = None
        self.x_hw: Optional[np.ndarray] = None
        self.x_ref: Optional[np.ndarray] = None
        self.fs: float = 1.0
        self.origem: str = ""
        self.n_uteis: Optional[int] = None
        self.escala: Optional[float] = None
        self._popouts: dict = {}

        self.status = tk.StringVar(value="Pronto. Abra um arquivo .mrph "
                                         "com o espectro.")
        theme.make_status_bar(self, self.status).pack(side="bottom", fill="x")

        root = ttk.Frame(self, style="Main.TFrame", padding=12)
        root.pack(fill="both", expand=True)

        lado = ttk.Frame(root, style="Main.TFrame")
        lado.pack(side="left", fill="y", padx=(0, 12))
        self._build_sidebar(lado)

        plots = ttk.Frame(root, style="Main.TFrame")
        plots.pack(side="right", fill="both", expand=True)
        self._build_plots(plots)

    # ------------------------------------------------------------------
    def _build_sidebar(self, parent):
        arq = ttk.LabelFrame(parent, text=" Espectro de entrada ",
                             style="Card.TLabelframe",
                             padding=(14, 12, 14, 14))
        arq.pack(fill="x")
        ttk.Label(arq,
                  text="Um .mrph com seção complexa — o X[k] salvo pela "
                       "tela da FFT serve direto.",
                  style="SectionHint.TLabel",
                  wraplength=300, justify="left").pack(anchor="w",
                                                       pady=(0, 8))
        ttk.Button(arq, text="Abrir arquivo .mrph…",
                   style="Primary.TButton",
                   command=self._on_abrir).pack(fill="x")

        self.var_arquivo = tk.StringVar(value="(nenhum)")
        ttk.Label(arq, textvariable=self.var_arquivo, style="Card.TLabel",
                  wraplength=300, justify="left",
                  font=("TkFixedFont", 8)).pack(anchor="w", pady=(8, 0))

        # Escolha da seção: um bundle pode ter mais de uma seção complexa.
        self.var_secao = tk.StringVar()
        self.cbo_secao = ttk.Combobox(arq, textvariable=self.var_secao,
                                      state="disabled", values=[])
        self.cbo_secao.pack(fill="x", pady=(8, 0))
        self.cbo_secao.bind("<<ComboboxSelected>>",
                            lambda e: self._on_secao_change())

        op = ttk.LabelFrame(parent, text=" IFFT na FPGA ",
                            style="Card.TLabelframe",
                            padding=(14, 12, 14, 14))
        op.pack(fill="x", pady=(12, 0))
        self.btn_ifft = ttk.Button(op, text="Calcular IFFT na FPGA",
                                   style="Primary.TButton",
                                   command=self._on_ifft, state="disabled")
        self.btn_ifft.pack(fill="x", pady=(0, 4))
        self.btn_salvar = ttk.Button(op, text="Salvar (X, x reconstruído) "
                                              "em .mrph",
                                     style="Secondary.TButton",
                                     command=self._on_salvar,
                                     state="disabled")
        self.btn_salvar.pack(fill="x")

        cmp_box = ttk.LabelFrame(parent, text=" FPGA × NumPy ",
                                 style="Card.TLabelframe",
                                 padding=(14, 12, 14, 14))
        cmp_box.pack(fill="x", pady=(12, 0))
        self.var_metricas = tk.StringVar(value="(rode a IFFT)")
        ttk.Label(cmp_box, textvariable=self.var_metricas,
                  style="Card.TLabel", justify="left",
                  font=("TkFixedFont", 8)).pack(anchor="w")

    def _build_plots(self, parent):
        header = theme.make_plot_header_bar(
            parent,
            items=[
                ("|X[k]| de entrada",   lambda: self._popout("X")),
                ("x[n] reconstruído",   lambda: self._popout("x")),
                ("Erro",                lambda: self._popout("erro")),
            ],
        )
        header.pack(fill="x", pady=(0, 6))

        self.fig = Figure(figsize=(7.4, 7.6), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        self.ax_X = self.fig.add_subplot(311)
        self.ax_x = self.fig.add_subplot(312)
        self.ax_e = self.fig.add_subplot(313)
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.toolbar = PlotToolbar(self.canvas)
        self._redraw()

    # ------------------------------------------------------------------
    def _redraw(self):
        _plot_espectro(self.ax_X, self.X, self.fs)
        _plot_reconstruido(self.ax_x, self.x_hw, self.x_ref, self.n_uteis)
        _plot_erro(self.ax_e, self.x_hw, self.x_ref)
        self.fig.tight_layout()
        self.canvas.draw_idle()
        refresh_all(self._popouts)

    def _popout(self, qual: str):
        if qual == "X" and self.X is None:
            messagebox.showwarning("Atenção", "Abra o espectro antes.")
            return
        if qual in ("x", "erro") and self.x_hw is None:
            messagebox.showwarning("Atenção", "Rode a IFFT antes.")
            return

        def draw(fig: Figure):
            ax = fig.add_subplot(111)
            if qual == "X":
                _plot_espectro(ax, self.X, self.fs)
            elif qual == "x":
                _plot_reconstruido(ax, self.x_hw, self.x_ref, self.n_uteis)
            else:
                _plot_erro(ax, self.x_hw, self.x_ref)

        titulos = {"X": "|X[k]|", "x": "x[n] reconstruído", "erro": "Erro"}
        open_or_focus(self._popouts, key="ifft_" + qual, parent=self,
                      title="Morphe — " + titulos[qual],
                      draw_fn=draw, size="1000x600")

    # ------------------------------------------------------------------
    def _on_abrir(self):
        path = filedialog.askopenfilename(
            title="Abrir bundle .mrph com o espectro",
            filetypes=[("Morphe bundle", "*.mrph"), ("Todos", "*.*")])
        if not path:
            return
        try:
            bundle = dsp.parse_mrph_bundle(path)
        except Exception as e:
            messagebox.showerror("Erro ao abrir", str(e))
            return

        complexas = [s["name"] for s in bundle["sections"]
                     if np.iscomplexobj(np.asarray(s["data"]))]
        if not complexas:
            messagebox.showerror(
                "Sem espectro",
                "Nenhuma seção complexa neste arquivo.\n\n"
                "A IFFT precisa de X[k], que tem parte real e imaginária. "
                "Seções encontradas: %s"
                % ", ".join(s["name"] for s in bundle["sections"]))
            return

        self._bundle = bundle
        self.origem = path
        self.var_arquivo.set(os.path.basename(path) +
                             "\ntítulo: " + bundle.get("title", "?"))
        self.cbo_secao.configure(values=complexas, state="readonly")
        # "X" e o nome que a tela da FFT usa; se existir, e a escolha obvia.
        self.var_secao.set("X" if "X" in complexas else complexas[0])
        self._on_secao_change()

    def _on_secao_change(self):
        sec = dsp.section_by_name(self._bundle, self.var_secao.get())
        X = np.asarray(sec["data"], dtype=np.complex128)

        if len(X) != cfg.FFT_N:
            messagebox.showerror(
                "Tamanho incompatível",
                "O hardware faz IFFT de exatamente %d pontos, e esta seção "
                "tem %d.\n\nUm espectro não pode ser preenchido com zeros "
                "como um sinal no tempo: isso mudaria o sinal que ele "
                "representa." % (cfg.FFT_N, len(X)))
            self.btn_ifft.configure(state="disabled")
            return

        self.X = X
        self.fs = float(sec.get("fs") or 1.0)
        self.x_hw = None
        self.x_ref = None
        self.n_uteis = None
        # Quantas amostras do resultado sao sinal e quantas sao padding: se
        # o bundle guardou o x[n] original, da para marcar no grafico.
        try:
            self.n_uteis = int(len(dsp.section_by_name(self._bundle,
                                                       "x")["data"]))
        except KeyError:
            self.n_uteis = None

        self.btn_ifft.configure(state="normal")
        self.btn_salvar.configure(state="disabled")
        self.var_metricas.set("(rode a IFFT)")
        self.status.set("Espectro '%s' carregado: %d bins."
                        % (self.var_secao.get(), len(X)))
        self._redraw()

    # ------------------------------------------------------------------
    def _on_ifft(self):
        if self.X is None:
            return
        try:
            client = self.master.tcp_panel.make_client()
        except Exception as e:
            messagebox.showerror("Configuração", str(e))
            return

        X = self.X
        self.btn_ifft.configure(state="disabled")
        self.status.set("Mandando o espectro à FPGA (inverse=1)...")

        def worker():
            try:
                req, escala = build_ifft_request(X)
                resp = client.request(req)
                x_hw = decode_ifft_response(resp, escala)
                self.after(0, lambda: self._on_ifft_done(x_hw, escala))
            except Exception as e:
                self.after(0, lambda err=e: self._on_ifft_erro(err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_ifft_done(self, x_hw: np.ndarray, escala: float):
        self.x_hw = x_hw
        self.x_ref = np.fft.ifft(self.X)
        self.escala = escala
        self.btn_ifft.configure(state="normal")
        self.btn_salvar.configure(state="normal")

        m = dsp.compute_error_metrics(np.real(x_hw), np.real(self.x_ref))
        vaz = float(np.max(np.abs(np.imag(x_hw))))
        pico = float(np.max(np.abs(np.real(self.x_ref))))
        self.var_metricas.set(
            "erro máx:   %.4g\n"
            "erro rms:   %.4g\n"
            "SNR:        %.2f dB\n"
            "vazamento:  %.4g  (imag)\n"
            "escala Q15.8: %.6g" %
            (m["max_abs_error"], m["rms_error"], m["snr_db"], vaz,
             escala))
        self.status.set(
            "IFFT OK. Erro máximo contra o NumPy: %.3e (pico do sinal: %.3g)"
            % (m["max_abs_error"], pico))
        self._redraw()

    def _on_ifft_erro(self, err: Exception):
        self.btn_ifft.configure(state="normal")
        messagebox.showerror("Erro na IFFT", str(err))
        self.status.set("Erro — ver mensagem.")

    # ------------------------------------------------------------------
    def _on_salvar(self):
        if self.x_hw is None:
            return
        path = filedialog.asksaveasfilename(
            title="Salvar resultado da IFFT",
            defaultextension=".mrph",
            initialfile="ifft_bundle.mrph",
            filetypes=[("Morphe", "*.mrph"), ("Todos", "*.*")])
        if not path:
            return
        N = len(self.X)
        try:
            dsp.save_mrph_bundle(
                path, title="Morphe IFFT",
                sections=[
                    {"name": "X", "kind": "complex",
                     "n": np.arange(N, dtype=np.int64), "data": self.X,
                     "description": "X[k] de entrada — %s"
                                    % os.path.basename(self.origem),
                     "fs": self.fs},
                    {"name": "x_ifft", "kind": "complex",
                     "n": np.arange(len(self.x_hw), dtype=np.int64),
                     "data": self.x_hw,
                     "description": "x[n] = IFFT(X) na FPGA",
                     "fs": self.fs},
                ])
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e))
            return
        messagebox.showinfo("Salvo", "Arquivo gravado:\n%s\n\nAbra no "
                                     "Comparador para conferir contra o "
                                     "NumPy." % path)
        self.status.set("Salvo em " + os.path.basename(path))
