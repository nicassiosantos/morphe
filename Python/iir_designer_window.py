"""iir_designer_window.py -- projetar um filtro IIR por especificacao.

Porte da janela Iir_filter_window.m do DSPFinal (Prof. Armando S. Sanca)
para o cliente Morphe. Os mesmos controles -- aproximacao (Butterworth,
Chebyshev I, Chebyshev II, eliptica), bordas fp/fs, ripple dp, atenuacao
ds, taxa Fs -- e as mesmas saidas: tipo e ordem do filtro, mapa de polos e
zeros com resposta ao impulso, e freqz (modulo e fase). O calculo e o do
iir_design.py, porte do dsp_iir_filter.m com os quatro erros corrigidos.

O que a janela do MATLAB nao mostra, e esta mostra, porque o filtro vai
para uma FPGA em Q15.16:

  - os polos DEPOIS de quantizar, sobre o mesmo mapa, para ver quanto cada
    um andou (num IIR e isso que decide se o filtro continua estavel);
  - a resposta em frequencia quantizada sobre a ideal;
  - o veredito de viabilidade (ok / alerta / recusar) com os motivos, antes
    de deixar aplicar.

Convencao do professor mantida: "fs" (minusculo) e a borda da banda de
rejeicao e "Fs" e a taxa de amostragem. Na tela os rotulos dizem qual e
qual.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Callable, Optional

import numpy as np

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import iir_design as iir
import morphe_config as cfg
import morphe_theme as theme
from plot_toolbar import PlotToolbar


_TYPE_UI_TO_INT = {
    "Passa-baixa":   "lowpass",
    "Passa-alta":    "highpass",
    "Passa-banda":   "bandpass",
    "Rejeita-banda": "bandstop",
}

_APROX_UI = [
    ("Butterworth",  "butterworth"),
    ("Chebyshev I",  "cheby1"),
    ("Chebyshev II", "cheby2"),
    ("Elíptica",     "ellip"),
]

_SIDEBAR_W = 360
_WRAP = _SIDEBAR_W - 40

_BTN_APPLY_BG  = "#16a34a"   # green-600  aplicar
_BTN_SAVE_BG   = "#2563eb"   # blue-600   salvar
_BTN_DESIGN_BG = "#7c3aed"   # violet-600 recalcular
_BTN_FG_LIGHT  = "white"

_COLOR_IDEAL = "tab:blue"
_COLOR_QUANT = "tab:red"
_COLOR_IMP   = "tab:orange"

#: Quantas amostras da resposta ao impulso mostrar: ate a cauda cair a
#: 1e-4 do pico, com teto -- um polo em 0,988 demora ~700 amostras.
_IMP_MAX = 1024
_IMP_MIN = 32

FRAC = cfg.IIR_FRAC_BITS
TOTAL = 32


def _stretch_fields(frame):
    frame.columnconfigure(1, weight=1)
    for child in frame.winfo_children():
        info = child.grid_info()
        if info and int(info.get("column", 0)) == 1:
            child.grid_configure(sticky="ew")


def _make_action_button(parent, text: str, bg: str,
                        command: Callable[[], None]) -> tk.Button:
    return tk.Button(
        parent, text=text,
        bg=bg, fg=_BTN_FG_LIGHT,
        activebackground=bg, activeforeground=_BTN_FG_LIGHT,
        bd=0, relief="flat",
        font=("TkDefaultFont", 9, "bold"),
        cursor="hand2",
        padx=8, pady=5,
        command=command,
    )


class IIRDesignerWindow(tk.Toplevel):
    """Toplevel para projetar filtros IIR.

    on_apply(sos, descricao, fs): chamado em 'Aplicar a janela IIR' com a
    cascata JA com o ganho distribuido entre as secoes (o que vai para o
    hardware), a descricao e a taxa de amostragem do projeto.
    """

    def __init__(self, master, on_apply: Callable[[np.ndarray, str, float], None]):
        super().__init__(master)
        self.title("Morphe — Projetar filtro IIR")
        self.configure(bg=theme.COLORS["bg"])
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry("%dx%d" % (min(1180, sw - 80), min(880, sh - 80)))
        self.minsize(880, 520)

        theme.setup_styles(self)

        self._on_apply = on_apply
        self.projeto: Optional[iir.ProjetoIIR] = None
        self.sos_hw: Optional[np.ndarray] = None      # ganho distribuido
        self.viabilidade: Optional[dict] = None
        self.description: str = ""
        self._dirty_after_id: Optional[str] = None

        self.status = tk.StringVar(value="Pronto. Ajuste a especificação.")
        theme.make_status_bar(self, self.status).pack(side="bottom", fill="x")

        root = ttk.Frame(self, style="Main.TFrame", padding=8)
        root.pack(fill="both", expand=True)

        left_outer, left = self._make_scroll_column(root, _SIDEBAR_W)
        left_outer.pack(side="left", fill="y", padx=(0, 8))
        right = ttk.Frame(root, style="Main.TFrame")
        right.pack(side="right", fill="both", expand=True)

        self._build_controls(left)
        self._build_actions(left)
        self._build_plots(right)

        self._on_type_change()
        self.after(100, self._on_design)

    # ==================================================================
    # UI
    # ==================================================================

    def _make_scroll_column(self, parent, width: int):
        outer = ttk.Frame(parent, style="Main.TFrame")
        canvas = tk.Canvas(outer, width=width, bd=0, highlightthickness=0,
                           background=theme.COLORS["bg"])
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, style="Main.TFrame")
        canvas.configure(yscrollcommand=vsb.set)
        item = canvas.create_window((0, 0), window=inner, anchor="nw",
                                    width=width)
        canvas.pack(side="left", fill="y", expand=False)
        estado = {"w": width}

        def _on_inner_config(_ev=None):
            req = max(width, inner.winfo_reqwidth())
            if req != estado["w"]:
                estado["w"] = req
                canvas.itemconfigure(item, width=req)
                canvas.configure(width=req)
            canvas.configure(scrollregion=canvas.bbox("all"))
            precisa = inner.winfo_reqheight() > canvas.winfo_height()
            if precisa and not vsb.winfo_ismapped():
                vsb.pack(side="right", fill="y")
            elif not precisa and vsb.winfo_ismapped():
                vsb.pack_forget()

        inner.bind("<Configure>", _on_inner_config)
        canvas.bind("<Configure>", _on_inner_config)

        def _on_wheel(ev):
            if inner.winfo_reqheight() > canvas.winfo_height():
                canvas.yview_scroll(-1 if ev.delta > 0 else 1, "units")

        canvas.bind("<Enter>",
                    lambda e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>",
                    lambda e: canvas.unbind_all("<MouseWheel>"))
        return outer, inner

    def _entry(self, frame, row, label, var, default):
        ttk.Label(frame, text=label, style="Card.TLabel").grid(
            row=row, column=0, sticky="w", pady=(4, 0))
        var.set(default)
        e = ttk.Entry(frame, textvariable=var, width=12)
        e.grid(row=row, column=1, sticky="w", padx=4, pady=(4, 0))
        e.bind("<KeyRelease>", lambda ev: self._schedule_redesign())
        return e

    def _build_controls(self, parent):
        self._banner = theme.make_banner(
            parent, kind="info", wraplength=_WRAP,
            text=("Cascata de seções de 2ª ordem em Q15.16, até %d seções "
                  "(ordem %d). O mapa mostra os polos antes e depois de "
                  "quantizar: é isso que decide se o filtro sobrevive ao "
                  "hardware." % (cfg.IIR_SECOES_MAX, 2 * cfg.IIR_SECOES_MAX)))
        self._banner.pack(fill="x", pady=(0, 6))

        # ---- Aproximacao (os quatro radios do professor)
        aprox_box = ttk.LabelFrame(
            parent, text=" Aproximação ",
            style="Card.TLabelframe", padding=(14, 10, 14, 12))
        aprox_box.pack(fill="x", pady=3)
        self.var_aprox = tk.StringVar(value="butterworth")
        for rotulo, chave in _APROX_UI:
            rb = ttk.Radiobutton(
                aprox_box, text=rotulo, variable=self.var_aprox,
                value=chave, command=self._schedule_redesign)
            rb.pack(anchor="w")
            if chave == "ellip" and not iir.TEM_SCIPY:
                rb.configure(state="disabled",
                             text="Elíptica  (precisa do scipy)")

        # ---- Tipo
        type_box = ttk.LabelFrame(
            parent, text=" Tipo de filtro ",
            style="Card.TLabelframe", padding=(14, 12, 14, 14))
        type_box.pack(fill="x", pady=3)
        self.var_type = tk.StringVar(value="Passa-baixa")
        cb = ttk.Combobox(type_box, textvariable=self.var_type,
                          values=list(_TYPE_UI_TO_INT.keys()),
                          state="readonly", width=20)
        cb.pack(fill="x")
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_type_change())

        # ---- Especificacao
        f = ttk.LabelFrame(
            parent, text=" Especificação ",
            style="Card.TLabelframe", padding=(14, 12, 14, 14))
        f.pack(fill="x", pady=3)
        self.frm_spec = f

        self.var_fp1, self.var_fp2 = tk.StringVar(), tk.StringVar()
        self.var_fs1, self.var_fs2 = tk.StringVar(), tk.StringVar()
        self.var_dp, self.var_ds, self.var_Fs = (tk.StringVar(),
                                                 tk.StringVar(),
                                                 tk.StringVar())

        self._lbl_fp1 = ttk.Label(f, text="fp (Hz):", style="Card.TLabel")
        self._lbl_fp1.grid(row=0, column=0, sticky="w")
        self.var_fp1.set("200")
        e = ttk.Entry(f, textvariable=self.var_fp1, width=12)
        e.grid(row=0, column=1, sticky="w", padx=4)
        e.bind("<KeyRelease>", lambda ev: self._schedule_redesign())

        self._lbl_fp2 = ttk.Label(f, text="fp2 (Hz):", style="Card.TLabel")
        self.var_fp2.set("800")
        self._entry_fp2 = ttk.Entry(f, textvariable=self.var_fp2, width=12)
        self._entry_fp2.bind("<KeyRelease>",
                             lambda ev: self._schedule_redesign())

        self._lbl_fs1 = ttk.Label(f, text="fs rejeição (Hz):",
                                  style="Card.TLabel")
        self._lbl_fs1.grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.var_fs1.set("300")
        e = ttk.Entry(f, textvariable=self.var_fs1, width=12)
        e.grid(row=2, column=1, sticky="w", padx=4, pady=(4, 0))
        e.bind("<KeyRelease>", lambda ev: self._schedule_redesign())

        self._lbl_fs2 = ttk.Label(f, text="fs2 rejeição (Hz):",
                                  style="Card.TLabel")
        self.var_fs2.set("1000")
        self._entry_fs2 = ttk.Entry(f, textvariable=self.var_fs2, width=12)
        self._entry_fs2.bind("<KeyRelease>",
                             lambda ev: self._schedule_redesign())

        self._entry(f, 4, "δp ripple (dB):", self.var_dp, "1.0")
        self._entry(f, 5, "δs atenuação (dB):", self.var_ds, "40.0")
        self._entry(f, 6, "Fs amostragem (Hz):", self.var_Fs, "8000")
        _stretch_fields(f)

    def _build_actions(self, parent):
        actions = ttk.LabelFrame(
            parent, text=" Ações ",
            style="Card.TLabelframe", padding=(14, 12, 14, 14))
        actions.pack(fill="x", pady=3)

        _make_action_button(actions, "Recalcular projeto",
                            _BTN_DESIGN_BG, self._on_design).pack(
            fill="x", pady=2)
        self.btn_apply = _make_action_button(
            actions, "Aplicar à janela IIR", _BTN_APPLY_BG,
            self._on_apply_click)
        self.btn_apply.pack(fill="x", pady=2)
        self.btn_apply.configure(state="disabled")
        self.btn_save = _make_action_button(
            actions, "Salvar seções (.txt)", _BTN_SAVE_BG,
            self._on_save_click)
        self.btn_save.pack(fill="x", pady=2)
        self.btn_save.configure(state="disabled")

        # Resumo: o TextFilter / TextOrder do professor, mais o ponto fixo
        summary = ttk.LabelFrame(
            parent, text=" Resumo ",
            style="Card.TLabelframe", padding=(14, 12, 14, 14))
        summary.pack(fill="both", expand=True, pady=3)
        self.var_summary = tk.StringVar(value="(nenhum filtro projetado)")
        ttk.Label(summary, textvariable=self.var_summary,
                  style="Card.TLabel", wraplength=_WRAP, justify="left",
                  font=("TkFixedFont", 8)).pack(fill="x", anchor="w")

    def _build_plots(self, parent):
        self.fig = Figure(figsize=(7.6, 7.8), dpi=100)
        self.fig.patch.set_facecolor(theme.COLORS["bg"])
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.toolbar = PlotToolbar(self.canvas)

        # A figura do professor: pzmap + impz em cima, freqz embaixo.
        self.ax_pz  = self.fig.add_subplot(3, 2, 1)
        self.ax_imp = self.fig.add_subplot(3, 2, 2)
        self.ax_H   = self.fig.add_subplot(3, 1, 2)
        self.ax_ph  = self.fig.add_subplot(3, 1, 3, sharex=self.ax_H)
        theme.draw_empty_axes(self.ax_pz,  "Polos e zeros")
        theme.draw_empty_axes(self.ax_imp, "Resposta ao impulso h[n]")
        theme.draw_empty_axes(self.ax_H,   "Resposta em frequência |H(f)|")
        theme.draw_empty_axes(self.ax_ph,  "Espectro de fase ∠H(f)")
        self.fig.tight_layout()
        self.canvas.draw_idle()

    # ==================================================================
    # Eventos
    # ==================================================================

    def _on_type_change(self):
        kind = _TYPE_UI_TO_INT[self.var_type.get()]
        is_band = kind in ("bandpass", "bandstop")
        if is_band:
            self._lbl_fp1.configure(text="fp1 passante (Hz):")
            self._lbl_fs1.configure(text="fs1 rejeição (Hz):")
            self._lbl_fp2.grid(row=1, column=0, sticky="w", pady=(4, 0))
            self._entry_fp2.grid(row=1, column=1, sticky="ew", padx=4,
                                 pady=(4, 0))
            self._lbl_fs2.grid(row=3, column=0, sticky="w", pady=(4, 0))
            self._entry_fs2.grid(row=3, column=1, sticky="ew", padx=4,
                                 pady=(4, 0))
        else:
            self._lbl_fp1.configure(text="fp passante (Hz):")
            self._lbl_fs1.configure(text="fs rejeição (Hz):")
            self._lbl_fp2.grid_forget()
            self._entry_fp2.grid_forget()
            self._lbl_fs2.grid_forget()
            self._entry_fs2.grid_forget()
        self._schedule_redesign()

    def _schedule_redesign(self):
        if self._dirty_after_id is not None:
            try:
                self.after_cancel(self._dirty_after_id)
            except tk.TclError:
                pass
        self._dirty_after_id = self.after(250, self._on_design)

    def _fail(self, msg: str):
        self.status.set("[!] " + msg.splitlines()[0])
        self.var_summary.set(msg)
        self.btn_apply.configure(state="disabled")
        self.btn_save.configure(state="disabled")
        self.projeto = None
        self.sos_hw = None
        self.viabilidade = None

    # ---- projeto ----------------------------------------------------

    def _le_especificacao(self):
        """Devolve (aprox, fp, fs_borda, dp, ds, Fs) ou levanta ValueError
        com a mensagem para o usuario."""
        kind = _TYPE_UI_TO_INT[self.var_type.get()]
        try:
            Fs = float(self.var_Fs.get())
            dp = float(self.var_dp.get())
            ds = float(self.var_ds.get())
            fp1 = float(self.var_fp1.get())
            fs1 = float(self.var_fs1.get())
            if kind in ("bandpass", "bandstop"):
                fp = (fp1, float(self.var_fp2.get()))
                fs_borda = (fs1, float(self.var_fs2.get()))
            else:
                fp, fs_borda = fp1, fs1
        except ValueError:
            raise ValueError("Preencha todos os campos com números.")

        if Fs <= 0:
            raise ValueError("Fs precisa ser positiva.")
        for v in np.atleast_1d(fp).tolist() + np.atleast_1d(fs_borda).tolist():
            if not (0 < v < Fs / 2):
                raise ValueError(
                    "Toda borda precisa estar em (0, Fs/2) = (0, %g Hz)."
                    % (Fs / 2))
        if dp <= 0 or ds <= 0:
            raise ValueError("δp e δs precisam ser positivos (em dB).")
        if ds <= dp:
            raise ValueError("δs (atenuação) precisa ser maior que δp (ripple).")

        # A regra do professor (o tipo sai da posicao das bordas) continua
        # valendo dentro do design_iir; aqui so conferimos que as bordas
        # digitadas batem com o tipo escolhido, para o erro ser claro.
        if kind == "lowpass" and not fp < fs_borda:
            raise ValueError("Passa-baixa: fp tem que ser menor que fs.")
        if kind == "highpass" and not fp > fs_borda:
            raise ValueError("Passa-alta: fp tem que ser maior que fs.")
        if kind == "bandpass" and not (fs_borda[0] < fp[0] < fp[1] < fs_borda[1]):
            raise ValueError("Passa-banda: fs1 < fp1 < fp2 < fs2.")
        if kind == "bandstop" and not (fp[0] < fs_borda[0] < fs_borda[1] < fp[1]):
            raise ValueError("Rejeita-banda: fp1 < fs1 < fs2 < fp2.")
        return self.var_aprox.get(), fp, fs_borda, dp, ds, Fs

    def _on_design(self):
        self._dirty_after_id = None
        try:
            aprox, fp, fs_borda, dp, ds, Fs = self._le_especificacao()
        except ValueError as e:
            self._fail(str(e))
            return

        try:
            proj = iir.design_iir(aprox, fp, fs_borda, dp, ds, Fs)
        except iir.IIRSpecError as e:
            self._fail(str(e))
            return
        except Exception as e:  # numerico: raiz que nao converge, etc.
            self._fail("O projeto falhou: %s" % e)
            return

        if proj.n_secoes > cfg.IIR_SECOES_MAX:
            self._fail(
                "O filtro precisa de %d seções (ordem %d) e o hardware "
                "aceita %d. Relaxe a especificação: aumente a banda de "
                "transição ou reduza δs." % (proj.n_secoes, proj.ordem,
                                              cfg.IIR_SECOES_MAX))
            return

        sos_hw = iir.distribui_ganho(proj.sos)
        viab = iir.verifica_viabilidade(sos_hw, FRAC, TOTAL, simular=True)

        self.projeto = proj
        self.sos_hw = sos_hw
        self.viabilidade = viab
        self.description = proj.descricao()

        self._redraw(proj, sos_hw, viab)
        self._escreve_resumo(proj, sos_hw, viab)

        if viab["veredito"] == "recusar":
            self.btn_apply.configure(state="disabled")
            self.status.set("[!] Filtro projetado, mas NÃO cabe em Q15.16 "
                            "-- veja o resumo.")
        else:
            self.btn_apply.configure(state="normal")
            self.status.set("Filtro projetado: %s" % self.description)
        self.btn_save.configure(state="normal")

    def _escreve_resumo(self, proj, sos_hw, viab):
        coefs = iir.coeficientes_inteiros(sos_hw, FRAC, TOTAL)
        linhas = [
            "Tipo : %s %s" % (iir.APROX_LABEL_PT[proj.aprox],
                              iir.TIPO_LABEL_PT[proj.tipo]),
            "Ordem: N = %d  (%d seções de 2ª ordem)" % (proj.ordem,
                                                       proj.n_secoes),
            "Fs   : %g Hz" % proj.fs,
            "",
            "Ponto fixo Q15.16 (o que vai para a FPGA):",
            "  |polo| máx antes/depois: %.6f / %.6f"
            % (viab["raio_antes"], viab["raio_depois"]),
            "  deslocamento máx de polo: %.2e" % viab["deslocamento_max"],
        ]
        if viab.get("dead_band") is not None:
            linhas.append("  dead band medida: %.3g" % viab["dead_band"])
        rot = {"ok": "OK", "alerta": "ALERTA", "recusar": "RECUSADO"}
        linhas.append("  veredito: %s" % rot[viab["veredito"]])
        for m in viab["motivos"]:
            linhas.append("  - " + m)
        linhas.append("")
        linhas.append("Coeficientes inteiros (b0 b1 b2 a1 a2):")
        for j, c in enumerate(coefs):
            linhas.append("  s%-2d %d %d %d %d %d" % ((j,) + tuple(c)))
        self.var_summary.set("\n".join(linhas))

    # ---- graficos ---------------------------------------------------

    def _redraw(self, proj, sos_hw, viab):
        for ax in (self.ax_pz, self.ax_imp, self.ax_H, self.ax_ph):
            ax.clear()

        # -- polos e zeros: ideal (azul) e quantizado (vermelho) --------
        ax = self.ax_pz
        t = np.linspace(0, 2 * np.pi, 400)
        ax.plot(np.cos(t), np.sin(t), color="gray", lw=0.8)
        ax.axhline(0, color="gray", lw=0.5)
        ax.axvline(0, color="gray", lw=0.5)
        zs, ps, ps_q = [], [], []
        for sec, sec_q in zip(sos_hw, viab["sos_q"]):
            zs.extend(np.roots(sec[0:3]))
            ps.extend(np.roots(sec[3:6]))
            ps_q.extend(np.roots(sec_q[3:6]))
        zs, ps, ps_q = map(np.asarray, (zs, ps, ps_q))
        if zs.size:
            ax.plot(zs.real, zs.imag, "o", mfc="none", color=_COLOR_IDEAL,
                    ms=6, label="zeros")
        ax.plot(ps.real, ps.imag, "x", color=_COLOR_IDEAL, ms=7,
                label="polos")
        ax.plot(ps_q.real, ps_q.imag, "+", color=_COLOR_QUANT, ms=8,
                mew=1.5, label="polos Q15.16")
        lim = max(1.1, float(np.max(np.abs(np.r_[zs, ps, ps_q]))) * 1.05)
        ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
        ax.set_aspect("equal")
        ax.set_title("Polos e zeros (N = %d)" % proj.ordem, fontsize=9)
        ax.legend(fontsize=7, loc="upper left")
        ax.grid(True, alpha=0.3)

        # -- resposta ao impulso ---------------------------------------
        h = iir.resposta_impulso_sos(sos_hw, _IMP_MAX)
        pico = float(np.max(np.abs(h))) or 1.0
        acima = np.nonzero(np.abs(h) > 2e-3 * pico)[0]
        n_show = int(min(_IMP_MAX, max(_IMP_MIN, (acima[-1] + 8) if acima.size else _IMP_MIN)))
        ax = self.ax_imp
        n = np.arange(n_show)
        if n_show <= 128:
            ml, sl, bl = ax.stem(n, h[:n_show])
            ml.set_color(_COLOR_IMP); sl.set_color(_COLOR_IMP)
            bl.set_color("gray")
        else:
            ax.plot(n, h[:n_show], color=_COLOR_IMP, lw=1)
        ax.set_title("Resposta ao impulso h[n] (%d amostras)" % n_show,
                     fontsize=9)
        ax.set_xlabel("n", fontsize=8)
        ax.grid(True, alpha=0.3)

        # -- freqz: ideal e quantizada ---------------------------------
        f, H = iir.resposta_sos(proj.sos, n_freq=2048, fs=proj.fs)
        _, Hq = iir.resposta_sos(viab["sos_q"], n_freq=2048, fs=proj.fs)
        piso = 1e-8
        ax = self.ax_H
        ax.plot(f, 20 * np.log10(np.abs(H) + piso), color=_COLOR_IDEAL,
                lw=1.2, label="projeto")
        ax.plot(f, 20 * np.log10(np.abs(Hq) + piso), color=_COLOR_QUANT,
                lw=1, ls="--", label="quantizado Q15.16")
        self._marca_bandas(ax, proj)
        # Ate 60 dB abaixo da atenuacao pedida: mostra a banda de
        # rejeicao inteira sem achatar a passante.
        ax.set_ylim(-(proj.ds_db + 60), 5)
        ax.set_ylabel("|H(f)| (dB)", fontsize=8)
        ax.set_title("Resposta em frequência", fontsize=9)
        ax.legend(fontsize=7, loc="lower left")
        ax.grid(True, alpha=0.3)

        ax = self.ax_ph
        ax.plot(f, np.degrees(np.unwrap(np.angle(H))), color=_COLOR_IDEAL,
                lw=1)
        ax.set_ylabel("∠H(f) (graus)", fontsize=8)
        ax.set_xlabel("f (Hz)", fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.set_xlim(0, proj.fs / 2)

        self.fig.tight_layout()
        self.canvas.draw_idle()

    @staticmethod
    def _marca_bandas(ax, proj):
        """Linhas de especificacao: ripple na passante, atenuacao na rejeicao."""
        fp = np.atleast_1d(proj.fp).astype(float)
        fsb = np.atleast_1d(proj.fs_borda).astype(float)
        for v in fp:
            ax.axvline(v, color="green", lw=0.7, ls=":")
        for v in fsb:
            ax.axvline(v, color="red", lw=0.7, ls=":")
        ax.axhline(-proj.dp_db, color="green", lw=0.7, ls=":")
        ax.axhline(-proj.ds_db, color="red", lw=0.7, ls=":")

    # ---- acoes ------------------------------------------------------

    def _on_apply_click(self):
        if self.sos_hw is None or self.viabilidade is None:
            return
        if self.viabilidade["veredito"] == "alerta":
            ok = messagebox.askokcancel(
                "Atenção — ponto fixo",
                "\n\n".join(self.viabilidade["motivos"])
                + "\n\nAplicar mesmo assim?")
            if not ok:
                return
        try:
            self._on_apply(self.sos_hw.copy(), self.description,
                           float(self.projeto.fs))
        except Exception as e:
            messagebox.showerror("Erro ao aplicar", str(e))
            return
        self.status.set("Filtro aplicado à janela IIR.")

    def _on_save_click(self):
        if self.sos_hw is None:
            return
        kind_int = _TYPE_UI_TO_INT.get(self.var_type.get(), "filter")
        path = filedialog.asksaveasfilename(
            title="Salvar seções do filtro IIR",
            defaultextension=".txt",
            initialfile="iir_%s_%s.txt" % (self.projeto.aprox, kind_int),
            filetypes=[("Texto", "*.txt"), ("Seções", "*.sos"),
                       ("Todos", "*.*")],
        )
        if not path:
            return
        try:
            iir.salva_sos_txt(path, self.sos_hw, self.description,
                              float(self.projeto.fs))
        except OSError as e:
            messagebox.showerror("Erro ao salvar", str(e))
            return
        self.status.set("Seções salvas: %s" % os.path.basename(path))
        messagebox.showinfo("OK", "Salvo em:\n%s" % path)
