# Morphe — ADC e FFT

Plataforma para capturar sinais pelo **ADC** de uma placa DE1-SoC e calcular a **FFT**
na FPGA da mesma placa, comparando o resultado do hardware com a referência calculada em
software. TCC de Carlos Valadão (UEFS), evoluído no estágio de Antonio Nicassio Santos
Lima no LabPS/UEFS, sob supervisão do Prof. Armando S. Sanca. Ver `NOTICE.md` e
`LICENSE` (GPL v3).

Esta é a branch `estagio/adc-fft`: só os dois blocos de hardware, a captura do ADC e a
FFT.

## Os dois blocos

| bloco | hardware | o que faz |
|---|---|---|
| **ADC** | `Quartus/adc_captura.v` + RAM `adc_buf` | captura o LTC2308 (12 bits, 8 canais, conector J15) a uma fs fixa de 1 kHz a 200 kHz; até 32768 amostras de uma vez, ou contínua em blocos, sem limite |
| **FFT** | `Quartus/fft_wrapper.v` + IP `fft_core` | FFT de 1024 pontos em Q15.8, com ponto flutuante de bloco; sinais maiores viram uma FFT de 1024·M pontos em quatro passos (M FFTs na placa, ligadas no PC) |

No aplicativo:

| janela | o que faz |
|---|---|
| **Gerador de Sinais** | gera ou abre de arquivo (`.csv`, `.txt`, `.npy`, `.wav`) um sinal e o salva em `.mrph` |
| **Aquisição (ADC da placa)** | voltímetro, captura única ou contínua, medidas de uma senoide (frequência, SINAD, ENOB), gravação em arquivo |
| **FFT** | manda um sinal gerado, de arquivo ou a última captura do ADC à FFT da placa; magnitude e fase |
| **Comparador** | abre o `.mrph` salvo pela FFT e compara FPGA × NumPy (magnitude, real, imaginária) |

## Usar

Na estação do laboratório, com a placa ligada ao USB-Blaster:

```bash
./morphe-up.sh
```

```bash
cd Python && python3 morphe_app.py
```

O primeiro prepara a placa (programa a FPGA e sobe o servidor) e termina com o
`morphe_ping` 4/4; o segundo abre o aplicativo, já conectado. O passo a passo completo,
inclusive a instalação para uma turma inteira, está em `PREPARACAO.md`.

O servidor atende um cliente por vez: dois alunos na mesma placa não recebem erro, um
espera o outro. Com várias placas no `placas.conf`, o aplicativo escolhe a mais livre.

Uma placa também pode ficar ao lado de qualquer computador, em qualquer ponto de rede:
ao abrir, o aplicativo grava a FPGA das placas ligadas ao USB daquele computador, e cada
placa reconhece o próprio bitstream e é achada pelo nome. Ver `docs/NOVA-PLACA.md`,
"Trocar a placa de computador ou de ponto de rede".

## O que é cada pasta

| pasta | o que é |
|---|---|
| `Python/` | o aplicativo (`morphe_app.py` e as janelas) e os módulos que ele usa: protocolo, captura do ADC, FFT longa, núcleo de DSP |
| `C/` | o servidor que roda no processador ARM da placa e fala com a FPGA (`morphe_server.c`), mais o `autostart/` que o sobe no boot |
| `Quartus/` | o projeto de hardware da FPGA e o bitstream; o mapa da pasta está em `Quartus/README.md` |
| `Python/ferramentas/` | testes contra a placa: `testa_adc.py` (ADC com multímetro e gerador), `testa_blocos.py` (FFT longa e leitura de arquivos), `testa_porta_estado.py`, `estado_placas.py`. Rodar de dentro de `Python/` |
| `exemplos/` | um bundle `.mrph` de FFT e sinais de teste em `exemplos/sinais/` |
| `docs/` | documentação técnica (abaixo) |
| raiz | `morphe-up.sh` (prepara a placa), `deploy.sh` (envia o servidor), `instala-quartus.sh` (Quartus 20.1 para todas as contas de um computador), `instala-morphe.sh` (o aplicativo em `/opt/morphe`), `atualizar.sh` e `atualizar-lab.sh` (atualizam as instalações), `placas.conf` (as placas do laboratório) |

## Documentação

| arquivo | assunto |
|---|---|
| `PREPARACAO.md` | preparar a placa, instalar para uma turma, Quartus nos computadores |
| `docs/ADC.md` | o ADC da placa: pinagem do J15, faixas, como a captura funciona, o que foi medido, como ligar um microfone |
| `docs/PRECISAO-NUMERICA.md` | o formato Q15.8 da FFT, a normalização, o teto de ~92 dB e o ENOB do ADC |
| `docs/COMPILAR.md` | como gerar o bitstream a partir do repositório, e o mapa de endereços |
| `docs/NOVA-PLACA.md` | incorporar uma placa nova ao laboratório |
| `docs/de1-soc/` | manuais da placa e folha de dados do LTC2308 |

## Estado

O código desta branch (Verilog, Platform Designer, servidor e aplicativo) tem só o ADC
e a FFT. O servidor foi compilado para ARM sem avisos, e o aplicativo e o `morphe_ping`
foram testados contra um servidor falso. **Falta na estação:** gerar o sistema,
compilar o bitstream novo, gravar e testar na placa — ver `docs/COMPILAR.md`. Até lá, o
`.sof` versionado é o da versão completa, que também serve: o ADC e a FFT estão nos
mesmos endereços.

Depois da compilação, `./gera_proveniencia.sh` cria o `PROVENIENCIA.sha256`, e
`sha256sum -c PROVENIENCIA.sha256` passa a conferir que as fontes e o bitstream de um
clone são os validados na placa.
