# Diário de atividades — estágio no LabDSP/UEFS

Registro do que foi feito, medido e validado, em ordem cronológica. Serve de base
para as reuniões de fechamento de ciclo e para o relatório final.

**Regra deste arquivo:** só entra aqui o que foi **verificado**, com o número medido
e onde ele foi medido. Trabalho escrito mas não validado fica marcado como tal — a
distinção entre "escrito" e "funciona" é o que torna este registro útil.

Estagiário: Antonio Nicassio Santos Lima · Supervisor: Prof. Armando S. Sanca
Plataforma: Morphe (TCC de Carlos Valadão) · DE1-SoC · Fork: `nicassiosantos/morphe`

> As entradas até 10/09 são anteriores ao início oficial do estágio (21/09/2026,
> conforme o plano revisado) e foram reconstituídas a partir das notas de trabalho.
> A partir de 14/09 o registro é feito no dia.

---

## 15/09/2026 — Caminho crítico identificado; estágio S_SEL no `iir_cascade`

**Fmax medido, build de 14/09:** `clock_50_1` = **49,11 MHz** (`quartus_sta -t
relatorio_timing.tcl`, modelo Slow 1100 mV 85 °C). Primeiro Fmax registrado do projeto;
daqui em diante toda compilação anota o seu.

**O caminho crítico não era o divisor nem o acumulador.** Os 15 piores caminhos são o
mesmo: `iir_cascade:iir_inst|s[2..3]` → `sy1[9][28]`, `sy1[11][16]`, `amostra[15]`,
com **19,7 ns de lógica** em 20 ns. Era o estado `S_MAC` inteiro num ciclo: mux de
MAX_SECOES entradas selecionado por `s` (nove sinais × 32 bits), cinco multiplicações
32×32, soma de 72 bits, arredondamento, saturação e escrita de volta em `sy1[s]`,
decodificada pelo mesmo `s`. O `Div0`/`Mod0` do `c_idx % 5` não aparece entre os
violadores.

**Correção:** novo estado `S_SEL` copia `sx1[s]`…`ca2[s]` para registradores planos
`op_*`; o `S_MAC` calcula a partir deles. O multiplexador sai do caminho crítico e o
Quartus passa a medir as duas metades separadamente. `iir_biquad_mac.v` e `iir_sos.v`
intocados.

- **Testbench (Icarus, Windows): bit a bit igual ao modelo nos 3 casos.**
- Custo: **35 ciclos por amostra** (eram 24), medido no `tb_iir_cascade`. Em 1024
  amostras a 50 MHz: +0,2 ms. Irrelevante.
- **Sintetizado às 10h: `clock_50_1` = 59,81 MHz, 0 caminhos violados, pior slack
  +3,28 ns.** Um estágio de registro, +10,7 MHz. Recursos: 11.140 ALMs (35%), 30/87 DSP
  (o IIR custou 15: cada 32×32 vira três blocos de 27×27), 29% da memória.
- **Programado com `morphe-up.sh`: `morphe_ping` 4/4** — conv1d erro 0,00 em 214 ms,
  FFT plana em 21,4 ms. O remapeamento não quebrou o que existia.

**Dois defeitos encontrados ao validar, nenhum no IIR:**

1. **`--deploy` não recompilava o servidor.** A placa não tem RTC e acorda em 1970; o
   binário datado de 2026 é "do futuro" para o `make`, que responde "up to date". A
   impressão digital `.fontes.sha256` era gravada em seguida e atestava um binário que
   não correspondia às fontes. Corrigido com `make -B` (`acb5423`).
