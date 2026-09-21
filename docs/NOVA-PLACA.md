# Acrescentar uma placa DE1-SoC ao laboratório

Procedimento para pôr uma segunda (terceira, quarta…) placa em serviço, do cartão SD
vazio até o cliente achá-la na rede.

**Estado deste documento (21/09/2026):** todos os passos foram executados na placa 2
(`172.16.230.52`, hostname `de1soc-02`), e ela volta do reboot com MAC próprio e servidor
no ar. O caminho descrito aqui é o que sobrou depois de dois que não funcionaram (o `.link`
do systemd e o `pre-up` do ifupdown) e de um que derrubava a placa no boot (o autostart com
um servidor que tocava a FPGA de fábrica). O que custou o dia 21/09 está na seção 2.4.

---

## Por que não basta ligar a segunda placa

Todas as DE1-SoC sobem com o **mesmo endereço MAC**, `12:34:56:78:90:12`, que é
placeholder da imagem de fábrica. Duas na mesma rede disputam a tabela ARP do roteador:
as conexões ficam intermitentes e o sintoma não parece de rede — parece placa com
defeito. É a única razão pela qual "ligue uma de cada vez" ainda é a regra do
laboratório.

Então o passo que importa neste documento é o **2**. O resto é cópia.

---

## Passo 1 — o que você precisa ter em mãos

- A placa nova, com fonte e cabo de rede.
- Um cartão SD de 8 GB ou mais (o da placa em serviço é o molde).
- Um leitor de cartão na estação.
- A estação com Quartus em `/opt/intelFPGA_lite` (ver `PREPARACAO.md`).
- Um MAC novo, que você escolhe. Use a faixa de administração local, que nunca colide
  com fabricante nenhum: o segundo dígito **2**, **6**, **A** ou **E**. Sugestão de
  convenção para o laboratório, que deixa o número da placa legível no próprio endereço:

| placa | MAC |
|---|---|
| 1 | `02:00:00:6D:70:01` |
| 2 | `02:00:00:6D:70:02` |
| 3 | `02:00:00:6D:70:03` |

(`6D 70` é "mp", de Morphe; o último octeto é o número da placa.)

## Passo 2 — o cartão SD

### 2.1 Clonar o cartão que já funciona

> **Se já existir uma imagem pronta na estação, pule a leitura do cartão.** Em
> 17/09/2026 havia `~/Documentos/de1soc_sd_20260903.img` (03/09), e com ela a placa em
> serviço nem precisa ser desligada. Vá direto para "Gravar no cartão novo", mas leia
> antes a armadilha de tamanho logo abaixo.

#### A armadilha de tamanho

A imagem tem o tamanho do cartão de origem, não o dos dados. A de 03/09 tem **29,76
GiB** e o cartão novo comprado para a placa 2 tinha **29,1 GiB** — um `dd` direto
falharia com `No space left on device` **depois de meia hora gravando**, e um cartão
truncado assim não dá erro na hora: dá placa que não sobe.

Olhe a tabela de partições da imagem antes:

```bash
fdisk -l ~/Documentos/de1soc_sd_20260903.img
```

Na imagem de 03/09, a última partição termina no setor **13.096.959** — ou seja, só os
primeiros **~6,25 GiB** têm dados, e os outros 23 GiB são zeros. Copiar só essa parte
resolve o tamanho **e** corta o tempo de gravação para um quinto:

```
último setor usado × 512 ÷ 4 MiB = quantos blocos de 4M copiar
13.096.960 × 512 ÷ 4.194.304 = 1.599  →  use count=1600, com folga
```

Ajuste o `count` à sua imagem; o `1600` vale para a de 03/09.


Desligue a placa em serviço e ponha o cartão dela no leitor da estação. **Identifique o
dispositivo antes de qualquer coisa** — errar aqui apaga o disco da estação:

```bash
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,MODEL
```

O cartão aparece como um disco do tamanho dele (8/16/32 GB) com duas ou três partições,
uma delas `vfat`. Anote o nome (`/dev/sdX`, ou `/dev/mmcblk0` se o leitor for interno) e
confira uma segunda vez: o disco do sistema costuma ser `/dev/sda` ou `/dev/nvme0n1`.

Se alguma partição tiver sido montada automaticamente, desmonte:

```bash
sudo umount /dev/sdX*
```

Copie o cartão para um arquivo (leva alguns minutos; o `status=progress` mostra o
andamento):

```bash
sudo dd if=/dev/sdX of=$HOME/morphe-de1soc.img bs=4M status=progress conv=fsync
```

Devolva o cartão original à placa e ponha o **cartão novo** no leitor. Confirme o
dispositivo de novo — ele pode ter mudado de letra:

```bash
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,MODEL
```

```bash
sudo umount /dev/sdY*
```

Grave. **Este comando apaga o cartão de destino inteiro**, e não pergunta nada. O
`count` vem da conta da armadilha de tamanho, acima:

```bash
sudo dd if=$HOME/morphe-de1soc.img of=/dev/sdY bs=4M count=1600 status=progress conv=fsync
```

