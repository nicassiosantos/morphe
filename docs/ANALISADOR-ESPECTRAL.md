# Analisador espectral: como funciona, do PC à FPGA

Este documento segue um quadro do analisador espectral do começo ao fim: do clique em
**Iniciar** até o espectro aparecer na tela. Passa por todas as camadas, cada uma na sua
seção:

1. **o programa em Python** (PC): a janela, a captura, a janela de análise, a FFT longa;
2. **o protocolo TCP** entre o PC e a placa;
3. **o servidor em C** (HPS, o ARM da DE1-SoC): recebe os pedidos e comanda a FPGA;
4. **o hardware na FPGA** (Verilog + Platform Designer): o controlador do ADC e o
   wrapper da FFT.

Cada afirmação aponta para o arquivo e a linha de onde saiu (branch `estagio/v1.8-codec`,
14/10/2026). As medidas citadas estão no `DIARIO.md` e no `PRECISAO-NUMERICA.md`.

---

## 0. A visão geral

```
 PC (Python)                         placa DE1-SoC
 ───────────                         ──────────────────────────────────────────────
                                      HPS (ARM, Linux)          FPGA (Cyclone V)
 analisador_window.py                 morphe_server.c
  │                                   │
  │ 1. OP_ADC (n, divisor, config) ──►│ escreve PIOs ─────────► adc_captura.v
  │                                   │ start=1                  │ CONVST/SCLK/SDI/SDO
  │                                   │                          │   ⇅  LTC2308 (ADC)
  │                                   │ espera done ◄──────────  │ grava na RAM adc_buf
  │ ◄── n códigos int32 ──────────────│ lê adc_buf
  │
  │ 2. no PC: volts, tira DC, janela, escala para Q15.8
  │
  │ 3. OP_FFT (1024 × Q15.8) ────────►│ escreve fft_xn_re/imag ► fft_wrapper.v
  │                                   │ start=1                  │ lê SRAM → IP FFT
  │                                   │ espera done ◄──────────  │ IP FFT → grava SRAM
  │ ◄── 1024 complexos float32 ───────│ lê fft_yn + expoente BFP
  │
  │ 4. no PC: desfaz a escala, |X|/ganho → volts de pico, pico, compara com NumPy
  │ 5. desenha; volta ao passo 1 até Parar
```

Pontos que valem para tudo o que vem depois:

- **Captura e FFT são dois pedidos separados**, cada um numa conexão TCP própria. O
  servidor atende uma conexão por vez; entre um quadro e o próximo, outro aluno pode usar
  a mesma placa.
- **Quem calcula a FFT é a FPGA**, com o IP FFT da Intel (1024 pontos, ponto flutuante
  em bloco). O PC só prepara o sinal e interpreta o resultado. O NumPy refaz a mesma
  conta só para mostrar quanto as duas concordam.
- **Acima de 1024 pontos** (4096 e 16384), o PC divide a FFT em várias FFTs de 1024 na
  placa e as junta pelo algoritmo de quatro passos. O resultado é exato, sem aproximação.

---

## 1. O programa em Python

### 1.1 Onde está cada coisa

| arquivo | papel no analisador |
|---|---|
| `Python/morphe_app.py:110` | botão "Analisador espectral (ADC → FFT na FPGA)" na tela inicial |
| `Python/analisador_window.py` | a janela: opções, laço de quadros, contas do espectro, gráficos |
| `Python/aquisicao.py` | captura pelo ADC: palavra de configuração, fs, volts, saturação |
| `Python/blocos.py` | `FftPlaca` (uma FFT na placa) e `fft_longa` (quatro passos) |
| `Python/morphe_protocol.py` | monta e decodifica as mensagens binárias; `TcpClient` |
| `Python/dsp_core.py` | codificação Q15.8 (`fft_q1508_encode`), constantes, `.mrph` |
| `Python/morphe_config.py` | os mesmos limites do `C/morphe_config.h` (1024, 32768, 50 MHz...) |

### 1.2 As opções da janela

`AnalisadorWindow._build_sidebar` (`analisador_window.py:225`):

| opção | o que faz |
|---|---|
| **Modo / Canal** | simples (CH0..CH7 contra o terra, 0 a 4,095 V) ou diferencial (CH0−CH1 ... CH6−CH7, −2,048 a +2,047 V) |
| **fs (Hz)** | taxa de amostragem pedida, de 1 kHz a 200 kHz |
| **Pontos** | 1024 (1 FFT na FPGA), 4096 (4 FFTs) ou 16384 (16 FFTs) |
| **Janela** | Hann, Blackman-Harris, Flat-top (medir amplitude), Retangular |
| **Média** | sem média, média de potência de 4 ou 16 quadros, retenção de pico |
| **Tirar o nível DC** | subtrai a média do quadro antes da FFT |
| **Mostrar a fase** | terceiro gráfico, ∠X(f) |
| **Stem** | desenha as amostras como hastes, sem ligar os pontos |

