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

## 22/09/2026 — A infraestrutura de requisições, documentada e medida

**O que se queria saber:** o que acontece quando duas pessoas, em máquinas diferentes,
pedem coisas às placas ao mesmo tempo. Até hoje isso era conjectura apoiada na leitura
do código.

**Escrito:** `docs/GERENCIAMENTO-PLACAS.md`, que descreve as peças que existem hoje
entre o cliente e a placa — servidor de um cliente por vez (`accept` → atende → `close`,
`listen(4)`), uma conexão TCP por operação, descoberta por lista local e varredura que
para na primeira placa, escolha pela sonda de ocupação (`OP_PING`), marca de FPGA
preparada, tether por cabo JTAG — com o que decorre de cada uma, uma tabela
sintoma → causa e o que falta (a v1.4). E `Python/testa_concorrencia.py`, que dispara N
requisições simultâneas e **confere cada resposta**: convolução com impulso tem que
devolver a própria entrada, FFT de impulso tem que dar espectro plano. Uma resposta
trocada entre conexões concorrentes apareceria como erro de valor, não como lentidão.

**Medido**, com as duas placas preparadas, a estação (`alunopds`) e um notebook Windows
na mesma rede, N = 1024 (convolução ≈ 215 ms, FFT ≈ 21 ms de placa vazia):

| cenário | resultado |
|---|---|
| 4 clientes de uma máquina, uma placa | 32/32 ok, mediana 471 ms contra 120 ms sozinho (3,9×) |
| 6 clientes de uma máquina, uma placa | 24/24 ok, mediana 604 ms (5,1×), pior 1,29 s, **nenhuma recusa** |
| 3 clientes em cada máquina, as duas placas, ao mesmo tempo | **90/90 ok**, ~16 req/s somados |
| dois clientes gráficos, um por máquina | cada um escolheu uma placa **diferente** |

**A infraestrutura aguenta seis clientes simultâneos de duas máquinas sem perder nem
trocar uma resposta.** O preço é latência previsível: ~k vezes a de placa vazia, com k
clientes na mesma placa.

**Uma expectativa corrigida pela medição.** O documento dizia que a 5ª conexão
simultânea seria recusada, por causa do `listen(srv, 4)`. Não é o que acontece: o Linux
guarda `backlog + 1 = 5` conexões esperando e a sexta é a que está sendo atendida — por
isso 6 clientes couberam justo, sem uma falha. E, mesmo estourando, o excesso **não**
vira `ECONNREFUSED`: com `tcp_abort_on_overflow = 0` o kernel descarta o SYN em silêncio
e o cliente retransmite ~1 s depois. O sintoma seria um pico de latência, não um erro.
Falta medir com 8 a 10 clientes.

**Assimetria que vale registro:** na rodada conjunta a estação viu a placa `.52` em
605 ms e a `.24` em 101 ms, enquanto o notebook viu 394 ms e 313 ms. Não é preferência
de máquina — é a fila de cada placa em cada instante, e nenhuma das duas máquinas sabe
da existência da outra. É exatamente o que a falta de alocação produz, e é o argumento
concreto para a v1.4.

**Dois defeitos do próprio teste, achados ao usá-lo e corrigidos** (`4e81045`): a sonda
descartava do teste inteiro uma placa que perdesse um único `OP_PING` de 3 s — aconteceu
com a placa 2 logo depois de a estação ligar, e o primeiro teste do dia rodou sem ela
sem avisar; agora são duas tentativas. E a razão contra a linha de base comparava
medianas de misturas diferentes de convolução e FFT, o que chegou a imprimir "0,3×";
agora só as convoluções entram na conta.

**Preparar o notebook para enxergar as duas placas:** o `.morphe-estado` é por clone, e a
varredura para na primeira placa que acha. Basta escrever a lista uma vez —
`.morphe-estado/placas` com um IP por linha. Não serve usar o `morphe-up.sh` para isso:
mesmo com `--skip-fpga` ele reinicia o servidor da placa e derrubaria quem estivesse no
meio de uma operação.

---

## 21/09/2026 — Primeiro dia oficial: por que a placa 2 não voltava do reboot

