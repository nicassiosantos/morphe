"""
aquisicao_window.py -- janela "Aquisição (ADC)": le tensoes e captura sinais
pelo ADC da DE1-SoC.

Duas coisas na mesma janela, as etapas 1 e 2 do docs/ADC.md:
  - voltimetro: a tensao media de 0,1 s na entrada escolhida, com o desvio,
    o minimo e o maximo; pode repetir sozinho, para acompanhar um
    potenciometro ou uma fonte sendo ajustada;
  - captura: n amostras a fs fixa, com o instante de cada amostra dado pelo
    hardware. O grafico mostra o sinal em volts e o espectro, com as medidas
    de uma senoide (frequencia, SINAD, ENOB) -- e a forma de conferir o ADC
    com um gerador de funcoes. Ate 32768 amostras a captura e de uma vez; acima
    disso, ou com 0 (sem limite, ate clicar em Parar), e continua, em blocos,
    sem buraco no tempo (aquisicao.capturar_continuo).

A ultima captura vira o tipo "Captura do ADC" no painel de sinal de todas as
outras janelas (convolucao, FFT, FIR, IIR), e pode ser salva em .csv, .npy ou
.wav para abrir depois pelo tipo "Arquivo".
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import numpy as np

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import aquisicao as aq
import dsp_core as dsp
import morphe_theme as theme
from morphe_config import ADC_N_MAX
from plot_toolbar import PlotToolbar
from popout_helper import open_or_focus, refresh_all

MODOS = {
    "Simples  (0 a 4,096 V)": aq.MODO_SIMPLES,
    "Diferencial  (±2,048 V)": aq.MODO_DIFERENCIAL,
}
REPETIR_MS = 500
# Grafico do espectro embaixo do sinal. Desligado a pedido em 24/09/2026, ate a
# validacao do ADC terminar; as medidas (frequencia, SINAD, ENOB) continuam no
# quadro "Medidas". Religar = True.
MOSTRAR_ESPECTRO = False

COMO_LIGAR = (
    "Conector J15 (2x5) da placa, pino 1 no furo quadrado:\n"
    "  1 VCC5 (5 V — não ligar!)   2 CH0\n"
    "  3 CH1    4 CH2    5 CH3    6 CH4\n"
    "  7 CH5    8 CH6    9 CH7   10 GND\n\n"
    "• Cada pino aceita de 0 a 4,096 V. Tensão NEGATIVA pode danificar "
    "o conversor, em qualquer modo.\n"
    "• Gerador de funções: offset DC ≈ 2 V e no máximo 4 Vpp. Confira no "
    "osciloscópio antes de ligar.\n"
    "• Terra do gerador no pino 10.\n"
    "• Não há filtro antialiasing: tudo acima de fs/2 volta como alias."
)


# Acima disto o grafico no tempo mostra a envoltoria (minimo e maximo por
# faixa de amostras): desenhar milhoes de pontos trava o matplotlib e nao se
# ve mais nada; a envoltoria preserva picos e buracos.
PONTOS_MAX_TEMPO = 200_000
# Espectro e medidas usam as ultimas N amostras de uma captura longa.
N_ESPECTRO = 1 << 18


def _desenha_tempo(ax, cap: Optional[aq.Captura]):
    ax.clear()
    if cap is None or cap.volts.size == 0:
        theme.draw_empty_axes(ax, "x(t) — capture um sinal")
        return
    v = cap.volts
    longo = v.size > PONTOS_MAX_TEMPO
    escala, unidade = (1.0, "s") if v.size / cap.fs > 2.0 else (1e3, "ms")
    if longo:
        faixa = int(np.ceil(v.size / (PONTOS_MAX_TEMPO // 2)))
        m = v.size // faixa
        blocos = v[:m * faixa].reshape(m, faixa)
        t = (np.arange(m) * faixa + faixa / 2) / cap.fs * escala
        ax.fill_between(t, blocos.min(axis=1), blocos.max(axis=1),
                        color=dsp.COLOR_X, linewidth=0)
    else:
        t = np.arange(v.size) / cap.fs * escala
        ax.plot(t, v, color=dsp.COLOR_X, linewidth=0.8)
    dur = v.size / cap.fs
    ax.set_title(f"x(t)  —  {cap.nome_entrada}, {v.size} amostras ({dur:.3g} s) a "
                 f"{cap.fs:g} Hz" + ("  [envoltória]" if longo else ""), fontsize=9)
    ax.set_xlabel(f"t ({unidade})")
    ax.set_ylabel("tensão (V)")
    ax.set_xlim(0, dur * escala)
    theme.style_plot_axes(ax)


def _trecho_espectro(cap: aq.Captura) -> np.ndarray:
    return cap.volts[-N_ESPECTRO:]


def _desenha_espectro(ax, cap: Optional[aq.Captura]):
    ax.clear()
    if cap is None or cap.volts.size == 0:
        theme.draw_empty_axes(ax, "Espectro (NumPy, janela de Blackman-Harris)")
        return
    x = _trecho_espectro(cap)
    x = x - np.mean(x)
    w = aq.janela_bh(x.size)
    X = np.fft.rfft(x * w) / (np.sum(w) / 2)          # amplitude de pico, em V
    f = np.fft.rfftfreq(x.size, 1.0 / cap.fs)
    ax.plot(f / 1e3, 20 * np.log10(np.abs(X) + 1e-9), color=dsp.COLOR_MAG,
            linewidth=0.8)
    ax.set_title("Espectro da parte AC  (dBV de pico, janela de Blackman-Harris)"
                 + (f"  — últimas {x.size} amostras" if x.size < cap.volts.size else ""),
                 fontsize=9)
    ax.set_xlabel("f (kHz)")
    ax.set_ylabel("dBV")
    ax.set_xlim(0, cap.fs / 2e3)
    ax.set_ylim(bottom=-120)
    theme.style_plot_axes(ax)


class AquisicaoWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Morphe — Aquisição pelo ADC (LTC2308)")
        self.geometry("1240x820")
        self.configure(bg=theme.COLORS["bg"])
        theme.setup_styles(self)

        self.cap: Optional[aq.Captura] = aq.ultima_captura()
        self._ocupado = False
        self._parar: Optional[threading.Event] = None    # captura continua em curso
        self._popouts: dict = {}
        self.protocol("WM_DELETE_WINDOW", self._on_fechar)

        self.status = tk.StringVar(value="Pronto. Confira a ligação em "
                                         "“Como ligar” antes de conectar um sinal.")
        theme.make_status_bar(self, self.status).pack(side="bottom", fill="x")

        root = ttk.Frame(self, style="Main.TFrame", padding=12)
        root.pack(fill="both", expand=True)
        lado = ttk.Frame(root, style="Main.TFrame")
        lado.pack(side="left", fill="y", padx=(0, 12))
        self._build_sidebar(lado)
        area = ttk.Frame(root, style="Main.TFrame")
        area.pack(side="right", fill="both", expand=True)
        self._build_plots(area)
        self._atualiza_fs()
        self._redraw()
        if self.cap is not None:
            self._mostra_metricas()

    # ------------------------------------------------------------------
    def _linha(self, parent, rotulo: str) -> ttk.Frame:
        linha = ttk.Frame(parent, style="Card.TFrame")
        linha.pack(fill="x", pady=(0, 6))
        ttk.Label(linha, text=rotulo, style="Card.TLabel", width=11).pack(side="left")
        return linha

    def _build_sidebar(self, parent):
        sec = theme.CollapsibleSection(parent, title="Como ligar", expanded=False)
        sec.pack(fill="x", pady=(0, 6))
        theme.make_banner(sec.body, kind="warn", wraplength=320,
                          text=COMO_LIGAR).pack(fill="x")

        # --- entrada ---
        ent = ttk.LabelFrame(parent, text=" Entrada ", style="Card.TLabelframe",
                             padding=(14, 12, 14, 10))
        ent.pack(fill="x", pady=(6, 0))
        self.var_modo = tk.StringVar(value=next(iter(MODOS)))
        cb = ttk.Combobox(self._linha(ent, "Modo"), textvariable=self.var_modo,
                          values=list(MODOS), state="readonly", width=22)
        cb.pack(side="left", fill="x", expand=True)
        cb.bind("<<ComboboxSelected>>", lambda e: self._troca_modo())
        self.var_canal = tk.StringVar(value=aq.CANAIS_SIMPLES[0])
        self.cb_canal = ttk.Combobox(self._linha(ent, "Canal"),
                                     textvariable=self.var_canal,
                                     values=aq.CANAIS_SIMPLES, state="readonly",
                                     width=22)
        self.cb_canal.pack(side="left", fill="x", expand=True)

        # --- voltimetro ---
        vol = ttk.LabelFrame(parent, text=" Voltímetro ", style="Card.TLabelframe",
                             padding=(14, 10, 14, 12))
        vol.pack(fill="x", pady=(12, 0))
        self.var_tensao = tk.StringVar(value="— V")
        ttk.Label(vol, textvariable=self.var_tensao, style="Card.TLabel",
                  font=("TkDefaultFont", 22, "bold")).pack(anchor="w")
        self.var_tensao_det = tk.StringVar(value="média de 0,1 s (2000 amostras)")
        ttk.Label(vol, textvariable=self.var_tensao_det, style="Card.TLabel",
                  font=("TkFixedFont", 8), justify="left").pack(anchor="w",
                                                                pady=(0, 8))
        self.btn_ler = ttk.Button(vol, text="Ler tensão", style="Secondary.TButton",
                                  command=self._on_ler)
        self.btn_ler.pack(fill="x")
        self.var_repetir = tk.BooleanVar(value=False)
        ttk.Checkbutton(vol, text="Repetir (2 leituras por segundo)",
                        variable=self.var_repetir, command=self._on_repetir,
                        style="Card.TCheckbutton").pack(anchor="w", pady=(6, 0))

        # --- captura ---
        cap = ttk.LabelFrame(parent, text=" Captura ", style="Card.TLabelframe",
                             padding=(14, 12, 14, 14))
        cap.pack(fill="x", pady=(12, 0))
        self.var_fs = tk.StringVar(value="10000")
        e = ttk.Entry(self._linha(cap, "fs (Hz)"), textvariable=self.var_fs, width=12)
        e.pack(side="left", fill="x", expand=True)
        self.var_n = tk.StringVar(value="8192")
        e2 = ttk.Entry(self._linha(cap, "Amostras"), textvariable=self.var_n, width=12)
        e2.pack(side="left", fill="x", expand=True)
        for w in (e, e2):
            w.bind("<KeyRelease>", lambda ev: self._atualiza_fs())
        ttk.Label(cap, text=f"Até {ADC_N_MAX} amostras: captura de uma vez. Mais que "
                            "isso, ou 0 (sem limite), é contínua, em blocos, até "
                            "completar ou você clicar em Parar.",
                  style="SectionHint.TLabel", wraplength=300,
                  justify="left").pack(anchor="w", pady=(0, 4))
        self.var_fs_info = tk.StringVar()
        ttk.Label(cap, textvariable=self.var_fs_info, style="SectionHint.TLabel",
                  wraplength=300, justify="left").pack(anchor="w", pady=(0, 8))
        self.btn_capt = ttk.Button(cap, text="Capturar", style="Primary.TButton",
                                   command=self._on_capturar)
        self.btn_capt.pack(fill="x", pady=(0, 4))
        self.btn_salvar = ttk.Button(cap, text="Salvar captura (.csv, .npy, .wav)…",
                                     style="Secondary.TButton",
                                     command=self._on_salvar,
                                     state="normal" if self.cap else "disabled")
        self.btn_salvar.pack(fill="x")

        # --- medidas ---
        med = ttk.LabelFrame(parent, text=" Medidas da captura ",
                             style="Card.TLabelframe", padding=(14, 10, 14, 12))
        med.pack(fill="x", pady=(12, 0))
        self.var_metricas = tk.StringVar(value="(capture um sinal)")
        ttk.Label(med, textvariable=self.var_metricas, style="Card.TLabel",
                  justify="left", font=("TkFixedFont", 8)).pack(anchor="w")

    def _build_plots(self, parent):
        itens = [("x(t)", lambda: self._popout("t"))]
        if MOSTRAR_ESPECTRO:
            itens.append(("Espectro", lambda: self._popout("f")))
        header = theme.make_plot_header_bar(parent, items=itens)
        header.pack(fill="x", pady=(0, 6))
        self.fig = Figure(figsize=(7.4, 7.6), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        if MOSTRAR_ESPECTRO:
            self.ax_t = self.fig.add_subplot(211)
            self.ax_f = self.fig.add_subplot(212)
        else:
            self.ax_t = self.fig.add_subplot(111)
            self.ax_f = None
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
        self.var_tensao.set("— V")

    def _le_campos(self) -> tuple[float, int]:
        try:
            fs = float(self.var_fs.get().replace(",", "."))
            n = int(self.var_n.get())
        except ValueError as e:
            raise ValueError("fs e amostras devem ser numéricos") from e
        if not 0 <= n < 2 ** 32:
            raise ValueError("amostras deve ser 0 (sem limite) ou positivo")
        aq.divisor_para(fs)                 # confere a faixa
        return fs, n

    @staticmethod
    def _continua(n: int) -> bool:
        return n == 0 or n > ADC_N_MAX

    def _atualiza_fs(self):
        try:
            fs, n = self._le_campos()
        except ValueError as e:
            self.var_fs_info.set(str(e))
            return
        div = aq.divisor_para(fs)
        fs_real = aq.fs_de(div)
        txt = f"fs real: {fs_real:.3f} Hz  (50 MHz ÷ {div})"
        if abs(fs_real - fs) > 1e-9:
            txt += " — a mais próxima que o divisor inteiro permite"
        if n == 0:
            txt += (f"\ncontínua até Parar; memória no PC: "
                    f"~{10 * fs_real * 60 / 1e6:.0f} MB por minuto")
        else:
            txt += f"\nduração: {aq.duracao_s(n, div):.3g} s"
            if self._continua(n):
                txt += f" (contínua); memória no PC: ~{10 * n / 1e6:.0f} MB"
        self.var_fs_info.set(txt)

    def _cliente(self):
        return self.master.tcp_panel.make_client()

    def _trava(self, ocupado: bool, continua: bool = False):
        self._ocupado = ocupado
        estado = "disabled" if ocupado else "normal"
        self.btn_ler.configure(state=estado)
        if ocupado and continua:
            self.btn_capt.configure(state="normal", text="Parar",
                                    command=self._on_parar)
        else:
            self.btn_capt.configure(state=estado, text="Capturar",
                                    command=self._on_capturar)

    # ------------------------------------------------------------------
    def _on_ler(self):
        if self._ocupado:
            return
        try:
            client = self._cliente()
        except Exception as e:
            messagebox.showerror("Configuração", str(e))
            self.var_repetir.set(False)
            return
        modo, canal = self._modo_canal()
        self._trava(True)

        def worker():
            try:
                r = aq.ler_tensao(client, modo, canal)
                self.after(0, lambda: self._on_tensao(r))
            except Exception as e:
                self.after(0, lambda err=e: self._on_erro("Erro na leitura", err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_tensao(self, r: dict):
        self._trava(False)
        self.var_tensao.set(f"{r['media']:.3f} V")
        det = (f"σ {r['desvio'] * 1e3:.2f} mV   "
               f"mín {r['minimo']:.3f}   máx {r['maximo']:.3f} V")
        if r["saturou"]:
            det += "\nATENÇÃO: bateu no limite da faixa"
        self.var_tensao_det.set(det)
        self.status.set(f"Leitura: {r['media']:.3f} V (média de {r['n']} amostras)")
        if self.var_repetir.get():
            self.after(REPETIR_MS, self._repete)

    def _repete(self):
        if self.var_repetir.get() and self.winfo_exists():
            self._on_ler()

    def _on_repetir(self):
        if self.var_repetir.get() and not self._ocupado:
            self._on_ler()

    def _on_capturar(self):
        if self._ocupado:
            return
        try:
            fs, n = self._le_campos()
            client = self._cliente()
        except Exception as e:
            messagebox.showerror("Configuração", str(e))
            return
        modo, canal = self._modo_canal()
        self.var_repetir.set(False)
        div = aq.divisor_para(fs)
        if self._continua(n):
            self._captura_continua(client, n, fs, modo, canal)
            return
        self._trava(True)
        self.status.set(f"Capturando {n} amostras a {aq.fs_de(div):g} Hz "
                        f"({aq.duracao_s(n, div):.3g} s na placa)...")

        def worker():
            try:
                cap = aq.capturar(client, n, fs, modo, canal)
                self.after(0, lambda: self._on_capturado(cap))
            except Exception as e:
                self.after(0, lambda err=e: self._on_erro("Erro na captura", err))

        threading.Thread(target=worker, daemon=True).start()

    def _captura_continua(self, client, n: int, fs: float, modo: str, canal: int):
        parar = threading.Event()
        self._parar = parar
        self._trava(True, continua=True)
        fs_real = aq.fs_de(aq.divisor_para(fs))
        alvo = "até você clicar em Parar" if n == 0 else f"{n} amostras"
        self.status.set(f"Captura contínua a {fs_real:g} Hz, {alvo}...")
        ultimo = [0.0]

        def ao_bloco(total, _bloco):
            agora = time.monotonic()
            if agora - ultimo[0] >= 0.3:            # a tela nao precisa de mais
                ultimo[0] = agora
                self.after(0, lambda: self.status.set(
                    f"Capturando: {total / fs_real:.1f} s ({total} amostras, "
                    f"~{10 * total / 1e6:.0f} MB)" + (f" de {n}" if n else "")
                    + ". Clique em Parar para encerrar."))

        def worker():
            try:
                cap = aq.capturar_continuo(client, n, fs, modo, canal,
                                           parar=parar, ao_bloco=ao_bloco)
                self.after(0, lambda: self._on_capturado(cap))
            except Exception as e:
                self.after(0, lambda err=e: self._on_erro("Erro na captura", err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_parar(self):
        if self._parar is not None:
            self._parar.set()
            self.btn_capt.configure(state="disabled", text="Parando...")

    def _on_fechar(self):
        if self._parar is not None:
            self._parar.set()        # a placa para e fica livre para os outros
        self.destroy()

    def _on_capturado(self, cap: aq.Captura):
        self._parar = None
        self._trava(False)
        if cap.volts.size == 0:
            self.status.set("A captura terminou sem nenhuma amostra.")
            return
        self.cap = cap
        self.btn_salvar.configure(state="normal")
        self._mostra_metricas()
        self._redraw()
        aviso = "  ATENÇÃO: bateu no limite da faixa." if aq.saturou(cap) else ""
        fim = {"completa": "", "parada": " (parada por você)",
               "perdeu": " — ATENÇÃO: a placa não acompanhou e a captura parou aqui; "
                         "o que veio é contínuo e válido",
               "timeout": " — ATENÇÃO: o hardware parou de mandar amostras",
               "conexao": " — ATENÇÃO: a conexão caiu no meio; o que veio é contínuo "
                          "e válido"}
        self.status.set(f"OK: {cap.volts.size} amostras ({cap.volts.size / cap.fs:.3g} s) "
                        f"de {cap.nome_entrada} a {cap.fs:g} Hz"
                        f"{fim.get(cap.termino, '')}. Disponível como “Captura do ADC” "
                        f"nas outras janelas.{aviso}")
        if cap.termino in ("perdeu", "timeout", "conexao"):
            messagebox.showwarning("Captura interrompida", self.status.get())

    def _mostra_metricas(self):
        m = aq.metricas(_trecho_espectro(self.cap), self.cap.fs)
        linhas = [
            f"nível DC:     {m['dc']:.4f} V",
            f"pico a pico:  {m['vpp']:.4f} V",
            f"RMS da AC:    {m['rms_ac'] * 1e3:.2f} mV",
        ]
        if np.isfinite(m["f_pico"]):
            linhas.append(f"freq. do pico: {m['f_pico']:.2f} Hz")
        if np.isfinite(m["sinad_db"]):
            linhas.append(f"SINAD:        {m['sinad_db']:.1f} dB")
            linhas.append(f"ENOB:         {m['enob']:.2f} bits")
        linhas.append(f"fs:           {self.cap.fs:.3f} Hz")
        if self.cap.volts.size > N_ESPECTRO:
            linhas.append(f"(medidas nas últimas {N_ESPECTRO} amostras)")
        if aq.saturou(self.cap):
            linhas.append("SATUROU (código no limite)")
        self.var_metricas.set("\n".join(linhas))

    def _on_erro(self, titulo: str, err: Exception):
        self._parar = None
        self._trava(False)
        self.var_repetir.set(False)
        messagebox.showerror(titulo, str(err))
        self.status.set("Erro — ver mensagem.")

    def _on_salvar(self):
        if self.cap is None:
            return
        path = filedialog.asksaveasfilename(
            title="Salvar captura", defaultextension=".csv",
            initialfile=f"captura_{self.cap.nome_entrada.split()[0].lower()}.csv",
            filetypes=aq.TIPOS_SALVAR)
        if not path:
            return
        try:
            msg = aq.salvar(self.cap, path)
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e))
            return
        self.status.set(f"Salvo: {msg}")

    # ------------------------------------------------------------------
    def _redraw(self):
        _desenha_tempo(self.ax_t, self.cap)
        if self.ax_f is not None:
            _desenha_espectro(self.ax_f, self.cap)
        self.fig.tight_layout()
        self.canvas.draw_idle()
        refresh_all(self._popouts)

    def _popout(self, qual: str):
        if self.cap is None:
            messagebox.showwarning("Atenção", "Capture um sinal antes.")
            return

        def draw(fig: Figure):
            ax = fig.add_subplot(111)
            if qual == "t":
                _desenha_tempo(ax, self.cap)
            else:
                _desenha_espectro(ax, self.cap)

        titulos = {"t": "x(t)", "f": "Espectro"}
        open_or_focus(self._popouts, key="adc_" + qual, parent=self,
                      title="Morphe — " + titulos[qual], draw_fn=draw,
                      size="1100x650")
