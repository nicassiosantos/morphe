# Linha de base — quantos passos são hoje necessários

Versão 1.1 do plano de estágio, objetivo específico (f): comparar indicadores medidos
**antes e depois** das mudanças. Este documento registra o **antes**.

Medido em 14/09/2026, **antes** de qualquer alteração de usabilidade. Indicador único:
**número de passos**. Não há medição de tempo, por decisão do estagiário — a contagem de
passos é objetiva, reproduzível por qualquer pessoa a partir dos mesmos documentos, e
não depende de sujeito de teste.

## Como os passos foram contados

Fontes: `INSTALACAO.md` seções 2 a 5 e 8, e `PROCEDIMENTO-QUE-FUNCIONOU.md` seção 6.

Regra de contagem:

- **um passo** = um comando digitado, uma ação física na placa ou uma interação na
  interface gráfica que o usuário precisa executar e na qual pode falhar;
- conta-se apenas a **trilha feliz**. As seções "Se não funcionar" de cada etapa não
  entram na contagem, embora existam em número relevante;
- pré-condições que independem do usuário (placa com cartão SD gravado, conta na
  estação, acesso root na placa já habilitado) não contam como passo.

Os três cenários abaixo são os que o `INSTALACAO.md` descreve.

## Cenário A — primeira vez, estação sem nada preparado: **40 passos**

| etapa | seção | passos |
|---|---|---|
| Obter o código | 2 | 2 |
| Cliente Python (venv e dependências) | 3.2 | 4 |
| Ligar a placa e descobrir o IP | 4.1 | 6 |
| Quartus na estação (PATH e regras udev) | 4.2 | 7 |
| Programar a FPGA | 4.3 | 5 |
| Regenerar `C/hps_0.h` | 4.4 | 2 |
| Enviar e compilar o servidor | 4.5 | 4 |
| Rodar o servidor | 4.6 | 2 |
| Verificação de bring-up | 5.1 | 3 |
| Abrir e conectar a interface | 5.2 | 3 |
| Primeira operação até o resultado | 5.3 | 2 |
| **total** | | **40** |

Desses 40, **30 são comandos de terminal** e 3 exigem `sudo` — que a conta `alunopds`
da estação não tem.

Sete pontos de conhecimento tácito, que não são passos mas fazem qualquer um deles
falhar em silêncio se o usuário não souber de antemão:

1. o cabo do USB-Blaster II é o mini-USB **ao lado do botão de power**, não o USB-to-UART
   que fica logo ao lado;
2. o IP útil é o `172.16.x.x` da `eth0`; os `192.168.x.123` são aliases de fábrica e não
   servem;
3. o nome do cabo JTAG (`DE-SoC [1-1]` ou `[1-2]`) muda conforme a porta USB e precisa
   sair do `jtagconfig` a cada vez;
4. o `@2` no `quartus_pgm` é a posição da FPGA na cadeia; sem ele a programação falha;
5. o terminal do `quartus_pgm` **tem que ficar aberto** — é o tether da licença de
   avaliação do IP da FFT; fechá-lo dá uma hora de vida à FFT;
6. o `hps_0.h` versionado está desatualizado e precisa ser regenerado antes do primeiro
   build, senão a convolução devolve resultado inválido **sem erro nenhum**;
7. o `deploy.sh` não envia o `morphe_config.h` e a compilação na placa falha — por isso
   os seis arquivos vão por `scp` na mão.

## Cenário B — rotina do dia a dia, tudo já instalado: **9 passos**

Fonte: `INSTALACAO.md` seção 8. Pressupõe estação preparada, IP da placa conhecido,
servidor já compilado na placa e bitstream no lugar.

1. `cd morphe/Quartus`
2. `jtagconfig` e ler o nome do cabo
3. `quartus_pgm` com o cabo certo e o `@2`
4. deixar aquele terminal aberto
5. `ssh root@<ip> 'cd morphe && nohup sudo ./morphe_server 5000 &'`
6. `cd ../Python && ./.venv/bin/python morphe_ping.py <ip>`
7. `./.venv/bin/python morphe_app.py`
8. painel Conexão TCP: host, porta, timeout, conectar
9. escolher a operação, carregar o sinal, executar

Seis dos nove são comandos de terminal e dois exigem acesso à placa por SSH.

## Cenário C — Windows, com a placa já preparada por outra pessoa: **4 passos**

Fonte: `INSTALACAO.md` seção 8, bloco do Windows.

1. `cd morphe/Python`
2. `.venv/Scripts/python.exe morphe_app.py`
3. painel TCP, buscar automaticamente, conectar
4. escolher a operação, carregar o sinal, executar

**Este é o alvo.** O que as versões 1.2, 1.4 e 1.5 do plano fazem é transformar o
cenário C no único cenário que existe para o aluno: a preparação da placa (cenário B)
passa a ser feita pelo serviço de gerenciamento, e a instalação (cenário A) some atrás
da imagem de cartão e do instalador do cliente.

## Medição depois da v1.2 — 14/09/2026

Contada pela mesma regra, sobre o procedimento vigente após a v1.2, validada em
hardware na estação LABPS-47723 com a placa do laboratório.

**Cenário B — rotina do dia a dia: de 9 para 3 passos.**

1. `./morphe-up.sh`
2. `cd Python && ./.venv/bin/python morphe_app.py`
3. escolher a operação, carregar o sinal, executar

O que sumiu, e por quê:

| passo de antes | o que o substituiu |
|---|---|
| `cd morphe/Quartus` | o script se localiza sozinho |
| `jtagconfig` e ler o nome do cabo | lido automaticamente; erra em voz alta se houver mais de um |
| `quartus_pgm` com cabo e `@2` certos | montado pelo script |
| lembrar de deixar o terminal aberto | o tether vai para segundo plano e sobrevive ao comando |
| `ssh` para subir o servidor | feito pelo script, e sempre depois da FPGA |
| `morphe_ping` para conferir | roda sozinho antes de devolver o controle |
| preencher host, porta, timeout e conectar | o cliente abre já conectado |

Dos três passos restantes, **um é a operação em si** — ou seja, a preparação da
plataforma saiu de 8 passos para 1.

Os **sete pontos de conhecimento tácito** listados acima também deixaram de ser do
usuário: o conector, o IP, o nome do cabo, o `@2`, o tether, o `hps_0.h` e o
`morphe_config.h` são todos tratados ou verificados pelo script, que falha com
mensagem própria quando não consegue.

**Cenário A — primeira vez:** ainda não medido. A v1.5 (imagem de cartão e instalador
do cliente) é a etapa que o ataca; medir antes disso só registraria o mesmo 40.

**Cenário C:** continua em 4 passos, e continua sendo o alvo — a v1.4 deve torná-lo o
único cenário que o aluno vê, fazendo o serviço de gerenciamento executar o cenário B
no lugar dele.

## Como remedir depois

Contar de novo, pela mesma regra, sobre o procedimento vigente na época. A comparação
honesta é **cenário por cenário**.

---

As duas fontes desta contagem (`INSTALACAO.md` e `PROCEDIMENTO-QUE-FUNCIONOU.md`)
ainda estão fora do repositório. Antes de movê-las para cá, trocar o
`usuário@endereço` da placa por `${MORPHE_BOARD}` — são sete ocorrências e o
repositório é público.
