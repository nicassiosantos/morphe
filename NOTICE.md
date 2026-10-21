# Origem e créditos

Este repositório é um **fork** de **Morphe**, de **Carlos Valadão**
(https://github.com/CarlosValadao/morphe), desenvolvido como Trabalho de
Conclusão de Curso: *"Implementação de Ferramentas de Computação Numérica para
o Processamento Digital de Sinais em Hardware Reconfigurável"* (UEFS).

Todo o projeto original — a arquitetura, a integração do núcleo de FFT, o
servidor TCP em C e o cliente gráfico em Python — é de autoria de Carlos Valadão e permanece sob a **GNU General Public
License v3**, preservada integralmente em `LICENSE`.

O histórico de commits deste fork começa nos commits originais do autor; nada
foi reescrito, refeito ou reatribuído.

## Modificações

Modificado a partir de 2026-09-01 por **Antonio Nicassio Santos Lima**, durante
estágio curricular no Laboratório de DSP (DTEC/UEFS), sob supervisão do
**Prof. Armando S. Sanca**.

Objetivo do fork: tornar a plataforma reproduzível a partir do repositório e
utilizável por alunos de DSP sem conhecimento de baixo nível.

Esta versão (branch `estagio/adc-fft`) mantém só dois blocos de hardware: a
captura do ADC e a FFT. A plataforma completa, com o histórico detalhado das
mudanças, está na branch `estagio/v1.1-1024pontos`.

Resumo das mudanças que valem para esta versão:

1. Correções mínimas que fazem o `morphe_server` compilar.
2. FFT de 1024 pontos, com normalização da entrada e FFT longa em quatro passos.
3. Controlador próprio do ADC LTC2308 (`Quartus/adc_captura.v`), com captura a
   taxa fixa e captura contínua.
4. `Quartus/gen_hps_header.py`, ferramenta nova que gera e **verifica** o
   `C/hps_0.h` a partir do `.sopcinfo`, sem exigir o SoC EDS.
5. Versionamento do conjunto sintetizado que comprovadamente funciona
   (bitstream, `.sopcinfo`, `hps_0.h`) com manifesto de integridade.

As modificações são distribuídas sob a mesma GNU GPL v3.
