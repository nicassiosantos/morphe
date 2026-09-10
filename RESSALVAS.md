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
22.04.5 (`LABPS-47723`), compilação completa concluída em **2026-09-08 às
16:53**, a partir de `~/Documentos/morphe/tcc`. A síntese com 23.1std produz
resultados diferentes. Ver o item 12 antes de trocar esse arquivo por outro.

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

## 12. Existem sete cópias do `.sof` na estação e só uma funciona

Em 2026-09-09, `find ~ -name "soc_system_time_limited.sof"` na estação devolveu
**sete** arquivos, quatro deles na lixeira, com cinco hashes diferentes. Dois
compartilham o mesmo dia:

| Caminho | Hash | Concluído |
|---|---|---|
| `~/Documentos/tcc/output_files/` | `178ff65e…` | 08/09 **15:29** |
| `~/Documentos/morphe/tcc/output_files/` | `92a5dc35…` | 08/09 **16:53** |

**O que funciona é o das 16:53**, de `~/Documentos/morphe/tcc`. O das 15:29
compila, sintetiza, fecha timing, é aceito pelo programador e levanta `done` —
e não computa nada.

O commit `3cc794f` versionou o errado por isso. Um manifesto de sha256 prova
que os bytes chegaram íntegros, mas **não diz de qual diretório eles saíram**.
Por isso o `PROVENIENCIA.sha256` passou a registrar máquina e caminho de origem
no cabeçalho.

**How to apply:** antes de gerar qualquer manifesto, rode `pwd` e confira que
está em `~/Documentos/morphe/tcc`.

## 13. O tempo de resposta é o indicador de saúde do core

Uma convolução de 1024×1024 executa ~8,4 milhões de ciclos a 50 MHz, ou seja
**~168 ms**. Medido de ponta a ponta pelo cliente: **213,9 ms**.

Se a resposta vier **muito abaixo disso**, o core não computou, mesmo que o
`done` suba e o servidor logue `CONV OK`. Com o bitstream defeituoso das 15:29
o `done` subia em **3,3 ms** — cerca de 50× rápido demais. A FSM percorria os
2047 valores de `n` sem multiplicar nada e sem escrever a memória de saída.

Este é o único sintoma que denuncia um bitstream ruim. Nenhuma verificação
estática pega: as fontes RTL e o `soc_system.qsys` dos dois builds são **byte a
byte idênticos** — a diferença está só na compilação, provavelmente
resultados intermediários velhos em `db/`. Ao suspeitar, recompile do zero.

## 14. O que o `gen_hps_header.py --check` prova, e o que não prova

Ele prova que `C/hps_0.h` corresponde ao `Quartus/soc_system.sopcinfo`
versionado ao lado. **Não** prova que o `.sof` foi compilado a partir desse
projeto.

Em 2026-09-09 o `--check` passou com folga enquanto o sistema devolvia zeros,
porque os dois builds do mesmo dia têm o mesmo mapa de endereços — o
`hps_0.h` regenerado a partir do `.sopcinfo` correto saiu **idêntico** ao
anterior. O `--check` continua sendo o primeiro teste a rodar, mas passar nele
não encerra o diagnóstico.

## 15. Como diagnosticar direto na memória, sem o servidor

Quando o resultado sai zerado, o teste que separa hardware de software é
escrever e ler `/dev/mem` na mão. Endereços absolutos, retirados do
`.sopcinfo`:

| Sinal | Endereço |
|---|---|
| `conv1d_yn` | `0xC0012000` |
| `conv1d_hn` | `0xC0016000` |
| `conv1d_xn` | `0xC0017000` |
| `conv1d_done` | `0xFF200030` |
| `conv1d_start` | `0xFF200040` |
| `sysid_qsys` | `0xFF210000` |

Roteiro que resolveu o caso de 2026-09-09:

1. Preencher `yn` inteira com um marcador (`0xA5A5A5A5`) antes de disparar.
   Se o marcador sobreviver, o core **não escreveu** — é diferente de ter
   escrito zeros.
2. Escrever em `xn[0]`, `xn[127]` e `xn[1023]` e reler. Confirma se o bitstream
   carregado tem as memórias de 1024 ou as de 128.
3. Ler `start` e `done` **em repouso**. `done=1` parado é normal: a FSM termina
   em `done <= 1'b1` e segura até o próximo pulso. Sob reset ela iria para
   `done <= 0`.
4. Pulsar `start` (0, espera, 1 — o `conv1d.v` tem detector de borda) e
   **cronometrar** até `done` subir. É o item 13.
5. Anotar o `sysid`: `id` e `timestamp` mudam a cada *Generate* do Platform
   Designer, então servem de impressão digital do bitstream carregado.

Compile a sonda com as mesmas flags do Makefile do projeto, senão falta
`-std=gnu99` e `-lrt`:

    gcc -O2 -std=gnu99 -D_GNU_SOURCE -o probe probe.c -lrt

Rode com o `morphe_server` **parado**, senão os dois disputam o mesmo core.

## 16. O teste 4 do `morphe_ping.py` está quebrado