```bash
sync
```

Faça o kernel reler a tabela de partições — sem isso o `/dev/sdY2` do passo seguinte
ainda não existe:

```bash
sudo partprobe /dev/sdY
```

```bash
lsblk /dev/sdY
```

Tem que aparecer **três** partições. Se aparecer só uma, o `partprobe` não pegou: tire e
ponha o cartão.

O cartão novo fica com o tamanho de partições do molde. Se ele for maior, o espaço extra
fica sem uso — irrelevante para a plataforma, que não guarda nada grande na placa.

### 2.2 Trocar o MAC (o passo que não pode ser pulado)

**Medido em 17/09/2026, nas duas placas:** ambas mostram `12:34:56:78:90:12`. O conflito
não era hipótese.

O MAC vem do **U-Boot**: a variável `ethaddr` do ambiente dele, gravada no cartão, é o que
o kernel recebe. É lá que se troca — uma vez, pelo console serial, e vale para sempre
naquele cartão. Dois caminhos pelo Linux foram tentados antes e não servem: um `.link` em
`/etc/systemd/network/` (esta imagem usa ifupdown, não systemd-networkd — efeito nenhum) e
um `pre-up ip link set address` no `/etc/network/interfaces` (funciona, mas deixa o U-Boot
e o Linux discordando sobre o MAC, e não foi ele que resolveu a placa 2).

Com o cartão novo na placa nova, console serial aberto **antes** de ligar:

```bash
sudo screen /dev/ttyUSB0 115200
```

Ligue a placa e, quando aparecer `Hit any key to stop autoboot:`, aperte Enter. No prompt
`SOCFPGA_CYCLONE5 #`, escolha o MAC — `02:00:00:6D:70:NN`, com `NN` o número da placa
(o `02` marca endereço local, sem colidir com fabricante nenhum):

```
setenv ethaddr 02:00:00:6d:70:02
```

```
saveenv
```

Tem que responder `Writing to MMC(0)... done`. Aí `boot` segue o boot normal. O teste de
que a rede aceita a placa com esse MAC pode ser feito ali mesmo, sem Linux: `setenv
autoload no` e `dhcp` — em 2 s vem `DHCP client bound to address 172.16.x.y`.

O `/etc/network/interfaces` do clone é este (com a rootfs do cartão montada em
`/mnt/cartao`, ou já pela placa):

```bash
printf 'auto lo\niface lo inet loopback\n\nauto eth0\niface eth0 inet dhcp\n' > /mnt/cartao/etc/network/interfaces
```

**`auto eth0`, nunca `allow-hotplug eth0`.** Esta imagem é Ubuntu 12.04 com upstart, e o
job que levanta as interfaces no boot roda `ifup --allow auto`: uma interface
`allow-hotplug` **nunca sobe** sozinha. Foi a primeira das causas de a placa 2 não voltar
do reboot em 17/09.

**Os aliases `192.168.1.123` e `192.168.0.123` saem de propósito.** Eles são de fábrica e
vêm **idênticos em toda placa**, então duas na mesma rede colidem também por IP, não só
por MAC. Não servem para nada aqui — o laboratório é `172.16/16` por DHCP.

Dê também um hostname próprio, **nos dois arquivos** (sem a linha no `hosts`, tudo que
resolve o próprio nome espera timeout):

```bash
echo de1soc-02 > /mnt/cartao/etc/hostname
```

```bash
sed -i 's/^127.0.1.1.*/127.0.1.1\tde1soc-02/' /mnt/cartao/etc/hosts
```

### 2.3 Conferir na primeira vez que a placa nova ligar

Ponha o cartão, ligue a placa e, pelo console serial (`screen /dev/ttyUSB0 115200`) ou
por SSH depois que ela pegar IP:

```bash
ip link show eth0
```

O `link/ether` tem que ser o MAC novo. **Se não for**, o `saveenv` não pegou: volte ao
prompt do U-Boot e confira com `printenv ethaddr`.

### 2.4 O que o clone traz da placa de origem e precisa sair

Medido em 21/09/2026, na placa 2. Tudo com a rootfs montada em `/mnt/cartao`:

- **As concessões DHCP da placa de origem.** O `dhclient` da placa nova começa pedindo o
  IP antigo da outra placa (`Trying recorded lease 172.16.103.226`):

  ```bash
  sudo rm -f /mnt/cartao/var/lib/dhcp/dhclient*.leases
  ```

- **O console serial não tem shell.** O autologin do root desta imagem roda no `tty1`
  (`/etc/init/openvt.conf`), um terminal virtual que a placa não tem; na serial só sai o
  eco, e o que se digita não chega a ninguém. Um getty resolve, e sobe 3 s depois do
  kernel mesmo que o resto do boot trave:

  ```bash
  printf 'start on filesystem\nstop on runlevel [!2345]\nrespawn\nexec /sbin/getty -L 115200 ttyS0 vt102\n' | sudo tee /mnt/cartao/etc/init/ttyS0.conf
  ```

