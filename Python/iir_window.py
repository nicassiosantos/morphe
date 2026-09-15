"""iir_window.py -- janela do filtro IIR (via FPGA / TCP).

Gemea da fir_window.py: um sinal de entrada x[n] montado por superposicao,
um filtro (projetado na IIRDesignerWindow ou carregado de um .txt de
secoes), o botao que manda tudo para a FPGA e os graficos.

Duas diferencas que vem do IIR ser realimentado:

  - o grafico do meio nao e h[n] (que num IIR e infinito e pouco diz), e
    sim |H(f)| do projeto e do filtro quantizado -- e o que se ve numa
    tela de MATLAB e o que o aluno compara com a especificacao;
  - a saida da placa e conferida NA HORA, bit a bit, contra o modelo em
    ponto fixo (iir_design.filtra_sos_fixo). Num FIR um LSB de diferenca
    e ruido; num IIR e o sinal de que alguma coisa esta errada, porque a
    diferenca realimenta e nunca mais some. A barra de status diz se
    bateu e, se nao, em qual amostra comecou a divergir.

Saturacao chega no campo `extra` da resposta, nao como erro: o resultado
e mostrado (grudado no limite onde estourou) com o aviso.
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
import iir_design as iir
import morphe_config as cfg
import morphe_theme as theme
from morphe_protocol import build_iir_request, decode_iir_response, DTYPE_CODES
from popout_helper import open_or_focus, refresh_all
from fir_window import SuperpositionBuilder, _stem_array, _make_action_button
from iir_designer_window import IIRDesignerWindow
from plot_toolbar import PlotToolbar

FRAC = cfg.IIR_FRAC_BITS
TOTAL = 32
ESCALA = 1 << FRAC
MAX_N = cfg.IIR_N_MAX

_BTN_LOAD_BG   = "#2563eb"   # blue-600
_BTN_DESIGN_BG = "#7c3aed"   # violet-600
_COLOR_IDEAL = "tab:blue"
_COLOR_QUANT = "tab:red"


def _q(v: np.ndarray) -> np.ndarray:
    """float -> inteiros Q15.16 com o arredondamento do modelo e do
    hardware (floor(v*2^16 + 0.5)), saturado. dsp.float_to_q1516 usa
    np.round, que empata para o par: difere em exatamente .5, e um LSB
    num IIR nao e desprezivel."""
    lim = 1 << (TOTAL - 1)
    q = np.floor(np.asarray(v, dtype=np.float64) * ESCALA + 0.5)
    return np.clip(q, -lim, lim - 1).astype(np.int64)


class IIRFilterPanel(ttk.LabelFrame):
    """Card 'Filtro IIR': de onde vem a cascata e como ela esta."""

    def __init__(self, parent, on_loaded, on_design_request):
        super().__init__(parent, text=" Filtro IIR (seções de 2ª ordem) ",
                         style="Card.TLabelframe", padding=(14, 12, 14, 14))
        self._on_loaded = on_loaded
        self._on_design_request = on_design_request

        self.var_info = tk.StringVar(value="(nenhum filtro carregado)")
        ttk.Label(self, textvariable=self.var_info, style="Card.TLabel",
                  wraplength=320, justify="left").pack(fill="x", pady=(0, 8))

        _make_action_button(self, "Projetar filtro IIR…", _BTN_DESIGN_BG,
                            self._on_design_click).pack(fill="x", pady=2)
        _make_action_button(self, "Carregar seções (.txt)…", _BTN_LOAD_BG,
                            self._on_load_click).pack(fill="x", pady=2)

    def _on_design_click(self):
        self._on_design_request(self.set_filter)

    def _on_load_click(self):
        path = filedialog.askopenfilename(
            title="Carregar seções do filtro IIR",
            filetypes=[("Texto", "*.txt"), ("Seções", "*.sos"),
                       ("Todos", "*.*")])
        if not path:
            return
        try:
            sos, descr, fs = iir.carrega_sos_txt(path)
        except (OSError, iir.IIRSpecError, ValueError) as e:
            messagebox.showerror("Erro ao carregar", str(e))
            return
        self.set_filter(sos, descr or os.path.basename(path), fs)

    def set_filter(self, sos: np.ndarray, descr: str, fs: Optional[float]):
        sos = np.atleast_2d(np.asarray(sos, dtype=np.float64))
        if sos.shape[0] > cfg.IIR_SECOES_MAX:
            messagebox.showerror(
                "Filtro grande demais",
                "%d seções; o hardware aceita %d."
                % (sos.shape[0], cfg.IIR_SECOES_MAX))
            return
        viab = iir.verifica_viabilidade(sos, FRAC, TOTAL, simular=False)
        if viab["veredito"] == "recusar":
            messagebox.showerror(
                "Filtro não cabe em Q15.16", "\n\n".join(viab["motivos"]))
            return
        # Ordem real: uma secao com a2 = 0 e de 1a ordem (filtro impar).
        ordem = int(np.sum(np.abs(sos[:, 4:6]) > 0))
        texto = "%d seções (ordem %d)" % (sos.shape[0], ordem)
        if descr:
            texto += "\n" + descr
        if fs is not None:
            texto += "\nfs do projeto: %g Hz" % fs
        if viab["veredito"] == "alerta":
            texto += "\n[!] " + viab["motivos"][0]
        self.var_info.set(texto)
        self._on_loaded(sos, descr, fs)


class IIRWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Morphe — Filtro IIR (via FPGA / TCP)")
        self.geometry("1240x820")
        self.configure(bg=theme.COLORS["bg"])
        theme.setup_styles(self)

        self.x_input: Optional[np.ndarray] = None
        self.x_n: Optional[np.ndarray] = None
        self.x_n_useful: int = 0
        self.sos: Optional[np.ndarray] = None
        self.sos_descr: str = ""
        self.sos_fs: Optional[float] = None
        self.y_output: Optional[np.ndarray] = None
        self.y_saturou: bool = False
        self.y_confere: Optional[str] = None
        self._popouts: dict = {}

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

    def _build_sidebar(self, parent):
        hw_section = theme.CollapsibleSection(
            parent, title="Limitações do hardware IIR", expanded=False)
        hw_section.pack(fill="x", pady=(0, 6))
        theme.make_banner(
            hw_section.body, kind="warn", wraplength=320,
            text=(f"• x[n]: até {MAX_N} amostras (o bloco processa sempre "
                  f"{MAX_N}; o resto vai como zero)\n"
                  f"• Até {cfg.IIR_SECOES_MAX} seções de 2ª ordem "
                  f"(ordem {2 * cfg.IIR_SECOES_MAX})\n"
                  "• Amostras e coeficientes em Q15.16, "
                  "acumulador de 72 bits, arredondamento na saída\n"
                  "• Saturação em vez de wrap: a saída gruda no limite e "
                  "a placa avisa\n"
                  "• Saída conferida bit a bit com o modelo em Python"),
        ).pack(fill="x")

        self.builder = SuperpositionBuilder(
            parent, on_signal_changed=self._on_x_updated)
        self.builder.pack(fill="x", pady=(6, 0))

        self.filtro = IIRFilterPanel(
            parent, on_loaded=self._on_sos_loaded,
            on_design_request=self._open_designer)
        self.filtro.pack(fill="x", pady=(10, 0))

        actions = ttk.LabelFrame(
            parent, text=" Execução ", style="Card.TLabelframe",
            padding=(14, 12, 14, 14))
        actions.pack(fill="x", pady=(10, 0))
        self.btn_run = ttk.Button(
            actions, text="Aplicar IIR (FPGA)", style="Primary.TButton",
            command=self._on_run, state="disabled")
        self.btn_run.pack(fill="x", pady=(0, 4))
        self.btn_save = ttk.Button(
            actions, text="Salvar bundle (.mrph)…", style="Secondary.TButton",
            command=self._on_save_bundle, state="disabled")
        self.btn_save.pack(fill="x")

    def _build_plot_area(self, parent):
        header = theme.make_plot_header_bar(
            parent,
            items=[
                ("x[n]",           lambda: self._popout_one("x")),
                ("|H(f)|",         lambda: self._popout_one("H")),
                ("y[n] (FPGA)",    lambda: self._popout_one("y")),
            ],
        )
        header.pack(fill="x", pady=(0, 6))

        self.fig = Figure(figsize=(7, 7), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        self.ax_x = self.fig.add_subplot(311)
        self.ax_H = self.fig.add_subplot(312)
        self.ax_y = self.fig.add_subplot(313)
        theme.draw_empty_axes(self.ax_x, "x[n]")
        theme.draw_empty_axes(self.ax_H, "|H(f)|\n(projete ou carregue um filtro)")
        theme.draw_empty_axes(self.ax_y, "y[n] = IIR{x}[n]\n(clique 'Aplicar IIR')")
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.toolbar = PlotToolbar(self.canvas)

    # ------------------------------------------------------------------
    # graficos

    def _draw_H(self, ax):
        ax.clear()
        if self.sos is None:
            theme.draw_empty_axes(ax, "|H(f)|\n(projete ou carregue um filtro)")
            return
        fs = self.sos_fs if self.sos_fs else 1.0
        sos_q, _ = iir.quantiza(self.sos, FRAC, TOTAL)
        f, H = iir.resposta_sos(self.sos, n_freq=2048, fs=fs)
        _, Hq = iir.resposta_sos(sos_q, n_freq=2048, fs=fs)
        piso = 1e-8
        ax.plot(f, 20 * np.log10(np.abs(H) + piso), color=_COLOR_IDEAL,
                lw=1.2, label="projeto")
        ax.plot(f, 20 * np.log10(np.abs(Hq) + piso), color=_COLOR_QUANT,
                lw=1, ls="--", label="quantizado Q15.16")
        ax.set_ylim(-120, 5)
        ax.set_xlim(0, fs / 2)
        titulo = "|H(f)| — %d seções" % self.sos.shape[0]
        if self.sos_descr:
            titulo += " — " + self.sos_descr[:60]
        ax.set_title(titulo, fontsize=10)
        ax.set_xlabel("f (Hz)" if self.sos_fs else "f (normalizada)")
        ax.set_ylabel("dB")
        ax.legend(fontsize=7, loc="lower left")
        theme.style_plot_axes(ax)

    def _titulo_y(self) -> str:
        t = "y[n] (saída da FPGA, %d amostras)" % len(self.y_output)
        if self.y_saturou:
            t += " — SATUROU"
        if self.y_confere:
            t += " — " + self.y_confere
        return t

    def _redraw_plots(self):
        if self.x_input is not None:
            zeros_x = len(self.x_input) - self.x_n_useful
            _stem_array(self.ax_x, self.x_n, self.x_input, dsp.COLOR_X,
                        "x[n] (N=%d amostras + %d zeros, total %d)"
                        % (self.x_n_useful, zeros_x, len(self.x_input)), "x")
        else:
            theme.draw_empty_axes(self.ax_x, "x[n]")

        self._draw_H(self.ax_H)

        if self.y_output is not None:
            n_y = np.arange(len(self.y_output), dtype=np.int64)
            _stem_array(self.ax_y, n_y, self.y_output, dsp.COLOR_Y,
                        self._titulo_y(), "y")
        else:
            theme.draw_empty_axes(
                self.ax_y, "y[n] = IIR{x}[n]\n(clique 'Aplicar IIR')")

        self.fig.tight_layout()
        self.canvas.draw_idle()
        refresh_all(self._popouts)

    def _popout_one(self, which: str):
        if which == "x":
            if self.x_input is None:
                messagebox.showwarning("Atenção", "x[n] ainda não foi gerado.")
                return
            def draw(fig):
                _stem_array(fig.add_subplot(111), self.x_n, self.x_input,
                            dsp.COLOR_X, "x[n] (N=%d)" % self.x_n_useful, "x")
            open_or_focus(self._popouts, key="one_x", parent=self,
                          title="Morphe — x[n]", draw_fn=draw, size="1000x600")
        elif which == "H":
            if self.sos is None:
                messagebox.showwarning("Atenção", "Carregue um filtro antes.")
                return
            def draw(fig):
                self._draw_H(fig.add_subplot(111))
            open_or_focus(self._popouts, key="one_H", parent=self,
                          title="Morphe — |H(f)|", draw_fn=draw, size="1000x600")
        elif which == "y":
            if self.y_output is None:
                messagebox.showwarning("Atenção", "y[n] ainda não foi calculado.")
                return
            def draw(fig):
                n_y = np.arange(len(self.y_output))
                _stem_array(fig.add_subplot(111), n_y, self.y_output,
                            dsp.COLOR_Y, self._titulo_y(), "y")
            open_or_focus(self._popouts, key="one_y", parent=self,
                          title="Morphe — y[n]", draw_fn=draw, size="1000x600")

    # ------------------------------------------------------------------
    # callbacks

    def _auto_initial_update(self):
        try:
            n_arr, x = self.builder.compute_signal()
        except ValueError:
            return
        self._on_x_updated(n_arr, x)

    def _on_x_updated(self, n_arr, x):
        warn = dsp.q1516_range_warning(x)
        self.status.set(("[!] " + warn) if warn else "x[n] atualizado: N=%d" % len(x))
        self.x_n, self.x_input = n_arr, x
        try:
            self.x_n_useful, _ = self.builder.read_globals()
        except ValueError:
            self.x_n_useful = len(x)
        self.y_output = None
        self._update_run_button()
        self._redraw_plots()

    def _open_designer(self, on_apply_callback):
        IIRDesignerWindow(self, on_apply=on_apply_callback)

    def _on_sos_loaded(self, sos, descr, fs):
        self.sos, self.sos_descr, self.sos_fs = sos, descr, fs
        self.y_output = None
        if fs is not None:
            # Filtro e sinal na mesma taxa, como a janela FIR faz.
            self.builder.set_fs_locked(fs, locked=True)
            try:
                self.x_n, self.x_input = self.builder.compute_signal()
                self.x_n_useful, _ = self.builder.read_globals()
            except ValueError:
                pass
        msg = "Filtro IIR: %d seções" % sos.shape[0]
        if descr:
            msg += " — " + descr
        if fs is not None:
            msg += "  |  fs do sinal travada em %g Hz" % fs
        self.status.set(msg)
        self._update_run_button()
        self._redraw_plots()

    def _update_run_button(self):
        ok = self.x_input is not None and self.sos is not None
        self.btn_run.configure(state="normal" if ok else "disabled")
        self.btn_save.configure(
            state="normal" if (ok and self.y_output is not None) else "disabled")

    def _on_run(self):
        if self.x_input is None or self.sos is None:
            return
        try:
            client = self.master.tcp_panel.make_client()
        except (AttributeError, ValueError) as e:
            messagebox.showerror("Configuração TCP",
                                 "Erro: %s\nVerifique host/porta na janela principal." % e)
            return

        x = self.x_input[:MAX_N]
        sos = self.sos
        x_q = _q(x)
        coefs = iir.coeficientes_inteiros(sos, FRAC, TOTAL)
        dtype_code = DTYPE_CODES["int32"]

        self.btn_run.configure(state="disabled")
        self.status.set("Enviando para FPGA: N=%d, %d seções..." % (len(x), len(coefs)))

        def worker():
            try:
                resp = client.request(build_iir_request(x_q, coefs, dtype_code))
                y_q, saturou = decode_iir_response(resp)
                # Referencia: o mesmo modelo que o testbench e o
                # testa_iir_hw usam. Se a placa bate aqui, bate em tudo.
                y_ref = _q(iir.filtra_sos_fixo(x, sos, FRAC, TOTAL))
                self.after(0, lambda: self._on_run_done(y_q, saturou, y_ref))
            except Exception as e:
                self.after(0, lambda err=e: self._on_run_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_run_done(self, y_q, saturou, y_ref):
        self.y_output = dsp.q1516_to_float(y_q)
        self.y_saturou = saturou
        dif = np.nonzero(y_q != y_ref[:len(y_q)])[0]
        if dif.size == 0:
            self.y_confere = "bit a bit igual ao modelo"
            msg = "IIR concluído: %d amostras, bit a bit igual ao modelo em Python." % len(y_q)
        else:
            i = int(dif[0])
            self.y_confere = "DIFERE do modelo em %d amostras (1ª em n=%d)" % (dif.size, i)
            msg = ("[!] IIR concluído, mas a saída difere do modelo em %d amostras; "
                   "primeira em n=%d (placa %d, modelo %d)."
                   % (dif.size, i, y_q[i], y_ref[i]))
        if saturou:
            msg += "  SATUROU em alguma amostra."
        self.status.set(msg)
        self._update_run_button()
        self._redraw_plots()

    def _on_run_error(self, err):
        self.btn_run.configure(state="normal")
        self.status.set("Erro: %s" % err)
        messagebox.showerror("Erro na execução IIR", str(err))

    def _on_save_bundle(self):
        if self.x_input is None or self.sos is None or self.y_output is None:
            return
        path = filedialog.asksaveasfilename(
            title="Salvar bundle IIR", defaultextension=".mrph",
            filetypes=[("Morphe bundle", "*.mrph"), ("Todos", "*.*")])
        if not path:
            return
        try:
            try:
                _, fs = self.builder.read_globals()
            except ValueError:
                fs = 1.0
            coefs = np.asarray(iir.coeficientes_inteiros(self.sos, FRAC, TOTAL),
                               dtype=np.float64).reshape(-1)
            # x vai já encaixado na grade Q15.16 (o que a placa recebeu),
            # para o comparador refazer a conta a partir dos mesmos inteiros.
            x = _q(self.x_input[:MAX_N]) / ESCALA
            sections = [
                {"name": "x", "kind": "real", "type": "float32", "fs": fs,
                 "data": x.astype(np.float32),
                 "n": np.arange(len(x), dtype=np.int64),
                 "description": self.builder.describe()},
                # h guarda os COEFICIENTES INTEIROS Q15.16, 5 por secao
                # (b0 b1 b2 a1 a2): e o que o servidor grava no bundle
                # dele e o que o comparador precisa para refazer a conta.
                {"name": "h", "kind": "real", "type": "float32", "fs": fs,
                 "data": coefs.astype(np.float32),
                 "n": np.arange(len(coefs), dtype=np.int64),
                 "description": "IIR Q15.16: %d secoes x (b0 b1 b2 a1 a2) inteiros; %s"
                                % (self.sos.shape[0], self.sos_descr or "")},
                {"name": "y", "kind": "real", "type": "float32", "fs": fs,
                 "data": self.y_output.astype(np.float32),
                 "n": np.arange(len(self.y_output), dtype=np.int64),
                 "description": "y[n] = IIR{x}[n] — saída da FPGA"
                                + (" (saturou)" if self.y_saturou else "")},
            ]
            dsp.save_mrph_bundle(path, title="Morphe IIR", sections=sections)
            self.status.set("Bundle salvo: %s" % os.path.basename(path))
            messagebox.showinfo("OK", "Bundle salvo em:\n%s" % path)
        except Exception as e:
            messagebox.showerror("Erro ao salvar bundle", str(e))