`Quartus/morphe_ping.py:185` chama `build_fft_request(x, DTYPE_FLOAT32)` com
dois argumentos, mas a assinatura em `Python/morphe_protocol.py:135` é
`build_fft_request(x_float)`, com um só — a FFT sempre codifica em Q15.8, e o
parâmetro de dtype saiu da API sem que a ferramenta de teste acompanhasse.

A falha é da ferramenta, não do sistema: com o bitstream correto, a FFT
funciona normalmente pela interface gráfica.

## 17. A IFFT: validada em hardware em 10/09/2026

Escrita e validada em 10/09/2026, branch `estagio/v1.2-ifft`, mesclada em
`estagio/v1.1-1024pontos`.

Nao houve mudanca de RTL e nada foi resintetizado. O caminho ja existia
desligado: o IP foi gerado bidirecional
(`Quartus/fft_core/fft_core.xml:602`), o `fft_wrapper.v` recebe o bit
`inverse` (:21), trava ele na borda de subida do `start` (:133) e entrega ao
IP (:298), e existe um PIO de 1 bit `fft_inverse` (`soc_system.qsys:703`,
`ghrd_top.v:574` e `:706`) em `FFT_INVERSE_BASE 0x70`. O servidor escrevia
zero nesse PIO desde sempre.

### O que foi medido na DE1-SoC

`testa_bit_inverse.py`, com o servidor em `MORPHE_FFT_INVERSE=1`:

| hipotese                          | erro relativo |
|-----------------------------------|---------------|
| DFT direta (bit morto)            | 2,0e+00       |
| IDFT normalizada (IP aplica 1/N)  | 1,0e+03       |
| **IDFT sem normalizar**           | **3,1e-04**   |

`testa_ifft_roundtrip.py`, zero falhas: delta espectral 3,1e-05; ida e volta
9,5e-04 na parte real com 6,3e-04 de vazamento imaginario; ganho por minimos
quadrados 1,0002.

Contra a IDFT do professor (`DSPFinal/idft.m` no MATLAB R2024b), com um
espectro de 1024 bins:

| comparacao                        | erro relativo | SNR      |
|-----------------------------------|---------------|----------|
| `idft.m` (Sanca) x `np.fft.ifft`  | 7,9e-14       | 261,0 dB |
| IFFT na FPGA x `np.fft.ifft`      | 2,5e-05       | 94,4 dB  |
| IFFT na FPGA x `idft.m`           | 2,5e-05       | 94,4 dB  |

O `idft.m` usa a convencao com 1/N, a mesma do NumPy -- terceiro caminho
independente confirmando o `IFFT_HW_GAIN`.

### `IFFT_HW_GAIN` = `1.0 / FFT_N`, medido

O IP NAO aplica o fator 1/N da IDFT: a saida dele e N vezes a transformada
inversa matematica. Para `x` real a IDFT vale `conj(DFT(x))/N`, ou seja,
magnitude N vezes menor que a DFT -- e o que voltou da placa tem a MESMA
magnitude (`|Y|/|DFT(x)| = 1,00031`). O cliente aplica o fator no
`decode_ifft_response`.

Cuidado ao reler esse numero: a primeira versao do `testa_bit_inverse.py`
comparava contra `np.fft.fft` e imprimia a conclusao invertida, dizendo que o
IP ja aplicava o 1/N. A logica agora testa as tres hipoteses da tabela acima
e elege a de menor erro relativo ao pico de cada uma.

### A inversa e mais limpa que a direta, e o motivo importa

Medido com o mesmo sinal: FFT direta 43,9 dB de SNR contra 94,4 dB da
inversa. Nao e o hardware -- e o uso da faixa do Q15.8.

O `build_ifft_request` normaliza o espectro para encostar no teto da faixa
antes de codificar e desfaz a escala na volta (a transformada e linear, entao
isso e exato). Precisa fazer isso porque `X[k]` pode ser ate N vezes maior
que o `x[n]` que o gerou e, ao mesmo tempo, os bins pequenos somem abaixo da
resolucao de 1/256.

A FFT direta nao faz nada disso: manda `x[n]` como esta. Um sinal de
amplitude 3 numa faixa que vai a 32768 desperdica cerca de 13 bits. **A mesma
normalizacao aplicada a FFT direta recuperaria boa parte dos 50 dB de
diferenca** -- nao foi feito.

### O que continua valendo

O IP da FFT e licenciado por avaliacao: o `.sof` em uso e o
`soc_system_time_limited.sof` e o processo do `quartus_pgm` precisa ficar
aberto no prompt `Please enter i for info and q to quit`. Interromper comeca
a contagem de 1 h. A IFFT herda essa amarra, nao cria uma nova.

O erro do ida-e-volta nunca vai a zero: o piso e o Q15.8 do espectro, na
ordem de 1e-3 relativo.

`C/morphe_server_handling_sigs.c` e uma copia antiga do servidor, que o
Makefile nao compila e que **nao** recebeu a IFFT. Se ainda serve para
alguma coisa, precisa decidir se volta a ser o principal ou se sai.
