# Compilar o bitstream com o ADC (etapas 1 e 2)

Branch `estagio/v1.7-adc`. Esta mudança **altera o hardware**: `soc_system.qsys`,
`ghrd_top.v` e o `.qsf` ganharam o controlador de captura do LTC2308. O bitstream
versionado **ainda não tem o ADC** até a compilação abaixo ser feita na estação.

Enquanto isso, nada quebra. O servidor só compila o ADC quando o `hps_0.h` gerado
tem a RAM `adc_buf`, e o `hps_0.h` versionado ainda não tem. Um servidor novo com
um bitstream antigo recusa o pedido e não toca na FPGA (ver "Proteção" abaixo).

## O que foi alterado

| arquivo | o que entrou |
|---|---|
| `Quartus/adc_captura.v` | controlador próprio do LTC2308, com captura única e contínua (buffer circular), novo |
| `Quartus/tb_adc_captura.v`, `roda_tb_adc.sh` | testbench com modelo do LTC2308, novo |
| `Quartus/soc_system.qsys` | 1 memória on-chip e 6 PIOs, clonados dos do IIR |
| `Quartus/ghrd_top.v` | fios, instância do `adc_captura` e portas no `soc_system`; sai a instância comentada do IP do University Program |
| `Quartus/soc_system.qsf` | entra `adc_captura.v`; saem `fft_impulse_test.v` e `output_files/spiral_dft_top.v` (sem uso) |
| `Quartus/gen_hps_header.py` | passa a emitir `SYSID_QSYS_ID` e `SYSID_QSYS_TIMESTAMP` |
| `C/morphe_server.c`, `morphe_protocol.h`, `morphe_config.h` | `OP_ADC` = 7 (até 32768 amostras) e `OP_ADC_CONTINUO` = 8 (sem limite, em blocos); `SIGPIPE` ignorado |
| `Python/` | `aquisicao.py`, `aquisicao_window.py`, tipo "Captura do ADC" no painel de sinal, `ferramentas/testa_adc.py` |

Mapa de endereços, nos primeiros buracos livres. Nada foi movido:

```
h2f_axi_master        (memória)
  0x00020000  adc_buf        128 KiB   32768 amostras de 32 bits (12 úteis)

h2f_lw_axi_master     (PIOs)
  0x00D0  adc_start      saída, 1 bit    borda de subida dispara a captura
  0x00E0  adc_done       entrada, 1 bit
  0x00F0  adc_config     saída, 7 bits   [5:0] palavra do LTC2308; [6] contínua
  0x0100  adc_divisor    saída, 32 bits  fs = 50 MHz / divisor (250 a 50000)
  0x0110  adc_namostras  saída, 16 bits  1 a 32768 (captura única)
  0x0120  adc_contador   entrada, 32 bits amostras já na RAM (0 em repouso)
```

Memória: a RAM de captura ocupa ~128 dos 232 blocos M10K livres (a última
compilação usava 165 de 397). Deve ficar perto de 293 de 397 (74 %).

## Captura contínua (sinais maiores que a RAM)

Até 32768 amostras, a captura é de uma vez. Acima disso, ou sem limite, o
hardware grava sem parar na RAM, que funciona como buffer circular. O servidor
copia as amostras novas e as manda em blocos enquanto a captura segue. Não há
buraco no tempo entre blocos, porque o contador de período do FPGA não para.

- **O limite passa a ser o servidor acompanhar.** A RAM segura 164 ms a 200 kHz.
  Se o servidor atrasar mais que isso, amostras seriam sobrescritas antes de lidas.
  Isso nunca vira buraco silencioso: o servidor relê o contador depois de cada
  cópia e, se o escritor passou do ponto, a captura termina com o estado
  "perdeu". O que chegou até ali é contínuo e válido.
- **A placa fica ocupada durante a captura inteira.** O servidor atende uma
  conexão por vez: outro aluno na mesma placa espera, e a busca de placas não a
  encontra até a captura acabar.
- **Memória no PC:** ~10 bytes por amostra (1 minuto a 200 kHz ≈ 120 MB).
- **Parar:** o cliente manda 1 byte (botão Parar) ou fecha a conexão. Fechar a
  janela também para a captura.

## O que já foi verificado sem a placa (24/09/2026, no Windows)

- `Quartus/roda_tb_adc.sh`: o controlador contra um modelo do LTC2308 em 9 casos:
  - captura única a 200 kHz, 50 kHz e 1 kHz, divisor abaixo do mínimo, n = 0 e a
    RAM cheia;
  - contínua a 200 e a 50 kHz com a RAM dando a volta, parada no meio de um quadro;
  - captura única depois da contínua.

  O testbench confere o período exato, o canal, a ordem dos bits e os tempos do
  LTC2308. No modo contínuo, confere também, a cada amostra, que contador = c
  significa amostra c−1 já na RAM. **TUDO OK.**
- O servidor C compilado para ARM (`-Wall -Wextra`, sem aviso) com e sem o ADC.
- O servidor C real rodando em Linux x86, com `/dev/mem` trocado por memória e uma
  thread no lugar do `adc_captura.v`:
  - captura única: 25 verificações;
  - contínua: sequência **idêntica amostra por amostra** em 100 mil amostras
    (29 blocos), parada pelo usuário, bipolar, 2 milhões de amostras em 10 s;
  - perda forçada: acusada como "perdeu", com o prefixo intacto;
  - cliente que fecha a conexão no meio: o servidor sobrevive;
  - proteção: bitstream antigo e servidor sem ADC.

**Não verificado:**
- o `.qsys` nunca passou pelo `qsys-generate`, e o `ghrd_top.v` nunca passou
  pelo Quartus;
