"""morphe_app.py — janela principal (hub) do Morphe DSP Toolkit.

Consome o design system de `morphe_theme`. Estrutura:
  - Cabeçalho com título + subtítulo
  - Painel TCP (compartilhado por todas as janelas filhas)
  - Card "Ferramentas FPGA" com ações primárias
  - Card "Comparação" (independente)
  - Link "Sair" discreto no canto inferior direito
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import morphe_theme as theme
from signal_generator_window import SignalGeneratorWindow
from conv_window import ConvolutionWindow
from fft_window import FFTWindow
from ifft_window import IFFTWindow
from fir_window import FIRWindow
from comparator_window import ComparatorWindow
from tcp_panel import TcpConfigPanel


class MorpheMainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Morphe — DSP Toolkit")
        self.configure(bg=theme.COLORS["bg"])

        theme.setup_styles(self)
        self._build_ui()

        # Em vez de fixar uma altura "no chute" (que sobrava e deixava
        # aquele vão vazio antes do "Sair"), deixamos o próprio Tk medir o
        # conteúdo real e encaixamos a janela nele — assim o rodapé encosta
        # logo abaixo do último card. Robusto a DPI/fonte: a altura vem do
        # que de fato foi renderizado.
        #   - largura travada em 600
        #   - altura = conteúdo, mas ainda arrastável para baixo
        self.update_idletasks()
        content_h = self.winfo_reqheight()
        self.geometry(f"600x{content_h}")
        self.minsize(600, content_h)
        self.resizable(False, True)

    def _build_ui(self):
        main = ttk.Frame(self, style="Main.TFrame", padding=(28, 22, 28, 16))
        main.pack(fill="both", expand=True)

        # Rodapé pinado à base via side="bottom" — packed antes do resto
        # para reservar a faixa inferior.
        footer = ttk.Frame(main, style="Main.TFrame")
        footer.pack(side="bottom", fill="x", pady=(8, 0))
        theme.make_exit_link(footer, on_click=self.destroy).pack(side="right")

        # Cabeçalho
        header = ttk.Frame(main, style="Main.TFrame")
        header.pack(fill="x", pady=(0, 22))
        ttk.Label(header, text="Morphe", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="DSP Toolkit  ·  DE1-SoC  ·  HPS ↔ FPGA via TCP",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        # Conexão TCP
        self.tcp_panel = TcpConfigPanel(main)
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
            ("Convolução  (2 sinais → FPGA)",  self._open_conv),
            ("FFT  (1 sinal → FPGA)",          self._open_fft),
            ("IFFT  (espectro de arquivo → FPGA)", self._open_ifft),
            ("Filtro FIR  (FPGA)",             self._open_fir),
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

    # ─── Callbacks ───────────────────────────────────────────
    def _open_generator(self):
        SignalGeneratorWindow(self)

    def _open_conv(self):
        ConvolutionWindow(self)

    def _open_fft(self):
        FFTWindow(self)

    def _open_ifft(self):
        IFFTWindow(self)

    def _open_fir(self):
        FIRWindow(self)

    def _open_comparator(self):
        ComparatorWindow(self)


if __name__ == "__main__":
    app = MorpheMainWindow()
    app.mainloop()
