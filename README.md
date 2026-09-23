# Morphe

Plataforma para executar operações de Processamento Digital de Sinais — convolução,
FIR, IIR, FFT e IFFT — na FPGA de uma placa DE1-SoC, comparando o resultado do
hardware com a referência calculada em software. TCC de Carlos Valadão (UEFS),
evoluído no estágio de Antonio Nicassio Santos Lima no LabPS/UEFS, sob supervisão do
Prof. Armando S. Sanca. Ver `NOTICE.md` e `LICENSE` (GPL v3).

## Usar

Na estação do laboratório, com a placa ligada ao USB-Blaster:

```bash
./morphe-up.sh
```

```bash
cd Python && python3 morphe_app.py
```

O primeiro prepara a placa (programa a FPGA e sobe o servidor); o segundo abre o
aplicativo, já conectado. O passo a passo completo, inclusive a instalação para uma
turma inteira, está em `PREPARACAO.md`.

## O que é cada pasta

**O produto** — o que roda quando alguém usa o Morphe:

| pasta | o que é |
|---|---|
| `Python/` | o aplicativo (`morphe_app.py` e as janelas) e os módulos que ele usa: protocolo, projeto de filtros, núcleo de DSP |
| `C/` | o servidor que roda no processador ARM da placa e fala com a FPGA (`morphe_server.c`), mais o `autostart/` que o sobe no boot |
| `Quartus/` | o projeto de hardware da FPGA e o bitstream pronto, em `output_files/soc_system_time_limited.sof` |
| raiz | `morphe-up.sh` (prepara a placa), `deploy.sh` (envia o servidor), `instala-quartus.sh` (Quartus 20.1 para todas as contas de um computador) |

**O que não é produto:**

| pasta | o que é |
|---|---|
| `Python/ferramentas/` | testes contra a placa (`testa_*.py`), comparação com o MATLAB, geração de vetores para o testbench, geração de figuras. Rodar de dentro de `Python/`: `python3 ferramentas/testa_iir_hw.py <ip>` |
| `exemplos/` | bundles `.mrph` com resultados reais da placa, para abrir no comparador do aplicativo |
| `docs/` | documentação técnica e registro do estágio (ver abaixo) |
| `legado/` | arquivos do projeto original que o produto não usa, guardados para referência |

**Dentro de `Quartus/`**, nem tudo vai para o bitstream. Os testbenches do IIR
(`tb_iir_*.v`, `roda_tb_iir.sh`) e as ferramentas de compilação
(`gen_hps_header.py`, `relatorio_timing.tcl`, `morphe_ping.py`) ficam ali porque
dependem de estar na pasta do projeto. Dois arquivos ainda estão listados no projeto
sem serem usados — `fft_impulse_test.v` e `output_files/spiral_dft_top.v` —, e só saem
junto com a próxima compilação do bitstream, que é o que prova que a retirada não quebra
nada.

**Não mover os `iir_*.v` para fora de `Quartus/`:** eles não estão listados no
`soc_system.qsf`; o Quartus os encontra por estarem na pasta do projeto. Fora dela, a
compilação falha.

## Documentação

| arquivo | assunto |
|---|---|
| `PREPARACAO.md` | preparar a placa, instalar para uma turma, Quartus nos computadores |
| `docs/GERENCIAMENTO-PLACAS.md` | como uma requisição chega à placa, com várias placas e vários clientes |
| `docs/PRECISAO-NUMERICA.md` | os formatos de ponto fixo e os erros medidos |
| `docs/COMPILAR-IIR.md` | como recompilar o bitstream |
| `docs/NOVA-PLACA.md` | incorporar uma placa nova ao laboratório |
| `docs/ADC.md` | como o ADC da placa funciona e as etapas para capturar sinais com ele |
| `docs/RESSALVAS.md` | o que foi corrigido no projeto original, e por quê |
| `docs/LINHA-DE-BASE-PASSOS.md` | a medição de usabilidade antes das mudanças |
| `docs/DIARIO.md` | o diário do estágio: o que foi feito, medido e validado, dia a dia |

## Conferir um clone

```bash
sha256sum -c PROVENIENCIA.sha256
```

Confere que as fontes e o bitstream são os mesmos que foram validados na placa.
**Hoje `C/morphe_server.c` e `C/morphe_config.h` falham, e é esperado:** a lista foi
gerada em 15/09, e o servidor mudou depois (em 21/09, para não travar a placa antes de a
FPGA estar programada). Ela precisa ser regerada com `gera_proveniencia.sh` na estação.