2. **`IFFT: timeout` — e depois `FFT: timeout` em tudo.** A inversa travava o
   `fft_wrapper` em `S_RECV_WAIT` e só reprogramar a FPGA destravava. Causa: o
   `fft_wrapper.v` do git tinha `source_ready` como registrador que cai a cada amostra;
   o de `~/Documentos/morphe/tcc` — origem byte a byte do `.sof` versionado, sha256
   `92a5dc35…` — tem um `[FIX]` que o torna combinacional (`state == S_RECV_WAIT`).
   **O bitstream versionado sempre foi de um RTL que o repositório não tinha**; hoje
   foi a primeira compilação de ponta a ponta a partir do git, e foi ela que expôs
   isso. O `fft_core` é o mesmo (só CRLF/LF). Correção trazida para o git.
   Encerra a validação de 09/09 de forma honesta: o clone reproduzia o *bitstream*,
   não a *compilação*.

- Se a multiplicação 32×32 mais a soma de 72 bits ainda
  não couber em 20 ns, o próximo estágio é registrar os produtos no
  `iir_biquad_mac.v`, como o `COMPILAR-IIR.md` já previa. Uma mudança por compilação.
  (Não foi preciso.)

---

## 14/09/2026 (tarde) — Primeira compilação do IIR: não fechou timing

Branch `estagio/v1.3-iir-hw`, commit `b46befe`. A v1.2 foi mesclada nesta branch antes
de compilar, para que o `morphe-up.sh` reenviasse o servidor sozinho quando o
`hps_0.h` mudasse.

Compilado pela interface do Quartus, ~10 min. **0 erros — e timing violado:**

```
Critical Warning (332148): Timing requirements not met
Worst-case setup slack is -0.364   clock_50_1   TNS -12.649
```

O `clock_50_1` tem período de 20 ns. Slack de −0,364 ns significa caminho crítico de
20,364 ns: o projeto fecha em **~49,1 MHz, abaixo dos 50 MHz** exigidos. E o TNS de
−12,6 ns mostra que são dezenas de caminhos, não um.

**O bitstream não foi programado.** Projeto fora de timing pode funcionar na bancada e
falhar de forma intermitente, que é o pior resultado possível numa plataforma didática.

**Suspeito identificado no log da síntese**, ainda não confirmado como caminho crítico:

```
Inferred divider/modulo megafunction ("lpm_divide")
    from "iir_cascade:iir_inst|Div0"  e  "|Mod0"
```

Vem de `Quartus/iir_cascade.v:209` — `case (c_idx % 5)` com `cb0[c_idx / 5]`, onde
`c_idx` é contador de 8 bits em tempo de execução. Dividir por 5 não é deslocamento,
então o Quartus sintetizou um divisor inteiro. Escapou no passo 2 porque **o testbench
valida o resultado, não a frequência**: em simulação o divisor acerta, só que devagar.

**Lacuna de método descoberta aqui, e corrigida:** o `.sta.rpt` do fluxo padrão traz só
resumos — diz o slack e o relógio, nunca os nós. Sem os nós não dá para saber o que
corrigir, e cada palpite errado custa uma compilação. Criado
`Quartus/relatorio_timing.tcl` para extrair Fmax e piores caminhos. **Daqui em diante,
anotar o Fmax de toda compilação neste diário.**

**Pergunta em aberto que muda a conclusão:** não se sabe se a v1.1 já falhava timing. O
`COMPILAR-IIR.md` registrou os recursos do build anterior mas nunca o Fmax, e o
`.sta.rpt` é ignorado pelo git. Se a v1.1 já não fechava, a plataforma vem rodando fora
de especificação desde sempre — o que explicaria o `CONV: timeout` intermitente.

**Ruído descartado:** as linhas de slack −0,77 em `HPS_DDR3_DQ[...]` são da DDR3 do
HPS, pré-existentes, e a análise específica de DDR ao fim do log dá tudo positivo
(Write 0,243 / Read Capture 0,234). Nada a ver com o IIR.

**Também em 14/09:** decidido manter a truncação do `conv1d.v` como o autor escreveu,
em vez de aplicar o arredondamento que derrubaria o erro de 521 para 25 LSB. Registrado
no `RESSALVAS.md` item 3 como escolha, não como pendência.