O texto de informação (`_atualiza_info`, linha 342) já mostra a **fs real**, a resolução
em frequência (fs/N) e a duração do quadro (N/fs), porque a fs pedida raramente é a que
o hardware usa (ver 1.4).

### 1.3 O laço de quadros

`_on_iniciar` (`analisador_window.py:368`) cria o cliente TCP a partir do painel de
conexão e dispara uma **thread de trabalho** (`worker`, linha 395). A thread faz, em
laço, até o evento `parar` ser acionado:

```python
cap = aq.capturar(client, n, fs, modo, canal, guardar=False)    # pedido 1: ADC
q = processar_quadro(cap.volts, cap.fs, janela, tirar_dc, fft)   # pedido(s) 2: FFT
self._novo = q                                                   # entrega à tela
```

A tela **não** é desenhada pela thread: o Tk só pode ser usado pela thread principal.
Por isso existem dois ritmos independentes:

- a thread produz quadros tão rápido quanto a placa e a rede permitem, e deixa sempre
  só o **último** em `self._novo` (protegido por `self._trava_q`);
- a thread do Tk confere a cada `TELA_MS = 50 ms` (`_tela`, linha 504) se há quadro
  novo e, se houver, acumula a média e redesenha.

Se a tela for mais lenta que a placa, quadros intermediários são simplesmente pulados no
desenho; a análise não atrasa. As opções que a thread lê (janela, tirar DC) ficam num
dicionário `self._cfg`, copiado pela thread do Tk em `_zera_media` (linha 359): variáveis
do Tk não podem ser lidas de outra thread.

### 1.4 A captura (`aquisicao.capturar`)

`aquisicao.py:139`. Três contas acontecem antes de qualquer byte sair do PC:

**a) A fs que o hardware realmente usa.** O FPGA conta ciclos de um relógio de 50 MHz;
o período de amostragem tem que ser um número inteiro de ciclos, o `divisor`:

```python
divisor = round(50e6 / fs)        # divisor_para, linha 86; faixa 250..50000
fs_real = 50e6 / divisor          # fs_de, linha 93
```

Pedir 44 100 Hz dá divisor 1134 e fs real de 44 091,7 Hz. **Todas as contas seguintes
usam a fs real**, não a pedida; é ela que aparece no eixo de frequência.

**b) A palavra de configuração do LTC2308** (`palavra_config`, linha 63): 6 bits
`S/D O/S S1 S0 UNI SLP` que escolhem canal, modo simples/diferencial e unipolar/bipolar.
No modo simples o canal é codificado como `{S1, S0, O/S}` (tabela 1 da folha de dados).
`SLP` fica sempre 0: dormir desliga a referência interna, que leva 200 ms para voltar.

**c) O tempo de espera.** A captura leva `(n+1) · divisor / 50 MHz` segundos (o
primeiro quadro é descartado, ver 4.2). O cliente usa um timeout de pelo menos essa
duração + 10 s: 32 768 amostras a 1 kHz levam 33 s, e o padrão do painel TCP é 10 s.

A resposta são **códigos inteiros** do conversor: 0..4095 no modo simples, −2048..2047
no diferencial (o servidor já estendeu o sinal). Com a referência interna de 4,096 V,
**1 código = 1 mV**, e a conversão para volts é só `codigos * 0.001`. O cliente confere
que voltaram exatamente `n` amostras e que o divisor usado (campo `extra` da resposta) é
o pedido. `saturou()` (linha 357) avisa se algum código bateu no limite da faixa.

### 1.5 O processamento de um quadro (`processar_quadro`)

`analisador_window.py:120`. É uma função pura, sem Tk: recebe os volts e uma função
`fft`, e devolve um dicionário com tudo o que a tela mostra. Os testes de bancada a
chamam com `np.fft.fft` no lugar da placa.

**Passo 1 — nível DC e janela.**

```python
dc = mean(x)
x_env = (x - dc) * w        # se "Tirar o nível DC" estiver marcado
```

O sinal do ADC no modo simples nunca é negativo: um gerador com offset de 2 V gera uma
raia enorme em f = 0 que, vazando pela janela, esconderia os tons baixos. Tirar a média
remove essa raia.

