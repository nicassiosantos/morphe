"""morphe_theme.py — design system compartilhado do Morphe.

Centraliza paleta, estilos ttk e helpers de widgets usados por todas as
janelas. Use em qualquer janela top-level:

    import morphe_theme as theme

    class MinhaJanela(tk.Toplevel):
        def __init__(self, master):
            super().__init__(master)
            theme.setup_styles(self)
            self.configure(bg=theme.COLORS["bg"])
            ...

Estilos disponíveis após `setup_styles`:

  Frames:        Main.TFrame
  LabelFrames:   Card.TLabelframe
  Labels:        Title.TLabel, Subtitle.TLabel, SectionHint.TLabel,
                 Card.TLabel
  Botões:        Primary.TButton  (azul sólido, ação principal),
                 Outline.TButton  (contorno azul, ação primária "leve"),
                 Secondary.TButton(branco, ação neutra),
                 Icon.TButton     (compacto, sem borda — ícone único)
  Outros:        Card.TCheckbutton

Helpers:
  make_banner(parent, kind, text)         -> tk.Frame
  make_form_row(parent, row, label, var)  -> ttk.Entry
  make_exit_link(parent, on_click)        -> tk.Label
  make_status_bar(parent, textvariable)   -> tk.Frame
  make_plot_header_bar(parent, items)     -> tk.Frame
  CollapsibleSection(parent, title, ...)  -> ttk.Frame com .body
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional, Tuple


# ─── Paleta ──────────────────────────────────────────────────
COLORS = {
    # Base
    "bg":            "#f4f5f7",
    "card_bg":       "#ffffff",
    "border":        "#e2e8f0",
    "border_hover":  "#cbd5e1",
    "text":          "#0f172a",
    "text_muted":    "#64748b",
    "surface_hover": "#f1f5f9",

    # Primária (azul, ações principais)
    "primary":       "#2563eb",
    "primary_hover": "#1d4ed8",
    "primary_text":  "#ffffff",

    # Perigo (vermelho discreto, link Sair)
    "danger":        "#b91c1c",
    "danger_hover":  "#7f1d1d",

    # Banners
    "info_bg":       "#eff6ff",
    "info_fg":       "#1e40af",
    "info_border":   "#bfdbfe",

    "warn_bg":       "#fffbeb",
    "warn_fg":       "#92400e",
    "warn_border":   "#fde68a",

    "ok_bg":         "#f0fdf4",
    "ok_fg":         "#15803d",
    "ok_border":     "#bbf7d0",

    # Plotagem (área de gráficos)
    "axis":          "#94a3b8",   # eixos remanescentes (x/y), tom suave
    "grid":          "#e9edf2",   # linhas de grade, bem discretas
    "empty_fg":      "#94a3b8",   # texto do estado vazio (prompt)
}


# ─── Setup de estilos ttk ────────────────────────────────────
_STYLES_INITIALIZED = False


def setup_styles(root: tk.Misc) -> None:
    """Configura estilos ttk customizados. Idempotente.

    Chame uma vez por janela top-level — chamadas subsequentes são no-op,
    já que ttk.Style é global ao processo Tk.
    """
    global _STYLES_INITIALIZED
    if _STYLES_INITIALIZED:
        return

    style = ttk.Style(root)
    style.theme_use("clam")

    # ── Frames base ──
    style.configure("Main.TFrame", background=COLORS["bg"])
    style.configure("Card.TFrame", background=COLORS["card_bg"])

    # ── Cards (LabelFrames brancos com borda suave) ──
    style.configure(
        "Card.TLabelframe",
        background=COLORS["card_bg"],
        bordercolor=COLORS["border"],
        borderwidth=1,
        relief="solid",
    )
    style.configure(
        "Card.TLabelframe.Label",
        background=COLORS["card_bg"],
        foreground=COLORS["text"],
        font=("TkDefaultFont", 10, "bold"),
        padding=(4, 0),
    )

    # ── Labels ──
    style.configure(
        "Title.TLabel",
        background=COLORS["bg"],
        foreground=COLORS["text"],
        font=("TkDefaultFont", 20, "bold"),
    )
    style.configure(
        "Subtitle.TLabel",
        background=COLORS["bg"],
        foreground=COLORS["text_muted"],
        font=("TkDefaultFont", 10),
    )
    style.configure(
        "SectionHint.TLabel",
        background=COLORS["card_bg"],
        foreground=COLORS["text_muted"],
        font=("TkDefaultFont", 9),
    )
    style.configure(
        "Card.TLabel",
        background=COLORS["card_bg"],
        foreground=COLORS["text"],
        font=("TkDefaultFont", 10),
    )

    # ── Checkbutton sobre fundo de card ──
    style.configure(
        "Card.TCheckbutton",
        background=COLORS["card_bg"],
        foreground=COLORS["text"],
        focuscolor="",
        font=("TkDefaultFont", 10),
    )
    style.map(
        "Card.TCheckbutton",
        background=[("active", COLORS["card_bg"])],
    )

    # ── Botões ──
    # Primary: ação principal (azul, negrito) — UM por seção, idealmente
    style.configure(
        "Primary.TButton",
        background=COLORS["primary"],
        foreground=COLORS["primary_text"],
        font=("TkDefaultFont", 10, "bold"),
        padding=(14, 11),
        borderwidth=0,
        focusthickness=0,
    )
    style.map(
        "Primary.TButton",
        background=[
            ("active",   COLORS["primary_hover"]),
            ("pressed",  COLORS["primary_hover"]),
            ("disabled", "#cbd5e1"),
        ],
    )

    # Secondary: ação neutra (contorno fino sobre branco)
    style.configure(
        "Secondary.TButton",
        background=COLORS["card_bg"],
        foreground=COLORS["text"],
        font=("TkDefaultFont", 10),
        padding=(14, 10),
        borderwidth=1,
        relief="solid",
        bordercolor=COLORS["border"],
        focusthickness=0,
    )
    style.map(
        "Secondary.TButton",
        background=[("active", COLORS["surface_hover"])],
        bordercolor=[("active", COLORS["border_hover"])],
    )

    # Outline: ação primária em estilo "outline" (contorno + texto azuis).
    # Harmoniza com Primary (mesma cor) porém pesa menos visualmente — ideal
    # para o "Gerar" dos painéis de sinal, que fica sobre card branco.
    style.configure(
        "Outline.TButton",
        background=COLORS["card_bg"],
        foreground=COLORS["primary"],
        font=("TkDefaultFont", 10, "bold"),
        padding=(14, 10),
        borderwidth=1,
        relief="solid",
        bordercolor=COLORS["primary"],
        focusthickness=0,
    )
    style.map(
        "Outline.TButton",
        background=[
            ("active",   COLORS["info_bg"]),
            ("pressed",  COLORS["info_bg"]),
            ("disabled", COLORS["card_bg"]),
        ],
        foreground=[
            ("active",   COLORS["primary_hover"]),
            ("disabled", COLORS["border_hover"]),
        ],
        bordercolor=[
            ("active",   COLORS["primary_hover"]),
            ("disabled", COLORS["border"]),
        ],
    )

    # Icon: botão compacto só com símbolo (⛶, ▾, ?, etc.)
    style.configure(
        "Icon.TButton",
        background=COLORS["card_bg"],
        foreground=COLORS["text_muted"],
        font=("TkDefaultFont", 11),
        padding=(6, 2),
        borderwidth=0,
        relief="flat",
        focusthickness=0,
    )
    style.map(
        "Icon.TButton",
        background=[("active", COLORS["surface_hover"])],
        foreground=[("active", COLORS["text"])],
    )

    _STYLES_INITIALIZED = True


# ─── Helpers de widgets ──────────────────────────────────────

_BANNER_PALETTE = {
    "info": ("ℹ",  "info_bg",  "info_fg",  "info_border"),
    "warn": ("⚠",  "warn_bg",  "warn_fg",  "warn_border"),
    "ok":   ("✓",  "ok_bg",    "ok_fg",    "ok_border"),
}


def make_banner(parent: tk.Misc, kind: str, text: str,
                wraplength: int = 400) -> tk.Frame:
    """Banner suave com ícone (ℹ/⚠/✓), sem borda preta.

    kind: 'info' (azul), 'warn' (âmbar) ou 'ok' (verde).
    """
    if kind not in _BANNER_PALETTE:
        raise ValueError(f"kind precisa ser 'info', 'warn' ou 'ok' (recebi {kind!r})")
    icon, bg_key, fg_key, border_key = _BANNER_PALETTE[kind]
    bg = COLORS[bg_key]
    fg = COLORS[fg_key]
    border = COLORS[border_key]

    frame = tk.Frame(
        parent,
        background=bg,
        highlightbackground=border,
        highlightcolor=border,
        highlightthickness=1,
        bd=0,
    )
    tk.Label(
        frame, text=icon,
        background=bg, foreground=fg,
        font=("TkDefaultFont", 13, "bold"),
    ).pack(side="left", padx=(10, 8), pady=8, anchor="n")
    tk.Label(
        frame, text=text,
        background=bg, foreground=fg,
        justify="left", wraplength=wraplength,
        font=("TkDefaultFont", 9),
    ).pack(side="left", padx=(0, 10), pady=8, fill="x", expand=True)
    return frame


def make_form_row(parent: tk.Misc, row: int, label_text: str,
                  textvariable: tk.Variable, *,
                  unit: Optional[str] = None,
                  entry_width: int = 12,
                  label_minsize: int = 90) -> ttk.Entry:
    """Linha de formulário alinhada por grid: label | entry | unidade.

    Reusa as columnconfigure do parent — basta chamar make_form_row para
    cada linha que o alinhamento vertical da coluna de inputs sai grátis.
    """
    parent.columnconfigure(0, minsize=label_minsize)
    parent.columnconfigure(1, weight=1)

    ttk.Label(parent, text=label_text, style="Card.TLabel").grid(
        row=row, column=0, sticky="w", pady=(0, 6))
    entry = ttk.Entry(parent, textvariable=textvariable, width=entry_width)
    entry.grid(row=row, column=1, sticky="ew", pady=(0, 6))
    if unit:
        ttk.Label(parent, text=unit, style="SectionHint.TLabel").grid(
            row=row, column=2, sticky="w", padx=(6, 0), pady=(0, 6))
    return entry


def make_exit_link(parent: tk.Misc, on_click: Callable[[], None]) -> tk.Label:
    """Link clicável 'Sair' em vermelho, sem moldura. Sublinha no hover."""
    font_normal = ("TkDefaultFont", 10)
    font_hover  = ("TkDefaultFont", 10, "underline")

    lbl = tk.Label(
        parent, text="Sair",
        background=COLORS["bg"],
        foreground=COLORS["danger"],
        font=font_normal,
        cursor="hand2",
        padx=4, pady=2, bd=0, highlightthickness=0,
    )
    lbl.bind("<Button-1>", lambda _e: on_click())
    lbl.bind(
        "<Enter>",
        lambda _e: lbl.configure(font=font_hover,
                                 foreground=COLORS["danger_hover"]),
    )
    lbl.bind(
        "<Leave>",
        lambda _e: lbl.configure(font=font_normal,
                                 foreground=COLORS["danger"]),
    )
    return lbl


def make_status_bar(parent: tk.Misc, textvariable: tk.StringVar) -> tk.Frame:
    """Barra de status discreta no rodapé — substitui `relief='sunken'`."""
    frame = tk.Frame(
        parent,
        background=COLORS["card_bg"],
        highlightthickness=1,
        highlightbackground=COLORS["border"],
        bd=0,
    )
    tk.Label(
        frame, textvariable=textvariable,
        background=COLORS["card_bg"],
        foreground=COLORS["text_muted"],
        font=("TkDefaultFont", 9),
        anchor="w", padx=10, pady=4,
    ).pack(side="left", fill="x", expand=True)
    return frame


def make_plot_header_bar(parent: tk.Misc,
                         items: List[Tuple[str, Callable[[], None]]],
                         orientation: str = "horizontal") -> tk.Frame:
    """Barra de cabeçalho com nome do plot + ícone ⛶ por item.

    Substitui a linha tradicional de "Pop-out X | Pop-out Y" — agora
    cada plot tem seu próprio rótulo prominente e um ícone compacto
    de expansão alinhado à direita.

    orientation: 'horizontal' (default, items lado a lado em colunas de
    largura igual) ou 'vertical' (items empilhados).
    """
    bar = tk.Frame(parent, background=COLORS["bg"])
    for i, (label, cb) in enumerate(items):
        cell = tk.Frame(bar, background=COLORS["bg"])
        if orientation == "horizontal":
            cell.grid(row=0, column=i, sticky="ew", padx=2)
            bar.columnconfigure(i, weight=1, uniform="plot_header")
        else:
            cell.grid(row=i, column=0, sticky="ew", pady=1)
            bar.columnconfigure(0, weight=1)

        tk.Label(
            cell, text=label,
            background=COLORS["bg"],
            foreground=COLORS["text"],
            font=("TkDefaultFont", 10, "bold"),
            anchor="w", padx=4,
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            cell, text="⛶", width=3,
            style="Icon.TButton",
            command=cb,
        ).pack(side="right", padx=(0, 4))
    return bar


# ─── Estilização de plots (matplotlib) ───────────────────────
# Estes dois helpers operam sobre um Axes já existente (não importam
# matplotlib — apenas chamam métodos do objeto recebido), mantendo o
# tema desacoplado do backend gráfico.

def style_plot_axes(ax, *, grid: bool = True) -> None:
    """Aplica o visual de *dashboard* do Morphe a um Axes COM dados.

    - Remove as spines superior e direita (o "quadro" acadêmico completo).
    - Mantém apenas o eixo x (base) e o eixo y (esquerda), em tom suave.
    - Deixa ticks e rótulos de tick em cinza e a grade bem leve, ATRÁS
      dos dados.

    Chame ao final do desenho de cada subplot que contém dados.
    """
    ax.set_facecolor(COLORS["card_bg"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for side in ("left", "bottom"):
        sp = ax.spines[side]
        sp.set_visible(True)
        sp.set_color(COLORS["axis"])
        sp.set_linewidth(1.0)
    ax.tick_params(
        colors=COLORS["axis"],
        labelcolor=COLORS["text_muted"],
        labelsize=8, length=3, width=0.8,
    )
    if grid:
        ax.set_axisbelow(True)
        ax.grid(True, color=COLORS["grid"], linewidth=0.8)
    else:
        ax.grid(False)


def draw_empty_axes(ax, message: str) -> None:
    """Estado vazio de um Axes — "tela em branco à espera".

    Esconde spines, ticks e grade e escreve apenas um texto suave,
    centralizado, sobre um fundo cinza claro. Usado ANTES de qualquer
    sinal existir, evitando a grade "travada" de 0.0 a 1.0 que parecia
    um erro de carregamento.
    """
    ax.clear()
    ax.set_facecolor(COLORS["bg"])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    ax.text(
        0.5, 0.5, message,
        transform=ax.transAxes,
        ha="center", va="center",
        color=COLORS["empty_fg"],
        fontsize=10, fontstyle="italic",
        linespacing=1.4, wrap=True,
    )


class CollapsibleSection(ttk.Frame):
    """Seção colapsável: cabeçalho clicável + corpo que aparece/some.

    Use para *progressive disclosure* de conteúdo denso (ex.: caixa de
    limitações do hardware) que o usuário não precisa ver o tempo todo.

    Após instanciar, adicione widgets em `self.body`.
    """
    def __init__(self, parent: tk.Misc, title: str,
                 expanded: bool = False, **kwargs):
        super().__init__(parent, style="Main.TFrame", **kwargs)
        self._expanded = expanded
        self._title = title

        self._header = tk.Label(
            self,
            background=COLORS["bg"],
            foreground=COLORS["text_muted"],
            font=("TkDefaultFont", 9, "bold"),
            cursor="hand2",
            padx=2, pady=4,
            anchor="w",
        )
        self._header.pack(fill="x")
        self._header.bind("<Button-1>", lambda _e: self.toggle())

        self.body = ttk.Frame(self, style="Main.TFrame")
        # `body` não é empacotado agora — toggle controla.

        self._refresh_header()
        if expanded:
            self.body.pack(fill="x", pady=(4, 0))

    def toggle(self):
        self._expanded = not self._expanded
        if self._expanded:
            self.body.pack(fill="x", pady=(4, 0))
        else:
            self.body.pack_forget()
        self._refresh_header()

    def _refresh_header(self):
        chevron = "▾" if self._expanded else "▸"
        self._header.config(text=f"{chevron}  {self._title}")
