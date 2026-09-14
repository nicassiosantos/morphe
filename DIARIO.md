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