**Resultado do dia:** a placa 2 (`172.16.230.52`, `de1soc-02`) volta do reboot com MAC
próprio (`02:00:00:6d:70:02`), responde ao ping e ao SSH, e o console serial tem shell.
Foram **quatro** defeitos empilhados, e o que derrubava a placa era o último — um bug do
próprio Morphe, presente também na placa 1, que **não pode ser reiniciada** até receber
o servidor corrigido.

**1. `allow-hotplug eth0` nunca sobe nesta imagem.** O `printf` do `NOVA-PLACA.md`
reescrevia o `interfaces` com `allow-hotplug`; a imagem é Ubuntu 12.04 com upstart, cujo
`network-interface.conf` roda `ifup --allow auto`. Medido pelo `syslog` do cartão: depois
do reboot de 17/09 13:30 não há uma linha de `dhclient` — a eth0 não era levantada.
Corrigido para `auto eth0`.

**2. O console serial não tinha shell.** O `login:` nunca apareceu porque o autologin do
root roda no `tty1` (`/etc/init/openvt.conf`), inexistente na placa; a serial só
mostrava o eco. Confirmado que o sentido estação→placa funciona parando o U-Boot com
Enter. Getty em `/etc/init/ttyS0.conf` (`start on filesystem`, para subir mesmo que o
resto trave).

**3. MAC no lugar certo: o `ethaddr` do U-Boot.** `printenv` mostrou
`ethaddr=12:34:56:78:90:12` — o kernel recebia o MAC de fábrica e o `pre-up` trocava
depois. `setenv ethaddr 02:00:00:6d:70:02` + `saveenv` (`Writing to MMC(0)... done`).
Teste sem Linux, no próprio U-Boot: `dhcp` → `DHCP client bound to address
172.16.230.52` em 2 s, com o MAC novo. **Isso provou que hardware, cabo, switch e DHCP
aceitavam a placa** — e que o problema estava dentro do Linux.

**4. O servidor no autostart travava o HPS.** Com `init=/bin/bash` (sem upstart) o mesmo
kernel respondia ao ping IPv6 (`fe80::ff:fe6d:7002`) e o `ip -s link` contava RX. Com o
boot normal, o `dhclient` mandava `DHCPDISCOVER` por 5 min sem resposta, o `login`
congelava depois da senha e o diagnóstico no `rc.local` nunca imprimia. Diferença: o
`S20morphe-server`. O `fpga_init()` do servidor zerava quatro PIOs pela ponte lightweight
ao subir — e no boot a FPGA carrega o `soc_system.rbf` de fábrica, em que esses
endereços não existem. No Cyclone V, acesso a endereço sem escravo na ponte HPS→FPGA
trava o barramento L3, sem timeout, e leva junto a Ethernet e o que mais tocar memória
mapeada. Confirmação: renomeando `S20morphe-server` → `K20`, a placa voltou do reboot
com ping, SSH, diag impresso e `login` funcionando.

Em 17/09 o autostart foi instalado com o bitstream do Morphe já programado, então o caso
"servidor + FPGA de fábrica" nunca tinha acontecido. A placa 1 tem o mesmo autostart.

**Validação da correção, à tarde, nas duas placas** (`138ca3e`, de `/opt/morphe`):

| passo | placa 2 (`.52`) | placa 1 (`.24`) |
|---|---|---|
| `morphe-up.sh --deploy` (servidor novo, marca, testes) | 4/4 | 4/4 |
| `reboot` com o autostart ligado | volta; servidor no ar; sem marca | volta; servidor no ar; sem marca |
| `morphe_ping` na placa recém-ligada, sem `morphe-up.sh` | — | [1] [2] passam; [3] `CONV: FPGA nao preparada -- rode ./morphe-up.sh nesta placa` |
| `morphe-up.sh` depois do reboot | marca criada, 4/4 | marca criada, 4/4 |

Os dois cabos JTAG ao mesmo tempo (`DE-SoC [1-2]` = placa 1, `DE-SoC [1-3]` = placa 2),
cada `morphe-up.sh` com o seu `--cable`, e o tether de uma sobreviveu à preparação da
outra. O item "autostart sobrevive ao reboot", pendente desde 14/09, está fechado nas duas.

**Correção (versionada em `138ca3e`, implantada e validada acima):**

