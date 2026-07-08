"""fir_window.py — janela do filtro FIR.

Refatorado para consumir o design system de `morphe_theme`. As classes
internas (ComponentRow, SuperpositionBuilder, CoefficientsLoader) foram
adaptadas para usar estilos de card. Os botões coloridos semanticos
(verde adicionar / vermelho remover / azul atualizar / roxo projetar)
foram mantidos -- a cor codifica o tipo da acao e e parte da UX.
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import List, Optional

import numpy as np

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import dsp_core as dsp
import morphe_theme as theme
from morphe_protocol import (build_fir_request, decode_fir_response,
                              DTYPE_CODES)
from popout_helper import open_or_focus, refresh_all
from fir_designer_window import FIRDesignerWindow
from plot_toolbar import PlotToolbar


# ---- Constantes / limites ------------------------------------------------

MAX_COMPONENTS = 16
MAX_N = dsp.MAX_CONV_INPUT_SIZE


# ---- Cores de acao semanticas (alinhadas a paleta do tema) ---------------
# Verde adicionar / vermelho remover / azul atualizar / roxo projetar.
# Tons "tailwind" para combinar com o resto da paleta.
_BTN_REMOVE_BG  = "#dc2626"   # red-600
_BTN_ADD_BG     = "#16a34a"   # green-600
_BTN_UPDATE_BG  = "#2563eb"   # blue-600 (= theme primary)
_BTN_DESIGN_BG  = "#7c3aed"   # violet-600
_BTN_FG_LIGHT   = "white"


def _make_action_button(parent, text: str, bg: str,
                         command, *, width: Optional[int] = None,
                         small: bool = False) -> tk.Button:
    """tk.Button colorido em estilo consistente (cor codifica acao)."""
    kwargs = dict(
        bg=bg, fg=_BTN_FG_LIGHT,
        activebackground=bg, activeforeground=_BTN_FG_LIGHT,
        bd=0, relief="flat",
        cursor="hand2",
        command=command,
    )
    if small:
        kwargs.update(padx=4, pady=1,
                       font=("TkDefaultFont", 9, "bold"))
    else:
        kwargs.update(padx=8, pady=5,
                       font=("TkDefaultFont", 9, "bold"))
    if width is not None:
        kwargs["width"] = width
    return tk.Button(parent, text=text, **kwargs)


# ----------------------------------------------------------------------
# Helpers de plot

def _attach_stem_format_coord(ax, n_arr: np.ndarray, x_arr: np.ndarray,
                               x_label: str = "n", y_label: str = "x"):
    if n_arr.size == 0:
        return
    n_arr = np.asarray(n_arr, dtype=float)
    x_arr = np.asarray(x_arr)

    def fmt(xc, yc):
        i = int(np.argmin(np.abs(n_arr - xc)))
        n_i = int(n_arr[i])
        try:
            v_str = f"{float(x_arr[i]):.4g}"
        except (TypeError, ValueError):
            v_str = str(x_arr[i])
        return f"{x_label}={n_i},  {y_label}[{n_i}] = {v_str}"

    ax.format_coord = fmt


def _stem_array(ax, n_arr, values, color, title: str, ylabel: str):
    ax.clear()
    n = np.asarray(n_arr, dtype=float)
    v = np.asarray(values)
    if v.size == 0:
        theme.draw_empty_axes(ax, title)
        return

    if v.size >= 512:
        ax.plot(n, v, color=color, linewidth=0.8)
    else:
        ml, sl, _ = ax.stem(n, v, basefmt=" ")
        ml.set_markersize(3)
        ml.set_color(color)
        ml.set_markerfacecolor(color)
        sl.set_color(color)
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("n")
    ax.set_ylabel(ylabel)
    ax.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
    theme.style_plot_axes(ax)
    _attach_stem_format_coord(ax, n, v, x_label="n", y_label=ylabel)


# ----------------------------------------------------------------------
# Parser do arquivo de coeficientes (inalterado)

class CoefficientsParseError(ValueError):
    """Erro ao interpretar o arquivo de coeficientes do FIR."""


def parse_coefficients_file(path: str) -> tuple[np.ndarray, str]:
    description = ""
    values: List[float] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("#"):
                    if not description:
                        description = stripped.lstrip("#").strip()
                    continue
                for token in stripped.split():
                    try:
                        values.append(float(token))
                    except ValueError as e:
                        raise CoefficientsParseError(
                            f"{os.path.basename(path)} linha {lineno}: "
                            f"valor invalido {token!r}"
                        ) from e
    except OSError as e:
        raise CoefficientsParseError(
            f"Não foi possível ler o arquivo: {e}"
        ) from e

    if not values:
        raise CoefficientsParseError(
            f"{os.path.basename(path)} não contém nenhum coeficiente."
        )
    return np.asarray(values, dtype=np.float64), description


# ======================================================================
# Linha individual de componente senoidal
# ======================================================================

class ComponentRow(ttk.Frame):
    """Uma linha do construtor de superposição: tipo, A, f, fase, [X]."""

    SIGNAL_TYPES = ("sin", "cos")

    def __init__(self, parent, on_remove, on_change, idx: int = 0):
        super().__init__(parent, padding=2)
        self._on_remove = on_remove
        self._on_change = on_change

        self.idx_label = ttk.Label(self, text=f"#{idx + 1}", width=3,
                                    style="Card.TLabel")
        self.idx_label.grid(row=0, column=0, padx=(0, 4))

        self.var_type = tk.StringVar(value="sin")
        cb = ttk.Combobox(self, textvariable=self.var_type,
                          values=list(self.SIGNAL_TYPES),
                          state="readonly", width=4)
        cb.grid(row=0, column=1, padx=2)
        cb.bind("<<ComboboxSelected>>", lambda e: self._notify())

        ttk.Label(self, text="A=", style="Card.TLabel").grid(
            row=0, column=2, padx=(6, 0))
        self.var_A = tk.StringVar(value="1.0")
        e = ttk.Entry(self, textvariable=self.var_A, width=8)
        e.grid(row=0, column=3, padx=2)
        e.bind("<FocusOut>", lambda ev: self._notify())
        e.bind("<Return>", lambda ev: self._notify())

        ttk.Label(self, text="f=", style="Card.TLabel").grid(
            row=0, column=4, padx=(6, 0))
        self.var_f = tk.StringVar(value="5.0")
        e = ttk.Entry(self, textvariable=self.var_f, width=8)
        e.grid(row=0, column=5, padx=2)
        e.bind("<FocusOut>", lambda ev: self._notify())
        e.bind("<Return>", lambda ev: self._notify())

        ttk.Label(self, text="phi=", style="Card.TLabel").grid(
            row=0, column=6, padx=(6, 0))
        self.var_phi = tk.StringVar(value="0.0")
        e = ttk.Entry(self, textvariable=self.var_phi, width=7)
        e.grid(row=0, column=7, padx=2)
        e.bind("<FocusOut>", lambda ev: self._notify())
        e.bind("<Return>", lambda ev: self._notify())

        btn = _make_action_button(
            self, text="✕", bg=_BTN_REMOVE_BG,
            command=self._on_remove_click,
            width=2, small=True)
        btn.grid(row=0, column=8, padx=(8, 0))

    def _on_remove_click(self):
        self._on_remove(self)

    def _notify(self):
        pass

    def set_idx(self, idx: int):
        self.idx_label.configure(text=f"#{idx + 1}")

    def read(self) -> dict:
        try:
            A = float(self.var_A.get())
        except ValueError:
            raise ValueError(f"componente: A inválido ({self.var_A.get()!r})")
        try:
            f = float(self.var_f.get())
        except ValueError:
            raise ValueError(f"componente: f inválido ({self.var_f.get()!r})")
        try:
            phi = float(self.var_phi.get())
        except ValueError:
            raise ValueError(f"componente: phi inválido ({self.var_phi.get()!r})")
        return {
            "type": self.var_type.get(),
            "A":    A,
            "f":    f,
            "phi":  phi,
        }


# ======================================================================
# Builder do sinal de entrada (superposicao)
# ======================================================================

class SuperpositionBuilder(ttk.LabelFrame):
    """Painel que monta x[n] = soma de componentes senoidais."""

    def __init__(self, parent, on_signal_changed):
        super().__init__(
            parent, text=" Sinal de entrada x[n] (superposição) ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        self._on_signal_changed = on_signal_changed
        self._rows: List[ComponentRow] = []

        # Linha de parâmetros globais (N + fs)
        params = ttk.Frame(self, style="Card.TFrame")
        params.pack(fill="x", pady=(0, 8))

        ttk.Label(params, text=f"N (max {MAX_N}):",
                  style="Card.TLabel").pack(side="left")
        self.var_N = tk.StringVar(value="64")
        ttk.Entry(params, textvariable=self.var_N, width=6).pack(
            side="left", padx=(4, 14))

        ttk.Label(params, text="fs (Hz):",
                  style="Card.TLabel").pack(side="left")
        self.var_fs = tk.StringVar(value="64.0")
        self._entry_fs = ttk.Entry(params, textvariable=self.var_fs, width=8)
        self._entry_fs.pack(side="left", padx=(4, 4))

        self.var_fs_lock = tk.StringVar(value="")
        self._lbl_fs_lock = tk.Label(
            params, textvariable=self.var_fs_lock,
            background=theme.COLORS["card_bg"],
            foreground=theme.COLORS["primary"],
            font=("TkDefaultFont", 8, "italic"),
        )
        self._lbl_fs_lock.pack(side="left", padx=(0, 0))

        # Canvas com scrollbar para a lista de componentes
        canvas_frame = ttk.Frame(self, style="Card.TFrame")
        canvas_frame.pack(fill="x", pady=(2, 6))

        self._canvas = tk.Canvas(
            canvas_frame, height=180,
            background=theme.COLORS["card_bg"],
            highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical",
                                   command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)

        self._canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._rows_frame = ttk.Frame(self._canvas, style="Card.TFrame")
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._rows_frame, anchor="nw")

        self._rows_frame.bind(
            "<Configure>",
            lambda e: self._canvas.configure(
                scrollregion=self._canvas.bbox("all")))
        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfigure(
                self._canvas_window, width=e.width))

        # Expressão visualizada (label suave em vez de "sunken")
        ttk.Label(self, text="Expressão",
                  style="SectionHint.TLabel").pack(anchor="w", pady=(4, 2))
        self.var_expression = tk.StringVar(value="x[n] = 0")
        self._expr_label = tk.Label(
            self,
            textvariable=self.var_expression,
            background="#f8fafc",
            foreground=theme.COLORS["text"],
            highlightbackground=theme.COLORS["border"],
            highlightthickness=1,
            bd=0,
            anchor="w", justify="left",
            wraplength=420,
            padx=10, pady=6,
            font=("TkDefaultFont", 9))
        self._expr_label.pack(fill="x", pady=(0, 8))

        # Botões de ação (verde adicionar / azul atualizar)
        btns = ttk.Frame(self, style="Card.TFrame")
        btns.pack(fill="x")

        self.btn_add = _make_action_button(
            btns, text="+ Adicionar componente",
            bg=_BTN_ADD_BG, command=self._on_add_click)
        self.btn_add.pack(side="left")

        _make_action_button(
            btns, text="↻ Atualizar x[n]",
            bg=_BTN_UPDATE_BG, command=self._on_update_click).pack(
            side="right")

        self._add_row()
        self._update_expression_display()

    def _add_row(self):
        if len(self._rows) >= MAX_COMPONENTS:
            messagebox.showwarning(
                "Limite",
                f"Máximo de {MAX_COMPONENTS} componentes. Remova algum "
                "antes de adicionar outro.")
            return
        row = ComponentRow(self._rows_frame,
                            on_remove=self._on_row_remove,
                            on_change=lambda: None,
                            idx=len(self._rows))
        row.pack(fill="x", pady=1)
        self._rows.append(row)

    def _on_add_click(self):
        self._add_row()
        self._update_expression_display()

    def _on_row_remove(self, row: ComponentRow):
        if row in self._rows:
            self._rows.remove(row)
            try:
                row.destroy()
            except tk.TclError:
                pass
            for i, r in enumerate(self._rows):
                r.set_idx(i)
        self._update_expression_display()

    def _on_update_click(self):
        try:
            sig = self.compute_signal()
        except ValueError as e:
            messagebox.showerror("Sinal inválido", str(e))
            return
        n_arr, x = sig
        self._update_expression_display()
        self._on_signal_changed(n_arr, x)

    def _build_text_expression(self) -> str:
        try:
            _, fs = self.read_globals()
        except ValueError:
            fs = None

        if not self._rows:
            return "x[n] = 0"

        parts = []
        for row in self._rows:
            try:
                c = row.read()
            except ValueError:
                parts.append("(inválido)")
                continue
            ftxt = self._fmt_num(c["f"])
            fstxt = self._fmt_num(fs) if fs is not None else "fs"
            arg = f"2π·{ftxt}·n/{fstxt}"
            if c["phi"] != 0.0:
                arg += f" + {self._fmt_num(c['phi'])}"
            atxt = self._fmt_num(c["A"])
            parts.append(f"{atxt}·{c['type']}({arg})")
        return "x[n] = " + " + ".join(parts)

    @staticmethod
    def _fmt_num(v) -> str:
        if isinstance(v, str):
            return v
        if v == int(v):
            return str(int(v))
        return f"{v:.4g}"

    def _update_expression_display(self):
        self.var_expression.set(self._build_text_expression())

    def read_globals(self) -> tuple[int, float]:
        try:
            N = int(self.var_N.get())
        except ValueError:
            raise ValueError("N deve ser inteiro")
        if N <= 0 or N > MAX_N:
            raise ValueError(f"N deve estar em [1, {MAX_N}]")
        try:
            fs = float(self.var_fs.get())
        except ValueError:
            raise ValueError("fs deve ser numérico")
        if fs <= 0:
            raise ValueError("fs deve ser > 0")
        return N, fs

    def set_fs_locked(self, fs: float, locked: bool = True) -> None:
        self.var_fs.set(f"{fs:g}")
        if locked:
            self._entry_fs.configure(state="readonly")
            self.var_fs_lock.set("(fs do filtro)")
        else:
            self._entry_fs.configure(state="normal")
            self.var_fs_lock.set("")

    def compute_signal(self) -> tuple[np.ndarray, np.ndarray]:
        N, fs = self.read_globals()
        if not self._rows:
            raise ValueError("Adicione ao menos um componente.")

        n_useful = np.arange(N, dtype=np.float64)
        x_useful = np.zeros(N, dtype=np.float64)
        for row in self._rows:
            comp = row.read()
            t_arg = 2 * np.pi * comp["f"] * n_useful / fs + comp["phi"]
            if comp["type"] == "sin":
                x_useful += comp["A"] * np.sin(t_arg)
            else:
                x_useful += comp["A"] * np.cos(t_arg)

        x = np.zeros(MAX_N, dtype=np.float64)
        x[:N] = x_useful
        n_arr = np.arange(MAX_N, dtype=np.int64)
        return n_arr, x

    def describe(self) -> str:
        N, fs = self.read_globals()
        parts = []
        for i, row in enumerate(self._rows, start=1):
            try:
                c = row.read()
                parts.append(
                    f"{c['A']:.3g}*{c['type']}(2π*{c['f']:.3g}*n/{fs:.3g}"
                    f"{'+'+str(c['phi']) if c['phi'] != 0 else ''})"
                )
            except ValueError:
                parts.append(f"#{i}=(invalido)")
        return (f"x[n] N={N} (+{MAX_N-N} zeros, total {MAX_N}) "
                f"fs={fs}: " + " + ".join(parts))


# ======================================================================
# Loader de coeficientes
# ======================================================================

class CoefficientsLoader(ttk.LabelFrame):
    def __init__(self, parent, on_loaded, on_design_request=None):
        super().__init__(
            parent, text=" Coeficientes do filtro h[n] ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        self._on_loaded = on_loaded
        self._on_design_request = on_design_request
        self.coefs: Optional[np.ndarray] = None
        self.n_taps: int = 0
        self.description: str = ""
        self.path: Optional[str] = None

        btns = ttk.Frame(self, style="Card.TFrame")
        btns.pack(fill="x", pady=(0, 6))
        ttk.Button(
            btns, text="Carregar (.txt)…",
            style="Secondary.TButton",
            command=self._on_load_click,
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        if on_design_request is not None:
            _make_action_button(
                btns, text="🛠 Projetar filtro…",
                bg=_BTN_DESIGN_BG,
                command=self._on_design_click).pack(
                side="left", fill="x", expand=True, padx=(4, 0))

        self.var_status = tk.StringVar(value="(nenhum filtro carregado)")
        tk.Label(
            self, textvariable=self.var_status,
            background=theme.COLORS["card_bg"],
            foreground=theme.COLORS["text_muted"],
            font=("TkDefaultFont", 9),
            wraplength=320, justify="left", anchor="w",
        ).pack(fill="x")

    def _on_design_click(self):
        if self._on_design_request is None:
            return
        self._on_design_request(
            lambda coefs, desc, fs: self.set_coefficients(
                coefs, desc, source="(projeto)", fs=fs))

    def _on_load_click(self):
        path = filedialog.askopenfilename(
            title="Carregar coeficientes do filtro FIR",
            filetypes=[("Texto", "*.txt"),
                       ("Coeficientes Morphe", "*.coef"),
                       ("Todos", "*.*")],
        )
        if not path:
            return
        try:
            coefs, desc = parse_coefficients_file(path)
        except CoefficientsParseError as e:
            messagebox.showerror("Erro ao carregar coeficientes", str(e))
            return
        self.set_coefficients(coefs, desc, source=path, fs=None)

    def set_coefficients(self, coefs: np.ndarray, description: str,
                          source: str = "",
                          fs: Optional[float] = None) -> bool:
        coefs = np.asarray(coefs, dtype=np.float64)

        if len(coefs) > MAX_N:
            messagebox.showerror(
                "Filtro grande demais",
                f"O filtro tem {len(coefs)} taps, mas o hardware só "
                f"comporta até {MAX_N}. Reduza o número de coeficientes."
            )
            return False

        warn = dsp.q1516_range_warning(coefs)
        if warn:
            ok = messagebox.askokcancel(
                "Atenção - faixa Q15.16",
                f"{warn}\n\nDeseja continuar mesmo assim? Os valores "
                "fora da faixa serão saturados ao serem enviados."
            )
            if not ok:
                return False

        n_taps = len(coefs)
        h_padded = np.zeros(MAX_N, dtype=np.float64)
        h_padded[:n_taps] = coefs

        self.coefs = h_padded
        self.n_taps = n_taps
        self.description = description or ""
        self.path = source if source.endswith(".txt") else None

        if source.endswith(".txt"):
            label = os.path.basename(source)
        elif source:
            label = source
        else:
            label = "(definido)"
        info = (f"{label}\n"
                f"Taps: {n_taps} (zero-padded para {MAX_N})    "
                f"Max |h|: {float(np.max(np.abs(coefs))):.4g}")
        if self.description:
            info += f"\nDescrição: {self.description}"
        self.var_status.set(info)
        self._on_loaded(h_padded, self.description, fs, n_taps)
        return True


# ======================================================================
# Janela principal
# ======================================================================

class FIRWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Morphe — Filtro FIR (via FPGA / TCP)")
        self.geometry("1240x820")
        self.configure(bg=theme.COLORS["bg"])

        theme.setup_styles(self)

        self.x_input: Optional[np.ndarray] = None
        self.x_n: Optional[np.ndarray] = None
        self.x_n_useful: int = 0
        self.h_coefs: Optional[np.ndarray] = None
        self.h_n_taps: int = 0
        self.h_descr: str = ""
        self.y_output: Optional[np.ndarray] = None
        self._popouts: dict = {}

        # Status bar
        self.status = tk.StringVar(value="Pronto.")
        theme.make_status_bar(self, self.status).pack(side="bottom", fill="x")

        root = ttk.Frame(self, style="Main.TFrame", padding=12)
        root.pack(fill="both", expand=True)

        sidebar = ttk.Frame(root, style="Main.TFrame")
        sidebar.pack(side="left", fill="y", padx=(0, 12))
        self._build_sidebar(sidebar)

        plot_area = ttk.Frame(root, style="Main.TFrame")
        plot_area.pack(side="right", fill="both", expand=True)
        self._build_plot_area(plot_area)

        self.after(100, self._auto_initial_update)

    # ------------------------------------------------------------------

    def _build_sidebar(self, parent: ttk.Frame):
        # ── Limitações: progressive disclosure ──
        hw_section = theme.CollapsibleSection(
            parent, title="Limitações do hardware FIR",
            expanded=False,
        )
        hw_section.pack(fill="x", pady=(0, 6))
        hw_text = (
            f"• Tamanho do buffer x[n] e h[n]: {MAX_N} amostras "
            "(zero-padded até esse tamanho)\n"
            f"• Saída y[n]: até N+M−1 = {2*MAX_N - 1} amostras\n"
            "• Formato Q15.16 (1 sinal + 15 inteiros + 16 fracionários)\n"
            "• Faixa aproximada: [−32768, +32768)\n"
            "• Hardware separado da convolução geral"
        )
        theme.make_banner(
            hw_section.body, kind="warn", text=hw_text, wraplength=320,
        ).pack(fill="x")

        # ── Construtor de x[n] (superposição) ──
        self.builder = SuperpositionBuilder(
            parent, on_signal_changed=self._on_x_updated)
        self.builder.pack(fill="x", pady=(6, 0))

        # ── Loader de coeficientes h[n] ──
        self.loader = CoefficientsLoader(
            parent, on_loaded=self._on_h_loaded,
            on_design_request=self._open_designer)
        self.loader.pack(fill="x", pady=(10, 0))

        # ── Execução & Exportação ──
        actions = ttk.LabelFrame(
            parent, text=" Execução ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        actions.pack(fill="x", pady=(10, 0))

        # PRIMARY: ação principal
        self.btn_run = ttk.Button(
            actions, text="Aplicar FIR (FPGA)",
            style="Primary.TButton",
            command=self._on_run, state="disabled",
        )
        self.btn_run.pack(fill="x", pady=(0, 4))

        # SECONDARY: exportação
        self.btn_save = ttk.Button(
            actions, text="Salvar bundle (.mrph)…",
            style="Secondary.TButton",
            command=self._on_save_bundle, state="disabled",
        )
        self.btn_save.pack(fill="x")

        # LabelFrame "Pop-outs" removida — agora cada plot tem ⛶ no header.

    # ------------------------------------------------------------------

    def _build_plot_area(self, parent: ttk.Frame):
        # Cabeçalho com ⛶ por plot
        header = theme.make_plot_header_bar(
            parent,
            items=[
                ("x[n]",                lambda: self._popout_one("x")),
                ("h[n]",                lambda: self._popout_one("h")),
                ("y[n] = (x ∗ h)[n]",   lambda: self._popout_one("y")),
            ],
        )
        header.pack(fill="x", pady=(0, 6))

        self.fig = Figure(figsize=(7, 7), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        self.ax_x = self.fig.add_subplot(311)
        self.ax_h = self.fig.add_subplot(312)
        self.ax_y = self.fig.add_subplot(313)
        for ax, msg in [
                (self.ax_x, "x[n]"),
                (self.ax_h, "h[n]\n(carregue um filtro)"),
                (self.ax_y, "y[n] = (x ∗ h)[n]\n(clique 'Aplicar FIR')")]:
            theme.draw_empty_axes(ax, msg)

        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Ferramentas flutuantes (home/pan/zoom/salvar) no canto superior
        # direito — substituem a antiga toolbar cinza do rodapé.
        self.toolbar = PlotToolbar(self.canvas)

    # ------------------------------------------------------------------
    # Pop-outs por plot
    # ------------------------------------------------------------------

    def _popout_one(self, which: str):
        if which == "x":
            if self.x_input is None:
                messagebox.showwarning("Atenção", "x[n] ainda não foi gerado.")
                return
            def draw(fig: Figure):
                ax = fig.add_subplot(111)
                zeros_x = len(self.x_input) - self.x_n_useful
                _stem_array(ax, self.x_n, self.x_input, dsp.COLOR_X,
                             f"x[n] (N={self.x_n_useful} + {zeros_x} zeros)",
                             "x")
            open_or_focus(self._popouts, key="one_x",
                          parent=self, title="Morphe — x[n]",
                          draw_fn=draw, size="1000x600")
        elif which == "h":
            if self.h_coefs is None:
                messagebox.showwarning("Atenção", "Carregue h[n] antes.")
                return
            def draw(fig: Figure):
                ax = fig.add_subplot(111)
                n_h = np.arange(len(self.h_coefs))
                zeros_h = len(self.h_coefs) - self.h_n_taps
                _stem_array(ax, n_h, self.h_coefs, dsp.COLOR_H,
                             f"h[n] (M={self.h_n_taps} + {zeros_h} zeros)",
                             "h")
            open_or_focus(self._popouts, key="one_h",
                          parent=self, title="Morphe — h[n]",
                          draw_fn=draw, size="1000x600")
        elif which == "y":
            if self.y_output is None:
                messagebox.showwarning("Atenção",
                                       "y[n] ainda não foi calculado.")
                return
            def draw(fig: Figure):
                ax = fig.add_subplot(111)
                n_y = np.arange(len(self.y_output))
                _stem_array(ax, n_y, self.y_output, dsp.COLOR_Y,
                             f"y[n] ({len(self.y_output)} amostras)", "y")
            open_or_focus(self._popouts, key="one_y",
                          parent=self, title="Morphe — y[n]",
                          draw_fn=draw, size="1000x600")

    # ------------------------------------------------------------------
    # Callbacks (lógica preservada)
    # ------------------------------------------------------------------

    def _auto_initial_update(self):
        try:
            n_arr, x = self.builder.compute_signal()
        except ValueError:
            return
        self._on_x_updated(n_arr, x)

    def _on_x_updated(self, n_arr: np.ndarray, x: np.ndarray):
        warn = dsp.q1516_range_warning(x)
        if warn:
            self.status.set(f"[!] {warn}")
        else:
            self.status.set(f"x[n] atualizado: N={len(x)}")
        self.x_n = n_arr
        self.x_input = x
        try:
            n_useful, _ = self.builder.read_globals()
            self.x_n_useful = n_useful
        except ValueError:
            self.x_n_useful = len(x)
        self.y_output = None
        self._update_run_button()
        self._redraw_plots()

    def _open_designer(self, on_apply_callback):
        FIRDesignerWindow(self, on_apply=on_apply_callback)

    def _on_h_loaded(self, coefs: np.ndarray, descr: str,
                       fs: Optional[float] = None,
                       n_taps: Optional[int] = None):
        self.h_coefs = coefs
        self.h_n_taps = n_taps if n_taps is not None else int(np.sum(coefs != 0.0))
        self.h_descr = descr
        self.y_output = None

        if fs is not None:
            self.builder.set_fs_locked(fs, locked=True)
            try:
                n_arr, x = self.builder.compute_signal()
                self.x_n = n_arr
                self.x_input = x
                try:
                    n_useful, _ = self.builder.read_globals()
                    self.x_n_useful = n_useful
                except ValueError:
                    self.x_n_useful = len(x)
            except ValueError:
                pass

        msg = (f"Coeficientes carregados: {self.h_n_taps} taps "
               f"(padded para {MAX_N})")
        if descr:
            msg += f" — {descr}"
        if fs is not None:
            msg += f"  |  fs do sinal travada em {fs:g} Hz"
        self.status.set(msg)
        self._update_run_button()
        self._redraw_plots()

    def _update_run_button(self):
        ok = self.x_input is not None and self.h_coefs is not None
        self.btn_run.configure(state="normal" if ok else "disabled")
        self.btn_save.configure(
            state="normal" if (ok and self.y_output is not None)
                           else "disabled")

    def _on_run(self):
        if self.x_input is None or self.h_coefs is None:
            return

        try:
            client = self.master.tcp_panel.make_client()
        except (AttributeError, ValueError) as e:
            messagebox.showerror("Configuração TCP",
                                 f"Erro: {e}\n"
                                 "Verifique host/porta na janela principal.")
            return

        x = self.x_input
        h = self.h_coefs
        x_q = dsp.float_to_q1516(x)
        h_q = dsp.float_to_q1516(h)
        dtype_code = DTYPE_CODES["int32"]

        self.btn_run.configure(state="disabled")
        self.status.set(f"Enviando para FPGA: N={len(x)}, M={len(h)}...")

        def worker():
            try:
                req = build_fir_request(x_q, h_q, dtype_code)
                resp = client.request(req)
                y_q = decode_fir_response(resp)
                y = dsp.q1516_to_float(y_q.astype(np.int32))
                self.after(0, lambda: self._on_run_done(y))
            except Exception as e:
                self.after(0, lambda err=e: self._on_run_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_run_done(self, y: np.ndarray):
        self.y_output = y
        self.status.set(f"FIR concluído: {len(y)} amostras na saída.")
        self._update_run_button()
        self._redraw_plots()

    def _on_run_error(self, err: Exception):
        self.btn_run.configure(state="normal")
        self.status.set(f"Erro: {err}")
        messagebox.showerror("Erro na execução FIR", str(err))

    def _redraw_plots(self):
        if self.x_input is not None:
            n_useful = self.x_n_useful
            zeros_x = len(self.x_input) - n_useful
            xtitle = (f"x[n] (N={n_useful} amostras + {zeros_x} zeros, "
                      f"total {len(self.x_input)})")
            _stem_array(self.ax_x, self.x_n, self.x_input,
                         dsp.COLOR_X, xtitle, "x")
        else:
            theme.draw_empty_axes(self.ax_x, "x[n]")

        if self.h_coefs is not None:
            n_h = np.arange(len(self.h_coefs), dtype=np.int64)
            zeros_count = len(self.h_coefs) - self.h_n_taps
            title = (f"h[n] (M={self.h_n_taps} taps + "
                     f"{zeros_count} zeros, total {len(self.h_coefs)})")
            if self.h_descr:
                title += f" — {self.h_descr[:50]}"
            _stem_array(self.ax_h, n_h, self.h_coefs,
                         dsp.COLOR_H, title, "h")
        else:
            theme.draw_empty_axes(self.ax_h, "h[n]\n(carregue um filtro)")

        if self.y_output is not None:
            n_y = np.arange(len(self.y_output), dtype=np.int64)
            _stem_array(self.ax_y, n_y, self.y_output,
                         dsp.COLOR_Y, f"y[n] (saída da FPGA, "
                         f"{len(self.y_output)} amostras)", "y")
        else:
            theme.draw_empty_axes(self.ax_y,
                                  "y[n] = (x ∗ h)[n]\n(clique 'Aplicar FIR')")

        self.fig.tight_layout()
        self.canvas.draw_idle()
        refresh_all(self._popouts)

    def _on_save_bundle(self):
        if (self.x_input is None or self.h_coefs is None
                or self.y_output is None):
            return

        path = filedialog.asksaveasfilename(
            title="Salvar bundle FIR",
            defaultextension=".mrph",
            filetypes=[("Morphe bundle", "*.mrph"),
                       ("Todos", "*.*")],
        )
        if not path:
            return

        try:
            try:
                _, fs = self.builder.read_globals()
            except ValueError:
                fs = 1.0

            sections = [
                {"name": "x", "kind": "real", "type": "float32",
                 "fs": fs, "data": self.x_input.astype(np.float32),
                 "n":  np.arange(len(self.x_input), dtype=np.int64),
                 "description": self.builder.describe()},
                {"name": "h", "kind": "real", "type": "float32",
                 "fs": fs, "data": self.h_coefs.astype(np.float32),
                 "n":  np.arange(len(self.h_coefs), dtype=np.int64),
                 "description": self.h_descr or "h[n] (coeficientes FIR)"},
                {"name": "y", "kind": "real", "type": "float32",
                 "fs": fs, "data": self.y_output.astype(np.float32),
                 "n":  np.arange(len(self.y_output), dtype=np.int64),
                 "description": "y[n] = (x * h)[n] — saída da FPGA (FIR)"},
            ]
            dsp.save_mrph_bundle(path, title="Morphe FIR",
                                  sections=sections)
            self.status.set(f"Bundle salvo: {os.path.basename(path)}")
            messagebox.showinfo("OK", f"Bundle salvo em:\n{path}")
        except Exception as e:
            messagebox.showerror("Erro ao salvar bundle", str(e))
