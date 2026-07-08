"""popout_helper.py -- janelas pop-out reativas para o Morphe.

Cada pop-out e um Toplevel com uma Figure propria. A funcao de desenho
(draw_fn) recebe a Figure e desenha o sinal atual lendo dos atributos
da janela-mae (closure por referencia, nao por valor) -- isso garante
que ao chamar refresh() o pop-out reflita o estado mais recente.

A funcao open_or_focus() implementa a regra "uma janela por chave":
se o usuario clicar de novo no botao de pop-out e ja houver uma janela
viva, ela e focada e atualizada em vez de duplicada.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from plot_toolbar import PlotToolbar


class ReactivePopout:
    """Toplevel com Figure que se redesenha sob demanda.

    A draw_fn recebe a Figure (ja limpa) e desenha o conteudo atual.
    Ela deve LER os atributos da janela-mae diretamente (nao capturar
    valores em variaveis locais), para que refresh() pegue o estado novo.
    """

    def __init__(self, parent, title: str,
                 draw_fn: Callable[[Figure], None],
                 size: str = "1100x800"):
        self.parent = parent
        self._draw_fn = draw_fn
        self.alive = True

        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.geometry(size)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        self.fig = Figure(figsize=(10, 8), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.win)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        # Mesma barra flutuante das janelas principais (home/pan/zoom/salvar
        # no canto superior direito) — consistência visual em todo o app.
        self.toolbar = PlotToolbar(self.canvas)

        self.refresh()

    def _on_close(self):
        self.alive = False
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    def set_draw_fn(self, draw_fn: Callable[[Figure], None]):
        self._draw_fn = draw_fn

    def refresh(self):
        if not self.alive:
            return
        try:
            # Limpa figura completamente (incluindo subplots antigos)
            self.fig.clear()
            self._draw_fn(self.fig)
            self.fig.tight_layout()
            self.canvas.draw_idle()
        except tk.TclError:
            # Janela morta entre o teste e o draw -- ignora
            self.alive = False

    def focus(self):
        if not self.alive:
            return
        try:
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
        except tk.TclError:
            self.alive = False


def open_or_focus(registry: dict, key: str, parent, title: str,
                  draw_fn: Callable[[Figure], None],
                  size: str = "1100x800") -> ReactivePopout:
    """Se ja existe pop-out vivo com essa key, atualiza e foca.
       Senao, cria novo e registra.
    """
    existing = registry.get(key)
    if existing is not None and existing.alive:
        existing.set_draw_fn(draw_fn)
        existing.refresh()
        existing.focus()
        return existing
    popout = ReactivePopout(parent, title, draw_fn, size)
    registry[key] = popout
    return popout


def refresh_all(registry: dict) -> None:
    """Re-renderiza todos os pop-outs vivos. Limpa entradas mortas."""
    dead_keys = []
    for key, popout in registry.items():
        if popout.alive:
            popout.refresh()
        else:
            dead_keys.append(key)
    for key in dead_keys:
        registry.pop(key, None)
