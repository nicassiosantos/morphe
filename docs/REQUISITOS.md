# Requisitos de usabilidade e de recursos

Atividade 2 do cronograma do plano de estágio: **levantamento de requisitos de
usabilidade e de recursos**. Este documento consolida, em 03/11/2026, o que foi levantado
ao longo do estágio: a linha de base de 14/09 (`LINHA-DE-BASE-PASSOS.md`), os problemas
encontrados ao reproduzir a plataforma, as decisões tomadas com o supervisor
(`DECISOES.md`) e as medições do `DIARIO.md`. Cada requisito diz **de onde veio**, **como
se verifica** e **em que estado está**, com a evidência.

Vale para as duas versões em uso (decisão de 29/10): a **completa** (branch principal,
convolução, FIR, IIR, FFT, IFFT, ADC e áudio), que é o produto do estágio, e a
**adc-fft** (`estagio/adc-fft`, só ADC e FFT), que é a que os alunos usam agora. Quando
um requisito vale só para uma delas, isso é dito.

Estados: **atendido** (verificado em hardware, com data), **parcial** (existe, mas falta
parte ou falta verificar), **pendente**, **encerrado** (decidido não fazer, com o
motivo).

---

## 1. Quem usa a plataforma

| perfil | conta | o que faz | o que **não** deve precisar saber |
|---|---|---|---|
| **Aluno** da disciplina de PDS | `alunopds`, sem `sudo` | abre o aplicativo, escolhe sinal e operação, compara o resultado da placa com a referência em software | IP da placa, SSH, Quartus, nome do cabo JTAG, tether da licença, servidor |
| **Professor ou monitor** | `coordenador`, com `sudo` | prepara o laboratório: instala e atualiza os PCs, grava cartões, põe placas em serviço | o funcionamento interno do servidor e do bitstream |
| **Aluno que cria um módulo** (desenvolvedor) | qualquer uma, com o Quartus | escreve um bloco em Verilog, liga ao Platform Designer, ao servidor e ao aplicativo | simulação e testbench (decisão de 29/10): testa pela serial |

O aluno é o perfil que define a usabilidade. Os outros dois definem o que a
documentação precisa cobrir.

## 2. O problema de partida

Medido em 14/09/2026, antes de qualquer mudança (`LINHA-DE-BASE-PASSOS.md`), pela regra
"um passo = um comando, uma ação física ou uma interação na interface em que o usuário
pode falhar; só a trilha feliz":

| cenário | passos | o que pesa |
|---|---|---|
| A — primeira vez, estação sem nada | **40** | 30 comandos de terminal, 3 com `sudo` |
| B — rotina do dia, tudo instalado | **9** | 6 comandos, 2 com SSH na placa |
| C — placa já preparada por outra pessoa | **4** | o alvo |

E sete pontos de **conhecimento tácito** que faziam qualquer passo falhar calado: qual
conector é o USB-Blaster, qual IP serve, o nome do cabo JTAG, o `@2` do `quartus_pgm`, o
terminal do tether que não pode fechar, o `hps_0.h` desatualizado, o `morphe_config.h`
que o `deploy.sh` não enviava.

Os requisitos de usabilidade abaixo saem desses números e desses sete pontos.

## 3. Requisitos de usabilidade