- `C/morphe_server.c`: `fpga_init()` não toca mais a FPGA. Os PIOs são zerados em
  `fpga_preparada()`, na primeira operação depois que existe
  `/var/run/morphe-fpga-preparada`. Sem a marca, toda operação devolve o status novo
  `MORPHE_STATUS_FPGA_NAO_PREPARADA` (8) com a mensagem "rode ./morphe-up.sh nesta
  placa"; o `OP_PING` passa a informar `fpga_preparada=0|1`.
- `morphe-up.sh`: depois de `Configuration succeeded`, grava a marca na placa por SSH,
  antes de (re)iniciar o servidor. A marca vive em tmpfs — some no reboot, junto com o
  bitstream. Com `--skip-fpga`, vale a que já estiver lá.
- Cliente: `ServerInfo.preparada`; a escolha automática de placa e a autoconexão ignoram
  placas de fábrica; a janela de descoberta ganhou a coluna FPGA.
- `docs/NOVA-PLACA.md` reescrito no passo 2 (MAC pelo U-Boot, `auto eth0`, hostname nos
  dois arquivos) e com a seção 2.4 (leases herdadas, getty, servidor mínimo para o
  autostart).

**Limpezas feitas na placa 2 durante o diagnóstico, já desfeitas:** o `/etc/morphe-diag.sh`
saiu do `/etc/rc.local` e o `S20morphe-server` voltou nas duas placas depois do servidor
novo. Ficaram, de propósito: o getty na serial (`/etc/init/ttyS0.conf`) e a linha
`source /opt/ros/hydro/setup.bash` comentada no `/root/.bashrc` (herança da imagem; não
era a causa, mas não faz falta).

**Tarde: o aluno sozinho, com duas placas.** Coordenador com `--down` e logout de
verdade; da conta `alunopds`: `--setup-ssh` nas duas placas, `morphe-up.sh` em cada uma
com o seu cabo (`DE-SoC [1-3]` = `.52`, `DE-SoC [1-2]` = `.24`), o tether da primeira
intocado pela segunda, **4/4 nas duas**, cliente aberto. O objetivo de operar a
plataforma só da conta do aluno está cumprido, agora com duas placas. Do coordenador,
em seguida: o cliente abre; e `morphe-up.sh` contra o cabo do aluno para com "o tether
de DE-SoC [1-3] pertence a conta 'alunopds'" sem reprogramar (`44459a9` — antes, o
`kill -0` num processo alheio dava EPERM, o script achava o cabo livre e o Quartus
recusaria o cabo). Não anotado: qual IP cada cliente escolheu; o teste de "cair na
placa parada" com uma convolução em andamento fica para amanhã.

**Miúdos do dia:** `1dc7082` o `--setup-ssh` escreve o bloco `Host <ip>` no
`~/.ssh/config` (ssh e scp avulsos sem senha, medido nas duas contas); `61e3a4d` o
`distribui_ganho()` mede a seção pelo maior `|b|` — o passa-alta 3800/3700 de ordem 13
sai de `recusar` para `ok`, com `|H|` idêntica; o cliente do coordenador quebrou de novo
por um `pip --user` (matplotlib 3.10 exigindo numpy ≥ 1.23), limpo com `pip uninstall`,
e o caso virou seção do PREPARACAO.md.

**Ferramentas que valeram o dia, para a próxima vez:** `screen -L -Logfile` para gravar
a serial; o U-Boot como bancada de teste de rede (`setenv autoload no; dhcp`); o IPv6
link-local (`fe80::` + MAC) como endereço fixo da placa que dispensa DHCP;
`init=/bin/bash` para separar kernel de init; e o `syslog` do cartão montado na estação
como registro do que cada boot fez.

---

## 17/09/2026 — O aluno prepara a placa sozinho; e o tether segura o bitstream inteiro

**Duas medições derrubaram duas crenças anteriores.**

**1. O tether sobrevive ao logout — faltava uma linha.** Em 16/09 ficou registrado que
o tether morria ao encerrar a sessão do coordenador. Hoje, depois de
`sudo loginctl enable-linger coordenador`, o logout foi feito de verdade e o
`pgrep -af quartus_pgm` da conta do aluno ainda mostrava o **PID 5123 — o tether do
próprio `setsid` do `morphe-up.sh`**. Ou seja: o `setsid` nunca foi o problema; o
`logind` é que destruía o escopo do usuário inteiro no logout, e o `linger` impede isso.
O `systemd-run` que se cogitou é desnecessário, e a linha 264 do `morphe-up.sh` fica como
está. A regra "trocar de usuário, nunca encerrar sessão" morreu.

