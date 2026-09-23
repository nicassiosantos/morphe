"""
sinal_arquivo.py -- carregar um sinal qualquer de arquivo como dsp.Signal.

Ate 23/09/2026 a plataforma so trabalhava com os cinco sinais gerados do
signal_panel (degrau, impulso, senoide, exponencial, retangular). Ler de
arquivo abre sequencias arbitrarias (exercicios do livro com valores dados,
sinais medidos, audio) e e por onde vai entrar o sinal capturado pelo ADC.

Formatos:
  .csv / .txt  uma coluna (as amostras) ou duas (indice ou tempo, amostra).
               Separador: virgula, ponto e virgula, tabulacao ou espacos.
               Com ponto e virgula, aceita virgula decimal (planilha em pt-BR).
               Linhas que nao sao numeros (cabecalho) sao ignoradas.
               Duas colunas com tempo nao inteiro dao fs = 1 / (passo medio).
  .npy         vetor do NumPy; matriz de duas colunas como no .csv.
  .wav         audio; fs vem do arquivo, e so o primeiro canal e usado.
               Inteiros sao levados a [-1, 1).
"""
from __future__ import annotations

import os
import re

import numpy as np

import dsp_core as dsp

EXTENSOES = (".csv", ".txt", ".npy", ".wav")
TIPOS_DIALOGO = [("Sinais", "*.csv *.txt *.npy *.wav"),
                 ("Texto (.csv, .txt)", "*.csv *.txt"),
                 ("NumPy (.npy)", "*.npy"),
                 ("Audio (.wav)", "*.wav"),
                 ("Todos", "*.*")]


def carregar_sinal(caminho: str) -> dsp.Signal:
    """Le `caminho` e devolve o dsp.Signal, com n comecando em 0 (ou no
    indice lido, quando a primeira coluna e um indice inteiro)."""
    ext = os.path.splitext(caminho)[1].lower()
    if ext in (".csv", ".txt"):
        n, x, fs = _ler_texto(caminho)
    elif ext == ".npy":
        n, x, fs = _duas_colunas(np.load(caminho, allow_pickle=False))
    elif ext == ".wav":
        n, x, fs = _ler_wav(caminho)
    else:
        raise ValueError(f"formato nao suportado: '{ext}'. "
                         f"Use {', '.join(EXTENSOES)}.")
    if x.size == 0:
        raise ValueError(f"{os.path.basename(caminho)}: nenhuma amostra lida")
    if not np.all(np.isfinite(x)):
        raise ValueError(f"{os.path.basename(caminho)}: ha valores NaN ou infinitos")
    desc = f"{os.path.basename(caminho)} ({x.size} amostras"
    desc += f", fs={fs:g} Hz)" if fs != 1.0 else ")"
    return dsp.Signal(n=n, x=x, fs=fs, description=desc)


def _duas_colunas(a: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Vetor -> amostras. Duas colunas -> (indice ou tempo, amostras)."""
    a = np.asarray(a, dtype=np.float64)
    if a.ndim == 1:
        return np.arange(a.size, dtype=np.int64), a, 1.0
    if a.ndim == 2 and 2 in a.shape:
        if a.shape[1] != 2:
            a = a.T
        eixo, x = a[:, 0], a[:, 1]
        if x.size >= 2 and np.all(eixo == np.round(eixo)) and np.all(np.diff(eixo) == 1):
            return eixo.astype(np.int64), x, 1.0          # indice n
        passo = np.diff(eixo)
        if x.size >= 2 and np.all(passo > 0):
            fs = 1.0 / float(np.mean(passo))                # tempo em segundos
            if np.max(np.abs(passo - np.mean(passo))) > 1e-3 * np.mean(passo):
                raise ValueError("a coluna de tempo nao tem passo constante")
            return np.arange(x.size, dtype=np.int64), x, fs
        raise ValueError("a primeira coluna nao e indice nem tempo crescente")
    if a.ndim == 2 and 1 in a.shape:
        return _duas_colunas(a.ravel())
    raise ValueError(f"esperado vetor ou duas colunas; veio forma {a.shape}")


def _ler_texto(caminho: str) -> tuple[np.ndarray, np.ndarray, float]:
    with open(caminho, encoding="utf-8-sig", errors="replace") as f:
        linhas = [l.strip() for l in f if l.strip()]
    ponto_virgula = any(";" in l for l in linhas)
    linhas_num = []
    for l in linhas:
        if ponto_virgula:
            campos = [c.strip().replace(",", ".") for c in l.split(";")]
        else:
            campos = [c for c in re.split(r"[,\t ]+", l) if c]
        try:
            linhas_num.append([float(c) for c in campos if c != ""])
        except ValueError:
            continue                                         # cabecalho
    if not linhas_num:
        raise ValueError(f"{os.path.basename(caminho)}: nenhuma linha numerica")
    larguras = {len(l) for l in linhas_num}
    if larguras == {1}:
        return _duas_colunas(np.array([l[0] for l in linhas_num]))
    if larguras == {2}:
        return _duas_colunas(np.array(linhas_num))
    raise ValueError(f"{os.path.basename(caminho)}: esperado 1 ou 2 colunas "
                     f"em todas as linhas; achei {sorted(larguras)}")


def _ler_wav(caminho: str) -> tuple[np.ndarray, np.ndarray, float]:
    from scipy.io import wavfile
    fs, dados = wavfile.read(caminho)
    if dados.ndim == 2:
        dados = dados[:, 0]
    if dados.dtype == np.uint8:
        x = (dados.astype(np.float64) - 128.0) / 128.0
    elif np.issubdtype(dados.dtype, np.integer):
        x = dados.astype(np.float64) / float(-np.iinfo(dados.dtype).min)
    else:
        x = dados.astype(np.float64)
    return np.arange(x.size, dtype=np.int64), x, float(fs)
