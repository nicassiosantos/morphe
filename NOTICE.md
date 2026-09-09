# Origem e créditos

Este repositório é um **fork** de **Morphe**, de **Carlos Valadão**
(https://github.com/CarlosValadao/morphe), desenvolvido como Trabalho de
Conclusão de Curso: *"Implementação de Ferramentas de Computação Numérica para
o Processamento Digital de Sinais em Hardware Reconfigurável"* (UEFS).

Todo o projeto original — a arquitetura, o RTL de `conv1d` e do FIR, a
integração do núcleo de FFT, o servidor TCP em C e o cliente gráfico em Python
— é de autoria de Carlos Valadão e permanece sob a **GNU General Public
License v3**, preservada integralmente em `LICENSE`.

O histórico de commits deste fork começa nos commits originais do autor; nada
foi reescrito, refeito ou reatribuído.

## Modificações

Modificado a partir de 2026-09-01 por **Antonio Nicassio Santos Lima**, durante
estágio curricular no Laboratório de DSP (DTEC/UEFS), sob supervisão do
**Prof. Armando S. Sanca**.

Objetivo do fork: tornar a plataforma reproduzível a partir do repositório e
utilizável por alunos de DSP sem conhecimento de baixo nível.

Resumo das mudanças, detalhadas em `RESSALVAS.md`:

1. Correções mínimas que fazem o `morphe_server` compilar.
2. Expansão de `conv1d` e do FIR de 128 para 1024 amostras por entrada.
3. `Quartus/gen_hps_header.py`, ferramenta nova que gera e **verifica** o
   `C/hps_0.h` a partir do `.sopcinfo`, sem exigir o SoC EDS.
4. Versionamento do conjunto sintetizado que comprovadamente funciona
   (bitstream, `.sopcinfo`, `hps_0.h`) com manifesto de integridade.

As modificações são distribuídas sob a mesma GNU GPL v3.