As janelas (`janela`, linha 109) são **periódicas** (soma exata conhecida): Hann
(`np.hanning(n+1)[:n]`), Blackman-Harris de 4 termos, flat-top de 5 termos e retangular.
A escolha é um compromisso (comentário da linha 48):

| janela | erro máximo de amplitude (tom entre dois bins) | uso |
|---|---|---|
| Retangular | até 3,9 dB a menos | só para sinais com número inteiro de períodos no quadro |
| Hann | até 1,4 dB | uso geral |
| Blackman-Harris | até 0,8 dB, lóbulos laterais abaixo de −92 dB | separar tons fracos de fortes |
| Flat-top | < 0,02 dB | **medir amplitude**; pico mais largo |

**Passo 2 — a FFT (na FPGA).** `X = fft(x_env)`, com o tempo medido (`t_fft`). A função
`fft` foi montada em `_on_iniciar` (linha 389):

```python
fft_placa = blocos.FftPlaca(client, normalizar=True)
def fft(x):
    return blocos.fft_longa(x, fft_placa) if x.size > 1024 else fft_placa(x)
```

Os detalhes estão em 1.6 e 1.7.

**Passo 3 — de |X[k]| para volts de pico.** Uma senoide de amplitude A janelada por `w`
produz, no bin dela, `|X| = A · Σw / 2`. Então:

```python
ganho = sum(w) / 2
amp = abs(X) / ganho        # volts de pico em cada bin
amp[0] /= 2                 # no DC o ganho é Σw inteiro, não metade
```

O espectro mostrado é **completo, de 0 a fs** (os N bins), com uma linha pontilhada em
fs/2: a metade de cima é o espelho da de baixo (sinal real ⇒ X[N−k] = X[k]*), e um tom
em f aparece também em fs − f, com a mesma amplitude. O eixo vertical é **linear, em
volts de pico**, por decisão registrada em `DECISOES.md` (01/10).

**Passo 4 — o pico.** Procurado só na metade de baixo, ignorando os `BINS_DC = 3`
primeiros bins (o que sobra do DC depois da janela). A frequência é refinada por uma
**parábola** nos três bins em volta do máximo, em dB (linha 156): o lóbulo de uma
janela é quase parabólico em escala logarítmica, e isso corrige o erro de até meio bin
do índice inteiro. O deslocamento é limitado a ±0,5 bin, porque perto do DC ou só com
ruído a parábola pode apontar longe.

**Passo 5 — a prova.** O NumPy calcula `np.fft.fft(x_env)` do **mesmo** vetor enviado à
placa, e a tela mostra

```
SNR = 20·log10( ‖X_numpy‖ / ‖X_fpga − X_numpy‖ )     em dB
```

como "FPGA × NumPy". Medido na placa 1 em 30/09: **97,6 dB** em todos os quadros com
1024 pontos e 97,4 a 97,8 dB com 4096. É a confirmação, a cada quadro, de que o espectro
saiu mesmo da FPGA e com que precisão.

### 1.6 Uma FFT de 1024 na placa (`FftPlaca`)

`blocos.py:106`:

```python
x = dsp.pad_zeros_to(x, 1024)
req, escala = build_fft_request(x, normalizar=True)
return decode_fft_response(self.client.request(req), escala)
```

O hardware recebe números em **Q15.8**: inteiros de 24 bits com sinal, 8 deles
fracionários. Faixa ±32768, passo 1/256. Um sinal do ADC tem no máximo ±2 V; mandado
como está, usaria só uns 10 dos 24 bits, e o erro de arredondamento seria enorme em
comparação com o sinal.

Por isso a **normalização** (`escala_para_q1508`, `morphe_protocol.py:198`):

```python
escala = 0.98 * 32767.996 / max(|x|)    # encosta o pico em 98 % do teto
q = round(x * escala * 256)             # fft_q1508_encode, saturando em 24 bits
```

e, na volta, `X = X_placa / escala` (`decode_fft_response`, linha 450). A conta é exata,
porque a DFT é linear: `DFT(s·x)/s = DFT(x)`. O que muda é só o erro de quantização,
que cai 6,02 dB por bit de faixa recuperado, até o teto de ~92 dB do IP
(`PRECISAO-NUMERICA.md`, seção 3). Cada bloco é normalizado separadamente.

Cada amostra Q15.8 vai num `int32` big-endian, com os 8 bits de cima repetindo o bit de
sinal (o hardware só olha os 24 de baixo).