---

## 14/09/2026 — Versão 1.2: preparação da placa em um comando

**Validado em hardware**, placa `172.16.230.24`, estação LABPS-47723.

Resultado final do `morphe_ping`, pelo `./morphe-up.sh`:

| teste | resultado |
|---|---|
| 1 — TCP alcançável | porta 5000 aceita conexões |
| 2 — protocolo Morphe | magic MRPN correto |
| 3 — convolução com impulso | `y == x`, erro `0,00e+00`, 214,1 ms |
| 4 — FFT com impulso | espectro plano (variação 0,0%) em N=1024, 21,2 ms |

Validado em duas etapas. Primeiro as metades separadas; depois **o fluxo completo numa
tacada só**, com `./morphe-up.sh` sem argumento nenhum: achou o Quartus, substituiu o
tether antigo, leu o cabo `DE-SoC [1-2]`, programou a FPGA, achou a placa sem que o IP
fosse informado, conferiu que o servidor dela correspondia às fontes do clone,
reiniciou o servidor e fechou com 4/4. Em seguida o cliente abriu **já conectado**, sem
nenhum endereço digitado.

O que passou a existir:

- **`morphe-up.sh`** — um comando que acha o Quartus, lê o cabo JTAG do `jtagconfig`,
  programa a FPGA mantendo o tether da licença vivo, acha a placa, confere se o
  servidor dela corresponde às fontes do clone, reenvia se não, reinicia o servidor
  e verifica antes de devolver o controle. Também `--setup-ssh`, `--status`, `--down`.
- **Autoconexão do cliente** ao abrir, sem clique. Validada contra placa viva.
- **`C/autostart/`** — servidor no boot da placa, detecta systemd ou init.d.
  **Escrito, ainda não instalado em nenhuma placa.**

**Resultado de usabilidade medido:** a rotina do dia a dia caiu de **9 passos para 3**,
e destes três um é a operação em si — ou seja, a preparação da plataforma saiu de 8
passos para 1. Os sete pontos de conhecimento tácito deixaram de ser do usuário.
Contagem pela mesma regra do "antes", em `LINHA-DE-BASE-PASSOS.md`.

Seis defeitos encontrados e corrigidos no caminho, em ordem de descoberta:

1. **`jtagconfig` escreve por cima da própria barra de progresso.** A linha vira
   `<barra>\r1) DE-SoC [1-2]` e um `^[0-9]` nunca casa. O script dizia "não há cabo"
   com o cabo ali. Cada `\r` passou a virar quebra de linha.
2. **`pkill -f morphe_server` matava o próprio shell remoto**, cuja linha de comando
   continha a string. O `pgrep -f` seguinte tinha o defeito espelhado: daria positivo
   sem servidor nenhum. Passaram a ser `-x`, que casa o nome do processo.
3. **Chave ed25519 não serve para estas placas.** Elas rodam OpenSSH 6.0 (Debian 7);
   ed25519 só existe a partir do 6.5. A chave era gravada e ignorada, sem erro. E a
   recíproca: o OpenSSH 8.9 da estação desabilitou `ssh-rsa`/SHA-1 por padrão, que é
   o único tipo que um sshd 6.0 assina — os dois ajustes só funcionam juntos.
4. **"O binário existe na placa" não prova que ele corresponde às fontes.** O script
   pulava o deploy e rodava contra um servidor de origem desconhecida. Passou a gravar
   na placa o sha256 das seis fontes e comparar. O `RESSALVAS.md` item 1 já avisava.
5. **Recusa educada chegava como queda.** Uma FFT de tamanho errado era recusada com
   `BAD_SIZE`, mas o servidor fechava o socket sem ler o payload já enviado — e fechar
   com dados não lidos faz o kernel mandar **RST em vez de FIN**, descartando a
   resposta de erro. O cliente via `Connection reset by peer`. O `send_error` passou a
   drenar antes de devolver, o que vale para toda operação, não só a FFT.