- a velocidade real de leitura da ponte HPS–FPGA, que decide se o servidor
  acompanha 200 kHz na contínua. O `testa_adc.py basico` mede isso.

## Sequência, na estação LABPS-47723, conta `coordenador`

Tudo no clone de desenvolvimento `~/Documentos/validacao-final/morphe`, e não em
`/opt/morphe`: é lá que fica o projeto do Quartus com o `db/`. Um comando por vez.
Se aparecer `not found` num comando do Quartus, digite `bash` antes.

### 0. Trazer a branch

```bash
cd ~/Documentos/validacao-final/morphe
```

```bash
git fetch origin
```

```bash
git checkout estagio/v1.7-adc
```

```bash
git log --oneline -1
```

Nunca use `git reset --hard` nesse clone (o `db/` está rastreado por engano).

### 1. Simular o controlador (1 minuto, sem placa)

```bash
bash Quartus/roda_tb_adc.sh
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
grep -cE "ADC_(BUF|START|DONE|CONFIG|DIVISOR|NAMOSTRAS|CONTADOR)_BASE|SYSID_QSYS_TIMESTAMP" ../C/hps_0.h
```

Tem que dar **8**. Se der menos, o Qsys não gerou algum módulo: volte ao passo 2.

### 4. Compilar (~30 min)

```bash
quartus_sh --flow compile soc_system.qpf
```

```bash
grep -E "Logic utilization|Total DSP|Total block memory" output_files/soc_system.fit.summary
```

```bash
grep -A5 "Slow 1100mV 85C Model Fmax Summary" output_files/soc_system.sta.rpt
```

Fmax acima de 50 MHz (estava em 60,99). Memória perto de 293 de 397 blocos.

### 5. Programar a placa 1 e subir o servidor

```bash
cd ~/Documentos/validacao-final/morphe
```

```bash
./morphe-up.sh --cable 'DE-SoC [1-2]' --board 172.16.230.24
```

O `hps_0.h` mudou, então o servidor é reenviado e recompilado sozinho. Nunca use
`sudo` com o `morphe-up.sh`.

### 6. Conferir que o resto continua igual

```bash
python3 Python/ferramentas/testa_ifft_roundtrip.py 172.16.230.24
```

```bash
python3 Python/ferramentas/testa_iir_hw.py 172.16.230.24
```

```bash
python3 Python/ferramentas/testa_blocos.py --placa 172.16.230.24
```

### 7. O ADC, em quatro degraus

**7a. Sem nada ligado** (servidor, recusas e se o HPS acompanha 200 kHz na
contínua):

```bash
python3 Python/ferramentas/testa_adc.py 172.16.230.24 basico
```

**7b. Tensão conhecida, com o multímetro.** Ligue uma tensão entre 0 e 4 V no
CH0 (pino 2 do J15) e o terra no pino 10. Pode ser uma pilha ou dois resistores
iguais entre o pino 1 (5 V) e o 10, que dão ~2,5 V. Meça com o multímetro no
mesmo ponto.

```bash
python3 Python/ferramentas/testa_adc.py 172.16.230.24 tensao --canal 0
```

**7c. Senoide do gerador.** Antes de ligar na placa, **confira no
osciloscópio**: offset DC de ~2 V, no máximo 4 Vpp, mínimo acima de 0 V. Use
1 kHz no gerador.

```bash
python3 Python/ferramentas/testa_adc.py 172.16.230.24 senoide --f 1000 --canal 0
```

**7d. Contínua com a senoide** (10 s a 200 kHz, confere as emendas entre blocos):

```bash
python3 Python/ferramentas/testa_adc.py 172.16.230.24 continuo --f 1000 --segundos 10
```

Anote os números de 7b a 7d no DIARIO.

### 8. A janela

```bash
cd Python
```

```bash
python3 morphe_app.py
```

Abra **Aquisição (ADC da placa)**. Leia a tensão. Capture 8192 amostras. Depois
ponha 0 em Amostras, clique em Capturar e, alguns segundos depois, em Parar. Por
fim, abra a FFT com o tipo de sinal **Captura do ADC**.

### 9. Fechar

Com tudo validado: `morphe-up` nas duas placas, depois
`./gera_proveniencia.sh "ADC validado: <resumo>"`, o commit do `.sof`, do
`.sopcinfo` e do `hps_0.h` gerados, e a entrada no DIARIO. Só depois disso a
branch vai para a principal e para o `/opt/morphe` da turma.

## Proteção contra bitstream trocado

No Cyclone V, acessar pela ponte um endereço sem escravo **trava o barramento
do HPS** (foi o que derrubou a placa 2 em 21/09). Os PIOs do ADC só existem no
bitstream novo. Por isso o servidor:

1. só compila o ADC se o `hps_0.h` **gerado** tiver `adc_buf` e os PIOs;
2. antes de tocar em qualquer PIO do ADC, lê o timestamp do `sysid`, que existe
   em todos os bitstreams do Morphe no mesmo endereço. Se não for o timestamp do
   `hps_0.h`, recusa com `FPGA_NAO_PREPARADA` e a mensagem "o bitstream na FPGA
   não é o deste servidor";
3. no PING, informa `adc_n_max=0` sempre que o ADC não pode ser usado.

Consequência prática: depois de um `qsys-generate`, o `.sof` **tem** que ser
recompilado e reprogramado, senão o ADC fica recusado. É o comportamento
desejado.

## Se precisar voltar atrás

```bash
git checkout estagio/v1.1-1024pontos
```

A principal não foi tocada, e o bitstream dela continua valendo.
