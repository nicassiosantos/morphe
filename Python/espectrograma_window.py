"""
espectrograma_window.py -- espectrograma (STFT) de um sinal longo, com a FFT
da FPGA.

A janela da FFT mostra o espectro do sinal INTEIRO: diz quais frequencias
existem, mas nao quando. O espectrograma corta o sinal em quadros de 1024
amostras, aplica uma janela (Hann, por padrao) a cada um, calcula a FFT de
cada quadro na placa e poe os espectros lado a lado: o eixo horizontal e o
tempo, o vertical e a frequencia, a cor e a magnitude. Uma varredura de
frequencia aparece como uma rampa; dois tons fixos, como duas linhas.

Os quadros se sobrepoem (50 % por padrao): com a janela de Hann, que zera as
pontas, e o que evita que um evento curto caia justo na borda de dois quadros
e suma. O preco da resolucao e a incerteza: quadro de 1024 amostras a 8 kHz
tem resolucao de 7,8 Hz na frequencia e de 128 ms no tempo.

Embaixo, o espectro medio dos quadros (metodo de Welch): o espectro do sinal
inteiro com menos variancia que uma FFT so.

Tudo e conferido contra o mesmo calculo com np.fft: a diferenca e so a
quantizacao Q15.8 da FFT da placa (blocos.espectrograma, blocos.FftPlaca).
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import numpy as np

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import blocos
import dsp_core as dsp
import morphe_theme as theme
from plot_toolbar import PlotToolbar
from popout_helper import open_or_focus, refresh_all
from signal_panel import SignalPanel

N_FFT = dsp.MAX_FFT_INPUT_SIZE
JANELAS = ("Hann", "Hamming", "Retangular")
SOBREPOSICOES = {"50 %": N_FFT // 2, "75 %": N_FFT // 4, "0 % (sem)": N_FFT}
FAIXA_DB = 80.0          # a imagem mostra os 80 dB abaixo do pico
_COLOR_NUMPY = "#dc2626"


def _db(v: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.abs(v) + 1e-12)


def _desenha_x(ax, sig: Optional[dsp.Signal]):
    ax.clear()
    if sig is None:
        theme.draw_empty_axes(ax, "x[n] — gere ou carregue um sinal")
        return
    t = np.arange(sig.x.size) / sig.fs
    ax.plot(t, sig.x, color=dsp.COLOR_X, linewidth=0.7)
    ax.set_title(f"x[n]  —  {sig.description}", fontsize=9)
    ax.set_xlabel("t (s)" if sig.fs != 1.0 else "n")
    ax.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
    ax.set_xlim(t[0], t[-1] if t.size > 1 else 1)
    theme.style_plot_axes(ax)


def _desenha_espectrograma(ax, fig, res: Optional[dict], db: bool):
    ax.clear()
    if res is None:
        theme.draw_empty_axes(ax, "Espectrograma\n(calcule na FPGA)")
        return None
    fs = res["fs"]
    X = res["X"][:, :N_FFT // 2 + 1]
    S = _db(X) if db else np.abs(X)
    t_ini = res["inicios"][0] / fs
    t_fim = (res["inicios"][-1] + N_FFT) / fs
    if db:
        vmax = float(S.max())
        vmin = vmax - FAIXA_DB
    else:
        vmin, vmax = 0.0, float(S.max())
    im = ax.imshow(S.T, origin="lower", aspect="auto", cmap="viridis",
                   extent=[t_ini, t_fim, 0.0, fs / 2], vmin=vmin, vmax=vmax,
                   interpolation="nearest")
    ax.set_title(f"Espectrograma — {X.shape[0]} quadros de {N_FFT}, janela "
                 f"{res['janela']}, salto {res['salto']}  (FFT na FPGA)",
                 fontsize=9)
    ax.set_xlabel("t (s)" if fs != 1.0 else "n")
    ax.set_ylabel("f (Hz)" if fs != 1.0 else "f (ciclos/amostra)")
    theme.style_plot_axes(ax)
    cb = fig.colorbar(im, ax=ax, pad=0.01)
    cb.set_label("|X| (dB)" if db else "|X|", fontsize=8)
    return cb


def _desenha_medio(ax, res: Optional[dict], db: bool):
    ax.clear()
    if res is None:
        theme.draw_empty_axes(ax, "Espectro médio dos quadros (Welch)")
        return
    fs = res["fs"]
    k = np.arange(N_FFT // 2 + 1)
    f = k * fs / N_FFT
    p_hw = blocos.espectro_medio(res["X"], res["janela"])[:k.size]
    p_np = blocos.espectro_medio(res["X_ref"], res["janela"])[:k.size]
    if db:
        ax.plot(f, 10 * np.log10(p_hw + 1e-24), color=dsp.COLOR_MAG,
                linewidth=1.0, label="FPGA")
        ax.plot(f, 10 * np.log10(p_np + 1e-24), color=_COLOR_NUMPY,
                linewidth=0.8, linestyle="--", alpha=0.8, label="NumPy (ref)")
        ax.set_ylabel("potência (dB)")
    else:
        ax.plot(f, p_hw, color=dsp.COLOR_MAG, linewidth=1.0, label="FPGA")
        ax.plot(f, p_np, color=_COLOR_NUMPY, linewidth=0.8, linestyle="--",
                alpha=0.8, label="NumPy (ref)")
        ax.set_ylabel("potência")
    ax.set_title("Espectro médio dos quadros (Welch)", fontsize=9)
    ax.set_xlabel("f (Hz)" if fs != 1.0 else "f (ciclos/amostra)")
    ax.set_xlim(0, fs / 2)
    ax.legend(fontsize=7, loc="upper right")
    theme.style_plot_axes(ax)


class EspectrogramaWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Morphe — Espectrograma via FPGA (TCP)")
        self.geometry("1320x860")
        self.configure(bg=theme.COLORS["bg"])
        theme.setup_styles(self)

        self.x_sig: Optional[dsp.Signal] = None
        self.res: Optional[dict] = None
        self._cbar = None
        self._popouts: dict = {}

        self.status = tk.StringVar(value="Pronto. Carregue um sinal longo — "
                                         "exemplos/sinais/varredura_8k.wav.")
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
        sec = theme.CollapsibleSection(parent, title="Como funciona",
                                       expanded=False)
        sec.pack(fill="x", pady=(0, 6))
        theme.make_banner(
            sec.body, kind="info", wraplength=320,
            text=(f"• O sinal é cortado em quadros de {N_FFT} amostras, "
                  "janelados e sobrepostos\n"
                  f"• Cada quadro é uma FFT de {N_FFT} pontos na FPGA\n"
                  "• Horizontal: tempo; vertical: frequência; cor: magnitude\n"
                  f"• Resolução: fs/{N_FFT} na frequência, {N_FFT}/fs no tempo\n"
                  "• Embaixo, a média dos quadros (Welch)"),
        ).pack(fill="x")

        self.x_panel = SignalPanel(
            parent, title="Sinal x[n]", on_generate=self._on_gen_x,
            default_N=8192, default_type="Arquivo",
            max_N=N_FFT, aceita_longo=True)
        self.x_panel.pack(fill="x", pady=(6, 0))

        op = ttk.LabelFrame(parent, text=" Espectrograma ",
                            style="Card.TLabelframe", padding=(14, 12, 14, 14))
        op.pack(fill="x", pady=(12, 0))

        linha = ttk.Frame(op, style="Card.TFrame")
        linha.pack(fill="x", pady=(0, 6))
        ttk.Label(linha, text="Janela", style="Card.TLabel",
                  width=12).pack(side="left")
        self.var_janela = tk.StringVar(value="Hann")
        ttk.Combobox(linha, textvariable=self.var_janela, values=JANELAS,
                     state="readonly", width=14).pack(side="left", fill="x",
                                                      expand=True)
        linha = ttk.Frame(op, style="Card.TFrame")
        linha.pack(fill="x", pady=(0, 6))
        ttk.Label(linha, text="Sobreposição", style="Card.TLabel",
                  width=12).pack(side="left")
        self.var_sobrep = tk.StringVar(value="50 %")
        ttk.Combobox(linha, textvariable=self.var_sobrep,
                     values=list(SOBREPOSICOES), state="readonly",
                     width=14).pack(side="left", fill="x", expand=True)

        self.var_norm = tk.BooleanVar(value=True)
        ttk.Checkbutton(op, text="Normalizar cada quadro (faixa cheia do Q15.8)",
                        variable=self.var_norm,
                        style="Card.TCheckbutton").pack(anchor="w", pady=(4, 2))
        self.var_db = tk.BooleanVar(value=True)
        ttk.Checkbutton(op, text="Magnitude em dB", variable=self.var_db,
                        command=self._redraw,
                        style="Card.TCheckbutton").pack(anchor="w", pady=(0, 10))

        self.btn_calc = ttk.Button(op, text="Calcular espectrograma na FPGA",
                                   style="Primary.TButton",
                                   command=self._on_calcular)
        self.btn_calc.pack(fill="x", pady=(0, 4))
        self.btn_salvar = ttk.Button(op, text="Salvar espectrograma (.npz)…",
                                     style="Secondary.TButton",
                                     command=self._on_salvar, state="disabled")
        self.btn_salvar.pack(fill="x")

        cmp_box = ttk.LabelFrame(parent, text=" FPGA × NumPy ",
                                 style="Card.TLabelframe",
                                 padding=(14, 12, 14, 14))
        cmp_box.pack(fill="x", pady=(12, 0))
        self.var_metricas = tk.StringVar(value="(calcule o espectrograma)")
        ttk.Label(cmp_box, textvariable=self.var_metricas, style="Card.TLabel",
                  justify="left", font=("TkFixedFont", 8)).pack(anchor="w")

    def _build_plots(self, parent):
        header = theme.make_plot_header_bar(parent, items=[
            ("x[n]",            lambda: self._popout("x")),
            ("Espectrograma",   lambda: self._popout("S")),
            ("Espectro médio",  lambda: self._popout("W")),
        ])
        header.pack(fill="x", pady=(0, 6))
        self.fig = Figure(figsize=(7.4, 8.6), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        gs = self.fig.add_gridspec(3, 1, height_ratios=[1, 2.2, 1.2])
        self.ax_x = self.fig.add_subplot(gs[0])
        self.ax_S = self.fig.add_subplot(gs[1])
        self.ax_W = self.fig.add_subplot(gs[2])
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.toolbar = PlotToolbar(self.canvas)

    # ------------------------------------------------------------------
    def _redraw(self):
        if self._cbar is not None:
            self._cbar.remove()
            self._cbar = None
        db = bool(self.var_db.get())
        _desenha_x(self.ax_x, self.x_sig)
        self._cbar = _desenha_espectrograma(self.ax_S, self.fig, self.res, db)
        _desenha_medio(self.ax_W, self.res, db)
        self.fig.tight_layout()
        self.canvas.draw_idle()
        refresh_all(self._popouts)

    def _popout(self, qual: str):
        if qual == "x" and self.x_sig is None:
            messagebox.showwarning("Atenção", "Carregue x[n] antes.")
            return
        if qual in ("S", "W") and self.res is None:
            messagebox.showwarning("Atenção", "Calcule o espectrograma antes.")
            return

        def draw(fig: Figure):
            ax = fig.add_subplot(111)
            db = bool(self.var_db.get())
            if qual == "x":
                _desenha_x(ax, self.x_sig)
            elif qual == "S":
                _desenha_espectrograma(ax, fig, self.res, db)
            else:
                _desenha_medio(ax, self.res, db)

        titulos = {"x": "x[n]", "S": "Espectrograma", "W": "Espectro médio"}
        open_or_focus(self._popouts, key="esp_" + qual, parent=self,
                      title="Morphe — " + titulos[qual], draw_fn=draw,
                      size="1100x650")

    # ------------------------------------------------------------------
    def _on_gen_x(self, panel: SignalPanel):
        try:
            self.x_sig = panel.build()
        except Exception as e:
            messagebox.showerror("Erro em x[n]", str(e))
            return
        self.res = None
        self.btn_salvar.configure(state="disabled")
        self.var_metricas.set("(calcule o espectrograma)")
        self._redraw()
        self.status.set(f"x[n]: {self.x_sig.description}")

    def _on_calcular(self):
        if self.x_sig is None:
            messagebox.showwarning("Atenção", "Gere ou carregue x[n] antes.")
            return
        try:
            client = self.master.tcp_panel.make_client()
        except Exception as e:
            messagebox.showerror("Configuração", str(e))
            return

        x = np.asarray(self.x_sig.x, dtype=np.float64)
        fs = float(self.x_sig.fs)
        janela = self.var_janela.get()
        salto = SOBREPOSICOES[self.var_sobrep.get()]
        normalizar = bool(self.var_norm.get())
        n_quadros = 1 + max(0, int(np.ceil((x.size - N_FFT) / salto)))
        self.btn_calc.configure(state="disabled")
        self.status.set(f"{n_quadros} quadros de {N_FFT}, enviando à FPGA...")

        def progresso(feitos, total):
            self.after(0, lambda: self.status.set(
                f"Quadro {feitos} de {total} na FPGA..."))

        def worker():
            try:
                inicios, X = blocos.espectrograma(
                    x, blocos.FftPlaca(client, normalizar), N_FFT, salto,
                    janela, progresso)
                _, X_ref = blocos.espectrograma(x, np.fft.fft, N_FFT, salto,
                                                janela)
                res = {"inicios": inicios, "X": X, "X_ref": X_ref, "fs": fs,
                       "janela": janela, "salto": salto}
                self.after(0, lambda: self._on_pronto(res))
            except Exception as e:
                self.after(0, lambda err=e: self._on_erro(err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_pronto(self, res: dict):
        self.res = res
        self.btn_calc.configure(state="normal")
        self.btn_salvar.configure(state="normal")
        X, R = res["X"], res["X_ref"]
        erro = np.sum(np.abs(X - R) ** 2)
        snr = (float("inf") if erro == 0
               else 10 * np.log10(np.sum(np.abs(R) ** 2) / erro))
        meio = N_FFT // 2
        picos_iguais = np.mean(np.argmax(np.abs(X[:, :meio]), axis=1)
                               == np.argmax(np.abs(R[:, :meio]), axis=1))
        fs = res["fs"]
        self.var_metricas.set(
            "quadros:          %d\n"
            "resolução em f:   %.4g Hz\n"
            "resolução em t:   %.4g s\n"
            "SNR:              %.2f dB\n"
            "pico no mesmo bin: %.0f %% dos quadros"
            % (X.shape[0], fs / N_FFT, N_FFT / fs, snr, 100 * picos_iguais))
        self.status.set("OK. %d quadros de %d, FFT na FPGA; %.1f dB contra o "
                        "mesmo espectrograma com o NumPy."
                        % (X.shape[0], N_FFT, snr))
        self._redraw()

    def _on_erro(self, err: Exception):
        self.btn_calc.configure(state="normal")
        messagebox.showerror("Erro no espectrograma", str(err))
        self.status.set("Erro — ver mensagem.")

    def _on_salvar(self):
        if self.res is None:
            return
        path = filedialog.asksaveasfilename(
            title="Salvar espectrograma", defaultextension=".npz",
            initialfile="espectrograma.npz",
            filetypes=[("NumPy (.npz)", "*.npz"), ("Todos", "*.*")])
        if not path:
            return
        r = self.res
        try:
            np.savez(path, x=self.x_sig.x, fs=r["fs"], inicios=r["inicios"],
                     X_fpga=r["X"], X_numpy=r["X_ref"], janela=r["janela"],
                     salto=r["salto"], n_fft=N_FFT)
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e))
            return
        self.status.set(f"Salvo em {path}")
