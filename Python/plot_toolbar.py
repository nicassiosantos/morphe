"""plot_toolbar.py — barra de ferramentas flutuante para os plots do Morphe.

Substitui a NavigationToolbar2Tk padrão (a barra cinza no rodapé, que destoa
do restante da UI e parece "desconectada") por botões-ícone compactos que
flutuam no canto superior direito da própria área de plotagem, no estilo de
dashboards modernos. O rodapé fica limpo.

Como funciona
─────────────
Internamente ainda instanciamos uma NavigationToolbar2Tk — ela concentra toda
a lógica de pan/zoom/home/salvar do Matplotlib — porém a mantemos OCULTA
(nunca é empacotada nem posicionada). Nossos botões apenas disparam os
métodos dela:

    home()         → restaura o enquadramento original
    pan()          → alterna o modo "mover" (arrastar o gráfico)
    zoom()         → alterna o modo "zoom por caixa"
    save_figure()  → abre o diálogo de exportação PNG/SVG/PDF

Os ícones são desenhados vetorialmente em um ``tk.Canvas`` (linhas, ovais,
polígonos), portanto independem de fontes/emoji e ficam nítidos em qualquer
sistema operacional. Pan e zoom são botões de ESTADO: refletem o modo ativo.

O leitor de coordenadas (o texto "n=12, x[12]=0.73" que aparecia ao passar o
mouse sobre o gráfico) é preservado: interceptamos ``set_message`` e o
exibimos como um chip discreto no canto inferior esquerdo, visível apenas
quando há texto.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk

import morphe_theme as theme


# "Miolo" desenhável (px) dentro de cada botão; há uma folga (_PAD) ao redor.
_ICON = 22
_PAD = 5


# ─── Botão-ícone vetorial ────────────────────────────────────

class _IconButton(tk.Canvas):
    """Botão quadrado cujo ícone é desenhado vetorialmente.

    Estados visuais:
      normal → traço em ``text_muted``, fundo do card
      hover  → traço em ``text``,       fundo ``surface_hover``
      ativo  → traço em ``primary``,    fundo ``info_bg``  (toggles ligados)
    """

    def __init__(self, parent, draw: Callable[["_IconButton"], None],
                 command: Callable[[], None], tooltip: str = ""):
        side = _ICON + 2 * _PAD
        super().__init__(parent, width=side, height=side,
                         background=theme.COLORS["card_bg"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self._draw = draw
        self._command = command
        self._active = False
        self._hover = False
        self._tooltip_text = tooltip
        self._tip = None

        self._render()
        self.bind("<Button-1>", lambda _e: self._command())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    # ---- cores conforme o estado ----
    def _stroke(self) -> str:
        if self._active:
            return theme.COLORS["primary"]
        if self._hover:
            return theme.COLORS["text"]
        return theme.COLORS["text_muted"]

    def _bg(self) -> str:
        if self._active:
            return theme.COLORS["info_bg"]
        if self._hover:
            return theme.COLORS["surface_hover"]
        return theme.COLORS["card_bg"]

    def _render(self):
        self.delete("all")
        self.configure(background=self._bg())
        self._draw(self)

    # ---- helpers de desenho (coordenadas em 0.._ICON) ----
    def line(self, x1, y1, x2, y2, **kw):
        kw.setdefault("width", 1.8)
        kw.setdefault("capstyle", "round")
        kw.setdefault("joinstyle", "round")
        self.create_line(_PAD + x1, _PAD + y1, _PAD + x2, _PAD + y2,
                         fill=self._stroke(), **kw)

    def oval(self, x1, y1, x2, y2, **kw):
        kw.setdefault("width", 1.8)
        self.create_oval(_PAD + x1, _PAD + y1, _PAD + x2, _PAD + y2,
                         outline=self._stroke(), fill="", **kw)

    # ---- toggle on/off ----
    def set_active(self, active: bool):
        if active != self._active:
            self._active = active
            self._render()

    # ---- hover ----
    def _on_enter(self, _e):
        self._hover = True
        self._render()
        self._show_tip()

    def _on_leave(self, _e):
        self._hover = False
        self._render()
        self._hide_tip()

    # ---- tooltip minimalista ----
    def _show_tip(self):
        if not self._tooltip_text or self._tip is not None:
            return
        self._tip = tk.Toplevel(self)
        self._tip.wm_overrideredirect(True)
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 4
        tk.Label(self._tip, text=self._tooltip_text,
                 background=theme.COLORS["text"], foreground="#ffffff",
                 font=("TkDefaultFont", 8), padx=6, pady=2, bd=0).pack()
        self._tip.wm_geometry(f"+{x}+{y}")

    def _hide_tip(self):
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


# ─── Funções de desenho de cada ícone ────────────────────────
# Todas trabalham num espaço 0.._ICON (22x22); o _IconButton aplica a folga.

def _draw_home(b: _IconButton):
    """Casinha — metáfora "Home" do Matplotlib (enquadramento inicial)."""
    b.line(3, 11, 11, 4)          # água esquerda do telhado
    b.line(11, 4, 19, 11)         # água direita do telhado
    b.line(5, 10, 5, 19)          # parede esquerda
    b.line(17, 10, 17, 19)        # parede direita
    b.line(5, 19, 17, 19)         # base
    b.line(9.5, 19, 9.5, 14)      # porta
    b.line(9.5, 14, 12.5, 14)
    b.line(12.5, 14, 12.5, 19)


def _draw_pan(b: _IconButton):
    """Seta em quatro direções — mover/arrastar (pan)."""
    c = 11
    b.line(c, 3, c, 19)           # eixo vertical
    b.line(3, c, 19, c)           # eixo horizontal
    b.line(c, 3, c - 2.5, 5.5)    # ponta ↑
    b.line(c, 3, c + 2.5, 5.5)
    b.line(c, 19, c - 2.5, 16.5)  # ponta ↓
    b.line(c, 19, c + 2.5, 16.5)
    b.line(3, c, 5.5, c - 2.5)    # ponta ←
    b.line(3, c, 5.5, c + 2.5)
    b.line(19, c, 16.5, c - 2.5)  # ponta →
    b.line(19, c, 16.5, c + 2.5)


def _draw_zoom(b: _IconButton):
    """Lupa com "+" — zoom por caixa."""
    b.oval(3, 3, 14, 14)          # lente
    b.line(13, 13, 19, 19)        # cabo
    b.line(8.5, 6, 8.5, 11)       # "+"
    b.line(6, 8.5, 11, 8.5)


def _draw_save(b: _IconButton):
    """Bandeja + seta para baixo — salvar/exportar imagem."""
    b.line(4, 13, 4, 19)          # bandeja (U aberto no topo)
    b.line(4, 19, 18, 19)
    b.line(18, 19, 18, 13)
    b.line(11, 3, 11, 14)         # haste da seta
    b.line(11, 14, 8, 11)         # aba esquerda
    b.line(11, 14, 14, 11)        # aba direita


# ─── Barra flutuante ─────────────────────────────────────────

class PlotToolbar:
    """Ferramentas flutuantes (home/pan/zoom/salvar) sobre um canvas mpl.

    Uso típico dentro de uma janela::

        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.toolbar = PlotToolbar(self.canvas)   # guarde a referência!

    Guardar a referência é importante: a barra e a toolbar oculta seriam
    coletadas pelo GC caso contrário.
    """

    def __init__(self, canvas, *, save: bool = True):
        self.canvas = canvas
        widget = canvas.get_tk_widget()
        container = widget.master

        # Toolbar real do Matplotlib, mantida OCULTA (num frame nunca
        # empacotado). Ela é quem executa pan/zoom/home/salvar de fato.
        self._holder = tk.Frame(container)  # sem pack/place → invisível
        try:
            self._nav = NavigationToolbar2Tk(canvas, self._holder,
                                             pack_toolbar=False)
        except TypeError:                    # Matplotlib < 3.3
            self._nav = NavigationToolbar2Tk(canvas, self._holder)
        self._nav.update()

        # Barra flutuante de botões (canto superior direito do canvas).
        bar = tk.Frame(container, background=theme.COLORS["card_bg"],
                       highlightthickness=1,
                       highlightbackground=theme.COLORS["border"], bd=0)
        self._bar = bar

        self._btn_home = _IconButton(bar, _draw_home, self._home,
                                     tooltip="Restaurar zoom")
        self._btn_pan = _IconButton(bar, _draw_pan, self._pan,
                                    tooltip="Mover (arrastar)")
        self._btn_zoom = _IconButton(bar, _draw_zoom, self._zoom,
                                     tooltip="Zoom por caixa")
        for b in (self._btn_home, self._btn_pan, self._btn_zoom):
            b.pack(side="left", padx=1, pady=1)
        if save:
            self._btn_save = _IconButton(bar, _draw_save, self._save,
                                         tooltip="Salvar imagem")
            self._btn_save.pack(side="left", padx=1, pady=1)

        # `in_=widget` ancora a barra ao retângulo do canvas (e não do
        # frame-pai, que também contém o cabeçalho com os ⛶).
        bar.place(in_=widget, relx=1.0, x=-8, y=8, anchor="ne")
        bar.lift()

        # Chip de leitura de coordenadas (canto inferior esquerdo). Fica
        # oculto até haver texto — preserva o readout da toolbar antiga
        # sem sujar o rodapé.
        self._widget = widget
        self._readout = tk.Label(
            container, text="",
            background=theme.COLORS["card_bg"],
            foreground=theme.COLORS["text_muted"],
            font=("TkDefaultFont", 8), padx=6, pady=2,
            highlightthickness=1,
            highlightbackground=theme.COLORS["border"], bd=0,
        )
        self._nav.set_message = self._on_message  # intercepta o readout

    # ---- ações ----
    def _home(self):
        self._nav.home()
        self._sync_modes()

    def _pan(self):
        self._nav.pan()
        self._sync_modes()

    def _zoom(self):
        self._nav.zoom()
        self._sync_modes()

    def _save(self):
        self._nav.save_figure()

    def _sync_modes(self):
        """Reflete nos botões o modo ativo da toolbar (pan/zoom/nenhum)."""
        mode = str(getattr(self._nav, "mode", "")).lower()
        self._btn_pan.set_active("pan" in mode)
        self._btn_zoom.set_active("zoom" in mode)

    # ---- readout de coordenadas ----
    def _on_message(self, msg):
        text = (msg or "").strip()
        if text:
            self._readout.configure(text=text)
            self._readout.place(in_=self._widget, relx=0.0, rely=1.0,
                                x=8, y=-8, anchor="sw")
            self._readout.lift()
        else:
            self._readout.place_forget()
