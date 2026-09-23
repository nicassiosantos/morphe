"""Poe Python/ no sys.path, para as ferramentas importarem os modulos do cliente.

As ferramentas de teste e de desenvolvimento moram em Python/ferramentas/
desde 23/09/2026, separadas do aplicativo; os modulos que elas usam
(morphe_protocol, dsp_core, iir_design...) continuam em Python/. Cada
ferramenta faz `import _caminho` antes de importa-los -- funciona porque a
pasta do script rodado ja esta no sys.path.
"""
import os
import sys

_PYTHON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PYTHON not in sys.path:
    sys.path.insert(0, _PYTHON)
