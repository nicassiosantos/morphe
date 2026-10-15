# Ideia guardada: filtro em tempo real no caminho do áudio

**Estado em 15/10/2026: escrito e simulado, NÃO compilado nem testado na placa.**
Fica nesta branch (`estagio/filtro-tempo-real`) como ideia; a plataforma usa a
opção que não exige bitstream novo (gravar → filtrar no IIR da placa → tocar, na
janela Áudio).

## O que é

Um filtro IIR entre a entrada e a saída do codec: o aluno fala no microfone e
ouve filtrado na hora (latência de um quadro, 20 µs), como num equalizador.
O IIR que já existe (`iir_cascade.v`) não serve para isso: ele processa um bloco
da memória quando o servidor manda, zera os estados a cada bloco, e não está
ligado ao caminho do áudio — ligar exige mudar o hardware.

## Como foi feito

- `Quartus/filtro_audio.v`: cascata de até 16 biquads, Forma Direta I, Q15.16,
  com o mesmo `iir_biquad_mac.v` do IIR (mesmo arredondamento e saturação).
  Processa cada amostra assim que ela chega: 2 ciclos por seção, 35 de 1024
  ciclos com 16 seções. Amostra int16 → Q15.16 é `x * 2`; a volta é
  `floor(y/2 + 1/2)`, saturada.
- `Quartus/audio_buf.v`: dois bits livres do `adc_config` — `[2]` carrega
  5·n coeficientes da RAM `adc_buf` para o filtro, `[3]` faz a operação passar
  por ele. O filtro recebe a entrada do codec ou, na reprodução, a palavra que
  está tocando (ouve-se um arquivo filtrado). Na captura cada palavra vira
  `{saída filtrada, entrada}`. Platform Designer intocado.
- Servidor: suboperação `AUDIO` 3 (`FILTRO`), `n_h` = seções e 5·n coeficientes
  no payload; `n_h` = 0 desliga. O bit de filtrar vai em toda operação de áudio
  enquanto o filtro estiver ligado.

## O que foi verificado

- `Quartus/testbench/roda_tb_filtro_audio.sh`: o `filtro_audio.v` bate **bit a
  bit** com `iir_design.filtra_sos_fixo` em 6 casos (passa-baixas, passa-altas,
  passa-faixa, 16 seções, 0 seções, saturação da saída int16), 2000 amostras cada.
- `tb_audio_buf.v`: as operações de antes e o caso 6 — carga de 2 seções pela
  RAM, captura + loopback e reprodução filtradas, TUDO OK.
- O servidor compila sem avisos (`-Wall -Wextra`, zig para ARM).

## O que falta para usar

1. Compilar o bitstream (a compilação de teste no Quartus 23.1 foi interrompida
   antes do fim: folga de tempo e ocupação ainda não medidas; o bloco usa mais 15
   multiplicadores DSP).
2. Testar na placa: carregar um passa-baixas, falar no microfone e ouvir.
3. A parte do cliente (`audio.py`: carregar/desligar o filtro; janela Áudio:
   ligar o filtro, os dois espectros e |H(f)|) não foi escrita.