| id | requisito | origem | como verificar | estado |
|---|---|---|---|---|
| **RU-01** | Preparar uma placa (FPGA, servidor, verificação) em **um comando** | cenário B (8 dos 9 passos são preparação); objetivo (b) | contar os passos do cenário B | **atendido** 14/09: B de 9 para 3 (`morphe-up.sh`) |
| **RU-02** | O aluno **não digita IP** nem escolhe porta | pontos tácitos 2 e 3; DHCP muda o IP | abrir o aplicativo num PC sem configurar nada | **atendido**: broadcast UDP na porta 5000 e nome da placa (30/09); app abre conectado |
| **RU-03** | Nenhum dos **sete pontos tácitos** fica com o usuário | linha de base | cada ponto é tratado ou verificado com mensagem própria | **atendido** 14/09 (`morphe-up.sh`, `morphe_ping`) |
| **RU-04** | A licença do IP da FFT **não depende de um terminal aberto** | ponto tácito 5; sem tether o bitstream inteiro para em ~1 h (medido 17/09) | fechar o terminal e operar depois de 1 h | **atendido**: tether em segundo plano, um por cabo; sobrevive ao logout com `linger` |
| **RU-05** | A conta do aluno, **sem `sudo`**, prepara e usa a placa sozinha | o aluno não tem `sudo`; a aula não pode depender da sessão do coordenador | da conta `alunopds`, partida a frio | **atendido** 17/09 (Quartus em `/opt`); 27/10 a segunda conta passou a gravar (`protected_regular`) |
| **RU-06** | **Abrir o aplicativo basta**: ele grava a FPGA da placa no USB e conecta | cenário C é o alvo; a placa junto de cada PC (22/10) | contar os passos do cenário B pelo caminho do aluno | **atendido** 22/10 (placa 1); 29/10 cenário B = **2 passos** (placa 2, estação); 09/11 cenário C = **2 passos** (PC de aluno, `alunopds`) |
| **RU-07** | A placa funciona **junto de qualquer PC, em qualquer ponto de rede** | uma placa por PC, sem passar pela estação | levar a placa a outro PC e ponto de rede | **atendido** 27/10 (placa 2, app do aluno gravou e ADC+FFT ok) |
| **RU-08** | Todo resultado da placa aparece **ao lado da referência em software**, com o erro medido | objetivo geral; critério numérico do plano | comparar FPGA × NumPy/float64 em cada operação | **atendido**: Comparador e janelas das operações; conv/FIR 0,5 LSB, IIR 0 LSB × modelo, FFT 8192 pontos 92,9 dB (`testa_blocos`) |
| **RU-09** | Os **limites do hardware ficam escondidos**: sinal maior que 1024 amostras, formato Q, escala | objetivo (c) | mandar sinal de N > 1024 e ver o resultado inteiro | **atendido**: FFT de 1024·M em quatro passos, convolução, FIR e IIR por blocos (`blocos.py`) |
| **RU-10** | Uma falha **diz a causa e o que fazer**, em vez de travar ou dar zeros | sintoma mais confuso da linha de base: servidor antes da FPGA passa 2 testes e falha 2 | provocar as falhas conhecidas | **parcial**: `morphe_ping` traduz os 4 testes; `morphe-up.sh` e o app dizem placa sem bitstream, licença presa por outra conta, chave SSH faltando, bitstream de outra versão. Sem levantamento sistemático das mensagens |
| **RU-11** | Duas pessoas na mesma placa **não quebram** uma à outra | turma com ~5 placas | clientes simultâneos na mesma placa | **atendido** 22/09: 6 clientes, 0 falhas, latência 5,1× (`GERENCIAMENTO-PLACAS.md`); o 7º só atrasa |
| **RU-12** | O aplicativo **mostra a placa livre** e escolhe a menos usada | objetivo (d) | duas placas, uma ocupada | **atendido** 28/09 (porta de estado) |
| **RU-13** | Alocação de placa por sessão e **bloqueio de uso simultâneo** | objetivo (d), v1.4 | — | **encerrado** 29/10: com uma placa por PC e a placa livre visível no app, o problema deixou de existir (`DECISOES.md`) |
| **RU-14** | Interface com **fluxo único**: sinal → operação → executar → resultado ao lado da referência | objetivo (e), v1.6 | uso pelo supervisor | **atendido** 22/09: interface aprovada pelo Prof. Sanca; encerra v1.3 e v1.6 |
| **RU-15** | **Instalar o aplicativo** num PC em poucos passos, e **atualizar todos** de uma vez | cenário A (40 passos); 8 PCs | contar o cenário A; rodar a atualização | **parcial**: `instala-morphe.sh` (um comando por PC) e `atualizar-lab.sh` (todos por SSH, usado em 28/10); **cenário A ainda não remedido** |
| **RU-16** | **Pôr uma placa nova** em serviço: gravar o cartão e declará-la | v1.5 | gravar um cartão e ligar | **parcial**: procedimento em `NOVA-PLACA.md` e no guia `nova-placa` (placa 3 em serviço em 22/10); falta a **imagem de cartão** com servidor e autostart |
| **RU-17** | **Roteiros de prática** que levam o aluno do sinal à comparação | objetivo (h) | aluno segue o roteiro sem ajuda | **parcial**: roteiros de **módulo** prontos (somador na adc-fft, convolução); roteiros de **operação** (ADC, FFT, filtros) pendentes |
| **RU-18** | **Manual de uso** e documentação para quem for manter | objetivo (h) | — | **parcial**: manual da completa (LaTeX, 72 p. em 19/10), `como-funciona.pdf` (adc-fft, 13 p.), guias de instalação e de placa nova; falta pôr o manual em dia (`atualizar-lab.sh`, fase e stem do analisador, app gravando a FPGA) |
| **RU-19** | Material de aluno **sem simulação nem testbench** | decisão de 29/10 | — | **atendido** 29/10 (adc-fft e roteiro do somador) |

## 4. Requisitos de recursos

O que precisa existir para a plataforma funcionar como descrita acima. Levantado das
instalações feitas no laboratório (LABPS, Labotec 3) e dos problemas que cada falta
causou.

### 4.1 Placas

| id | recurso | por quê | situação |
|---|---|---|---|
| RR-01 | **DE1-SoC** com cartão SD: Linux embarcado, servidor `morphe_server` e autostart | uma por PC no arranjo atual | 3 em serviço: placa 1 `de1soclinux`, placa 2 `de1soc-02`, placa 3 `de1soc-03` (placas 1 e 2 rev H) |
| RR-02 | **Hostname e MAC únicos** por placa | a placa é achada pelo nome; duas com o MAC de fábrica brigam pelo IP | placas 2 e 3 com MAC `02:00:00:6d:70:0N`; placa 1 ainda com o de fábrica |
| RR-03 | **Chave SSH** de cada conta que prepara a placa pelo `morphe-up.sh` | sem ela, senha três vezes por preparação | RSA, por causa do OpenSSH 6.0 da placa (`PREPARACAO.md`) |
| RR-04 | Cabo **USB-Blaster** ligado ao PC ao lado | o app grava a FPGA pelo USB | regra udev `MODE="0666"`: qualquer conta enxerga o cabo |

