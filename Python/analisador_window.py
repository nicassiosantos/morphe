"""
analisador_window.py -- janela "Analisador espectral": o sinal do ADC passando
pela FFT da FPGA, quadro a quadro, até o usuário clicar em Parar.

Cada quadro é um ciclo completo na placa:
  1. o ADC captura N amostras à fs escolhida (OP_ADC, o instante de cada
     amostra dado pelo hardware);
  2. no PC: tira o nível DC (se pedido) e aplica a janela;
  3. a FPGA calcula a FFT (OP_FFT, 1024 pontos; N maior vira a FFT longa em
     quatro passos, N/1024 FFTs na placa);
  4. a tela mostra o quadro no tempo e o espectro completo (os N bins, de 0
     a fs) em volts de pico, escala linear, com o pico marcado.
Ao lado, o NumPy calcula a mesma FFT do mesmo x[n] janelado, e a tela mostra
quanto as duas concordam: é a prova, a cada quadro, de que o espectro saiu
mesmo da FPGA e com que precisão.

Captura e FFT são pedidos separados, como os de qualquer janela: entre um
quadro e o próximo a placa atende quem mais estiver na fila. O último quadro
pode ser salvo em .mrph e aberto no Comparador.
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

import numpy as np

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import aquisicao as aq
import blocos
import dsp_core as dsp
import morphe_theme as theme
from aquisicao_window import COMO_LIGAR, MODOS
from plot_toolbar import PlotToolbar

# Pontos da FFT: 1024 é uma FFT da placa; acima, a FFT longa em quatro passos.
PONTOS = {"1024  (1 FFT na FPGA)": 1024,
          "4096  (4 FFTs na FPGA)": 4096,
          "16384  (16 FFTs na FPGA)": 16384}

# Hann e Blackman-Harris separam bem tons vizinhos, mas a amplitude de um tom
# que cai entre dois bins sai até 1,4 dB (Hann) ou 0,8 dB (B-H) abaixo; a
# retangular perde até 3,9 dB. A flat-top erra menos de 0,02 dB em qualquer
# frequência, ao custo de um pico mais largo: é a janela de medir amplitude.
JANELAS = ("Hann", "Blackman-Harris", "Flat-top (medir amplitude)", "Retangular")
_FLAT_TOP = (0.21557895, 0.41663158, 0.277263158, 0.083578947, 0.006947368)

MEDIA_NENHUMA = "Sem média"
MEDIA_PICO = "Retenção de pico"
MEDIAS = {MEDIA_NENHUMA: 1, "Média de 4 quadros": 4, "Média de 16 quadros": 16,
          MEDIA_PICO: 0}

# A tela confere se há quadro novo a cada TELA_MS.
TELA_MS = 50
# Eixo vertical do espectro: volts de pico, linear, de 0 até um pouco acima
# do maior bin do quadro (no mínimo AMP_MIN, para o ruído não encher a tela).
AMP_MIN = 0.01
# Bins em volta de f = 0 que não contam na busca do pico (o que sobra do DC).
BINS_DC = 3


def janela(nome: str, n: int) -> np.ndarray:
    if nome == "Hann":
        return np.hanning(n + 1)[:n]            # periódica: soma exata n/2
    if nome == "Blackman-Harris":
        return aq.janela_bh(n)
    if nome.startswith("Flat-top"):
        k = np.arange(n) * (2.0 * np.pi / n)
        return sum((-1) ** i * a * np.cos(i * k) for i, a in enumerate(_FLAT_TOP))
    return np.ones(n)


def processar_quadro(volts: np.ndarray, fs: float, nome_janela: str,
                     tirar_dc: bool,
                     fft: Callable[[np.ndarray], np.ndarray]) -> dict:
    """Um quadro, da captura ao espectro. `fft` é quem calcula a FFT de
    len(volts) pontos (a da placa, na janela; a do NumPy, nos testes).

    Devolve o x enviado à FFT, o X[k] que voltou, o espectro completo em
    volts de pico (os N bins, f de 0 a fs), o pico, e a concordância com o
    NumPy.
    """
    x = np.asarray(volts, dtype=np.float64)
    n = x.size
    dc = float(np.mean(x))
    w = janela(nome_janela, n)
    x_env = ((x - dc) if tirar_dc else x) * w
    t0 = time.monotonic()
    X = np.asarray(fft(x_env))
    t_fft = time.monotonic() - t0

    # amplitude de pico de uma senoide: |X[k]| / (soma da janela / 2). O tom
    # aparece duas vezes, em f e em fs - f, e as duas linhas leem a mesma
    # amplitude. O DC (k = 0) aparece uma vez só: ali o ganho é a soma inteira.
    ganho = np.sum(w) / 2.0
    amp = np.abs(X) / ganho
    amp[0] /= 2.0
    f = np.arange(n) * fs / n

    # o pico se procura na metade de baixo (a de cima é o espelho); a
    # frequência sai da parábola em dB, que se ajusta bem ao lóbulo da janela
    db = 20.0 * np.log10(np.maximum(amp[: n // 2 + 1], 1e-12))
    busca = db.copy()
    busca[:BINS_DC] = -np.inf
    k = int(np.argmax(busca))
    # frequência pela parábola nos três bins em volta do pico (em dB): melhor
    # que o bin inteiro, que erra até meio bin
    f_pico = f[k]
    if 0 < k < db.size - 1:
        a, b, c = db[k - 1], db[k], db[k + 1]
        den = a - 2 * b + c
        if den < 0:
            # no máximo meio bin: perto do DC, ou só com ruído, a parábola
            # pode apontar longe (e até para f < 0)
            f_pico = (k + float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))) * fs / n

    ref = np.fft.fft(x_env)
    erro = float(np.linalg.norm(X - ref))
    snr = (float("inf") if erro == 0.0
           else 20.0 * np.log10(float(np.linalg.norm(ref)) / erro))
    return {"x": x, "x_env": x_env, "X": X, "f": f, "amp": amp,
            "k_pico": k, "f_pico": float(f_pico), "amp_pico": float(amp[k]),
            "dc": dc, "t_fft": t_fft, "snr_numpy": snr, "fs": fs, "n": n}


class AnalisadorWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Morphe — Analisador espectral (ADC → FFT na FPGA)")
        self.geometry("1240x820")
        self.configure(bg=theme.COLORS["bg"])
        theme.setup_styles(self)

        self._parar: Optional[threading.Event] = None
        self._trava_q = threading.Lock()
        self._novo: Optional[dict] = None       # último quadro, ainda não desenhado
        self._ultimo: Optional[dict] = None     # último quadro desenhado
        self._acum: Optional[np.ndarray] = None  # média / pico em amplitude²
        self._fila: list = []
        self._n_quadros = 0
        self._inicio = 0.0
        # O que a thread da análise lê a cada quadro. Só a thread do Tk escreve
        # (em _zera_media); variáveis do Tk não podem ser lidas de outra thread.
        self._cfg = {"janela": JANELAS[0], "dc": True}
        self.protocol("WM_DELETE_WINDOW", self._on_fechar)

        self.status = tk.StringVar(value="Pronto. Ligue o sinal no ADC (ver “Como "
                                         "ligar”) e clique em Iniciar.")
        theme.make_status_bar(self, self.status).pack(side="bottom", fill="x")

        root = ttk.Frame(self, style="Main.TFrame", padding=12)
        root.pack(fill="both", expand=True)
        lado = ttk.Frame(root, style="Main.TFrame")
        lado.pack(side="left", fill="y", padx=(0, 12))
        self._build_sidebar(lado)
        area = ttk.Frame(root, style="Main.TFrame")
        area.pack(side="right", fill="both", expand=True)
        self._build_plots(area)
        self._atualiza_info()

    # ------------------------------------------------------------------
    def _linha(self, parent, rotulo: str) -> ttk.Frame:
        linha = ttk.Frame(parent, style="Card.TFrame")
        linha.pack(fill="x", pady=(0, 6))
        ttk.Label(linha, text=rotulo, style="Card.TLabel", width=11).pack(side="left")
        return linha

    def _combo(self, parent, rotulo, var, valores, ao_mudar=None):
        cb = ttk.Combobox(self._linha(parent, rotulo), textvariable=var,
                          values=list(valores), state="readonly", width=24)
        cb.pack(side="left", fill="x", expand=True)
        if ao_mudar is not None:
            cb.bind("<<ComboboxSelected>>", lambda e: ao_mudar())
        return cb

    def _build_sidebar(self, parent):
        sec = theme.CollapsibleSection(parent, title="Como ligar", expanded=False)
        sec.pack(fill="x", pady=(0, 6))
        theme.make_banner(sec.body, kind="warn", wraplength=320,
                          text=COMO_LIGAR).pack(fill="x")

        ent = ttk.LabelFrame(parent, text=" Entrada ", style="Card.TLabelframe",
                             padding=(14, 12, 14, 10))
        ent.pack(fill="x", pady=(6, 0))
        self.var_modo = tk.StringVar(value=next(iter(MODOS)))
        self._combo(ent, "Modo", self.var_modo, MODOS, self._troca_modo)
        self.var_canal = tk.StringVar(value=aq.CANAIS_SIMPLES[0])
        self.cb_canal = self._combo(ent, "Canal", self.var_canal, aq.CANAIS_SIMPLES)

        an = ttk.LabelFrame(parent, text=" Análise ", style="Card.TLabelframe",
                            padding=(14, 12, 14, 14))
        an.pack(fill="x", pady=(12, 0))
        self.var_fs = tk.StringVar(value="10000")
        e = ttk.Entry(self._linha(an, "fs (Hz)"), textvariable=self.var_fs, width=12)
        e.pack(side="left", fill="x", expand=True)
        e.bind("<KeyRelease>", lambda ev: self._atualiza_info())
        self.var_pontos = tk.StringVar(value=next(iter(PONTOS)))
        self._combo(an, "Pontos", self.var_pontos, PONTOS, self._atualiza_info)
        self.var_janela = tk.StringVar(value=JANELAS[0])
        self._combo(an, "Janela", self.var_janela, JANELAS, self._zera_media)
        self.var_media = tk.StringVar(value=MEDIA_NENHUMA)
        self._combo(an, "Média", self.var_media, MEDIAS, self._zera_media)
        self.var_dc = tk.BooleanVar(value=True)
        ttk.Checkbutton(an, text="Tirar o nível DC antes da FFT", variable=self.var_dc,
                        command=self._zera_media,
                        style="Card.TCheckbutton").pack(anchor="w", pady=(0, 6))
        self.var_info = tk.StringVar()
        ttk.Label(an, textvariable=self.var_info, style="SectionHint.TLabel",
                  wraplength=300, justify="left").pack(anchor="w", pady=(0, 8))
        self.btn_iniciar = ttk.Button(an, text="Iniciar", style="Primary.TButton",
                                      command=self._on_iniciar)
        self.btn_iniciar.pack(fill="x", pady=(0, 4))
        self.btn_salvar = ttk.Button(an, text="Salvar quadro (.mrph)…",
                                     style="Secondary.TButton", state="disabled",
                                     command=self._on_salvar)
        self.btn_salvar.pack(fill="x")

        med = ttk.LabelFrame(parent, text=" Medidas do quadro ", style="Card.TLabelframe",
                             padding=(14, 10, 14, 12))
        med.pack(fill="x", pady=(12, 0))
        self.var_medidas = tk.StringVar(value="(inicie a análise)")
        ttk.Label(med, textvariable=self.var_medidas, style="Card.TLabel",
                  justify="left", font=("TkFixedFont", 8)).pack(anchor="w")

    def _build_plots(self, parent):
        self.fig = Figure(figsize=(7.4, 7.6), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        self.ax_t = self.fig.add_subplot(211)
        self.ax_f = self.fig.add_subplot(212)
        theme.draw_empty_axes(self.ax_t, "x(t) — o quadro que o ADC capturou")
        theme.draw_empty_axes(self.ax_f, "|X(f)| — calculado pela FFT da FPGA")
        self.fig.tight_layout()
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.toolbar = PlotToolbar(self.canvas)

    # ------------------------------------------------------------------
    def _modo_canal(self) -> tuple[str, int]:
        modo = MODOS[self.var_modo.get()]
        lista = aq.CANAIS_SIMPLES if modo == aq.MODO_SIMPLES else aq.PARES_DIFERENCIAIS
        return modo, lista.index(self.var_canal.get())

    def _troca_modo(self):
        modo = MODOS[self.var_modo.get()]
        lista = aq.CANAIS_SIMPLES if modo == aq.MODO_SIMPLES else aq.PARES_DIFERENCIAIS
        self.cb_canal.configure(values=lista)
        self.var_canal.set(lista[0])

    def _le_fs(self) -> float:
        try:
            fs = float(self.var_fs.get().replace(",", "."))
        except ValueError as e:
            raise ValueError("fs deve ser um número") from e
        aq.divisor_para(fs)                  # confere a faixa
        return fs

    def _atualiza_info(self):
        try:
            fs = self._le_fs()
        except ValueError as e:
            self.var_info.set(str(e))
            return
        fs_real = aq.fs_de(aq.divisor_para(fs))
        n = PONTOS[self.var_pontos.get()]
        self.var_info.set(
            f"fs real {fs_real:.3f} Hz · espectro de 0 a {fs_real:g} Hz\n"
            f"resolução {fs_real / n:.3g} Hz · quadro de {1e3 * n / fs_real:.4g} ms\n"
            "Acima de fs/2 é o espelho da metade de baixo. Sem filtro\n"
            "antialiasing: sinal acima de fs/2 na entrada volta como alias.")
        self._zera_media()

    def _zera_media(self):
        """Janela, DC ou média mudou: a média recomeça, e a análise em curso
        passa a usar as escolhas novas a partir do próximo quadro."""
        self._acum = None
        self._fila = []
        if hasattr(self, "var_dc"):
            self._cfg = {"janela": self.var_janela.get(), "dc": self.var_dc.get()}

    # ------------------------------------------------------------------
    def _on_iniciar(self):
        if self._parar is not None:
            return
        try:
            fs = self._le_fs()
            client = self.master.tcp_panel.make_client()
        except Exception as e:
            messagebox.showerror("Configuração", str(e))
            return
        modo, canal = self._modo_canal()
        n = PONTOS[self.var_pontos.get()]
        fs_real = aq.fs_de(aq.divisor_para(fs))
        parar = threading.Event()
        self._parar = parar
        self._zera_media()                   # também fixa self._cfg
        self._n_quadros = 0
        self._inicio = time.monotonic()
        self._prepara_graficos(n, fs_real, modo)
        self.btn_iniciar.configure(text="Parar", command=self._on_parar)
        self.status.set(f"Analisando {n} pontos a {fs_real:g} Hz: captura no ADC, "
                        "FFT na FPGA, quadro a quadro. Clique em Parar para encerrar.")
        fft_placa = blocos.FftPlaca(client, normalizar=True)

        def fft(x):
            return blocos.fft_longa(x, fft_placa) if x.size > dsp.MAX_FFT_INPUT_SIZE \
                else fft_placa(x)

        def worker():
            try:
                while not parar.is_set():
                    t0 = time.monotonic()
                    cap = aq.capturar(client, n, fs, modo, canal, guardar=False)
                    t_cap = time.monotonic() - t0
                    cfg = self._cfg
                    q = processar_quadro(cap.volts, cap.fs, cfg["janela"], cfg["dc"], fft)
                    q["janela"], q["tirou_dc"] = cfg["janela"], cfg["dc"]
                    q["t_cap"] = t_cap
                    q["saturou"] = aq.saturou(cap)
                    q["entrada"] = cap.nome_entrada
                    with self._trava_q:
                        self._novo = q
                self.after(0, self._on_parado)
            except Exception as e:
                self.after(0, lambda err=e: self._on_erro(err))

        threading.Thread(target=worker, daemon=True).start()
        self.after(TELA_MS, self._tela)

    def _on_parar(self):
        if self._parar is not None:
            self._parar.set()
            self.btn_iniciar.configure(state="disabled", text="Parando...")

    def _on_parado(self):
        self._parar = None
        self.btn_iniciar.configure(state="normal", text="Iniciar", command=self._on_iniciar)
        seg = time.monotonic() - self._inicio
        self.status.set(f"Parado: {self._n_quadros} quadros em {seg:.0f} s. A tela "
                        "mostra o último; “Salvar quadro” o leva ao Comparador.")

    def _on_erro(self, err: Exception):
        self._parar = None
        self.btn_iniciar.configure(state="normal", text="Iniciar", command=self._on_iniciar)
        self.status.set("Erro — ver mensagem.")
        messagebox.showerror("Erro no analisador", str(err))

    def _on_fechar(self):
        if self._parar is not None:
            self._parar.set()        # a placa fica livre para os outros
        self.destroy()

    # --- tela -----------------------------------------------------------
    def _prepara_graficos(self, n: int, fs: float, modo: str):
        self._esc_t, un_t = (1e3, "ms") if n / fs < 2.0 else (1.0, "s")
        self._esc_f, self._un_f = (1e-3, "kHz") if fs >= 2000 else (1.0, "Hz")
        ax = self.ax_t
        ax.clear()
        (self._l_t,) = ax.plot([], [], color=dsp.COLOR_X, linewidth=0.8)
        ax.set_xlim(0, n / fs * self._esc_t)
        ax.set_ylim(*((-0.1, 4.2) if modo == aq.MODO_SIMPLES else (-2.15, 2.15)))
        ax.set_xlabel(f"t ({un_t})")
        ax.set_ylabel("tensão (V)")
        theme.style_plot_axes(ax)
        ax = self.ax_f
        ax.clear()
        (self._l_f,) = ax.plot([], [], color=dsp.COLOR_MAG, linewidth=0.8)
        (self._p_f,) = ax.plot([], [], "v", color=dsp.COLOR_PHASE, markersize=7)
        self._txt_pico = ax.text(0.99, 0.95, "", transform=ax.transAxes, ha="right",
                                 va="top", fontsize=9, color=theme.COLORS["text"])
        ax.axvline(fs / 2 * self._esc_f, color=theme.COLORS["axis"], linewidth=0.8,
                   linestyle=":")
        ax.text(fs / 2 * self._esc_f, 0.98, " fs/2", transform=ax.get_xaxis_transform(),
                ha="left", va="top", fontsize=8, color=theme.COLORS["text"])
        ax.set_xlim(0, fs * self._esc_f)
        ax.set_ylim(0, AMP_MIN)
        ax.set_xlabel(f"f ({self._un_f})")
        ax.set_ylabel("amplitude (V de pico)")
        theme.style_plot_axes(ax)
        # títulos provisórios antes do tight_layout: ele reserva o espaço deles,
        # e os títulos de verdade (a cada quadro) cabem sem encostar na borda
        self.ax_t.set_title("x(t)", fontsize=9)
        self.ax_f.set_title("|X(f)|", fontsize=9)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _acumula(self, q: dict) -> np.ndarray:
        """O espectro a mostrar, em amplitude: o do quadro, a média de
        potência dos últimos K, ou o máximo desde o começo."""
        p = q["amp"] ** 2
        k = MEDIAS[self.var_media.get()]
        if k == 1:
            self._zera_media()
            return q["amp"]
        if self._acum is not None and self._acum.shape != p.shape:
            self._zera_media()
        if k == 0:
            self._acum = p if self._acum is None else np.maximum(self._acum, p)
            return np.sqrt(self._acum)
        self._fila = (self._fila + [p])[-k:]
        return np.sqrt(np.mean(self._fila, axis=0))

    def _tela(self):
        if not self.winfo_exists():
            return
        with self._trava_q:
            q, self._novo = self._novo, None
        if q is not None:
            self._n_quadros += 1
            self._ultimo = q
            self.btn_salvar.configure(state="normal")
            self._desenha(q)
        if self._parar is not None:
            self.after(TELA_MS, self._tela)

    def _desenha(self, q: dict):
        fs, n = q["fs"], q["n"]
        self._l_t.set_data(np.arange(n) / fs * self._esc_t, q["x"])
        amp = self._acumula(q)
        self._l_f.set_data(q["f"] * self._esc_f, amp)
        topo = max(1.15 * float(np.max(amp)), AMP_MIN)
        self.ax_f.set_ylim(0, topo)
        busca = amp[: n // 2 + 1].copy()
        busca[:BINS_DC] = -np.inf
        k = int(np.argmax(busca))
        f_pico = q["f_pico"] if k == q["k_pico"] else q["f"][k]
        self._p_f.set_data([f_pico * self._esc_f], [amp[k] + 0.04 * topo])
        self._txt_pico.set_text(f"pico: {f_pico:.2f} Hz, {amp[k] * 1e3:.1f} mV de pico")
        passos = n // dsp.MAX_FFT_INPUT_SIZE
        fft_txt = ("1 FFT de 1024 na FPGA" if passos == 1
                   else f"{passos} FFTs de 1024 na FPGA (quatro passos)")
        self.ax_t.set_title(f"x(t) — {q['entrada']}, quadro {self._n_quadros}: {n} "
                            f"amostras a {fs:g} Hz" + ("  [SATUROU]" if q["saturou"] else ""),
                            fontsize=9)
        media = self.var_media.get()
        self.ax_f.set_title(f"|X(f)| — {fft_txt}, janela {q['janela']}"
                            + ("" if media == MEDIA_NENHUMA else f", {media.lower()}"),
                            fontsize=9)
        seg = max(time.monotonic() - self._inicio, 1e-9)
        snr = q["snr_numpy"]
        snr_txt = "idênticas" if not np.isfinite(snr) else f"{snr:.1f} dB"
        self.var_medidas.set("\n".join([
            f"pico:         {f_pico:.2f} Hz",
            f"amplitude:    {amp[k] * 1e3:.2f} mV de pico",
            f"nível DC:     {q['dc']:.4f} V",
            f"captura ADC:  {q['t_cap'] * 1e3:.0f} ms",
            f"FFT na FPGA:  {q['t_fft'] * 1e3:.0f} ms",
            f"quadros:      {self._n_quadros} ({self._n_quadros / seg:.1f} por s)",
            f"FPGA × NumPy: {snr_txt}",
        ] + (["SATUROU (código no limite)"] if q["saturou"] else [])))
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    def _on_salvar(self):
        q = self._ultimo
        if q is None:
            return
        path = filedialog.asksaveasfilename(
            title="Salvar o quadro (abre no Comparador)", defaultextension=".mrph",
            initialfile="analisador_quadro.mrph",
            filetypes=[("Morphe", "*.mrph"), ("Todos", "*.*")])
        if not path:
            return
        n = q["n"]
        dc = " sem DC," if q["tirou_dc"] else ""
        try:
            dsp.save_mrph_bundle(path, title="Morphe FFT", sections=[
                {"name": "x", "kind": "real", "n": np.arange(n), "data": q["x_env"],
                 "description": (f"x[n] - ADC {q['entrada']},{dc} janela "
                                 f"{q['janela']}, como foi enviado à FPGA"),
                 "fs": q["fs"], "dtype_out": "float32"},
                {"name": "X", "kind": "complex", "n": np.arange(n), "data": q["X"],
                 "description": f"X[k] = FFT(x) na FPGA, N={n}", "fs": q["fs"]},
            ])
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e))
            return
        self.status.set(f"Quadro salvo em {path}. Abra em “Comparar .mrph (FPGA) × NumPy”.")
