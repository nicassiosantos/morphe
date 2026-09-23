#!/usr/bin/env python3
"""compara_professor_fpga.py -- o dsp_iir_filter.m do professor contra a FPGA.

Responde a pergunta "a placa da o mesmo resultado que o MATLAB do
professor?" com numeros, e separa o que e custo do ponto fixo do que e
limitacao do MATLAB.

Roda o dsp_iir_filter.m (DSPFinal, Prof. Sanca) no MATLAB com uma
especificacao, pega o polinomio [numz, denz] e o filter() em dupla
precisao, converte o polinomio em secoes de 2a ordem (tf2sos), manda AS
SECOES DELE para a FPGA e compara:

  1. FPGA x modelo em ponto fixo (filtra_sos_fixo)   -> esperado: 0
  2. FPGA x cascata de biquads em dupla precisao      -> custo do Q15.16
  3. FPGA x filter(numz, denz) do MATLAB              -> o resultado dele
  4. forma direta em Python x filter() do MATLAB, com o MESMO polinomio
     -> mede o condicionamento do polinomio: se duas implementacoes em
        double nao concordam, a diferenca em 3 nao e da FPGA

Medido em 15/09/2026 (Butterworth passa-baixa 200/300 Hz, 1/40 dB, 8 kHz,
ordem 13): 1 = 0; 2 = 1,7e-3; 3 = 2,1e-2; 4 = 3,0e-2. A FPGA em cascata
fica mais perto da resposta certa do que o filter() do MATLAB com o
polinomio de ordem 13 -- e o argumento do iir_cascade.v, medido.

Precisa do MATLAB com o Signal Processing Toolbox (buttord, tf2sos) e da
pasta DSPFinal do professor, que nao esta neste repositorio.

Uso:
    python compara_professor_fpga.py <host> --dspfinal <pasta> [--matlab <exe>]
        [--fp 200 --fs 300 --dp 1 --ds 40 --Fs 8000 --classe Bw]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

import numpy as np

import _caminho  # noqa: F401 -- poe Python/ no sys.path
import iir_design as iir
import morphe_config as cfg
from morphe_protocol import TcpClient, build_iir_request, decode_iir_response

ESC = float(1 << cfg.IIR_FRAC_BITS)

SCRIPT_M = r"""
S = getenv('MORPHE_S');
addpath(getenv('MORPHE_DSPFINAL'));
[numz, denz, texto, N] = dsp_iir_filter(%(fp)s, %(fs)s, %(dp)s, %(ds)s, %(Fs)s, '%(classe)s');
x = load(fullfile(S, 'x.txt'));
y = filter(numz, denz, x);
[sos, g] = tf2sos(numz, denz);
sos(1,1:3) = sos(1,1:3) * g;
writematrix(numz(:).', fullfile(S, 'prof_num.txt'), 'Delimiter', ' ');
writematrix(denz(:).', fullfile(S, 'prof_den.txt'), 'Delimiter', ' ');
writematrix(sos, fullfile(S, 'prof_sos.txt'), 'Delimiter', ' ');
writematrix(y(:), fullfile(S, 'prof_y.txt'));
fprintf('MATLAB: %%s, N = %%d\n', texto, N);
"""


def q(v):
    return np.floor(np.asarray(v, dtype=np.float64) * ESC + 0.5).astype(np.int64)


def cascata_double(x, sos):
    """Mora no iir_design desde 17/09/2026, para o comparador da
    interface usar a MESMA referencia que este script."""
    return iir.filtra_sos_double(x, sos)


def direta_double(x, b, a):
    """Forma direta I com o polinomio inteiro, em double -- o que o
    filter() do MATLAB faz (ele usa a DF-II transposta; a diferenca entre
    as duas, em double, e justamente a medida do condicionamento)."""
    y = np.zeros(len(x))
    for k in range(len(x)):
        acc = 0.0
        for i in range(len(b)):
            if k - i >= 0:
                acc += b[i] * x[k - i]
        for i in range(1, len(a)):
            if k - i >= 0:
                acc -= a[i] * y[k - i]
        y[k] = acc / a[0]
    return y


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("--porta", type=int, default=cfg.DEFAULT_PORT)
    ap.add_argument("--dspfinal", required=True, help="pasta com dsp_iir_filter.m")
    ap.add_argument("--matlab", default="matlab", help="executavel do MATLAB")
    ap.add_argument("--fp", default="200"); ap.add_argument("--fs", default="300")
    ap.add_argument("--dp", default="1");   ap.add_argument("--ds", default="40")
    ap.add_argument("--Fs", default="8000"); ap.add_argument("--classe", default="Bw")
    ap.add_argument("--f-passa", type=float, default=100.0, help="tom de teste na passante (Hz)")
    ap.add_argument("--f-rejeita", type=float, default=1000.0, help="tom de teste na rejeicao (Hz)")
    a = ap.parse_args()

    S = tempfile.mkdtemp(prefix="morphe_prof_")
    Fs = float(a.Fs)
    n = np.arange(cfg.IIR_N_MAX)
    x = 0.5 * np.sin(2 * np.pi * a.f_passa * n / Fs) + 0.5 * np.sin(2 * np.pi * a.f_rejeita * n / Fs)
    np.savetxt(os.path.join(S, "x.txt"), x, fmt="%.15g")

    script = os.path.join(S, "roda_professor.m")
    with open(script, "w", encoding="ascii") as f:
        f.write(SCRIPT_M % dict(fp=a.fp, fs=a.fs, dp=a.dp, ds=a.ds, Fs=a.Fs, classe=a.classe))
    env = dict(os.environ, MORPHE_S=S, MORPHE_DSPFINAL=a.dspfinal)
    print("rodando o dsp_iir_filter.m no MATLAB...")
    r = subprocess.run([a.matlab, "-batch", "run('%s')" % script.replace("\\", "/")],
                       env=env, capture_output=True, text=True)
    print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-400:])
    if r.returncode != 0 or not os.path.exists(os.path.join(S, "prof_y.txt")):
        print("MATLAB falhou:\n", r.stderr[-1500:])
        return 1

    y_prof = np.loadtxt(os.path.join(S, "prof_y.txt"))
    num = np.loadtxt(os.path.join(S, "prof_num.txt")); den = np.loadtxt(os.path.join(S, "prof_den.txt"))
    sos = iir.distribui_ganho(np.atleast_2d(np.loadtxt(os.path.join(S, "prof_sos.txt"))))
    ordem = int(np.sum(np.abs(sos[:, 4:6]) > 0))
    print("secoes: %d (ordem %d); |p| max: polinomio %.6f, cascata %.6f"
          % (sos.shape[0], ordem, np.max(np.abs(np.roots(den))),
             max(np.max(np.abs(np.roots(s[3:6]))) for s in sos)))
    viab = iir.verifica_viabilidade(sos, cfg.IIR_FRAC_BITS, 32, simular=False)
    print("viabilidade em Q15.16:", viab["veredito"])
    if viab["veredito"] == "recusar":
        for m in viab["motivos"]:
            print("  -", m)
        return 1

    coefs = iir.coeficientes_inteiros(sos, cfg.IIR_FRAC_BITS, 32)
    cli = TcpClient(a.host, a.porta, timeout=15.0)
    y_q, sat = decode_iir_response(cli.request(build_iir_request(q(x), coefs)))
    y_fpga = y_q / ESC
    y_modelo = q(iir.filtra_sos_fixo(x, sos, cfg.IIR_FRAC_BITS, 32))
    y_casc = cascata_double(x, sos)
    y_dir = direta_double(x, num, den)
    pico = float(np.max(np.abs(y_prof)))

    def linha(rotulo, e):
        m = float(np.max(np.abs(e)))
        print("  %-58s %.3e  (%.2f%% do pico)" % (rotulo, m, 100 * m / pico))

    print()
    print("erro maximo absoluto (pico de |y| = %.4f):" % pico)
    print("  %-58s %d amostras diferentes%s" % ("1. FPGA x modelo em ponto fixo", int(np.sum(y_q != y_modelo)),
                                              " (SATUROU)" if sat else ""))
    linha("2. FPGA x cascata de biquads em double", y_fpga - y_casc)
    linha("3. FPGA x filter(numz,denz) do MATLAB", y_fpga - y_prof)
    linha("4. forma direta em Python x filter() do MATLAB (mesmo polinomio)", y_dir - y_prof)
    linha("   cascata em double x filter() do MATLAB", y_casc - y_prof)

    w = 2 * np.pi * a.f_passa / Fs
    zpol = np.exp(-1j * w * np.arange(len(num)))
    H_pol = abs(np.dot(num, zpol) / np.dot(den, zpol))
    H_sos = abs(np.prod([(s[0] + s[1] * np.exp(-1j * w) + s[2] * np.exp(-2j * w))
                         / (s[3] + s[4] * np.exp(-1j * w) + s[5] * np.exp(-2j * w)) for s in sos]))
    print()
    print("|H(%g Hz)|: pelo polinomio %.5f | pela cascata %.5f" % (a.f_passa, H_pol, H_sos))
    for rot, s in (("projeto do professor", sos),):
        f, H = iir.resposta_sos(s, 8192, Fs)
        print("%s: em fp=%s Hz %.2f dB (pedido >= -%s) | em fs=%s Hz %.2f dB (pedido <= -%s)"
              % (rot, a.fp, 20 * np.log10(abs(H[np.searchsorted(f, float(a.fp))])), a.dp,
                 a.fs, 20 * np.log10(abs(H[np.searchsorted(f, float(a.fs))])), a.ds))
    print("(arquivos em %s)" % S)
    return 0


if __name__ == "__main__":
    sys.exit(main())