### 1.7 FFT de 4096 e 16384 pontos (`fft_longa`)

`blocos.py:241`. Uma DFT de N = 1024·M pontos pelo algoritmo de **quatro passos**
(Cooley-Tukey com raiz M):

```
1. separa x em M subsequências decimadas:  x_n1[m] = x[n1 + M·m],  n1 = 0..M-1
2. FFT de 1024 de cada uma, NA PLACA:      A[n1][k2]           (M pedidos OP_FFT)
3. multiplica pelos fatores de giro:       A[n1][k2] · e^(−j2π·n1·k2/N)
4. FFT de M pontos ao longo de n1, no PC:  X[k2 + 1024·k1]
```

No código, os passos 3 e 4 são duas linhas de NumPy:

```python
giro = np.exp(-2j*np.pi * np.outer(np.arange(M), np.arange(1024)) / N)
return np.fft.fft(A * giro, axis=0).reshape(-1)
```

O trabalho pesado (M FFTs de 1024) é feito na FPGA; o PC faz só M·1024 multiplicações
complexas e 1024 FFTs minúsculas de M pontos. Com 16384 pontos são 16 pedidos à placa
por quadro, o que reduz a taxa de quadros.

### 1.8 A tela: média, pico, fase

- **Média** (`_acumula`, linha 488): sempre sobre a **potência** (`amp²`), nunca sobre
  a amplitude ou o complexo. Média de K quadros = `sqrt(média dos últimos K amp²)`;
  retenção de pico = `sqrt(máximo desde o começo)`. Mudar a janela, o DC ou o tipo de
  média zera o acumulador.
- **Fase** (`fase_visivel`, linha 99): `angle(X)` só nos bins com amplitude ≥ 2 % do
  maior; nos outros, X[k] é ruído e a fase é um número sorteado entre −π e π, por isso
  aparece como lacuna (NaN). A fase é sempre a do quadro atual: cada captura começa num
  ponto diferente da onda, então a média de fase não faz sentido.
- **Medidas do quadro**: pico (Hz e mV), nível DC, tempo de captura, tempo da FFT,
  quadros por segundo, FPGA × NumPy e o aviso de saturação.
- **Salvar quadro (.mrph)** (`_on_salvar`, linha 561): grava o `x_env` (exatamente o
  que foi para a FPGA) e o `X` da placa, no formato que o Comparador abre.

---

## 2. O protocolo entre o PC e a placa

Definido em dois arquivos que espelham um ao outro: `Python/morphe_protocol.py` e
`C/morphe_protocol.h`. TCP, porta 5000, **uma conexão por pedido**, tudo em big-endian.

**Cabeçalho do pedido (20 bytes)**, `struct.pack(">IHHHHII", ...)`:

| campo | tipo | valor |
|---|---|---|
| magic | u32 | `0x4D52504D` ("MRPM") |
| version | u16 | 1 |
| opcode | u16 | 2 = FFT, 7 = ADC (outros: CONV, FIR, IFFT, IIR, PING, ADC contínuo) |
| dtype | u16 | 1 = int32 |
| flags | u16 | ADC: a palavra de 6 bits do LTC2308; FFT: 0 |
| n_x | u32 | ADC: amostras; FFT: 1024 |
| n_h | u32 | ADC: o divisor; FFT: 0 |

**Cabeçalho da resposta (20 bytes)**: magic `0x4D52504E` ("MRPN"), version, opcode
(espelhado), dtype, status (0 = OK), `n_out`, `extra`.

Os dois pedidos do analisador:

| | pedido | resposta |
|---|---|---|
| **OP_ADC** (7) | só o cabeçalho, sem carga | `n` códigos `int32`; `extra` = divisor usado |
| **OP_FFT** (2) | cabeçalho + 1024 `int32` Q15.8 (4 KiB) | 1024 complexos `float32` (re, im intercalados, 8 KiB) |

Em erro, `status ≠ 0` e a carga é a mensagem em texto (`n_out` = bytes). O Python a
transforma em `RuntimeError("erro do servidor: ...")`, que a janela mostra numa caixa
de diálogo. Exemplo: com a FPGA ainda com o bitstream de fábrica, a resposta é status 8,
"FFT: FPGA nao preparada -- rode ./morphe-up.sh nesta placa".

O `TcpClient.request` (`morphe_protocol.py:370`) abre a conexão, desliga o algoritmo de
Nagle (`TCP_NODELAY`, que atrasaria mensagens curtas), envia, lê exatamente 20 bytes de
cabeçalho, calcula o tamanho da carga pelo opcode (FFT: `8·n_out`; ADC: `4·n_out`) e lê
exatamente esse tanto.

