# Sinais de teste: arquivo e processamento por blocos

Arquivos para testar a entrada por arquivo e o processamento de sinais maiores que o
hardware (1024 amostras) em todas as janelas. Gerados por
`Python/ferramentas/gera_sinais_exemplo.py`.

| arquivo | o que é |
|---|---|
| `duas_senoides_8k.wav` | x[n]: 1 s a 8 kHz (8000 amostras), tom de **300 Hz** (amplitude 0,5) + tom de **3 kHz** (amplitude 0,3) |
| `duas_senoides_8k.csv` | o mesmo sinal em texto, colunas `t` e `x`, 3000 amostras |
| `passa_baixa_1k.csv` | h[n]: passa-baixa de 67 coeficientes, corte em 1 kHz |
| `impulso_atrasado.txt` | h[n] = δ[n − 2000]: 2001 amostras, também maior que o hardware |
| `espectro_8192.npy` | X[k]: a FFT de 8192 pontos do `.wav`, complexa |
| `varredura_8k.wav` | 2 s a 8 kHz: um tom que sobe de 100 Hz a 3,5 kHz, mais um tom fixo de 1 kHz a partir de t = 1 s |

Todos os casos abaixo foram conferidos contra a placa `172.16.230.24` em 23/09/2026,
pelas próprias janelas.

## Convolução

1. **Sinal x[n]** → Tipo **Arquivo** → **Escolher arquivo…** → `duas_senoides_8k.wav` → **Gerar**
2. **Sinal h[n]** → Tipo **Arquivo** → `passa_baixa_1k.csv` → **Gerar**
3. **Convoluir na FPGA** → "Bloco k de 8"; y[n] com 8066 amostras, **só o tom de 300 Hz**

Com h[n] = `impulso_atrasado.txt`, y[n] é o próprio x deslocado 2000 amostras.

## Filtro FIR

1. **Carregar x[n] de arquivo…** (embaixo do construtor de superposição) → `duas_senoides_8k.wav`
2. **Carregar…** em Coeficientes → `passa_baixa_1k.csv`
3. **Aplicar FIR (FPGA)** → 8 blocos, 8066 amostras, o tom de 3 kHz some

**↻ Atualizar x[n]** volta para a superposição de senoides.

## Filtro IIR

1. **Carregar x[n] de arquivo…** → `duas_senoides_8k.wav`
2. **Projetar filtro IIR…** → um passa-baixa Butterworth com corte em 1 kHz e fs = 8000 Hz
3. **Aplicar IIR (FPGA)** → a barra de status diz se a placa bateu **bit a bit** com o
   modelo, quantos blocos, o aquecimento e a distância dos blocos para o filtro rodando
   sem parar, em LSB (Butterworth de ordem 4: 9 blocos, aquecimento 80, **0 LSB**)

Filtros com polos muito perto do círculo unitário (corte muito baixo) precisam de mais
aquecimento do que cabe no bloco: a janela recusa com a explicação.

## FFT

1. **Sinal x[n]** → Tipo **Arquivo** → `duas_senoides_8k.wav` → **Gerar**
2. **Calcular FFT na FPGA** → FFT de **8192 pontos** em quatro passos (8 FFTs de 1024 na
   placa); picos em 300 Hz e 3 kHz
3. **IFFT na FPGA (voltar ao tempo)** → o sinal de volta, erro ~5 × 10⁻⁵

## IFFT

1. **Abrir espectro…** → `espectro_8192.npy`
2. **Calcular IFFT na FPGA** → 8 IFFTs de 1024 na placa; SNR contra o NumPy ~92 dB

## Espectrograma (desligado no aplicativo)

A janela existe (`Python/espectrograma_window.py`) mas está **fora do menu** desde
23/09/2026. Para reativar, descomente as três linhas marcadas `ESPECTROGRAMA` em
`Python/morphe_app.py`. Com ela ligada:

1. **Sinal x[n]** → Tipo **Arquivo** → `varredura_8k.wav` → **Gerar**
2. **Calcular espectrograma na FPGA** → 31 quadros de 1024 (janela de Hann, 50 % de
   sobreposição), uma FFT da placa por quadro
3. A imagem mostra **uma rampa** (a varredura) e, a partir de 1 s, **uma linha em
   1 kHz**. As faixas verticais em 1 s e no fim são o início abrupto do tom e o corte
   do sinal, que espalham energia por todas as frequências. Embaixo, o espectro médio
   (Welch), FPGA e NumPy sobrepostos; ~93 dB entre os dois

Troque a sobreposição (0 %, 50 %, 75 %) e a janela (Retangular mostra o vazamento
espectral bem maior que a de Hann).

## Gerador de sinais

Tipo **Arquivo** → qualquer um dos arquivos acima → **Gerar**. Sinais longos aparecem
como linha, e podem ser salvos em `.mrph`.

## Teste automático

```bash
cd Python && python3 ferramentas/testa_blocos.py --placa 172.16.230.24
```