- **O servidor do Morphe só pode ir para o autostart se for de 21/09/2026 ou posterior.**
  No boot o U-Boot carrega o `soc_system.rbf` de fábrica, em que os PIOs do Morphe não
  existem; o servidor antigo escrevia neles ao subir e **travava o barramento do HPS** —
  a placa some da rede, o login na serial congela, e nada disso aparece em log nenhum. O
  servidor atual só toca a FPGA depois que o `morphe-up.sh` grava
  `/var/run/morphe-fpga-preparada` (tmpfs, some no reboot). Ver
  `C/autostart/instala-autostart.sh`.

## Passo 3 — SSH na placa nova

> **Cartão clonado de uma placa que já funciona pula este passo inteiro.** Conferido em
> 17/09/2026 na imagem de 03/09: ela já traz `PermitRootLogin yes` e `AllowUsers labpds
> root` no `sshd_config`, e a senha do root vem junto — é a mesma da placa de origem.
> Confira antes de mexer, com a rootfs montada:
>
> ```bash
> sudo grep -E 'PermitRootLogin|AllowUsers' /mnt/cartao/etc/ssh/sshd_config
> ```

Só para cartão gravado com imagem de fábrica: ela não deixa o root entrar por SSH. São
três ajustes, pelo console serial, como já foi feito na primeira placa
(`INSTALACAO.md`):

1. `passwd` — definir a senha do root;
2. `PermitRootLogin yes` no `/etc/ssh/sshd_config`;
3. acrescentar `root` ao `AllowUsers` do mesmo arquivo, que só traz `labpds`.

```bash
/etc/init.d/ssh restart
```

## Passo 4 — a chave, uma por conta que for usar a placa

Da estação, em **cada conta** que vai operar (a chave mora em
`$HOME/.ssh/id_rsa_morphe`, então não se compartilha):

```bash
cd /opt/morphe && ./morphe-up.sh --setup-ssh --board <ip da placa nova>
```

## Passo 5 — o servidor sobe sozinho no boot

Assim a placa fica visível na rede sem ninguém preparar nada, que é o ponto da v1.2:

```bash
scp -r /opt/morphe/C/autostart root@<ip>:morphe/
```

```bash
ssh root@<ip> 'cd morphe/autostart && sh instala-autostart.sh'
```

O script detecta systemd ou init.d sozinho. Validado na placa 2 em 21/09/2026: sobrevive
ao reboot **desde que o servidor seja o de 21/09 ou posterior** (seção 2.4).

## Passo 6 — pôr em serviço

```bash
cd /opt/morphe && ./morphe-up.sh --board <ip da placa nova>
```

Tem que fechar **4/4** no `morphe_ping`. Com isso a placa está pronta para a turma.

---

## O que ainda NÃO existe, e é a v1.4

Este documento põe N placas na rede. Ele **não** resolve o uso simultâneo delas, e vale
saber exatamente onde está o limite hoje:

- **O servidor atende um cliente por vez.** `morphe_server.c:1091` é um laço
  `accept` → `serve_connection` → `close`, sem `fork` nem thread. Um segundo cliente não
  toma erro: ele **espera na fila** (`listen(srv, 4)`) até o primeiro terminar. Como o
  cliente Python abre e fecha uma conexão **por operação**
  (`morphe_protocol.py:337`), duas pessoas em computadores diferentes funcionam hoje,
  intercalando operações de ~200 ms. O que não existe é a partir da quinta conexão
  simultânea, que a fila recusa, e o timeout do cliente (10 s por padrão) se a fila
  andar devagar.
- **Nada impede duas pessoas de usarem a MESMA placa** achando que cada uma tem a sua. O
  resultado sai certo — as requisições são atômicas —, mas o tempo de resposta dobra e
  ninguém sabe por quê.
- **Preparar é global, e com duas placas isso vira um problema concreto.** O estado do
  `morphe-up.sh` é um só por raiz: `.morphe-estado/tether.pid` e `.morphe-estado/placa`.
  Preparar a placa 2 **derruba o tether da placa 1** ("já existe um tether vivo;
  reprogramando e substituindo") e sobrescreve o IP que o cliente lê para abrir já
  conectado. Na prática, hoje, a estação sustenta uma placa de cada vez — não por limite
  de hardware, mas porque o estado não tem como guardar duas.
  O que **já** está pronto para duas é a escolha do cabo: com mais de um cabo JTAG o
  script se recusa a adivinhar e pede `--cable` (`morphe-up.sh:195`).
- **O cliente escolhe a placa pelo arquivo, não pela disponibilidade.** Enquanto
  `.morphe-estado/placa` guardar um endereço só, o aluno vai para a placa que o último
  `morphe-up.sh` gravou, mesmo que ela esteja ocupada e a outra livre.
- **A busca automática do cliente cobre três `/24` numa rede `/16`** (`INSTALACAO.md`
  5.2). Com mais placas, a chance de uma cair fora da varredura cresce.

A v1.4 do plano é exatamente isto: um serviço que conhece as placas, aloca uma a cada
aluno e impede o uso simultâneo. Este documento é o pré-requisito dela — sem MACs
distintos, não há o que alocar.
