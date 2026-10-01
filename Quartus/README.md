# Quartus/ — o projeto da FPGA

Projeto Quartus Prime Lite **20.1** da DE1-SoC (Cyclone V 5CSEMA5F31C6N).
Abrir `soc_system.qpf`. Como compilar: `docs/COMPILAR-ADC.md`; o processo
completo, com o porquê de cada passo, está no capítulo 10 do manual.

> **Não mover os `.v` da raiz desta pasta.** Alguns (os `iir_*.v`) não estão
> listados no `soc_system.qsf`: o Quartus os encontra por estarem na pasta do
> projeto. Em outra pasta, a compilação falha.

## O que vai para o bitstream

| Arquivo | O que é |
|---|---|
| `soc_system.qpf`, `soc_system.qsf` | o projeto: dispositivo, pinos, lista de arquivos |
| `soc_system_timing.sdc` | restrições de tempo |
| `ghrd_top.v` | o topo: liga o HPS (Platform Designer) aos aceleradores e aos pinos |
| `conv1d.v` | convolução; instanciado duas vezes (convolução e FIR) |
| `fft_wrapper.v` | envolve o núcleo de FFT da Intel (`fft_core/`) |
| `iir_cascade.v`, `iir_sos.v`, `iir_biquad_mac.v` | o filtro IIR em seções de segunda ordem |
| `adc_captura.v` | o controlador próprio do ADC LTC2308 (leitura e captura) |
| `memory_read_controller.v`, `memory_write_controller.v` | leitura e escrita nas memórias de porta dupla, usados pelos aceleradores |
| `soc_system.qsys` → `soc_system/` | o sistema do Platform Designer: HPS, pontes, memórias, PIOs |
| `fft_core.qsys` → `fft_core/` | o núcleo de FFT da Intel (IP licenciada, gera o `_time_limited.sof`) |
| `ip/` | IPs pequenos do GHRD: reset do HPS, detector de borda, captura de interrupção |
| `hps_isw_handoff/` | configuração do HPS gerada pela compilação, usada pelo *preloader* |
| `soc_system.sopcinfo` | descrição do sistema; dela sai o `C/hps_0.h` |

## O resultado

| Arquivo | O que é |
|---|---|
| `output_files/soc_system_time_limited.sof` | **o bitstream que as placas usam** (o `morphe-up.sh` grava este) |
| `output_files/soc_system_time_limited.cdf` | a cadeia JTAG para abrir no Programmer |
| `output_files/soc_system.fit.summary`, `.sta.summary` | recursos usados e Fmax da última compilação |

O resto do `output_files/` é regenerado a cada compilação e não é versionado.

## Ferramentas (não vão para o bitstream)

| Arquivo | Para quê |
|---|---|
| `gen_hps_header.py` | gera o `C/hps_0.h` a partir do `.sopcinfo`; `--check` confere se estão iguais |
| `relatorio_timing.tcl` | resume o caminho crítico depois de uma compilação |
| `morphe_ping.py` | os quatro testes que o `morphe-up.sh` faz contra a placa |
| `testbench/` | simulações em Icarus Verilog, sem Quartus nem placa: `roda_tb_iir.sh` (IIR bit a bit contra o modelo em Python) e `roda_tb_adc.sh` (controlador do ADC contra um modelo do LTC2308) |

## Retirados em 01/10/2026

Estavam listados no `soc_system.qsf` sem serem instanciados no `ghrd_top.v`.
A síntese do projeto com e sem eles deu o mesmo circuito (ver o DIARIO de
01/10/2026). Continuam no histórico do git, se um dia fizerem falta:

- `fir_wrapper.v` e `fir_ii/`: o IP de FIR da Intel; o FIR usa a segunda instância do `conv1d`;
- `adcltc2308_controller/` e o `.qsys`/`.sopcinfo` dele: o controlador do *University Program*, trocado pelo `adc_captura.v`;
- `ip/debounce/`: o fio `fpga_debounced_buttons` não tem quem o acione;
- `stp1.stp`: SignalTap, que estava desligado;
- `fifo.qip`: vazio, sem referência.