---

## 3. O servidor em C (HPS)

`C/morphe_server.c`, um processo só, que roda no Linux do ARM da placa, como root (por
causa do `/dev/mem`).

### 3.1 Como o ARM enxerga a FPGA

O ARM e a FPGA estão no mesmo chip (Cyclone V SoC), ligados por duas **pontes AXI**. Do
lado do ARM, cada memória e cada registrador da FPGA é um **endereço físico**.
`fpga_init` (linha 413) abre `/dev/mem` e mapeia duas janelas no espaço do processo com
`mmap`:

| janela | endereço físico | o que tem dentro (offsets de `C/hps_0.h`) |
|---|---|---|
| ponte HPS→FPGA | `0xC0000000` | as RAMs: `fft_xn_re` 0x1A000, `fft_xn_imag` 0x1B000, `fft_yn_re` 0x18000, `fft_yn_imag` 0x19000 (4 KiB cada = 1024 int32); `adc_buf` 0x20000 (128 KiB = 32 768 int32) |
| ponte leve (LW) | `0xFF200000` | os PIOs (registradores de 1 a 32 bits): `fft_wrapper_start` 0x80, `fft_wrapper_done` 0x60, `fft_inverse` 0x70, `fft_bfp_exponent` 0x50; `adc_start` 0xD0, `adc_done` 0xE0, `adc_config` 0xF0, `adc_divisor` 0x100, `adc_namostras` 0x110, `adc_contador` 0x120 |

Depois disso, escrever num registrador da FPGA é uma atribuição de ponteiro em C:
`*g_pio_adc_divisor = divisor;`. Os ponteiros são `volatile`, para o compilador não
eliminar nem reordenar os acessos.

Os endereços em `hps_0.h` são gerados a partir do projeto do Platform Designer
(`Quartus/gen_hps_header.py`). **Se o bitstream muda de mapa, o servidor tem que ser
recompilado com o `hps_0.h` novo.**

### 3.2 Proteções antes de tocar na FPGA

Acessar, pela ponte, um endereço que a FPGA não implementa **trava o barramento inteiro
do ARM**, sem timeout: a placa some da rede. Isso aconteceu (21/09), quando o servidor
subia no boot com a FPGA ainda com o bitstream de fábrica. Daí duas proteções:

- `fpga_preparada()` (linha 495): só deixa uma operação seguir se o arquivo
  `/var/run/morphe-fpga-preparada` existe. Quem o cria é o `morphe-up.sh`, depois de
  programar o `.sof` do Morphe. Na primeira vez, zera os PIOs de start.
- `adc_recusa()` (linha 1097), só para o ADC: compara o **timestamp do sysid** gravado
  no bitstream (`g_sysid[1]`) com o `SYSID_QSYS_TIMESTAMP` com que o servidor foi
  compilado. Se forem diferentes, o bitstream é outro, e os PIOs do ADC podem nem
  existir. Confere também o divisor (250..50000), o dtype e o bit SLP.

### 3.3 O laço principal

`main` (linha 1566) abre o socket na porta 5000 e entra num laço `accept` →
`serve_connection` → `close`. **Uma conexão por vez**: enquanto uma captura ou FFT
roda, a próxima conexão espera na fila do `listen`. É isso que permite várias pessoas
usarem a mesma placa: cada quadro do analisador são 2 ou mais conexões curtas, e as dos
outros entram entre elas.

`serve_connection` (linha 1524) lê o cabeçalho de 20 bytes, confere magic e versão e
despacha pelo opcode. Em paralelo, uma thread responde na **porta UDP 5001** quem está
usando a placa e qual operação está rodando (`thread_estado`); é o que a tela de
descoberta mostra como "ocupada".

### 3.4 OP_ADC — `handle_adc` (linha 1138)

```c
*g_pio_adc_divisor   = divisor;      // período em ciclos de 50 MHz
*g_pio_adc_namostras = n;
*g_pio_adc_config    = cfg;          // bit 6 = 0: captura única
*g_pio_adc_start = 0; usleep(1); *g_pio_adc_start = 1;   // borda de subida

wait_done(g_pio_adc_done, duracao_ms + 2000);            // polling do PIO done
*g_pio_adc_start = 0;                                     // libera o hardware

for (i = 0; i < n; i++)                                   // lê a RAM pela ponte
    tx[i] = adc_codigo(g_adc_buf[i], bipolar);            // 12 bits → int32
```

