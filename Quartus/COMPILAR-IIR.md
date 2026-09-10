# Compilar o bitstream com o bloco IIR

Branch `estagio/v1.3-iir-hw`. Esta branch **muda o hardware**: o
`soc_system.qsys` e o `ghrd_top.v` ganharam o bloco IIR, e o bitstream
versionado no repositorio **ainda nao tem esse bloco**.

Enquanto a compilacao nao for feita, esta branch nao roda IIR em placa
nenhuma. Isso e esperado.

## O que foi alterado

| arquivo | o que entrou |
|---|---|
| `soc_system.qsys` | 3 memorias on-chip e 4 PIOs |
| `ghrd_top.v` | fios, parametros, instancia do `iir_cascade` e as portas no `soc_system` |

Mapa de enderecos escolhido nos primeiros buracos livres:

```
h2f_axi_master        (memorias)
  0x0001C000  iir_xn      4 KiB   1024 amostras de 32 bits
  0x0001D000  iir_yn      4 KiB   1024 amostras
  0x0001E000  iir_coef    1 KiB   256 palavras = 5 por secao, ate 51 secoes

h2f_lw_axi_master     (PIOs)
  0x0090  iir_start     saida, 1 bit
  0x00A0  iir_done      entrada, 1 bit
  0x00B0  iir_error     entrada, 1 bit   (saturou em alguma amostra)
  0x00C0  iir_nsecoes   saida, 5 bits    (quantas secoes usar)
```

Ate 0x1B000 e ate 0x80 ja estavam ocupados; nada foi movido.

## O que NAO foi alterado, de proposito

**`soc_system.sopcinfo` e `C/hps_0.h` estao desatualizados** nesta branch.
Os dois sao *gerados*: o `.sopcinfo` sai do Qsys e o `hps_0.h` sai do
`.sopcinfo`. Edita-los a mao criaria exatamente a armadilha do item 11 do
RESSALVAS -- um cabecalho que descreve um hardware que nao existe, com
`mmap` caindo em espaco vazio e leituras devolvendo zero sem erro nenhum.

Eles sao regenerados no passo 2 abaixo.

## Sequencia

Na estacao do laboratorio, com o Quartus no PATH (se der
`qsys-generate: not found`, digite `bash` antes -- alguns terminais abrem
em ksh93, que nao le o `~/.bashrc`).

### 1. Gerar o sistema do Platform Designer

```bash
cd ~/Documentos/validacao-final/morphe/Quartus
```

```bash
qsys-generate soc_system.qsys --synthesis=VERILOG --family="Cyclone V" --part=5CSEMA5F31C6
```

Leva alguns minutos. Ele reescreve `soc_system/` e o
`soc_system.sopcinfo`.

### 2. Regenerar o cabecalho de enderecos

```bash
python3 gen_hps_header.py
```

Confira que os sete simbolos novos apareceram:

```bash
grep -E "IIR_(XN|YN|COEF|START|DONE|ERROR|NSECOES)_BASE" ../C/hps_0.h
```

Se algum faltar, o Qsys nao gerou o modulo -- volte ao passo 1 antes de
compilar.

### 3. Compilar

```bash
quartus_sh --flow compile soc_system.qpf
```

Meia hora, mais ou menos. Ao terminar, confira que o bloco coube:

```bash
grep -E "Logic utilization|Total DSP|Total block memory" output_files/soc_system.fit.summary
```

Antes do IIR: 8.657 / 32.070 ALMs (27%), 15 / 87 DSP, 27% da memoria.
O `iir_cascade` usa 5 blocos DSP -- um por multiplicador do biquad,
compartilhados no tempo entre as secoes -- entao espere algo perto de
20 / 87. Se subir muito mais que isso, o sintetizador replicou o MAC em
vez de compartilhar, e vale olhar.

Confira tambem o timing:

```bash
grep -A5 "Slow 1100mV 85C Model Fmax Summary" output_files/soc_system.sta.rpt
```

O projeto roda a 50 MHz. O caminho critico do biquad e o acumulador de 72
bits somado aos cinco produtos; se o Fmax cair abaixo de 50 MHz, o
caminho a seguir e registrar os produtos (pipeline de um estagio no
`iir_biquad_mac.v`), o que **muda a latencia mas nao o resultado**.

### 4. Programar e testar o que ja funcionava

```bash
quartus_pgm -m jtag -c "DE-SoC [1-1]" -o "p;output_files/soc_system_time_limited.sof@2"
```

**Deixe esse terminal aberto** no prompt `Please enter i for info and q to
quit` -- e o tether da licenca de avaliacao do IP da FFT. Ctrl+C comeca a
contagem de 1 hora.

Antes de testar o IIR, confirme que **conv1d, FIR, FFT e IFFT continuam
funcionando**. O bitstream e novo; tudo foi remapeado. Reenvie o servidor
e rode:

```bash
python testa_ifft_roundtrip.py 172.16.103.226
```

Se a IFFT continuar com zero falhas, o remapeamento nao quebrou nada.

## Depois disso

O bloco estara na FPGA mas ainda sem caminho de software: falta o
`MORPHE_OP_IIR`, o `handle_iir` no servidor C e a tela do projetista.
Ate la, o jeito de exercitar o hardware e escrever direto na memoria com
uma sonda, como descreve o item 15 do RESSALVAS.

## Se precisar voltar atras

```bash
git checkout estagio/v1.1-1024pontos -- Quartus/soc_system.qsys Quartus/ghrd_top.v
```

O bitstream anterior continua versionado e valido -- foi por isso que
esta mudanca nasceu numa branch separada.
