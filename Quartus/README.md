# Morphe — DSP Toolkit para DE1-SoC

Suite de software para geração, processamento e visualização de sinais DSP
acelerados na FPGA da DE1-SoC. O cliente roda no PC (Python/Tkinter) e
conversa com um servidor C no HPS via protocolo TCP binário.

## Estrutura

```
morphe_app/        cliente Python/Tkinter (roda no PC)
hps_server/        servidor C (roda no HPS — produção — ou no PC — teste)
tests/             testes unitários e end-to-end
morphe_ping.py     ferramenta CLI de bring-up/diagnóstico
```

## Operações suportadas

| Operação    | Hardware        | Formato interno   | Origem do resultado |
|-------------|-----------------|-------------------|---------------------|
| Gerador     | —               | float/int32       | calculado no cliente |
| Convolução  | conv1d FPGA     | **Q15.16**        | FPGA via TCP        |
| FFT         | FFT IP Intel    | int8 com BFP      | FPGA via TCP        |

### Convolução em Q15.16 (transparente)

A conv1d da FPGA é nativamente Q15.16 (1 bit sinal + 15 bits inteiros +
16 bits fracionários). O cliente Python converte automaticamente:

```
UI gera sinal float → float_to_q1516() → int32 Q15.16 → TCP → FPGA
                                                                ↓
UI mostra float ← q1516_to_float() ← int32 Q15.16 ← TCP ← FPGA
```

Usuário nunca vê Q15.16. Escolhe `int32` ou `float32` só para decidir
como o **gerador** discretiza o sinal (ex: uma senóide em int32 vai ser
arredondada pra inteiros antes de virar Q15.16). A faixa efetiva de
valores é [-32768.0, +32767.999...] com resolução ~1.5×10⁻⁵; valores
fora da faixa disparam aviso de saturação na UI.

### FFT com BFP (int8 × 2^exp)

O FFT IP devolve cada bin como `int8 × 2^exponent`. O servidor no HPS
aplica o scaling e envia ao cliente já como `float32 complex` — o
cliente não precisa saber de BFP.

## Como rodar

### 1. Cliente no PC

```bash
cd morphe_app/
pip install -r requirements.txt
# No Ubuntu, se tkinter não estiver instalado: sudo apt install python3-tk
python morphe_app.py
```

Abre uma janela-hub com 3 botões (Gerador, Convolução, FFT).

### 2. Desenvolvimento sem hardware (recomendado inicialmente)

Mantém o **Modo Simulação** ligado no painel TCP. O cliente calcula
as respostas localmente via numpy. Útil pra testar UI e ver a forma
dos sinais antes de ter o HPS configurado.

Alternativa mais realista: compile o testserver e rode no próprio PC.

```bash
cd hps_server/
make             # compila morphe_server + morphe_testserver
./morphe_testserver 5000
```

No cliente: desmarque "Modo Simulação", host=`127.0.0.1`, porta=5000.

### 3. Produção no HPS

Com as chaves SSH configuradas, tem um script pra automatizar:

```bash
cd hps_server/
./deploy.sh root@<ip-do-hps>
# copia arquivos, compila no HPS. Se compilar sem erro:
ssh root@<ip-do-hps>
cd morphe/ && sudo ./morphe_server 5000
```

Ou manualmente:

```bash
scp hps_server/morphe_server.c \
    hps_server/morphe_protocol.h \
    hps_server/Makefile \
    hps_server/hps_0.h \
    hps_server/address_map_arm.h \
    root@<ip-do-hps>:morphe/

ssh root@<ip-do-hps>
cd morphe/
make morphe_server
sudo ./morphe_server 5000
```

No cliente: desmarque "Modo Simulação", host=`<ip-do-hps>`, porta=5000.

### 4. Validar bring-up com `morphe_ping`

Antes de abrir a UI, vale rodar um ping pra garantir que tudo responde:

```bash
python3 morphe_ping.py <ip-do-hps>
python3 morphe_ping.py 127.0.0.1 5000     # contra testserver local
```

Roda 4 testes em ordem, com saída colorida e hints por erro:

1. **TCP reachable** — porta aceita conexão
2. **Magic MRPN** — servidor fala Morphe
3. **Conv com δ[n]** — envia `h = impulso`, verifica `y == x` (testa pipeline Q15.16 inteiro)
4. **FFT com δ[n]** — verifica que espectro do impulso é plano

Se 1 ou 2 falham → problema de rede/servidor. Se só 3 ou 4 falham → problema no hardware ou no mapeamento de memória.

## Testes

```bash
cd tests/

# Testes do núcleo + protocolo (sem precisar de hardware nem servidor C)
python3 test_all.py

# Teste Q15.16 isolado (sobe o testserver C automaticamente)
python3 test_q1516.py

# Teste end-to-end completo (7 cenários)
python3 test_e2e.py

# Teste unitário do wire format em C
cd ../hps_server/
make test
```

## Protocolo Morphe-TCP (resumo)

Tudo big-endian. Cabeçalho fixo de 20 bytes + payload variável. Uma
operação por conexão (abrir, request, response, fechar).

**Request** — cliente envia:

```
magic 'MRPM' | version | opcode | dtype | flags | n_x | n_h
     4 bytes    2 B       2 B      2 B     2 B    4 B   4 B
```

Depois, para CONV envia `n_x` amostras de x seguidas de `n_h` amostras
de h. Para FFT envia só `n_x` amostras.

**Response** — servidor envia:

```
magic 'MRPN' | version | opcode | dtype | status | n_out | extra
     4 bytes    2 B       2 B      2 B     2 B     4 B    4 B
```

Depois o payload. Para CONV: `n_out` amostras no dtype espelhado. Para
FFT: `n_out` pares (re, im) em float32. Para erro: `n_out` bytes de
texto UTF-8.

Detalhes completos no cabeçalho de `morphe_protocol.h`.

## Limites do hardware atual

| Operação | Limite                  | Motivo                         |
|----------|-------------------------|--------------------------------|
| FFT      | N = 64                  | FFT IP configurado em N=64     |
| CONV     | n_x ≤ 128, n_h ≤ 128    | SRAMs de 128 × int32           |
| CONV y   | n_out ≤ 255             | SRAM de saída 255 × int32      |
| CONV     | valores ∈ [-32768, +32768) | faixa Q15.16                |

## Arquivos por módulo

### morphe_app/
- `morphe_app.py` — janela-hub com botões
- `dsp_core.py` — geradores, operações, quantização, Q15.16, I/O .mrph
- `signal_panel.py` — widget reutilizável de geração
- `signal_generator_window.py` — tela do gerador (com operações no tempo)
- `conv_window.py` — convolução via FPGA (Q15.16 transparente)
- `fft_window.py` — FFT via FPGA
- `tcp_panel.py` — configuração de conexão + modo simulação
- `morphe_protocol.py` — protocolo binário do lado cliente

### hps_server/
- `morphe_protocol.h` — constantes do protocolo em C
- `morphe_server.c` — servidor de produção (acessa FPGA via /dev/mem)
- `morphe_testserver.c` — servidor de teste (calcula em software)
- `Makefile` — build com suporte a cross-compile
- `deploy.sh` — script para enviar + compilar no HPS via SSH
- `test_wire.c` — teste unitário do wire format

### tests/
- `test_all.py` — testes do protocolo puro + SimClient
- `test_q1516.py` — testes Q15.16 unitários + TCP via testserver
- `test_e2e.py` — 7 cenários end-to-end via testserver C
- `test_cross_python_c.py` — verifica byte-a-byte Python ↔ C