- O **aperto de mão** start/done é o mesmo de todos os blocos do Morphe: o HPS sobe
  `start`; o hardware trabalha; sobe `done` e o mantém em 1 até o HPS baixar `start`.
  Assim nenhum dos dois lados perde o evento do outro.
- `wait_done` (linha 529) lê o PIO a cada 50 µs, com timeout.
- `adc_codigo` (linha 1132) pega os 12 bits de baixo da palavra; no modo bipolar
  (`UNI = 0`), estende o sinal do complemento de dois de 12 bits.
- A resposta leva o **divisor no campo `extra`**, para o cliente confirmar a fs.

### 3.5 OP_FFT — `handle_fft` (linha 1375) e `fft_run_block` (linha 1334)

```c
recv_exact(sock, rx_buf, 1024*4);                 // os 1024 int32 Q15.8
decode_samples_to_q1508(rx_buf, 1024, x);         // big-endian → int32, satura em 24 bits
for (i...) { g_fft_xn_re[i] = x[i]; g_fft_xn_imag[i] = 0; }   // entrada real

*g_pio_fft_inverse = 0;                           // ANTES do start: o wrapper o trava na borda
*g_pio_fft_start = 0; usleep(1); *g_pio_fft_start = 1;
wait_done(g_pio_fft_done, 5000);
*g_pio_fft_start = 0;

exp = *g_pio_fft_bfp_exponent & 0x3F;             // expoente de 6 bits, com sinal
for (k...) { re[k] = g_fft_yn_re[k]; im[k] = g_fft_yn_imag[k]; }

escala = 2^(-exp) / 256;                          // desfaz o BFP e o Q15.8
envia (float)re[k]*escala, (float)im[k]*escala    // float32 big-endian
```

O ponto central é o **expoente de ponto flutuante em bloco (BFP)**. O IP da FFT, para
não estourar os 24 bits ao longo dos estágios, divide os dados por 2 sempre que um
estágio cresceria demais, e conta quantas vezes fez isso. Esse número sai junto com o
resultado, num único expoente para o bloco inteiro de 1024 bins. O servidor o lê do PIO
`fft_bfp_exponent` e multiplica a saída por 2^(−exp), recuperando a escala verdadeira.
Depois divide por 256 para tirar o Q15.8 da entrada. O que chega ao Python é a DFT
de `x·escala_python`, em float; o Python divide pela própria escala (1.6).

Cada FFT também grava um arquivo `.mrph` de depuração no disco da placa
(`save_debug_bundle_fft`). Os mais antigos são apagados (`MORPHE_DUMP_MAX`, padrão 100).

---

## 4. O hardware na FPGA

Projeto Quartus em `Quartus/`. O topo é `ghrd_top.v`, que instancia o sistema do
Platform Designer (`soc_system`: HPS, pontes, RAMs on-chip, PIOs) e, ao lado dele, os
blocos próprios do Morphe. Todos rodam no relógio `CLOCK_50` (50 MHz).

### 4.1 As memórias de duas portas

Cada RAM do caminho (`fft_xn_re`, `fft_xn_imag`, `fft_yn_re`, `fft_yn_imag`, `adc_buf`)
é uma memória on-chip de **duas portas**:

- **porta A**, no barramento: o ARM a lê e escreve pela ponte, como em 3.1;
- **porta B**, exportada para o `ghrd_top.v`: ligada diretamente ao bloco de hardware.

É por elas que os dados passam entre o software e o hardware, sem DMA: o ARM escreve a
entrada na porta A, o hardware a lê pela porta B, escreve o resultado pela porta B de
outra RAM, e o ARM o lê pela porta A.

### 4.2 O controlador do ADC — `Quartus/adc_captura.v`

Instanciado em `ghrd_top.v:604`, com os pinos `ADC_CONVST`, `ADC_SCLK`, `ADC_DIN` e
`ADC_DOUT` ligados ao LTC2308 da placa, e a porta B da RAM `adc_buf` (2¹⁵ palavras).

**Por que um controlador próprio** (cabeçalho do arquivo e `docs/ADC.md`): o IP do
University Program converte sem parar, no ritmo dele, e entrega só o último valor de
cada canal. Ler esse valor a cada 1/fs deixa o instante da amostra incerto em alguns
microssegundos, e essa incerteza vira ruído que cresce com a frequência do sinal. Aqui,
**cada conversão começa exatamente no ciclo em que o contador de período zera**. O
instante de amostragem é fixado pelo hardware, com a incerteza de um ciclo de 50 MHz
(20 ns). Isso é essencial para um analisador espectral: o espaçamento uniforme das
amostras é o que a DFT supõe.

