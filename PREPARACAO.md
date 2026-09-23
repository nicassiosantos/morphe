# Preparação automática da placa — versão 1.2

Antes, colocar a plataforma em operação eram **9 passos** na estação, seis deles
comandos de terminal, dois exigindo SSH na placa, e cinco pontos de conhecimento
tácito que faziam qualquer um deles falhar em silêncio. A contagem está em
`docs/LINHA-DE-BASE-PASSOS.md`.

Agora:

```
./morphe-up.sh
```

```
cd Python && ./.venv/bin/python morphe_app.py
```

O cliente abre já conectado à placa. **São 3 passos** — este, o de cima, e executar
a operação.

## O que o `morphe-up.sh` faz

Na ordem, e parando com mensagem clara no primeiro problema:

1. **Acha o Quartus** no `PATH`, em `$QUARTUS_ROOTDIR` ou nas instalações usuais.
   Os terminais em ksh93 da estação não leem o `~/.bashrc`, onde o `PATH` do Quartus
   mora — deixou de ser problema do usuário.
2. **Lê o nome do cabo JTAG do `jtagconfig`.** O índice muda conforme a porta USB
   (`DE-SoC [1-1]` ou `[1-2]`); chutar é o erro clássico.
3. **Programa a FPGA e mantém o tether da licença vivo.** O `quartus_pgm` não devolve
   o prompt: fica em `Please enter i for info and q to quit:`, e **esse processo aberto
   é o tether** da licença de avaliação do IP da FFT. Enquanto vive, não há limite de
   tempo; quando morre, começa a contagem de 1 hora e a FFT passa a devolver zeros.
   Por isso ele vai para segundo plano com um `stdin` que nunca fecha, em sessão
   própria, com o PGID guardado para o `--down`. **Um script que programasse a FPGA e
   simplesmente retornasse mataria a FFT em uma hora** — é a razão de esta parte não
   ser trivial.
4. **Acha a placa**: `--board`, `$MORPHE_BOARD`, descoberta pela rede, ou a placa
   lembrada da última vez. Informada uma vez, fica lembrada.
5. **Envia e compila o servidor**, se o binário não estiver lá ou com `--deploy`.
   Os seis arquivos incluem o `morphe_config.h`, que o `deploy.sh` esquecia.
6. **Reinicia o servidor — sempre depois da FPGA.** Um servidor que subiu antes da
   programação passa nos testes 1 e 2 do ping e dá `FPGA_TIMEOUT` nos testes 3 e 4;
   é o sintoma mais confuso da plataforma, e agora é impossível por construção.
7. **Verifica com o `morphe_ping`** antes de devolver o controle, e traduz a falha:
   quais testes falharam significam rede, FPGA ou `hps_0.h` desatualizado.

Outros modos:

```
./morphe-up.sh --board 172.16.103.226
```

```
./morphe-up.sh --status
```

```
./morphe-up.sh --down
```

`--status` diz se o tether está vivo — ou seja, se a FFT ainda está dentro do prazo.

## Uma vez por placa: acabar com as senhas

```
./morphe-up.sh --setup-ssh --board <ip>
```

Cria uma chave SSH na estação, se ainda não houver, e a instala na placa. É a
última vez que alguém digita senha: sem isso, um único `morphe-up.sh` pede senha
três vezes (scp, make, start), o que já desmonta a promessa de "um comando".

A chave é **RSA, não ed25519**, e isso não é conservadorismo: as placas rodam
OpenSSH 6.0 (Debian 7), anterior ao 6.5, que foi quando o ed25519 apareceu. Uma
chave ed25519 é aceita pelo `ssh-copy-id`, gravada no `authorized_keys` e
simplesmente ignorada na autenticação — sem erro, só a senha pedida de novo.

E a recíproca morde do outro lado: o OpenSSH 8.9 da estação desabilitou `ssh-rsa`
(SHA-1) por padrão desde a 8.8, que é o único tipo que um sshd 6.0 assina. Por
isso as conexões levam `PubkeyAcceptedKeyTypes=+ssh-rsa`. Os dois ajustes só
funcionam juntos; qualquer um sozinho reproduz o mesmo sintoma.

## Uma vez por placa: o servidor no boot

```
scp -r C/autostart root@<ip>:morphe/
```

```
ssh root@<ip> 'cd morphe/autostart && sh instala-autostart.sh'
```

