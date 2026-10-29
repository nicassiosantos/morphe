# Passagem: roteiro do somador na versão adc-fft

Instruções para o Claude Code que vai trabalhar na estação do laboratório
(LABPS-47723, conta `coordenador`). Escrito em 29/10/2026 a partir do
Windows do estagiário, onde o roteiro foi feito. Leia tudo antes de começar e
explique ao Antonio o que entendeu; só comece depois que ele confirmar.

## O objetivo

Deixar pronto, nesta branch (`estagio/modulo-soma-adc-fft`), o roteiro que
ensina o aluno a criar um módulo novo (um somador saturado Q15.16) e
integrá-lo à plataforma Morphe, **a partir da versão adc-fft** (só ADC e FFT).

O jeito de fazer isso: **seguir o roteiro do PDF passo a passo, como um aluno
faria**, nesta estação, e corrigir o texto onde ele não bater com o que
acontece de verdade.

## O que já existe

- `docs/roteiro-modulo/` (trazido para esta branch de `origin/estagio/modulo-soma`,
  commit 78b6846): `main.tex`, `roteiro-modulo.pdf` (33 p.), `trechos.txt`
  (os trechos de código do PDF, para copiar sem erro de colagem) e `prints/`.
- O **gabarito** (código pronto) está em `origin/estagio/modulo-soma`:
  `Quartus/soma_core.v`, `Quartus/soma.v`, `Quartus/testbench/tb_soma_core.v`,
  os 3 PIOs de teste no `soc_system.qsys` (`soma_teste_a/b/y`), mudanças no
  `ghrd_top.v` e no `.qsf`, `C/devmem.c`, `C/Makefile`, servidor (opcode da
  soma), `morphe-up.sh`, e a janela Soma no app (Python).
- O roteiro tem duas partes: **A** (conta Q15.16, `soma_core`, 3 PIOs, topo,
  compilar + morphe-up, teste sozinho pela serial com `devmem`) e **B**
  (integração: `soma.v` completo, servidor, Python, janela Soma no app).
- Ele já foi seguido uma vez no laboratório (06/10) e funcionou, mas naquela
  versão.

## Por que provavelmente não bate mais

1. O roteiro e o gabarito foram feitos em cima da **principal antiga**
   (`estagio/v1.1-1024pontos`, 978c4bb), que tinha conv1d, FIR e IIR. A
   adc-fft tirou do Qsys as memórias e PIOs desses blocos, o `ghrd_top.v` só
   tem `adc_captura` + `fft_wrapper`, e o servidor só tem FFT, ADC,
   ADC_CONTINUO e PING. Endereços, componentes, trechos do topo, opcodes e o
   `git clone -b` do roteiro precisam ser conferidos contra esta branch.
2. O app da adc-fft só tem Gerador, Aquisição, FFT e Comparador.
3. O `morphe-up.sh` mudou desde então (assinatura MRPH, `--board`, sem codec,
   placa deduzida). O app grava a FPGA ao abrir.
4. Os prints foram tirados no **Quartus 23.1 do Windows**, numa cópia do
   projeto. A estação tem o **20.1**: se alguma tela ou menu for diferente,
   o texto (e o print, se valer a pena) muda.
5. Comandos e caminhos foram testados no Windows/WSL: confira cada um aqui.
6. O gabarito vem de `origin/estagio/modulo-soma` (que é da versão antiga).
   Para a adc-fft vai precisar de um gabarito novo; **pergunte ao Antonio**
   o nome da branch e se ela vai para o GitHub (aluno vê).

Leia também: `README.md`, `docs/COMPILAR.md` (qsys-generate 20.1,
gen_hps_header, quartus_sh, gera_proveniencia), `docs/NOVA-PLACA.md`.

## Como trabalhar

- `~/morphe-adc-fft` é o clone do autor: é aqui que o roteiro é editado.
- Siga o roteiro como aluno num clone separado, como ele manda
  (`~/meu-modulo`, a partir de `estagio/adc-fft`).
- A placa está no USB desta estação. Descubra qual é com `jtagconfig` e
  `ls /dev/ttyUSB*`; não assuma número de cabo nem de porta.
- Anote cada divergência (passo, o que o texto diz, o que aconteceu) e
  corrija o `main.tex`. Depois regere o PDF e o `trechos.txt`.

## Regras dos roteiros (do Antonio)

- **Código completo** no PDF. Nada resumido com "...".
- **Nenhum número fixo** de cabo, porta ou IP: o aluno descobre o dele.
- Prático: um diagrama por etapa, caixas **Faça** / **Confira**, e o
  **porquê** de cada passo.
- O módulo é criado e **testado sozinho pela serial ANTES** de integrar.
- Comandos para colar: **um por bloco, numa linha só, sem barra invertida**.
  **Evite `$`**: no terminal dele, o trecho entre dois `$` some na colagem
  (vira fórmula). Use crases, `xargs`, ou ponha o comando num script.
- Mensagens e texto em português.

## Tudo nesta estação é temporário

- Não instale nada no sistema: **sem `sudo apt`**, sem `pip install` fora
  de um venv. O que precisar (por exemplo `tectonic` para o PDF) vai numa
  pasta só para isso (`~/tmp-roteiro/`). Mantenha a lista em
  `~/tmp-roteiro/INSTALADO.txt`.
- Não mexa em `~/.bashrc`, `~/.profile`, `git config --global`, `/opt/morphe`
  (o app dos alunos sai de lá) nem nos clones de outras pessoas.
- Identidade do git: só `git config --local` neste clone.
- **No fim:** `./morphe-up.sh --down` no `~/meu-modulo`, depois
  `cd /opt/morphe` e `./morphe-up.sh` para a placa voltar ao normal; apagar
  `~/meu-modulo` (só DEPOIS do `--down`) e `~/tmp-roteiro/`; mostrar ao
  Antonio o que foi apagado. Ele sai da conta e faz `/logout` no Claude.

## Pergunte antes de

- gravar a FPGA ou mandar servidor para a placa;
- commit;
- apagar qualquer coisa fora de `~/tmp-roteiro/`.

**Push:** não há credencial na estação. Faça commits locais; o Antonio decide
se faz o push com um token de 7 dias ou se traz para o Windows.
