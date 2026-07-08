"""
signal_panel.py — widget reutilizável que gera um Signal.

Consome o design system de `morphe_theme` (card branco + botão "Gerar"
em estilo outline azul). Reutilizado pelas telas de convolução (duas
instâncias), de FFT (uma instância) e pelo gerador. Aceita um `max_N`
opcional para impor o limite do hardware.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

import dsp_core as dsp
import morphe_theme as theme


SIGNAL_TYPES = [
    "Degrau unitário",
    "Impulso unitário",
    "Senóide",
    "Exponencial",
    "Retangular",
]

# Layout do formulário de geração. Um único grid de 2 colunas partilhado por
# TODOS os campos (Tipo, N e parâmetros dinâmicos) garante que rótulos e
# entradas fiquem alinhados na mesma margem e com a mesma largura.
_LABEL_COL_MIN = 96     # largura mínima da coluna de rótulos (col 0)
_INPUT_WIDTH = 14       # largura-base de todos os campos de entrada (col 1)
_PARAMS_ROW0 = 2        # primeira linha dos parâmetros dinâmicos
_GERAR_ROW = 90         # linha "alta" reservada ao botão Gerar (sempre embaixo)


class SignalPanel(ttk.LabelFrame):
    """
    Painel compacto para configurar e gerar um sinal.
    Use .build() para obter um dsp.Signal a partir dos campos preenchidos.
    """

    def __init__(self, parent, title: str = "Sinal",
                 on_generate: Optional[Callable[["SignalPanel"], None]] = None,
                 default_N: int = 32, default_type: str = "Impulso unitário",
                 max_N: Optional[int] = None):
        # Garante os estilos do tema mesmo se o painel for instanciado
        # fora do hub principal (setup_styles é idempotente).
        theme.setup_styles(parent)

        super().__init__(
            parent, text=f" {title} ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        self._on_generate = on_generate
        self._max_N = max_N

        # Grid de duas colunas partilhado por TODOS os campos: rótulos na
        # coluna 0 (largura fixa) e entradas na coluna 1 (expansível, sticky
        # "ew"). Assim "Tipo", "N" e cada parâmetro dinâmico alinham na mesma
        # margem esquerda e recebem a mesma largura — a sugestão de
        # alinhamento da revisão de UX.
        self.columnconfigure(0, minsize=_LABEL_COL_MIN, weight=0)
        self.columnconfigure(1, weight=1)

        # Linha 0 — Tipo
        ttk.Label(self, text="Tipo", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6))
        self.signal_type = tk.StringVar(value=default_type)
        combo = ttk.Combobox(self, textvariable=self.signal_type,
                             values=SIGNAL_TYPES, state="readonly",
                             width=_INPUT_WIDTH)
        combo.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_params())

        # Linha 1 — N
        n_label = "N" if max_N is None else f"N (máx {max_N})"
        ttk.Label(self, text=n_label, style="Card.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, 6))
        self.var_N = tk.StringVar(value=str(default_N))
        ttk.Entry(self, textvariable=self.var_N, width=_INPUT_WIDTH).grid(
            row=1, column=1, sticky="ew", pady=(0, 6))

        # Parâmetros dinâmicos ocupam as linhas 2..N do MESMO grid.
        # Guardamos os widgets criados para removê-los ao trocar de tipo.
        self.param_vars: dict[str, tk.StringVar] = {}
        self._param_widgets: list[tk.Widget] = []

        # Botão Gerar numa linha "alta" fixa → fica sempre abaixo dos
        # parâmetros, qualquer que seja a quantidade deles (o grid apenas
        # ignora as linhas intermediárias vazias).
        ttk.Button(self, text="Gerar", style="Outline.TButton",
                   command=self._on_gen_click).grid(
            row=_GERAR_ROW, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        self._refresh_params()

    # ---- parâmetros dinâmicos --------------------------------------------

    def _refresh_params(self):
        # Remove os widgets de parâmetros da rodada anterior.
        for w in self._param_widgets:
            w.destroy()
        self._param_widgets.clear()
        self.param_vars.clear()

        self._row = _PARAMS_ROW0
        t = self.signal_type.get()
        if t == "Degrau unitário":
            self._add("n0", "n0", "0")
        elif t == "Impulso unitário":
            self._add("n0", "n0", "0")
        elif t == "Senóide":
            self._add("A", "A", "1.0")
            self._add("f (Hz)", "f", "5.0")
            self._add("fs (Hz)", "fs", "64.0")
            self._add("φ (rad)", "phase", "0.0")
        elif t == "Exponencial":
            self._add("A", "A", "1.0")
            self._add("α", "alpha", "0.9")
            # combobox de "modo" — no MESMO grid, mesma coluna/largura
            lbl = ttk.Label(self, text="modo", style="Card.TLabel")
            lbl.grid(row=self._row, column=0, sticky="w", pady=(0, 4))
            self.param_vars["mode"] = tk.StringVar(value="discrete")
            cb = ttk.Combobox(self, textvariable=self.param_vars["mode"],
                              values=["discrete", "continuous"],
                              state="readonly", width=_INPUT_WIDTH)
            cb.grid(row=self._row, column=1, sticky="ew", pady=(0, 4))
            self._param_widgets.extend([lbl, cb])
            self._row += 1
        elif t == "Retangular":
            self._add("A", "A", "1.0")
            self._add("Início", "n_start", "0")
            self._add("Largura", "width", "8")

    def _add(self, label: str, key: str, default: str):
        lbl = ttk.Label(self, text=label, style="Card.TLabel")
        lbl.grid(row=self._row, column=0, sticky="w", pady=(0, 4))
        var = tk.StringVar(value=default)
        self.param_vars[key] = var
        ent = ttk.Entry(self, textvariable=var, width=_INPUT_WIDTH)
        ent.grid(row=self._row, column=1, sticky="ew", pady=(0, 4))
        self._param_widgets.extend([lbl, ent])
        self._row += 1

    # ---- leitura ---------------------------------------------------------

    def _gi(self, key: str, name: str) -> int:
        try:
            return int(self.param_vars[key].get())
        except ValueError as e:
            raise ValueError(f"'{name}' deve ser inteiro") from e

    def _gf(self, key: str, name: str) -> float:
        try:
            return float(self.param_vars[key].get())
        except ValueError as e:
            raise ValueError(f"'{name}' deve ser numérico") from e

    def build(self) -> dsp.Signal:
        """Monta o Signal com base no estado atual dos campos."""
        try:
            N = int(self.var_N.get())
        except ValueError as e:
            raise ValueError("N deve ser inteiro") from e
        if N <= 0:
            raise ValueError("N deve ser > 0")
        if self._max_N is not None and N > self._max_N:
            raise ValueError(
                f"N={N} excede o máximo permitido pelo hardware ({self._max_N}). "
                f"Reduza N ou — quando aplicável — o sinal será automaticamente "
                f"completado com zeros até atingir o tamanho do hardware."
            )

        t = self.signal_type.get()
        if t == "Degrau unitário":
            return dsp.gen_unit_step(N, self._gi("n0", "n0"))
        if t == "Impulso unitário":
            return dsp.gen_unit_impulse(N, self._gi("n0", "n0"))
        if t == "Senóide":
            A = self._gf("A", "A")
            f = self._gf("f", "f")
            fs = self._gf("fs", "fs")
            phase = self._gf("phase", "φ")
            if fs <= 0:
                raise ValueError("fs deve ser > 0")
            return dsp.gen_sinusoid(N, A, f, fs, phase)
        if t == "Exponencial":
            return dsp.gen_exponential(
                N, self._gf("A", "A"), self._gf("alpha", "α"),
                self.param_vars["mode"].get(),
            )
        if t == "Retangular":
            return dsp.gen_rectangular(
                N, self._gf("A", "A"),
                self._gi("n_start", "Início"),
                self._gi("width", "Largura"),
            )
        raise ValueError(f"tipo desconhecido: {t}")

    def _on_gen_click(self):
        if self._on_generate is not None:
            self._on_generate(self)