**2. Sem tether para a lógica INTEIRA, não só a FFT.** Depois de desligar a estação (o
que mata o tether — `linger` não sobrevive a um boot), da conta do aluno: a placa
respondia ao `ping` em 1 ms, mas a **convolução dava timeout** e a FFT voltava errada.
Timeout, e não "conexão recusada", é o servidor vivo esperando um `done` que a lógica
parada nunca emite. Um `./morphe-up.sh` devolveu os 4/4. O `.sof` chama-se
`soc_system_time_limited` porque é o bitstream que é time-limited, não o IP da FFT
sozinho. O `INSTALACAO.md` afirmava que "convolução e FIR não são afetados" — corrigido
hoje, no texto da seção 4.3 e na tabela de sintomas.

**O coordenador saiu do caminho crítico.** A premissa de que "programar a FPGA exige
Quartus, logo é sempre do coordenador" não se sustentava: a regra udev do USB-Blaster já
era `MODE="0666"` e o `achar_quartus` do `morphe-up.sh` já procurava em
`/opt/intelFPGA_lite`. O Quartus só estava no lugar errado — dentro de uma home `0750`.
Copiado para `/opt/intelFPGA_lite` (16 GB) com `a+rX`, e o `morphe-up.sh` devolvido ao
grupo. **Validado**: da conta `alunopds`, depois de um desligamento completo da estação e
sem o coordenador entrar, `./morphe-up.sh` achou o Quartus em `/opt`, achou o cabo
`DE-SoC [1-2]`, reprogramou, levantou o tether, reiniciou o servidor e fechou **4/4** —
conv1d com erro 0,00 em 214,0 ms e FFT plana em 21,4 ms. Uma vez por conta é preciso
`./morphe-up.sh --setup-ssh --board <ip>`, porque a chave da placa é por conta.

O preço, registrado porque é real: o `morphe-up.sh` de um aluno reprograma a FPGA e
derruba o tether dos outros. A regra de bolso vira "rodar para começar a aula ou para
consertar uma placa parada, não durante". Se virar problema na prática, a resposta é a
v1.4, não trancar o script.

**Um serviço systemd no boot foi considerado e descartado**, por decisão do estagiário:
ele rodaria ao ligar a estação supondo a placa ligada e na rede, e falharia calado quando
não estivesse. Fica o comando explícito, que uma vez executado não precisa ser repetido —
os outros computadores só abrem o app.

**Fluxo do aluno validado de ponta a ponta**, os seis itens que faltavam de ontem: app
abrindo já conectado (sem digitar IP), convolução, FFT de 1024, IFFT, filtro IIR e
projeto de um **elíptico** (que exercita o scipy do sistema), com bundle salvo na home
dele. `/opt/morphe` continuou só-leitura para o aluno o tempo todo.

**O app do coordenador voltou a abrir.** `numpy 2.2.6` instalado por `pip --user`
sombreava o do sistema e quebrava o scipy com `AttributeError: _ARRAY_API not found`;
`python3 -m pip uninstall -y numpy` devolveu o **1.21.5** de
`/usr/lib/python3/dist-packages`. A conta do aluno tem a mesma armadilha com o
`matplotlib` do `--user`, hoje só um aviso (`Unable to import Axes3D`), ainda não limpa.

**Endurecimento parcial, e por que parcial.** `chmod g-x` no `morphe-up.sh` deixou o modo
`-rwxrw----`: o aluno não executava direto, mas ainda lia e **escrevia** o script —
`bash morphe-up.sh` contornava, e pior, ele podia editar o que o coordenador roda com
sudo. Ficou sem efeito de qualquer forma: com o Quartus em `/opt`, o script foi devolvido
ao grupo de propósito.

**`18531bf` — o comparador mostra as duas referências no bundle IIR.** Veio de uma
pergunta: "por que o erro do IIR é sempre zero?". Porque a referência é o
`filtra_sos_fixo`, que **é a especificação do RTL** — mesma aritmética inteira, mesmo
arredondamento — e num filtro realimentado só serve comparação bit a bit: um LSB de
divergência numa amostra diverge para sempre. Esse zero, porém, esconde a outra pergunta.
`filtra_sos_double()` subiu para o `iir_design.py` (era local do
`compara_professor_fpga.py`, que agora delega) e roda a mesma cascata, com os mesmos
coeficientes já quantizados, em float64. Medido no `iir_lowpass.mrph` de 1024 amostras:
**0 contra o modelo Q15.16 e 1,45e-05 — 0,95 LSB, 103 dB — contra o float64**. A segunda
não mede o custo de quantizar coeficiente: para isso a referência teria de ser o `sos` de
projeto, que o bundle não carrega.

