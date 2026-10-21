# Compilar o bitstream (ADC e FFT)

O hardware desta versão tem dois blocos: o controlador de captura do ADC
(`Quartus/adc_captura.v`) e a FFT (`Quartus/fft_wrapper.v` + o IP `fft_core/`). Este é
o passo a passo para gerar o bitstream a partir do repositório, na estação do
laboratório, com o **Quartus Prime Lite 20.1**.

## Estado desta branch

A branch `estagio/adc-fft` saiu da versão completa do Morphe. O `soc_system.qsys`, o
`ghrd_top.v` e o `.qsf` já estão só com ADC e FFT, mas **os arquivos gerados ainda são
os da versão completa**: `soc_system.sopcinfo`, `soc_system/`, `C/hps_0.h`,
`hps_isw_handoff/` e o `.sof`. Enquanto a sequência abaixo não for feita:

- o `.sof` versionado ainda carrega os outros blocos, sem uso; o ADC e a FFT funcionam
  com ele normalmente, porque os endereços dos dois não mudaram;
- o `C/hps_0.h` ainda lista os endereços dos outros blocos, e o servidor os ignora;
- não há `PROVENIENCIA.sha256`: ele é gerado no passo 7.

Depois do passo 2, o `hps_0.h` muda e o sysid ganha um timestamp novo. A partir daí
o `.sof` **tem** que ser recompilado e gravado: o servidor novo recusa o ADC com o
bitstream antigo (ver "Proteção", abaixo). É o comportamento desejado.

## Mapa de endereços

```
h2f_axi_master        (memórias)
  0x00018000  fft_yn_re      4 KiB    saída da FFT, parte real
  0x00019000  fft_yn_imag    4 KiB    saída da FFT, parte imaginária
  0x0001A000  fft_xn_re      4 KiB    entrada da FFT, parte real (Q15.8)
  0x0001B000  fft_xn_imag    4 KiB    entrada da FFT, parte imaginária
  0x00020000  adc_buf        128 KiB  32768 amostras de 32 bits (12 úteis)

h2f_lw_axi_master     (PIOs)
  0x0050  fft_bfp_exponent  entrada, 6 bits  expoente do ponto flutuante de bloco
  0x0060  fft_wrapper_done  entrada, 1 bit
  0x0070  fft_inverse       saída, 1 bit     0 na operação normal
  0x0080  fft_wrapper_start saída, 1 bit
  0x00D0  adc_start         saída, 1 bit     borda de subida dispara a captura
  0x00E0  adc_done          entrada, 1 bit
  0x00F0  adc_config        saída, 7 bits    [5:0] palavra do LTC2308; [6] contínua
  0x0100  adc_divisor       saída, 32 bits   fs = 50 MHz / divisor (250 a 50000)
  0x0110  adc_namostras     saída, 16 bits   1 a 32768 (captura única)
  0x0120  adc_contador      entrada, 32 bits amostras já na RAM (0 em repouso)
  0x10000 sysid_qsys                         id e timestamp do bitstream
```

## Sequência, na estação, conta `coordenador`

Tudo num clone de desenvolvimento, e não em `/opt/morphe`. Um comando por vez. Se
aparecer `not found` num comando do Quartus, digite `bash` antes.

### 0. Trazer a branch

```bash
git clone -b estagio/adc-fft https://github.com/nicassiosantos/morphe.git ~/morphe-adc-fft
```

```bash
cd ~/morphe-adc-fft
```

### 1. Simular o controlador do ADC (1 minuto, sem placa)

```bash
bash Quartus/testbench/roda_tb_adc.sh
```

Tem que terminar em `TUDO OK`.

### 2. Gerar o sistema do Platform Designer

```bash
cd Quartus
```

```bash
qsys-generate soc_system.qsys --synthesis=VERILOG --family="Cyclone V" --part=5CSEMA5F31C6
```

### 3. Regenerar o cabeçalho de endereços

```bash
python3 gen_hps_header.py
```

```bash
grep -cE "CONV1D_|FIR_|IIR_" ../C/hps_0.h
```

Tem que dar **0**: os outros blocos saíram.

```bash
grep -cE "ADC_(BUF|START|DONE|CONFIG|DIVISOR|NAMOSTRAS|CONTADOR)_BASE|FFT_(XN|YN)_(RE|IMAG)_BASE|SYSID_QSYS_TIMESTAMP" ../C/hps_0.h
```

