# Como as requisições chegam às placas

O que existe **hoje** (22/09/2026) entre um cliente e uma DE1-SoC: quem descobre a
placa, quem escolhe qual usar, o que acontece quando duas pessoas pedem ao mesmo tempo,
e onde estão os limites. Escrito a partir do código e das medições, não do que se
pretende ter.

Para **acrescentar** uma placa nova ao laboratório, o procedimento (com as armadilhas já
medidas) está em [`NOVA-PLACA.md`](NOVA-PLACA.md). Para instalar a plataforma numa
estação e operar em turma, em [`../PREPARACAO.md`](../PREPARACAO.md).

---

## As cinco peças

```
 cliente (Tk)                estação                          placa DE1-SoC
 ────────────               ─────────                        ───────────────
 morphe_app.py  ──TCP:5000──────────────────────────────────▶ morphe_server
   │  uma conexão POR OPERAÇÃO                                  │ um cliente por vez
   │                                                            │ listen(fila 4)
   ├─ lê .morphe-estado/placas  (quem já foi preparada aqui)    │
   ├─ OP_PING em cada uma, em paralelo → escolhe a mais rápida  ├─ /dev/mem → FPGA
   └─ se a lista estiver vazia: varredura TCP nas sub-redes     └─ marca: FPGA preparada?

 morphe-up.sh  ──JTAG (quartus_pgm, um tether por cabo)───────▶ bitstream
               ──SSH─────────────────────────────────────────▶ compila, reinicia, marca
```

### 1. O servidor atende **um cliente por vez**

`C/morphe_server.c:1139` é um laço `accept` → `serve_connection` → `close`, sem `fork`
nem thread. Não há fila interna, nem prioridade, nem identificação de quem pediu: a fila
é a do sistema operacional, criada por `listen(srv, 4)` (`morphe_server.c:1135`).

Consequência direta: **duas pessoas na mesma placa não tomam erro — elas esperam.** A
segunda requisição fica no `listen` até a primeira terminar, e a latência de cada uma
soma. Medido em 21/09: convolução de 1024 pontos ≈ **214 ms**, FFT de 1024 ≈ **21 ms**.
Dois clientes disputando a mesma placa veem ~2× isso; seis veem ~5×, conferido em 22/09
(tabela adiante).

**Onde está o limite, medido em 22/09/2026** (`testa_concorrencia.py --modo mesma`):
com **6 clientes simultâneos** na placa 2 não houve uma falha sequer — a latência
mediana foi 604 ms contra 119 ms de placa vazia (**5,1×**), e a pior 1,29 s, que é
exatamente 6 × 215 ms. O `listen(4)` do Linux guarda `backlog + 1 = 5` conexões
esperando, e a sexta é a que está sendo atendida: 6 cabe justo.

O limite começa no **7º cliente simultâneo**, e vale corrigir uma expectativa: no Linux
o excesso **não** vira `ECONNREFUSED`. Com `tcp_abort_on_overflow = 0` (o padrão) o
kernel descarta o SYN calado e o cliente retransmite cerca de um segundo depois — o
sintoma é um pico de latência, não um erro. Só com a fila cheia por tempo demais o
cliente desiste por timeout. **Ainda não medido**: falta rodar com 8 ou 10 clientes.

### 2. O cliente abre uma conexão **por operação**

`Python/morphe_protocol.py:335`: cada operação é um `connect` → envia → lê → `close`.
Não há sessão nem reserva. Por isso duas pessoas em máquinas diferentes funcionam na
prática, intercalando operações de ~200 ms — e por isso ninguém "segura" uma placa: entre
duas operações suas, qualquer outro cliente pode entrar.

### 3. Descoberta: lista local primeiro, varredura depois

- `.morphe-estado/placas` guarda toda placa já preparada **naquele clone** (escrito pelo
  `morphe-up.sh`). `.morphe-estado/placa` guarda a última.
- Com a lista vazia, o cliente varre as sub-redes prováveis por TCP + `OP_PING`
  (`morphe_protocol.py:559` e `:657`): o /24 da placa lembrada, o da própria estação, e
  os 101/102/103 históricos — e **para na primeira que achar**.

**Isto é o que explica o notebook.** O `.morphe-estado` mora na raiz do clone, então um
notebook com seu próprio clone começa sem lista nenhuma: ele varre, acha **uma** placa e
para. A lista é texto puro, um IP por linha — no notebook, escreva-a uma vez:

```bash
mkdir -p .morphe-estado && printf '172.16.230.24\n172.16.230.52\n' > .morphe-estado/placas
```

