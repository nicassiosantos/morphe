# Preparação automática da placa — versão 1.2

Antes, colocar a plataforma em operação eram **9 passos** na estação, seis deles
comandos de terminal, dois exigindo SSH na placa, e cinco pontos de conhecimento
tácito que faziam qualquer um deles falhar em silêncio. A contagem está em
`LINHA-DE-BASE-PASSOS.md`.

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

## No cliente

O painel de conexão agora procura a placa ao abrir, sem clique: primeiro a que o
`morphe-up.sh` acabou de preparar (as duas pontas leem o mesmo
`.morphe-estado/placa`), depois a LAN. Não acha nada em ~6 s e desiste **em silêncio**,
com uma mensagem no próprio painel — sem pop-up, porque quem vai usar o gerador de
sinais, a comparação ou o projeto de FIR não precisa de placa nenhuma.

## Estado desta versão

Escrita e verificada estaticamente: sintaxe dos três scripts conferida, módulos Python
compilados, e o caminho de autoconexão do cliente exercitado de ponta a ponta sem placa
(tenta a lembrada, cai na varredura, desiste em 6 s com a mensagem certa).

**O `morphe-up.sh` ainda não rodou contra hardware.** Os passos que dependem de Quartus,
cabo JTAG e placa — 1, 2, 3, 5, 6 e 7 — só podem ser verificados na estação do
laboratório. Até lá, a contagem de 3 passos é uma expectativa, não uma medição.