Tem que dar **12**. Se der menos, o Qsys não gerou algum módulo: volte ao passo 2.

### 4. Compilar (~20 min)

```bash
quartus_sh --flow compile soc_system.qpf
```

```bash
grep -E "Logic utilization|Total DSP|Total block memory" output_files/soc_system.fit.summary
```

A versão completa usava 45 % dos ALMs e 55 % da memória; esta tem de usar bem menos.

```bash
grep -A5 "Slow 1100mV 85C Model Fmax Summary" output_files/soc_system.sta.rpt
```

Fmax acima de 50 MHz.

### 5. Programar a placa e subir o servidor

```bash
cd ~/morphe-adc-fft
```

```bash
./morphe-up.sh --cable 'DE-SoC [1-2]' --deploy
```

O `--deploy` reenvia e recompila o servidor na placa, com o `hps_0.h` novo. Tem que
terminar com o `morphe_ping` 4/4 (TCP, protocolo, captura do ADC, FFT de impulso).
Nunca use `sudo` com o `morphe-up.sh`.

### 6. Testar

```bash
python3 Python/ferramentas/testa_blocos.py --placa 172.16.230.24
```

```bash
python3 Python/ferramentas/testa_adc.py 172.16.230.24 basico
```

Com o gerador de funções no CH0 (offset ~2 V, no máximo 4 Vpp, conferido antes no
osciloscópio):

```bash
python3 Python/ferramentas/testa_adc.py 172.16.230.24 senoide --f 1000 --canal 0
```

```bash
python3 Python/ferramentas/testa_adc.py 172.16.230.24 continuo --f 1000 --segundos 10
```

Depois, o aplicativo:

```bash
cd Python
```

```bash
python3 morphe_app.py
```

Abra **Aquisição (ADC da placa)** e capture. Depois abra a **FFT** com o tipo de sinal
**Captura do ADC**.

### 7. Registrar e versionar

```bash
cd ~/morphe-adc-fft
```

```bash
./gera_proveniencia.sh "morphe_ping 4/4; testa_adc TUDO OK; testa_blocos TUDO OK"
```

Entram no commit: `Quartus/output_files/soc_system_time_limited.sof`,
`Quartus/output_files/soc_system.fit.summary` e `.sta.summary`,
`Quartus/soc_system.sopcinfo`, `Quartus/soc_system/` (sem `db/`),
`Quartus/hps_isw_handoff/`, `C/hps_0.h` e `PROVENIENCIA.sha256`.

## Proteção contra bitstream trocado

No Cyclone V, acessar pela ponte um endereço sem escravo **trava o barramento do HPS**.
Os PIOs do ADC só existem no bitstream que os tem. Por isso o servidor:

1. só compila o ADC se o `hps_0.h` **gerado** tiver `adc_buf` e os PIOs;
2. antes de tocar em qualquer PIO do ADC, lê o timestamp do `sysid`, que existe em
   todos os bitstreams do Morphe no mesmo endereço. Se não for o timestamp do
   `hps_0.h`, recusa com `FPGA_NAO_PREPARADA` e a mensagem "o bitstream na FPGA não é
   o deste servidor";
3. no PING, informa `adc_n_max=0` sempre que o ADC não pode ser usado.

## Captura contínua (sinais maiores que a RAM)

Até 32768 amostras, a captura é de uma vez. Acima disso, ou sem limite, o hardware
grava sem parar na RAM, que funciona como buffer circular. O servidor copia as amostras
novas e as manda em blocos enquanto a captura segue.

- **O limite passa a ser o servidor acompanhar.** A RAM segura 164 ms a 200 kHz. Se o
  servidor atrasar mais que isso, a captura termina com o estado "perdeu". O que
  chegou até ali é contínuo e válido.
- **A placa fica ocupada durante a captura inteira.** O servidor atende uma conexão
  por vez.
- **Memória no PC:** ~10 bytes por amostra (1 minuto a 200 kHz ≈ 120 MB).
- **Parar:** o cliente manda 1 byte (botão Parar) ou fecha a conexão.

## Se precisar voltar atrás

A versão completa continua na branch `estagio/v1.1-1024pontos`, com o bitstream dela.
Para devolver a placa a ela, rode o `morphe-up.sh` de um clone dessa branch (por
exemplo `/opt/morphe`).