### Tarde: a segunda placa entra em servico, e a v1.4 comeca

**A placa 2 nasceu.** Cartao gravado a partir de `de1soc_sd_20260903.img` com
`dd bs=4M count=1600` — a imagem tem 29,76 GiB e o cartao 29,1 GiB, mas so os primeiros
6,25 GiB carregam dados, entao copiar ate o ultimo setor usado resolve o tamanho e corta
o tempo para um quinto. Procedimento inteiro em `docs/NOVA-PLACA.md`.

**O conflito de MAC era real, e foi medido:** as duas placas mostravam
`12:34:56:78:90:12`. O `.link` do systemd **nao funciona** nesta imagem — quem configura
a rede e o ifupdown. O que resolveu foi `pre-up ip link set dev eth0 address ...` no
`/etc/network/interfaces`. A placa 2 subiu com `02:00:00:6D:70:02` e o DHCP deu
**172.16.230.52**, endereco diferente do da placa 1 — prova de que a troca surtiu efeito.
Os aliases de fabrica `192.168.1.123` e `192.168.0.123` sairam junto: vinham identicos
nas duas e colidiriam por IP tambem.

**`instala-autostart.sh` estreou**, pelo caminho do init.d, depois de meses escrito e
nunca executado. A placa 2 fechou **4/4** (conv1d 0,00 em 213,6 ms; FFT plana em 21,0 ms).

**Uma armadilha que quase passou por boa:** o `git pull` em `/opt/morphe` dizia
`Already up to date` e nao aplicava nada, porque o diretorio estava em outro branch — o
`cp -a` da instalacao copiou o `.git` junto, com o branch que o clone de origem tinha.
Duas preparacoes rodaram com o codigo velho antes de alguem notar. O sintoma que
denunciou foi o `pgrep` mostrando `.morphe-estado/tether.pid`, o arquivo unico que o
commit novo ja tinha substituido.

**`7744287` — um tether por cabo JTAG.** Preparar a placa 2 derrubava o tether da 1, e
sem tether o bitstream inteiro para em 1 h. Nao era limite de hardware: sao dois cabos,
dois `quartus_pgm`, dois tethers independentes; o estado do script e que era um arquivo
so. Agora e `.morphe-estado/tethers/<cabo>.pid`. **Validado na estacao com as duas placas
ligadas**: preparar a segunda imprimiu "1 tether(s) de outras placas seguem vivos,
intocados", o `--status` listou os dois (PGID 13875 no `DE-SoC [1-2]`, 14011 no
`[1-3]`) e o `pgrep` confirmou dois processos. As duas placas responderam 4/4.

**`030d348` — o cliente escolhe a placa sozinho.** Le a lista
`.morphe-estado/placas`, sonda todas em paralelo com um `OP_PING` e fica com a que
responder mais rapido. O tempo do handshake mede ocupacao porque o servidor e um laco
`accept`/atende/fecha sem thread (`morphe_server.c:1091`): placa livre responde em
milissegundos, ocupada responde quando termina os ~200 ms da operacao em curso. Nao e
alocacao — dois alunos que abram no mesmo instante ainda podem cair na mesma placa —,
mas o aluno deixou de precisar saber que existem duas placas, que era o pedido.

**Branch `estagio/v1.2-ifft` apagada**, local e no remoto, depois de confirmado que não
tinha um único commit fora da principal.

---

## 16/09/2026 — A plataforma sai da conta do coordenador; o tether não sobrevive ao logout

**Instalação de turma em `/opt/morphe`, validada.** Até hoje a plataforma só tinha sido
usada da conta `coordenador`. Medido da conta `alunopds`: a home do coordenador é
`drwxr-x---`, então **nada dentro dela é legível pelo aluno** — nem o clone, nem o
`.morphe-estado/placa` que o cliente lê para abrir já conectado. Era o único bloqueio:
`ping` na placa responde (1 ms) e o `python3` **do sistema** já tem `tkinter`, `numpy`,
`matplotlib` e `scipy`, então o aluno não precisa de venv nenhum.

