"""
audio_window.py -- janela "Áudio (codec)": o som entrando e saindo da placa
pelo codec WM8731, com as funções de audio.py.

  Capturar     grava alguns segundos da entrada do codec no computador, em
               blocos de 1024 quadros, e mostra o último bloco no tempo e o
               espectro; o resultado pode ser salvo (.wav, .npy) ou tocado.
  Reproduzir   toca na LINE-out da placa um tom gerado aqui, a última
               captura ou um arquivo (.wav, .npy, .csv, .txt).
  Loopback     o som que entra no codec volta: pela saída da própria placa
               (a FPGA repassa, sem passar pelo computador), para o
               computador (ao vivo, bloco a bloco), ou para os dois.
  Filtrar      passa a última captura (ou um arquivo) pelo filtro IIR da
               placa (IIR: Butterworth, Chebyshev I e II, elíptico; FIR:
               método das janelas; ou o filtro de um dos projetistas), em
               blocos de 1024, e mostra os espectros da entrada e da saída
               com |H(f)|; as duas podem ser tocadas e a saída salva.
               Não é tempo real: grava, filtra, ouve. O filtro em tempo
               real ficou como ideia (docs/IDEIA-FILTRO-TEMPO-REAL.md).

A taxa é fixa, 48 828,125 Hz (50 MHz / 1024), 16 bits, estéreo. O espectro
desta janela é calculado no computador (NumPy): enquanto o áudio corre, a
conexão com a placa está ocupada com ele.
"""
from __future__ import annotations

import os
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

import audio
import blocos
import dsp_core as dsp
import iir_design as iir
import morphe_config as cfg
import morphe_theme as theme
import sinal_arquivo
from analisador_window import JANELAS, janela as janela_de
from fir_designer_window import FIRDesignerWindow
from iir_designer_window import IIRDesignerWindow
from plot_toolbar import PlotToolbar

ANTES = ("Antes de usar, configure o codec na placa (uma vez por boot):\n"
         "  ./codec --entrada mic digital   microfone no MIC-in (rosa)\n"
         "  ./codec digital                 linha no LINE-in (azul)\n"
         "A saída é a LINE-out (verde): fone ou caixa de som. A chave SW9 "
         "tem de estar BAIXA (alta = tom de teste de 1017 Hz).\n"
         "Microfone perto da caixa com o loopback ligado dá microfonia: "
         "comece com o volume baixo (./codec --volume -20 ...).")

BLOCOS = ("256", "1024", "4096")
DESTINOS = {"Na placa  (entrada → caixa, pela FPGA)": "codec",
            "Para o computador  (ao vivo)": "computador",
            "Os dois  (caixa e computador)": "ambos"}
FONTES = ("Gerador", "Última captura", "Arquivo")
FORMAS = ("Senoide", "Quadrada", "Dente de serra", "Varredura (f → f2)", "Ruído branco")

# O que vale saber do codec, como o Morphe o usa (folha de dados do WM8731,
# rev. 4.8, em docs/de1-soc; AVDD = 3,3 V na DE1-SoC).
SOBRE_CODEC = (
    "Codec WM8731 (Wolfson/Cirrus), sigma-delta, estéreo.\n"
    "\n"
    "Amostragem\n"
    "  fs = 50 MHz / 1024 = 48 828,125 Hz (exata; não é 48 kHz:\n"
    "  o relógio-mestre de 12,5 MHz vem de um contador na FPGA,\n"
    "  sem PLL, e o codec trabalha em 256·fs).\n"
    "  16 bits por canal, complemento de dois: 1 LSB = 1/32768.\n"
    "\n"
    "Filtro anti-aliasing (digital, de dizimação, no ADC)\n"
    "  plano (±0,05 dB) até 0,4535·fs = 22,1 kHz\n"
    "  −6 dB em fs/2 = 24,4 kHz\n"
    "  ≥ 60 dB de atenuação acima de 0,5465·fs = 26,7 kHz\n"
    "  Entre 24,4 e 26,7 kHz o rebatimento é atenuado só em parte.\n"
    "  O DAC tem o filtro de reconstrução equivalente (≥ 50 dB).\n"
    "\n"
    "Passa-altas na entrada: 3,7 Hz (−3 dB). O codec não mede\n"
    "nível contínuo (entradas acopladas em AC).\n"
    "\n"
    "Níveis (fundo de escala = 0 dBFS)\n"
    "  LINE-in com ganho 0 dB: 1,0 Vrms (1,41 V de pico)\n"
    "  MIC-in: 14 dB de ganho fixo + 20 dB do --entrada mic\n"
    "    = 34 dB: fundo de escala perto de 20 mVrms\n"
    "  LINE-out: 1,0 Vrms no fundo de escala, menos o --volume\n"
    "\n"
    "Desempenho típico: SNR do ADC 90 dB, do DAC 100 dB (pond. A).\n"
    "Atraso dos filtros: 20/fs no ADC + 18/fs no DAC = 0,78 ms;\n"
    "o loopback pela FPGA soma mais 1 quadro (20 µs).\n"
    "\n"
    "O LTC2308 (conector J15, janela Aquisição) é outro conversor:\n"
    "12 bits, acoplado em DC, fs escolhida, e SEM anti-aliasing.")
TIPOS_FILTRO = {"Passa-baixas": "lowpass", "Passa-altas": "highpass",
                "Passa-faixa": "bandpass", "Rejeita-faixa": "bandstop"}
ORIGENS_FILTRO = ("Projetar aqui", "Projetista IIR", "Projetista FIR")
CLASSES = ("IIR", "FIR")
APROX_IIR = {"Butterworth": "butter", "Chebyshev I": "cheby1",
             "Chebyshev II": "cheby2", "Elíptico": "ellip"}
JANELAS_FIR = {"Hamming": "hamming", "Hann": "hann", "Blackman": "blackman",
               "Kaiser": "kaiser"}
FONTES_FILTRAR = ("Última captura", "Arquivo (o de Reproduzir)")
TELA_MS = 100


def polo_max(sos: np.ndarray) -> float:
    """Modulo do polo mais externo da cascata."""
    p = 0.0
    for sec in np.atleast_2d(sos):
        a = sec[3:6]
        if np.any(a[1:] != 0):
            p = max(p, float(np.max(np.abs(np.roots(a)))))
    return p
GUARDA_MAX_S = 60.0          # o ao vivo guarda no máximo o último minuto


class AudioWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Morphe — Áudio (codec da placa)")
        self.geometry("1240x820")
        self.configure(bg=theme.COLORS["bg"])
        theme.setup_styles(self)

        self._parar: Optional[threading.Event] = None
        self._ocupado = False
        self._trava = threading.Lock()
        self._novo: Optional[np.ndarray] = None      # último bloco, a desenhar
        self._partes: list = []                      # blocos da gravação em curso
        self._gravado = 0
        self._captura: Optional[np.ndarray] = None   # última captura completa
        self._arquivo: Optional[tuple] = None        # (sinal, fs, nome)
        self._loop_placa = False
        self._proj: dict = {}                        # "IIR"/"FIR" -> filtro do projetista
        self._filtragem: Optional[dict] = None       # a ultima: entrada, saida, sos, fs
        self.protocol("WM_DELETE_WINDOW", self._on_fechar)

        self.status = tk.StringVar(value="Pronto. Configure o codec na placa "
                                         "(ver “Antes de usar”).")
        theme.make_status_bar(self, self.status).pack(side="bottom", fill="x")
        root = ttk.Frame(self, style="Main.TFrame", padding=12)
        root.pack(fill="both", expand=True)
        self._build_sidebar(self._lateral_rolavel(root))
        area = ttk.Frame(root, style="Main.TFrame")
        area.pack(side="right", fill="both", expand=True)
        self._build_plots(area)
        self._troca_fonte()

    # ---- montagem -------------------------------------------------------------
    def _lateral_rolavel(self, root) -> ttk.Frame:
        """A barra lateral num Canvas com rolagem vertical: numa tela baixa os
        cards de baixo (Loopback, Medidas) continuam alcancaveis. A barra so
        aparece quando falta altura; a roda do mouse rola com o ponteiro em
        cima da lateral (<MouseWheel> no Windows, Button-4/5 no Linux)."""
        externo = ttk.Frame(root, style="Main.TFrame")
        externo.pack(side="left", fill="y", padx=(0, 12))
        canvas = tk.Canvas(externo, width=340, background=theme.COLORS["bg"],
                           highlightthickness=0, bd=0)
        barra = ttk.Scrollbar(externo, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=barra.set)
        canvas.pack(side="left", fill="y", expand=True)
        dentro = ttk.Frame(canvas, style="Main.TFrame")
        item = canvas.create_window((0, 0), window=dentro, anchor="nw")

        def ajusta(_ev=None):
            canvas.configure(width=dentro.winfo_reqwidth())
            canvas.itemconfigure(item, width=canvas.winfo_width())
            canvas.configure(scrollregion=canvas.bbox("all"))
            precisa = dentro.winfo_reqheight() > canvas.winfo_height()
            if precisa and not barra.winfo_ismapped():
                barra.pack(side="right", fill="y")
            elif not precisa and barra.winfo_ismapped():
                barra.pack_forget()
                canvas.yview_moveto(0)

        dentro.bind("<Configure>", ajusta)
        canvas.bind("<Configure>", ajusta)

        def roda(ev):
            if dentro.winfo_reqheight() <= canvas.winfo_height():
                return
            sobe = getattr(ev, "num", 0) == 4 or getattr(ev, "delta", 0) > 0
            canvas.yview_scroll(-1 if sobe else 1, "units")

        def entra(_ev):
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.bind_all(seq, roda)

        def sai(_ev):
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.unbind_all(seq)

        externo.bind("<Enter>", entra)
        externo.bind("<Leave>", sai)
        return dentro

    def _linha(self, parent, rotulo: str) -> ttk.Frame:
        linha = ttk.Frame(parent, style="Card.TFrame")
        linha.pack(fill="x", pady=(0, 6))
        ttk.Label(linha, text=rotulo, style="Card.TLabel", width=11).pack(side="left")
        return linha

    def _entrada(self, parent, rotulo, valor, largura=10) -> tk.StringVar:
        var = tk.StringVar(value=valor)
        ttk.Entry(self._linha(parent, rotulo), textvariable=var,
                  width=largura).pack(side="left", fill="x", expand=True)
        return var

    def _build_sidebar(self, parent):
        sec = theme.CollapsibleSection(parent, title="Antes de usar", expanded=False)
        sec.pack(fill="x", pady=(0, 6))
        theme.make_banner(sec.body, kind="warn", wraplength=320,
                          text=ANTES).pack(fill="x")
        sec = theme.CollapsibleSection(parent, title="Sobre o codec (fs, anti-aliasing, níveis)",
                                       expanded=False)
        sec.pack(fill="x", pady=(0, 6))
        ttk.Label(sec.body, text=SOBRE_CODEC, style="Card.TLabel", justify="left",
                  font=("TkFixedFont", 8)).pack(anchor="w")

        # Capturar
        cap = ttk.LabelFrame(parent, text=" Capturar ", style="Card.TLabelframe",
                             padding=(14, 10, 14, 10))
        cap.pack(fill="x", pady=(6, 0))
        self.var_dur = self._entrada(cap, "Duração (s)", "3")
        self.var_bloco = tk.StringVar(value="1024")
        ttk.Combobox(self._linha(cap, "Bloco"), textvariable=self.var_bloco,
                     values=BLOCOS, state="readonly", width=10).pack(side="left")
        self.var_cap_loop = tk.BooleanVar(value=False)
        ttk.Checkbutton(cap, text="Tocar na saída enquanto grava",
                        variable=self.var_cap_loop,
                        style="Card.TCheckbutton").pack(anchor="w", pady=(0, 6))
        self.btn_capturar = ttk.Button(cap, text="Capturar", style="Primary.TButton",
                                       command=self._on_capturar)
        self.btn_capturar.pack(fill="x", pady=(0, 4))
        self.btn_salvar = ttk.Button(cap, text="Salvar captura (.wav, .npy)…",
                                     style="Secondary.TButton", state="disabled",
                                     command=self._on_salvar)
        self.btn_salvar.pack(fill="x")

        # Reproduzir
        rep = ttk.LabelFrame(parent, text=" Reproduzir na placa ", style="Card.TLabelframe",
                             padding=(14, 10, 14, 10))
        rep.pack(fill="x", pady=(10, 0))
        self.var_fonte = tk.StringVar(value=FONTES[0])
        cb = ttk.Combobox(self._linha(rep, "Fonte"), textvariable=self.var_fonte,
                          values=FONTES, state="readonly", width=16)
        cb.pack(side="left", fill="x", expand=True)
        cb.bind("<<ComboboxSelected>>", lambda e: self._troca_fonte())
        self.fr_tom = ttk.Frame(rep, style="Card.TFrame")
        self.var_forma = tk.StringVar(value=FORMAS[0])
        ttk.Combobox(self._linha(self.fr_tom, "Forma"), textvariable=self.var_forma,
                     values=FORMAS, state="readonly", width=16).pack(
                         side="left", fill="x", expand=True)
        self.var_freq = self._entrada(self.fr_tom, "f (Hz)", "440")
        self.var_f2 = self._entrada(self.fr_tom, "f2 (Hz)", "4000")
        self.var_amp = self._entrada(self.fr_tom, "Amplitude", "0.3")
        self.var_tdur = self._entrada(self.fr_tom, "Duração (s)", "2")
        ttk.Label(self.fr_tom, text="Amplitude de 0 a 1 (1 = fundo de escala). "
                  "f2 só vale na varredura.", style="SectionHint.TLabel",
                  wraplength=300, justify="left").pack(anchor="w")
        self.fr_arq = ttk.Frame(rep, style="Card.TFrame")
        ttk.Button(self.fr_arq, text="Escolher arquivo…", style="Secondary.TButton",
                   command=self._on_arquivo).pack(fill="x", pady=(0, 4))
        self.var_arq = tk.StringVar(value="(nenhum)")
        ttk.Label(self.fr_arq, textvariable=self.var_arq, style="SectionHint.TLabel",
                  wraplength=300).pack(anchor="w")
        self.var_norm = tk.BooleanVar(value=True)
        self.ck_norm = ttk.Checkbutton(rep, text="Ajustar o volume: pico em 90 % do máximo",
                                       variable=self.var_norm, style="Card.TCheckbutton")
        # Arquivo e captura chegam com qualquer nivel: um .csv em volts pode
        # passar de 1 (e saturar), e uma captura de microfone fica em -40 dBFS
        # (quase muda). O ajuste multiplica tudo por um fator so, o que leva o
        # maior pico a 0,9 do fundo de escala (-0,9 dBFS): a forma nao muda.
        self.btn_tocar = ttk.Button(rep, text="Tocar", style="Primary.TButton",
                                    command=self._on_tocar)
        self.btn_tocar.pack(side="bottom", fill="x", pady=(6, 0))
        self.ck_norm.pack(side="bottom", anchor="w")

        # Filtrar na placa (IIR ou FIR, por blocos)
        fl = ttk.LabelFrame(parent, text=" Filtrar na placa (IIR ou FIR) ",
                            style="Card.TLabelframe", padding=(14, 10, 14, 10))
        fl.pack(fill="x", pady=(10, 0))
        self.var_ffonte = tk.StringVar(value=FONTES_FILTRAR[0])
        ttk.Combobox(self._linha(fl, "Sinal"), textvariable=self.var_ffonte,
                     values=FONTES_FILTRAR, state="readonly", width=20).pack(
                         side="left", fill="x", expand=True)
        self.var_forig = tk.StringVar(value=ORIGENS_FILTRO[0])
        cb = ttk.Combobox(self._linha(fl, "Filtro"), textvariable=self.var_forig,
                          values=ORIGENS_FILTRO, state="readonly", width=20)
        cb.pack(side="left", fill="x", expand=True)
        cb.bind("<<ComboboxSelected>>", lambda e: self._troca_origem_filtro())

        # projetar aqui: IIR (4 aproximacoes) ou FIR (metodo das janelas)
        self.fr_aqui = ttk.Frame(fl, style="Card.TFrame")
        self.var_fclasse = tk.StringVar(value=CLASSES[0])
        cb = ttk.Combobox(self._linha(self.fr_aqui, "Classe"), textvariable=self.var_fclasse,
                          values=CLASSES, state="readonly", width=16)
        cb.pack(side="left", fill="x", expand=True)
        cb.bind("<<ComboboxSelected>>", lambda e: self._troca_classe())
        self.var_ftipo = tk.StringVar(value=next(iter(TIPOS_FILTRO)))
        ttk.Combobox(self._linha(self.fr_aqui, "Tipo"), textvariable=self.var_ftipo,
                     values=list(TIPOS_FILTRO), state="readonly", width=16).pack(
                         side="left", fill="x", expand=True)
        self.var_faprox = tk.StringVar(value=next(iter(APROX_IIR)))
        linha = self._linha(self.fr_aqui, "Método")
        self.cb_aprox = ttk.Combobox(linha, textvariable=self.var_faprox,
                                     values=list(APROX_IIR), state="readonly", width=16)
        self.cb_aprox.pack(side="left", fill="x", expand=True)
        linha = ttk.Frame(self.fr_aqui, style="Card.TFrame")
        linha.pack(fill="x", pady=(0, 6))
        self.lb_ordem = ttk.Label(linha, text="Ordem", style="Card.TLabel", width=11)
        self.lb_ordem.pack(side="left")
        self.var_fordem = tk.StringVar(value="4")
        ttk.Entry(linha, textvariable=self.var_fordem, width=10).pack(
            side="left", fill="x", expand=True)
        self.var_ff1 = self._entrada(self.fr_aqui, "f1 (Hz)", "1000")
        self.var_ff2 = self._entrada(self.fr_aqui, "f2 (Hz)", "3000")
        self.var_frp = self._entrada(self.fr_aqui, "Ripple (dB)", "1")
        self.var_frs = self._entrada(self.fr_aqui, "Atenuação (dB)", "60")
        self.var_fbeta = self._entrada(self.fr_aqui, "β (Kaiser)", "8")
        self.var_fdica = tk.StringVar()
        ttk.Label(self.fr_aqui, textvariable=self.var_fdica, style="SectionHint.TLabel",
                  wraplength=300, justify="left").pack(anchor="w")

        # projetistas da plataforma
        self.fr_proj = ttk.Frame(fl, style="Card.TFrame")
        self.btn_proj = ttk.Button(self.fr_proj, text="Abrir o projetista…",
                                   style="Secondary.TButton", command=self._on_projetista)
        self.btn_proj.pack(fill="x", pady=(0, 4))
        self.var_fproj = tk.StringVar(value="(nenhum filtro do projetista ainda)")
        ttk.Label(self.fr_proj, textvariable=self.var_fproj, style="SectionHint.TLabel",
                  wraplength=300, justify="left").pack(anchor="w")

        self.btn_filtrar = ttk.Button(fl, text="Filtrar na placa", style="Primary.TButton",
                                      command=self._on_filtrar)
        self.btn_filtrar.pack(side="bottom", fill="x", pady=(6, 0))
        linha_f = ttk.Frame(fl, style="Card.TFrame")
        linha_f.pack(side="bottom", fill="x", pady=(6, 0))
        self.btn_toca_ent = ttk.Button(linha_f, text="Tocar entrada", style="Secondary.TButton",
                                       state="disabled", command=lambda: self._toca_filtragem("x"))
        self.btn_toca_ent.pack(side="left", fill="x", expand=True, padx=(0, 3))
        self.btn_toca_sai = ttk.Button(linha_f, text="Tocar saída", style="Secondary.TButton",
                                       state="disabled", command=lambda: self._toca_filtragem("y"))
        self.btn_toca_sai.pack(side="left", fill="x", expand=True, padx=(3, 0))
        self.btn_salva_sai = ttk.Button(fl, text="Salvar a saída (.wav, .npy)…",
                                        style="Secondary.TButton", state="disabled",
                                        command=self._on_salva_filtragem)
        self.btn_salva_sai.pack(side="bottom", fill="x", pady=(4, 0))
        self._troca_classe()
        self._troca_origem_filtro()

        # Loopback
        lb = ttk.LabelFrame(parent, text=" Loopback ", style="Card.TLabelframe",
                            padding=(14, 10, 14, 10))
        lb.pack(fill="x", pady=(10, 0))
        ttk.Label(lb, text="O som que entra no codec volta por:",
                  style="Card.TLabel").pack(anchor="w", pady=(0, 4))
        self.var_dest = tk.StringVar(value=next(iter(DESTINOS)))
        for nome in DESTINOS:
            ttk.Radiobutton(lb, text=nome, value=nome, variable=self.var_dest,
                            style="Card.TCheckbutton").pack(anchor="w")
        self.btn_loop = ttk.Button(lb, text="Ligar loopback", style="Primary.TButton",
                                   command=self._on_loop)
        self.btn_loop.pack(fill="x", pady=(6, 0))

        med = ttk.LabelFrame(parent, text=" Medidas ", style="Card.TLabelframe",
                             padding=(14, 8, 14, 10))
        med.pack(fill="x", pady=(10, 0))
        self.var_medidas = tk.StringVar(value="(nenhum áudio ainda)")
        ttk.Label(med, textvariable=self.var_medidas, style="Card.TLabel",
                  justify="left", font=("TkFixedFont", 8)).pack(anchor="w")

    def _build_plots(self, parent):
        topo = ttk.Frame(parent, style="Card.TFrame", padding=(8, 4))
        topo.pack(fill="x", pady=(0, 4))
        self.var_db = tk.BooleanVar(value=True)
        ttk.Checkbutton(topo, text="Espectro em dB  (desmarcado: linear)", variable=self.var_db,
                        command=self._troca_escala,
                        style="Card.TCheckbutton").pack(side="left")
        # O espectro inteiro, de 0 a fs: a metade de cima (fs/2 a fs) e a
        # replica da de baixo, espelhada -- o mesmo que o analisador espectral
        # mostra. Desmarcado, so de 0 a fs/2, onde esta a informacao.
        self.var_completo = tk.BooleanVar(value=False)
        ttk.Checkbutton(topo, text="0 a fs  (com a réplica)", variable=self.var_completo,
                        command=self._troca_escala,
                        style="Card.TCheckbutton").pack(side="left", padx=(14, 0))
        # A janela do espectro. Hann e Blackman-Harris separam tons vizinhos;
        # a flat-top acerta a amplitude de um tom entre dois bins (as outras
        # perdem ate 1,4 dB); a retangular mostra o vazamento sem disfarce.
        ttk.Label(topo, text="Janela:", style="SectionHint.TLabel").pack(side="left", padx=(18, 4))
        self.var_janela = tk.StringVar(value=JANELAS[0])
        cb = ttk.Combobox(topo, textvariable=self.var_janela, values=JANELAS,
                          state="readonly", width=24)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._troca_escala())
        self._ultimo = None                  # (bloco, titulo) para redesenhar
        self._vista_filtro = False           # a tela mostra a ultima filtragem
        self.fig = Figure(figsize=(7.4, 7.6), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        self.ax_t = self.fig.add_subplot(211)
        self.ax_f = self.fig.add_subplot(212)
        theme.draw_empty_axes(self.ax_t, "x(t) — o último bloco que chegou do codec")
        theme.draw_empty_axes(self.ax_f, "|X(f)| — espectro do bloco (NumPy, no computador)")
        self.fig.tight_layout()
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.toolbar = PlotToolbar(self.canvas)
        self._eixos_prontos = None

    def _troca_fonte(self):
        self.fr_tom.pack_forget()
        self.fr_arq.pack_forget()
        f = self.var_fonte.get()
        if f == "Gerador":
            self.fr_tom.pack(fill="x")
        elif f == "Arquivo":
            self.fr_arq.pack(fill="x")

    # ---- utilitários ------------------------------------------------------------
    def _cliente(self):
        return self.master.tcp_panel.make_client()

    def _num(self, var: tk.StringVar, nome: str, minimo: float, maximo: float) -> float:
        try:
            v = float(var.get().replace(",", "."))
        except ValueError as e:
            raise ValueError(f"{nome} deve ser um número") from e
        if not (minimo <= v <= maximo):
            raise ValueError(f"{nome} deve estar entre {minimo:g} e {maximo:g}")
        return v

    def _botoes(self, livre: bool):
        estado = "normal" if livre else "disabled"
        for b in (self.btn_capturar, self.btn_tocar, self.btn_filtrar):
            b.configure(state=estado)
        if self._filtragem is not None:
            for b in (self.btn_toca_ent, self.btn_toca_sai, self.btn_salva_sai):
                b.configure(state=estado)

    def _erro(self, err: Exception):
        self._ocupado = False
        self._parar = None
        self._botoes(True)
        self.btn_loop.configure(state="normal",
                                text="Desligar loopback" if self._loop_placa else "Ligar loopback")
        self.status.set("Erro — ver mensagem.")
        messagebox.showerror("Áudio", str(err), parent=self)

    # ---- captura --------------------------------------------------------------------
    def _corre_captura(self, n_total: int, n_bloco: int, loopback: bool,
                       parar: Optional[threading.Event], guarda_max: int):
        """Thread: recebe os blocos, guarda e entrega o último para a tela."""
        cli = self._cliente()
        for b in audio.blocos(cli, n_bloco=n_bloco, n_total=n_total,
                              loopback=loopback, parar=parar):
            with self._trava:
                self._partes.append(b)
                self._gravado += b.shape[0]
                while self._gravado - self._partes[0].shape[0] >= guarda_max:
                    self._gravado -= self._partes.pop(0).shape[0]
                self._novo = b

    def _comeca(self, texto: str):
        self._ocupado = True
        self._partes, self._gravado, self._novo = [], 0, None
        self._botoes(False)
        self.status.set(texto)
        self.after(TELA_MS, self._tela)

    def _termina(self, texto: str):
        self._ocupado = False
        with self._trava:
            partes = self._partes
        if partes:
            self._captura = np.concatenate(partes)
            self.btn_salvar.configure(state="normal")
        self._botoes(True)
        self._tela(final=True)
        self.status.set(texto)

    def _on_capturar(self):
        try:
            seg = self._num(self.var_dur, "Duração", 0.01, 600)
            n_bloco = int(self.var_bloco.get())
            self._cliente()
        except Exception as e:
            messagebox.showerror("Captura", str(e), parent=self)
            return
        n = max(1, int(round(seg * audio.FS)))
        loop = self.var_cap_loop.get()
        self._comeca(f"Capturando {seg:g} s ({n} quadros) em blocos de {n_bloco}"
                     + (", tocando na saída..." if loop else "..."))

        def worker():
            try:
                t0 = time.monotonic()
                self._corre_captura(n, n_bloco, loop, None, n)
                dt = time.monotonic() - t0
                self.after(0, lambda: self._termina(
                    f"Captura pronta: {n} quadros ({n / audio.FS:.2f} s) em {dt:.2f} s. "
                    "Salve, ou toque com Reproduzir → Última captura."))
            except Exception as e:
                self.after(0, lambda err=e: self._erro(err))
        threading.Thread(target=worker, daemon=True).start()

    # ---- loopback ---------------------------------------------------------------------
    def _on_loop(self):
        destino = DESTINOS[self.var_dest.get()]
        if self._parar is not None:                    # ao vivo em curso: parar
            self._parar.set()
            self.btn_loop.configure(state="disabled", text="Parando...")
            return
        if self._loop_placa:                           # desligar o da placa
            self._loop_placa_liga(False)
            return
        if destino == "codec":
            self._loop_placa_liga(True)
            return
        try:
            n_bloco = int(self.var_bloco.get())
            self._cliente()
        except Exception as e:
            messagebox.showerror("Loopback", str(e), parent=self)
            return
        parar = threading.Event()
        self._parar = parar
        ambos = destino == "ambos"
        self._comeca("Loopback ao vivo: o som do codec chega ao computador bloco a bloco"
                     + (" e sai na caixa" if ambos else "") + ". Clique em Parar.")
        self.btn_loop.configure(text="Parar")
        guarda = int(GUARDA_MAX_S * audio.FS)

        def worker():
            try:
                self._corre_captura(0, n_bloco, ambos, parar, guarda)
                self.after(0, self._fim_ao_vivo)
            except Exception as e:
                self.after(0, lambda err=e: self._erro(err))
        threading.Thread(target=worker, daemon=True).start()

    def _fim_ao_vivo(self):
        self._parar = None
        self.btn_loop.configure(state="normal", text="Ligar loopback")
        self._termina(f"Loopback parado. A última captura guarda até {GUARDA_MAX_S:.0f} s "
                      "do fim; salve ou toque.")

    def _loop_placa_liga(self, ligar: bool):
        try:
            cli = self._cliente()
            audio.loopback(cli, "codec" if ligar else "desligado")
        except Exception as e:
            messagebox.showerror("Loopback", str(e), parent=self)
            return
        self._loop_placa = ligar
        self.btn_loop.configure(text="Desligar loopback" if ligar else "Ligar loopback")
        self.status.set("Loopback na placa LIGADO: a entrada do codec sai na LINE-out, "
                        "pela FPGA. Fica ligado até desligar aqui (ou fechar a janela)."
                        if ligar else "Loopback na placa desligado: a saída fica em silêncio.")

    # ---- reprodução -----------------------------------------------------------------
    def _on_arquivo(self):
        caminho = filedialog.askopenfilename(parent=self, title="Sinal para tocar",
                                             filetypes=sinal_arquivo.TIPOS_DIALOGO)
        if not caminho:
            return
        try:
            s = sinal_arquivo.carregar_sinal(caminho)
        except Exception as e:
            messagebox.showerror("Arquivo", str(e), parent=self)
            return
        fs = s.fs if s.fs != 1.0 else audio.FS
        self._arquivo = (np.asarray(s.x, dtype=np.float64), fs, os.path.basename(caminho))
        aviso = "" if s.fs != 1.0 else " — sem fs no arquivo: tocado a 48 828 Hz"
        self.var_arq.set(f"{os.path.basename(caminho)}: {s.x.size} amostras, "
                         f"{s.x.size / fs:.2f} s{aviso}")

    def _sinal_para_tocar(self) -> tuple[np.ndarray, float, str]:
        f = self.var_fonte.get()
        if f == "Gerador":
            return self._gera()
        if f == "Última captura":
            if self._captura is None:
                raise ValueError("ainda não há captura: use Capturar ou o loopback")
            return self._captura, audio.FS, "a última captura"
        if self._arquivo is None:
            raise ValueError("escolha um arquivo")
        x, fs, nome = self._arquivo
        return x, fs, nome

    def _gera(self) -> tuple[np.ndarray, float, str]:
        """O sinal do gerador, ja em FS, com 10 ms de rampa nas pontas (sem
        estalo no comeco e no fim)."""
        forma = self.var_forma.get()
        freq = self._num(self.var_freq, "f", 1, audio.FS / 2)
        amp = self._num(self.var_amp, "Amplitude", 0, 1)
        dur = self._num(self.var_tdur, "Duração", 0.01, 600)
        t = np.arange(int(round(dur * audio.FS))) / audio.FS
        if forma == "Senoide":
            x, nome = np.sin(2 * np.pi * freq * t), f"senoide de {freq:g} Hz"
        elif forma == "Quadrada":
            x, nome = np.where(np.sin(2 * np.pi * freq * t) >= 0, 1.0, -1.0), \
                f"quadrada de {freq:g} Hz"
        elif forma == "Dente de serra":
            x, nome = 2.0 * np.mod(freq * t, 1.0) - 1.0, f"dente de serra de {freq:g} Hz"
        elif forma.startswith("Varredura"):
            f2 = self._num(self.var_f2, "f2", 1, audio.FS / 2)
            fase = 2 * np.pi * (freq * t + (f2 - freq) * t * t / (2 * dur))
            x, nome = np.sin(fase), f"varredura de {freq:g} a {f2:g} Hz"
        else:
            x, nome = np.random.default_rng().uniform(-1.0, 1.0, t.size), "ruído branco"
        borda = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.01)
        return amp * borda * x, audio.FS, nome

    def _on_tocar(self):
        try:
            x, fs, nome = self._sinal_para_tocar()
            cli = self._cliente()
        except Exception as e:
            messagebox.showerror("Reproduzir", str(e), parent=self)
            return
        if self.var_norm.get() and self.var_fonte.get() != "Gerador":
            x = np.asarray(x, dtype=np.float64)
            pico = float(np.max(np.abs(x))) if x.size else 0.0
            if pico > 0:
                x = 0.9 * x / pico
        elif np.issubdtype(np.asarray(x).dtype, np.integer):
            x = np.asarray(x, dtype=np.float64) / 32768.0
        dur = len(x) / fs
        self._ocupado = True
        self._botoes(False)
        self.status.set(f"Tocando {nome} ({dur:.2f} s) na LINE-out da placa...")
        self._mostra_sinal(np.asarray(x, dtype=np.float64), fs, f"tocando: {nome}")

        def worker():
            try:
                r = audio.reproduzir(cli, x, fs=fs)
                msg = (f"Tocou {nome}: {r['quadros']} quadros ({r['segundos']:.2f} s)."
                       if r["termino"] == "completa" else
                       f"Tocou {nome}, mas o fim foi “{r['termino']}”: a rede atrasou "
                       "e houve um trecho com som errado.")
                self.after(0, lambda: self._fim_tocar(msg))
            except Exception as e:
                self.after(0, lambda err=e: self._erro(err))
        threading.Thread(target=worker, daemon=True).start()

    def _fim_tocar(self, msg: str):
        self._ocupado = False
        self._botoes(True)
        self.status.set(msg)

    # ---- filtrar na placa ------------------------------------------------------------------
    def _troca_origem_filtro(self):
        self.fr_aqui.pack_forget()
        self.fr_proj.pack_forget()
        orig = self.var_forig.get()
        if orig == ORIGENS_FILTRO[0]:
            self.fr_aqui.pack(fill="x")
            return
        self.fr_proj.pack(fill="x")
        qual = "IIR" if orig == ORIGENS_FILTRO[1] else "FIR"
        self.btn_proj.configure(text=f"Abrir o projetista {qual}…")
        guardado = self._proj.get(qual)
        self.var_fproj.set(guardado["texto"] if guardado else
                           f"(nenhum filtro do projetista {qual} ainda)")

    def _troca_classe(self):
        """IIR: metodo = aproximacao, 'Ordem'. FIR: metodo = janela,
        'Coeficientes'. A dica diz quais campos valem."""
        if self.var_fclasse.get() == "IIR":
            self.cb_aprox.configure(values=list(APROX_IIR))
            if self.var_faprox.get() not in APROX_IIR:
                self.var_faprox.set(next(iter(APROX_IIR)))
            self.lb_ordem.configure(text="Ordem")
            if int(float(self.var_fordem.get() or 0)) > 32:
                self.var_fordem.set("4")
            self.var_fdica.set("Ripple: Chebyshev I e elíptico. Atenuação: Chebyshev II e "
                               "elíptico. f2: passa-faixa e rejeita-faixa. Roda no bloco IIR "
                               "da placa (até 16 seções).")
        else:
            self.cb_aprox.configure(values=list(JANELAS_FIR))
            if self.var_faprox.get() not in JANELAS_FIR:
                self.var_faprox.set(next(iter(JANELAS_FIR)))
            self.lb_ordem.configure(text="Coeficientes")
            if int(float(self.var_fordem.get() or 0)) < 8:
                self.var_fordem.set("101")
            self.var_fdica.set("FIR pelo método das janelas (β só na Kaiser). f2: passa-faixa "
                               "e rejeita-faixa. Roda no bloco FIR da placa (até 1024 "
                               "coeficientes); cada bloco de 1024 amostras leva ~0,2 s, perto "
                               "de 10 vezes o tempo real.")

    def _on_projetista(self):
        qual = "IIR" if self.var_forig.get() == ORIGENS_FILTRO[1] else "FIR"

        def aplicar(coef, descricao="", fs=None):
            coef = np.asarray(coef, dtype=np.float64)
            if qual == "IIR":
                filtro = {"tipo": "iir", "sos": np.atleast_2d(coef)}
                texto = f"{filtro['sos'].shape[0]} seções"
            else:
                filtro = {"tipo": "fir", "h": coef.ravel()}
                texto = f"{coef.size} coeficientes"
            if descricao:
                texto += f" — {descricao[:60]}"
            if fs:
                texto += f"\nprojetado para fs = {fs:g} Hz"
            filtro.update(desc=descricao or f"do projetista {qual}", fs=fs, texto=texto)
            self._proj[qual] = filtro
            self.var_fproj.set(texto)

        if qual == "IIR":
            IIRDesignerWindow(self, on_apply=aplicar)
        else:
            FIRDesignerWindow(self, on_apply=aplicar)

    def _sinal_para_filtrar(self) -> tuple[np.ndarray, float, str]:
        if self.var_ffonte.get() == FONTES_FILTRAR[0]:
            if self._captura is None:
                raise ValueError("ainda não há captura: use Capturar ou o loopback")
            # o canal esquerdo; com o microfone os dois canais sao iguais
            return self._captura[:, 0].astype(np.float64) / 32768.0, audio.FS, "a última captura"
        if self._arquivo is None:
            raise ValueError("escolha um arquivo em Reproduzir → Fonte: Arquivo")
        x, fs, nome = self._arquivo
        return np.asarray(x, dtype=np.float64), fs, nome

    def _projeta_aqui(self, fs: float) -> dict:
        from scipy import signal
        tipo = TIPOS_FILTRO[self.var_ftipo.get()]
        f1 = self._num(self.var_ff1, "f1", 1, fs / 2 - 1)
        if tipo in ("bandpass", "bandstop"):
            f2 = self._num(self.var_ff2, "f2", f1 + 1, fs / 2 - 1)
            wn, faixa = [f1, f2], f"{f1:g}–{f2:g} Hz"
        else:
            wn, faixa = f1, f"{f1:g} Hz"
        metodo = self.var_faprox.get()
        if self.var_fclasse.get() == "IIR":
            ordem = int(self._num(self.var_fordem, "Ordem", 1, 32))
            ftype = APROX_IIR[metodo]
            rp = self._num(self.var_frp, "Ripple", 0.01, 20) if ftype in ("cheby1", "ellip") else None
            rs = self._num(self.var_frs, "Atenuação", 1, 200) if ftype in ("cheby2", "ellip") else None
            # O scipy poe o ganho inteiro na 1a secao: num passa-baixas de 1 kHz
            # a 48,8 kHz os b dela viram 1 LSB em Q15.16 (espurios medidos a
            # -36 dB). Distribuir o ganho, como o projetista IIR faz, os leva a
            # centenas de LSB (-88 dB).
            sos = signal.iirfilter(ordem, wn, rp=rp, rs=rs, btype=tipo, ftype=ftype,
                                   fs=fs, output="sos")
            sos = iir.distribui_ganho(sos)
            return {"tipo": "iir", "sos": sos,
                    "desc": f"IIR {metodo} ordem {ordem}, {self.var_ftipo.get()} {faixa}"}
        n = int(self._num(self.var_fordem, "Coeficientes", 3, cfg.CONV_N_MAX))
        if tipo in ("highpass", "bandstop") and n % 2 == 0:
            n += 1                # passa-altas e rejeita-faixa precisam de n impar
        janela = JANELAS_FIR[metodo]
        if janela == "kaiser":
            janela = ("kaiser", self._num(self.var_fbeta, "β", 0, 30))
        h = signal.firwin(n, wn, window=janela, pass_zero=tipo, fs=fs)
        return {"tipo": "fir", "h": h,
                "desc": f"FIR {metodo}, {n} coeficientes, {self.var_ftipo.get()} {faixa}"}

    def _filtro_escolhido(self, fs: float) -> dict:
        """O filtro escolhido, conferido para o hardware:
        {"tipo": "iir", "sos"} ou {"tipo": "fir", "h"}, mais "desc"."""
        orig = self.var_forig.get()
        if orig == ORIGENS_FILTRO[0]:
            f = self._projeta_aqui(fs)
        else:
            qual = "IIR" if orig == ORIGENS_FILTRO[1] else "FIR"
            if qual not in self._proj:
                raise ValueError(f"abra o projetista {qual} e aplique um filtro")
            f = dict(self._proj[qual])
            if f.get("fs") and abs(f["fs"] - fs) > 1e-6 * fs:
                raise ValueError(f"o filtro foi projetado para fs = {f['fs']:g} Hz e o sinal "
                                 f"tem fs = {fs:g} Hz: projete de novo com a fs do sinal")
        if f["tipo"] == "iir":
            if f["sos"].shape[0] > cfg.IIR_SECOES_MAX:
                raise ValueError(f"{f['sos'].shape[0]} seções; o bloco IIR aceita "
                                 f"{cfg.IIR_SECOES_MAX} (ordem {2 * cfg.IIR_SECOES_MAX})")
            viab = iir.verifica_viabilidade(f["sos"], cfg.IIR_FRAC_BITS, 32, simular=False)
            if viab["veredito"] == "recusar":
                raise ValueError("o filtro não cabe em Q15.16:\n\n" + "\n\n".join(viab["motivos"]))
        elif f["h"].size > cfg.CONV_N_MAX:
            raise ValueError(f"{f['h'].size} coeficientes; o bloco FIR aceita {cfg.CONV_N_MAX}")
        return f

    def _resposta(self, f: dict, fs: float, n: int = 8192):
        """(freqs, H) com os coeficientes QUANTIZADOS que vao para a placa."""
        if f["tipo"] == "iir":
            c = np.asarray(iir.coeficientes_inteiros(f["sos"], cfg.IIR_FRAC_BITS, 32),
                           dtype=np.float64) / 65536.0
            sos_q = np.column_stack([c[:, 0:3], np.ones(len(c)), c[:, 3:5]])
            return iir.resposta_sos(sos_q, n, fs)
        hq = np.asarray(dsp.float_to_q1516(f["h"]), dtype=np.float64) / 65536.0
        fr = np.arange(n) * (fs / 2) / (n - 1)
        H = np.exp(-2j * np.pi * np.outer(fr / fs, np.arange(hq.size))) @ hq
        return fr, H

    def atraso_de_grupo(self, f: dict, fs: float, f0: float) -> float:
        """Atraso de grupo do filtro em f0, em segundos: -d(fase)/d(omega).
        E o atraso que o envelope de um sinal perto de f0 sofre ao passar pelo
        filtro -- existe em qualquer filtro, tambem em tempo real. Num FIR de
        fase linear e (N-1)/2 amostras em toda a banda."""
        if f["tipo"] == "fir":
            h = f["h"]
            if np.allclose(h, h[::-1]) or np.allclose(h, -h[::-1]):
                return (h.size - 1) / 2.0 / fs
        fr, H = self._resposta(f, fs, 16384)
        w = 2 * np.pi * fr / fs
        gd = -np.gradient(np.unwrap(np.angle(H)), w)
        return float(np.interp(f0, fr, gd)) / fs

    def _on_filtrar(self):
        try:
            x, fs, nome = self._sinal_para_filtrar()
            f = self._filtro_escolhido(fs)
            nota = ""
            if f["tipo"] == "iir":
                aquec = blocos.aquecimento_iir(f["sos"], cfg.IIR_FRAC_BITS)
                limite = cfg.IIR_N_MAX - cfg.IIR_N_MAX // 8
                if x.size > cfg.IIR_N_MAX and aquec > limite:
                    # O aquecimento estimado tem 50 % de folga. Com o maximo que
                    # o bloco permite, o que sobra do transitorio na emenda e
                    # |p|^limite (p = o polo mais externo): se for desprezivel,
                    # segue com ele e diz quanto.
                    resto_db = 20 * np.log10(max(polo_max(f["sos"]) ** limite, 1e-300))
                    if resto_db > -90:
                        raise ValueError(
                            f"este filtro precisa de {aquec} amostras de aquecimento por "
                            f"bloco, e o bloco da placa tem {cfg.IIR_N_MAX}: os polos estão "
                            f"perto demais do círculo unitário para a fs de {fs:g} Hz (com "
                            f"{limite} amostras, as emendas entre blocos ficariam a "
                            f"{resto_db:.0f} dB). Suba a frequência de corte, baixe a ordem "
                            f"ou o ripple, ou use um FIR.")
                    aquec = limite
                    nota = (f" Aquecimento reduzido a {limite} amostras por bloco: as emendas "
                            f"ficam a {resto_db:.0f} dB.")
            cli = self._cliente()
        except Exception as e:
            messagebox.showerror("Filtrar na placa", str(e), parent=self)
            return
        desc = f["desc"]
        self._ocupado = True
        self._botoes(False)
        self.status.set(f"Filtrando {nome} ({x.size / fs:.2f} s) na placa: {desc}...")

        def progresso(feitos, total):
            self.after(0, lambda: self.status.set(
                f"Filtrando {nome} na placa: bloco {feitos} de {total} ({desc})"))

        def worker():
            try:
                t0 = time.monotonic()
                saturou = False
                if f["tipo"] == "iir":
                    coefs = iir.coeficientes_inteiros(f["sos"], cfg.IIR_FRAC_BITS, 32)
                    yq, saturou = blocos.iir_por_blocos(x, blocos.IirPlaca(cli, coefs), aquec,
                                                        cfg.IIR_N_MAX, progresso)
                    y = np.asarray(yq, dtype=np.float64) / 65536.0
                else:
                    # overlap-add no bloco FIR (conv1d); a saida causal tem o
                    # tamanho da entrada
                    y = blocos.conv_por_blocos(x, f["h"], blocos.FirPlaca(cli),
                                               cfg.CONV_N_MAX, progresso)[:x.size]
                dt = time.monotonic() - t0
                self.after(0, lambda: self._fim_filtrar(x, y, fs, f, nome, saturou, dt, nota))
            except Exception as e:
                self.after(0, lambda err=e: self._erro(err))
        threading.Thread(target=worker, daemon=True).start()

    def _fim_filtrar(self, x, y, fs, f, nome, saturou, dt, nota=""):
        self._filtragem = {"x": x, "y": y, "fs": fs, "filtro": f, "nome": nome, "desc": f["desc"]}
        # O atraso desta opcao (gravar -> filtrar na placa -> tocar), do
        # comeco do som ate ouvi-lo filtrado: a gravacao inteira tem de
        # terminar antes de filtrar, depois vem o processamento na placa, e
        # o atraso de grupo do proprio filtro.
        dur = x.size / fs
        f0 = audio.freq_dominante(x, fs)
        gd = self.atraso_de_grupo(f, fs, f0) if np.isfinite(f0) else float("nan")
        self._atraso = {"gravacao": dur, "proc": dt, "grupo": gd, "f0": f0}
        self.var_medidas.set(
            f"atraso desta opção (gravar → placa → tocar)\n"
            f"  gravação    {dur:8.2f} s  (o sinal inteiro)\n"
            f"  filtragem   {dt:8.2f} s  ({dt / dur:.1f}× o tempo real)\n"
            f"  do filtro   {gd * 1e3:8.3f} ms (atraso de grupo em {f0:.0f} Hz)\n"
            f"  total       {dur + dt + gd:8.2f} s  até começar a ouvir\n"
            f"em tempo real seria só o do filtro + 20 µs")
        self._ocupado = False
        self._botoes(True)
        self._eixos_prontos = None
        self._desenha_filtragem()
        aviso = "  SATUROU em alguma amostra (a saída passou do Q15.16)." if saturou else ""
        self.status.set(f"Filtrado na placa: {nome}, {x.size} amostras em {dt:.1f} s "
                        f"({f['desc']}); atraso até ouvir: {dur + dt:.1f} s. Toque a entrada "
                        f"e a saída para comparar.{aviso}{nota}")

    def _desenha_filtragem(self):
        """Entrada e saida no tempo (20 ms do meio do sinal) e os espectros
        medios das duas (blocos de 4096 com a janela escolhida), com |H(f)| dos
        coeficientes quantizados -- o que a placa de fato aplicou."""
        d = self._filtragem
        x, y, fs, f = d["x"], d["y"], d["fs"], d["filtro"]
        completo, em_db = self.var_completo.get(), self.var_db.get()
        self._vista_filtro = True
        self._eixos_prontos = None
        for ax in (self.ax_t, self.ax_f):
            ax.clear()
        ax = self.ax_t
        m = min(x.size, max(8, int(0.02 * fs)))
        i0 = max(0, x.size // 2 - m // 2)
        t = (i0 + np.arange(m)) / fs * 1e3
        ax.plot(t, x[i0:i0 + m], color=dsp.COLOR_X, linewidth=0.9, label="entrada")
        ax.plot(t, y[i0:i0 + m], color=dsp.COLOR_Y, linewidth=0.9, label="saída (placa)")
        ax.set_xlabel("t (ms)")
        ax.set_ylabel("amplitude (fundo = 1)")
        ax.set_title(f"{d['nome']}: 20 ms do meio, entrada e saída", fontsize=10)
        ax.legend(fontsize=7, loc="upper right")
        theme.style_plot_axes(ax)

        nfft = int(min(4096, 2 ** int(np.floor(np.log2(max(x.size, 8))))))
        w = janela_de(self.var_janela.get(), nfft)
        # A media comeca depois do transitorio de partida (o filtro sai do
        # estado zero): no IIR, a estimativa do aquecimento dos blocos; no FIR,
        # o comprimento do filtro.
        if f["tipo"] == "iir":
            try:
                ini = blocos.aquecimento_iir(f["sos"], cfg.IIR_FRAC_BITS)
            except ValueError:
                ini = 0
        else:
            ini = f["h"].size
        if x.size - ini < nfft:
            ini = 0

        def espectro(v):
            v = np.asarray(v, dtype=np.float64)
            pedacos = [v[k:k + nfft] for k in range(ini, v.size - nfft + 1, nfft // 2)][:200]
            acc = None
            for pd in pedacos:
                X = np.abs(np.fft.fft((pd - pd.mean()) * w) if completo
                           else np.fft.rfft((pd - pd.mean()) * w)) / (np.sum(w) / 2.0)
                acc = X * X if acc is None else acc + X * X
            return np.sqrt(acc / len(pedacos))

        X, Y = espectro(x), espectro(y)
        fr = np.arange(X.size) * fs / nfft / 1e3
        ax = self.ax_f
        if em_db:
            ax.plot(fr, 20 * np.log10(np.maximum(X, 1e-7)), color=dsp.COLOR_X,
                    linewidth=0.8, label="entrada")
            ax.plot(fr, 20 * np.log10(np.maximum(Y, 1e-7)), color=dsp.COLOR_Y,
                    linewidth=0.8, label="saída (placa)")
            fh, H = self._resposta(f, fs, 4096)
            hdb = 20 * np.log10(np.maximum(np.abs(H), 1e-7))
            if completo:
                fh = np.concatenate([fh, fs - fh[::-1]])
                hdb = np.concatenate([hdb, hdb[::-1]])
            ax.plot(fh / 1e3, hdb, color="black", linewidth=1.0, linestyle="--",
                    label="|H(f)| do filtro (dB)")
            ax.set_ylim(-140, 10)
            ax.set_ylabel("dBFS  (|H| em dB)")
        else:
            ax.plot(fr, X, color=dsp.COLOR_X, linewidth=0.8, label="entrada")
            ax.plot(fr, Y, color=dsp.COLOR_Y, linewidth=0.8, label="saída (placa)")
            ax.set_ylim(0, max(1e-4, 1.1 * float(max(np.max(X), np.max(Y)))))
            ax.set_ylabel("amplitude de pico (fundo = 1)")
        ax.set_xlim(0, (fs if completo else fs / 2) / 1e3)
        if completo:
            ax.axvline(fs / 2 / 1e3, color=theme.COLORS["axis"], linewidth=0.8, linestyle=":")
        ax.set_xlabel("f (kHz)")
        ax.set_title(f"espectro médio (sem o transitório de {ini} amostras) — {d['desc']}",
                     fontsize=9)
        ax.legend(fontsize=7, loc="upper right")
        theme.style_plot_axes(ax)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _toca_filtragem(self, qual: str):
        d = self._filtragem
        if d is None:
            return
        try:
            cli = self._cliente()
        except Exception as e:
            messagebox.showerror("Tocar", str(e), parent=self)
            return
        v = np.asarray(d[qual], dtype=np.float64)
        pico = float(np.max(np.abs(v))) if v.size else 0.0
        if self.var_norm.get() and pico > 0:
            v = 0.9 * v / pico
        nome = "a entrada" if qual == "x" else "a saída filtrada"
        self._ocupado = True
        self._botoes(False)
        self.status.set(f"Tocando {nome} ({v.size / d['fs']:.2f} s) na LINE-out...")

        def worker():
            try:
                r = audio.reproduzir(cli, v, fs=d["fs"])
                self.after(0, lambda: self._fim_tocar(
                    f"Tocou {nome}: {r['segundos']:.2f} s, fim {r['termino']}."))
            except Exception as e:
                self.after(0, lambda err=e: self._erro(err))
        threading.Thread(target=worker, daemon=True).start()

    def _on_salva_filtragem(self):
        d = self._filtragem
        if d is None:
            return
        caminho = filedialog.asksaveasfilename(
            parent=self, title="Salvar a saída filtrada", defaultextension=".wav",
            filetypes=[("Áudio (.wav)", "*.wav"), ("NumPy (.npy)", "*.npy")])
        if not caminho:
            return
        try:
            if caminho.lower().endswith(".npy"):
                np.save(caminho, d["y"])
            else:
                from scipy.io import wavfile
                y = d["y"]
                pico = float(np.max(np.abs(y))) if y.size else 0.0
                esc = 1.0 / pico if pico > 1.0 else 1.0     # .wav int16 nao passa de 1
                wavfile.write(caminho, int(round(d["fs"])),
                              np.round(np.clip(y * esc, -1, 1) * 32767).astype(np.int16))
        except Exception as e:
            messagebox.showerror("Salvar", str(e), parent=self)
            return
        self.status.set(f"Saída filtrada salva em {caminho}")

    # ---- salvar -----------------------------------------------------------------------
    def _on_salvar(self):
        if self._captura is None:
            return
        caminho = filedialog.asksaveasfilename(
            parent=self, title="Salvar captura", defaultextension=".wav",
            filetypes=[("Áudio (.wav)", "*.wav"), ("NumPy (.npy)", "*.npy")])
        if not caminho:
            return
        try:
            if caminho.lower().endswith(".npy"):
                np.save(caminho, self._captura)
            else:
                from scipy.io import wavfile
                wavfile.write(caminho, int(round(audio.FS)), self._captura)
        except Exception as e:
            messagebox.showerror("Salvar", str(e), parent=self)
            return
        self.status.set(f"Salvo: {caminho} ({self._captura.shape[0]} quadros, estéreo, "
                        "16 bits)")

    # ---- tela ---------------------------------------------------------------------------
    def _prepara_eixos(self, n: int, titulo: str):
        chave = (n, titulo, self.var_janela.get(), self.var_db.get(),
                 self.var_completo.get())
        if self._eixos_prontos == chave:
            return
        self._eixos_prontos = chave
        for ax in (self.ax_t, self.ax_f):
            ax.clear()
        ax = self.ax_t
        (self._l_esq,) = ax.plot([], [], color=dsp.COLOR_X, linewidth=0.9, label="esquerdo")
        (self._l_dir,) = ax.plot([], [], color=dsp.COLOR_Y, linewidth=0.9, alpha=0.7,
                                 label="direito")
        ax.set_xlim(0, n / audio.FS * 1e3)
        ax.set_ylim(-1.05, 1.05)
        ax.set_xlabel("t (ms)")
        ax.set_ylabel("amplitude (fundo = 1)")
        ax.set_title(titulo, fontsize=10)
        ax.legend(fontsize=7, loc="upper right")
        theme.style_plot_axes(ax)
        ax = self.ax_f
        (self._l_f,) = ax.plot([], [], color=dsp.COLOR_MAG, linewidth=0.9)
        if self.var_completo.get():
            ax.set_xlim(0, audio.FS / 1e3)
            # fs/2 separa o espectro da replica; a faixa sombreada e a replica
            ax.axvspan(audio.FS / 2 / 1e3, audio.FS / 1e3, color=theme.COLORS["axis"],
                       alpha=0.18, linewidth=0)
            ax.axvline(audio.FS / 2 / 1e3, color=theme.COLORS["axis"], linewidth=0.8,
                       linestyle=":")
            ax.text(audio.FS / 2 / 1e3, 0.98, " fs/2", transform=ax.get_xaxis_transform(),
                    ha="left", va="top", fontsize=8, color=theme.COLORS["text"])
            ax.text(0.75 * audio.FS / 1e3, 0.90, "réplica (espelho)",
                    transform=ax.get_xaxis_transform(), ha="center", va="top",
                    fontsize=8, color=theme.COLORS["text"])
        else:
            ax.set_xlim(0, audio.FS / 2 / 1e3)
        if self.var_db.get():
            ax.set_ylim(-140, 0)
            ax.set_ylabel("dBFS")
        else:
            ax.set_ylabel("amplitude de pico (fundo = 1)")
        ax.set_xlabel("f (kHz)")
        ax.set_title(f"|X(f)| do canal esquerdo, janela {self.var_janela.get()} (NumPy)",
                     fontsize=10)
        theme.style_plot_axes(ax)
        self.fig.tight_layout()

    def _desenha_bloco(self, b: np.ndarray, titulo: str):
        n = b.shape[0]
        self._prepara_eixos(n, titulo)
        t = np.arange(n) / audio.FS * 1e3
        self._l_esq.set_data(t, b[:, 0] / 32768.0)
        self._l_dir.set_data(t, b[:, 1] / 32768.0)
        # um microfone da -40 dBFS: com o eixo fixo em +-1 a onda seria uma
        # reta. O eixo acompanha o pico (no minimo +-0,01).
        pico = float(np.max(np.abs(b.astype(np.int32)))) / 32768.0 if n else 0.0
        lim = min(1.05, max(0.01, 1.2 * pico))
        self.ax_t.set_ylim(-lim, lim)
        x = b[:, 0].astype(np.float64) / 32768.0
        w = janela_de(self.var_janela.get(), n)
        # Amplitude de pico de um tom: |X[k]| / (soma da janela / 2). No
        # espectro completo o tom aparece em f e em fs - f, as duas com a mesma
        # leitura (a convencao do analisador espectral).
        xw = (x - x.mean()) * w
        X = np.abs(np.fft.fft(xw) if self.var_completo.get() else np.fft.rfft(xw))
        X = X / (np.sum(w) / 2.0)
        f = np.arange(X.size) * audio.FS / n / 1e3
        if self.var_db.get():
            self._l_f.set_data(f, 20 * np.log10(np.maximum(X, 1e-7)))
        else:
            self._l_f.set_data(f, X)
            self.ax_f.set_ylim(0, max(1e-4, 1.1 * float(np.max(X))))
        self._ultimo = (b, titulo)
        self._vista_filtro = False
        self.canvas.draw_idle()

    def _troca_escala(self):
        """dB <-> linear, janela, replica: refaz os eixos e redesenha o que
        estiver na tela (o ultimo bloco, ou a ultima filtragem)."""
        self._eixos_prontos = None
        if self._vista_filtro and self._filtragem is not None:
            self._desenha_filtragem()
        elif self._ultimo is not None:
            self._desenha_bloco(*self._ultimo)

    def _mostra_sinal(self, x: np.ndarray, fs: float, titulo: str):
        """Mostra o começo do que vai tocar (os primeiros 4096 quadros)."""
        y = audio.para_int16(x[:int(4096 * fs / audio.FS) + 1], fs)[:4096]
        if y.shape[0]:
            self._desenha_bloco(y, titulo)

    def _tela(self, final: bool = False):
        with self._trava:
            b, self._novo = self._novo, None
            total = self._gravado
        if b is not None and b.shape[0] >= 2:
            self._desenha_bloco(b, f"x(t) — último bloco do codec ({b.shape[0]} quadros)")
            pico = int(np.max(np.abs(b.astype(np.int32))))
            self.var_medidas.set(
                f"nível     {audio.nivel_dbfs(b):7.1f} dBFS\n"
                f"pico      {pico:7d}  ({20 * np.log10(max(pico, 1) / 32768):.1f} dBFS)\n"
                f"f maior   {audio.freq_dominante(b):7.0f} Hz\n"
                f"recebido  {total / audio.FS:7.2f} s")
        if self._ocupado and not final:
            self.after(TELA_MS, self._tela)

    def _on_fechar(self):
        if self._parar is not None:
            self._parar.set()
        if self._loop_placa:
            try:
                audio.loopback(self._cliente(), "desligado")
            except Exception:
                pass
        self.destroy()