O instalador detecta systemd ou init.d sozinho, porque a imagem gravada no cartão
varia de placa para placa. Depois disso a placa sobe o servidor sozinha — e a
descoberta pela rede passa a achar a placa **sem ninguém precisar saber o IP**, que é
o ponto da versão 1.2.

## Bundles de depuração na placa

O servidor grava um `.mrph` a cada operação, no diretório dele na placa. Não
havia limite: numa turma de PDS isso enche o cartão SD em silêncio — e cartão
cheio não falha na hora, falha na próxima gravação, longe da causa.

Agora ele mantém **100 por tipo de operação** (conv1d, fir, fft, ifft) e apaga
os mais antigos. Para mudar, ou desligar de vez:

```
ssh root@<ip> 'cd morphe && MORPHE_DUMP_MAX=0 nohup ./morphe_server 5000 &'
```

No autostart de boot, acrescente a variável ao serviço instalado por
`C/autostart/`.

## No cliente

O painel de conexão agora procura a placa ao abrir, sem clique: primeiro a que o
`morphe-up.sh` acabou de preparar (as duas pontas leem o mesmo
`.morphe-estado/placa`), depois a LAN. Não acha nada em ~6 s e desiste **em silêncio**,
com uma mensagem no próprio painel — sem pop-up, porque quem vai usar o gerador de
sinais, a comparação ou o projeto de FIR não precisa de placa nenhuma.

## Instalação para uso em turma

Tudo acima supõe **uma conta só**. Na estação do laboratório são duas, e elas não são
equivalentes:

| | `coordenador` | `alunopds` |
|---|---|---|
| sudo | sim | não |
| Quartus | sim | **não** |
| Home | `drwxr-x---` | — |

Medido em 16/09/2026, da conta `alunopds`: a home do coordenador é `0750`, então
**nada dentro dela é legível pelo aluno** — nem o clone, nem o `.morphe-estado/placa`,
nem o cliente. Em compensação, o resto estava verde: `ping` na placa responde, e o
`python3` **do sistema** já tem `tkinter`, `numpy`, `matplotlib` e `scipy` — ou seja, o
aluno não precisa de venv nenhum. (O `.venv` do coordenador, esse sim, não tem scipy, e
a aproximação elíptica não roda nele.)

A divisão do trabalho decorria disso: programar a FPGA exige Quartus, logo seria sempre
do coordenador. **Em 17/09/2026 isso deixou de ser verdade**, e de propósito — ver
"Tirando o coordenador do caminho crítico", adiante. O Quartus saiu da home e foi para
`/opt/intelFPGA_lite`, e o aluno prepara a placa sozinho.

### A instalação, uma vez

Como a plataforma não pode morar numa home, ela vai para `/opt/morphe`. Na conta do
coordenador:

```bash
cd ~/Documentos/validacao-final/morphe && ./morphe-up.sh --down
```

```bash
sudo mkdir -p /opt/morphe && sudo cp -a ~/Documentos/validacao-final/morphe/. /opt/morphe/
```

```bash
sudo rm -rf /opt/morphe/Quartus/db /opt/morphe/Quartus/incremental_db /opt/morphe/Python/.venv
```

```bash
sudo chown -R coordenador:alunopds /opt/morphe && sudo chmod -R u+rwX,g+rX,o-rwx /opt/morphe
```

O `.venv` sai **de propósito**: sem ele tudo passa a usar o `python3` do sistema, que é o
que tem scipy, e o aluno não esbarra num ambiente onde não pode instalar nada. O
`achar_python` do `morphe-up.sh` já cai para o `python3` do sistema quando não há venv.

O clone na home continua sendo onde se compila e se desenvolve. `/opt/morphe` é a
**instalação de turma**, atualizada com uma cópia quando algo mudar.

### Atualizar a instalacao de turma

O `cp -a` copiou o `.git` junto, entao `/opt/morphe` **e um clone**, e atualizar e um
`git pull` — sem `sudo`, porque o dono e o `coordenador`:

```bash
cd /opt/morphe && git pull
```

**Confira o branch antes.** Em 17/09/2026 o `git pull` la dizia `Already up to date` e
nao aplicava nada: o diretorio estava no branch que o clone de origem tinha, e nao na
principal. Duas preparacoes rodaram com codigo velho antes de alguem notar.

```bash
git -C /opt/morphe branch -vv
```

Se houver arquivos copiados a mao por cima, o `git pull` recusa; descarte-os primeiro com
`git -C /opt/morphe checkout -- .`.

### A rotina, depois disso

Coordenador, uma vez por dia de aula — **de dentro de `/opt/morphe`**:

```bash
cd /opt/morphe && ./morphe-up.sh
```

Aluno:

```bash
cd /opt/morphe/Python && python3 morphe_app.py
```

**Por que o coordenador tem de rodar de `/opt/morphe` e não da home:** o cliente lê o
endereço da placa em `<raiz do repositório>/.morphe-estado/placa`, e quem escreve esse
arquivo é o `morphe-up.sh`. Se os dois rodarem de raízes diferentes, o aluno abre o
cliente e não acha placa nenhuma — o sintoma parece ser de rede, e não é.

### O tether da licença, com duas contas

O `quartus_pgm` que fica aberto depois de programar é o tether da licença de avaliação.
Duas coisas sobre ele foram **medidas em 17/09/2026** e contrariam o que se supunha:

- **Ele segura o bitstream INTEIRO, não só a FFT.** Sem tether, passada ~1 h, a lógica
  na FPGA para: a convolução passa a dar **timeout** (o servidor continua no ar,
  esperando um `done` que não vem) e a FFT volta errada. O `.sof` chama-se
  `soc_system_time_limited` por isso. A versão anterior deste documento dizia que
  "convolução e FIR não são afetados"; era engano.
- **Ele sobrevive ao logout, desde que a estação tenha `linger`.** O que o matava não
  era fraqueza do `setsid`, era o `logind` destruindo o escopo do usuário ao encerrar a
  sessão. Uma linha, uma vez por estação:

```bash
sudo loginctl enable-linger coordenador
```

Diagnóstico, de qualquer conta, sem pedir ajuda a ninguém:

```bash
pgrep -af quartus_pgm
```

Não imprimiu nada? O tether caiu, e **qualquer** operação errada a partir daí é
consequência disso, não defeito de quem está usando. A correção é sempre a mesma:
`cd /opt/morphe && ./morphe-up.sh`.

O `linger` **não** sobrevive a desligar a estação: depois de cada boot, alguém roda o
`morphe-up.sh` uma vez. "Alguém", agora, inclui o aluno.

### Tirando o coordenador do caminho crítico

Deixar a aula dependente de uma sessão aberta numa conta específica não se sustenta. O
bloqueio nunca foi técnico de verdade — a regra udev do USB-Blaster já é `MODE="0666"`
(qualquer conta enxerga o cabo) e o `achar_quartus` do `morphe-up.sh` já procurava em
`/opt/intelFPGA_lite`. O Quartus só estava no lugar errado: dentro de uma home `0750`.

Uma vez, como coordenador (são 16 GB, então confira o disco antes):

```bash
sudo cp -a ~/intelFPGA_lite /opt/intelFPGA_lite
```

```bash
sudo chmod -R a+rX /opt/intelFPGA_lite
```

Uma vez, na conta do aluno — cada conta precisa da sua chave para a placa:

```bash
cd /opt/morphe && ./morphe-up.sh --setup-ssh --board <ip da placa>
```

A partir daí o aluno roda `cd /opt/morphe && ./morphe-up.sh` e prepara tudo sozinho.
**Validado em 17/09/2026**: da conta `alunopds`, com o Quartus de `/opt`, o script achou
o cabo, reprogramou, levantou o tether, reiniciou o servidor e fechou 4/4 — depois de um
desligamento completo da estação, sem o coordenador entrar.

Isso tem um preço, e ele é real: **o `morphe-up.sh` de um aluno reprograma a FPGA e
derruba o tether dos outros.** Numa turma, isso interrompe quem estiver no meio de um
exercício. A regra de bolso: rodar o script é para **começar a aula ou consertar uma
placa parada**, não durante. Se isso virar problema na prática, o caminho é a v1.4 (o
serviço que gerencia as placas), não trancar o script de novo.

Um serviço systemd no boot foi considerado e **descartado** em 17/09: ele rodaria ao
ligar a estação supondo que a placa já está ligada e na rede, e falharia calado quando
não estivesse. Preferiu-se o comando explícito — que, uma vez executado, não precisa ser
repetido: os outros computadores só abrem o app.

### O Quartus 20.1 em todos os computadores do laboratório

Para o aluno usar o Quartus por conta própria — compilar um projeto dele e programar a
FPGA pelo USB-Blaster ligado em qualquer computador —, cada computador precisa do
Quartus **20.1** em `/opt`, da regra udev do cabo e do PATH para todas as contas. O
`instala-quartus.sh` faz tudo isso, copiando a 20.1 da estação em vez de usar o
instalador, para que a versão seja a mesma em todo o laboratório. Numa conta com sudo:

```bash
git clone -b estagio/v1.1-1024pontos https://github.com/nicassiosantos/morphe.git
```

```bash
cd morphe && sudo ./instala-quartus.sh
```

Na estação ele não copia nada e só completa o resto (PATH e atalho no menu). Com a
estação em outro IP, `--origem coordenador@<ip>`; de um HD externo, `--origem <pasta>`;
só conferir, `--verificar`. Quem estiver logado precisa sair e entrar de novo.

**Cuidado:** gravar um projeto próprio numa placa que está servindo o Morphe substitui o
bitstream da plataforma para a turma inteira; depois, `./morphe-up.sh` restaura.

### O que já foi verificado, e o que falta

Verificado em 16/09/2026, da conta `alunopds`: permissões da home (é o bloqueio), rede
até a placa, dependências do Python no interpretador do sistema, e que o tether continua
vivo e visível depois da troca de usuário.

Verificado em 17/09/2026, da conta `alunopds`: o **fluxo completo do aluno** a partir de
`/opt/morphe` — app abrindo já conectado, convolução, FFT, IFFT, filtro IIR, projeto de
um **elíptico** (que exercita o scipy do sistema) e bundle salvo na home dele; o tether
sobrevivendo ao **logout** com `linger`; e a **preparação da placa pelo próprio aluno**
depois de um desligamento da estação.

Verificado em 21/09/2026, da conta `alunopds`, **com duas placas e o coordenador
deslogado**: `--setup-ssh` nas duas (a senha da placa uma vez cada), `morphe-up.sh` em
cada uma com o seu `--cable`, o tether da primeira sobrevivendo à preparação da segunda,
4/4 nas duas, e o cliente abrindo. É a resposta aos dois itens que faltavam:

1. O autostart (`C/autostart/`) está instalado nas duas placas e **sobrevive ao reboot**
   — desde que o servidor seja o de 21/09 ou posterior (ver `docs/NOVA-PLACA.md`,
   seção 2.4: o anterior travava o HPS contra o bitstream de fábrica). Uma placa
   recém-ligada responde ao ping com `fpga_preparada=0`, recusa operações com uma
   mensagem que manda rodar o `morphe-up.sh`, e o cliente não a escolhe.
2. Duas contas e duas placas: o `morphe-up.sh` de uma conta **não** derruba o tether
   da outra por engano. Se tentar reprogramar um cabo cujo tether é de outra conta, para
   com "o tether de DE-SoC [1-x] pertence a conta 'alunopds'" e diz o que fazer
   (medido em 21/09: coordenador contra o tether do aluno). Os cabos, nesta estação:
   `DE-SoC [1-2]` é a placa `172.16.230.24`, `DE-SoC [1-3]` é a `172.16.230.52`.

### O `pip --user` é a armadilha recorrente do cliente

Duas vezes (17/09 e 21/09) o cliente quebrou numa conta por um pacote instalado com
`pip install --user` em `~/.local`: primeiro um numpy 2.2.6, depois um matplotlib 3.10
que exige numpy ≥ 1.23. O `python3` do sistema (numpy 1.21.5, matplotlib 3.5.1, scipy)
roda tudo que a plataforma precisa. Se o app não abrir com `ImportError` de versão:

```bash
python3 -m pip uninstall -y matplotlib numpy
```

```bash
python3 -c "import matplotlib, numpy; print(matplotlib.__version__, matplotlib.__file__, numpy.__version__)"
```

Tem que apontar para `/usr/lib/python3/dist-packages`. O aviso `Unable to import
Axes3D` na abertura do app é o mesmo problema em forma benigna, e some com a limpeza.

## Estado desta versão

**Validada em hardware em 14/09/2026**, na estação LABPS-47723 contra a placa
172.16.230.24: um `./morphe-up.sh` sem argumento nenhum achou a placa, programou a FPGA,
enviou e reiniciou o servidor, e fechou com `morphe_ping` 4/4 — conv1d com erro 0,00 em
214,1 ms e FFT de 1024 pontos com espectro plano em 21,2 ms. O cliente abriu já
conectado, sem endereço digitado. **A rotina diária caiu de 9 passos para 3**, e destes
três um é a operação em si — a preparação saiu de 8 passos para 1. A contagem anterior
está em `docs/LINHA-DE-BASE-PASSOS.md`.

Continua pendente: instalar o `C/autostart/` em alguma placa — está escrito e nunca foi
executado —, e os dois itens de turma listados na seção acima.
