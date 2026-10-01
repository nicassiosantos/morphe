"""morphe_app.py — janela principal (hub) do Morphe DSP Toolkit.

Consome o design system de `morphe_theme`. Estrutura:
  - Cabeçalho com título + subtítulo
  - Painel TCP (compartilhado por todas as janelas filhas)
  - Card "Ferramentas FPGA" com ações primárias (inclui o analisador espectral)
  - Card "Comparação" (independente)
  - Link "Sair" discreto no canto inferior direito
"""
from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

import morphe_theme as theme
from signal_generator_window import SignalGeneratorWindow
from aquisicao_window import AquisicaoWindow
from analisador_window import AnalisadorWindow
from conv_window import ConvolutionWindow
from fft_window import FFTWindow
from ifft_window import IFFTWindow
# ESPECTROGRAMA (desligado em 23/09/2026; a janela esta pronta e validada na
# placa -- para reativar, descomentar esta linha, o botao e o callback abaixo):
# from espectrograma_window import EspectrogramaWindow
from fir_window import FIRWindow
from iir_window import IIRWindow
from comparator_window import ComparatorWindow
from soma_window import SomaWindow
from tcp_panel import TcpConfigPanel

# Créditos do rodapé, uma linha cada: (texto, perfil do LinkedIn ou ""). O
# perfil é o final de linkedin.com/in/<perfil> e vira um "LinkedIn" clicável.
CREDITOS = [
    ("Desenvolvido por Antonio Nicassio Santos Lima", "antonio-nicassio-64908a276"),
    ("Baseado no Morphe de Carlos Valadão", "cvaladao"),
    ("Orientação: Prof. Armando Sanca Sanca", ""),
]


# Tamanho da janela principal: abre com LARGURA e a altura do conteúdo (ou da
# tela, se for menor). A largura não encolhe abaixo de LARGURA (o painel de
# placas não quebra linha); a altura encolhe até ALTURA_MIN, e o conteúdo rola.
LARGURA = 600
LARGURA_MIN, ALTURA_MIN = LARGURA, 320


class MorpheMainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Morphe — DSP Toolkit")
        self.configure(bg=theme.COLORS["bg"])

        theme.setup_styles(self)
        self._build_ui()

        # A janela abre do tamanho do conteúdo, se couber na tela; numa tela
        # baixa (notebook, projetor), abre com a altura da tela e o conteúdo
        # rola. Pode ser redimensionada nos dois sentidos: os cards
        # acompanham a largura, e a barra de rolagem aparece só quando falta
        # altura.
        self.update_idletasks()
        conteudo_h = self._conteudo.winfo_reqheight() + self._rodape.winfo_reqheight()
        tela_h = self.winfo_screenheight() - 80     # barra de tarefas, título
        altura = min(conteudo_h, tela_h)
        largura = max(LARGURA, self._conteudo.winfo_reqwidth())
        self.geometry(f"{largura}x{altura}+{max(0, (self.winfo_screenwidth() - largura) // 2)}+20")
        self.minsize(LARGURA_MIN, min(ALTURA_MIN, altura))

    def _build_ui(self):
        # Rodapé fora da área que rola: os créditos e o "Sair" ficam sempre
        # visíveis. Packed antes, para reservar a faixa de baixo.
        self._rodape = ttk.Frame(self, style="Main.TFrame", padding=(28, 8, 28, 16))
        self._rodape.pack(side="bottom", fill="x")
        theme.make_exit_link(self._rodape, on_click=self.destroy).pack(side="right", anchor="s")
        self._creditos(self._rodape).pack(side="left", anchor="w")

        main = self._area_rolavel()

        # Cabeçalho
        header = ttk.Frame(main, style="Main.TFrame")
        header.pack(fill="x", pady=(0, 22))
        ttk.Label(header, text="Morphe", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="DSP Toolkit  ·  DE1-SoC  ·  HPS ↔ FPGA via TCP",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        # Conexão TCP. autoconectar=True: a janela abre já procurando a placa
        # (a lembrada pelo morphe-up.sh primeiro, depois a LAN), para que o
        # aluno não precise saber nem digitar endereço nenhum.
        self.tcp_panel = TcpConfigPanel(main, autoconectar=True)
        self.tcp_panel.pack(fill="x", pady=(0, 16))

        # Ferramentas FPGA (ações primárias)
        tools = ttk.LabelFrame(
            main, text=" Ferramentas FPGA ",
            style="Card.TLabelframe",
            padding=(18, 14, 18, 16),
        )
        tools.pack(fill="x", pady=(0, 12))
        ttk.Label(
            tools, text="Processamento em hardware (Cyclone V)",
            style="SectionHint.TLabel",
        ).pack(anchor="w", pady=(0, 10))

        primary_actions = [
            ("Gerador de Sinais",              self._open_generator),
            ("Aquisição  (ADC da placa)",      self._open_aquisicao),
            ("Analisador espectral  (ADC → FFT na FPGA)", self._open_analisador),
            ("Convolução  (2 sinais → FPGA)",  self._open_conv),
            ("FFT  (1 sinal → FPGA)",          self._open_fft),
            ("IFFT  (espectro de arquivo → FPGA)", self._open_ifft),
            # ESPECTROGRAMA (desligado):
            # ("Espectrograma  (sinal longo → FFTs na FPGA)", self._open_espectrograma),
            ("Filtro FIR  (FPGA)",             self._open_fir),
            ("Filtro IIR  (FPGA)",             self._open_iir),
            ("Soma  (a + b → FPGA, exemplo do roteiro)", self._open_soma),
        ]
        for label, cmd in primary_actions:
            ttk.Button(
                tools, text=label,
                style="Primary.TButton",
                command=cmd,
            ).pack(fill="x", pady=3)

        # Comparação (ferramenta autônoma)
        comparison = ttk.LabelFrame(
            main, text=" Comparação ",
            style="Card.TLabelframe",
            padding=(18, 14, 18, 16),
        )
        comparison.pack(fill="x")
        ttk.Label(
            comparison,
            text="Resultado FPGA salvo em .mrph × referência calculada com NumPy",
            style="SectionHint.TLabel",
        ).pack(anchor="w", pady=(0, 10))
        ttk.Button(
            comparison,
            text="Comparar .mrph (FPGA) × NumPy",
            style="Secondary.TButton",
            command=self._open_comparator,
        ).pack(fill="x", pady=3)

    def _area_rolavel(self) -> ttk.Frame:
        """Um Frame dentro de um Canvas com barra de rolagem vertical. O
        Frame acompanha a largura da janela; a barra só aparece quando o
        conteúdo é mais alto que a janela."""
        externo = ttk.Frame(self, style="Main.TFrame")
        externo.pack(side="top", fill="both", expand=True)
        canvas = tk.Canvas(externo, background=theme.COLORS["bg"],
                           highlightthickness=0, bd=0)
        barra = ttk.Scrollbar(externo, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=barra.set)
        canvas.pack(side="left", fill="both", expand=True)
        self._conteudo = ttk.Frame(canvas, style="Main.TFrame", padding=(28, 22, 28, 0))
        item = canvas.create_window((0, 0), window=self._conteudo, anchor="nw")

        def ajusta(_ev=None):
            canvas.itemconfigure(item, width=canvas.winfo_width())
            canvas.configure(scrollregion=canvas.bbox("all"))
            precisa = self._conteudo.winfo_reqheight() > canvas.winfo_height()
            if precisa and not barra.winfo_ismapped():
                barra.pack(side="right", fill="y", before=canvas)
            elif not precisa and barra.winfo_ismapped():
                barra.pack_forget()
                canvas.yview_moveto(0)

        self._conteudo.bind("<Configure>", ajusta)
        canvas.bind("<Configure>", ajusta)

        # Roda do mouse: <MouseWheel> no Windows e no macOS, Button-4/5 no
        # Linux dos computadores do laboratório. bind_all pega a roda sobre
        # qualquer botão do menu; o teste de toplevel deixa as outras janelas
        # (que também recebem o bind_all) em paz.
        def roda(ev):
            try:
                if ev.widget.winfo_toplevel() is not self:
                    return
            except (AttributeError, KeyError, tk.TclError):
                return
            if not barra.winfo_ismapped():
                return
            passo = -1 if (getattr(ev, "num", 0) == 4 or ev.delta > 0) else 1
            canvas.yview_scroll(passo, "units")

        self.bind_all("<MouseWheel>", roda, add="+")
        self.bind_all("<Button-4>", roda, add="+")
        self.bind_all("<Button-5>", roda, add="+")
        return self._conteudo

    @staticmethod
    def _creditos(parent) -> tk.Frame:
        """Os créditos, discretos: cinza, 9 pt, o link do LinkedIn em azul."""
        bg, cinza, azul = (theme.COLORS["bg"], theme.COLORS["text_muted"],
                           theme.COLORS["primary"])
        fonte = ("TkDefaultFont", 9)
        quadro = tk.Frame(parent, background=bg)
        for texto, perfil in CREDITOS:
            faixa = tk.Frame(quadro, background=bg)
            faixa.pack(anchor="w")
            tk.Label(faixa, text=texto, background=bg, foreground=cinza,
                     font=fonte, bd=0, padx=0).pack(side="left")
            if not perfil:
                continue
            tk.Label(faixa, text="  ·  ", background=bg, foreground=cinza,
                     font=fonte, bd=0, padx=0).pack(side="left")
            link = tk.Label(faixa, text="LinkedIn", background=bg, foreground=azul,
                            font=fonte, cursor="hand2", bd=0, padx=0)
            link.pack(side="left")
            url = f"https://www.linkedin.com/in/{perfil}"
            link.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))
            link.bind("<Enter>", lambda _e, w=link: w.configure(
                font=("TkDefaultFont", 9, "underline")))
            link.bind("<Leave>", lambda _e, w=link: w.configure(font=fonte))
        return quadro

    # ─── Callbacks ───────────────────────────────────────────
    def _open_generator(self):
        SignalGeneratorWindow(self)

    def _open_aquisicao(self):
        AquisicaoWindow(self)

    def _open_analisador(self):
        AnalisadorWindow(self)

    def _open_conv(self):
        ConvolutionWindow(self)

    def _open_fft(self):
        FFTWindow(self)

    def _open_ifft(self):
        IFFTWindow(self)

    # ESPECTROGRAMA (desligado):
    # def _open_espectrograma(self):
    #     EspectrogramaWindow(self)

    def _open_fir(self):
        FIRWindow(self)

    def _open_iir(self):
        IIRWindow(self)

    def _open_soma(self):
        SomaWindow(self)

    def _open_comparator(self):
        ComparatorWindow(self)


if __name__ == "__main__":
    app = MorpheMainWindow()
    app.mainloop()