A plataforma foi copiada para `/opt/morphe` (`coordenador:alunopds`, `u+rwX g+rX o-rwx`,
sem `Quartus/db`, sem `incremental_db` e **sem `.venv`**), com `g+s` nos diretórios para
o grupo sobreviver aos `git pull` seguintes. `./morphe-up.sh` rodado de lá fecha
**4/4**: conv1d com erro 0,00 em 424,4 ms e FFT plana em 21,7 ms.

- **O coordenador passa a rodar o `morphe-up.sh` de `/opt/morphe`**, não da home: o
  cliente lê o IP em `<raiz>/.morphe-estado/placa` e as duas pontas precisam da mesma
  raiz. Se divergirem, o aluno não acha placa e o sintoma **parece ser de rede**.
- Na conta do aluno o app **abre**; o roteiro de operação dentro dele ainda não foi
  exercitado.

**Medido: o tether da licença não sobrevive ao logout do coordenador.** Sobrevive à troca
de usuário. O `systemd-logind` destrói o escopo da sessão inteiro, e o `setsid` que o
`morphe-up.sh` usa não protege contra isso — `pgrep -af quartus_pgm` volta vazio depois do
logout. Até existir correção, a regra de operação é **trocar de usuário, nunca encerrar
sessão**. Correção proposta e ainda não implementada: `loginctl enable-linger` mais
`systemd-run --user --unit=morphe-tether`, que sobrevive por ficar sob o `user@.service`
em vez de sob o escopo da sessão.

**Defeito encontrado, na conta do coordenador: o app não abre.** O
`~/.local/lib/python3.10/site-packages` dele tem **numpy 2.2.6** instalado por
`pip --user`, que sombreia o do sistema; o scipy do sistema foi compilado contra numpy 1.x
e quebra com `AttributeError: _ARRAY_API not found`. A conta do aluno não tem o problema.
Contorno imediato: `PYTHONNOUSERSITE=1`.

**Limpeza do git (`742152a`).** `Quartus/db/` e `incremental_db/` estavam **rastreados**
apesar do `.gitignore` — 987 arquivos de banco de dados intermediário do Quartus. Saíram
do índice; nada foi apagado do disco. Com isso some a trava que proibia `git reset --hard`
na estação, que revertia o `db/` para um estado antigo e corrompia o projeto.

**Documentação técnica do bloco IIR** (item 7 do plano), escrita e **ainda não
versionada**: `docs/iir-em-hardware.html`. Organizada pelo fluxo de execução — o que sai
do computador, o que o servidor faz, o que cada módulo da FPGA calcula e o que volta —,
com a derivação de onde vem cada um dos cinco coeficientes de uma seção, incluindo o
ganho, e duas calculadoras interativas: uma seção amostra a amostra e a cascata seção a
seção, ambas com a aritmética inteira do hardware.

**Achado no `distribui_ganho()`, documentado e não corrigido.** A medida usada é o ganho
em DC (`b0+b1+b2`). Num passa-alta os zeros ficam em `z = +1` e essa soma é **zero
exato**, então a guarda de produto nulo dispara e a distribuição **nunca acontece**.
Medidos: HP 3800/3700 Hz (ordem 13), 3900/3800 e 3950/3900 (ordem 8) todos produzem
`b0 = 0` depois de quantizar. Nada errado chega à placa — o `verifica_viabilidade()`
recusa os três —, mas a mensagem manda distribuir o ganho, que já foi tentado. A correção
é trocar a soma dos `b` por uma medida que nunca zere (`max|b|` ou a norma): qualquer
medida positiva preserva o produto, porque `∏(alvo/gᵢ) = alvoˢ/∏gᵢ = 1`.

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

**Recompilado com o wrapper corrigido, 11h: `clock_50_1` = 60,99 MHz, 0 violações.**
`morphe_ping` 4/4 (conv1d erro 0,00 em 217,7 ms; FFT plana em 21,3 ms) e
**`testa_ifft_roundtrip.py`: 0 falhas** — delta espectral com erro relativo 3,1e-5, ida e
volta 6,1e-5, ganho residual 0,99995. **Primeira vez que o repositório se prova de ponta
a ponta:** clone → compila → programa → tudo que existia passa. O IIR está na FPGA
(30/87 DSP), sem caminho de software ainda — é o passo 4.