6. **`morphe_ping` teste 4 mandava 64 amostras fixas**, sobra da época de 128 pontos.
   Passou a perguntar o `fft_n` ao servidor pelo PING, para não envelhecer de novo.

Além disso, a pedido: **teto de 100 bundles `.mrph` por tipo de operação** na placa,
ajustável por `MORPHE_DUMP_MAX`. Antes não havia limite — e cartão SD cheio não falha
na hora, falha na próxima gravação, longe da causa.

**Descoberto e ainda não resolvido:**

- O `PROVENIENCIA.sha256` estava vencido desde 10/09 para `C/morphe_server.c`, e em
  clone Windows falhava nos dez arquivos por causa de CRLF. Corrigido hoje; passou a
  fechar 10/10 nos dois sistemas.
- **A placa mudou de IP sozinha**, de `172.16.103.226` para `172.16.230.24` — DHCP.
  A descoberta automática varria só os `/24` 101/102/103 e não a acharia. Paliativo
  aplicado; a solução real é broadcast UDP no servidor, que é assunto da v1.4.
- **O MAC da placa é `12:34:56:78:90:12`**, o default de fábrica da Terasic. Se as
  cinco placas vieram da mesma imagem, as cinco têm o mesmo MAC e o mesmo hostname
  (`de1soclinux`) — o que **bloqueia a v1.4**, que pressupõe cinco placas vivas ao
  mesmo tempo. **Falta confirmar ligando uma segunda placa**, o que não foi possível
  neste dia. É o primeiro item a resolver antes de começar a v1.4.

---

## 10/09/2026 — IFFT validada, projetista FIR, IIR até o passo 3

- **IFFT validada em hardware.** Sem mudança de RTL: o caminho já existia desligado,
  o IP foi gerado bidirecional e o servidor escrevia zero no PIO `fft_inverse`.
- **Projetista FIR por especificação** publicado e conferido contra o MATLAB.
  **Nunca rodou na placa.**
- **Bloco IIR, passos 0 a 2** — projetista em Python, `iir_sos.v` e `iir_cascade.v`,
  bit a bit iguais ao modelo, validados com 11 seções. Passo 3 (Platform Designer)
  escrito e **não compilado**, na branch `estagio/v1.3-iir-hw`.
- O porte do `dsp_iir_filter.m` revelou **quatro erros no original do professor**,
  todos medidos contra as funções do próprio MATLAB.
- Plano de estágio revisado e preparado para reenvio à Coordenação.

## 09/09/2026 — A plataforma passa a ser reproduzível a partir do repositório

Validado com um **clone limpo do GitHub**, em pasta que nunca existira:
`sha256sum -c PROVENIENCIA.sha256` (10 OK), `gen_hps_header.py --check` (exit 0),
FPGA programada com o `.sof` do próprio clone, servidor recompilado na placa a partir
das fontes do clone, testes passando. conv1d 1024×1024 em ~214 ms, erro 0,00.

Encerra a pendência aberta em 03/09, quando o resultado bom dependia de artefatos
fora do git. Era o objetivo declarado: sair de "funciona só na máquina certa" para
"qualquer pessoa clona e roda".

## 08/09/2026 — Expansão de 128 para 1024 pontos

Concluída, validada e versionada.

## 01/09 a 03/09/2026 — Reprodução da plataforma e linha de base

Reprodução do ambiente como entregue, correções que fazem o servidor compilar, e o
`INSTALACAO.md` reconstituindo o caminho de ligar a placa até a interface gráfica.
As armadilhas encontradas viraram o `RESSALVAS.md`.

**Linha de base de usabilidade medida** (sem métricas de tempo, por decisão do
estagiário): 40 passos na primeira vez, 9 na rotina diária, 4 no melhor caso.
Detalhe em `LINHA-DE-BASE-PASSOS.md`.
