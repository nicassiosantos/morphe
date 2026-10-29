# Quartus/ — o projeto da FPGA

Projeto Quartus Prime Lite **20.1** da DE1-SoC (Cyclone V 5CSEMA5F31C6N), com dois
blocos de hardware: a **captura do ADC** e a **FFT**. Abrir `soc_system.qpf`. Como
compilar: `docs/COMPILAR.md`.

## O que vai para o bitstream

| Arquivo | O que é |
|---|---|
| `soc_system.qpf`, `soc_system.qsf` | o projeto: dispositivo, pinos, lista de arquivos |
| `soc_system_timing.sdc` | restrições de tempo |
| `ghrd_top.v` | o topo: liga o HPS (Platform Designer) aos dois blocos e aos pinos |
| `adc_captura.v` | o controlador próprio do ADC LTC2308 (captura a fs fixa, única ou contínua) |
| `fft_wrapper.v` | envolve o núcleo de FFT da Intel (`fft_core/`) |
| `memory_read_controller.v`, `memory_write_controller.v` | leitura e escrita nas memórias de porta dupla, usados pelo `fft_wrapper.v` |
| `soma_core.v`, `soma.v` | y = a + b: o módulo de exemplo do roteiro `docs/roteiro-modulo` (só na branch `estagio/modulo-soma-adc-fft`) |
| `soc_system.qsys` → `soc_system/` | o sistema do Platform Designer: HPS, pontes, memórias da FFT e do ADC, PIOs |
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

> **Atenção:** os arquivos gerados (`soc_system/`, `soc_system.sopcinfo`,
> `hps_isw_handoff/`, o `.sof` e os `.summary`) ainda são os da versão completa do
> Morphe até a compilação descrita em `docs/COMPILAR.md` ser feita na estação.

## Ferramentas (não vão para o bitstream)

| Arquivo | Para quê |
|---|---|
| `gen_hps_header.py` | gera o `C/hps_0.h` a partir do `.sopcinfo`; `--check` confere se estão iguais |
| `relatorio_timing.tcl` | resume o caminho crítico depois de uma compilação |
| `morphe_ping.py` | os quatro testes que o `morphe-up.sh` faz contra a placa: TCP, protocolo, captura do ADC, FFT de impulso |
| `testbench/` | simulação em Icarus Verilog, sem Quartus nem placa: `roda_tb_adc.sh` (controlador do ADC contra um modelo do LTC2308) |