**Passo 4 do IIR, tarde: `MORPHE_OP_IIR` (6), `handle_iir` no servidor, cliente Python
(`857a5ea`, `56d28fe`). `testa_iir_hw.py` contra a placa: 0 falhas em 4 casos, bit a
bit igual ao `filtra_sos_fixo`** — impulso por uma seção (Chebyshev I), cascata de 11
seções com 1024 e com 300 amostras (o hardware roda sempre 1024; o servidor completa
com zeros), e saturação provocada na ressonância com a flag `extra` = 1. Saturação não
é erro no protocolo: o vetor saturado chega ao cliente com o aviso.

Estado do bloco IIR: passos 0 a 4 prontos e validados em hardware. Faltam a tela do
projetista (5) e o comparador reconhecer o bundle `iir_*.mrph` (6) — software só.

**Passo 5, fim da tarde: tela do projetista IIR e janela "Filtro IIR (FPGA)"** —
`iir_designer_window.py` é o porte da `Iir_filter_window.m` do DSPFinal (aproximação,
tipo, fp/fs/δp/δs/Fs; tipo e ordem; polos e zeros + impulso; freqz), mais o que o
hardware exige: polos **depois de quantizar** sobre o mapa, resposta quantizada sobre
a ideal e o veredito de viabilidade antes de deixar aplicar. `iir_window.py` é a gêmea
da FIR: sinal, filtro, "Aplicar IIR (FPGA)", bundle — e confere a saída da placa bit a
bit com o modelo na hora. Botão "Filtro IIR (FPGA)" no hub. **Escrito e ensaiado sem
placa** (fluxo completo com a resposta simulada pelo modelo); falta rodar contra a
placa e o passo 6 (comparador).

**Passo 6: o comparador reconhece o bundle IIR** (título com "iir": tanto o `Morphe IIR`
da janela quanto o `iir server debug dump` do servidor). A referência **não** é o NumPy
em float, é o `filtra_sos_fixo` — o mesmo modelo do testbench e do `testa_iir_hw.py` —
então o erro esperado é exatamente zero e qualquer LSB é defeito. Ensaiado: bundle da
janela dá erro 0; dump do servidor com um LSB plantado em n=7 é apontado em n=7.

Com isso os seis passos do bloco IIR estão escritos; 0–4 validados na placa, 5 e 6
ensaiados sem placa. **Mesclar na principal só depois de testar 5 e 6 na interface**,
por decisão do estagiário.

**Interface testada no PC Windows contra a placa** (15/09, fim do dia): projetar →
aplicar → *Aplicar IIR (FPGA)* → "bit a bit igual ao modelo" → bundle → comparador com
erro 0. Passos 5 e 6 validados na interface.

**O código do professor contra a FPGA** (`compara_professor_fpga.py`, MATLAB R2024b
neste PC, `dsp_iir_filter.m` do DSPFinal; Butterworth 200/300 Hz, 1/40 dB, 8 kHz,
ordem 13, coeficientes **dele** via `tf2sos` enviados à placa):

| comparação | erro máx |
|---|---|
| FPGA × modelo em ponto fixo | **0 amostras diferentes** |
| FPGA × cascata de biquads em double | 1,7e-3 (0,34% do pico) — o custo real do Q15.16 |
| FPGA × `filter(numz,denz)` do MATLAB | 2,1e-2 (4,0% do pico) |
| forma direta em Python × `filter()` do MATLAB, **mesmo polinômio** | 3,1e-2 (6,1%) |

Duas implementações em dupla precisão do polinômio de ordem 13 dele não concordam
entre si: o polinômio é mal condicionado (13 polos em |p| ≈ 0,98; |H(100 Hz)| = 0,962
pelo polinômio, 0,978 pela cascata). **A FPGA em cascata fica mais perto da resposta
certa do que o MATLAB do professor com o polinômio** — o argumento do cabeçalho do
`iir_cascade.v`, medido. E o projeto dele erra a especificação: −3,28 dB em fp para 1 dB
pedido (`Wn` do `buttord` ignorado); o do cliente dá −1,03 dB.

Ambiente: o `.venv` da estação não tem scipy; a elíptica do `iir_design.py` não roda
lá. O teste usa Chebyshev I por isso.

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
