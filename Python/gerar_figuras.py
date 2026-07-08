"""gerar_figuras.py — gera as figuras vetoriais das telas do Morphe.

Roda o Morphe de verdade (mesmas classes, mesmos code paths), popula cada
janela com dados e exporta tudo para SVG vetorial via `morphe_export`.
Nenhuma captura de tela é envolvida.

Dois modos de origem dos dados
------------------------------
  --host 192.168.1.10   Fala com o servidor real no DE1-SoC. Os números
                        nos gráficos vêm da FPGA. **Use este para o
                        artigo e para a defesa.**

  --emular              Emula o servidor no nível do protocolo: monta e
                        decodifica os mesmos pacotes de 20 bytes, aplica
                        a MESMA quantização de ponto fixo do hardware
                        (Q15.16 na conv/FIR, Q15.8 na entrada da FFT) e
                        devolve a resposta. Serve para iterar no layout
                        sem a placa na mesa. NÃO é dado de hardware — as
                        figuras saem com sufixo `-emulado` justamente
                        para você não confundir na hora de escrever a
                        legenda.

Uso
---
    python gerar_figuras.py --emular
    python gerar_figuras.py --host 192.168.1.10
    python gerar_figuras.py --host 192.168.1.10 --so fft,conv

Saída: figuras/*.svg. Para o LaTeX:

    for f in figuras/*.svg; do rsvg-convert -f pdf -o "${f%.svg}.pdf" "$f"; done
    # ou: inkscape --export-type=pdf figuras/*.svg
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
import time
import tkinter as tk

import numpy as np

import dsp_core as dsp
import morphe_export as mex
import morphe_protocol as proto
from morphe_protocol import (
    OP_CONV, OP_FFT, OP_FIR, DTYPE_INT32, DTYPE_FLOAT32, Response,
)

FIG_DIR = "figuras"


# ══════════════════════════════════════════════════════════════════
# Emulador do servidor da DE1-SoC (nível de protocolo)
# ══════════════════════════════════════════════════════════════════

class EmulatedFpga:
    """Responde aos mesmos pacotes que o servidor C do HPS.

    Reproduz a aritmética de ponto fixo do hardware — não é NumPy em
    float64 disfarçado:

      * conv/FIR: operandos chegam em Q15.16 (int32). O produto vai para
        int64 (Q31.32) e volta a Q15.16 com um shift de 16 bits — é o que
        o acumulador da FSM em Verilog faz.
      * FFT: a entrada chega já saturada e quantizada em Q15.8 (24 bits
        úteis). Decodificamos, transformamos e devolvemos float32 — o
        erro de quantização de entrada, que domina o SNR ≈ 35 dB medido,
        aparece igual.

    O que NÃO é reproduzido: o arredondamento interno do block floating
    point do FFT II. Por isso o modo `--host` continua sendo o correto
    para números publicados.
    """

    def request(self, payload: bytes) -> Response:
        _magic, _ver, op, dcode, _st, n1, n2 = struct.unpack(
            ">IHHHHII", payload[:20])
        body = payload[20:]

        if op in (OP_CONV, OP_FIR):
            be = ">i4" if dcode == DTYPE_INT32 else ">f4"
            x = np.frombuffer(body, dtype=be, count=n1).astype(np.int64)
            h = np.frombuffer(body, dtype=be, count=n2,
                              offset=4 * n1).astype(np.int64)
            # Q15.16 × Q15.16 = Q31.32 (int64) → volta a Q15.16
            acc = np.convolve(x, h)
            y_q = np.right_shift(acc, 16).astype(np.int32)
            y_q = y_q[:dsp.MAX_CONV_INPUT_SIZE * 2 - 1]
            return Response(opcode=op, dtype_code=DTYPE_INT32, status=0,
                            n_out=len(y_q),
                            payload=y_q.astype(">i4").tobytes())

        if op == OP_FFT:
            enc = np.frombuffer(body, dtype=">i4", count=n1).astype(np.int64)
            xf = dsp.fft_q1508_decode(enc)          # desfaz o Q15.8
            X = np.fft.fft(xf, n=dsp.MAX_FFT_INPUT_SIZE)
            inter = np.empty(2 * len(X), dtype=">f4")
            inter[0::2] = X.real
            inter[1::2] = X.imag
            return Response(opcode=OP_FFT, dtype_code=DTYPE_FLOAT32,
                            status=0, n_out=len(X),
                            payload=inter.tobytes())

        raise RuntimeError(f"opcode não emulado: {op}")


# ══════════════════════════════════════════════════════════════════
# Infra
# ══════════════════════════════════════════════════════════════════

def instalar_backend(app, backend):
    """Faz `master.tcp_panel.make_client()` devolver o backend escolhido.

    Todas as janelas passam por esse único ponto, então trocar aqui basta.
    """
    app.tcp_panel.make_client = lambda: backend


def pump(win, pronto, timeout=30.0):
    """Roda o loop de eventos do Tk até a condição valer.

    As janelas fazem o request em uma thread e voltam para a thread Tk via
    `after(0, ...)`. Sem mainloop, precisamos bombear os eventos na mão.
    """
    t0 = time.time()
    while not pronto() and time.time() - t0 < timeout:
        win.update()
        time.sleep(0.02)
    win.update_idletasks()
    win.update()
    if not pronto():
        raise TimeoutError("a FPGA não respondeu no tempo esperado")


# Opções passadas a export_window; preenchido em main() a partir dos flags.
EXPORT_KW: dict = {}


def salvar(win, nome, sufixo):
    path = os.path.join(FIG_DIR, f"{nome}{sufixo}.svg")
    mex.export_window(win, path, **EXPORT_KW)
    print(f"  ✓ {path}")
    return path


# ══════════════════════════════════════════════════════════════════
# As telas
# ══════════════════════════════════════════════════════════════════

def fig_hub(app, sufixo):
    """Janela principal (hub). Não precisa de dados."""
    app.update_idletasks()
    return salvar(app, "morphe-hub", sufixo)


def fig_gerador(app, sufixo):
    from signal_generator_window import SignalGeneratorWindow
    from dsp_core import gen_sinusoid

    w = SignalGeneratorWindow(app)
    w.update()
    w.gen_panel.signal_type.set("Senóide")
    w.gen_panel._refresh_params()
    w.gen_panel.var_N.set("64")
    w.gen_panel.param_vars["A"].set("1.0")
    w.gen_panel.param_vars["f"].set("5.0")
    w.gen_panel.param_vars["fs"].set("64.0")
    w.gen_panel._on_gen_click()
    w.update()
    return salvar(w, "morphe-gerador", sufixo), w


def fig_conv(app, sufixo):
    from conv_window import ConvolutionWindow

    w = ConvolutionWindow(app)
    w.update()
    # x[n]: senóide de 64 amostras
    w.x_panel.signal_type.set("Senóide")
    w.x_panel._refresh_params()
    w.x_panel.var_N.set("64")
    w.x_panel.param_vars["f"].set("4.0")
    w.x_panel.param_vars["fs"].set("64.0")
    w.x_panel._on_gen_click()
    # h[n]: pulso retangular (média móvel)
    w.h_panel.signal_type.set("Retangular")
    w.h_panel._refresh_params()
    w.h_panel.var_N.set("16")
    w.h_panel.param_vars["A"].set("1.0")
    w.h_panel.param_vars["n_start"].set("0")
    w.h_panel.param_vars["width"].set("8")
    w.h_panel._on_gen_click()
    w.update()

    w._on_convolve()                       # ← caminho real: TCP + FPGA
    pump(w, lambda: w.y_signal is not None)
    return salvar(w, "morphe-convolucao", sufixo), w


def fig_fft(app, sufixo):
    from fft_window import FFTWindow

    w = FFTWindow(app)
    w.update()
    w.x_panel.signal_type.set("Senóide")
    w.x_panel._refresh_params()
    w.x_panel.var_N.set("256")
    w.x_panel.param_vars["A"].set("1.0")
    w.x_panel.param_vars["f"].set("50.0")
    w.x_panel.param_vars["fs"].set("1000.0")
    w.x_panel._on_gen_click()
    w.update()

    w._on_fft()                            # ← caminho real
    pump(w, lambda: w.X_complex is not None)
    return salvar(w, "morphe-fft", sufixo), w


def fig_fir(app, sufixo):
    from fir_window import FIRWindow
    import fir_design

    w = FIRWindow(app)
    w.update()
    w.builder._on_update_click()           # gera x[n] com os defaults
    w.update()

    h = fir_design.design_lowpass(31, fc=80.0, fs=1000.0, window="hamming")
    descr = fir_design.describe_filter("lowpass", 31, 1000.0, 80.0,
                                       window="hamming")
    w.loader.set_coefficients(h, descr, fs=1000.0)
    w.update()

    if w.x_input is not None and w.h_coefs is not None:
        w._on_run()                        # ← caminho real
        pump(w, lambda: w.y_output is not None)
    return salvar(w, "morphe-fir", sufixo), w


def fig_designer(app, sufixo):
    """Projetista de FIR — 100% local, não toca na FPGA."""
    from fir_designer_window import FIRDesignerWindow

    w = FIRDesignerWindow(app, on_apply=lambda h, d: None)
    w.update()
    w._on_design()
    w.update()
    return salvar(w, "morphe-fir-designer", sufixo), w


def fig_comparador(app, sufixo, conv_win):
    """Comparador — carrega um bundle .mrph com o resultado da FPGA."""
    from comparator_window import ComparatorWindow

    if conv_win is None or conv_win.y_signal is None:
        print("  · comparador pulado (precisa da convolução)")
        return None, None

    bundle = os.path.join(FIG_DIR, "_conv_para_comparar.mrph")
    dsp.save_mrph_bundle(bundle, title="Morphe convolucao", sections=[
        {"name": "x", "kind": "real", "n": conv_win.x_sig.n,
         "data": conv_win.x_sig.x, "fs": conv_win.x_sig.fs,
         "description": f"x[n] - {conv_win.x_sig.description}",
         "dtype_out": "float32"},
        {"name": "h", "kind": "real", "n": conv_win.h_sig.n,
         "data": conv_win.h_sig.x, "fs": conv_win.h_sig.fs,
         "description": f"h[n] - {conv_win.h_sig.description}",
         "dtype_out": "float32"},
        {"name": "y", "kind": "real", "n": conv_win.y_signal.n,
         "data": conv_win.y_signal.x, "fs": conv_win.y_signal.fs,
         "description": f"y[n] - {conv_win.y_signal.description}",
         "dtype_out": "float32"},
    ])

    w = ComparatorWindow(app)
    w.update()
    w._load_path(bundle)
    w.update()
    return salvar(w, "morphe-comparador", sufixo), w


def fig_discovery(app, sufixo):
    """Busca de servidores na LAN. Os resultados são ilustrativos — deixe
    isso claro na legenda se a figura entrar no artigo."""
    from discovery_window import DiscoveryWindow

    w = DiscoveryWindow(app, on_pick=lambda ip, p: None)
    w.update()
    w.tree.insert("", "end", values=(
        "172.16.101.42", "de1soc-morphe", "1", "1024", "128", "1873"))
    w.var_status.set("Busca concluída — 1 servidor encontrado.")
    w.progress["maximum"] = 762
    w.progress["value"] = 762
    w.update()
    return salvar(w, "morphe-discovery", sufixo), w


# ══════════════════════════════════════════════════════════════════
# Modo resultados: carrega bundles .mrph REAIS no comparador
# ══════════════════════════════════════════════════════════════════

def achar_toolbars(win):
    """Widgets da toolbar do Matplotlib, para passar a `skip=` do
    exportador. Numa figura de artigo os ícones Home/Zoom/Save são ruído."""
    from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk
    achados = []

    def walk(w):
        if isinstance(w, NavigationToolbar2Tk):
            achados.append(w)
            return
        for c in w.winfo_children():
            walk(c)
    walk(win)
    return achados


def exportar_mrph(app, caminho, *, fft_mode="magnitude", sem_toolbar=False):
    """Abre um bundle .mrph no comparador e exporta a figura resultante.

    É o caminho correto para a seção de resultados: o comparador NÃO fala
    com a FPGA — ele lê o resultado que já foi salvo em disco (de uma
    rodada real) e recomputa a referência NumPy sobre o mesmo x[n]. O SNR,
    o erro RMS e o erro máximo que aparecem na figura são exatamente os
    números que vão para o artigo.
    """
    from comparator_window import ComparatorWindow

    if not os.path.isfile(caminho):
        print(f"  ✗ arquivo não encontrado: {caminho}")
        return None

    w = ComparatorWindow(app)
    w.update()
    w._load_path(caminho)                  # ← recomputa NumPy + métricas + plots
    w.update()
    w.update_idletasks()

    if w.bundle is None:                    # _load_path engoliu um erro em dialog
        print(f"  ✗ não foi possível interpretar o bundle: {caminho}")
        try:
            w.destroy()
        except tk.TclError:
            pass
        return None

    # FFT: escolhe o que comparar (magnitude é o default do artigo)
    if w.bundle_type == "fft" and fft_mode != "magnitude":
        w.var_fft_mode.set(fft_mode)
        w._on_fft_mode_change()
        w.update()

    skip = achar_toolbars(w) if sem_toolbar else ()

    # nome de saída: tipo do bundle + nome do arquivo, sem ambiguidade
    stem = os.path.splitext(os.path.basename(caminho))[0]
    nome = f"resultado-{w.bundle_type}-{stem}"

    m = w.metrics or {}
    snr = m.get("snr_db", float("nan"))
    snr_txt = ("SNR=∞" if snr == float("inf")
               else f"SNR={snr:.2f} dB" if snr == snr  # not NaN
               else "SNR=n/a")
    path = os.path.join(FIG_DIR, f"{nome}.svg")
    mex.export_window(w, path, skip=skip, **EXPORT_KW)
    print(f"  ✓ {path}   ({w.bundle_type}, {snr_txt})")

    try:
        w.destroy()
    except tk.TclError:
        pass
    return path


# ══════════════════════════════════════════════════════════════════

TELAS = ("hub", "gerador", "conv", "fft", "fir", "designer",
         "comparador", "discovery")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", help="IP do servidor Morphe no DE1-SoC")
    ap.add_argument("--emular", action="store_true",
                    help="emula a FPGA no nível do protocolo (sem placa)")
    ap.add_argument("--mrph", nargs="+", metavar="ARQUIVO.mrph",
                    help="gera a figura do comparador a partir de bundles "
                         ".mrph REAIS (resultados salvos da FPGA). Não "
                         "precisa de --host nem --emular.")
    ap.add_argument("--fft-mode", default="magnitude",
                    choices=("magnitude", "real", "imag"),
                    help="o que comparar em bundles de FFT (default: "
                         "magnitude)")
    ap.add_argument("--sem-toolbar", action="store_true",
                    help="omite a barra do Matplotlib (recomendado p/ artigo)")
    ap.add_argument("--porta", type=int, default=5000)
    ap.add_argument("--so", default=",".join(TELAS),
                    help=f"telas a gerar: {','.join(TELAS)}")
    ap.add_argument("--fundo-branco", action="store_true",
                    help="força fundo branco nos gráficos (impressão)")
    args = ap.parse_args()

    os.makedirs(FIG_DIR, exist_ok=True)
    if args.fundo_branco:
        EXPORT_KW["plot_facecolor"] = "white"

    # ── Modo resultados: só o comparador, a partir de arquivos reais ──
    if args.mrph:
        from morphe_app import MorpheMainWindow
        app = MorpheMainWindow()
        # o comparador não usa o backend, mas make_client é chamado em
        # nenhum caminho aqui; ainda assim deixamos um stub inofensivo.
        instalar_backend(app, EmulatedFpga())

        def rodar_mrph():
            print(f"\n  Comparador × NumPy a partir de {len(args.mrph)} "
                  f"bundle(s) real(is).\n")
            for caminho in args.mrph:
                print(f"[{os.path.basename(caminho)}]")
                try:
                    exportar_mrph(app, caminho, fft_mode=args.fft_mode,
                                  sem_toolbar=args.sem_toolbar)
                except Exception as e:
                    print(f"  ✗ falhou: {type(e).__name__}: {e}")
            app.quit()

        app.after(200, rodar_mrph)
        app.mainloop()
        app.destroy()
        print(f"\nFiguras em {os.path.abspath(FIG_DIR)}/")
        return

    # ── Modo telas: precisa de uma fonte de dados ──
    if not args.host and not args.emular:
        ap.error("informe --host <ip>, --emular, ou --mrph <arquivos>")

    quais = [s.strip() for s in args.so.split(",") if s.strip()]

    if args.emular:
        backend = EmulatedFpga()
        sufixo = "-emulado"
        print("\n  ATENÇÃO: modo emulação. Os gráficos NÃO vêm da FPGA.")
        print("  Para figuras do artigo, use --host <ip do DE1-SoC>.\n")
    else:
        backend = proto.TcpClient(args.host, args.porta, timeout=15.0)
        sufixo = ""
        print(f"\n  Dados vindos da FPGA em {args.host}:{args.porta}\n")

    from morphe_app import MorpheMainWindow
    app = MorpheMainWindow()          # fica mapeada: o Tk precisa medir tudo
    instalar_backend(app, backend)

    def rodar():
        # Executa DENTRO do mainloop, e não antes dele: as janelas fazem o
        # request numa thread worker que ainda toca variáveis Tk (por ex.
        # `dtype_var.get()` na convolução). O Tkinter só aceita chamadas de
        # outras threads enquanto a thread principal está despachando
        # eventos — fora do mainloop isso vira "main thread is not in main
        # loop".
        conv_win = None
        for tela in quais:
            print(f"[{tela}]")
            try:
                if tela == "hub":
                    fig_hub(app, sufixo)
                elif tela == "gerador":
                    fig_gerador(app, sufixo)
                elif tela == "conv":
                    _, conv_win = fig_conv(app, sufixo)
                elif tela == "fft":
                    fig_fft(app, sufixo)
                elif tela == "fir":
                    fig_fir(app, sufixo)
                elif tela == "designer":
                    fig_designer(app, sufixo)
                elif tela == "comparador":
                    if conv_win is None:
                        _, conv_win = fig_conv(app, sufixo)
                    fig_comparador(app, sufixo, conv_win)
                elif tela == "discovery":
                    fig_discovery(app, sufixo)
                else:
                    print(f"  ! tela desconhecida: {tela}")
            except Exception as e:
                print(f"  ✗ falhou: {type(e).__name__}: {e}")
        app.quit()

    app.after(200, rodar)
    app.mainloop()
    app.destroy()
    print(f"\nFiguras em {os.path.abspath(FIG_DIR)}/")


if __name__ == "__main__":
    main()