**Máquina de estados** (`S_IDLE → S_PREP → S_CAPT → S_DONE`):

- `S_IDLE`: na borda de subida de `start`, trava `divisor` (no mínimo 250), `n_amostras`,
  `config_adc` e `continuo`; zera índice e contador.
- `S_PREP`: espera 16 ciclos, para garantir o tempo de aquisição do conversor.
- `S_CAPT`: um **quadro por amostra**, contado pela variável `fase`, de 0 a
  `divisor − 1`:

```
 fase 0            CONVST ↑    início da conversão  ← instante da amostra
 fase 96           CONVST ↓    (1,92 µs, mais que o tempo máximo de conversão)
 fase 98..145      12 pulsos de SCLK a 12,5 MHz:
                     - lê B11..B0 do SDO (bit mais significativo primeiro)
                     - nos 6 primeiros, envia pelo SDI a palavra de configuração
 fim da leitura    grava a amostra na RAM (endereço idx), contador += 1
 fase divisor−1    volta a 0: próximo quadro
```

  Com divisor 250 (200 kHz), o quadro inteiro (~146 ciclos) cabe com folga; a
  verificação está no `initial` do módulo.

- `S_DONE`: sobe `done` e espera o HPS baixar `start`.

**O primeiro quadro é descartado.** No LTC2308, a palavra de configuração enviada
durante uma leitura vale para a conversão **seguinte**. A conversão do quadro 0 usou a
configuração anterior (talvez outro canal), então são feitas n+1 conversões e a
primeira não é gravada (`descartar`).

A amostra vai para a RAM crua, nos 12 bits de baixo de uma palavra de 32. O sinal do
modo bipolar é estendido pelo servidor (3.4), não aqui.

**Modo contínuo** (bit 6 de `adc_config`, usado pela janela de Aquisição, não pelo
analisador): a RAM vira um buffer circular e o `contador` diz quantas amostras já foram
gravadas, para o servidor copiar as novas enquanto a captura segue.

### 4.3 O wrapper da FFT — `Quartus/fft_wrapper.v`

Instanciado em `ghrd_top.v:700`. Faz a ponte entre as quatro RAMs (portas B) e o **IP
FFT da Intel** (`fft_core`, gerado no Platform Designer: `Quartus/fft_core.qsys`).

**Configuração do IP** (do `.qsys`): 1024 pontos, arquitetura *Buffered Burst*,
entrada de 24 bits, fatores de giro (*twiddles*) de 18 bits, representação **Block
Floating Point**, ordem natural na entrada e na saída, bidirecional (o mesmo IP faz a
IFFT com `inverse = 1`).

O IP fala **Avalon-ST**: um fluxo com `valid`/`ready` dos dois lados e marcas de início
(`sop`) e fim (`eop`) de pacote. O wrapper converte "uma RAM endereçável" em "um fluxo
de 1024 amostras" e o contrário. Sua máquina de estados:

```
S_IDLE        espera a borda de subida de start; trava o bit inverse
  │
  ├─► S_READ_START   pede a amostra feed_addr às RAMs de entrada (re e im)
  │   S_READ_WAIT    espera os controladores de leitura (memory_read_controller.v)
  │   S_FEED_FFT     sink_valid=1, sop na amostra 0, eop na 1023;
  │                  espera sink_ready do IP; próxima amostra
  │   ... 1024 vezes
  │
  ├─► S_RECV_WAIT    source_ready=1; espera source_valid do IP
  │                  estende o sinal de 24 → 32 bits;
  │                  no sop, guarda source_exp (o expoente BFP)
  │   S_WRITE_START  escreve o bin recv_addr nas RAMs de saída
  │   S_WRITE_WAIT   espera os controladores de escrita (memory_write_controller.v)
  │   ... 1024 vezes
  │
  └─► S_COMPLETE     done=1 até o HPS baixar start
```

Detalhes que já custaram horas de depuração:

- **`source_ready` é um fio combinacional** (`state == S_RECV_WAIT`), e não um
  registrador. Com o ready oscilando no meio do quadro, a IFFT perdia o fim do pacote e
  o wrapper travava em `S_RECV_WAIT`; toda FFT seguinte dava timeout. A versão correta
  é a do bitstream de 08/09/2026, que só foi versionada em 15/09 (`DIARIO.md`).
- **`inverse` é travado na borda de subida do start.** Por isso o servidor escreve o PIO
  `fft_inverse` **antes** de subir o start (3.5).
