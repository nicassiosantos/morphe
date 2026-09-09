# Ressalvas

Comportamentos verificados em hardware que não são óbvios pelo código, e que
já custaram tempo de diagnóstico. Leia antes de investigar qualquer suspeita
de defeito.

Data de referência: 2026-09-09. Conjunto validado: 2026-09-08.

---

## 1. Bitstream, `hps_0.h` e `morphe_server` são um conjunto inseparável

A expansão para 1024 pontos mudou os endereços-base das memórias on-chip:

| Memória      | Base      | Span   |
|--------------|-----------|--------|
| `fir_yn`     | `0x10000` | 8192   |
| `conv1d_yn`  | `0x12000` | 8192   |
| `fir_hn`     | `0x14000` | 4096   |
| `fir_xn`     | `0x15000` | 4096   |
| `conv1d_hn`  | `0x16000` | 4096   |
| `conv1d_xn`  | `0x17000` | 4096   |

Misturar um `.sof` de uma versão com um `hps_0.h` de outra **não produz erro**:
o servidor escreve em endereços válidos porém errados e devolve lixo ou zeros.
Foi essa a causa raiz de dias de investigação equivocada de RTL.

**Como verificar em um comando**, sem ter Quartus instalado:

    python Quartus/gen_hps_header.py --check

Saída 0 significa que `C/hps_0.h` corresponde ao `Quartus/soc_system.sopcinfo`
versionado ao lado. Rode isso **antes** de suspeitar de qualquer outra coisa.

## 2. O acumulador faz wraparound, não saturação

`Quartus/conv1d.v:202` não tem clamp. Com N=1024 e amplitude 6, a saída dá
−28672 no lugar de +36864. O limiar é `N * A² >= 32768`.

**Como aplicar:** teste com amplitudes pequenas primeiro. Um resultado
negativo inesperado em sinais positivos é wraparound, não defeito.

## 3. Erro de truncamento cresce com N — é previsto

O erro contra o NumPy chega a centenas de LSBs com N=1024, por truncamento
acumulado em `Quartus/conv1d.v:104`. Não é regressão. Só passa de milhares se
houver wraparound (item 2).

A correção de melhor retorno é arredondar no shift, trocando `[47:16]` por
`[47:16] + mult_result_reg[15]`: derruba o erro máximo de 521 para 25 LSB.
**Ainda não aplicada** — exige recompilação completa e nova validação.

## 4. O corte por `nx+nh-1` no cliente não é bug

`Python/conv_window.py:310` faz zero-padding dos dois sinais até o máximo antes
de enviar; a linha 340 corta a saída pelo tamanho original
(`n_useful = nx_orig + nh_orig - 1`). O hardware calcula as 2047 amostras
corretas.

Para obter 2047 pontos não-nulos, **os dois** sinais originais precisam ter
N=1024 de verdade — não um com 1024 e outro com 1.

**Como diagnosticar:** a interface imprime `hardware: 1024+1024 -> NNNN
amostras`. O último número vem da placa; 2047 significa que hardware,
protocolo e servidor estão corretos. No log do servidor, `-> CONV OK:
n_out=2047`.

## 5. Custo quadrático: 2,6 ms para ~168 ms por operação

Por isso o timeout do servidor subiu para 5000 ms. Não reduza esse valor sem
medir.

## 6. O `_Static_assert` do `fir_yn` só falhava no hardware de 128

Com o hardware de 1024, `FIR_YN_SPAN` = 8192 e `MORPHE_CONV_Y_MAX` = 2047
(8188 bytes), então a asserção original **passa**. A troca de
`MORPHE_CONV_Y_MAX` por `MORPHE_CONV_N_MAX` era necessária apenas no hardware
antigo. Não reaplique.

## 7. `morphe_server_handling_sigs.c` é código morto

O Makefile constrói um único arquivo:

    $(TARGET): morphe_server.c $(HEADERS_PROD)

`morphe_server_handling_sigs.c` é uma duplicata legada que nunca é compilada.
Editá-lo não tem efeito nenhum. As correções que importam estão todas em
`morphe_server.c`.

## 8. O `.sof` versionado é time-limited

`Quartus/output_files/soc_system_time_limited.sof` foi gerado com licença
Quartus Lite time-limited: **só roda enquanto o programador estiver
conectado**. A placa perde a configuração ao ser desconectada.

Build de referência: Quartus Prime **20.1.0** Build 711 SJ Lite, em Ubuntu
22.04.5. A síntese com 23.1std produz resultados diferentes.

## 9. Nunca rode `make clean` no diretório do servidor da placa

O binário `morphe_server` que funciona foi compilado antes das correções deste
repositório e não pode ser regenerado a partir do estado que está na placa —
veja o item 10. `make clean` destrói o único artefato funcional. Já aconteceu
uma vez.

## 10. A pasta do servidor na placa não é auto-consistente

Verificado em 2026-09-09: o `morphe_server.c` que está na placa usa
`MORPHE_OP_FIR` em seis lugares, mas o `morphe_protocol.h` ao lado dele define
apenas `OP_CONV`, `OP_FFT` e `OP_PING`. **`make` na placa falha hoje.** O
binário em uso foi compilado de um estado em que o define existia, e o header
ficou para trás.

Este repositório corrige isso: `C/morphe_protocol.h` aqui define
`MORPHE_OP_FIR 4U`. Reenvie os arquivos deste repositório para a placa antes de
recompilar.

## 11. `FPGA_ONCHIP_BASE` e `0xC0000000`, nao `0xC8000000`

As memorias de `conv1d`, FIR e FFT sao slaves do `h2f_axi_master`, em offsets
`0x10000`-`0x1BFFF` (ver `C/hps_0.h`). A janela desse bridge no espaco fisico do
HPS comeca em **`0xC0000000`**, entao os enderecos reais sao
`0xC0010000`-`0xC001BFFF`.

O valor `0xC8000000` vem do mapa do **DE1-SoC Computer**, o sistema didatico da
Intel, em que a memoria on-chip fica nesse endereco. Este projeto nao usa aquele
sistema. Com `0xC8000000`, o `mmap` cai em espaco vazio do bridge: **nenhum erro
e reportado** e todas as leituras devolvem zero.

**Sintoma exato:** o `morphe_ping.py` passa nos testes 1 e 2, e o teste 3 devolve
`y = [0. 0. 0. 0. 0.]`. Na interface, convolucao inteira zerada.

O detalhe que engana: os PIOs de `start`, `done` e `error` ficam no
`h2f_lw_axi_master`, cuja base (`LW_BRIDGE_BASE 0xFF200000`) esta correta. Entao
o servidor sobe o `start`, ve o `done` subir e conclui que o hardware respondeu
-- mas as memorias que ele leu e escreveu nao eram as da FPGA. Foi essa a causa
do diagnostico de 02/09/2026 ("levantavam done sem gravar palavra alguma na
memoria de saida"), que na epoca foi atribuido a defeito de RTL.

**Cuidado com o `address_map_arm.h` que esta na placa:** ele tem `0xC8000000` e
esta desatualizado em relacao ao binario que roda ali, exatamente como o
`morphe_protocol.h` do item 10. Os cabecalhos que estao na placa nao sao a
fonte da verdade -- este repositorio e.