A partir daí o cliente do notebook sonda as duas e escolhe, como o da estação. **Não**
use o `morphe-up.sh` para isso: mesmo com `--skip-fpga` ele reinicia o servidor da placa,
o que derruba quem estiver no meio de uma operação. (O `--setup-ssh --board <ip>` também
registra a placa, e é o caminho certo se o notebook for precisar de SSH.)

### 4. A escolha da placa: a que responder mais rápido

Com mais de uma placa na lista, o cliente sonda **todas em paralelo** com `OP_PING` e
fica com a que respondeu primeiro (`Python/tcp_panel.py:262`). A barra de status diz
"a mais livre entre N placas".

Por que o tempo do PING mede ocupação: como o servidor atende um cliente por vez, uma
placa no meio de uma convolução só responde ao PING **depois** de terminá-la. Placa
vazia responde em milissegundos; placa ocupada, em centenas.

**Duas placas ociosas empatam.** A diferença entre elas é de microssegundos de rede, e o
vencedor muda a cada clique — é por isso que o autoconnect "fica variando entre os IPs".
Não é defeito: é a ausência de alocação. Duas pessoas que cliquem no mesmo instante ainda
podem cair na mesma placa; o que a regra resolve é o caso comum de uma placa ocupada e
outra livre.

Desde 21/09 a escolha **ignora placas não preparadas** (item 5).

### 5. Preparada ou de fábrica

No boot, o U-Boot carrega na FPGA o `soc_system.rbf` de fábrica, e o servidor sobe pelo
autostart. Uma placa nesse estado responde ao PING com `fpga_preparada=0` e **recusa**
toda operação com o status 8 (`FPGA_NAO_PREPARADA`) e a mensagem "rode ./morphe-up.sh
nesta placa". A marca é `/var/run/morphe-fpga-preparada`, gravada pelo `morphe-up.sh`
depois do `Configuration succeeded` e apagada sozinha no reboot (é tmpfs), junto com o
bitstream que ela atesta.

Isto não é conveniência: o servidor anterior tocava a FPGA ao subir e **travava o
barramento do HPS** contra o bitstream de fábrica — a placa sumia da rede e nem o console
serial respondia (21/09/2026, placa 2; `NOVA-PLACA.md`, seção 2.4).

### 6. O tether da licença, um por cabo JTAG

A FFT usa IP licenciada em avaliação: o `quartus_pgm` precisa ficar vivo, senão o
bitstream inteiro para depois de uma hora. O `morphe-up.sh` mantém um tether **por cabo**
(`.morphe-estado/tethers/<cabo>.pid`), então preparar uma placa não derruba a outra.

O tether pertence a uma **conta**. Desde 21/09, se outra conta tentar reprogramar aquele
cabo, o script para e diz de quem ele é, em vez de subir um segundo `quartus_pgm` e
esbarrar no Quartus. Cada conta que for operar precisa do seu `--setup-ssh`.

---

## Testar com várias requisições ao mesmo tempo

`Python/testa_concorrencia.py` dispara N requisições simultâneas, **confere cada
resposta** (convolução com impulso tem que devolver a própria entrada; FFT de impulso tem
que dar espectro plano) e mede a fila. Duas fases: sozinho, para a linha de base da placa
vazia, e concorrente.

Uma máquina só, as duas placas, um cliente em cada por vez:

```bash
cd /opt/morphe/Python && python3 testa_concorrencia.py --clientes 4 --rodadas 8
```

Todos na mesma placa, que é o teste da fila:

```bash
python3 testa_concorrencia.py --modo mesma --clientes 6
```

Com a regra do app (sonda antes de cada requisição e vai na mais livre):

```bash
python3 testa_concorrencia.py --modo escolher --clientes 4
```

**Duas máquinas ao mesmo tempo** — é o cenário real de dois alunos. Rode nas duas com
etiquetas diferentes, começando quase juntos; no notebook, informe as placas, porque a
descoberta dele para na primeira:

```bash
python3 testa_concorrencia.py --etiqueta lab --clientes 3 --rodadas 10
```

```bash
python3 testa_concorrencia.py --etiqueta notebook --placas 172.16.230.24,172.16.230.52 --clientes 3 --rodadas 10
```

Como ler a saída:

| o que aparece | o que significa |
|---|---|
| `mediana X ms contra Y ms sozinho -- k.k x` | a fila está serializando, como previsto; `k` perto do número de clientes por placa é o esperado |
| falhas do tipo `recusada` | ninguém esperava: no Linux a fila cheia descarta o SYN em silêncio, não recusa. Se aparecer, o servidor caiu |
| falhas do tipo `timeout` | a fila andou mais devagar que o timeout do cliente (10 s no app) |
| falhas do tipo `servidor` | o servidor respondeu com erro — leia a mensagem; `FPGA nao preparada` é a comum |
| falhas do tipo **`valor`** | **grave**: resposta que não corresponde ao pedido. Não deveria acontecer nunca; anote e investigue |

`--csv saida.csv` grava uma linha por requisição, para juntar as duas máquinas depois.

---

## O que foi medido em 22/09/2026

Duas placas preparadas, estação do laboratório (`alunopds`) e um notebook Windows na
mesma rede, N = 1024 em todas as operações (convolução ≈ 215 ms, FFT ≈ 21 ms de placa
vazia).

| cenário | resultado |
|---|---|
| 4 clientes de uma máquina, **uma** placa | 32/32 ok, mediana 471 ms contra 120 ms sozinho (**3,9×**) |
| 6 clientes de uma máquina, **uma** placa | 24/24 ok, mediana 604 ms (**5,1×**), pior 1,29 s, **nenhuma recusa** |
| 3 clientes em **cada** máquina, as duas placas, ao mesmo tempo | **90/90 ok**, ~16 req/s somando as duas; cada placa atendeu ~45 requisições vindas das duas máquinas |
| dois clientes gráficos, um por máquina | cada um escolheu uma placa **diferente** |

O que isso diz: **a infraestrutura aguenta seis clientes simultâneos de duas máquinas
sem perder nem trocar uma resposta** — as 90 requisições do teste conjunto foram
conferidas uma a uma, não só cronometradas. O preço é latência, e ela é previsível: ~k
vezes a de placa vazia, com k clientes na mesma placa.

Uma assimetria vale registro: na rodada conjunta, a estação viu a placa `.52` em 605 ms
e a `.24` em 101 ms, enquanto o notebook viu 394 ms e 313 ms. Não é preferência de
máquina — é a fila de cada placa em cada instante, e nenhuma das duas máquinas sabe da
existência da outra. É exatamente o que a falta de alocação produz.

---

## Sintoma → causa

| sintoma | causa | o que fazer |
|---|---|---|
| O autoconnect escolhe ora uma placa, ora outra | duas placas ociosas empatam na sonda | nada; é o comportamento esperado hoje |
| Dois clientes caíram na mesma placa | não há alocação, só a sonda de ocupação | fechar e reabrir um deles, ou informar o host à mão |
| Tudo ficou ~2× mais lento | outra pessoa está na mesma placa | é a fila; veja a outra placa |
| "A placa não respondeu", mas ela está no ar | a sonda expirou: placa ocupada, ou o primeiro pacote depois de a estação ligar (visto uma vez em 22/09, não reproduzido) | tentar de novo — o `testa_concorrencia.py` já faz duas tentativas |
| Operação recusada com "FPGA nao preparada" | a placa foi ligada e ninguém programou o bitstream | `./morphe-up.sh --board <ip>` |
| O notebook só enxerga uma placa | a descoberta para na primeira e o `.morphe-estado` dele está vazio | escrever `.morphe-estado/placas` com os dois IPs |
| "o tether de DE-SoC [1-x] pertence a conta ..." | o tether é de outra conta logada | usar a placa como está, ou pedir àquela conta um `--down` |

---

## O que **não** existe, e é a v1.4

1. **Alocação de verdade.** Nada impede duas pessoas de usarem a mesma placa achando que
   cada uma tem a sua. O resultado sai certo — as requisições são atômicas —, mas o tempo
   dobra e ninguém sabe por quê. Uma reserva (concessão com prazo, renovada pelo cliente)
   resolveria, e exige estado no servidor.
2. **Concorrência no servidor.** Um `fork` por conexão, ou uma fila explícita com
   resposta "ocupada, você é o 2º", tiraria o limite do backlog e, mais importante,
   diria ao cliente o que está acontecendo: hoje ele não distingue "placa ocupada" de
   "placa fora do ar" — nos dois casos a sonda simplesmente demora.
3. **Descoberta sem varredura.** O servidor não responde a broadcast UDP
   (`morphe_protocol.py:559` explica o paliativo). Uma placa num /24 nunca visto continua
   invisível, e o notebook precisa ser informado à mão.
4. **Estado compartilhado entre máquinas.** `.morphe-estado` é por clone: o que a estação
   sabe, o notebook não sabe.

Nada disso bloqueia o uso em turma hoje — bloqueia o uso **sem supervisão** com mais
gente do que placas.