- Os 8 bits de cima de cada palavra da RAM de entrada são ignorados: o IP recebe
  `[23:0]`. Por isso o cliente codifica em Q15.8 com o sinal estendido (1.6).

### 4.4 O expoente BFP, do IP até a tela

Para fechar o caminho numérico, um bin X[k] passa por estas escalas:

```
x_env[n] (volts, float64, PC)
  × escala_python                (≈ 32 000 / pico; encosta no teto do Q15.8)
  × 256, arredonda               → inteiro Q15.8 de 24 bits      [PC → fio → RAM]
  IP FFT: DFT com divisões por 2 internas, contadas em exp      [FPGA]
  × 2^(−exp) / 256               → float32                      [servidor C]
  / escala_python                → X[k] na escala de x_env       [PC]
  / (Σw / 2)                     → volts de pico na tela         [PC]
```

O ADC dá ~9 bits efetivos (ENOB 9,03 medido em 07/10, SINAD 56,1 dB). A FFT da placa
concorda com o NumPy a ~97 dB. Portanto **o limite do analisador é o conversor, não a
FFT**: o erro da FPGA fica uns 40 dB abaixo do ruído do próprio sinal.

---

## 5. Tempo de um quadro

Medido na placa 1, do PC Windows, CH0, 10 kHz, 1024 pontos (30/09/2026):

| etapa | tempo |
|---|---|
| captura no ADC | 1025 / 10 000 Hz ≈ 103 ms, mais a rede |
| FFT na FPGA (pedido completo: envio, cálculo, resposta) | 30 a 40 ms |
| resultado | **~5,6 quadros por segundo** |

Os 30 a 40 ms da FFT incluem a codificação no PC, a rede, a cópia pela ponte e a
conversão para float32; o pedido de FFT sozinho, com a placa livre, mede 21 a 25 ms
(`DIARIO.md`, testes do `morphe-up.sh`). O log do servidor separa as partes
(`log_tempos`: `entrada`, `fpga`, `saida`), mas o tempo só do hardware ainda não foi
registrado no diário. A captura, por outro lado, é limitada pela física: N amostras a
fs levam N/fs segundos. Com 16 384 pontos a 1 kHz, um quadro
leva 16 s só para ser capturado.

---

## 6. Limites e cuidados

- **Não há filtro antialiasing** entre o conector J15 e o LTC2308. Qualquer componente
  acima de fs/2 volta como alias, e a tela não tem como distinguir. Escolher fs bem
  acima do dobro da maior frequência presente.
- **Faixa de entrada**: 0 a 4,096 V por pino, em qualquer modo. Tensão negativa pode
  danificar o conversor. Com gerador de funções: offset de ~2 V e no máximo 4 Vpp,
  conferidos no osciloscópio antes de ligar.
- **N máximo** por captura única: 32 768 (tamanho da RAM `adc_buf`). O analisador usa
  até 16 384.
- **fs**: de 1 kHz (divisor 50 000) a 200 kHz (divisor 250). A fs real é 50 MHz dividido
  por um inteiro.
- **Entrada sem nada ligado** dá um sinal que começa em ~2,4 V e decai nas primeiras
  amostras (entrada de alta impedância; `DIARIO.md`, 30/09). Não é defeito do analisador.
- **Placa ocupada**: com várias pessoas na mesma placa, os pedidos se intercalam e a
  taxa de quadros de cada uma cai.

---

## 7. Para seguir no código

| quero entender... | começar por |
|---|---|
| o laço da janela | `Python/analisador_window.py:395` (`worker`) |
| as contas do espectro | `Python/analisador_window.py:120` (`processar_quadro`) |
| a fs e a palavra do ADC | `Python/aquisicao.py:63` e `:86` |
| a normalização Q15.8 | `Python/morphe_protocol.py:198` e `:213` |
| a FFT longa | `Python/blocos.py:241` |
| o despacho no servidor | `C/morphe_server.c:1524` (`serve_connection`) |
| a captura no servidor | `C/morphe_server.c:1138` (`handle_adc`) |
| a FFT no servidor e o BFP | `C/morphe_server.c:1334` (`fft_run_block`) |
| o tempo de amostragem | `Quartus/adc_captura.v`, estado `S_CAPT` |
| a ponte RAM ↔ IP FFT | `Quartus/fft_wrapper.v`, a máquina de estados |
| os endereços | `C/hps_0.h` e `C/address_map_arm.h` |
| precisão numérica | `docs/PRECISAO-NUMERICA.md` |
| o ADC em detalhe | `docs/ADC.md` |