### 4.2 Computadores

| id | recurso | por quê | situação |
|---|---|---|---|
| RR-05 | Linux com **Python 3 do sistema**, tkinter, NumPy, Matplotlib, SciPy | o aplicativo | instalado pelo `instala-morphe.sh`; pacotes do `pip --user` do aluno escondem os do sistema e quebram o app (visto 23/09) |
| RR-06 | **Quartus Prime Lite 20.1** em `/opt/intelFPGA_lite`, legível por todas as contas | o app grava a FPGA com o `quartus_pgm`; 20.1 porque o bitstream oficial é compilado nela | em todos os PCs (`instala-quartus.sh`); ~16 GB |
| RR-07 | `/opt/morphe` (clone do repositório) com o atalho no menu | uma instalação para todas as contas | `instala-morphe.sh`; ramo escolhido por PC (`atualizar-lab.sh --ramo`) |
| RR-08 | **Servidor SSH** nos PCs | atualizar os 8 PCs de uma vez pela estação | instalado em 08/10 |
| RR-09 | Grupo `dialout` na conta do aluno | console serial da placa, **só** para quem cria módulo | liberado em um PC só (06/10) |
| RR-10 | **Estação** do coordenador (LABPS-47723) com `linger` | tether que sobrevive ao logout; compilação do bitstream | `loginctl enable-linger coordenador` |

### 4.3 Rede

| id | recurso | por quê | situação |
|---|---|---|---|
| RR-11 | PCs e placas no **mesmo domínio de broadcast** (/16 do laboratório) | a placa é achada por broadcast UDP | funciona nas faixas `172.16.101` e `172.16.230`; num ponto (LABPS-47721) o broadcast não volta, o unicast sim (não resolvido) |
| RR-12 | **TCP e UDP 5000** abertos entre PC e placa | operações (TCP) e porta de estado (UDP) | funciona em todos os PCs usados; `ufw` conferido inativo no LABPS-47721 |
| RR-13 | **DHCP**, sem reserva de IP | o IP muda; resolvido pelo nome | decisão de 30/09: não depender da TI |

### 4.4 FPGA e licença

| id | recurso | por quê | situação |
|---|---|---|---|
| RR-14 | Licença de avaliação do **IP da FFT** com tether vivo | sem tether o bitstream inteiro para em ~1 h | `.sof` `time_limited`; tether mantido pelo app ou pelo `morphe-up.sh` |
| RR-15 | Área e tempo na **Cyclone V** | caber e fechar timing a 50 MHz | completa: 14 501 ALMs (45 %), estado do IIR incluído (19/10); adc-fft: 24 % dos ALMs, `clock_50` a 76,27 MHz (27/10) |
| RR-16 | Bitstream e servidor **da mesma versão** em cada placa | servidor da completa com bitstream adc-fft (ou o contrário) recusa operar | o servidor confere a assinatura MRPH; `--deploy` do ramo certo |

## 5. Requisitos de qualidade

| id | requisito | como se verifica | estado |
|---|---|---|---|
| RQ-01 | **Reprodutível a partir do repositório**: um clone limpo gera o bitstream e o servidor | compilar num clone limpo e conferir a `PROVENIENCIA.sha256` | **atendido** 09/09; proveniência conferida a cada bitstream oficial |
| RQ-02 | Resultado da placa **igual à referência**, dentro da tolerância do formato | testes automáticos contra a placa (`testa_blocos`, `testa_adc`, `testa_iir_hw`, `testa_codec`) e contra o servidor falso | **atendido**: versão completa revalidada em 29/10, 6 testes, 0 falhas |
| RQ-03 | **Evolução por camadas**: cada versão continua utilizável | a versão anterior roda sem mudança | **atendido**: protocolo e operações do autor preservados |
| RQ-04 | Usabilidade medida **só por número de passos** | mesma regra antes e depois, cenário por cenário | decisão de 01–03/09: sem tempo e sem sujeitos de teste |

## 6. O que falta verificar

1. **Cenário A** (primeira vez): remedir pela regra da linha de base. O B foi remedido
   (14/09: 3 passos; 29/10: 2) e o C também (09/11: 4 → 2).
2. **RU-15 e RU-16**: a imagem de cartão (v1.5) e a contagem do cenário A.
3. **RU-17 e RU-18**: roteiros de operação (ADC e FFT primeiro) e manual em dia.
4. **RU-10**: listar as mensagens de falha e conferir cada uma contra a causa.
5. **RR-11**: o ponto de rede do LABPS-47721, onde o broadcast não volta.

Esses itens alimentam o relatório de comparação antes × depois (objetivo f) e o
relatório final.
