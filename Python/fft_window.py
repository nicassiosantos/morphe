"""
fft_window.py — gera um sinal, envia à FPGA via TCP, recebe X[k] complexo
e exibe magnitude/fase.

Hardware: FFT IP em buffered burst, N=1024 fixo. Sinais menores são
zero-padded até 1024 (o que equivale, no domínio da frequência, a
interpolação espectral). A configuração TCP é compartilhada com a
janela principal (master.tcp_panel).
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional

import numpy as np

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import dsp_core as dsp
import morphe_theme as theme
from signal_panel import SignalPanel
from morphe_protocol import (build_fft_request, decode_fft_response,
                             build_ifft_request, decode_ifft_response)
from popout_helper import open_or_focus, refresh_all
from plot_toolbar import PlotToolbar


# ----------------------------------------------------------------------
# Helpers de plot (inalterados — comportamento já estava bom)

def _attach_stem_format_coord(ax, n_arr: np.ndarray, x_arr: np.ndarray,
                               x_label: str = "n", y_label: str = "x",
                               value_fmt: str = "{:.4g}"):
    """Substitui o display (x,y) cartesiano pelo valor da amostra discreta
    mais próxima do cursor: 'n=12, x[12] = 0.7314'."""
    if n_arr.size == 0:
        return
    n_arr = np.asarray(n_arr, dtype=float)
    x_arr = np.asarray(x_arr)

    def fmt(xc, yc):
        i = int(np.argmin(np.abs(n_arr - xc)))
        n_i = n_arr[i]
        v = x_arr[i]
        try:
            v_str = value_fmt.format(float(v))
        except (TypeError, ValueError):
            v_str = str(v)
        return f"{x_label}={int(n_i)},  {y_label}[{int(n_i)}] = {v_str}"

    ax.format_coord = fmt


def _stem_signal(ax, sig: Optional[dsp.Signal], title: str, color: str):
    ax.clear()
    if sig is None or sig.n.size == 0:
        theme.draw_empty_axes(ax, title)
        return
    n_plot = np.asarray(sig.n, dtype=float)
    ml, sl, _ = ax.stem(n_plot, sig.x, basefmt=" ")
    ml.set_markersize(4)
    ml.set_color(color)
    ml.set_markerfacecolor(color)
    sl.set_color(color)
    ax.set_title(f"{title}  —  {sig.description}", fontsize=9)
    ax.axhline(0, color=theme.COLORS["axis"], linewidth=0.6)
    n_min, n_max = float(n_plot.min()), float(n_plot.max())
    mx = max(1.0, 0.05 * (n_max - n_min))
    ax.set_xlim(n_min - mx, n_max + mx)
    if sig.x.size:
        x_min, x_max = float(np.min(sig.x)), float(np.max(sig.x))
        if x_min == x_max:
            x_min -= 0.5
            x_max += 0.5
        my = 0.1 * (x_max - x_min)
        ax.set_ylim(x_min - my, x_max + my)
    ax.set_xlabel("n")
    theme.style_plot_axes(ax)
    _attach_stem_format_coord(ax, n_plot, sig.x, x_label="n", y_label="x")


def _overlay_ifft(ax, x_ifft: Optional[np.ndarray], sig: Optional[dsp.Signal]):
    """Desenha por cima do x[n] o que a IFFT da FPGA devolveu.

    Fica como linha, e nao stem, para nao brigar com o stem do original:
    quando o ida-e-volta fecha, a linha passa exatamente pelas bolinhas.
    Onde nao passar, o erro esta visivel sem precisar de numero.
    """
    if x_ifft is None or sig is None or sig.n.size == 0:
        return
    n = np.arange(len(x_ifft), dtype=float)
    ax.plot(n, np.real(x_ifft), color=dsp.COLOR_Y, linewidth=1.1,
            alpha=0.9, zorder=3, label="IFFT da FPGA")
    ax.legend(fontsize=7, loc="upper right")


def _stem_complex_mag(ax, X: Optional[np.ndarray], db: bool, color: str,
                      fs: float = 1.0):
    ax.clear()
    if X is None:
        theme.draw_empty_axes(ax, "|X[k]|")
        return
    N = len(X)
    k = np.arange(N, dtype=float)
    mag = np.abs(X)

    if db:
        eps = 1e-20
        mag_plot = 20 * np.log10(mag + eps)
        ax.plot(k, mag_plot, marker="o", markersize=3, color=color)
        ax.set_ylabel("|X[k]|  (dB)")
        ax.set_title(f"|X[k]| em dB  (N={N})", fontsize=10)
    else:
        ml, sl, _ = ax.stem(k, mag, basefmt=" ")
        ml.set_markersize(3)
        ml.set_color(color)
        ml.set_markerfacecolor(color)
        sl.set_color(color)
        ax.set_ylabel("|X[k]|")
        ax.set_title(f"|X[k]|  (N={N})", fontsize=10)

    ax.set_xlabel("k")
    theme.style_plot_axes(ax)
    _attach_stem_format_coord(ax, k, mag,
                               x_label="k", y_label="|X|",
                               value_fmt="{:.4g}")


def _stem_complex_phase(ax, X: Optional[np.ndarray], color: str):
    ax.clear()
    if X is None:
        theme.draw_empty_axes(ax, "Fase de X[k]")
        return
    N = len(X)
    k = np.arange(N, dtype=float)
    phase = np.angle(X)
    ml, sl, _ = ax.stem(k, phase, basefmt=" ")
    ml.set_markersize(3)
    ml.set_color(color)
    ml.set_markerfacecolor(color)
    sl.set_color(color)
    ax.set_title("Fase de X[k] (rad)", fontsize=10)
    ax.set_xlabel("k")
    theme.style_plot_axes(ax)
    _attach_stem_format_coord(ax, k, phase,
                               x_label="k", y_label="fase",
                               value_fmt="{:+.4f} rad")


# ----------------------------------------------------------------------

class FFTWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Morphe — FFT via FPGA (TCP)")
        self.geometry("1320x840")
        self.configure(bg=theme.COLORS["bg"])

        theme.setup_styles(self)

        self.x_sig: Optional[dsp.Signal] = None
        self.X_complex: Optional[np.ndarray] = None
        #: x[n] reconstruido pela IFFT da FPGA, quando o usuario pede a
        #: volta ao tempo. Fica sobreposto ao x[n] original.
        self.x_ifft: Optional[np.ndarray] = None

        # Registry de pop-outs vivos: chave -> ReactivePopout.
        self._popouts: dict = {}

        # ── Barra de status no rodapé (packed primeiro com side="bottom") ──
        self.status = tk.StringVar(value="Pronto.")
        theme.make_status_bar(self, self.status).pack(side="bottom", fill="x")

        # ── Container principal ──
        root = ttk.Frame(self, style="Main.TFrame", padding=12)
        root.pack(fill="both", expand=True)

        # ── Sidebar esquerda ──
        sidebar = ttk.Frame(root, style="Main.TFrame")
        sidebar.pack(side="left", fill="y", padx=(0, 12))
        self._build_sidebar(sidebar)

        # ── Área de plots à direita ──
        plot_area = ttk.Frame(root, style="Main.TFrame")
        plot_area.pack(side="right", fill="both", expand=True)
        self._build_plot_area(plot_area)

        self._redraw()

    # ------------------------------------------------------------------
    # Construção da sidebar
    # ------------------------------------------------------------------

    def _build_sidebar(self, parent: ttk.Frame):
        # ── Limitações do hardware: progressive disclosure ──
        # Conteúdo denso ocupava ~150px do sidebar o tempo todo. Agora
        # vive em uma seção colapsável, fechada por padrão.
        hw_section = theme.CollapsibleSection(
            parent, title="Limitações do FFT IP (FPGA)",
            expanded=False,
        )
        hw_section.pack(fill="x", pady=(0, 6))

        # Texto formatado em "bullets" reais com espaçamento maior
        hw_text = (
            f"• Tamanho da FFT: fixo em {dsp.MAX_FFT_INPUT_SIZE} pontos\n"
            f"• Sinais com N < {dsp.MAX_FFT_INPUT_SIZE} são zero-padded "
            "(equivale a interpolação espectral)\n"
            f"• Sinais com N > {dsp.MAX_FFT_INPUT_SIZE} não são aceitos\n"
            f"• Formato Q15.8 no fio: 24 bits úteis, 8 fracionários\n"
            f"• Faixa de entrada: "
            f"[{dsp.FFT_Q_MIN_FLOAT:.1f}, {dsp.FFT_Q_MAX_FLOAT:.4f}]\n"
            f"• Resolução: 2⁻⁸ = {dsp.FFT_Q_RESOLUTION:.4f}\n"
            "• Saída: 1024 bins complexos float32"
        )
        theme.make_banner(
            hw_section.body, kind="warn", text=hw_text,
            wraplength=320,
        ).pack(fill="x")

        # ── Painel de geração de x[n] ──
        # Nota: a sugestão 2 (alinhar A:, f:, fs:, φ:) é interna ao
        # SignalPanel — depende daquele arquivo.
        self.x_panel = SignalPanel(
            parent, title="Sinal x[n]",
            on_generate=self._on_gen_x,
            default_N=64,
            default_type="Senóide",
            max_N=dsp.MAX_FFT_INPUT_SIZE,
        )
        self.x_panel.pack(fill="x", pady=(6, 0))

        # ── Operações FFT & Exportação ──
        op = ttk.LabelFrame(
            parent, text=" FFT & Exportação ",
            style="Card.TLabelframe",
            padding=(14, 12, 14, 14),
        )
        op.pack(fill="x", pady=(12, 0))

        ttk.Label(
            op,
            text="Formato no fio: int32 Q15.8 (fixado pelo hardware)",
            style="SectionHint.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        self.var_magdb = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            op, text="Magnitude em dB",
            variable=self.var_magdb,
            command=self._redraw_spectrum,
            style="Card.TCheckbutton",
        ).pack(anchor="w", pady=(0, 10))

        # PRIMARY: o botão mais importante da tela
        self.btn_fft = ttk.Button(
            op, text="Calcular FFT na FPGA",
            style="Primary.TButton",
            command=self._on_fft,
        )
        self.btn_fft.pack(fill="x", pady=(0, 4))

        # Volta ao tempo: mesma IP da FFT com o bit `inverse` ligado.
        # Fica desabilitado ate existir um X[k] para mandar de volta.
        self.btn_ifft = ttk.Button(
            op, text="IFFT na FPGA (voltar ao tempo)",
            style="Secondary.TButton",
            command=self._on_ifft,
            state="disabled",
        )
        self.btn_ifft.pack(fill="x", pady=(0, 4))

        # SECONDARY: ação de exportação
        ttk.Button(
            op, text="Salvar tudo (x, X) em 1 arquivo .mrph",
            style="Secondary.TButton",
            command=self._on_save_all,
        ).pack(fill="x")

        # Nota: o antigo botão "Visualizar em janela ampliada" foi
        # removido. Cada plot agora tem seu próprio ⛶ no cabeçalho,
        # eliminando a redundância apontada na sugestão 3.

    # ------------------------------------------------------------------
    # Construção da área de plots
    # ------------------------------------------------------------------

    def _build_plot_area(self, parent: ttk.Frame):
        # Cabeçalho da área de plots: rótulos prominentes + ⛶ por plot.
        # Substitui a antiga linha "Pop-out x[n] | Pop-out |X[k]| | ...".
        header = theme.make_plot_header_bar(
            parent,
            items=[
                ("x[n]",            lambda: self._popout_one("x")),
                ("|X[k]|",          lambda: self._popout_one("mag")),
                ("Fase de X[k]",    lambda: self._popout_one("phase")),
            ],
        )
        header.pack(fill="x", pady=(0, 6))

        # Figura com 3 subplots verticais (igual ao antes).
        self.fig = Figure(figsize=(7, 8), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        self.ax_x = self.fig.add_subplot(311)
        self.ax_mag = self.fig.add_subplot(312)
        self.ax_phase = self.fig.add_subplot(313)

        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Ferramentas flutuantes (home/pan/zoom/salvar) no canto superior
        # direito — substituem a antiga toolbar cinza do rodapé.
        self.toolbar = PlotToolbar(self.canvas)

    # ------------------------------------------------------------------
    # Render dos plots
    # ------------------------------------------------------------------

    @property
    def _signal_fs(self) -> float:
        return float(self.x_sig.fs) if self.x_sig is not None else 1.0

    def _redraw(self):
        _stem_signal(self.ax_x, self.x_sig, "x[n]", dsp.COLOR_X)
        _overlay_ifft(self.ax_x, self.x_ifft, self.x_sig)
        _stem_complex_mag(self.ax_mag, self.X_complex,
                          self.var_magdb.get(), dsp.COLOR_MAG,
                          fs=self._signal_fs)
        _stem_complex_phase(self.ax_phase, self.X_complex, dsp.COLOR_PHASE)
        self.fig.tight_layout()
        self.canvas.draw_idle()
        refresh_all(self._popouts)

    def _redraw_spectrum(self):
        _stem_complex_mag(self.ax_mag, self.X_complex,
                          self.var_magdb.get(), dsp.COLOR_MAG,
                          fs=self._signal_fs)
        _stem_complex_phase(self.ax_phase, self.X_complex, dsp.COLOR_PHASE)
        self.fig.tight_layout()
        self.canvas.draw_idle()
        refresh_all(self._popouts)

    # ------------------------------------------------------------------
    # Pop-outs reativos
    # ------------------------------------------------------------------

    def _popout_one(self, which: str):
        if which == "x":
            if self.x_sig is None:
                messagebox.showwarning("Atenção", "x[n] ainda não foi gerado.")
                return
            def draw(fig: Figure):
                ax = fig.add_subplot(111)
                _stem_signal(ax, self.x_sig, "x[n]", dsp.COLOR_X)
                _overlay_ifft(ax, self.x_ifft, self.x_sig)
            open_or_focus(self._popouts, key="one_x",
                          parent=self, title="Morphe — x[n]",
                          draw_fn=draw, size="1000x600")
        elif which == "mag":
            if self.X_complex is None:
                messagebox.showwarning("Atenção",
                                       "FFT ainda não foi calculada.")
                return
            def draw(fig: Figure):
                _stem_complex_mag(fig.add_subplot(111), self.X_complex,
                                  self.var_magdb.get(), dsp.COLOR_MAG,
                                  fs=self._signal_fs)
            open_or_focus(self._popouts, key="one_mag",
                          parent=self, title="Morphe — |X[k]|",
                          draw_fn=draw, size="1000x600")
        elif which == "phase":
            if self.X_complex is None:
                messagebox.showwarning("Atenção",
                                       "FFT ainda não foi calculada.")
                return
            def draw(fig: Figure):
                _stem_complex_phase(fig.add_subplot(111), self.X_complex,
                                    dsp.COLOR_PHASE)
            open_or_focus(self._popouts, key="one_phase",
                          parent=self, title="Morphe — Fase de X[k]",
                          draw_fn=draw, size="1000x600")

    # `_on_popout_all` removido: a sugestão de UX pediu consolidação
    # dos mecanismos de expansão. Cada plot agora tem seu próprio ⛶.
    # Para ver os três juntos, abra os três pop-outs e organize na tela.

    # ------------------------------------------------------------------
    # Callbacks de operação
    # ------------------------------------------------------------------

    def _on_gen_x(self, panel: SignalPanel):
        try:
            self.x_sig = panel.build()
            self._redraw()
            self.status.set(f"x[n]: {self.x_sig.description}")
        except Exception as e:
            messagebox.showerror("Erro em x[n]", str(e))

    def _on_fft(self):
        if self.x_sig is None:
            messagebox.showwarning("Atenção", "Gere x[n] antes.")
            return

        try:
            client = self.master.tcp_panel.make_client()
        except Exception as e:
            messagebox.showerror("Configuração", str(e))
            return

        try:
            x_padded = dsp.pad_zeros_to(self.x_sig.x, dsp.MAX_FFT_INPUT_SIZE)
        except ValueError as e:
            messagebox.showerror("Tamanho excedido", str(e))
            return

        warn = dsp.fft_q1508_range_warning(x_padded)
        if warn:
            ok = messagebox.askokcancel(
                "Atenção — faixa Q15.8",
                f"{warn}\n\nDeseja continuar mesmo assim?")
            if not ok:
                return

        n_orig = int(self.x_sig.x.size)
        self.btn_fft.config(state="disabled")
        self.status.set(
            f"Padding {n_orig}→{dsp.MAX_FFT_INPUT_SIZE} amostras, "
            "enviando à FPGA..."
        )

        def worker():
            try:
                req = build_fft_request(x_padded)
                resp = client.request(req)
                X = decode_fft_response(resp)
                self.after(0, lambda: self._on_fft_done(X))
            except Exception as e:
                self.after(0, lambda err=e: self._on_fft_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_fft_done(self, X: np.ndarray):
        self.X_complex = X
        # Um X[k] novo invalida a reconstrucao anterior.
        self.x_ifft = None
        self._redraw()
        self.btn_fft.config(state="normal")
        self.btn_ifft.config(state="normal")
        self.status.set(f"OK. FFT com {len(X)} pontos.")

    def _on_fft_error(self, err: Exception):
        self.btn_fft.config(state="normal")
        messagebox.showerror("Erro na FFT", str(err))
        self.status.set("Erro — ver mensagem.")

    # ------------------------------------------------------------------
    # IFFT: o mesmo IP, com o bit `inverse` ligado
    # ------------------------------------------------------------------

    def _on_ifft(self):
        if self.X_complex is None:
            messagebox.showwarning("Atenção", "Calcule a FFT antes.")
            return

        try:
            client = self.master.tcp_panel.make_client()
        except Exception as e:
            messagebox.showerror("Configuração", str(e))
            return

        X = self.X_complex
        self.btn_ifft.config(state="disabled")
        self.status.set("Mandando X[k] de volta à FPGA (inverse=1)...")

        def worker():
            try:
                req, escala = build_ifft_request(X)
                resp = client.request(req)
                x_rec = decode_ifft_response(resp, escala)
                self.after(0, lambda: self._on_ifft_done(x_rec))
            except Exception as e:
                self.after(0, lambda err=e: self._on_ifft_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_ifft_done(self, x_rec: np.ndarray):
        self.x_ifft = x_rec
        self._redraw()
        self.btn_ifft.config(state="normal")

        # O numero que interessa: o quanto o ida-e-volta fechou. Compara
        # so a parte do sinal original, sem o zero-padding.
        msg = f"OK. IFFT com {len(x_rec)} pontos."
        if self.x_sig is not None:
            n_orig = int(self.x_sig.x.size)
            pico = float(np.max(np.abs(self.x_sig.x)))
            if n_orig <= len(x_rec) and pico > 0.0:
                erro = float(np.max(np.abs(
                    np.real(x_rec[:n_orig]) - self.x_sig.x))) / pico
                vaz = float(np.max(np.abs(np.imag(x_rec)))) / pico
                msg += (f"  Erro do ida-e-volta: {erro:.2e} "
                        f"(vazamento na imaginária: {vaz:.2e})")
        self.status.set(msg)

    def _on_ifft_error(self, err: Exception):
        self.btn_ifft.config(state="normal")
        messagebox.showerror("Erro na IFFT", str(err))
        self.status.set("Erro — ver mensagem.")

    # ------------------------------------------------------------------
    # Save all
    # ------------------------------------------------------------------

    def _on_save_all(self):
        if self.x_sig is None:
            messagebox.showwarning("Atenção", "Gere x[n] antes de salvar.")
            return
        if self.X_complex is None:
            if not messagebox.askyesno(
                "FFT não calculada",
                "X[k] ainda não foi calculado. Salvar somente x[n]?",
            ):
                return

        try:
            path = filedialog.asksaveasfilename(
                title="Salvar todos os sinais em um único arquivo .mrph",
                defaultextension=".mrph",
                initialfile="fft_bundle.mrph",
                filetypes=[("Morphe", "*.mrph"), ("Todos", "*.*")],
            )
            if not path:
                return

            dtype_out = "float32"
            sections = [
                {
                    "name": "x",
                    "kind": "real",
                    "n":    self.x_sig.n,
                    "data": self.x_sig.x,
                    "description": f"x[n] - {self.x_sig.description}",
                    "fs":   self.x_sig.fs,
                    "dtype_out": dtype_out,
                },
            ]

            if self.X_complex is not None:
                N = len(self.X_complex)
                k = np.arange(N, dtype=np.int64)
                fs = self.x_sig.fs
                sections.append({
                    "name": "X",
                    "kind": "complex",
                    "n":    k,
                    "data": self.X_complex,
                    "description": f"X[k] = FFT(x), N={N}",
                    "fs":   fs,
                })

            if self.x_ifft is not None:
                m = len(self.x_ifft)
                sections.append({
                    "name": "x_ifft",
                    "kind": "complex",
                    "n":    np.arange(m, dtype=np.int64),
                    "data": self.x_ifft,
                    "description": (f"x[n] reconstruido = IFFT(X) na FPGA, "
                                    f"N={m}"),
                    "fs":   self.x_sig.fs,
                })

            dsp.save_mrph_bundle(
                path, title="Morphe FFT", sections=sections)
            messagebox.showinfo(
                "OK",
                f"Bundle salvo em:\n{path}\n\n"
                f"Seções: {', '.join(s['name'] for s in sections)}",
            )
            self.status.set(
                f"Bundle salvo ({len(sections)} seções): "
                f"{os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e))
